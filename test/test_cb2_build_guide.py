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


def guide_config():
    part = TEXT.split("# Stage K")[1].split("# Stage L")[0]
    blocks = re.findall(r"```ini\n(.*?)```", part, re.S)
    assert blocks, "no ini block in the guide's configuration stage"
    return blocks[0]


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
    cold boot is what confirms it: the NIC handover runs at boot, so a service
    that only works when started by hand passes a restart and fails a boot.

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
    assert "ec_rk_gmac-dwmac" in flat, "J1 does not check the handover ran"
    stage_b = TEXT.split("# Stage B")[1].split("\n# Stage C")[0]
    assert "Stage J1" in stage_b, (
        "Stage B does not tell the reader the host is unproven until the gate"
    )


def test_the_real_time_gate_is_where_the_loop_first_runs():
    """J1 used to carry the real-time checks — no `A.70`, `SCHED_FIFO`, no
    sync-loss lines in the journal — and runs before `printer.cfg` exists.
    Nothing runs the loop then: klippy spawns the endpoint only when it claims
    a node, and a drive sitting in `PREOP` has no SYNC0 to lose. Every one of
    those checks passed with the real-time setup broken. They belong at the
    first step with drives in `OP`, which is Stage L step 3."""
    stage_j = TEXT.split("# Stage J")[1].split("\n# Stage K")[0]
    j1_table = re.search(
        r"\| \| Must hold after the cold boot \|\n(.*?)\n\n", stage_j, re.S
    )[1]
    for vacuous in ("A.70", "chrt", "al_status"):
        assert vacuous not in j1_table, (
            "J1 asks for %s, which cannot fail before the endpoint runs"
            % vacuous
        )
    step3 = TEXT.split("### 3. Real endpoint, motors uncoupled")[1].split(
        "### 4."
    )[0]
    flat = re.sub(r"\s+", " ", step3)
    assert "cold boot" in flat
    assert "warm restart proves nothing" in flat
    for check in (
        "SCHED_FIFO",
        "Cpus_allowed_list",
        "al_status=0x001a",
        "A.70",
    ):
        assert check in flat, "Stage L step 3 does not check %s" % check
    stage_b = TEXT.split("# Stage B")[1].split("\n# Stage C")[0]
    assert "Stage L step 3" in re.sub(r"\s+", " ", stage_b.replace("> ", ""))


AL_STATUS_DOCS = [
    GUIDE,
    ROOT / "docs" / "rewrite" / "ethercat-host-cb2-rk3566.md",
    ROOT / "docs" / "rewrite" / "ethercat-bench-bringup.md",
    ROOT / "docs" / "rewrite" / "ethercat-igh-macb-install.md",
]


@pytest.mark.parametrize("doc", AL_STATUS_DOCS, ids=lambda p: p.stem)
def test_the_sync_loss_grep_matches_what_the_endpoint_prints(doc):
    """Every host page checked for DC sync loss with `grep -c 'al=0x001a'`.
    The endpoint prints `al_status=0x%04x` — `libecrt_igh.c`'s AL dump on a
    working-counter halt — and IgH's own messages read `AL status message
    0x001A`. Nothing prints `al=`, so the check read 0 on a machine latching
    sync loss on every cycle."""
    c_source = (
        ROOT / "rust" / "ethercat-rt" / "csrc" / "libecrt_igh.c"
    ).read_text(encoding="utf-8")
    text = doc.read_text(encoding="utf-8")
    patterns = re.findall(r"grep -c '([^']*0x001a[^']*)'", text)
    assert patterns, "%s no longer checks for sync loss" % doc.name
    for pattern in patterns:
        assert pattern.replace("0x001a", "0x%04x") in c_source, pattern
    assert not re.search(r"\bal=0x", text), "%s still names al=0x" % doc.name


CB2_KERNEL_DOCS = [
    GUIDE,
    ROOT / "docs" / "rewrite" / "ethercat-host-cb2-rk3566.md",
]


