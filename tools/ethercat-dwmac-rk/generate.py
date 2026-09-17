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


def rewrite_includes(text: str, kv: str) -> str:
    return re.sub(
        r'#include "([A-Za-z0-9_\-]+)\.h"',
        lambda m: f'#include "{m.group(1)}-{kv}-ethercat.h"',
        text,
    )


def ethercat_variant(text: str, kv: str, is_driver: bool) -> str:
    text = rewrite_includes(text, kv)
    text = text.replace("stmmac_dvr_probe(", "stmmac_ec_dvr_probe(")
    text = text.replace("stmmac_dvr_remove(", "stmmac_ec_dvr_remove(")
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
    return text


def generate(ksrc: pathlib.Path, out: pathlib.Path, kv: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in KERNEL_FILES:
        stem, ext = name.rsplit(".", 1)
        src = ksrc / name
        shutil.copy(src, out / f"{stem}-{kv}-orig.{ext}")
        body = src.read_text(encoding="utf-8")
        variant = ethercat_variant(body, kv, is_driver=(name == "dwmac-rk.c"))
        (out / f"{stem}-{kv}-ethercat.{ext}").write_text(
            variant, encoding="utf-8"
        )


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

    # 3. No call may still reach the non-EtherCAT probe path.
    for path in sorted(out.glob("*-ethercat.c")):
        body = path.read_text(encoding="utf-8")
        for symbol in ("stmmac_dvr_probe(", "stmmac_dvr_remove("):
            if symbol in body.replace("stmmac_ec_dvr", "X"):
                failures.append(f"{path.name}: unconverted {symbol}")

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
    args = ap.parse_args()

    ksrc, out = args.work / "upstream", args.work / "devices-stmmac"
    try:
        fetch(ksrc, args.kernel_tag)
        generate(ksrc, out, args.kernel_version)
        verify(ksrc, out, args.igh, args.kernel_version)
    except PortError as e:
        print(f"ec_dwmac: {e}", file=sys.stderr)
        return 1
    print(f"     copy {out}/* into the IgH tree at devices/stmmac/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
