"""`MCU_bus_digital_out`'s pre-config path builds a command string by hand.

`build_config` looks the command up by its protocol signature, where `%c`
means "one byte parameter". `update_digital_out`'s early branch takes that
same string and runs it through Python's `%`, where `%c` means chr() — so the
oid and value arrived as control bytes rather than digits. Everywhere else
that writes this command by hand uses `%d`, including mcu_pins.py.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from klippy.extras.bus import MCU_bus_digital_out  # noqa: E402


class RecordingMCU:
    def __init__(self):
        self.config_cmds = []

    def add_config_cmd(self, cmd, **kwargs):
        self.config_cmds.append(cmd)


def _pre_config_out(oid=5):
    out = MCU_bus_digital_out.__new__(MCU_bus_digital_out)
    out.mcu = RecordingMCU()
    out.oid = oid
    out.update_pin_cmd = None
    return out


def test_the_pre_config_command_is_decimal_not_control_bytes():
    out = _pre_config_out(oid=5)

    out.update_digital_out(1)

    (cmd,) = out.mcu.config_cmds
    assert cmd == "update_digital_out oid=5 value=1", repr(cmd)
    assert cmd.isprintable(), (
        "the command carries non-printable bytes, so the conversion ran as "
        "chr(): %r" % (cmd,)
    )


def test_a_cleared_output_is_zero_and_not_a_nul_byte():
    """value=0 through %c is chr(0) — a NUL in the middle of the command
    string, which is the same defect wearing its worst face."""
    out = _pre_config_out(oid=12)

    out.update_digital_out(0)

    (cmd,) = out.mcu.config_cmds
    assert cmd == "update_digital_out oid=12 value=0", repr(cmd)
    assert "\x00" not in cmd


def test_it_matches_the_form_mcu_pins_writes_by_hand():
    """mcu_pins.py emits the same command for the same purpose and has always
    used %d. The two must not drift apart again."""
    source = (
        pathlib.Path(__file__).resolve().parents[1] / "klippy" / "mcu_pins.py"
    ).read_text(encoding="utf-8")
    assert '"update_digital_out oid=%d value=%d"' in source, (
        "mcu_pins.py no longer pins the reference form for this command"
    )
