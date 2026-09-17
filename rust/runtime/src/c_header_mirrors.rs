//! The C headers and the Rust constants that mirror them are the same tables
//! written twice, in files neither build can see from the other. Three of them
//! carry a comment saying the copies must match and nothing checked that they
//! did; this module is what checks.
//!
//! Test-only. It reads the headers from the source tree, so it runs on a
//! checkout rather than against a compiled firmware — which is the point: the
//! mismatch it catches is one that compiles cleanly on both sides.

#![allow(clippy::panic, clippy::unwrap_used, clippy::expect_used)]

use std::collections::BTreeMap;
use std::path::PathBuf;

/// `#define NAME VALUE` pairs whose name starts with `prefix`.
fn defines(header: &str, prefix: &str) -> BTreeMap<String, i64> {
    let path: PathBuf = [env!("CARGO_MANIFEST_DIR"), "..", "..", header]
        .iter()
        .collect();
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    let mut found = BTreeMap::new();
    for line in text.lines() {
        let rest = match line.trim().strip_prefix("#define ") {
            Some(rest) => rest.trim(),
            None => continue,
        };
        let mut parts = rest.split_whitespace();
        let (Some(name), Some(value)) = (parts.next(), parts.next()) else {
            continue;
        };
        if !name.starts_with(prefix) {
            continue;
        }
        if let Ok(parsed) = value.parse::<i64>() {
            found.insert(name.to_string(), parsed);
        }
    }
    assert!(
        !found.is_empty(),
        "no {prefix}* defines found in {header} — the header moved or the \
         table was renamed, so this check silently stopped checking"
    );
    found
}

const EVENT_LOG_H: &str = "src/event_log.h";
const STEP_QUEUE_H: &str = "src/step_queue.h";
const FAULT_HANDLER_H: &str = "src/generic/fault_handler.h";
const TRANSPORT_DISPATCH_H: &str = "src/mcu_transport_dispatch.h";

/// The IWDG breadcrumb: the value latched at reset names the hung phase, so a
/// skew here mislabels every watchdog post-mortem.
#[test]
fn isr_phase_constants_match_the_c_header() {
    use crate::isr_phase::*;
    let c = defines(FAULT_HANDLER_H, "RT_PHASE_");
    let rust: BTreeMap<String, i64> = [
        ("RT_PHASE_IDLE", RT_PHASE_IDLE),
        ("RT_PHASE_ISR_ENTER", RT_PHASE_ISR_ENTER),
        ("RT_PHASE_WIDEN", RT_PHASE_WIDEN),
        ("RT_PHASE_GUARD", RT_PHASE_GUARD),
        ("RT_PHASE_TICK", RT_PHASE_TICK),
        ("RT_PHASE_WALK", RT_PHASE_WALK),
        ("RT_PHASE_ARM", RT_PHASE_ARM),
        ("RT_PHASE_CLENSHAW", RT_PHASE_CLENSHAW),
        ("RT_PHASE_STEP_ENQ", RT_PHASE_STEP_ENQ),
        ("RT_PHASE_ISR_EXIT", RT_PHASE_ISR_EXIT),
        ("RT_PHASE_STEPOUT_ENTER", RT_PHASE_STEPOUT_ENTER),
        ("RT_PHASE_STEPOUT_POP", RT_PHASE_STEPOUT_POP),
        ("RT_PHASE_STEPOUT_EMIT", RT_PHASE_STEPOUT_EMIT),
        ("RT_PHASE_STEPOUT_EXIT", RT_PHASE_STEPOUT_EXIT),
    ]
    .into_iter()
    .map(|(name, value)| (name.to_string(), i64::from(value)))
    .collect();
    assert_eq!(rust, c);
}

