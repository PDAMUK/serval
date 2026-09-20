"""The collated CB2 build guide must stay true to the repository it describes.

`markforged-cb2-complete-build.md` is one document a person follows with a
machine in pieces in front of them. Every command it tells them to type, every
config option it sets and every result code it explains has to exist in the
tree they just built, or the guide strands them at the one moment nothing else
can help.

These checks read the document and compare it against the code, not against the
source documents it was collated from — a guide that agrees with another guide
and disagrees with the code is the failure this file exists to catch.
"""

import pathlib
import pkgutil
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "rewrite" / "markforged-cb2-complete-build.md"
TEXT = GUIDE.read_text(encoding="utf-8")
# Prose wraps and the safety banner is a blockquote, so phrase assertions run
# against a copy with the "> " markers stripped and whitespace flattened —
# otherwise every reflow breaks a test that is about meaning, not layout.
FLAT = re.sub(r"\s+", " ", re.sub(r"^\s*>\s?", "", TEXT, flags=re.M))

PRINTER_SECTION = """[printer]
max_velocity: 300
max_accel: 3000
corner_deviation: 0.04
max_z_velocity: 5
max_z_accel: 100

"""


def guide_config():
    part = TEXT.split("# Stage K")[1].split("# Stage L")[0]
    blocks = re.findall(r"```ini\n(.*?)```", part, re.S)
    assert blocks, "no ini block in the guide's configuration stage"
    return PRINTER_SECTION + blocks[0]


def read_topology():
    from klippy import configfile

    _limits, _axes, kin, _consumed = (
        configfile._config_doc.read_motion_settings(guide_config())
    )
    return kin


# ---------------------------------------------------------------- the config


def test_the_worked_config_parses_through_the_real_reader():
    assert read_topology() is not None


def test_the_machine_it_describes_is_the_machine_it_configures():
    """Markforged, X and Y on servos, Z on a stepper. If this ever collapses
    the guide has stopped describing this build."""
    kind, lanes, followers = read_topology()
    assert kind == "markforged"
    drives = {name: drive for _idx, name, _motors, drive in lanes}
    assert drives == {"x": "servo", "y": "servo", "z": "stepper"}


def test_the_extruder_is_one_follower_axis_carrying_both_motors():
    """Two motors on one axis is what makes the tandem pair one trajectory.
    Two axes would let them drift apart, which is the thing the guide promises
    cannot happen."""
    _kind, _lanes, followers = read_topology()
    assert len(followers) == 1
    name, motors, _idx = followers[0]
    assert name == "e"
    assert len(motors) == 2


def test_every_section_the_config_uses_can_actually_load():
    """A documented section whose module is absent fails startup with
    `Module '<name>' not found`, after the machine is already wired."""
    parse_time = {
        "printer",
        "mcu",
        "kinematics",
        "motor",
        "axis",
        "extruder",
        "heater_bed",
        "fan",
    }
    extras = {
        m.name for m in pkgutil.iter_modules([str(ROOT / "klippy" / "extras")])
    }
    used = {
        m.group(1).split()[0]
        for m in re.finditer(r"^\[([^\]]+)\]", guide_config(), re.M)
    }
    missing = sorted(used - extras - parse_time)
    assert not missing, "sections with no module: %s" % (missing,)


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_every_endstop_is_pulled_up(axis):
    """An `endstop_pin` without `^` configures the STM32 input with no pull-up,
    so a switch wired to ground floats the moment it opens. It is invisible
    when wrong and reads as a flaky switch."""
    section = guide_config().split("[axis %s]" % axis)[1].split("\n[")[0]
    pin = re.search(r"endstop_pin:\s*(\S+)", section)
    assert pin, "no endstop_pin on [axis %s]" % axis
    assert pin.group(1).startswith("^"), (
        "[axis %s] endstop_pin %s has no pull-up" % (axis, pin.group(1))
    )


