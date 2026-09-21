"""The motion budget must be the repo's maths, not a plausible substitute.

The load-bearing test is the first one: `dynamics.rs` has a unit test pinning
`torque_ff` at 20 and 40 for a CoreXY fixture, and the mode algebra here has to
reproduce both. If it cannot, this module is modelling something else, however
sensible its numbers look.
"""

import math
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import motion_budget as mb  # noqa: E402


def mode_space_torque(frame, mass, slot_accels, slot):
    """`DynamicsModel::eval` with viscous and coulomb at zero: per mode,
    force = mass * (frame . accel), lifted back by frame[mode][slot]."""
    total = 0.0
    for k, row in enumerate(frame):
        a_mode = sum(f * a for f, a in zip(row, slot_accels))
        total += row[slot] * mass[k] * a_mode
    return total


def test_the_mode_algebra_reproduces_the_rust_torque_ff_test():
    """rust/ethercat-rt/src/dynamics/tests.rs:
    corexy_effective_inertia_is_direction_dependent — frame [[0.5,0.5],
    [0.5,-0.5]], mass [0.040, 0.080], slot accels [1000,1000] -> 20 and
    [1000,-1000] -> 40 on slot 0."""
    frame = mb.FRAMES["corexy"]
    mass = (0.040, 0.080)
    x_move = mode_space_torque(frame, mass, (1000.0, 1000.0), 0)
    y_move = mode_space_torque(frame, mass, (1000.0, -1000.0), 0)
    assert x_move == pytest.approx(20.0, abs=1e-3)
    assert y_move == pytest.approx(40.0, abs=1e-3)


def test_the_frames_match_the_kinematics_module():
    """The mixing is `kinematics.rs`'s, so it has to be read from there rather
    than remembered."""
    src = (ROOT / "rust" / "motion-core" / "src" / "kinematics.rs").read_text(
        encoding="utf-8"
    )
    coupling = re.search(r"MARKFORGED_Y_COUPLING: f64 = ([\d.]+);", src).group(
        1
    )
    assert float(coupling) == mb.MARKFORGED_Y_COUPLING
    assert "MARKFORGED_MOTOR_TO_AXIS" in src
    markforged = re.search(
        r"MARKFORGED_MOTOR_TO_AXIS[^=]*= \[\s*\[([^\]]*)\],\s*\[([^\]]*)\]",
        src,
        re.S,
    )
    first = markforged.group(1).replace("MARKFORGED_Y_COUPLING", coupling)
    row0 = [float(v) for v in first.split(",")[:2]]
    assert row0 == list(mb.FRAMES["markforged"][0])
    corexy = re.search(
        r"COREXY_MOTOR_TO_AXIS[^=]*=\s*\[\[([^\]]*)\]", src
    ).group(1)
    assert [float(v) for v in corexy.split(",")[:2]] == list(
        mb.FRAMES["corexy"][0]
    )


def test_a_markforged_move_loads_the_two_motors_differently_by_axis():
    """The asymmetry that decides this machine's budget, and it is not the
    obvious way round.

    Pure X: motor 0 turns and carries the carriage, and motor 1 must hold an
    equal and opposite *belt* torque without turning at all, or the belt
    reaction drags the gantry in Y. Pure Y: both motors turn, motor 1 carries
    the gantry, and motor 0 carries nothing but its own rotor.

    So neither axis gets two motors' worth of force — unlike CoreXY — and the
    limiting motor differs per axis."""
    machine = mb.Machine(kinematics="markforged")
    r = machine.motor.pulley_radius_m
    j = machine.motor.rotor_inertia_kgm2
    m_x, m_y = machine.mode_mass_kg()

    x = mb.slot_torques_nm(machine, (1000.0, 0.0))
    assert x[0] == pytest.approx(m_x * 1.0 * r + j * 1.0 / r, rel=1e-9)
    assert x[1] == pytest.approx(-m_x * 1.0 * r, rel=1e-9), (
        "motor 1 should hold the belt reaction and spin no rotor on an X move"
    )

    y = mb.slot_torques_nm(machine, (0.0, 1000.0))
    assert y[0] == pytest.approx(j * 1.0 / r, rel=1e-9), (
        "motor 0 should carry only its own rotor on a Y move"
    )
    assert y[1] == pytest.approx(m_y * 1.0 * r + j * 1.0 / r, rel=1e-9)


