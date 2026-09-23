"""What a servo `[motor]` section refuses, read through klippy's real config.

`gear_ratio` is parsed only by `klippy/stepper.py`; `bridge/ethercat_endpoint.rs`
passes `rotation_distance` straight to the endpoint and nothing in between
applies a ratio. By default klippy's unused-option accounting already refuses
the option, but only as "Option 'gear_ratio' is not valid", which does not say
where the reduction belongs — and `[danger_options]
error_on_unused_config_options: False` turns that refusal into a log line, at
which point every move on the axis is wrong by the ratio.
"""

import pytest
from klippy_testing import PrinterShim

from klippy.extras import servo_axis

SERVO_MOTOR = """
[danger_options]
error_on_unused_config_options: False

[motor motor_x]
protocol: ethercat
node: xy
ethercat_chain_index: 0
rotation_distance: 40
encoder_counts_per_rev: 1048576
"""


def load_motor_section(tmp_path, extra=""):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(SERVO_MOTOR + extra, encoding="utf-8")
    printer = PrinterShim({"config_file": str(cfg)})
    return printer.load_config().getsection("motor motor_x")


def test_a_servo_motor_without_gear_ratio_loads(tmp_path):
    motor = servo_axis.ServoMotor(load_motor_section(tmp_path), False)
    assert motor.get_rotation_distance() == 40.0


def test_gear_ratio_on_a_servo_motor_names_where_the_ratio_goes(tmp_path):
    section = load_motor_section(tmp_path, "gear_ratio: 80:20\n")
    with pytest.raises(
        Exception, match="fold the reduction into rotation_distance"
    ):
        servo_axis.ServoMotor(section, False)