def test_the_halt_input_is_wired_to_fail_safe():
    """`^PF1` with an NC contact halts on a press AND on a severed wire. An
    inverted pin halts on a press and does nothing at all with the wire off,
    and the guide must not be the thing that suggests it."""
    section = TEXT.split("[emergency_stop estop]")[1].split("\n```")[0]
    pin = re.search(r"^pin:\s*(\S+)", section, re.M)
    assert pin, "the emergency stop section sets no pin"
    assert pin.group(1) == "^PF1", (
        "the halt input is %s, not the fail-safe ^PF1" % pin.group(1)
    )


# ------------------------------------------------------- code the guide names


def test_every_servo_command_it_tells_you_to_type_exists_here():
    """The calibration macros live in serval-dashboard, not in this
    repository. A guide that mixes the two sends someone hunting a build
    failure that is really a missing install."""
    registered = set()
    for path in (ROOT / "klippy").rglob("*.py"):
        registered.update(
            re.findall(
                r'register_(?:mux_)?command\(\s*"([A-Z_0-9]+)"',
                path.read_text(encoding="utf-8"),
            )
        )
    typed = set(re.findall(r"`(SERVO_[A-Z_]+|QUERY_[A-Z_]+)[ `]", TEXT))
    # Commands the guide explicitly attributes to serval-dashboard.
    external = {"SERVO_FIT_DYNAMICS"}
    missing = sorted(typed - registered - external)
    assert not missing, (
        "the guide types commands this repository does not register: %s"
        % (missing,)
    )


def test_commands_it_calls_external_really_are_absent_here():
    """The other direction: if a dashboard macro ever lands in this tree, the
    paragraph telling the reader to install it elsewhere becomes wrong."""
    registered = "\n".join(
        p.read_text(encoding="utf-8") for p in (ROOT / "klippy").rglob("*.py")
    )
    assert '"SERVO_FIT_DYNAMICS"' not in registered, (
        "SERVO_FIT_DYNAMICS now ships here; the guide still sends readers to "
        "serval-dashboard for it"
    )


@pytest.mark.parametrize(
    "option", ["pdo_touch_probe", "pdo_digital_io", "pdo_following_error"]
)
def test_the_pdo_escape_hatches_are_options_the_node_actually_reads(option):
    """These three are the documented remedy for a refused map (rc=-6). An
    option the code does not read would leave that remedy inert."""
    node = (ROOT / "klippy" / "extras" / "ethercat_node.py").read_text(
        encoding="utf-8"
    )
    assert re.search(r'getboolean\(\s*"' + option + '"', node), (
        "ethercat_node does not read %s" % option
    )
    assert option in TEXT, "the guide no longer documents %s" % option


def test_every_result_code_it_explains_is_a_real_endpoint_code():
    """A fault table is read at the worst possible moment. A code that does not
    exist sends someone looking for a fault the endpoint cannot raise."""
    header = (ROOT / "rust" / "ethercat-rt" / "csrc" / "libecrt.h").read_text(
        encoding="utf-8"
    )
    real = {
        int(v)
        for v in re.findall(r"#define EC_RT_ERR_\w+\s+\((-\d+)\)", header)
    }
    assert real, "no EC_RT_ERR_* codes found in libecrt.h"
    cited = {int(v) for v in re.findall(r"`rc=(-\d+)`", TEXT)}
    assert cited, "the guide cites no result codes at all"
    assert cited <= real, "codes the endpoint cannot return: %s" % (
        sorted(cited - real),
    )


@pytest.mark.parametrize(
    "target", ["ethercat-endpoint-hw", "ethercat-stub", "setcap-ethercat"]
)
def test_every_make_target_it_names_exists(target):
    makefile = (ROOT / "Makefile.rust").read_text(encoding="utf-8")
    assert re.search(r"^%s:" % re.escape(target), makefile, re.M), (
        "Makefile.rust has no %s target" % target
    )
    assert target in TEXT