def test_the_rotor_outweighs_the_belt_load_on_a_light_carriage():
    """On pure X at a 20-tooth pulley the rotor term is larger than the load
    term. Anyone sizing this machine by carriage mass alone is reading the
    smaller half of the problem."""
    machine = mb.Machine()
    r = machine.motor.pulley_radius_m
    belt = machine.carriage_mass_kg * 1.0 * r
    rotor = machine.motor.rotor_inertia_kgm2 * 1.0 / r
    assert rotor > belt


def test_corexy_shares_a_pure_axis_move_across_both_motors():
    """The contrast that shows the markforged result is kinematic and not an
    artefact: in CoreXY both motors contribute to either axis."""
    machine = mb.Machine(kinematics="corexy")
    x = mb.slot_torques_nm(machine, (1000.0, 0.0))
    assert abs(x[0]) == pytest.approx(abs(x[1]), rel=1e-9)
    assert all(abs(t) > 0.0 for t in x)


def test_the_rotor_is_a_real_share_of_a_light_gantry():
    """J/r² at a 20-tooth GT2 pulley is 0.77 kg — more than a typical carriage.
    A model that drops it overstates acceleration on exactly the machines
    people try to make fast."""
    motor = mb.Motor()
    assert motor.reflected_mass_kg == pytest.approx(0.765, abs=0.01)
    assert motor.reflected_mass_kg > mb.Machine().carriage_mass_kg


def test_a_bigger_pulley_trades_acceleration_for_speed():
    """The whole point of the teeth control: force falls as 1/r, free speed
    rises as r."""
    small = mb.Machine(motor=mb.Motor(pulley_teeth=16))
    large = mb.Machine(motor=mb.Motor(pulley_teeth=32))
    assert mb.max_axis_accel_mm_s2(small, (0, 1)) > mb.max_axis_accel_mm_s2(
        large, (0, 1)
    )
    assert mb.max_axis_velocity_mm_s(small, (0, 1)) < mb.max_axis_velocity_mm_s(
        large, (0, 1)
    )


def test_a_heavier_gantry_only_slows_the_axis_that_carries_it():
    heavy = mb.Machine(gantry_mass_kg=4.0)
    light = mb.Machine(gantry_mass_kg=1.0)
    assert mb.max_axis_accel_mm_s2(heavy, (0, 1)) < mb.max_axis_accel_mm_s2(
        light, (0, 1)
    )
    assert mb.max_axis_accel_mm_s2(heavy, (1, 0)) == pytest.approx(
        mb.max_axis_accel_mm_s2(light, (1, 0))
    )


def test_the_stepper_ceiling_matches_motion_setup():
    """klippy/motion_setup.py is the source; this only spells step_dist out."""
    from klippy import motion_setup

    assert motion_setup.STEP_EDGE_FLOOR_SECONDS == mb.STEP_EDGE_FLOOR_SECONDS
    assert motion_setup.STEP_ISR_BUDGET_FRACTION == mb.STEP_ISR_BUDGET_FRACTION
    ceiling = mb.stepper_velocity_ceiling_mm_s(
        rotation_distance_mm=8.0, microsteps=16, pulse_duration_s=2e-6
    )
    step_dist = 8.0 / (200 * 16)
    assert ceiling == pytest.approx(0.5 / 3e-6 * step_dist)


def test_the_corner_factor_is_the_geometry_crate_s():
    src = (ROOT / "rust" / "geometry" / "src" / "frontend.rs").read_text(
        encoding="utf-8"
    )
    assert "SQRT_2 - 1.0" in src
    assert mb.CORNER_DEVIATION_SCV_FACTOR == pytest.approx(math.sqrt(2) - 1)
    assert mb.corner_deviation_from_scv(5.0, 3000.0) == pytest.approx(
        25.0 * (math.sqrt(2) - 1) / 3000.0
    )


def test_every_number_not_from_the_repo_is_labelled():
    """The habit this audit kept needing: a figure that looks authoritative and
    is a guess is the thing that hides a defect."""
    for key in ("rated_torque_nm", "rotor_inertia", "torque_ceiling_pct"):
        assert key in mb.SOURCES
        assert "docs/rewrite" in mb.SOURCES[key]
    for key in ("markforged_frame", "torque_model", "stepper_ceiling"):
        assert re.match(r"(rust|klippy)/", mb.SOURCES[key])
