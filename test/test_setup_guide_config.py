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


def test_guide_supplies_both_identity_halves_to_replace():
    """Both identity options must stay in the worked config.

    klippy rejects an identityless profile that is missing either half, so a
    guide that dropped one would hand the reader a config that cannot start.
    """
    block = guide_config()
    assert "vendor_id:" in block
    assert "product_code:" in block


HOST_DOCS = (
    GUIDE.parent / "ethercat-igh-macb-install.md",
    GUIDE.parent / "ethercat-host-cb2-rk3566.md",
)


@pytest.mark.parametrize("doc", HOST_DOCS, ids=lambda p: p.name)
def test_every_host_path_builds_the_endpoint(doc):
    """klippy spawns the endpoint binary; a host doc that never builds it
    strands the reader at the first claim with a missing file. The CB2 page
    shipped without this step while the Pi 5 page had it."""
    text = doc.read_text(encoding="utf-8")
    assert "ethercat-endpoint-hw" in text
    assert "ethercat-stub" in text


SERVO_BENCH_TORQUE_CEILING_PCT = 150.0


def servo_motor_blocks():
    block = guide_config()
    sections = re.split(r"\n(?=\[)", block)
    return [s for s in sections if "drive: servo" in s]


def test_the_guide_configures_two_servo_motors():
    assert len(servo_motor_blocks()) == 2


@pytest.mark.parametrize("field", ["max_torque", "following_error"])
def test_every_servo_motor_sets_both_drive_limits(field):
    """following_error has no default: omitting it writes no session limit and
    leaves whatever the last session left in the drive's 6065h."""
    for section in servo_motor_blocks():
        assert re.search(r"^%s\s*:" % field, section, re.M), section


def test_bring_up_torque_stays_below_the_bench_ceiling():
    """max_torque is a percentage of rated torque and accepts up to 400. A
    worked example for a first power-on must not hand over the motor's peak."""
    for section in servo_motor_blocks():
        value = float(
            re.search(r"^max_torque\s*:\s*([\d.]+)", section, re.M)[1]
        )
        assert value <= SERVO_BENCH_TORQUE_CEILING_PCT


H723_FIXTURE = GUIDE.parents[2] / "test" / "configs" / "stm32h723.config"


def h723_fixture_options():
    return dict(
        line.split("=", 1)
        for line in H723_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.startswith("CONFIG_") and "=" in line
    )


@pytest.mark.parametrize(
    "option,value",
    [
        ("CONFIG_MACH_STM32H723", "y"),
        ("CONFIG_STM32_CLOCK_REF_25M", "y"),
        ("CONFIG_FLASH_APPLICATION_ADDRESS", "0x8020000"),
    ],
)
def test_guide_firmware_rows_match_the_fixture(option, value):
    """Three of the guide's four menuconfig rows are shared with the build
    matrix fixture, so the guide cites it. If the fixture moves, the guide is
    wrong."""
    assert h723_fixture_options().get(option) == value


def test_the_fixture_is_a_uart_build_and_the_guide_says_so():
    """The fourth row is not shared: the fixture is a UART build, so copying
    it to .config yields a board that never enumerates over USB. Should the
    fixture ever gain USBSERIAL, the guide's warning becomes wrong and must be
    rewritten rather than silently left in place."""
    options = h723_fixture_options()
    assert options.get("CONFIG_SERIAL") == "y"
    assert "CONFIG_USBSERIAL" not in options
    assert "CONFIG_USBSERIAL" in GUIDE.read_text(encoding="utf-8")


LIBECRT_H = GUIDE.parents[2] / "rust" / "ethercat-rt" / "csrc" / "libecrt.h"


def endpoint_return_codes():
    return {
        int(m.group(2)): m.group(1)
        for m in re.finditer(
            r"#define (EC_RT_ERR_\w+)\s+\((-\d+)\)",
            LIBECRT_H.read_text(encoding="utf-8"),
        )
    }


@pytest.mark.parametrize("code", [-2, -4, -6, -21])
def test_fault_table_codes_are_real_endpoint_codes(code):
    """The guide's fault table lists rc values a reader will see on the bench.

    A code that no longer exists, or that never did, sends someone chasing the
    wrong failure at the worst moment.
    """
    assert code in endpoint_return_codes()
    assert "`rc=%d`" % code in GUIDE.read_text(encoding="utf-8")


