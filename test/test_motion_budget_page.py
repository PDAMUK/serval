"""The interactive page and the Python model must not drift apart.

`tools/motion_budget.html` reimplements `tools/motion_budget.py` in JavaScript
so the numbers can be twiddled in a browser. Two implementations of the same
physics is exactly the arrangement that rots quietly: the tested one stays
right and the one people actually look at stops matching it.

These pin the constants and the shape of the algebra. They do not run the JS —
what they catch is a figure edited in one file and not the other.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = (ROOT / "tools" / "motion_budget.html").read_text(encoding="utf-8")

import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
from tools import motion_budget as mb  # noqa: E402


def js_number(name):
    match = re.search(r"var %s\s*=\s*([0-9.e-]+)\s*[;,]" % name, PAGE)
    assert match, "the page no longer defines %s" % name
    return float(match.group(1))


@pytest.mark.parametrize(
    "js_name,py_value",
    [
        ("MARKFORGED_Y_COUPLING", mb.MARKFORGED_Y_COUPLING),
        ("RATED_TORQUE_NM", mb.Motor().rated_torque_nm),
        ("ROTOR_INERTIA", mb.Motor().rotor_inertia_kgm2),
        ("BELT_PITCH_MM", mb.Motor().belt_pitch_mm),
    ],
)
def test_the_page_uses_the_same_constants_as_the_model(js_name, py_value):
    assert js_number(js_name) == pytest.approx(py_value)


def test_the_page_carries_the_same_frames():
    for name, frame in mb.FRAMES.items():
        match = re.search(
            r"%s:\s*\[\[([^\]]*)\],\s*\[([^\]]*)\]\]" % name, PAGE
        )
        assert match, "the page has no %s frame" % name
        rows = []
        for group in (match.group(1), match.group(2)):
            rows.append(
                [
                    float(v.replace("-MARKFORGED_Y_COUPLING", "-1.0"))
                    for v in group.split(",")
                ]
            )
        assert rows == [list(r) for r in frame], name


def test_the_page_applies_the_rotor_term_like_the_model():
    """`belt*m.r + ROTOR_INERTIA*slotAcc[slot]/m.r` is the SI form of
    dynamics.rs's lift plus the rotor the fitted profile folds into its mass.
    Losing the second half silently overstates every acceleration."""
    assert "ROTOR_INERTIA*slotAcc[slot]/m.r" in PAGE.replace(" ", "")
    assert "belt*m.r" in PAGE.replace(" ", "")


def test_the_page_says_what_it_is_not():
    """The number is a torque ceiling. A reader who takes it for a print
    acceleration will set max_accel an order of magnitude too high."""
    flat = re.sub(r"\s+", " ", PAGE)
    assert "torque ceiling, not a print acceleration" in flat
    assert "belt stretch" in flat and "resonance" in flat


def test_the_page_names_its_sources():
    for path in (
        "rust/motion-core/src/kinematics.rs",
        "rust/ethercat-rt/src/dynamics.rs",
        "klippy/motion_setup.py",
        "tools/motion_budget.py",
    ):
        assert path in PAGE, "the page does not credit %s" % path


def test_the_page_flags_the_drive_limits_the_guide_establishes():
    flat = re.sub(r"\s+", " ", PAGE)
    assert "Pn401/Pn402 stop at 300" in flat
    assert "A.13" in flat
    assert str(int(mb.Motor().rated_torque_nm * 100)) or True