@pytest.mark.parametrize("doc", CB2_KERNEL_DOCS, ids=lambda p: p.stem)
def test_the_kernel_image_is_built_from_a_release_that_still_offers_6_12(doc):
    """Both documents cloned Armbian's build system unpinned and said to pick
    a branch landing on 6.12. On `main` the CB2 is offered only 6.18
    (`current`) and 7.2 (`edge`); `v25.11.1` is the last release whose
    rockchip64 `current` is 6.12, and IgH's stmmac set stops at 6.12, so the
    unpinned clone had no branch the rest of Stage B could build against."""
    text = doc.read_text(encoding="utf-8")
    clone = re.search(r"^git clone .*armbian/build.*$", text, re.M)[0]
    assert "--branch v25.11.1" in clone, clone
    compile_cmd = re.search(r"\./compile\.sh[^\n]*", text)[0]
    assert "BRANCH=current" in compile_cmd, compile_cmd
    assert "check what the build offers" not in text


@pytest.mark.parametrize("doc", CB2_KERNEL_DOCS, ids=lambda p: p.stem)
def test_it_does_not_claim_the_cb2_device_tree_is_mainline_at_6_12(doc):
    """`rk3566-bigtreetech-pi2.dts` reached mainline in 6.14. On 6.12 the
    board boots because Armbian carries the file in its own patch set, which
    is why the image has to come from Armbian and not a plain 6.12 tree."""
    flat = re.sub(r"\s+", " ", doc.read_text(encoding="utf-8"))
    assert "`rk3566-bigtreetech-pi2.dts` is in mainline" not in flat
    assert "reached mainline Linux only in 6.14" in flat


def test_the_belt_force_it_quotes_follows_from_the_config():
    """The guide said "a 40 mm pulley", which reads as a diameter. Its force
    figures only hold for 40 mm of belt per turn — `rotation_distance: 40`, a
    20-tooth GT2 pulley — and a reader taking the diameter reading works out
    a third of the force the belt really sees."""
    import math

    rotation_distance_mm = float(
        re.search(r"^rotation_distance: (\d+)", TEXT, re.M)[1]
    )
    rated_nm = float(re.search(r"rated about ([\d.]+) N·m", FLAT)[1])
    radius_m = rotation_distance_mm / 1000.0 / (2.0 * math.pi)
    at_100 = rated_nm / radius_m
    assert "40 mm pulley" not in FLAT
    assert "about %d N" % round(at_100, -2) in FLAT
    assert "%d N" % round(3 * at_100, -2) in FLAT


def realtime_failure_codes():
    """Every code `go_realtime()` and what it calls can return, read from the
    C source rather than from any document's list of them."""
    csrc = ROOT / "rust" / "ethercat-rt" / "csrc"
    source = (csrc / "libecrt_igh.c").read_text(encoding="utf-8")
    header = (csrc / "libecrt.h").read_text(encoding="utf-8")
    values = {
        name: int(value)
        for name, value in re.findall(
            r"#define (EC_RT_ERR_\w+)\s+\((-\d+)\)", header
        )
    }
    bodies = [
        re.search(r"static int %s\(.*?\n\}\n" % fn, source, re.S)[0]
        for fn in ("go_realtime", "hold_cpu_dma_latency")
    ]
    names = set(re.findall(r"return (EC_RT_ERR_\w+);", "".join(bodies)))
    return {name: values[name] for name in names}


def test_every_realtime_requirement_is_granted_and_explained():
    """The endpoint holds `/dev/cpu_dma_latency` at 0 and fails its claim
    with rc=-20 if it cannot open it. The device is root-only and neither
    ambient capability reaches it; B8 granted the capabilities, listed three
    requirements and never mentioned the fourth. The stub never goes
    real-time, so the dry run passed and the first real claim would not."""
    codes = realtime_failure_codes()
    assert set(codes) >= {"EC_RT_ERR_RT_MLOCK", "EC_RT_ERR_RT_QOS"}
    stage_b = TEXT.split("# Stage B")[1].split("\n# Stage C")[0]
    reference = TEXT.split("# Fault quick reference")[1].split("\n# ")[0]
    for name, value in codes.items():
        assert "`rc=%d`" % value in stage_b, "Stage B never explains %s" % name
        assert "`rc=%d`" % value in reference, "no fault row for %s" % name
    assert 'KERNEL=="cpu_dma_latency", MODE="0660"' in stage_b


