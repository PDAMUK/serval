import pytest
from fakes import FakeConfig, FakePrinter

from klippy.extras.emergency_stop import EmergencyStop


class RecordingButtons:
    def __init__(self):
        self.registered = []

    def register_debounce_button(self, pin, callback, config):
        self.registered.append(([pin], callback, config))


class RecordingGCode:
    def __init__(self):
        self.mux_commands = []
        self.responses = []

    def register_mux_command(
        self, cmd, key, value, func, desc=None, when_not_ready=False
    ):
        self.mux_commands.append((cmd, key, value, func, when_not_ready))

    def respond_info(self, msg):
        self.responses.append(msg)


def build(values=None, name="emergency_stop estop"):
    buttons = RecordingButtons()
    gcode = RecordingGCode()
    printer = FakePrinter({"buttons": buttons, "gcode": gcode})
    config = FakeConfig(printer, name, {"pin": "^PF1", **(values or {})})
    stop = EmergencyStop(config)
    return stop, printer, buttons, gcode


def test_asserting_the_input_shuts_down_without_touching_the_gcode_queue():
    """The whole point of this module. run_script("M112") would take the
    G-Code mutex and wait behind whatever is already queued; invoke_shutdown
    runs the klippy:shutdown handlers there and then."""
    stop, printer, buttons, gcode = build()
    (_pins, callback, _config) = buttons.registered[0]

    callback(0.0, 1)

    assert printer.is_shutdown()
    assert printer.shutdown_reasons == ["emergency stop 'estop' asserted"]
    assert gcode.mux_commands[0][0] == "QUERY_EMERGENCY_STOP"


def test_a_released_input_does_not_shut_down():
    stop, printer, buttons, _gcode = build()
    (_pins, callback, _config) = buttons.registered[0]

    callback(0.0, 0)

    assert not printer.is_shutdown()
    assert stop.get_status()["asserted"] is False


def test_the_pin_is_registered_unchanged():
    """The pull-up and any inversion belong to the config, because they are
    what decides whether a broken wire reads as pressed."""
    _stop, _printer, buttons, _gcode = build()

    assert buttons.registered[0][0] == ["^PF1"]


def test_a_stop_already_asserted_at_connect_still_shuts_down():
    """buttons reports an initial state that differs from its assumed zero, so
    a latched stop at power-on arrives as an ordinary press."""
    _stop, printer, buttons, _gcode = build()
    (_pins, callback, _config) = buttons.registered[0]

    callback(0.0, 1)

    assert printer.shutdown_reasons


def test_the_message_is_configurable_and_names_the_input():
    _stop, printer, buttons, _gcode = build({"message": "gantry stop hit"})
    (_pins, callback, _config) = buttons.registered[0]

    callback(0.0, 1)

    assert printer.shutdown_reasons == ["gantry stop hit"]


def test_releasing_after_a_press_clears_the_query_but_not_the_shutdown():
    """Klipper latches a shutdown; releasing the button must not look like
    recovery. Only FIRMWARE_RESTART clears it."""
    stop, printer, buttons, gcode = build()
    (_pins, callback, _config) = buttons.registered[0]

    callback(0.0, 1)
    callback(1.0, 0)

    assert printer.is_shutdown()
    assert stop.get_status()["asserted"] is False


def test_query_reports_both_states():
    stop, _printer, buttons, gcode = build()
    (_pins, callback, _config) = buttons.registered[0]
    query = gcode.mux_commands[0][3]

    query(gcode)
    callback(0.0, 1)
    query(gcode)

    assert gcode.responses == ["estop: clear", "estop: ASSERTED"]


def test_a_missing_pin_is_refused():
    buttons = RecordingButtons()
    printer = FakePrinter({"buttons": buttons, "gcode": RecordingGCode()})
    config = FakeConfig(printer, "emergency_stop estop", {})

    with pytest.raises(Exception):
        EmergencyStop(config)


def test_the_query_survives_the_shutdown_the_stop_causes():
    """Pressing the stop shuts klippy down, and a shutdown drops every command
    that is not registered when_not_ready. Without this the query can only ever
    be run in the clear state — it could never report the press that is the
    whole reason to ask, nor confirm the button is still held."""
    _stop, _printer, _buttons, gcode = build()

    (cmd, key, _value, _func, when_not_ready) = gcode.mux_commands[0]

    assert (cmd, key) == ("QUERY_EMERGENCY_STOP", "STOP")
    assert when_not_ready is True


def test_the_input_can_be_debounced_against_servo_noise():
    """The button hangs off a high-impedance pull-up on a cable run through a
    cabinet full of servo drives, and a false assert stops a print. Going
    through the debounce wrapper costs nothing at its 0.0 default and leaves
    debounce_delay available to anyone who sees trips; registering the raw
    button leaves them no option in config at all."""
    _stop, _printer, buttons, _gcode = build()

    (_pins, _callback, passed_config) = buttons.registered[0]

    assert passed_config is not None, (
        "no config reached the debouncer, so debounce_delay cannot be set"
    )
