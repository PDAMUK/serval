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
MOTION_REF = (
    pathlib.Path(__file__).resolve().parents[1]
    / "docs"
    / "Config_Reference_Motion.md"
)

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


@pytest.mark.parametrize(
    "doc", [GUIDE, BENCH, MOTION_REF], ids=lambda p: p.stem
)
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


# Cables a reader has to identify at the machine to apply the 300 mm rule.
# Aggressors first, then the runs they corrupt.
SEPARATION_AGGRESSORS = ["U`/`V`/`W", "B1`/`B2", "PF5", "Motor3"]
SEPARATION_VICTIMS = ["CN2", "EtherCAT", "PF1", "PB0"]


@pytest.mark.parametrize("doc", [GUIDE, BENCH], ids=lambda p: p.stem)
def test_the_separation_rule_names_cables_not_categories(doc):
    """ "Keep power and signal 300 mm apart" is not actionable at a machine
    where every cable is within 300 mm of every other. The reader has to know
    which runs on THIS build are which, and the worst pairing — a motor's
    power cable and its own encoder cable, same drive to same motor, sharing a
    drag chain — has to be called out because no distance is available for it.
    """
    text = doc.read_text(encoding="utf-8")
    if "300 mm" not in text:
        pytest.skip("%s does not carry the separation rule" % doc.stem)
    # Scoped to the section. `B1`/`B2` and CN2 appear in the wiring parts too,
    # so a whole-file search passes even after the rule stops naming them.
    section = text.split("Wire the motor coils in pairs by phase")[1]
    section = section.split("\n## ")[0]
    missing = [c for c in SEPARATION_AGGRESSORS if c not in section]
    assert not missing, "noisy cables the rule never names: %s" % (missing,)
    missing = [c for c in SEPARATION_VICTIMS if c not in section]
    assert not missing, "sensitive cables the rule never names: %s" % (missing,)
    flat = re.sub(r"\s+", " ", section)
    assert "same motor" in flat or "same drive" in flat, (
        "%s never says the motor power and encoder cables share a route, "
        "which is the one pairing distance cannot fix" % doc.stem
    )


@pytest.mark.parametrize("doc", [GUIDE, BENCH], ids=lambda p: p.stem)
def test_tuning_docs_say_where_a_tuned_value_lives(doc):
    """Both routes push to drive RAM and nothing writes EEPROM implicitly. A
    `SERVO_PARAM SET` is therefore gone on the next restart, while a `params:`
    entry comes back because klippy re-pushes it every claim. A page that
    teaches tuning without that distinction sends someone through a long
    session whose results evaporate, and leaves them no way to persist
    deliberately (CiA 301 `0x1010`).

    The same page has to warn that a rejected or clamped `params:` write
    *fails the claim* — the machine will not start, which is intended."""
    text = doc.read_text(encoding="utf-8")
    if "params:" not in text or "SERVO_PARAM" not in text:
        pytest.skip("%s does not document drive parameters" % doc.stem)
    flat = re.sub(r"\s+", " ", text)
    assert "0x1010" in flat, (
        "%s never names the store-parameters object, so there is no documented "
        "way to persist deliberately" % doc.stem
    )
    assert "EEPROM" in flat
    assert re.search(r"never (?:persists|does this) implicitly", flat), (
        "%s does not say the drive's EEPROM is left alone" % doc.stem
    )
    assert "fails the claim" in flat, (
        "%s does not warn that a rejected params: write stops startup"
        % doc.stem
    )


COLLATED = DOCS / "markforged-cb2-complete-build.md"


@pytest.mark.parametrize("doc", [GUIDE, COLLATED], ids=lambda p: p.stem)
def test_the_chain_check_does_not_claim_to_prove_direction(doc):
    """EtherCAT is direction-sensitive and both guides say so — then verified
    the chain with "the LINK/ACT LED lights on each connected RJ45".

    The link is negotiated below EtherCAT, so a CN4-to-CN4 link lights both
    LEDs exactly the same way. The check passes in the failure case it sits
    under, which is the worst property a verification can have. Direction is
    proven where `ethercat slaves` counts the slaves, and the page has to say
    so rather than let the LED stand in for it."""
    text = doc.read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", text)
    assert "LINK/ACT" in flat, "%s no longer checks the link at all" % doc.stem
    assert "nothing about direction" in flat, (
        "%s lets the LINK/ACT LED stand as the chain-direction check; it "
        "lights the same way on a reversed link" % doc.stem
    )
    assert re.search(r"CN4.{0,4}to.{0,4}`?CN4", flat), (
        "%s does not name the reversed link the LED cannot see" % doc.stem
    )


