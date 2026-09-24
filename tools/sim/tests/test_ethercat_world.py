"""An EtherCAT world: X and Y on servos, Z on a stepper, drives off.

This is Part 12 step 1 of the build guide made automatic — "stub endpoint,
drives off, klippy must reach ready", the step that proves planner to bridge to
transport with zero hardware risk. The simulator had no EtherCAT world at all
before this, so the only thing exercising that seam was a person following the
guide with a machine in pieces.

`ethercat-rt-stub` answers the endpoint protocol with nothing behind it, and
klippy spawns it itself at claim time, so the world needs no master and no NIC
— only the binary at the path `endpoint:` names.

The `sim_unit` tests below need none of that and run in the ordinary suite;
the world tests need the firmware ELF and the image, and run in CI.
"""

import pathlib
import re

import pytest

from tools.sim import configs

REPO = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.sim_unit
def test_the_config_declares_two_servo_lanes_and_one_stepper():
    """The bench's own shape: a lane's motors are all one drive type, but
    lanes may differ. If this ever collapses to a single drive type the world
    has stopped testing the mixed case the machine actually is."""
    from klippy import configfile

    cfg = configs.ethercat_servo_config(
        "/dev/pts/0", "/tmp/gcode", "/tmp/ec.sock"
    )
    _limits, _axes, kin, _consumed = (
        configfile._config_doc.read_motion_settings(cfg)
    )
    kind, lanes, _followers = kin
    assert kind == "cartesian"
    drives = {name: drive for _idx, name, _motors, drive in lanes}
    assert drives == {"x": "servo", "y": "servo", "z": "stepper"}


@pytest.mark.sim_unit
def test_the_config_points_at_the_stub_by_default():
    """klippy spawns whatever `endpoint:` names. Pointing at the hw endpoint
    by accident would try to open a real master inside the container."""
    cfg = configs.ethercat_servo_config(
        "/dev/pts/0", "/tmp/gcode", "/tmp/ec.sock"
    )
    assert f"endpoint: {configs.ETHERCAT_STUB_BINARY}" in cfg
    assert configs.ETHERCAT_STUB_BINARY.endswith("ethercat-rt-stub")


@pytest.mark.sim_unit
def test_extra_node_options_land_inside_the_ethercat_section():
    """The PDO group options are what a reader reaches for when a drive
    refuses the map, so the world has to be able to set them."""
    cfg = configs.ethercat_servo_config(
        "/dev/pts/0",
        "/tmp/gcode",
        "/tmp/ec.sock",
        extra_node_options="pdo_touch_probe: False\npdo_digital_io: False\n",
    )
    section = cfg.split("[ethercat_node node_xy]")[1].split("[motor")[0]
    assert "pdo_touch_probe: False" in section
    assert "pdo_digital_io: False" in section


