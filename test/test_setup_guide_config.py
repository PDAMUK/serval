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
def guide_config():
    text = GUIDE.read_text(encoding="utf-8")
    part = text.split("## Part 11 — Configuration")[1].split("## Part 12")[0]
    blocks = re.findall(r"```ini\n(.*?)```", part, re.S)
    assert blocks, "no ini block found in the guide's configuration part"
    return blocks[0]


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
    return re.findall(r"\*\*(\d{3}-\d{3,4})\*\*", text)


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
    table = table.split("\n### ")[0]
    rows = [line for line in table.splitlines() if line.startswith("| ")][2:]
    assert rows, "the substitution table is empty"
    for row in rows:
        assert "**and**" in row, f"does not say what it replaces: {row}"
        assert " one" in row, f"no net count stated: {row}"


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
    three digits, a hyphen, then three or four — nothing else parses as one."""
    codes = re.findall(r"RS \*\*([^*]+)\*\*", buy_section())
    assert codes, "the buy tables carry no RS stock numbers"
    bad = [code for code in codes if not re.fullmatch(r"\d{3}-\d{3,4}", code)]
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
    """A combination is only a substitution if both parts it stands in for are
    themselves listed. If either is renamed, the claim dangles."""
    needed = {row[0].lower() for row in buy_table("**Needed.**")}
    combinations = buy_table("**One part instead of two.**")
    assert combinations, "the combination table is empty"
    for row in combinations:
        replaced = re.findall(r"the ([\w ]+?) \*\*and\*\* the ([\w ]+)", row[1])
        assert replaced, f"does not name two parts: {row[1]}"
        for name in replaced[0]:
            assert name.strip().lower() in needed, (
                f"{name!r} is not a needed row"
            )


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


def test_no_stock_code_is_a_split_six_digit_one():
    """RS has both six- and seven-digit codes, and a product URL pads the six
    to seven with a leading zero. Splitting 0654748 as 065-4748 rather than
    654-748 orders a different part and reads as plausible either way. A real
    seven-digit code never starts with a zero, so one that does is the slip."""
    text = GUIDE.read_text(encoding="utf-8")
    bad = [c for c in stock_codes(text) if re.fullmatch(r"0\d\d-\d{4}", c)]
    assert not bad, f"six-digit codes split in the wrong place: {bad}"


def test_the_load_figure_is_stated_once_and_derives_from_the_rating():
    """Every sizing decision in the guide is made against one number — the
    inlet, the filter derating, the cable, the headroom under a 13 A plug. A
    second rounding of it appearing anywhere is how two sections stop
    agreeing, and a stale one outlives the rating it came from."""
    text = GUIDE.read_text(encoding="utf-8")
    prose = "\n".join(
        line for line in text.splitlines() if "ampacity" not in line
    )
    stated = set(re.findall(r"\b(7\.\d+) A\b", prose))
    assert stated == {"7.83"}, f"more than one rounding in use: {stated}"

    kva = float(re.search(r"\*\*([\d.]+) kVA per drive\*\*", text)[1])
    volts = int(re.search(r"(\d+) V the supply sits at the top", text)[1])
    assert abs(7.83 - 2 * kva * 1000 / volts) < 0.005, (
        f"{kva} kVA per drive at {volts} V is not 7.83 A for the pair"
    )


def test_the_native_nic_driver_is_named_consistently():
    """`ec_dwmac` and `ec_dwmac-rk` are not the same module name, and a reader
    following the host page looks for whichever spelling they were given."""
    text = GUIDE.read_text(encoding="utf-8")
    spellings = set(re.findall(r"ec_dwmac[\w-]*", text))
    assert spellings == {"ec_dwmac-rk"}, spellings


def test_the_belt_warning_points_at_the_part_that_couples_them():
    """The safety note defers the belts to a numbered part. When a part is
    inserted or the step moves, the number silently stops matching."""
    text = GUIDE.read_text(encoding="utf-8")
    deferred = int(re.search(r"Keep belts uncoupled until Part (\d+)", text)[1])
    couples = [
        int(re.match(r"## Part (\d+)", section)[1])
        for section in re.split(r"(?=^## Part )", text, flags=re.M)
        if section.startswith("## Part ") and "Couple the belts" in section
    ]
    assert couples == [deferred], (
        f"belts are coupled in {couples}, not {deferred}"
    )


def test_ec_only_drive_values_are_recorded_as_unverified():
    """These come from the -EC variant and the base ProNet manual contradicts
    or omits them. Stating them without saying so is how a guess hardens into
    a fact nobody rechecks."""
    text = GUIDE.read_text(encoding="utf-8")
    unverified = text.split("## Still unverified on hardware")[1]
    for value in ("Pn006.0 = 4", "A.70", "A.71"):
        assert value in unverified, f"{value} is asserted but never qualified"


def test_the_suppressor_names_the_contactor_the_bill_actually_lists():
    """Whether a coil suppressor is needed depends on the contactor in front of
    it — ABB's plain ESB20 has no built-in protection and the ESB20-20N-06
    does. If the contactor row changes and the reason under the suppressor does
    not, the guide keeps arguing about a part nobody is buying."""
    contactor = next(
        row for row in buy_table("**Needed.**") if row[0] == "Contactor"
    )
    part = re.search(r"`([\w.-]+)`", contactor[2])[1]
    suppressor = next(
        row for row in buy_table("**Optional.**") if row[0] == "Coil suppressor"
    )
    assert part in suppressor[3], (
        f"the reason to skip it does not mention {part}: {suppressor[3]}"
    )


def test_the_rail_budget_adds_up():
    """Swapping a part for a wider one changes the rail length, and the total
    is the number someone cuts metal against."""
    section = mains_section().split("### Fitting it in a printer enclosure")[1]
    rows = re.findall(r"^\| (.+?) \| (\**\d+\**) \|$", section, re.M)
    assert len(rows) >= 5, rows
    stated = int(rows[-1][1].strip("*"))
    assert "Rail needed" in rows[-1][0], rows[-1]
    assert sum(int(count) for _, count in rows[:-1]) == stated, rows
    millimetres = int(re.search(r"\*\*about (\d+) mm\*\*", section)[1])
    assert 17.5 * stated <= millimetres <= 18 * stated, (
        f"{stated} modules is not {millimetres} mm"
    )


def test_the_halt_button_pin_matches_the_wiring_table():
    """The pin appears in Part 8's table and again in the config. Changing one
    leaves the halt wired to whatever else is on the other pin."""
    text = GUIDE.read_text(encoding="utf-8")
    row = re.search(r"^\| Emergency stop signal \| `(\w+)` \|", text, re.M)
    assert row, "Part 8 no longer assigns a pin to the emergency stop"
    configured = re.search(r"\[emergency_stop estop\]\npin: ([^\n]+)", text)
    assert configured, "the config no longer carries the estop button"
    assert configured[1].lstrip("^") == row[1], (
        f"{configured[1]} is not the {row[1]} the wiring table gives"
    )


def test_the_printer_is_not_told_to_run_the_contributor_gate():
    """Part 11's verification happens on the machine running klippy, so it has
    to be something that machine can do. `ci.sh quick` is not: it compiles and
    runs every crate's test binaries, wants a rust/target reaching 19-25 GB,
    and on a CB2 competes with the DC loop for the core Part 2 isolated. The
    gate belongs on a development machine."""
    text = GUIDE.read_text(encoding="utf-8")
    part = text.split("## Part 11 — Configuration")[1].split("## Part 12")[0]
    instruction = part.split("**Verify.**")[1].split("\n\n")[0]
    assert "ci.sh" not in instruction, (
        f"Part 11 tells the printer to run the gate: {instruction.strip()}"
    )
    assert "klippy" in instruction.lower(), (
        "Part 11's verification no longer names what the printer should do"
    )


def test_the_cb2_page_refuses_the_gate_on_the_printer():
    """The CB2 must build on-device — the hw endpoint links libethercat and
    cannot be cross-compiled — which puts a full cargo toolchain on a board
    with 2-4 GB of RAM and an eMMC smaller than rust/target. That makes it
    exactly the machine someone would run the test suite on by habit."""
    cb2 = (GUIDE.parent / "ethercat-host-cb2-rk3566.md").read_text(
        encoding="utf-8"
    )
    assert re.search(r"[Dd]o not run[^\n]{0,40}ci\.sh", cb2), (
        "the CB2 page no longer refuses the gate in so many words"
    )
    for block in re.findall(r"```sh\n(.*?)```", cb2, re.S):
        assert "ci.sh" not in block, (
            f"the CB2 page hands the reader a command that runs the gate on "
            f"the printer:\n{block.strip()}"
        )


def test_every_switch_input_is_pulled_up():
    """A bare endstop_pin configures the STM32 input with no pull-up, so a
    switch to ground floats as soon as it opens and the axis homes against
    noise. BigTreeTech's own published config writes ^PF4, ^PF3 and ^PF2, and
    the pin-name test above passes either way because "PF4" is a substring of
    "^PF4" — which is how the prefix went missing in the first place."""
    declared = re.findall(r"^endstop_pin: (\S+)", guide_config(), re.M)
    assert len(declared) == 3, f"expected three endstops, found {declared}"
    for pin in declared:
        assert pin.startswith("^"), f"endstop_pin: {pin} has no pull-up"


def test_the_leakage_remedy_is_not_a_delayed_device():
    """ESTUN: "always use a fast-response type or one designed for PWM
    inverters. Do not use a time-delay type." A delayed RCD holds a residual
    current through the window an instantaneous one clears it in, so proposing
    one as the answer to a nuisance trip contradicts the drive manual on the
    protective device the rest of Part 5 is built around."""
    section = mains_section()
    assert "time-delay" in section or "time-delayed" in section, (
        "the manual's prohibition is no longer stated at all"
    )
    for sentence in re.split(r"(?<=[.!?])\s+", section):
        if "time-delayed" in sentence or "time-delay" in sentence:
            assert "not" in sentence.lower() or "do not" in sentence.lower(), (
                f"a delayed device is recommended rather than refused: "
                f"{sentence.strip()}"
            )


def test_the_torque_ceiling_is_the_drives_and_not_the_config_fields():
    """max_torque accepts 400 because that is the CiA 402 6072h ceiling, but
    ProNet's Pn401/Pn402 run 0-300%, so anything above 300 is clamped by the
    drive and the configured number stops describing the machine."""
    text = GUIDE.read_text(encoding="utf-8")
    block = text.split("The two drive limits")[1].split("\n\n")[0]
    assert "300" in block, "the drive's own 0-300% limit is not stated"
    assert "Pn401" in block or "Pn402" in block, (
        "nothing names the parameter that actually does the clamping"
    )


def test_the_halt_input_is_wired_to_fail_safe():
    """An NC contact on a pulled-up input reads the same pressed as it does
    with the wire off, so a broken signal wire stops the machine. Inverting it
    for an NO contact makes that same fault silent."""
    text = GUIDE.read_text(encoding="utf-8")
    pin = re.search(r"\[emergency_stop estop\]\npin: ([^\n]+)", text)[1]
    assert pin.startswith("^"), f"{pin} has no pull-up"
    assert "!" not in pin, f"{pin} is inverted, which is the NO wiring"
    assert "[gcode_button estop]" not in text, (
        "the halt is back on the G-Code queue"
    )


def test_the_guide_names_the_controlword_the_endpoint_actually_writes():
    """The guide tells the reader the emergency stop ends in CiA 402 Shutdown,
    0x0006, and that Pn004.0 decides whether the drive answers that with the
    dynamic brake. Changing the endpoint's disable path to Quick Stop or
    anything else would make that account wrong without touching the guide."""
    source = (
        GUIDE.parents[2] / "rust" / "ethercat-rt" / "csrc" / "libecrt_igh.c"
    ).read_text(encoding="utf-8")
    body = source.split("void ec_rt_disable_all(void)")[1].split("\n}")[0]
    written = set(re.findall(r"controlword = (0x[0-9A-Fa-f]+)", body))
    assert written == {"0x0006"}, f"disable_all now writes {written}"
    section = mains_section()
    assert "`0x0006`" in section
    assert "Pn004.0" in section


def test_dead_is_reserved_for_the_electrical_sense():
    """ "Dead" is the safe-isolation term of art — made dead, proved dead — and
    the document says so once and then relies on it. A drive that has failed is
    destroyed or faulted. Letting one word carry both states is how "the stop
    does not make the drive dead" comes to read as "the stop does not break
    the drive", which is the opposite of the warning intended."""
    text = GUIDE.read_text(encoding="utf-8")
    assert '**"Dead" in this document means electrically dead**' in text
    broken = re.findall(r"\bdead (drive|endpoint|motor|board|module)s?\b", text)
    assert not broken, f"'dead' used of a broken component: {broken}"


