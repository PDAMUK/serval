#!/usr/bin/env python3
"""Generate the ec_dwmac Rockchip binding for the IgH EtherCAT master.

IgH stable-1.6 already ships the whole stmmac core EtherCAT-ified under
devices/stmmac/ -- stmmac_main carries 62 ecdev hook sites, and the HW layers
(dwmac4, dwmac1000, dwxgmac2, hwif, descs) are all present. What it does not
ship is a binding for Rockchip's platform GMAC, so an RK3566/RK3588 board has
no native driver and falls back to ec_generic.

This produces that binding. Two upstream files are missing from the IgH tree:

    stmmac_platform.{c,h}   the generic DT/platform binding dwmac-rk builds on
    dwmac-rk.c              the Rockchip glue itself

Both are ported by the same mechanical transform IgH applies to its own
bindings, which carry no EtherCAT logic of their own -- every hook lives in
stmmac_main. Diffing stmmac_pci-6.12-orig.c against its -ethercat twin gives
the whole recipe, and it is what this script implements:

  1. local includes  ->  their versioned -ethercat form
  2. stmmac_dvr_probe/remove  ->  stmmac_ec_dvr_probe/remove
  3. MODULE_DEVICE_TABLE commented out, so the EtherCAT module never
     auto-binds and race the stock driver for the device
  4. module_*_driver() replaced by an explicit init/exit pair bracketing
     registration with stmmac_init()/stmmac_exit(), because the patched core
     no longer registers itself
  5. MODULE_DESCRIPTION marked EtherCAT-enabled
  6. every EXPORT_SYMBOL deleted, as IgH deletes all six from its
     stmmac_main copy: each ec_ module links its own copy of the core, and
     the kernel refuses to load a module exporting a name that a loaded
     module already exports -- the in-tree stmmac_platform is loaded on any
     board whose NIC the stock driver claimed at boot
  7. the platform driver's name prefixed ec_, as IgH does for its own
     (intel-eth-pci becomes ec_intel-eth-pci): the kernel refuses to
     register a second driver under a name already on the bus, and the
     handover's driver_override names this one

Every step is verified after generation; a failed check aborts rather than
emitting a file that merely looks right.
"""

import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys

KERNEL_FILES = ("stmmac_platform.c", "stmmac_platform.h", "dwmac-rk.c")
DRIVER_NAME = "rk_gmac-dwmac"
EC_DRIVER_NAME = "ec_" + DRIVER_NAME
EXPORT = re.compile(r"^EXPORT_SYMBOL(?:_GPL)?\(\w+\);\n", re.M)
UPSTREAM = (
    "https://raw.githubusercontent.com/torvalds/linux/v{tag}"
    "/drivers/net/ethernet/stmicro/stmmac/{name}"
)

# The init/exit bracket, mirroring stmmac_pci's exactly.
MODULE_BRACKET = """static int __init rk_gmac_dwmac_init(void)
{
\tint ret;
\tret = stmmac_init();
\tif (ret)
\t\treturn ret;
\tret = platform_driver_register(&rk_gmac_dwmac_driver);
\tif (ret) {
\t\tstmmac_exit();
\t}
\treturn ret;
}

static void __exit rk_gmac_dwmac_exit(void)
{
\tplatform_driver_unregister(&rk_gmac_dwmac_driver);
\tstmmac_exit();
}

module_init(rk_gmac_dwmac_init);
module_exit(rk_gmac_dwmac_exit);"""


class PortError(RuntimeError):
    pass