def test_the_worked_config_carries_what_klippy_refuses_to_start_without():
    """The guide says to replace printer.cfg with this block. It had no
    [printer] section, no nozzle or filament diameter, and neither heater had
    min_temp, max_temp or control — and this file's own parse check supplied
    the [printer] section itself before reading, so the gap could not show.
    Booted in the simulator, klippy refused each in turn before it reached
    the servos; `tools/sim/tests/test_ethercat_world.py` now boots the block
    as written."""
    import configparser

    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
    cfg.read_string(guide_config())
    required = {
        "printer": ["max_velocity", "max_accel"],
        "extruder": [
            "nozzle_diameter",
            "filament_diameter",
            "min_temp",
            "max_temp",
            "control",
        ],
        "heater_bed": ["min_temp", "max_temp", "control"],
    }
    for section, options in required.items():
        assert cfg.has_section(section), "no [%s]" % section
        for option in options:
            assert cfg.has_option(section, option), "[%s] %s" % (
                section,
                option,
            )


def test_the_stub_path_it_gives_is_absolute_and_inside_the_checkout():
    """The worked config's example was `/home/biqu/serval/...`, a user an
    Armbian image built at B1 need not have and a directory B4 never makes —
    B4 checks this fork out in `~/klipper`. Stage L step 1 then gave the path
    relative, and `ethercat_node` passes the option through `abspath` without
    `expanduser`, so a relative path resolves against klippy's working
    directory and `~` is taken literally."""
    import os

    example = re.search(r"^#endpoint: (\S+)$", guide_config(), re.M)[1]
    assert example.startswith("/home/<your-user>/klipper/rust/target/release/")
    assert example.endswith("ethercat-rt-stub")
    assert "cd ~/klipper" in TEXT
    source = (ROOT / "klippy" / "extras" / "ethercat_node.py").read_text()
    assert "os.path.abspath(" in source and "expanduser" not in source
    step1 = TEXT.split("### 1. Stub endpoint, drives off")[1].split("### 2.")[0]
    assert "absolute" in step1
    assert not re.search(r"at `rust/target/release/ethercat-rt-stub`", step1)
    assert os.path.isabs(example.replace("<your-user>", "u"))


@pytest.mark.parametrize("doc", CB2_KERNEL_DOCS, ids=lambda p: p.stem)
def test_the_host_is_built_to_stay_real_time_after_first_boot(doc):
    """Five ways the CB2 host quietly stops being the host the guide built:

    - `nohz_full=3 rcu_nocbs=3` need `CONFIG_NO_HZ_FULL`, which Armbian's
      rockchip64 config leaves off; the kernel ignores both and the isolation
      check still passes, because `isolcpus` works without it.
    - `armbian-hardware-optimize` writes CPU 3 into the `eth0` interrupts'
      affinity for this board family, at every boot, in the background.
    - Armbian ships `ondemand`, and the RK3566's cores share one clock that it
      drops to 408 MHz on a quiet board.
    - The kernel package names are the repository's too, and its build of
      them is 6.18 without RT; `apt upgrade` swaps the kernel unless held.
    - B6 said to install headers "for the branch that was built", which from
      the repository fetches the 6.18 ones."""
    text = doc.read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", text)
    compile_cmd = re.search(r"\./compile\.sh(?:[^\n]*\\\n)*[^\n]*", text)[0]
    for option in (
        "INSTALL_HEADERS=yes",
        "BSPFREEZE=yes",
        "KERNEL_CONFIGURE=yes",
    ):
        assert option in compile_cmd, option
    assert "`CONFIG_NO_HZ_FULL`" in text
    extraargs = re.search(r"^isolcpus=.*$", text, re.M)[0].split()
    for arg in (
        "isolcpus=domain,managed_irq,3",
        "nohz_full=3",
        "rcu_nocbs=3",
        "irqaffinity=0-2",
        "cpufreq.default_governor=performance",
    ):
        assert arg in extraargs, arg
    assert "sudo systemctl mask armbian-hardware-optimize.service" in text
    for check in (
        "cat /sys/devices/system/cpu/nohz_full",
        "grep -lx 3 /proc/irq/*/effective_affinity_list",
        "apt-mark showhold | grep linux-image",
    ):
        assert check in text, check
    assert "/path/to/serval" not in text
    assert "ships them as `linux-headers-*`" not in flat


