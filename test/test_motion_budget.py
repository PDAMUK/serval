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
    r = machine.pulley_radius_m
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
    r = machine.pulley_radius_m
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
    machine = mb.Machine()
    assert mb.reflected_rotor_mass_kg(machine) == pytest.approx(0.765, abs=0.01)
    assert mb.reflected_rotor_mass_kg(machine) > machine.carriage_mass_kg


def test_the_pulley_trade_off_depends_on_which_part_is_the_limit():
    """The rule of thumb — smaller pulley, more acceleration — only holds while
    the *motor* is the limit. Force falls as 1/r, so a smaller pulley pulls
    harder on a fixed torque.

    Once the *belt* is the limit it inverts. The ceiling is then the belt's
    allowable tension, which does not care about r, and the accel works out at
    T_allow / (m + J/r²): a bigger pulley shrinks the reflected rotor and lets
    the same belt tension accelerate more. Asserting the rule of thumb
    universally is how a model quietly recommends the wrong pulley."""

    def y_accel(teeth, belt, ceiling):
        return mb.max_axis_accel_mm_s2(
            mb.Machine(motor=mb.Motor(pulley_teeth=teeth), belt=belt),
            (0, 1),
            ceiling,
        )

    strong = mb.Belt("GT3", 12.0)
    assert (
        mb.Machine(
            motor=mb.Motor(pulley_teeth=16), belt=strong
        ).continuous_limiting_part
        == "motor"
    )
    assert y_accel(16, strong, "continuous") > y_accel(32, strong, "continuous")

    weak = mb.Belt("GT2", 6.0)
    assert (
        mb.Machine(
            motor=mb.Motor(pulley_teeth=16), belt=weak
        ).continuous_limiting_part
        == "belt"
    )
    assert y_accel(32, weak, "continuous") > y_accel(16, weak, "continuous")

    assert y_accel(16, weak, "peak") > y_accel(32, weak, "peak")


