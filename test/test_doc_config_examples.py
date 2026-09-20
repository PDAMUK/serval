"""Every config example in this fork's documents must load.

A worked example is the part of a document people copy. One that the config
reader refuses is worse than no example: it strands someone who has already
wired a machine, and it does it at the moment they have the least patience for
a documentation bug.

Two in `ethercat-bench-bringup.md` were in that state. Its headline sample
config used `[servo_x]`, which is in the reader's rejected set — role-encoding
sections were replaced by freely named `[motor]` sections assigned in
`[kinematics]` — so the block died at `reject_unsupported_sections`. Its
Markforged worked example named three axes in `[kinematics]` and defined none
of them. Both had prose around them that was entirely correct.
"""

import pathlib
import re

import pytest

from klippy import configfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

# [printer] is not servo-specific and the guides omit it, but the reader wants
# cartesian limits before it will look at the topology.
PRINTER = """[printer]
max_velocity: 300
max_accel: 3000
corner_deviation: 0.04
max_z_velocity: 5
max_z_accel: 100

"""

# Each: the document, the heading whose first ```ini block is a whole machine,
# and what that machine is. A fragment showing one option belongs in a
# document's prose, not here — these are the blocks someone copies wholesale.
WHOLE_MACHINE_EXAMPLES = [
    (
        "docs/rewrite/ethercat-bench-bringup.md",
        "## Sample config",
        "cartesian",
        {"x": "servo", "y": "stepper", "z": "stepper"},
    ),
    (
        "docs/rewrite/ethercat-bench-bringup.md",
        "## Markforged with two ESTUN drives",
        "markforged",
        {"x": "servo", "y": "servo", "z": "stepper"},
    ),
    (
        "docs/rewrite/estun-pronet-markforged-setup.md",
        "## Part 11 — Configuration",
        "markforged",
        {"x": "servo", "y": "servo", "z": "stepper"},
    ),
    (
        "docs/rewrite/markforged-cb2-complete-build.md",
        "# Stage K",
        "markforged",
        {"x": "servo", "y": "servo", "z": "stepper"},
    ),
]

IDS = [
    "%s::%s" % (pathlib.Path(d).stem, h.lstrip("# "))
    for d, h, _k, _l in WHOLE_MACHINE_EXAMPLES
]


def first_ini_block(rel, heading):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert heading in text, "%s no longer has %r" % (rel, heading)
    blocks = re.findall(r"```ini\n(.*?)```", text.split(heading)[1], re.S)
    assert blocks, "%s: no ini block under %r" % (rel, heading)
    return blocks[0]


@pytest.mark.parametrize(
    "rel,heading,kind,lanes", WHOLE_MACHINE_EXAMPLES, ids=IDS
)
def test_the_example_loads_through_the_reader_klippy_uses(
    rel, heading, kind, lanes
):
    block = first_ini_block(rel, heading)
    try:
        _limits, _axes, topology, _consumed = (
            configfile._config_doc.read_motion_settings(PRINTER + block)
        )
    except configfile.error as e:
        pytest.fail("%s %r would not load: %s" % (rel, heading, e))
    got_kind, got_lanes, _followers = topology
    assert got_kind == kind
    assert {name: drive for _i, name, _m, drive in got_lanes} == lanes


@pytest.mark.parametrize(
    "rel,heading,kind,lanes", WHOLE_MACHINE_EXAMPLES, ids=IDS
)
def test_the_example_uses_no_role_encoding_section(rel, heading, kind, lanes):
    """The reader refuses `[servo_x]` and `[stepper_x]` outright. Catching the
    name as well as the parse failure says *why* a block is wrong, and catches
    it in a fragment the parse test cannot reach."""
    block = first_ini_block(rel, heading)
    rejected = re.findall(r"^\[((?:servo|stepper)_[xyzab]\d*)\]", block, re.M)
    assert not rejected, "%s %r uses role-encoding sections: %s" % (
        rel,
        heading,
        rejected,
    )


def test_no_document_presents_a_role_encoding_section_as_current_syntax():
    """The bench checklist keeps a dated stub-validation record that names
    `[servo_x]` as it was at the time. That is fine — it is history — but it
    has to be marked as history, or it reads as the syntax to use."""
    text = (ROOT / "docs" / "rewrite" / "ethercat-bench-bringup.md").read_text(
        encoding="utf-8"
    )
    flat = re.sub(r"\s+", " ", text)
    assert "[servo_x] below" in flat or "syntax of the day" in flat, (
        "the dated record names [servo_x] without saying it is no longer the "
        "section name"
    )
    assert "Role-encoding sections" in flat, (
        "the sample config no longer explains which section names are refused"
    )