def test_guide_params_example_parses_with_the_real_parser():
    """Part 13 shows a `params:` block for drive tuning.

    The format is not guessable — address, type token and value, with the
    subindex after a dot — so an example that does not parse is worse than no
    example at all.
    """
    from klippy.extras.servo_param import parse_params_block

    text = GUIDE.read_text(encoding="utf-8")
    block = re.search(
        r"^params:\n((?:\s+0x[0-9A-Fa-f]+\.\d+:.*\n)+)", text, re.M
    )
    assert block, "the params: example in Part 13 has moved or gone"
    entries = parse_params_block(block.group(1))
    assert entries, "the example parsed to nothing"
    for index, subindex, size, value in entries:
        assert 0x3000 <= index <= 0x3FFF, (
            "ESTUN tuning parameters live in the 0x3xxx manufacturer area"
        )
        assert size > 0 and value >= 0


def test_guide_servo_param_examples_name_a_motor_the_config_declares():
    """SERVO= resolves a [motor] name, or an axis with a single servo. An
    example naming neither sends the reader to a command that cannot resolve."""
    text = GUIDE.read_text(encoding="utf-8")
    names = set(re.findall(r"^\[motor (\w+)\]", guide_config(), re.M))
    used = set(re.findall(r"SERVO_PARAM SERVO=(\w+)", text))
    assert used, "no SERVO_PARAM example found in the guide"
    assert used <= names, (
        f"{used - names} is not a [motor] in the guide's config"
    )


def mains_section():
    text = GUIDE.read_text(encoding="utf-8")
    return text.split("## Part 5 — Mains and drive power")[1].split(
        "## Part 6"
    )[0]


def test_breaker_rating_carries_the_stated_load():
    """The MCB is sized for inrush, not for the 7.8 A the drives draw.

    Two 0.9 kVA drives at 230 V is 7.8 A continuous, so the rating must exceed
    it with room for the rectifier inrush that a correctly-curved breaker has
    to ride through. A rating at or below the load would trip under normal
    running; the curve letter is what makes the inrush survivable.
    """
    section = mains_section()
    rating = int(re.search(r"(\d+) A, \*\*Type C\*\*", section)[1])
    load_amps = 2 * 0.9 * 1000 / 230
    assert rating > load_amps * 1.5, (
        f"{rating} A leaves no margin over {load_amps:.1f} A of load"
    )
    assert "Type C" in section and "Type B would trip" in section


def test_rcd_type_rules_out_the_one_that_cannot_see_dc():
    """Type AC is blinded by the DC residual a rectifier produces, which is the
    whole hazard. The section must name Type A as the floor and say so."""
    section = mains_section()
    assert "Type AC is not acceptable" in section
    assert "Type A is the minimum" in section


def bom_section():
    text = GUIDE.read_text(encoding="utf-8")
    return text.split("## Part 1 — Bill of materials")[1].split("## Part 2")[0]


def bom_group(heading):
    block = bom_section().split(heading)[1].split("\n\n")
    rows = next(part for part in block if part.lstrip().startswith("| Item |"))
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in rows.splitlines()[2:]
    ]


def stock_codes(text):
    return re.findall(r"\*\*(\d{3}-\d{4})\*\*", text)


def test_every_buyable_part_is_counted_in_the_bill_of_materials():
    """Part 5 argues each part and Part 1 says how many. A part that only one
    of them knows about is either uncounted or unexplained."""
    specified = set(stock_codes(buy_section()))
    counted = set(stock_codes(bom_section()))
    assert specified and counted
    assert not specified - counted, (
        f"specified, never counted: {specified - counted}"
    )
    assert not counted - specified, (
        f"counted, never specified: {counted - specified}"
    )


def test_no_stock_code_names_two_different_parts():
    """The same code appears in both parts of the guide. If one side is edited
    and the other is not, the code and the part number stop agreeing."""
    named = {}
    for line in GUIDE.read_text(encoding="utf-8").splitlines():
        codes = stock_codes(line)
        parts = set(re.findall(r"`([A-Z][\w./-]{4,})`", line))
        if len(codes) == 1 and parts:
            named.setdefault(codes[0], []).append(parts)
    for code, seen in named.items():
        assert set.intersection(*seen), f"{code} names {seen}"


def test_each_drive_gets_its_own_copy_of_the_per_drive_parts():
    """A regenerative resistor is per drive because each drive switches its
    own braking transistor. Anything in this group counted once is a part two
    drives would have to share, which none of them can."""
    rows = bom_group("### Per drive — two of each")
    assert len(rows) >= 6, rows
    for row in rows:
        assert row[1] == "2", row


def test_the_shared_chain_is_counted_once():
    """The drives sit on one supply, so the chain is one of each. A count of
    two here means someone has built a per-drive chain by accident."""
    rows = bom_group("### Once for the pair — the mains chain")
    assert len(rows) >= 8, rows
    for row in rows:
        assert not row[1].startswith("2"), row


