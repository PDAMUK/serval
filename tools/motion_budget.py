"""What this machine can accelerate and how fast it can run, from the repo's
own motion maths plus the drive data the build guide establishes.

Three things decide the answer, and all three already exist here:

`rust/motion-core/src/kinematics.rs` gives the lane mixing — which motor turns
for a move along which axis, and by how much. `rust/ethercat-rt/src/dynamics.rs`
gives the torque model the endpoint already uses for feedforward: per mode,
`force = mass * (frame . accel)`, lifted back to a slot by `frame[mode][slot]`.
`klippy/motion_setup.py` gives the stepper step-rate ceiling.

What is *not* from the repo is the motor itself — rated torque, rotor inertia,
rated speed. Those come from the build guide's drive section, which read them
out of the ProNet manual, and they are the numbers to change if the machine
changes. `SOURCES` records which is which, because a number that looks
authoritative and is a guess is the failure this whole audit kept finding.
"""

from __future__ import annotations

import dataclasses
import math

SOURCES = {
    "markforged_frame": "rust/motion-core/src/kinematics.rs MARKFORGED_MOTOR_TO_AXIS",
    "corexy_frame": "rust/motion-core/src/kinematics.rs COREXY_MOTOR_TO_AXIS",
    "torque_model": "rust/ethercat-rt/src/dynamics.rs DynamicsModel::eval",
    "corner_deviation": "rust/geometry/src/frontend.rs corner_deviation_from_scv",
    "stepper_ceiling": "klippy/motion_setup.py motor_velocity_ceiling",
    "rated_torque_nm": "docs/rewrite/*: EMJ-04AFD22, 400 W, about 1.27 N·m",
    "rotor_inertia": "docs/rewrite/*: EMJ-04AFD22 rotor inertia 0.31e-4 kg·m²",
    "torque_ceiling_pct": "docs/rewrite/*: Pn401/Pn402 run 0-300 %",
    "belt_tension": (
        "SDP/SI Technical Section Table 3, Allowable Working Tension of "
        "Different Belt Constructions, neoprene column, per 25.4 mm width"
    ),
    "belt_temperature": "Gates PowerGrip GT3 and 2GT EPDM published ranges",
    "gt15_tension": "ESTIMATE — Gates publishes no 1.5 mm pitch; see BELTS",
}

# klippy/motion_setup.py
STEP_EDGE_FLOOR_SECONDS = 1e-6
STEP_ISR_BUDGET_FRACTION = 0.5
# rust/geometry/src/frontend.rs
CORNER_DEVIATION_SCV_FACTOR = math.sqrt(2.0) - 1.0
# rust/motion-core/src/kinematics.rs
MARKFORGED_Y_COUPLING = 1.0

MM_PER_INCH = 25.4

# Allowable working tension, neoprene, per 25.4 mm of belt width. GT3 rows of
# SDP/SI Table 3; the MXL row (2.03 mm, 80 N) and the HTD 3 mm row (285 N) sit
# either side of the GT3 figures and agree with them in scale.
#
# 1.5 mm is not a Gates pitch and has no published figure. The value below is a
# linear-in-pitch extrapolation from 2 mm, marked estimated everywhere it is
# used, because a fabricated number that reads like a datasheet is the failure
# this repository keeps finding.
BELTS = {
    "GT1.5": {"pitch_mm": 1.5, "tension_n_per_inch": 83.0, "estimated": True},
    "GT2": {"pitch_mm": 2.0, "tension_n_per_inch": 111.0, "estimated": False},
    "GT3": {"pitch_mm": 3.0, "tension_n_per_inch": 507.0, "estimated": False},
}

# The tensile cord is fibreglass in both constructions, so the strength is the
# same and only the rubber changes. EPDM buys temperature, not force — the
# opposite of what "upgraded belt" suggests.
BELT_MATERIALS = {
    "standard": {"label": "Standard (neoprene)", "min_c": -35.0, "max_c": 80.0},
    "epdm": {"label": "EPDM high-temp", "min_c": -45.0, "max_c": 135.0},
}

BELT_WIDTHS_MM = (6.0, 9.0, 12.0)


@dataclasses.dataclass(frozen=True)
class Belt:
    profile: str = "GT2"
    width_mm: float = 6.0
    material: str = "standard"

    @property
    def pitch_mm(self) -> float:
        return BELTS[self.profile]["pitch_mm"]

    @property
    def tension_estimated(self) -> bool:
        return BELTS[self.profile]["estimated"]

    @property
    def allowable_tension_n(self) -> float:
        per_inch = BELTS[self.profile]["tension_n_per_inch"]
        return per_inch * self.width_mm / MM_PER_INCH

    @property
    def temperature_range_c(self):
        spec = BELT_MATERIALS[self.material]
        return (spec["min_c"], spec["max_c"])


# Slot-to-axis ("frame" in dynamics.rs, motor_to_axis in kinematics.rs), XY only.
FRAMES = {
    "markforged": ((1.0, -MARKFORGED_Y_COUPLING), (0.0, 1.0)),
    "corexy": ((0.5, 0.5), (0.5, -0.5)),
    "cartesian": ((1.0, 0.0), (0.0, 1.0)),
}


def axis_to_motor(frame):
    """The inverse mixing: how far each motor turns for a unit axis move."""
    (a, b), (c, d) = frame
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError("frame is singular; it cannot describe a machine")
    return ((d / det, -b / det), (-c / det, a / det))


