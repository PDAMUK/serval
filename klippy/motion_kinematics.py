from . import motion_engine, stepper

_KIN_COREXY = 0
_KIN_CARTESIAN = 1
_KIN_MARKFORGED = 2

# Mirrors MARKFORGED_Y_COUPLING in rust/motion-core/src/kinematics.rs. The two
# must agree or the host and the planner disagree about the machine, so
# check_markforged_coupling_agrees compares them rather than trusting the
# mirror to have been kept up to date.
MARKFORGED_Y_COUPLING = 1.0

# Row L of AXIS_TO_MOTOR gives motor lane L's position as a weighted sum of
# (x, y, z); row A of MOTOR_TO_AXIS recovers axis A from the lanes. Mirrors
# KinematicsModule in rust/motion-core/src/kinematics.rs.
_AXIS_TO_MOTOR = {
    "cartesian": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "corexy": ((1.0, 1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "markforged": (
        (1.0, MARKFORGED_Y_COUPLING, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ),
}
_MOTOR_TO_AXIS = {
    "cartesian": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "corexy": ((0.5, 0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.0, 1.0)),
    "markforged": (
        (1.0, -MARKFORGED_Y_COUPLING, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ),
}
_KIN_TAGS = {
    "corexy": _KIN_COREXY,
    "cartesian": _KIN_CARTESIAN,
    "markforged": _KIN_MARKFORGED,
}


def axis_to_motor_weights(kind):
    return _AXIS_TO_MOTOR[kind]


def kin_tag_for(kind):
    return _KIN_TAGS[kind]


def lanes_driven_by_axis(kind, axis):
    """Motor lanes whose position changes when `axis` alone moves."""
    return [row[axis] != 0.0 for row in _AXIS_TO_MOTOR[kind]]


_REBUILD_HINT = (
    "Change the value on both sides — klippy/motion_kinematics.py and the "
    "matching Rust source — then rebuild the module with "
    "scripts/build-native.sh: a Rust edit does nothing until it is recompiled."
)


def check_kinematic_tags_agree(planner_tags):
    """Fail on a kinematics tag table that disagrees with the planner's.

    The tag is the whole of what klippy tells the planner about the machine's
    geometry, so a renumber on either side — or a swap between two valid tags —
    builds the wrong kinematics from a config that still looks right."""
    if planner_tags is None:
        raise stepper.error(
            "the native motion engine is missing or predates the kinematics "
            "tag check, so the tags this host sends (%r) cannot be confirmed "
            "against it. " % (_KIN_TAGS,) + _REBUILD_HINT
        )
    if dict(planner_tags) == _KIN_TAGS:
        return
    raise stepper.error(
        "kinematics tag mismatch: klippy/motion_kinematics.py says %r but the "
        "planner says %r. The tag is all the planner is told about the "
        "machine's geometry, so a disagreement silently builds the wrong "
        "kinematics. " % (_KIN_TAGS, dict(planner_tags)) + _REBUILD_HINT
    )


def check_markforged_coupling_agrees(planner_coupling):
    """Fail on a coupling constant that was changed on one side only.

    The Rust constant compiles into klippy/_motion_engine.so, so editing it
    without rebuilding leaves this module's mirror as the only value that
    moved. Both halves then steer the machine to different geometry, which is
    worse than the wrong sign both would otherwise share. A module too old to
    carry the constant is the same failure one step earlier, so it lands here
    rather than as an AttributeError."""
    if planner_coupling is None:
        raise stepper.error(
            "the native motion engine is missing or predates the markforged "
            "coupling check, so it cannot report its constant and the "
            "planner's geometry cannot be confirmed to match this host's %r. "
            % (MARKFORGED_Y_COUPLING,)
            + _REBUILD_HINT
        )
    if planner_coupling == MARKFORGED_Y_COUPLING:
        return
    raise stepper.error(
        "markforged coupling mismatch: klippy/motion_kinematics.py says %r but "
        "the planner in klippy/_motion_engine.so says %r. The two copies are "
        "MARKFORGED_Y_COUPLING here and in rust/motion-core/src/kinematics.rs. "
        % (MARKFORGED_Y_COUPLING, planner_coupling)
        + _REBUILD_HINT
    )


def load_kinematics(config, motion):
    """Build the kinematics from the topology the native reader parsed and
    validated ([kinematics] type/roles, [motor] drives, follower slotting,
    orphan rejection) in Motion._load_motion_config."""
    if motion.kinematics_decl is None:
        raise config.error("[kinematics] section is required")
    kind, lanes, _followers = motion.kinematics_decl
    check_kinematic_tags_agree(motion_engine.native_attr("KINEMATIC_TAGS"))
    if kind == "markforged":
        check_markforged_coupling_agrees(
            motion_engine.native_attr("MARKFORGED_Y_COUPLING")
        )
    frontend_visible_kinematics = kind
    config.getsection("printer").get("kinematics", frontend_visible_kinematics)
    return _LinearKinematics(config, motion, kind, lanes)


class _LinearKinematics:
    supports_dual_carriage = False

    def __init__(self, config, motion, kind, lanes):
        self._motion = motion
        self.kind = kind
        self._printer = config.get_printer()

        self._lanes = [
            (lane_idx, axis_name, motors)
            for lane_idx, axis_name, motors, _drive in lanes
        ]
        self.rails = [self._build_lane(config, lane) for lane in lanes]
        self.limits = [(1.0, -1.0)] * 3
        self._parked_dirty = [False, False, False]

        self._printer.load_object(config, "homing").resolve_endstops(self)
        self._printer.register_event_handler(
            "stepper_enable:motor_off", self._handle_motor_off
        )

    def _build_lane(self, config, lane):
        lane_idx, axis_name, motor_names, drive = lane
        motor_sections = [
            config.getsection("motor " + name) for name in motor_names
        ]
        if drive == "servo":
            return self._build_servo_lane(config, axis_name, motor_sections)
        rail = stepper.AxisRail(
            config.getsection("axis " + axis_name),
            list(zip(motor_sections, motor_names)),
        )
        if self.kind == "corexy" and lane_idx < 2:
            rail.setup_itersolve(
                "corexy_stepper_alloc", b"+" if lane_idx == 0 else b"-"
            )
        elif self.kind == "markforged" and lane_idx < 2:
            rail.setup_itersolve(
                "markforged_stepper_alloc", b"x" if lane_idx == 0 else b"y"
            )
        else:
            rail.setup_itersolve(
                "cartesian_stepper_alloc", "xyz"[lane_idx].encode()
            )
        return rail

    def _build_servo_lane(self, config, axis_name, motor_sections):
        from .extras import servo_axis

        axis_config = config.getsection("axis " + axis_name)
        rail = servo_axis.ServoRail(axis_config, motor_sections)
        servo_axis.register_torque_enable(self._printer, config, rail)
        return rail

    def _handle_motor_off(self, print_time):
        for i in (0, 1, 2):
            if self._is_servo(i) and self.limits[i][0] <= self.limits[i][1]:
                self._parked_dirty[i] = True
            else:
                self.clear_homing_state([i])

    def _is_servo(self, axis):
        from .extras import servo_axis

        return isinstance(self.rails[axis], servo_axis.ServoRail)

    def mark_servo_parked(self, axes):
        for i in axes:
            if self._is_servo(i) and self.limits[i][0] <= self.limits[i][1]:
                self._parked_dirty[i] = True

    def parked_dirty_axes(self):
        return [i for i in (0, 1, 2) if self._parked_dirty[i]]

    def clear_parked_dirty(self, axes):
        for i in axes:
            self._parked_dirty[i] = False

    def _axis_rails(self):
        return {i: rail for i, rail in enumerate(self.rails)}

    def claimed_axes(self):
        return [axis_name for _, axis_name, _ in self._lanes]

    def lanes(self):
        return self._lanes

    def lanes_driven_by_axis(self, axis):
        return lanes_driven_by_axis(self.kind, axis)

    def axis_drives_one_lane(self, axis):
        return sum(self.lanes_driven_by_axis(axis)) == 1

    def coupled_xy(self):
        return not (
            self.axis_drives_one_lane(0) and self.axis_drives_one_lane(1)
        )

    def kin_tag(self):
        return kin_tag_for(self.kind)

    def mcu_tag(self, lanes_on_mcu):
        on_mcu = set(lanes_on_mcu)
        if self.coupled_xy() and 0 in on_mcu and 1 in on_mcu:
            return self.kin_tag()
        return _KIN_CARTESIAN

    def get_steppers(self):
        return [s for rail in self.rails for s in rail.get_steppers()]

    def active_rails(self, dx, dy, dz):
        axis_moved = [abs(dx) > 1e-9, abs(dy) > 1e-9, abs(dz) > 1e-9]
        weights = axis_to_motor_weights(self.kind)
        moved = [
            any(
                weight != 0.0 and axis_moved[axis]
                for axis, weight in enumerate(lane_weights)
            )
            for lane_weights in weights
        ]
        return [
            self.rails[lane_idx]
            for lane_idx, _, _ in self._lanes
            if moved[lane_idx]
        ]

    def calc_position(self, stepper_positions):
        def rail_pos(rail):
            vals = [
                stepper_positions.get(s.get_name(), 0.0)
                for s in rail.get_steppers()
            ]
            if not vals:
                return 0.0
            return sum(vals) / len(vals)

        lanes = [rail_pos(rail) for rail in self.rails]
        return [
            sum(weight * lanes[lane] for lane, weight in enumerate(row))
            for row in _MOTOR_TO_AXIS[self.kind]
        ]

    def _check_endstops(self, move):
        end_pos = move.end_pos
        for i in (0, 1, 2):
            if move.axes_d[i] and (
                end_pos[i] < self.limits[i][0] or end_pos[i] > self.limits[i][1]
            ):
                if self.limits[i][0] > self.limits[i][1]:
                    raise move.move_error("Must home axis first")
                raise move.move_error()

    def check_move(self, move):
        limits = self.limits
        xpos, ypos = move.end_pos[:2]
        if (
            xpos < limits[0][0]
            or xpos > limits[0][1]
            or ypos < limits[1][0]
            or ypos > limits[1][1]
        ):
            self._check_endstops(move)
        if not move.axes_d[2]:
            return
        self._check_endstops(move)
        z_ratio = move.move_d / abs(move.axes_d[2])
        move.limit_speed(self._motion.max_z_velocity * z_ratio)

    def set_position(self, newpos, homing_axes=()):
        self._motion.engine.set_position(newpos[0], newpos[1], newpos[2])
        for axis in homing_axes:
            self.limits[axis] = self.rails[axis].get_range()
            self._parked_dirty[axis] = False

    def note_z_not_homed(self):
        self.clear_homing_state([2])

    def clear_homing_state(self, axes):
        for i in (0, 1, 2):
            if i in axes:
                self.limits[i] = (1.0, -1.0)
                self._parked_dirty[i] = False

    def get_status(self, eventtime):
        from . import gcode as gcode_mod

        x_min, x_max = self.rails[0].get_range()
        y_min, y_max = self.rails[1].get_range()
        z_min, z_max = self.rails[2].get_range()
        homed = "".join(
            a
            for i, a in enumerate("xyz")
            if self.limits[i][0] <= self.limits[i][1]
        )
        return {
            "homed_axes": homed,
            "axis_minimum": gcode_mod.Coord(x_min, y_min, z_min, 0.0),
            "axis_maximum": gcode_mod.Coord(x_max, y_max, z_max, 0.0),
        }
