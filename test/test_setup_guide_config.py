"""The worked config in the ESTUN/Markforged setup guide must stay parseable.

A setup guide whose config example does not load is worse than no guide: it
strands someone who has already wired a machine. These tests read the block
straight out of the document and put it through the same native reader
Motion._load_motion_config uses, so the guide cannot drift away from the code.
"""

import pathlib
import re

import pytest
from fakes import FakeConfigError

from klippy import configfile

GUIDE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "docs"
    / "rewrite"
    / "estun-pronet-markforged-setup.md"
)

# The guide omits [printer] because it is not servo-specific, but the reader
# needs cartesian limits before it will look at the topology.
PRINTER_SECTION = """[printer]
max_velocity: 300
max_accel: 3000
corner_deviation: 0.04
max_z_velocity: 5
max_z_accel: 100

"""


def guide_config():
    text = GUIDE.read_text(encoding="utf-8")
    part = text.split("## Part 11 — Configuration")[1].split("## Part 12")[0]
    blocks = re.findall(r"```ini\n(.*?)```", part, re.S)
    assert blocks, "no ini block found in the guide's configuration part"
    return PRINTER_SECTION + blocks[0]


def read_topology():
    try:
        _limits, _axes, kin, _consumed = (
            configfile._config_doc.read_motion_settings(guide_config())
        )
    except configfile.error as e:
        raise FakeConfigError(str(e))
    return kin


def test_guide_config_parses():
    assert read_topology() is not None


def test_guide_declares_markforged():
    kind, _lanes, _followers = read_topology()
    assert kind == "markforged"


def test_guide_drives_xy_as_servos_and_z_as_a_stepper():
    _kind, lanes, _followers = read_topology()
    drives = {axis: drive for _idx, axis, _motors, drive in lanes}
    assert drives["x"] == "servo"
    assert drives["y"] == "servo"
    assert drives["z"] == "stepper"


def test_guide_uses_a_single_z_motor():
    _kind, lanes, _followers = read_topology()
    z_motors = next(motors for _i, axis, motors, _d in lanes if axis == "z")
    assert len(z_motors) == 1


def test_guide_extruder_is_one_axis_with_two_motors():
    """The tandem pair must be one follower axis, not two axes.

    Two motors on one axis step from a single trajectory and cannot drift
    apart; two axes would need synchronising and could.
    """
    _kind, _lanes, followers = read_topology()
    assert len(followers) == 1
    axis, motors, _slot = followers[0]
    assert axis == "e"
    assert len(motors) == 2


@pytest.mark.parametrize("pin", ["PB8", "PG13", "PG9", "PF4", "PF3", "PF2"])
def test_guide_config_carries_the_manta_pins(pin):
    """Pin names do not transfer between mainboards; a stale Octopus pin here
    would still look like a valid STM32 pin."""
    assert pin in guide_config()