def test_a_bigger_pulley_always_raises_top_speed():
    """The half of the trade-off that is unconditional: free speed is
    rotation_distance per revolution."""
    small = mb.Machine(motor=mb.Motor(pulley_teeth=16))
    large = mb.Machine(motor=mb.Motor(pulley_teeth=32))
    assert mb.max_axis_velocity_mm_s(large, (0, 1)) > mb.max_axis_velocity_mm_s(
        small, (0, 1)
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


def test_the_belt_tensions_are_the_published_ones():
    """SDP/SI Technical Section Table 3, neoprene column, per 25.4 mm of width.
    The MXL row (2.03 mm, 80 N) and HTD 3 mm (285 N) bracket these and agree in
    scale, which is the sanity check that the GT3 rows were read correctly."""
    assert mb.BELTS["GT2"]["tension_n_per_inch"] == 111.0
    assert mb.BELTS["GT3"]["tension_n_per_inch"] == 507.0
    assert mb.Belt("GT2", 6.0).allowable_tension_n == pytest.approx(
        26.2, abs=0.1
    )
    assert mb.Belt("GT3", 9.0).allowable_tension_n == pytest.approx(
        179.6, abs=0.1
    )


def test_only_the_unpublished_pitch_is_marked_estimated():
    """Gates does not make a 1.5 mm pitch, so there is no figure to quote and
    the extrapolation has to admit it. The two real ones must not be marked
    estimated, or the flag stops meaning anything."""
    assert mb.Belt("GT1.5").tension_estimated is True
    assert mb.Belt("GT2").tension_estimated is False
    assert mb.Belt("GT3").tension_estimated is False
    assert "ESTIMATE" in mb.SOURCES["gt15_tension"]


def test_epdm_buys_temperature_and_not_strength():
    """Both constructions carry the same fibreglass tensile cord, so the
    allowable tension is identical and only the rubber's range moves. A tool
    that made EPDM stronger would recommend it for the wrong reason."""
    standard = mb.Belt("GT2", 9.0, "standard")
    epdm = mb.Belt("GT2", 9.0, "epdm")
    assert epdm.allowable_tension_n == standard.allowable_tension_n
    assert epdm.temperature_range_c[1] > standard.temperature_range_c[1]
    assert epdm.temperature_range_c == (-45.0, 135.0)
    assert standard.temperature_range_c == (-35.0, 80.0)


def test_a_standard_2gt_6mm_belt_sets_the_continuous_limit_not_the_peak():
    """At 20 teeth the belt's allowable working tension is 0.167 N·m against
    the motor's rated 1.27, so it sets what the machine can pull all day.

    It does **not** set the peak. The catalog figure is a life rating — it
    falls with rpm, and §24 compares it against a running torque already
    carrying a 1.5-2.0 service factor — and §9.1 says an intermittent peak
    above it is ordinarily carried without special consideration. Capping the
    peak with it was this tool's own defect: it reported 8,844 mm/s² on Y
    where the drive will deliver 67,284."""
    machine = mb.Machine(belt=mb.Belt("GT2", 6.0))
    assert machine.continuous_limiting_part == "belt"
    assert machine.belt_continuous_torque_nm < machine.motor.rated_torque_nm / 5
    assert machine.continuous_torque_nm == machine.belt_continuous_torque_nm
    assert machine.peak_torque_nm == machine.motor.torque_nm

    peak = mb.max_axis_accel_mm_s2(machine, (0, 1), "peak")
    continuous = mb.max_axis_accel_mm_s2(machine, (0, 1), "continuous")
    assert peak == pytest.approx(67284, rel=0.01)
    assert continuous == pytest.approx(8844, rel=0.01)
    assert peak > continuous


def test_the_belt_duty_ratio_says_how_far_past_the_rating_a_peak_reaches():
    """The number that replaces the false ceiling. It is not a pass/fail — the
    catalog tolerates an intermittent peak over the rating — but 7.6× is the
    figure that decides whether a wider belt is worth fitting."""
    machine = mb.Machine(belt=mb.Belt("GT2", 6.0))
    assert mb.belt_duty_ratio(machine, (0, 1)) == pytest.approx(7.6, abs=0.1)
    wide = mb.Machine(belt=mb.Belt("GT3", 12.0))
    assert mb.belt_duty_ratio(wide, (0, 1)) < 1.0


def test_an_unknown_ceiling_is_refused_rather_than_guessed():
    machine = mb.Machine()
    with pytest.raises(ValueError, match="ceiling must be one of"):
        mb.max_axis_accel_mm_s2(machine, (0, 1), "average")


def test_the_source_table_records_that_the_belt_rating_is_continuous():
    """The distinction that was wrong is the one most worth pinning: the
    figure's meaning, and that nothing here quantifies the real peak."""
    assert (
        "intermittent peak torques" in mb.SOURCES["belt_tension_is_continuous"]
    )
    assert mb.SOURCES["belt_peak_is_ratcheting"].startswith("UNQUANTIFIED")
    assert "tooth jumping" in mb.SOURCES["belt_peak_is_ratcheting"]


def test_a_wide_gt3_belt_hands_the_continuous_limit_back_to_the_motor():
    machine = mb.Machine(belt=mb.Belt("GT3", 12.0))
    assert machine.continuous_limiting_part == "motor"
    assert machine.continuous_torque_nm == machine.motor.rated_torque_nm


def test_a_reduction_levers_torque_and_squares_the_rotor():
    """The whole point of the stage, and the half people forget. Torque at the
    gantry pulley scales with the ratio; the rotor referred through it scales
    with the square, because the motor both turns faster and is levered."""
    direct = mb.Machine()
    geared = mb.Machine(gearing=mb.Gearing(20, 40))
    assert geared.gearing.ratio == 2.0
    assert geared.gearing.is_reduction
    assert geared.output_peak_torque_nm == pytest.approx(
        direct.output_peak_torque_nm * 2.0
    )
    assert mb.reflected_rotor_mass_kg(geared) == pytest.approx(
        mb.reflected_rotor_mass_kg(direct) * 4.0
    )
    assert geared.rotation_distance_mm == pytest.approx(
        direct.rotation_distance_mm / 2.0
    )
    assert geared.pulley_radius_m == pytest.approx(direct.pulley_radius_m)


def test_an_overdrive_runs_every_term_the_other_way():
    """A big pulley on the servo driving a small one: speed for torque."""
    over = mb.Machine(gearing=mb.Gearing(40, 20))
    assert over.gearing.ratio == 0.5
    assert not over.gearing.is_reduction
    assert over.free_speed_mm_s == pytest.approx(
        mb.Machine().free_speed_mm_s * 2.0
    )
    assert mb.max_axis_velocity_mm_s(over, (0, 1)) > mb.max_axis_velocity_mm_s(
        mb.Machine(), (0, 1)
    )
    assert mb.max_axis_accel_mm_s2(
        over, (0, 1), "peak"
    ) < mb.max_axis_accel_mm_s2(mb.Machine(), (0, 1), "peak")


def test_peak_acceleration_maxes_out_where_the_inertia_matches():
    """Not asserted anywhere in the model — it falls out of torque scaling by
    the ratio and the rotor by its square. The best ratio for a 20 T servo
    pulley puts the reflected rotor on top of the moving mass, which is the
    textbook result and the reason a bigger reduction stops helping."""
    best = max(
        range(10, 101),
        key=lambda driven: mb.max_axis_accel_mm_s2(
            mb.Machine(gearing=mb.Gearing(20, driven)), (0, 1), "peak"
        ),
    )
    machine = mb.Machine(gearing=mb.Gearing(20, best))
    reflected = mb.reflected_rotor_mass_kg(machine)
    moving = max(machine.mode_mass_kg())
    assert reflected == pytest.approx(moving, rel=0.1)
    assert mb.max_axis_accel_mm_s2(
        machine, (0, 1), "peak"
    ) > mb.max_axis_accel_mm_s2(mb.Machine(), (0, 1), "peak")


def test_a_gear_stage_needs_real_teeth():
    with pytest.raises(ValueError, match="positive teeth counts"):
        mb.Gearing(20, 0)
    with pytest.raises(ValueError, match="positive teeth counts"):
        mb.Gearing(-1, 20)


def test_fifteen_millimetres_is_a_gt3_width_and_not_a_gt2_one():
    """Tension scales with any width asked for, so only the catalog list
    knows that a 15 mm 2GT belt is arithmetic rather than a part."""
    assert 15.0 in mb.BELT_WIDTHS_MM
    assert mb.Belt("GT3", 15.0).width_is_catalogued
    assert not mb.Belt("GT2", 15.0).width_is_catalogued
    assert not mb.Belt("GT1.5", 6.0).width_is_catalogued
    assert mb.Belt("GT2", 6.0).width_is_catalogued
    assert mb.Belt("GT3", 15.0).allowable_tension_n == pytest.approx(
        507.0 * 15.0 / 25.4, abs=0.1
    )


def test_the_source_table_records_what_the_gear_stage_leaves_out():
    assert mb.SOURCES["gear_stage_inertia"].startswith("NOT MODELLED")
    assert (
        "rotation_distance"
        in mb.SOURCES["gearing_folds_into_rotation_distance"]
    )
    assert (
        "parse_gear_ratio" in mb.SOURCES["gearing_folds_into_rotation_distance"]
    )


@pytest.mark.parametrize("teeth", [16, 20, 40, 140])
def test_the_teeth_range_the_tool_offers_stays_computable(teeth):
    machine = mb.Machine(motor=mb.Motor(pulley_teeth=teeth))
    assert mb.max_axis_accel_mm_s2(machine, (0, 1)) > 0
    assert math.isfinite(mb.max_axis_velocity_mm_s(machine, (1, 0)))
    assert machine.rotation_distance_mm == teeth * 2.0