def fetch(dest: pathlib.Path, tag: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in KERNEL_FILES:
        target = dest / name
        if target.exists():
            continue
        url = UPSTREAM.format(tag=tag, name=name)
        rc = subprocess.run(
            ["curl", "-sSL", "--retry", "3", "-o", str(target), url]
        ).returncode
        if rc != 0 or not target.exists() or target.stat().st_size == 0:
            raise PortError(f"could not fetch {url}")


def ec_renames(igh: pathlib.Path, kv: str) -> dict:
    """Symbols IgH re-exports under an ec_ prefix, read from its own header.

    The patched core cannot keep the in-tree stmmac symbol names or the two
    modules would clash, so IgH renames what it exports. It uses two
    conventions -- stmmac_dvr_probe becomes stmmac_ec_dvr_probe while
    stmmac_bus_clks_config becomes ec_stmmac_bus_clks_config -- so the map is
    derived here rather than assumed, and picks up anything a later IgH
    release renames as well.
    """
    ec_h = igh / f"stmmac-{kv}-ethercat.h"
    orig_h = igh / f"stmmac-{kv}-orig.h"
    if not (ec_h.exists() and orig_h.exists()):
        raise PortError(f"cannot read the rename map: {ec_h.name} not found")
    ec_text = ec_h.read_text(encoding="utf-8")
    orig_text = orig_h.read_text(encoding="utf-8")
    renames = {}
    for base in sorted(set(re.findall(r"\bec_(\w+)", ec_text))):
        if re.search(rf"\b{re.escape(base)}\b", orig_text):
            renames[base] = f"ec_{base}"
    return renames


def apply_renames(text: str, renames: dict) -> str:
    """Rename call sites only.

    Requiring a following '(' keeps string literals intact. That matters:
    dwmac-rk asks for its clock by the name "stmmaceth", which is a
    device-tree string and not a symbol. Renaming it would still compile and
    then fail to find the clock at probe time.
    """
    for old, new in renames.items():
        text = re.sub(rf"\b{re.escape(old)}\s*\(", f"{new}(", text)
    return text


def rewrite_includes(text: str, kv: str) -> str:
    return re.sub(
        r'#include "([A-Za-z0-9_\-]+)\.h"',
        lambda m: f'#include "{m.group(1)}-{kv}-ethercat.h"',
        text,
    )


def ethercat_variant(text: str, kv: str, is_driver: bool, renames: dict) -> str:
    text = rewrite_includes(text, kv)
    text = text.replace("stmmac_dvr_probe(", "stmmac_ec_dvr_probe(")
    text = text.replace("stmmac_dvr_remove(", "stmmac_ec_dvr_remove(")
    text = apply_renames(text, renames)
    text = EXPORT.sub("", text)
    text = re.sub(
        r'(MODULE_DESCRIPTION\("[^"]+)"',
        lambda m: m.group(1) + ' (EtherCAT-enabled)"',
        text,
    )
    if is_driver:
        table = "MODULE_DEVICE_TABLE(of, rk_gmac_dwmac_match);"
        if text.count(table) != 1:
            raise PortError("MODULE_DEVICE_TABLE anchor not found exactly once")
        text = text.replace(table, "//" + table, 1)
        driver = "module_platform_driver(rk_gmac_dwmac_driver);"
        if text.count(driver) != 1:
            raise PortError(
                "module_platform_driver anchor not found exactly once"
            )
        text = text.replace(driver, MODULE_BRACKET, 1)
        name = f'.name           = "{DRIVER_NAME}",'
        if text.count(name) != 1:
            raise PortError(
                "platform driver .name anchor not found exactly once"
            )
        text = text.replace(name, f'.name           = "{EC_DRIVER_NAME}",', 1)
    return text


def generate(
    ksrc: pathlib.Path, out: pathlib.Path, kv: str, renames: dict
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in KERNEL_FILES:
        stem, ext = name.rsplit(".", 1)
        src = ksrc / name
        shutil.copy(src, out / f"{stem}-{kv}-orig.{ext}")
        body = src.read_text(encoding="utf-8")
        variant = ethercat_variant(
            body, kv, is_driver=(name == "dwmac-rk.c"), renames=renames
        )
        (out / f"{stem}-{kv}-ethercat.{ext}").write_text(
            variant, encoding="utf-8"
        )


CONFIGURE_HOOK = """AM_CONDITIONAL(ENABLE_DWMACINTEL, test "x$enabledwmacintel" = "x1")
AC_SUBST(ENABLE_DWMACINTEL, [$enabledwmacintel])
"""

CONFIGURE_ADD = """
AC_ARG_ENABLE([dwmac-rk],
    AS_HELP_STRING([--enable-dwmac-rk],
                   [Build dwmac rockchip driver [default=no]]),
    [
        case "${enableval}" in
            yes) enabledwmacrk=1
                 enablestmmac=1
                ;;
            no) enabledwmacrk=0
                ;;
            *) AC_MSG_ERROR([Invalid value for --enable-dwmac-rk])
                ;;
        esac
    ],
    [enabledwmacrk=0]
)

AM_CONDITIONAL(ENABLE_DWMACRK, test "x$enabledwmacrk" = "x1")
AC_SUBST(ENABLE_DWMACRK, [$enabledwmacrk])
"""

KBUILD_HOOK = """ifeq (@ENABLE_STMMACPCI@,1)
\tobj-m += ec_stmmac-pci.o"""

KBUILD_ADD = """ifeq (@ENABLE_DWMACRK@,1)
\tobj-m += ec_dwmac-rk.o
\tec_dwmac-rk-objs := \\
\t\t$(EC_STMMAC_OBJS) \\
\t\tstmmac_platform-@KERNEL_STMMAC@-ethercat.o \\
\t\tdwmac-rk-@KERNEL_STMMAC@-ethercat.o
endif

"""


def wire(igh_root: pathlib.Path, out: pathlib.Path, kv: str) -> None:
    """Copy the generated pair set in and wire it into IgH's build system.

    Idempotent: a tree already carrying the binding is left alone, so this can
    be re-run after regenerating for a new kernel version.
    """
    dest = igh_root / "devices" / "stmmac"
    if not dest.is_dir():
        raise PortError(f"{dest} is not an IgH devices/stmmac directory")
    for f in sorted(out.iterdir()):
        shutil.copy(f, dest / f.name)

    configure = igh_root / "configure.ac"
    text = configure.read_text(encoding="utf-8")
    if "ENABLE_DWMACRK" not in text:
        if text.count(CONFIGURE_HOOK) != 1:
            raise PortError("configure.ac: dwmac-intel anchor not found once")
        configure.write_text(
            text.replace(CONFIGURE_HOOK, CONFIGURE_HOOK + CONFIGURE_ADD, 1),
            encoding="utf-8",
        )

    kbuild = dest / "Kbuild.in"
    text = kbuild.read_text(encoding="utf-8")
    if "ec_dwmac-rk" not in text:
        hook, add = (
            KBUILD_HOOK.replace("\\t", "\t"),
            KBUILD_ADD.replace("\\t", "\t"),
        )
        if text.count(hook) != 1:
            raise PortError("Kbuild.in: stmmac-pci anchor not found once")
        kbuild.write_text(text.replace(hook, add + hook, 1), encoding="utf-8")

    am = dest / "Makefile.am"
    text = am.read_text(encoding="utf-8")
    if f"dwmac-rk-{kv}-ethercat.c" not in text:
        names = sorted(f.name for f in out.iterdir())
        block = "".join(f"\t{n} \\\n" for n in names)
        anchor = "EXTRA_DIST = \\\n"
        if text.count(anchor) != 1:
            raise PortError("Makefile.am: EXTRA_DIST anchor not found once")
        am.write_text(text.replace(anchor, anchor + block, 1), encoding="utf-8")
    print(f"     wired into {igh_root}")


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(
    ksrc: pathlib.Path, out: pathlib.Path, igh: pathlib.Path, kv: str
) -> None:
    failures = []

    # 1. The -orig files must reproduce upstream byte for byte, or the pair is
    #    not a faithful baseline and every later diff is meaningless.
    for name in KERNEL_FILES:
        stem, ext = name.rsplit(".", 1)
        if digest(ksrc / name) != digest(out / f"{stem}-{kv}-orig.{ext}"):
            failures.append(f"-orig for {name} does not match upstream")

    # 2. Every local include must resolve, either to a file IgH already ships
    #    or to one generated here. This is what catches a missing dependency.
    search = [out]
    if igh.is_dir():
        search.append(igh)
    for path in sorted(out.glob("*-ethercat.*")):
        for inc in re.findall(
            r'#include "([^"]+)"', path.read_text(encoding="utf-8")
        ):
            if not any((d / inc).exists() for d in search):
                failures.append(f"{path.name}: unresolved include {inc}")

    # 3. No call may still reach an in-tree symbol the patched core renamed.
    #    A survivor either links against the stock stmmac or does not link.
    renames = ec_renames(igh, kv) if igh.is_dir() else {}
    for path in sorted(out.glob("*-ethercat.c")):
        body = path.read_text(encoding="utf-8")
        for symbol in ("stmmac_dvr_probe(", "stmmac_dvr_remove("):
            if symbol in body.replace("stmmac_ec_dvr", "X"):
                failures.append(f"{path.name}: unconverted {symbol}")
        for old in renames:
            if re.search(rf"(?<!ec_)\b{re.escape(old)}\s*\(", body):
                failures.append(f"{path.name}: unconverted call to {old}()")

    # 4. The driver must not auto-bind, and must bracket registration.
    drv = (out / f"dwmac-rk-{kv}-ethercat.c").read_text(encoding="utf-8")
    for needed in (
        "//MODULE_DEVICE_TABLE(of, rk_gmac_dwmac_match);",
        "module_init(rk_gmac_dwmac_init);",
        "module_exit(rk_gmac_dwmac_exit);",
        "stmmac_init();",
        "stmmac_exit();",
    ):
        if needed not in drv:
            failures.append(f"dwmac-rk: missing {needed!r}")
    if "module_platform_driver(" in drv:
        failures.append("dwmac-rk: module_platform_driver() still present")
    if f'"{EC_DRIVER_NAME}"' not in drv or f'"{DRIVER_NAME}"' in drv:
        failures.append(
            f"dwmac-rk: platform driver not renamed to {EC_DRIVER_NAME}"
        )

    # 5. Nothing exported: the in-tree stmmac_platform owns these names.
    for path in sorted(out.glob("*-ethercat.*")):
        for m in EXPORT.finditer(path.read_text(encoding="utf-8")):
            failures.append(f"{path.name}: still exports {m.group(0).strip()}")

    if failures:
        for f in failures:
            print(f"FAIL {f}", file=sys.stderr)
        raise PortError(f"{len(failures)} verification failure(s)")
    print(f"OK   {len(KERNEL_FILES)} file pairs generated and verified")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--kernel-version",
        default="6.12",
        help="IgH file-set version to target (6.1, 6.4, 6.12)",
    )
    ap.add_argument(
        "--kernel-tag",
        default="6.12",
        help="upstream Linux tag to take the -orig files from",
    )
    ap.add_argument(
        "--igh",
        type=pathlib.Path,
        default=pathlib.Path("."),
        help="IgH devices/stmmac directory, for the include check",
    )
    ap.add_argument("--work", type=pathlib.Path, default=pathlib.Path("build"))
    ap.add_argument(
        "--install",
        type=pathlib.Path,
        default=None,
        help="IgH source root to copy into and wire up",
    )
    args = ap.parse_args()

    ksrc, out = args.work / "upstream", args.work / "devices-stmmac"
    try:
        fetch(ksrc, args.kernel_tag)
        renames = ec_renames(args.igh, args.kernel_version)
        print(f"     rename map from IgH header: {len(renames)} symbol(s)")
        generate(ksrc, out, args.kernel_version, renames)
        verify(ksrc, out, args.igh, args.kernel_version)
    except PortError as e:
        print(f"ec_dwmac: {e}", file=sys.stderr)
        return 1
    if args.install is not None:
        try:
            wire(args.install, out, args.kernel_version)
        except PortError as e:
            print(f"ec_dwmac: {e}", file=sys.stderr)
            return 1
        print("     configure with --enable-dwmac-rk after ./bootstrap")
    else:
        print(f"     copy {out}/* into the IgH tree at devices/stmmac/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
