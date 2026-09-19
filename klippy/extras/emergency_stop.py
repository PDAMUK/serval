# Emergency stop input that shuts the printer down from the button callback
# rather than through the G-Code queue.
#
# This file may be distributed under the terms of the GNU GPLv3 license.


class EmergencyStop:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        self.message = config.get(
            "message", "emergency stop '%s' asserted" % (self.name,)
        )
        self.asserted = False
        buttons = self.printer.load_object(config, "buttons")
        buttons.register_buttons([config.get("pin")], self._handle_state)
        gcode = self.printer.lookup_object("gcode")
        gcode.register_mux_command(
            "QUERY_EMERGENCY_STOP",
            "STOP",
            self.name,
            self.cmd_QUERY_EMERGENCY_STOP,
            desc=self.cmd_QUERY_EMERGENCY_STOP_help,
        )

    def _handle_state(self, eventtime, state):
        self.asserted = bool(state)
        if self.asserted:
            self.printer.invoke_shutdown(self.message)

    cmd_QUERY_EMERGENCY_STOP_help = (
        "Report whether an emergency stop input is asserted"
    )

    def cmd_QUERY_EMERGENCY_STOP(self, gcmd):
        state = "ASSERTED" if self.asserted else "clear"
        gcmd.respond_info("%s: %s" % (self.name, state))

    def get_status(self, eventtime=None):
        return {"asserted": self.asserted}


def load_config_prefix(config):
    return EmergencyStop(config)