@pytest.mark.parametrize(
    "code",
    ["175-5085", "489-0447", "488-6915", "211-1482", "139-972", "870-3413"],
)
def test_the_collated_bill_quotes_the_same_parts_as_the_source(code):
    """The collation carries its own bill of materials, and the arithmetic
    tests that guard the source guide's never looked at it. A part that drifts
    between the two is a part someone buys twice."""
    source = GUIDE.read_text(encoding="utf-8")
    collated = COLLATED.read_text(encoding="utf-8")
    assert code in source, "%s left the source guide's bill" % code
    assert code in collated, "%s is missing from the collated bill" % code


def test_the_collated_bill_carries_the_load_and_the_breaker_that_matches():
    """7.83 A is the figure every sizing decision is made against. A bill that
    quotes a breaker without it, or a breaker too small for it, is a bill
    nobody can check."""
    text = COLLATED.read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", text)
    assert "7.83" in flat, "the collated guide no longer states the load"
    breaker = re.search(r"S201-C(\d+)", flat)
    assert breaker, "no breaker named in the collated bill"
    assert float(breaker.group(1)) > 7.83, (
        "the collated bill's breaker is rated below the load it states"
    )
    assert "Type A" in flat and "Type AC is not acceptable" in flat, (
        "the collated guide does not rule out the RCD type that cannot see DC"
    )


@pytest.mark.parametrize("doc", [GUIDE, COLLATED], ids=lambda p: p.stem)
def test_the_endstop_check_does_not_claim_to_prove_the_pull_up(doc):
    """Both guides spend a paragraph on the `^` prefix — an input without it
    floats the moment the switch opens — and then verified the wiring with
    "QUERY_ENDSTOPS reports all three switches changing state when pressed".

    That passes either way. Closing to ground pulls the pin firmly low with or
    without the pull-up; what a missing prefix breaks is the *released* state.
    So the check sits directly under the defect it cannot see, and the page
    has to say which half it proves and give the one that bites: the released
    state read repeatedly, and read again with the servos moving."""
    text = doc.read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", text)
    assert "QUERY_ENDSTOPS" in flat, (
        "%s no longer checks the endstops" % doc.stem
    )
    assert "It does not prove the pull-up" in flat, (
        "%s lets QUERY_ENDSTOPS stand as proof of the pull-up; a missing `^` "
        "passes it exactly like a correct one" % doc.stem
    )
    assert "released" in flat, (
        "%s does not point at the released state, which is the half a missing "
        "pull-up actually breaks" % doc.stem
    )
    assert "servos moving" in flat, (
        "%s does not say to re-check with the servos running, which is when "
        "the noise is there to be picked up" % doc.stem
    )


@pytest.mark.parametrize("doc", [GUIDE, COLLATED], ids=lambda p: p.stem)
def test_both_guides_name_the_stop_category_and_the_alarm_it_latches(doc):
    """Two things a builder meets on the first press and on every press after.

    The stop is Category 0 with dynamic braking, not Category 1 — these drives
    have no STO and `Pn004.0` offers brake or coast, never a ramp, so there is
    nothing to sequence a controlled stop against. Calling it anything else
    overstates what the chain does.

    And opening the contactor removes main power for longer than one AC
    period, so the drives latch A.21 and/or A.14 every time. `Pn000.3` is not
    an escape: the factory 0 already means one period, and A.21 is defined as
    longer than that. A guide that omits it leaves friction on every press
    looking like a fault."""
    text = doc.read_text(encoding="utf-8")
    # Scoped to the passage that explains the halt. A.21 also appears in the
    # fault quick reference, so a whole-file search passes after the halting
    # section stops naming it — which is where a reader meets it first.
    # Scoped per document to the passage that explains the halt; the two
    # organise it differently.
    marker, end = (
        ("Halting the drives as the stop is pressed", "### Earth leakage")
        if doc is GUIDE
        else ("## E7 — What the stop actually does", "## E9 —")
    )
    assert marker in text, "%s no longer explains the halt" % doc.stem
    section = text.split(marker)[1].split(end)[0]
    flat = re.sub(r"\s+", " ", section)
    assert "Stop Category 0" in flat, (
        "%s does not name the stop category, which decides what a reader "
        "expects the chain to do" % doc.stem
    )
    assert "not Category 1" in flat or "is not Category 1" in flat
    assert "no STO" in flat, (
        "%s does not say why Category 1 is unavailable" % doc.stem
    )
    assert "A.21" in flat and "A.14" in flat, (
        "%s does not say the drives latch an alarm on every stop press"
        % doc.stem
    )
    assert "Pn000.3" in flat, (
        "%s does not close off Pn000.3, which reads like an escape and is not"
        % doc.stem
    )