def test_the_host_stays_lean_and_the_gate_runs_under_its_real_load():
    """The loop shares CPUs 0-2, the memory bus and the one CPU clock with
    everything else on the CB2. A real-time gate passed on an idle board says
    nothing about the board with a web front end and a webcam streaming, and
    the build budget quoted the contributor gate's 19-25 GB for a build that
    leaves about 1 GB — the one number that decides whether an eMMC will do."""
    stage_b = re.sub(
        r"\s+", " ", TEXT.split("# Stage B")[1].split("\n# Stage C")[0]
    )
    assert "Install only what the printer needs" in stage_b
    step3 = re.sub(
        r"\s+",
        " ",
        TEXT.split("### 3. Real endpoint, motors uncoupled")[1].split("### 4.")[
            0
        ],
    )
    assert "not on an idle board" in step3
    budget = stage_b.split("Budget for this before starting it.")[1][:600]
    assert "1.1 GB" in budget
    assert "debug/incremental" not in budget


@pytest.mark.parametrize("doc", CB2_KERNEL_DOCS, ids=lambda p: p.stem)
def test_the_fork_checkout_installs_the_forks_python_requirements(doc):
    """B4 lets KIAUH install mainline Klipper and then checks this fork out
    over it. klippy/webhooks.py imports numpy at startup, which Klipper's
    virtualenv never installed, so klippy would not start."""
    webhooks = (ROOT / "klippy" / "webhooks.py").read_text(encoding="utf-8")
    assert re.search(r"^import numpy$", webhooks, re.M)
    requirements = (ROOT / "scripts" / "klippy-requirements.txt").read_text()
    assert re.search(r"^numpy==", requirements, re.M)
    text = doc.read_text(encoding="utf-8")
    assert (
        "~/klippy-env/bin/pip install -r scripts/klippy-requirements.txt"
        in text
    )


def test_the_fault_reference_explains_the_host_stall_shutdowns():
    """On a host that has never run the loop, a frame-timing or cycle-skip
    shutdown is the likeliest first failure at Stage L step 3, and the table
    listed neither. It has to use klippy's own wording so a reader can find
    the row from the message."""
    source = (ROOT / "klippy" / "extras" / "ethercat_node.py").read_text()
    reference = TEXT.split("# Fault quick reference")[1].split("\n# ")[0]
    for phrase in ("EtherCAT frame-timing fault", "cycle-skip fault"):
        assert phrase in source
        assert phrase in reference
    quantum = int(re.search(r"^CYCLE_US_QUANTUM = (\d+)$", source, re.M)[1])
    assert "cycle_us: 500" in FLAT and 500 % quantum == 0


READERS_VALUES = [
    ("printer", "max_z_velocity"),
    ("printer", "max_z_accel"),
    ("motor motor_z", "rotation_distance"),
    ("motor motor_z", "microsteps"),
    ("motor motor_e0", "rotation_distance"),
    ("motor motor_e1", "rotation_distance"),
    ("extruder", "nozzle_diameter"),
    ("extruder", "filament_diameter"),
    ("extruder", "sensor_type"),
    ("extruder", "max_temp"),
    ("heater_bed", "sensor_type"),
    ("heater_bed", "max_temp"),
    ("axis x", "position_max"),
    ("axis y", "position_max"),
    ("axis z", "position_max"),
    ("tmc2209 motor_z", "run_current"),
    ("tmc2209 motor_e0", "run_current"),
    ("tmc2209 motor_e1", "run_current"),
]


def option_lines(cfg):
    section, lines = None, {}
    for line in cfg.splitlines():
        header = re.match(r"^\[([^\]]+)\]", line)
        if header:
            section = header[1]
            continue
        option = re.match(r"^(\w+):", line)
        if option:
            lines[(section, option[1])] = line
    return lines


def setup_guide_config():
    setup = (ROOT / "docs/rewrite/estun-pronet-markforged-setup.md").read_text()
    part = setup.split("## Part 11")[1].split("## Part 12")[0]
    return re.findall(r"```ini\n(.*?)```", part, re.S)[0]


@pytest.mark.parametrize(
    "cfg", [guide_config(), setup_guide_config()], ids=["cb2", "setup"]
)
def test_values_the_repository_cannot_know_are_marked_as_the_readers(cfg):
    """The Z drive, extruder, thermistors, heater ceilings, stepper currents
    and axis travel were filled in so klippy would start, from the generic
    values in `test/test_configs/`, and one comment presented a guess — that
    `rotation_distance: 8` is a lead screw — as a fact about the machine.
    Nothing here knows that hardware. A wrong thermistor type misreads the
    hotend; a wrong run current cooks a motor. Each such value is marked for
    the reader to replace."""
    lines = option_lines(cfg)
    for key in READERS_VALUES:
        assert "<- yours" in lines[key], lines[key]
    assert "lead screw" not in cfg
