import logging
import os
from collections import namedtuple

from . import servo_axis

# One drive slot passed to engine.claim_ethercat_node. The engine extracts each
# field by attribute name (mirrored by a Rust named struct), so a reordered
# field fails loud rather than silently swapping, say, axis and chain_index.
EthercatDrive = namedtuple(
    "EthercatDrive",
    [
        "chain_index",
        "axis",
        "counts_per_mm",
        "rotation_distance",
        "following_error_counts",
        "max_torque_tenth_pct",
        "velocity_ff",
        "ff_max_torque",
        "invert_direction",
        "dynamics_profile",
    ],
)

# Default endpoint binary: ethercat_node.py lives at
# <repo>/klippy/extras/, so three os.path.dirname hops reach <repo>.
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_DEFAULT_ENDPOINT = os.path.join(
    _REPO_ROOT, "rust", "target", "release", "ethercat-rt"
)

DRIVE_FAULT_POLL_PERIOD = 1.0
# ERR_PIECES_WHILE_PARKED in rust/ethercat-rt/src/torque.rs, truncated to the
# u16 the heartbeat carries.
TORQUE_GATE_FAULT_CODE = 0xFEC7
FRAME_LATE_FAULT_CODE = 0xFE10
CYCLE_SKIP_FAULT_CODE = 0xFE11

EC_RT_MAX_SLAVES = 8

CYCLE_US_QUANTUM = 250

# Drive families the endpoint knows how to bring up. Each decides the identity
# matched on the bus, which optional CiA 402 objects are mapped, and the vendor
# SDOs written in PRE-OP. A family whose identity is not public ships none and
# must be given one here.
DRIVE_PROFILES = ("a6ec", "estun-pronet")
PROFILES_NEEDING_IDENTITY = ("estun-pronet",)

# Per-motor options that must be identical across a coupled node: a
# node-level dynamics profile computes each motor's torque feedforward
# from every motor's commanded kinematics, so asymmetry in the FF path
# skews the coupled model instead of tuning one motor.
COUPLED_UNIFORM_OPTIONS = (
    ("velocity_ff", lambda motor: motor.get_ff_config()[0]),
    ("ff_max_torque", lambda motor: motor.get_ff_config()[1]),
)


def missing_identity_options(drive_profile, vendor_id, product_code):
    """Identity halves the profile needs and the config did not supply.

    Both must be non-zero. A zero product code is not a wildcard: the master
    accepts the slave configuration, never attaches it, and the run then dies
    at the OP walk with nothing pointing back at the unset option."""
    if drive_profile not in PROFILES_NEEDING_IDENTITY:
        return []
    return [
        option
        for option, value in (
            ("vendor_id", vendor_id),
            ("product_code", product_code),
        )
        if not value
    ]


