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
