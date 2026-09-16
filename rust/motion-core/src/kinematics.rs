use runtime::segment::KinematicTag;

pub const SPATIAL_AXES: usize = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KinematicsKind {
    CoreXy,
    Cartesian,
    Markforged,
}

#[derive(Debug, Clone, Copy)]
pub struct KinematicsModule {
    kind: KinematicsKind,
    axis_to_motor: [[f64; SPATIAL_AXES]; SPATIAL_AXES],
    motor_to_axis: [[f64; SPATIAL_AXES]; SPATIAL_AXES],
}

#[derive(Debug, thiserror::Error)]
#[error("unknown kinematics tag {0}; known: 0=corexy, 1=cartesian, 2=markforged")]
pub struct UnknownKinematicsTag(pub u8);

const COREXY_AXIS_TO_MOTOR: [[f64; SPATIAL_AXES]; SPATIAL_AXES] =
    [[1.0, 1.0, 0.0], [1.0, -1.0, 0.0], [0.0, 0.0, 1.0]];
const COREXY_MOTOR_TO_AXIS: [[f64; SPATIAL_AXES]; SPATIAL_AXES] =
    [[0.5, 0.5, 0.0], [0.5, -0.5, 0.0], [0.0, 0.0, 1.0]];
const IDENTITY: [[f64; SPATIAL_AXES]; SPATIAL_AXES] =
    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]];

/// Sign of the Y term the Markforged X motor carries. Y runs a straight loop
/// on the frame, so lane 1 is pure Y; X runs a T-shaped loop anchored to the
/// frame, so driving the gantry in Y drags the carriage along it and lane 0
/// absorbs that drag on top of its own travel.
///
/// The bench check that fixes this sign: hold the X motor still and push the
/// gantry to +Y. A carriage that slides -X is `1.0`; one that slides +X is
/// `-1.0`. Flipping this constant flips the whole kinematics — both matrices
/// and every lane/axis coupling answer derive from it.
pub const MARKFORGED_Y_COUPLING: f64 = 1.0;

const MARKFORGED_AXIS_TO_MOTOR: [[f64; SPATIAL_AXES]; SPATIAL_AXES] = [
    [1.0, MARKFORGED_Y_COUPLING, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
];
const MARKFORGED_MOTOR_TO_AXIS: [[f64; SPATIAL_AXES]; SPATIAL_AXES] = [
    [1.0, -MARKFORGED_Y_COUPLING, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
];

fn matrix_vector(
    matrix: &[[f64; SPATIAL_AXES]; SPATIAL_AXES],
    vector: [f64; SPATIAL_AXES],
) -> [f64; SPATIAL_AXES] {
    let mut out = [0.0; SPATIAL_AXES];
    for (row, slot) in matrix.iter().zip(out.iter_mut()) {
        *slot = row
            .iter()
            .zip(vector.iter())
            .map(|(weight, value)| weight * value)
            .sum();
    }
    out
}

impl KinematicsModule {
    pub fn from_tag(tag: u8) -> Result<Self, UnknownKinematicsTag> {
        let (kind, axis_to_motor, motor_to_axis) = if tag == KinematicTag::CoreXy as u8 {
            (
                KinematicsKind::CoreXy,
                COREXY_AXIS_TO_MOTOR,
                COREXY_MOTOR_TO_AXIS,
            )
        } else if tag == KinematicTag::Cartesian as u8 {
            (KinematicsKind::Cartesian, IDENTITY, IDENTITY)
        } else if tag == KinematicTag::Markforged as u8 {
            (
                KinematicsKind::Markforged,
                MARKFORGED_AXIS_TO_MOTOR,
                MARKFORGED_MOTOR_TO_AXIS,
            )
        } else {
            return Err(UnknownKinematicsTag(tag));
        };
        Ok(Self {
            kind,
            axis_to_motor,
            motor_to_axis,
        })
    }

    pub fn kind(&self) -> KinematicsKind {
        self.kind
    }

    pub fn tag(&self) -> u8 {
        match self.kind {
            KinematicsKind::CoreXy => KinematicTag::CoreXy as u8,
            KinematicsKind::Cartesian => KinematicTag::Cartesian as u8,
            KinematicsKind::Markforged => KinematicTag::Markforged as u8,
        }
    }

    pub fn lane_weights(&self, lane: usize) -> [f64; SPATIAL_AXES] {
        self.axis_to_motor[lane]
    }

    pub fn lane_is_identity(&self, lane: usize) -> bool {
        let mut unit = [0.0; SPATIAL_AXES];
        unit[lane] = 1.0;
        self.axis_to_motor[lane] == unit
    }

    /// Motor lanes whose position changes when `axis` alone moves — the
    /// `axis` column of the axis-to-motor map. A lane weighted zero for this
    /// axis stands still, so it takes no part in the move.
    pub fn lanes_driven_by_axis(&self, axis: usize) -> [bool; SPATIAL_AXES] {
        let mut driven = [false; SPATIAL_AXES];
        for (lane, weights) in self.axis_to_motor.iter().enumerate() {
            driven[lane] = weights[axis] != 0.0;
        }
        driven
    }

    /// Motor lanes that must be known to reconstruct `axis` — the `axis` row
    /// of the motor-to-axis map. A lane weighted zero never enters that sum,
    /// so the axis is recoverable without it.
    pub fn lanes_feeding_axis(&self, axis: usize) -> [bool; SPATIAL_AXES] {
        let mut feeding = [false; SPATIAL_AXES];
        for (lane, weight) in self.motor_to_axis[axis].iter().enumerate() {
            feeding[lane] = *weight != 0.0;
        }
        feeding
    }

    pub fn axis_drives_one_lane(&self, axis: usize) -> bool {
        self.lanes_driven_by_axis(axis)
            .iter()
            .filter(|driven| **driven)
            .count()
            == 1
    }

    pub fn xy_is_coupled(&self) -> bool {
        !(self.axis_drives_one_lane(0) && self.axis_drives_one_lane(1))
    }

    pub fn forward(&self, axes: [f64; SPATIAL_AXES]) -> [f64; SPATIAL_AXES] {
        matrix_vector(&self.axis_to_motor, axes)
    }

    pub fn inverse(&self, motors: [f64; SPATIAL_AXES]) -> [f64; SPATIAL_AXES] {
        matrix_vector(&self.motor_to_axis, motors)
    }
}

#[cfg(test)]
mod tests;
