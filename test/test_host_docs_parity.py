"""The two EtherCAT host pages must cover the same ground.

One is exercised on the bench, the other has never been run, and the gap showed:
the CB2 page was missing the udev rule for /dev/EtherCAT0, the systemd unit, the
NetworkManager override that Armbian in particular needs, and its own See also.
Each gap was a first-boot failure on the path nobody has walked.

They are different SoCs, so their content differs. What must not differ is
whether a step exists at all.
"""

import pathlib

import pytest

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs" / "rewrite"
PI5 = DOCS / "ethercat-igh-macb-install.md"
CB2 = DOCS / "ethercat-host-cb2-rk3566.md"

# Each entry is a thing both pages must tell the reader to do, and a token that
# shows they did. Kept as substrings rather than prose so a rewording does not
# fail this, only a removal.
SHARED_STEPS = {
    "udev rule for /dev/EtherCAT0": "99-ethercat.rules",
    "the device node the endpoint opens": "/dev/EtherCAT0",
    "a boot service that hands the NIC over": "Before=klipper.service",
    "NetworkManager told to leave the NIC alone": "unmanaged-devices",
    "the master's device and module settings": "MASTER0_DEVICE",
    "lowercase MAC, which is matched as a string": "lowercase",
    "RT capabilities for the endpoint": "AmbientCapabilities",
    "building the endpoint binary": "ethercat-endpoint-hw",
    "the stub for the drive-off dry run": "ethercat-stub",
    "an isolated core for the DC loop": "isolcpus",
    "where to go next": "## See also",
}


@pytest.mark.parametrize(
    "what,token", sorted(SHARED_STEPS.items()), ids=lambda v: v[:38]
)
@pytest.mark.parametrize("doc", [PI5, CB2], ids=lambda p: p.stem)
def test_both_host_paths_cover_the_same_step(doc, what, token):
    assert token in doc.read_text(encoding="utf-8"), (
        f"{doc.name} never covers {what}"
    )


def test_both_host_pages_put_the_master_config_under_the_install_prefix():
    """Both pages build the master with `--prefix=/opt/etherlab`, which puts
    autoconf's sysconfdir at `/opt/etherlab/etc`. The init script and the file
    it reads are therefore under that prefix.

    The CB2 page had the config at `/etc/ethercat.conf` and started the master
    with `/etc/init.d/ethercat` — a distro-packaged master's layout, which
    this build does not install — while its own ExecStop already used the
    prefixed path. A MASTER0_DEVICE written to a file nothing reads produces a
    master that loads and finds no link, which is indistinguishable from a
    wrong MAC and is the row its own troubleshooting table sends you to."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    pages = [
        "docs/rewrite/ethercat-igh-macb-install.md",
        "docs/rewrite/ethercat-host-cb2-rk3566.md",
        "docs/rewrite/markforged-cb2-complete-build.md",
    ]
    for rel in pages:
        text = (root / rel).read_text(encoding="utf-8")
        assert "--prefix=/opt/etherlab" in text, (
            "%s no longer sets the prefix" % rel
        )
        # The unprefixed paths belong to a packaged master, so they may only
        # appear where the page is explaining that they do not apply.
        for stray in re.finditer(
            r"(?<!ld\.so\.conf\.d/)\betc/ethercat\.conf\b", text
        ):
            window = text[max(0, stray.start() - 220) : stray.end() + 120]
            assert "distro-packaged" in window, (
                "%s points MASTER0_DEVICE at /etc/ethercat.conf, which a "
                "--prefix=/opt/etherlab master never reads" % rel
            )
        for stray in re.finditer(r"(?<!etherlab/)etc/init\.d/ethercat", text):
            window = text[max(0, stray.start() - 220) : stray.end() + 120]
            assert "distro-packaged" in window, (
                "%s runs /etc/init.d/ethercat, which this build does not "
                "install" % rel
            )


def test_both_host_pages_check_the_module_against_the_running_kernel():
    """A module built against a different kernel tree is refused by modprobe
    with nothing that names the cause. The Pi 5 page checks `modinfo -F
    vermagic` against `uname -r`; the CB2 page only printed the first lines of
    modinfo and never said to compare them.

    The CB2 is the side where this is likelier, not less: the Pi 5 installs a
    distro RT kernel with matching headers, while the CB2 page has you build
    the kernel yourself in Step 1 and then build modules against it."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in [
        "docs/rewrite/ethercat-igh-macb-install.md",
        "docs/rewrite/ethercat-host-cb2-rk3566.md",
        "docs/rewrite/markforged-cb2-complete-build.md",
    ]:
        text = (root / rel).read_text(encoding="utf-8")
        # In a command block, not merely mentioned in prose: a troubleshooting
        # row telling you to check it after it has already failed is not the
        # same as a step that checks it before you go on.
        fences = "\n".join(re.findall(r"```sh\n(.*?)```", text, re.S))
        assert "modinfo -F vermagic" in fences, (
            "%s does not check the module's vermagic as a step, so a module "
            "built against the wrong kernel tree is found by modprobe "
            "refusing it" % rel
        )
        flat = re.sub(r"\s+", " ", text)
        assert re.search(r"wrong kernel tree", flat), (
            "%s checks vermagic without saying what a mismatch means" % rel
        )