def test_the_halt_test_is_where_klippy_actually_runs():
    """Part 5 is mains bring-up: no config, no klippy. A step there that asks
    for QUERY_EMERGENCY_STOP cannot be performed when it is read. Part 5 now
    points forward instead, and this holds the pointer to the step that really
    carries the test — renumbering Part 12 is what breaks it."""
    text = GUIDE.read_text(encoding="utf-8")
    mains = mains_section()
    assert "QUERY_EMERGENCY_STOP" not in mains, (
        "Part 5 asks for a command that needs the Part 11 config"
    )
    pointed = int(re.search(r"\*\*Part 12, step (\d+)\*\*", mains)[1])

    part12 = text.split("## Part 12")[1].split("\n## ")[0]
    steps = re.findall(r"^(\d+)\. (.*(?:\n(?!\d+\. |## ).*)*)", part12, re.M)
    carrying = [
        int(number) for number, body in steps if "QUERY_EMERGENCY_STOP" in body
    ]
    assert carrying == [pointed], (
        f"halt tested in {carrying}, pointed at {pointed}"
    )


def test_the_guide_does_not_present_the_query_as_a_live_reading():
    """An MCU shutdown drops every user timer, the button sampler among them,
    so the value freezes at whatever caused the stop. Someone told it is live
    would hold the button, release it, see no change and conclude the wiring
    is broken."""
    text = GUIDE.read_text(encoding="utf-8")
    assert "not a live reading" in text
    assert "FIRMWARE_RESTART" in text.split("not a live reading")[1][:600]


def test_the_guide_tells_the_latching_button_from_the_unlatched_circuit():
    """Two things get called latching and only one of them is. The 139-972
    button latches and is key release — it cannot be twisted or knocked back.
    The coil circuit does not: no safety relay holds the contactor dropped
    out, so the key is the reset and power returns the instant it turns.

    The guide said "Nothing latches" while its own bill of materials called
    the part latching, which is a flat contradiction and sells the key short:
    key-out is a real interlock against someone else restoring power. It is
    still not isolation, and the guide has to say both."""
    flat = re.sub(r"\s+", " ", GUIDE.read_text(encoding="utf-8"))
    assert "Nothing latches" not in flat, (
        "the guide contradicts its own bill of materials, which lists a "
        "latching key-release button"
    )
    assert "key release" in flat, (
        "the guide no longer says the part is key release"
    )
    assert "The button latches" in flat
    assert "The coil circuit does not" in flat
    assert "Take the key out and nobody restores power" in flat
    assert "not a lockable disconnector" in flat, (
        "the guide no longer says key-out is not isolation"
    )