@dataclasses.dataclass(frozen=True)
class Motor:
    """A servo and the pulley on its shaft.

    The pulley's *pitch* is the belt's, not the motor's — it lives on `Belt`
    so there is one source for it. Everything geometric therefore hangs off
    `Machine`, which holds both.
    """

    rated_torque_nm: float = 1.27
    rotor_inertia_kgm2: float = 0.31e-4
    rated_rpm: float = 3000.0
    max_rpm: float = 5000.0
    torque_limit_pct: float = 100.0
    pulley_teeth: int = 20

    @property
    def torque_nm(self) -> float:
        return self.rated_torque_nm * self.torque_limit_pct / 100.0


@dataclasses.dataclass(frozen=True)
class Machine:
    kinematics: str = "markforged"
    motor: Motor = dataclasses.field(default_factory=Motor)
    belt: Belt = dataclasses.field(default_factory=Belt)
    gantry_mass_kg: float = 1.6
    carriage_mass_kg: float = 0.6

    @property
    def rotation_distance_mm(self) -> float:
        """`[motor] rotation_distance` — mm of belt per motor revolution."""
        return self.motor.pulley_teeth * self.belt.pitch_mm

    @property
    def pulley_radius_m(self) -> float:
        return self.rotation_distance_mm / (2.0 * math.pi) / 1000.0

    @property
    def belt_force_n(self) -> float:
        """Belt force the motor can produce at its configured torque limit."""
        return self.motor.torque_nm / self.pulley_radius_m

    @property
    def free_speed_mm_s(self) -> float:
        return self.motor.max_rpm / 60.0 * self.rotation_distance_mm

    @property
    def belt_torque_ceiling_nm(self) -> float:
        """The belt's allowable tension seen as a torque at this pulley, so it
        compares directly with the motor's limit."""
        return self.belt.allowable_tension_n * self.pulley_radius_m

    @property
    def torque_ceiling_nm(self) -> float:
        return min(self.motor.torque_nm, self.belt_torque_ceiling_nm)

    @property
    def limiting_part(self) -> str:
        return (
            "belt"
            if self.belt_torque_ceiling_nm < self.motor.torque_nm
            else "motor"
        )

    @property
    def frame(self):
        return FRAMES[self.kinematics]

    def mode_mass_kg(self):
        """Mass each axis moves. X moves the carriage along the gantry; Y moves
        the gantry and everything on it."""
        return (
            self.carriage_mass_kg,
            self.gantry_mass_kg + self.carriage_mass_kg,
        )


def slot_torques_nm(machine: Machine, axis_accel_mm_s2):
    """`dynamics.rs`'s eval, in SI and with the rotors added.

    Per mode: force = mass * mode_accel. Lifted to a slot by frame[mode][slot],
    exactly as `tau += row[slot] * mode_force`. The rotor term is the part a
    fitted profile folds into its mass and a predictive model must add: each
    motor also spins its own inertia at the slot's own acceleration.
    """
    frame = machine.frame
    a2m = axis_to_motor(frame)
    masses = machine.mode_mass_kg()
    accel_m_s2 = [a / 1000.0 for a in axis_accel_mm_s2]

    radius = machine.pulley_radius_m
    slot_accel = [
        sum(a2m[s][k] * accel_m_s2[k] for k in range(2)) for s in range(2)
    ]
    torques = []
    for slot in range(2):
        belt_force = sum(
            frame[k][slot] * masses[k] * accel_m_s2[k] for k in range(2)
        )
        rotor = machine.motor.rotor_inertia_kgm2 * slot_accel[slot] / radius
        torques.append(belt_force * radius + rotor)
    return torques


def max_axis_accel_mm_s2(machine: Machine, direction) -> float:
    """Largest acceleration along `direction` before any motor is asked for
    more torque than its limit. Linear in accel, so one probe scales."""
    norm = math.hypot(*direction)
    if norm == 0.0:
        raise ValueError("direction must be non-zero")
    unit = [d / norm for d in direction]
    probe = slot_torques_nm(machine, [u * 1000.0 for u in unit])
    worst = max(abs(t) for t in probe)
    if worst == 0.0:
        return math.inf
    return 1000.0 * machine.torque_ceiling_nm / worst


def max_axis_velocity_mm_s(machine: Machine, direction) -> float:
    """Free speed, limited by whichever motor turns fastest for this move."""
    norm = math.hypot(*direction)
    unit = [d / norm for d in direction]
    a2m = axis_to_motor(machine.frame)
    turns = [abs(sum(a2m[s][k] * unit[k] for k in range(2))) for s in range(2)]
    fastest = max(turns)
    if fastest == 0.0:
        return math.inf
    return machine.free_speed_mm_s / fastest


def stepper_velocity_ceiling_mm_s(
    rotation_distance_mm,
    microsteps,
    full_steps_per_rev=200,
    pulse_duration_s=2e-6,
    both_edge=False,
):
    """klippy/motion_setup.py motor_velocity_ceiling, with step_dist spelled
    out: the ISR budget fraction of real time divided by what one step costs."""
    step_dist = rotation_distance_mm / (full_steps_per_rev * microsteps)
    per_step_s = STEP_EDGE_FLOOR_SECONDS + (
        0.0 if both_edge else pulse_duration_s
    )
    return STEP_ISR_BUDGET_FRACTION / per_step_s * step_dist


def corner_deviation_from_scv(scv_mm_s, accel_mm_s2):
    """rust/geometry/src/frontend.rs."""
    return scv_mm_s * scv_mm_s * CORNER_DEVIATION_SCV_FACTOR / accel_mm_s2


def reflected_rotor_mass_kg(machine: Machine) -> float:
    return machine.motor.rotor_inertia_kgm2 / (machine.pulley_radius_m**2)


def inertia_ratio(machine: Machine) -> float:
    """Load-to-rotor, the number the drive manual ties to A.13 at about 30x."""
    return max(machine.mode_mass_kg()) / reflected_rotor_mass_kg(machine)