@pytest.mark.sim_unit
def test_the_sim_image_builds_and_installs_the_stub():
    """The world is only runnable if the image carries the binary. Both halves
    matter: built in the rust stage, and copied to the path the config names."""
    dockerfile = (REPO / "tools" / "sim" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "--bin ethercat-rt-stub" in dockerfile, (
        "the rust stage no longer builds the stub"
    )
    # Checked as a COPY destination, not merely as a string present somewhere:
    # the same path appears in the build stage's `cp ... /artifacts/`, so a
    # substring test cannot tell "built and installed" from "built only".
    installs = [
        block
        for block in dockerfile.split("COPY --from=rust-build")[1:]
        if configs.ETHERCAT_STUB_BINARY in block.split("COPY")[0]
    ]
    assert installs, (
        "the stub is built but never COPYed to %s, so the world would spawn "
        "nothing" % configs.ETHERCAT_STUB_BINARY
    )


@pytest.mark.needs_elf
def test_the_endpoint_is_spawned_and_claimed(sim_world, tmp_path):
    """Part 12 step 1. The fixture already waits for klippy to reach ready and
    fails the test if it does not, so re-asserting that proves nothing — what
    is specific to this world is that the claim happened at all: klippy spawned
    the endpoint binary and it created its socket.

    The name is kept short on purpose. A unix socket path is capped near 108
    bytes and pytest's tmp_path is already most of one."""
    socket_path = str(tmp_path / "ec.sock")
    sim_world(
        lambda w: configs.ethercat_servo_config(
            w.h7_pty, str(w.gcode_dir), socket_path
        ),
        dual_mcu=False,
    )
    assert pathlib.Path(socket_path).exists(), (
        "klippy reached ready but the endpoint never created %s — the claim "
        "did not happen" % socket_path
    )


@pytest.mark.needs_elf
def test_a_servo_axis_move_is_accepted(sim_world, tmp_path):
    """The drives are off, so this proves the stream reaches the endpoint and
    is accepted — not that anything turned. A move rejected here is the
    planner-to-bridge path failing, which is what this world exists to catch
    before a drive is ever energised."""
    socket_path = str(tmp_path / "ec.sock")
    world = sim_world(
        lambda w: configs.ethercat_servo_config(
            w.h7_pty, str(w.gcode_dir), socket_path
        ),
        dual_mcu=False,
    )
    world.gcode_ok("SET_KINEMATIC_POSITION X=125 Y=125 Z=125")
    world.gcode_ok("G1 X135 Y135 F3000")
    world.gcode_ok("M400")
    assert world.toolhead_position()[:2] == pytest.approx(
        [135.0, 135.0], abs=0.01
    )


@pytest.mark.sim_unit
def test_the_guide_config_is_the_guide_with_only_the_machine_swapped():
    """The world below boots the CB2 guide's Stage K block. What makes it
    worth running is that nothing a reader copies is edited on the way in —
    only pins, the serial path, the endpoint and the Stage J identity."""
    from klippy import configfile

    guide = configs.cb2_guide_stage_k(REPO)
    sim = configs.cb2_guide_config(REPO, "/dev/pts/0", "/tmp/g", "/tmp/ec.sock")

    def sections(text):
        return set(re.findall(r"^\[([^\]]+)\]", text, re.M))

    dropped = sections(guide) - sections(sim)
    assert dropped == {s for s in sections(guide) if s.startswith("tmc2209 ")}
    assert not re.search(r"\bP[A-G]\d{1,2}\b", sim)
    kind, _lanes, _followers = configfile._config_doc.read_motion_settings(sim)[
        2
    ]
    assert kind == "markforged"


@pytest.mark.needs_elf
def test_the_cb2_guide_config_reaches_ready_and_moves(sim_world, tmp_path):
    """Stage L step 1 on the guide's own config: klippy must reach ready
    against the stub. The config had no [printer] section, no nozzle or
    filament diameter and no heater limits or control, and klippy refuses
    each of those before it gets near the servos. Then X, Y and a diagonal:
    Y is the second drive on the node, which the stub used to drop."""
    socket_path = str(tmp_path / "ec.sock")
    world = sim_world(
        lambda w: configs.cb2_guide_config(
            REPO, w.h7_pty, str(w.gcode_dir), socket_path
        ),
        dual_mcu=False,
    )
    world.gcode_ok("SET_KINEMATIC_POSITION X=150 Y=150 Z=100")
    for move, expect in [
        ("G1 X160 F3000", [160.0, 150.0]),
        ("G1 Y160 F3000", [160.0, 160.0]),
        ("G1 X150 Y150 F3000", [150.0, 150.0]),
    ]:
        world.gcode_ok(move)
        world.gcode_ok("M400")
        assert world.toolhead_position()[:2] == pytest.approx(expect, abs=0.01)


@pytest.mark.needs_elf
def test_the_cb2_guide_stop_halts_the_servos(sim_world, tmp_path):
    """Stage L step 2: pressing the stop opens the NC contact, `^PF1` reads
    high, klippy shuts down naming it, and ethercat_node sends Stop and a
    torque disable to the endpoint."""
    import time

    socket_path = str(tmp_path / "ec.sock")
    world = sim_world(
        lambda w: configs.cb2_guide_config(
            REPO, w.h7_pty, str(w.gcode_dir), socket_path
        ),
        dual_mcu=False,
    )
    control = world.sim_control()
    control.set_gpio_input(0, configs.CB2_GUIDE_ESTOP_LINE, 0)
    world.gcode_ok("SET_KINEMATIC_POSITION X=150 Y=150 Z=100")
    world.gcode_ok("G1 X155 F600")
    control.set_gpio_input(0, configs.CB2_GUIDE_ESTOP_LINE, 1)
    assert world.wait_for_log_text(
        "emergency stop 'estop' asserted", timeout=10
    )
    deadline = time.monotonic() + 10
    stub = ""
    while time.monotonic() < deadline:
        stub = (world.log_dir / "klippy.stdout").read_text(errors="replace")
        if "scheduled torque disable executed" in stub:
            break
        time.sleep(0.2)
    assert "ec-rt-stub: Stop" in stub
    assert "scheduled torque disable executed" in stub


@pytest.mark.needs_elf
def test_the_torque_command_the_guide_gives_enables_the_node(
    sim_world, tmp_path
):
    """Stage L step 4 said the drives reach Operation Enabled and never said
    how. The servo rails register with stepper_enable under their section
    names, so the command is `SET_STEPPER_ENABLE STEPPER="axis x"`; the bare
    axis letter is refused as an invalid stepper."""
    import time

    socket_path = str(tmp_path / "ec.sock")
    world = sim_world(
        lambda w: configs.cb2_guide_config(
            REPO, w.h7_pty, str(w.gcode_dir), socket_path
        ),
        dual_mcu=False,
    )
    guide = (REPO / configs.CB2_GUIDE).read_text(encoding="utf-8")
    step4 = guide.split("### 4. Torque on, no motion")[1].split("### 5.")[0]
    command = re.search(r"```\n(SET_STEPPER_ENABLE [^\n]+)\n```", step4)[1]
    world.gcode_ok(command)
    deadline = time.monotonic() + 5
    stub = ""
    while time.monotonic() < deadline:
        stub = (world.log_dir / "klippy.stdout").read_text(errors="replace")
        if "torque enabled" in stub:
            break
        time.sleep(0.1)
    assert "ec-rt-stub: torque enabled" in stub
    world.gcode_ok("M18")
    assert world.wait_for_log_text("has been manually enabled", timeout=5)


@pytest.mark.needs_elf
@pytest.mark.parametrize("axis,line", [("X", 10), ("Y", 11)])
def test_the_cb2_guide_homes_each_servo_axis_on_its_manta_endstop(
    sim_world, tmp_path, axis, line
):
    """Stage L step 8: a servo axis homes against a GPIO endstop on the Manta,
    which is a lane the MCU does not step. Y is the Markforged axis that moves
    both motors, and the second slot on the node."""
    import threading
    import time

    socket_path = str(tmp_path / "ec.sock")
    world = sim_world(
        lambda w: configs.cb2_guide_config(
            REPO, w.h7_pty, str(w.gcode_dir), socket_path
        ),
        dual_mcu=False,
    )
    control = world.sim_control()
    control.set_gpio_input(0, line, 0)
    outcome = {}

    def home():
        try:
            outcome["result"] = world.gcode_ok("G28 %s" % axis, timeout=60)
        except Exception as e:
            outcome["error"] = e

    homing = threading.Thread(target=home)
    homing.start()
    time.sleep(2.0)
    control.set_gpio_input(0, line, 1)
    time.sleep(0.3)
    control.set_gpio_input(0, line, 0)
    homing.join(70)
    assert "error" not in outcome, outcome
    assert "result" in outcome, "G28 %s never returned" % axis
