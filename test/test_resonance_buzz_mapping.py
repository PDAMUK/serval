import pytest

from klippy.extras.resonance_buzz import (
    ResonanceBuzz,
    _buzz_kind,
    buzz_axis_to_motor_mask,
)


def test_corexy_x_drives_both_motors_in_phase():
    axis_mask, sign_mask = buzz_axis_to_motor_mask("x", kind="corexy")
    assert axis_mask == 0b011
    assert sign_mask == 0b000


def test_corexy_y_drives_both_motors_anti_phase():
    axis_mask, sign_mask = buzz_axis_to_motor_mask("y", kind="corexy")
    assert axis_mask == 0b011
    assert sign_mask == 0b010


def test_corexy_z_is_single_slot():
    assert buzz_axis_to_motor_mask("z", kind="corexy") == (0b100, 0b000)


def test_cartesian_axes_map_one_to_one():
    assert buzz_axis_to_motor_mask("x", kind="cartesian") == (0b001, 0b000)
    assert buzz_axis_to_motor_mask("y", kind="cartesian") == (0b010, 0b000)
    assert buzz_axis_to_motor_mask("z", kind="cartesian") == (0b100, 0b000)


def test_case_insensitive():
    assert buzz_axis_to_motor_mask(
        "X", kind="corexy"
    ) == buzz_axis_to_motor_mask("x", kind="corexy")


def test_unsupported_axis_raises():
    with pytest.raises(ValueError, match="unsupported buzz axis"):
        buzz_axis_to_motor_mask("e", kind="cartesian")


class FakeBuzzKinematics:
    """These tests bound accel and amplitude, not motor masks, but the buzz
    code still has to know the machine: a bare stub used to be read as
    cartesian by default, which would have buzzed a corexy gantry one motor at
    a time. Say cartesian explicitly instead of relying on that."""

    kind = "cartesian"


class FakeBuzzToolhead:
    def get_kinematics(self):
        return FakeBuzzKinematics()

    def wait_moves(self):
        pass


class FakeBuzzMotion:
    def __init__(self):
        self.calls = []

    def submit_resonance_buzz(self, *args):
        self.calls.append(args)


class FakeBuzzReactor:
    def monotonic(self):
        return 0.0

    def pause(self, waketime):
        pass


class FakeBuzzPrinter:
    def __init__(self):
        self.motion = FakeBuzzMotion()
        self._objs = {"toolhead": FakeBuzzToolhead(), "motion": self.motion}

    def lookup_object(self, name, default=None):
        return self._objs.get(name, default)

    def get_reactor(self):
        return FakeBuzzReactor()


class FakeBuzzGcmd:
    error = RuntimeError

    def __init__(self):
        self.infos = []

    def respond_info(self, msg):
        self.infos.append(msg)


def _resonance_buzz(max_peak_accel=200000.0, max_amplitude=5.0):
    buzz = ResonanceBuzz.__new__(ResonanceBuzz)
    buzz.printer = FakeBuzzPrinter()
    buzz.max_peak_accel = max_peak_accel
    buzz.max_amplitude = max_amplitude
    return buzz


def test_over_ceiling_accel_per_hz_fails_loud_instead_of_clamping():
    buzz = _resonance_buzz()
    with pytest.raises(RuntimeError, match="largest ACCEL_PER_HZ"):
        buzz.run_sweep(
            FakeBuzzGcmd(), "x", 100.0, 400.0, 300.0, 0.1, 600.0, 0.0
        )
    assert buzz.printer.motion.calls == []


def test_accel_per_hz_at_ceiling_runs():
    buzz = _resonance_buzz()
    amplitude = buzz.run_sweep(
        FakeBuzzGcmd(), "x", 100.0, 400.0, 300.0, 0.1, 500.0, 0.0
    )
    assert buzz.printer.motion.calls
    assert amplitude > 0.0


def test_configured_max_peak_accel_bounds_the_sweep():
    buzz = _resonance_buzz(max_peak_accel=10000.0)
    with pytest.raises(RuntimeError, match="max_peak_accel"):
        buzz.run_sweep(FakeBuzzGcmd(), "x", 100.0, 400.0, 300.0, 0.1, 50.0, 0.0)
    assert buzz.printer.motion.calls == []


def test_configured_max_amplitude_bounds_explicit_amplitude():
    buzz = _resonance_buzz(max_amplitude=0.5)
    with pytest.raises(RuntimeError, match="max_amplitude"):
        buzz.run_sweep(FakeBuzzGcmd(), "x", 100.0, 400.0, 300.0, 0.1, 50.0, 1.0)
    assert buzz.printer.motion.calls == []


def test_markforged_x_buzzes_one_lane_and_y_buzzes_both_in_phase():
    assert buzz_axis_to_motor_mask("x", kind="markforged") == (0b001, 0b000)
    assert buzz_axis_to_motor_mask("y", kind="markforged") == (0b011, 0b000)
    assert buzz_axis_to_motor_mask("z", kind="markforged") == (0b100, 0b000)


def test_kinematics_without_a_kind_is_an_error_not_a_cartesian_machine():
    """Defaulting would drive one motor where a corexy needs two together."""
    with pytest.raises(ValueError, match="does not report one"):
        _buzz_kind(object())