@pytest.mark.parametrize(
    "path",
    [
        "tools/ethercat-dwmac-rk/generate.py",
        "klippy/extras/emergency_stop.py",
        "rust/ethercat-rt/csrc/pdo_map.h",
        "rust/ethercat-rt/src/torque.rs",
        "rust/ethercat-rt/src/endpoint/commands.rs",
        "rust/ethercat-rt/src/endpoint/cycle.rs",
        "klippy/extras/ethercat_node.py",
        "scripts/servo_capture.py",
    ],
)
def test_every_file_the_fork_comparison_names_exists(path):
    """The 'what this fork adds' section is only useful if a reader can open
    what it points at."""
    assert (ROOT / path).is_file(), (
        "%s is named in the guide and is gone" % path
    )
    assert path.rsplit("/", 1)[-1] in TEXT


def test_the_torque_ceiling_tells_the_config_field_from_the_drive():
    """400 is the config field's validation limit; the drive honours 0-300.
    Conflating them is how someone sets a number the machine silently clamps."""
    from klippy.extras.servo_axis import MAX_TORQUE_PCT_6072H

    assert MAX_TORQUE_PCT_6072H == 400.0
    assert "0 to 300 %" in FLAT
    assert "Treat 300 as the real ceiling" in FLAT


def test_the_homing_limits_match_their_defaults():
    """The guide states both defaults. A drift here means someone plans a
    bring-up around a torque limit the code does not apply."""
    servo = (ROOT / "klippy" / "extras" / "servo_axis.py").read_text(
        encoding="utf-8"
    )
    assert re.search(r'"homing_following_error",\s*2\.5', servo)
    assert re.search(r'"homing_max_torque",\s*\n?\s*50\.0', servo)
    assert "2.5 mm" in FLAT and "50 %" in FLAT


def test_the_shutdown_controlword_is_the_one_the_endpoint_writes():
    """0x0006 is Shutdown, not Quick Stop. The guide leans on that distinction
    to explain why there is no ramp, so it must not drift from the code."""
    shim = (ROOT / "rust" / "ethercat-rt" / "csrc" / "libecrt_igh.c").read_text(
        encoding="utf-8"
    )
    disable = shim.split("void ec_rt_disable_all(void)")[1].split("\n}")[0]
    assert "0x0006" in disable
    assert "for (int i = 0; i < 100; i++)" in disable, (
        "the disable hold is no longer 100 cycles"
    )
    assert "`0x0006`" in FLAT
    assert "for 100 cycles" in FLAT


# --------------------------------------------------------- the document itself


def test_it_says_it_is_a_personal_project_and_not_to_be_followed():
    """The one paragraph that must never be edited out."""
    banner = FLAT.split("Read this before anything else")[1].split(
        "Safety rules that apply"
    )[0]
    assert "personal project" in banner.lower()
    assert "Do not follow this guide" in banner
    assert "no STO" in banner
    assert "has not been reviewed" in banner


def test_it_does_not_claim_the_cb2_path_has_been_run():
    """Every version of this claim has to stay hedged: the driver compiles and
    has never been loaded."""
    assert "never been run" in TEXT or "never been loaded" in TEXT
    assert "builds; never run" in TEXT


def test_it_names_the_cb2_native_driver_and_not_the_pi_one():
    """`ec_macb` is the Pi 5's Cadence GEM driver and does not apply to an
    RK3566. Naming it as this build's driver sends someone down a path that
    cannot work."""
    assert "ec_dwmac-rk" in TEXT
    for match in re.finditer(r"ec_macb", TEXT):
        window = TEXT[max(0, match.start() - 200) : match.end() + 200]
        assert re.search(r"Pi 5|RP1|Cadence|pi5|alternative", window), (
            "ec_macb is named without saying it is the Pi 5's driver"
        )


