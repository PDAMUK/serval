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
def test_klippy_reaches_ready_with_the_drives_off(sim_world, tmp_path):
    """Part 12 step 1. A world that comes up means the claim completed: the
    endpoint was spawned, the handshake finished, and both drive slots were
    configured."""
    socket_path = str(tmp_path / "kalico-ethercat.sock")
    world = sim_world(
        lambda w: configs.ethercat_servo_config(
            w.h7_pty, str(w.gcode_dir), socket_path
        ),
        dual_mcu=False,
    )
    status = world.status({"webhooks": None})["webhooks"]
    assert status["state"] == "ready", status


@pytest.mark.needs_elf
def test_a_servo_axis_move_is_accepted(sim_world, tmp_path):
    """The drives are off, so this proves the stream reaches the endpoint and
    is accepted — not that anything turned. A move rejected here is the
    planner-to-bridge path failing, which is what this world exists to catch
    before a drive is ever energised."""
    socket_path = str(tmp_path / "kalico-ethercat.sock")
    world = sim_world(
        lambda w: configs.ethercat_servo_config(
            w.h7_pty, str(w.gcode_dir), socket_path
        ),
        dual_mcu=False,
    )
    world.gcode_ok("SET_KINEMATIC_POSITION X=125 Y=125 Z=125")
    world.gcode_ok("G1 X135 Y135 F3000")
    world.gcode_ok("M400")
    toolhead = world.status({"toolhead": None})["toolhead"]
    assert toolhead["position"][0] == pytest.approx(135.0, abs=0.01)
    assert toolhead["position"][1] == pytest.approx(135.0, abs=0.01)