/// Ring tags are re-emitted verbatim as DIAG event codes, so the header's
/// numbering and the decoder's are one table.
#[test]
fn diag_event_tags_match_the_c_header() {
    use crate::log_codes::*;
    let c = defines(FAULT_HANDLER_H, "DIAG_EV_");
    let rust: BTreeMap<String, i64> = [
        ("DIAG_EV_NONE", 0),
        ("DIAG_EV_TIM5_LONG", i64::from(EVENT_DIAG_TIM5_LONG)),
        ("DIAG_EV_OTG_LONG", i64::from(EVENT_DIAG_OTG_LONG)),
        ("DIAG_EV_USB_OUT_GAP", i64::from(EVENT_DIAG_USB_OUT_GAP)),
        ("DIAG_EV_USB_IN_GAP", i64::from(EVENT_DIAG_USB_IN_GAP)),
        ("DIAG_EV_TX_DROP_KAL", i64::from(EVENT_DIAG_TX_DROP_KAL)),
        ("DIAG_EV_TX_DROP_KLP", i64::from(EVENT_DIAG_TX_DROP_KLP)),
        ("DIAG_EV_ENGINE_XITION", i64::from(EVENT_DIAG_ENGINE_XITION)),
        ("DIAG_EV_RUST_FAULT", i64::from(EVENT_DIAG_RUST_FAULT)),
        (
            "DIAG_EV_FAULT_POSITIONS",
            i64::from(EVENT_DIAG_FAULT_POSITIONS),
        ),
        (
            "DIAG_EV_FAULT_STEP_COUNTS",
            i64::from(EVENT_DIAG_FAULT_STEP_COUNTS),
        ),
    ]
    .into_iter()
    .map(|(name, value)| (name.to_string(), value))
    .collect();
    assert_eq!(rust, c);
}

/// cbindgen does not export these, so the transport header hand-declares the
/// three it needs. Every one it declares must be the value Rust returns.
#[test]
fn transport_return_codes_match_the_c_header() {
    use crate::error::*;
    let rust: BTreeMap<&str, i64> = [
        (
            "RUNTIME_ERR_INVALID_CURVE",
            i64::from(RUNTIME_ERR_INVALID_CURVE),
        ),
        ("RUNTIME_ERR_NOT_INIT", i64::from(RUNTIME_ERR_NOT_INIT)),
        (
            "RUNTIME_ERR_MOTION_RUNTIME_ABSENT",
            i64::from(RUNTIME_ERR_MOTION_RUNTIME_ABSENT),
        ),
    ]
    .into_iter()
    .collect();
    for (name, value) in defines(TRANSPORT_DISPATCH_H, "RUNTIME_ERR_") {
        let expected = rust.get(name.as_str()).unwrap_or_else(|| {
            panic!("{name} is declared in {TRANSPORT_DISPATCH_H} with no Rust counterpart here")
        });
        assert_eq!(*expected, value, "{name} disagrees");
    }
}

/// The level rides the wire as a bare number and is turned back into a word
/// on the host, so a renumber silently relabels every record rather than
/// failing anything.
#[test]
fn log_levels_match_the_c_header() {
    use crate::fault_helpers::*;
    let c = defines(EVENT_LOG_H, "EVENT_LOG_LEVEL_");
    let rust: BTreeMap<String, i64> = [
        ("EVENT_LOG_LEVEL_TRACE", LOG_LEVEL_TRACE),
        ("EVENT_LOG_LEVEL_DEBUG", LOG_LEVEL_DEBUG),
        ("EVENT_LOG_LEVEL_WARN", LOG_LEVEL_WARN),
        ("EVENT_LOG_LEVEL_ERROR", LOG_LEVEL_ERROR),
    ]
    .into_iter()
    .map(|(name, value)| (name.to_string(), i64::from(value)))
    .collect();
    assert_eq!(rust, c);
}

/// The step-queue depth is derived independently on each side, from the same
/// two inputs: the Makefile passes CONFIG_MOTION_SAMPLE_RATE_HZ through as
/// RUNTIME_SAMPLE_RATE_HZ, and this rate is written down in both. The C header
/// rounds up with a ladder of ternaries and build.rs with next_power_of_two,
/// which agree today but are two expressions, not one.
#[test]
fn step_rate_target_matches_the_c_header() {
    let c = defines(STEP_QUEUE_H, "RUNTIME_TARGET_STEP_RATE_HZ");
    assert_eq!(
        c.get("RUNTIME_TARGET_STEP_RATE_HZ"),
        Some(&(crate::sizing::TARGET_STEP_RATE_HZ as i64))
    );
}

/// The C ladder and build.rs's next_power_of_two must agree for every sample
/// rate either side could be built with, not just the one this build used.
#[test]
fn the_two_queue_depth_formulas_agree_over_the_whole_range() {
    fn c_ladder(depth_min: usize) -> usize {
        match depth_min {
            0..=32 => 32,
            33..=64 => 64,
            65..=128 => 128,
            129..=256 => 256,
            _ => 512,
        }
    }
    let target = crate::sizing::TARGET_STEP_RATE_HZ;
    for sample_rate_hz in 1..=200_000usize {
        let max_steps = target.div_ceil(sample_rate_hz).clamp(16, 256);
        let depth_min = 2 * max_steps;
        assert_eq!(
            depth_min.next_power_of_two(),
            c_ladder(depth_min),
            "depths diverge at sample_rate_hz={sample_rate_hz}"
        );
    }
}