def test_the_printer_is_not_told_to_run_the_contributor_gate():
    """`ci.sh` on a CB2 is an hour of A55, a target directory the eMMC cannot
    hold, and contention for the very core the DC loop was given."""
    assert re.search(r"[Dd]o not run `?\./scripts/ci\.sh", TEXT), (
        "the guide no longer warns against running the gate on the printer"
    )
    for block in re.findall(r"```sh\n(.*?)```", TEXT, re.S):
        assert "ci.sh" not in block, (
            "a shell block on the printer's page runs ci.sh:\n%s" % block
        )


def test_every_repo_relative_link_resolves():
    here = GUIDE.parent
    broken = []
    for label, target in re.findall(
        r"\[([^\]]+)\]\((\.\./[^)#]+|[A-Za-z0-9_.\-]+\.md)\)", TEXT
    ):
        if not (here / target).resolve().exists():
            broken.append("%s -> %s" % (label, target))
    assert not broken, "broken links: %s" % (broken,)


def test_every_in_page_anchor_resolves():
    """The guide cross-references its own diagrams from the stages. A stale
    anchor is a reader scrolling for a drawing that moved — and `ci.sh docs`
    fails the build over it, so this mirrors python-markdown's slugify rather
    than inventing its own."""

    def slug(heading):
        text = re.sub(r"[`*]", "", heading)
        text = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.U)
        return re.sub(r"[-\s]+", "-", text.strip())

    slugs = {slug(h) for h in re.findall(r"^#{1,6} (.+)$", TEXT, re.M)}
    dangling = [
        a for a in re.findall(r"\]\(#([\w-]+)\)", TEXT) if a not in slugs
    ]
    assert not dangling, "anchors with no heading: %s" % (dangling,)


def test_it_tells_the_latching_button_from_the_unlatched_circuit():
    """The RS 139-972 is a latching, key-release button: pressed, it stays in
    with both NC contacts held open, and only a key turns it back. The coil
    circuit behind it does not latch — no safety relay holds the contactor
    dropped out — so the key is the reset and main power returns the instant
    it turns.

    Both source documents said "Nothing latches" while their own bill of
    materials called the part latching. The distinction is not pedantry: it
    decides whether pocketing the key stops someone else re-energising the
    enclosure."""
    assert "Nothing latches" not in FLAT, (
        "this contradicts the bill of materials, which lists a latching "
        "key-release button"
    )
    assert "Latching, key release" in FLAT, (
        "the parts list no longer says the button latches and takes a key"
    )
    assert "key release" in FLAT and "cannot be twisted back" in FLAT
    assert (
        "There is no safety relay holding the contactor dropped out" in FLAT
    ), (
        "the guide no longer says the coil circuit is the half that does "
        "not latch"
    )
    assert "the key is the reset" in FLAT.lower()
    assert "take the key out and nobody restores power" in FLAT.lower()


def test_it_does_not_let_the_key_stand_in_for_the_isolator():
    """A key in a pocket stops someone restoring main power. It does not make
    the enclosure dead: control power at L1C/L2C is never interrupted, by
    design, so the drives can be halted cleanly. Anyone who reads the key as
    isolation reaches into a live enclosure."""
    assert "key out is an interlock" in FLAT.lower()
    assert "the isolator locked off is isolation" in FLAT.lower()
    assert "not a lockable disconnector" in FLAT
    assert "live at 230 V the whole time the stop was pressed" in FLAT


def test_the_stop_button_has_no_normally_open_contact():
    """The same RS family runs to a 2 NC + 1 NO variant. An NO contact on PF1
    is silent when the wire comes off, which is the one failure the wiring is
    chosen to avoid — so the guide has to say why that variant is not used."""
    row = [
        line
        for line in TEXT.splitlines()
        if line.startswith("| Emergency stop |")
    ]
    assert row, "no emergency stop row in the bill of materials"
    assert "1 NC/1 NC" in row[0], "the stop no longer specifies two NC contacts"
    assert "2 NC + 1 NO variant" in FLAT, (
        "the guide no longer warns off the variant with an NO contact"
    )


