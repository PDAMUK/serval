mod bridge;
#[cfg(feature = "snapshot")]
pub mod viz;

#[doc(hidden)]
pub use motion_core::{
    anchor, classify, config, drain, enqueue, fence, homing, kinematics, lock_ext, mcu_config,
    motion_history, nudge, pump, timing, types, worker,
};

#[doc(hidden)]
pub use motion_services::{
    bg_call, logging, mcu_log, position_query, remote_trigger, servo_capture, servo_sdo,
    servo_torque,
};

#[cfg(feature = "test-support")]
#[doc(hidden)]
pub use motion_core::seam_test_harness;

use pyo3::prelude::*;

use bridge::{PyClockSyncEstimator, PyDecayRegression, PyMotionEngine};

#[pymodule]
fn _motion_engine(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyMotionEngine>()?;
    m.add_class::<PyClockSyncEstimator>()?;
    m.add_class::<PyDecayRegression>()?;
    m.add(
        "MARKFORGED_Y_COUPLING",
        motion_core::kinematics::MARKFORGED_Y_COUPLING,
    )?;
    let tags = pyo3::types::PyDict::new(_py);
    for (name, tag) in [
        ("corexy", runtime::segment::KinematicTag::CoreXy),
        ("cartesian", runtime::segment::KinematicTag::Cartesian),
        ("markforged", runtime::segment::KinematicTag::Markforged),
    ] {
        tags.set_item(name, tag as u8)?;
    }
    m.add("KINEMATIC_TAGS", tags)?;
    #[cfg(feature = "snapshot")]
    m.add_function(wrap_pyfunction!(viz::pipeline_snapshot, m)?)?;
    Ok(())
}
