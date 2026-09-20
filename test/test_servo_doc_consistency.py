"""Two documents describe this machine's servo config, and they must agree.

The setup guide is the one someone follows; the bench checklist carries a
worked example for the same gantry and the setup guide sends readers to it.
They drifted: the bench copy still had the pre-safety torque ceiling, no
following-error limit, and a plausible-looking drive identity that passes
config-time validation and then never matches a drive.

The values checked here are the ones where disagreement is dangerous rather
than untidy.
"""

import pathlib
import re

import pytest

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs" / "rewrite"
GUIDE = DOCS / "estun-pronet-markforged-setup.md"
BENCH = DOCS / "ethercat-bench-bringup.md"

BENCH_TORQUE_CEILING_PCT = 150.0


@pytest.mark.parametrize("doc", [GUIDE, BENCH], ids=lambda p: p.stem)
def test_worked_servo_motors_stay_under_the_bench_torque_ceiling(doc):
    """max_torque is a percentage of rated and accepts up to 400. A worked
    example for a first power-on must not hand over the motor's peak."""
    values = [
        float(v)
        for v in re.findall(r"^max_torque: (\d+)", doc.read_text(), re.M)
    ]
    assert values, f"{doc.name} has no worked max_torque"
    assert max(values) <= BENCH_TORQUE_CEILING_PCT


@pytest.mark.parametrize("doc", [GUIDE, BENCH], ids=lambda p: p.stem)
def test_worked_servo_motors_set_a_following_error(doc):
    """It has no default: omitted, no session limit is written and the drive
    keeps whatever the last session left in 6065h."""
    assert re.search(r"^following_error: [\d.]+", doc.read_text(), re.M), (
        f"{doc.name}'s worked example omits following_error"
    )


@pytest.mark.parametrize("doc", [GUIDE, BENCH], ids=lambda p: p.stem)
def test_drive_identity_placeholders_are_refused_not_merely_wrong(doc):
    """A zero identity is rejected at config time, naming the missing half.

    A plausible-looking wrong one is worse: it is accepted, never matches a
    drive, and the bus dies at the OP walk with nothing pointing back at it.
    """
    from klippy.extras.ethercat_node import missing_identity_options

    for vendor, product in re.findall(
        r"^vendor_id: (\S+).*?\n(?:.*\n)?product_code: (\S+)",
        doc.read_text(),
        re.M,
    ):
        parsed = [
            int(v, 16) if v.lower().startswith("0x") else int(v)
            for v in (vendor, product)
        ]
        assert missing_identity_options("estun-pronet", *parsed), (
            f"{doc.name} shows identity {vendor}/{product}, which klippy "
            f"accepts — a reader who copies it fails on the bus instead"
        )


def registered_gcode_commands():
    klippy = pathlib.Path(__file__).resolve().parents[1] / "klippy"
    found = set()
    for path in klippy.rglob("*.py"):
        found.update(
            re.findall(
                r'register_(?:mux_)?command\(\s*"([A-Z_0-9]+)"',
                path.read_text(encoding="utf-8"),
            )
        )
    return found


@pytest.mark.parametrize("doc", [GUIDE, BENCH], ids=lambda p: p.stem)
def test_a_doc_naming_a_dashboard_macro_says_it_is_one(doc):
    """`SERVO_CAPTURE_START` ships here; `SERVO_FIT_DYNAMICS` is a
    serval-dashboard macro. The bench page described both under one heading,
    so a reader typing the second gets "Unknown command" and goes looking for
    a build failure that is really a missing install. A page that names a
    command this repository does not register has to say so."""
    text = doc.read_text(encoding="utf-8")
    registered = registered_gcode_commands()
    named = set(re.findall(r"`(SERVO_[A-Z_]+)[ `]", text))
    external = sorted(named - registered)
    if not external:
        pytest.skip(
            "%s names no command from outside this repository" % doc.stem
        )
    assert "serval-dashboard" in text, (
        "%s names %s without pointing anywhere they come from"
        % (doc.stem, external)
    )
    assert re.search(r"Unknown\s+command", text), (
        "%s names %s but never says a console will answer 'Unknown command' "
        "for them" % (doc.stem, external)
    )