def test_the_separation_rule_names_cables_not_categories():
    """ "Keep power and signal 300 mm apart" is not actionable on a machine
    smaller than 300 mm. The reader needs to know which runs are which, so the
    rule names every aggressor and every victim on this build — and the one
    pairing distance cannot fix: a motor's power cable and its own encoder
    cable leave the same drive, reach the same motor, and share a drag chain.

    Scoped to the section, not the document: `B1`/`B2` appears in the drive
    terminal diagram and in Stage E10 as well, so a whole-file search passes
    even after the separation rule stops naming it."""
    section = TEXT.split("**Cable separation")[1].split("\n### ")[0]
    assert "300 mm" in section
    for cable in ["U`/`V`/`W", "B1`/`B2", "PF5", "Motor3 / Motor5 / Motor6"]:
        assert cable in section, "noisy cable the rule never names: %s" % cable
    for cable in ["CN2", "EtherCAT patch leads", "^PF1", "PB0"]:
        assert cable in section, (
            "sensitive cable the rule never names: %s" % cable
        )
    flat = re.sub(r"\s+", " ", section)
    assert "same motor" in flat, (
        "the rule never says the motor power and encoder cables share a route"
    )
    assert "BTB socket and the USB link" in flat, (
        "the rule no longer says the MCU link is not an external run"
    )


def test_the_tuning_stage_says_where_a_tuned_value_lives():
    """Both routes push to drive RAM; nothing writes EEPROM implicitly. So a
    `SERVO_PARAM SET` evaporates on the next restart while a `params:` entry
    comes back, because klippy re-pushes it every claim. Without that, a long
    tuning session at the console is lost and the reader has no documented way
    to persist deliberately."""
    # Split on the next top-level heading, not on "\n# " — the config
    # examples contain comment lines that start the same way.
    stage = TEXT.split("# Stage M")[1].split("\n# Fault quick reference")[0]
    flat = re.sub(r"\s+", " ", stage)
    assert "0x1010" in flat, (
        "the tuning stage never names the store-parameters object"
    )
    assert "never persists implicitly" in flat
    assert "Survives a **drive** power cycle?" in flat, (
        "the tuning stage no longer distinguishes the two routes by what "
        "survives what"
    )
    assert "fails the claim" in flat, (
        "the tuning stage does not warn that a rejected params: write stops "
        "the machine starting"
    )
    assert "Objects wider than 4 bytes" in flat


def test_the_host_is_gated_on_a_cold_boot_before_the_config_stage():
    """The CB2 host page ends with "confirm the bus before trusting it", and a
    cold boot is what confirms it: `ec_generic` and a PREEMPT-not-PREEMPT_RT
    kernel both hold cadence on an idle bench and drop frames under boot load.

    The collation had that only in the closing done-criteria, hundreds of
    lines after the point where it decides whether to carry on — so a reader
    built the host, wired the machine, and met the failure at the most
    expensive moment. The gate belongs before the config stage, which is the
    first place it can run: the host is built with no drives wired."""
    stage_j = TEXT.split("# Stage J")[1].split("\n# Stage K")[0]
    flat = re.sub(r"\s+", " ", stage_j)
    assert "cold boot" in flat.lower(), (
        "Stage J does not gate on a cold boot, so nothing proves Stage B "
        "before printer.cfg is written"
    )
    assert "A.70" in flat, "the gate does not say what a failure looks like"
    assert "warm restart proves nothing" in flat
    # And Stage B has to say it is not finished.
    stage_b = TEXT.split("# Stage B")[1].split("\n# Stage C")[0]
    assert "Stage J1" in stage_b, (
        "Stage B does not tell the reader the host is unproven until the gate"
    )