class EtherCatNode:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        socket_path = config.get("socket").strip()
        if not socket_path:
            raise config.error(
                "ethercat_node %s: 'socket' must be a non-empty path"
                % (self.name,)
            )
        self.socket_path = socket_path
        interface = config.get("interface").strip()
        if not interface:
            raise config.error(
                "ethercat_node %s: 'interface' must be a non-empty "
                "NIC name (e.g. eth0)" % (self.name,)
            )
        self.interface = interface
        self.endpoint = os.path.abspath(
            config.get("endpoint", _DEFAULT_ENDPOINT)
        )
        self.cycle_us = config.getint("cycle_us", CYCLE_US_QUANTUM)
        if self.cycle_us <= 0 or self.cycle_us % CYCLE_US_QUANTUM != 0:
            raise config.error(
                "ethercat_node %s: cycle_us=%d is invalid — the sync cycle "
                "must be a positive integer multiple of %d us"
                % (self.name, self.cycle_us, CYCLE_US_QUANTUM)
            )
        self.drive_profile = config.get("drive_profile", "a6ec").strip()
        if self.drive_profile not in DRIVE_PROFILES:
            raise config.error(
                "ethercat_node %s: drive_profile=%r is unknown (known: %s)"
                % (self.name, self.drive_profile, ", ".join(DRIVE_PROFILES))
            )
        self.vendor_id = self._parse_identity(config, "vendor_id")
        self.product_code = self._parse_identity(config, "product_code")
        missing = missing_identity_options(
            self.drive_profile, self.vendor_id, self.product_code
        )
        if missing:
            raise config.error(
                "ethercat_node %s: drive_profile=%s ships no built-in identity "
                "and %s is unset or zero — read the pair off the bus with "
                "`ethercat slaves -v`, or take it from the drive's ESI. A zero "
                "product code is not a wildcard: the master would accept the "
                "slave configuration, never attach it, and the bus would fail "
                "at the OP walk instead of here"
                % (self.name, self.drive_profile, " and ".join(missing))
            )
        # Optional PDO groups. Unset leaves the drive profile's own answer in
        # place. A drive whose dictionary lacks touch probe or digital I/O
        # refuses the entire map — rc=-6 at bring-up — and before these existed
        # the only way past that was editing C and rebuilding. Nothing in the
        # endpoint reads either group, so turning them off costs no function
        # and takes 20 bytes per drive off every cycle.
        self.map_touch_probe = config.getboolean("pdo_touch_probe", None)
        self.map_digital_io = config.getboolean("pdo_digital_io", None)
        self.map_following_error = config.getboolean(
            "pdo_following_error", None
        )
        self.dynamics_profile = servo_axis.read_dynamics_profile_option(config)
        self.live_dynamics_profile = None
        # Default 0: strict - any late frame faults. Deliberate fail-loud
        # choice so late cycles are caught, not tolerated; raise it
        # explicitly per node if a bounded budget is ever wanted.
        self.late_tolerance_us = config.getfloat(
            "late_tolerance_us", default=0.0, minval=0.0
        )
        self.group_delay_us = config.getfloat(
            "group_delay_us", default=float(self.cycle_us), minval=0.0
        )
        self.engine_handle = None
        self._counts_per_mm = None
        self._slot_by_motor = {}
        self._torque_motors = set()
        self.printer.register_event_handler("klippy:mcu_identify", self._claim)
        self.printer.register_event_handler(
            "klippy:shutdown", self._handle_shutdown
        )
        self.printer.load_object(config, "servo_capture")
        self.printer.load_object(config, "servo_param")

    @staticmethod
    def _parse_identity(config, option):
        """EtherCAT identities are published as hex, so accept the 0x form the
        ESI and `ethercat slaves -v` both print, as well as plain decimal."""
        raw = config.get(option, None)
        if raw is None:
            return 0
        text = raw.strip()
        try:
            return int(text, 16 if text.lower().startswith("0x") else 10)
        except ValueError:
            raise config.error(
                "ethercat_node %s: %s=%r is not an integer"
                % (config.get_name().split()[-1], option, raw)
            )

    def _find_motors(self):
        toolhead = self.printer.lookup_object("toolhead")
        kin = toolhead.get_kinematics()
        found = []
        for lane_idx, _axis_name, _motor_names in kin.lanes():
            rail = kin.rails[lane_idx]
            if not isinstance(rail, servo_axis.ServoRail):
                continue
            for motor in rail.get_motors():
                if motor.get_node_name() == self.name:
                    found.append((lane_idx, motor))
        if not found:
            raise self.printer.config_error(
                "ethercat_node %s: no servo motor with node=%s — "
                "cannot locate any drives" % (self.name, self.name)
            )
        return found

    def _validate_chain(self, motors):
        by_index = {}
        for _global_axis, motor in motors:
            idx = motor.get_chain_index()
            if idx >= EC_RT_MAX_SLAVES:
                raise self.printer.config_error(
                    "ethercat_node %s: motor %s ethercat_chain_index=%d "
                    "exceeds the %d-drive endpoint limit (valid 0..%d)"
                    % (
                        self.name,
                        motor.get_motor_name(),
                        idx,
                        EC_RT_MAX_SLAVES,
                        EC_RT_MAX_SLAVES - 1,
                    )
                )
            if idx in by_index:
                raise self.printer.config_error(
                    "ethercat_node %s: motors %s and %s share "
                    "ethercat_chain_index=%d — each drive on a chain needs a "
                    "distinct position"
                    % (
                        self.name,
                        by_index[idx],
                        motor.get_motor_name(),
                        idx,
                    )
                )
            by_index[idx] = motor.get_motor_name()

    def _validate_dynamics_profiles(self, motors):
        per_servo = [
            (motor.get_motor_name(), motor.get_dynamics_profile())
            for _global_axis, motor in motors
        ]
        configured = [
            name for name, profile in per_servo if profile is not None
        ]
        if not configured:
            return
        if self.dynamics_profile is not None:
            raise self.printer.config_error(
                "ethercat_node %s: dynamics_profile is set on [ethercat_node] "
                "and on [motor %s]; a node is either coupled (one node-level "
                "profile) or independent (one profile per motor), not both"
                % (self.name, configured[0])
            )
        missing = [name for name, profile in per_servo if profile is None]
        if missing:
            raise self.printer.config_error(
                "ethercat_node %s: dynamics_profile must be set on every motor "
                "or none — missing on: %s" % (self.name, ", ".join(missing))
            )

    def _validate_coupled_uniformity(self, motors):
        if self.dynamics_profile is None:
            return
        for option, read in COUPLED_UNIFORM_OPTIONS:
            values = {
                motor.get_motor_name(): read(motor)
                for _global_axis, motor in motors
            }
            if len(set(values.values())) > 1:
                raise self.printer.config_error(
                    "ethercat_node %s: a coupled (node-level) "
                    "dynamics_profile computes each motor's torque "
                    "feedforward from every motor's commanded kinematics, "
                    "so %s must be identical across the node — got %s"
                    % (
                        self.name,
                        option,
                        ", ".join(
                            "%s=%s" % (name, value)
                            for name, value in sorted(values.items())
                        ),
                    )
                )

    def _claim(self):
        if self.engine_handle is not None:
            return
        motors = sorted(
            self._find_motors(),
            key=lambda pair: (pair[0], pair[1].get_chain_index()),
        )
        self._validate_chain(motors)
        self._slot_by_motor = {
            motor.get_motor_name(): slot
            for slot, (_global_axis, motor) in enumerate(motors)
        }
        self._validate_dynamics_profiles(motors)
        self._validate_coupled_uniformity(motors)
        drives = []
        for global_axis, motor in motors:
            following_error_counts, max_torque_tenth_pct = (
                motor.get_session_drive_limits()
            )
            velocity_ff, ff_max_torque = motor.get_ff_config()
            drives.append(
                EthercatDrive(
                    chain_index=motor.get_chain_index(),
                    axis=global_axis,
                    counts_per_mm=motor.get_counts_per_mm(),
                    rotation_distance=motor.get_rotation_distance(),
                    following_error_counts=following_error_counts,
                    max_torque_tenth_pct=max_torque_tenth_pct,
                    velocity_ff=velocity_ff,
                    ff_max_torque=ff_max_torque,
                    invert_direction=motor.get_invert_direction(),
                    dynamics_profile=motor.get_dynamics_profile(),
                )
            )
        self._counts_per_mm = motors[0][1].get_counts_per_mm()
        engine = self.printer.lookup_object("motion_engine")
        try:
            self.engine_handle = engine.claim_ethercat_node(
                self.name,
                self.socket_path,
                self.interface,
                self.endpoint,
                self.cycle_us,
                self.dynamics_profile,
                drives,
                late_tolerance_us=self.late_tolerance_us,
                group_delay_us=self.group_delay_us,
                drive_profile=self.drive_profile,
                vendor_id=self.vendor_id,
                product_code=self.product_code,
                map_touch_probe=self.map_touch_probe,
                map_digital_io=self.map_digital_io,
                map_following_error=self.map_following_error,
            )
        except RuntimeError as e:
            raise self.printer.config_error(str(e))
        logging.info(
            "ethercat_node %s: claimed handle=%s socket=%s interface=%s "
            "endpoint=%s drives=%s dynamics_profile=%s drive_profile=%s "
            "vendor_id=0x%08x product_code=0x%08x",
            self.name,
            self.engine_handle,
            self.socket_path,
            self.interface,
            self.endpoint,
            drives,
            self.dynamics_profile,
            self.drive_profile,
            self.vendor_id,
            self.product_code,
        )
        for slot, (_global_axis, motor) in enumerate(motors):
            self._push_drive_params(motor, slot)
        reactor = self.printer.get_reactor()
        reactor.register_timer(
            self._poll_drive_fault,
            reactor.monotonic() + DRIVE_FAULT_POLL_PERIOD,
        )

    def _handle_shutdown(self):
        if self.engine_handle is None:
            return
        engine = self.printer.lookup_object("motion_engine")
        try:
            engine.stop_node(self.engine_handle)
        except Exception:
            logging.exception(
                "ethercat_node %s: THE DRIVES WERE NOT STOPPED — stop_node "
                "failed on handle=%s. The contactor is what removes power; "
                "this path is what tells the drives about it, and it did not.",
                self.name,
                self.engine_handle,
            )
            return
        logging.info(
            "ethercat_node %s: servo motion discarded on shutdown (handle=%s)",
            self.name,
            self.engine_handle,
        )

    def _poll_drive_fault(self, eventtime):
        engine = self.printer.lookup_object("motion_engine")
        death = engine.take_endpoint_death(self.engine_handle)
        if death is not None:
            self.printer.invoke_shutdown(
                "EtherCAT endpoint died mid-session on node %s: %s"
                % (self.name, death)
            )
            return self.printer.get_reactor().NEVER
        fault = engine.take_drive_fault(self.engine_handle)
        if fault is None:
            return eventtime + DRIVE_FAULT_POLL_PERIOD
        if fault == FRAME_LATE_FAULT_CODE:
            msg = (
                "EtherCAT frame-timing fault on node %s: the realtime "
                "endpoint sent a frame later than late_tolerance_us and "
                "parked the drives (host CPU stall, not a drive alarm)"
                % (self.name,)
            )
        elif fault == CYCLE_SKIP_FAULT_CODE:
            msg = (
                "EtherCAT cycle-skip fault on node %s: the realtime "
                "endpoint overran a full cycle and the drives coasted on "
                "a stale target (host CPU stall, not a drive alarm)"
                % (self.name,)
            )
        elif fault == TORQUE_GATE_FAULT_CODE:
            msg = (
                "EtherCAT torque-gate fault on node %s: a torque disable came "
                "due with motion still queued. This is the endpoint refusing "
                "an inconsistent state, not a drive alarm — the drives were "
                "disabled on the way out, but the endpoint is gone and a "
                "restart is needed" % (self.name,)
            )
        else:
            msg = (
                "EtherCAT drive fault 0x%04x on node %s — drive parked by"
                " the realtime endpoint" % (fault, self.name)
            )
        self.printer.invoke_shutdown(msg)
        return self.printer.get_reactor().NEVER

    def _push_drive_params(self, motor, slot):
        params = motor.get_sdo_params()
        if not params:
            return
        engine = self.printer.lookup_object("motion_engine")
        for index, subindex, size, value in params:
            try:
                engine.sdo_write(
                    self.engine_handle, slot, index, subindex, size, value
                )
            except RuntimeError as e:
                raise self.printer.config_error(
                    "ethercat_node %s: claim-time drive param "
                    "0x%04x.%d = %d (slot %d) failed: %s"
                    % (self.name, index, subindex, value, slot, e)
                )
            logging.info(
                "ethercat_node %s: drive param 0x%04x.%d = %d pushed (slot %d)",
                self.name,
                index,
                subindex,
                value,
                slot,
            )

    def get_engine_handle(self):
        return self.engine_handle

    def get_counts_per_mm(self):
        return self._counts_per_mm

    def get_cycle_us(self):
        return self.cycle_us

    def get_slot_for_motor(self, motor_name):
        return self._slot_by_motor.get(motor_name)

    def get_drive_count(self):
        return len(self._slot_by_motor)

    def get_dynamics_profile(self):
        return self.dynamics_profile

    def set_live_dynamics_profile(self, path):
        self.live_dynamics_profile = path

    def get_live_dynamics_profile(self):
        return self.live_dynamics_profile or self.dynamics_profile

    def set_motor_torque(self, motor_name, value, print_time):
        if self.engine_handle is None:
            raise self.printer.command_error(
                "servo torque: ethercat_node %s has no engine handle"
                % (self.name,)
            )
        engine = self.printer.lookup_object("motion_engine")
        if value:
            first = not self._torque_motors
            self._torque_motors.add(motor_name)
            if first:
                return engine.set_torque_deferred(
                    self.engine_handle, True, print_time
                )
        else:
            self._torque_motors.discard(motor_name)
            if not self._torque_motors:
                engine.set_torque(self.engine_handle, False, print_time)
        return None


def load_config_prefix(config):
    return EtherCatNode(config)