def test_the_substitution_says_what_it_removes():
    section = bom_section()
    table = section.split("### Substitutions, and what each one removes")[1]
    row = next(line for line in table.splitlines() if line.startswith("| RCBO"))
    assert "MCB" in row and "RCD" in row, row
    assert "one" in row, f"no net count stated: {row}"


def buy_section():
    return (
        mains_section()
        .split("### What to buy")[1]
        .split("### Fitting it in a printer enclosure")[0]
    )


def buy_table(heading):
    block = buy_section().split(heading)[1].split("\n\n")
    rows = next(part for part in block if part.lstrip().startswith("| Item |"))
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in rows.splitlines()[2:]
    ]


def test_every_rs_stock_code_is_well_formed():
    """A mistyped stock number orders the wrong part silently. RS codes are
    three digits, a hyphen, four digits — nothing else parses as one."""
    codes = re.findall(r"RS \*\*([^*]+)\*\*", buy_section())
    assert codes, "the buy tables carry no RS stock numbers"
    bad = [code for code in codes if not re.fullmatch(r"\d{3}-\d{4}", code)]
    assert not bad, f"not RS stock numbers: {bad}"


def test_each_part_is_labelled_needed_optional_or_a_combination():
    section = buy_section()
    for heading in (
        "**Needed.**",
        "**One part instead of two.**",
        "**Optional.**",
    ):
        assert heading in section, f"{heading} has gone from the buy section"


def test_the_combination_replaces_rows_that_exist_on_their_own():
    """The RCBO is only a substitution if the two parts it stands in for are
    themselves listed. If either row is renamed, the claim dangles."""
    needed = {row[0] for row in buy_table("**Needed.**")}
    assert {"MCB", "RCD"} <= needed, needed
    for row in buy_table("**One part instead of two.**"):
        assert "MCB" in row[1] and "RCD" in row[1], row


def test_every_optional_part_says_when_to_skip_it():
    """Calling a part optional without the reason leaves the reader guessing
    which corner they are cutting."""
    rows = buy_table("**Optional.**")
    assert rows, "the optional table is empty"
    for row in rows:
        assert len(row) == 4, row
        assert row[3], f"{row[0]} is optional with no reason given"


def test_the_needed_table_carries_the_whole_protective_chain():
    """Every device the chain table numbers must be buyable from one of the
    three tables, or the reader assembles a chain they cannot source."""
    needed = {row[0] for row in buy_table("**Needed.**")}
    assert {"Isolator", "EMC filter", "Contactor"} <= needed, needed


def earth_section():
    return (
        mains_section()
        .split("### Where the supply arrives")[1]
        .split("### The chain, in order")[0]
    )


def test_the_inlet_is_rated_above_what_the_drives_draw():
    """A C14 coupler is rated 10 A and the drives take 7.83 A of it, so the
    connector runs out before the circuit does. The bill has to name the
    bigger one and say why."""
    row = re.search(r"^\| Mains inlet \|.*$", bom_section(), re.M)
    assert row, "the inlet row has gone from the bill of materials"
    assert "C20" in row.group(0), row.group(0)
    assert "10 A" in row.group(0), "the C14 rating is what makes C20 the answer"


def test_the_drive_manuals_earthing_instruction_is_refused():
    """ESTUN specifies a local electrode, which is a JIS Class D earth. Followed
    literally on a PME supply that is dangerous, so the guide has to say so
    rather than repeat the manual."""
    section = earth_section()
    assert "independent ground" in section, "the manual's wording is not quoted"
    assert "PME" in section
    assert "100 ohm" in section, "the figure being overridden is not stated"


def test_earth_continuity_is_tested_at_the_right_order_of_magnitude():
    """100 ohm is the manual's electrode figure. Using it as a continuity
    limit would pass a bond made onto paint."""
    steps = mains_section().split("**Verify (no motor connected).**")[1]
    assert "0.1 ohm" in steps, "no continuity figure in the verification"
    assert "100 ohm" not in steps


def test_numbered_lists_run_in_order():
    """A step inserted by hand renumbers everything after it, and markdown
    renders the list correctly either way, so nothing else catches this."""
    run, bad = [], []
    for line in GUIDE.read_text(encoding="utf-8").splitlines() + [""]:
        found = re.match(r"^(\d+)\. ", line)
        if found:
            run.append(int(found[1]))
        elif line.strip() and not line.startswith("   ") and run:
            if run != list(range(1, len(run) + 1)):
                bad.append(run)
            run = []
    assert not bad, f"out-of-order numbered lists: {bad}"
