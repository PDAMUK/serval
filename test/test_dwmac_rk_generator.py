"""The CB2's native NIC driver is generated, and has to load where it runs.

`tools/ethercat-dwmac-rk/generate.py` ports `stmmac_platform` and `dwmac-rk`
by the transform IgH applies to its own stmmac bindings. It was derived from
one pair, `stmmac_pci`, which takes its driver name from a header macro and
exports nothing, so two steps of the recipe were invisible:

- IgH deletes every `EXPORT_SYMBOL` from its copies. The generated
  `stmmac_platform` kept six, under the names the in-tree `stmmac_platform`
  exports, and the kernel refuses a module exporting a name a loaded module
  owns. On the image Stage B builds the stock driver claims the NIC at boot,
  so that module is loaded.
- IgH prefixes its drivers' names with `ec_`. The generated driver registered
  as `rk_gmac-dwmac`, which the in-tree driver already holds, and the handover
  script's `driver_override` named a driver that did not exist.
"""

import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dwmac_rk_generate", ROOT / "tools" / "ethercat-dwmac-rk" / "generate.py"
)
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)

KV = "6.12"

PLATFORM_C = """\
int stmmac_pltfr_probe(struct platform_device *pdev)
{
\treturn stmmac_dvr_probe(&pdev->dev, NULL, NULL);
}
EXPORT_SYMBOL_GPL(stmmac_pltfr_probe);

const struct dev_pm_ops stmmac_pltfr_pm_ops;
EXPORT_SYMBOL_GPL(stmmac_pltfr_pm_ops);

MODULE_DESCRIPTION("STMMAC 10/100/1000 Ethernet platform support");
"""

DWMAC_RK_C = """\
static const struct of_device_id rk_gmac_dwmac_match[] = {
\t{ .compatible = "rockchip,rk3568-gmac" },
\t{ }
};
MODULE_DEVICE_TABLE(of, rk_gmac_dwmac_match);

static struct platform_driver rk_gmac_dwmac_driver = {
\t.probe  = rk_gmac_probe,
\t.driver = {
\t\t.name           = "rk_gmac-dwmac",
\t\t.of_match_table = rk_gmac_dwmac_match,
\t},
};
module_platform_driver(rk_gmac_dwmac_driver);

MODULE_DESCRIPTION("Rockchip RK3288 DWMAC specific glue layer");
"""


def variant(text, is_driver):
    return gen.ethercat_variant(text, KV, is_driver=is_driver, renames={})


def test_the_generated_binding_exports_nothing():
    out = variant(PLATFORM_C, is_driver=False)
    assert "EXPORT_SYMBOL" not in out
    assert "int stmmac_pltfr_probe(" in out


def test_the_generated_driver_registers_under_its_own_name():
    out = variant(DWMAC_RK_C, is_driver=True)
    assert '.name           = "ec_rk_gmac-dwmac",' in out
    assert '"rk_gmac-dwmac"' not in out


def generated_tree(tmp_path, platform_c, dwmac_rk_c):
    ksrc, out = tmp_path / "upstream", tmp_path / "out"
    ksrc.mkdir()
    sources = {
        "stmmac_platform.c": platform_c,
        "stmmac_platform.h": "int stmmac_pltfr_probe(void *pdev);\n",
        "dwmac-rk.c": dwmac_rk_c,
    }
    for name, text in sources.items():
        (ksrc / name).write_text(text, encoding="utf-8")
    gen.generate(ksrc, out, KV, renames={})
    return ksrc, out


def test_verify_accepts_what_generate_produces(tmp_path):
    ksrc, out = generated_tree(tmp_path, PLATFORM_C, DWMAC_RK_C)
    gen.verify(ksrc, out, tmp_path / "no-igh", KV)


@pytest.mark.parametrize(
    "tamper,complaint",
    [
        (
            lambda out: (out / f"stmmac_platform-{KV}-ethercat.c").write_text(
                "EXPORT_SYMBOL_GPL(stmmac_pltfr_probe);\n", encoding="utf-8"
            ),
            "still exports",
        ),
        (
            lambda out: (out / f"dwmac-rk-{KV}-ethercat.c").write_text(
                (out / f"dwmac-rk-{KV}-ethercat.c")
                .read_text(encoding="utf-8")
                .replace('"ec_rk_gmac-dwmac"', '"rk_gmac-dwmac"'),
                encoding="utf-8",
            ),
            "not renamed",
        ),
    ],
    ids=["export", "driver-name"],
)
def test_verify_refuses_a_binding_the_kernel_would_refuse(
    tmp_path, capsys, tamper, complaint
):
    ksrc, out = generated_tree(tmp_path, PLATFORM_C, DWMAC_RK_C)
    tamper(out)
    with pytest.raises(gen.PortError):
        gen.verify(ksrc, out, tmp_path / "no-igh", KV)
    assert complaint in capsys.readouterr().err


HANDOVER_DOCS = [
    ROOT / "docs" / "rewrite" / "markforged-cb2-complete-build.md",
    ROOT / "docs" / "rewrite" / "ethercat-host-cb2-rk3566.md",
]


def handover_script(doc):
    text = doc.read_text(encoding="utf-8")
    return re.search(
        r"```bash\n(#!/bin/bash\n# Hand the RK3566 GMAC.*?)```", text, re.S
    )[1]


@pytest.mark.parametrize("doc", HANDOVER_DOCS, ids=lambda p: p.stem)
def test_the_handover_overrides_to_the_name_the_generator_registers(doc):
    script = handover_script(doc)
    overrides = re.findall(
        r"echo (\S+) > \"\$SYS/devices/\$DEV/driver_override\"", script
    )
    assert overrides == [gen.EC_DRIVER_NAME]


@pytest.mark.parametrize("doc", HANDOVER_DOCS, ids=lambda p: p.stem)
def test_the_handover_leaves_module_loading_to_the_init_script(doc):
    """`ethercatctl start` loads `ec_master` with `main_devices`, then swaps
    `dwmac-rk` for `ec_dwmac-rk`. A `modprobe ec_dwmac-rk` ahead of it pulls
    `ec_master` in with no `main_devices`, and the init script's own load is
    then a no-op — a master with no device."""
    script = handover_script(doc)
    assert "modprobe" not in script
    assert script.rstrip().endswith("/opt/etherlab/etc/init.d/ethercat start")


@pytest.mark.parametrize("doc", HANDOVER_DOCS, ids=lambda p: p.stem)
def test_the_module_path_it_checks_is_where_igh_installs_it(doc):
    """IgH's `modules_install` puts modules under `--with-module-dir`, default
    `ethercat`, keeping the source layout — so the binding `generate.py` wires
    into `devices/stmmac/` lands at `ethercat/devices/stmmac/ec_dwmac-rk.ko`.
    Both pages checked `extra/ec_dwmac-rk.ko`, which is where an out-of-tree
    module goes without that override: the check failed on a correct install,
    and the vermagic comparison after it never ran."""
    paths = re.findall(
        r"(/lib/modules/[^\n`]*?ec_dwmac-rk\.ko)", doc.read_text()
    )
    assert paths
    assert "\tec_dwmac-rk-objs" in gen.KBUILD_ADD.replace("\\t", "\t")
    for path in paths:
        assert path == (
            "/lib/modules/$(uname -r)/ethercat/devices/stmmac/ec_dwmac-rk.ko"
        ), path
