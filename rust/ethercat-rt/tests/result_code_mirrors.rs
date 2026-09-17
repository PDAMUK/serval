//! The wire result codes are declared in three places that cannot see each
//! other: `runtime::error` (the MCU runtime), `mcu_protocol::result_codes`
//! (the wire contract both ends read) and `ethercat_rt::stream_halt` (the
//! endpoint's own piece gate). `mcu-protocol` deliberately depends on neither
//! of the others, so nothing there can compare them and its own test can only
//! restate the literals.
//!
//! This crate is the one that depends on all three, so the comparison lives
//! here. A renumber on any side fails this rather than shipping two ends that
//! disagree about what a refusal means.

use mcu_protocol::result_codes;

#[test]
fn wire_codes_match_the_runtime_they_mirror() {
    assert_eq!(
        result_codes::RING_FULL,
        runtime::error::RUNTIME_ERR_RING_FULL
    );
    assert_eq!(
        result_codes::STREAM_HALTED,
        runtime::error::RUNTIME_ERR_STREAM_HALTED
    );
    assert_eq!(
        result_codes::INVALID_ARG,
        runtime::error::RUNTIME_ERR_INVALID_ARG
    );
    assert_eq!(
        result_codes::PIECE_SLOT_GAP,
        runtime::error::RUNTIME_ERR_PIECE_SLOT_GAP
    );
}

#[test]
fn the_endpoint_piece_gate_code_matches_the_wire_contract() {
    assert_eq!(
        result_codes::EC_PIECES_WHILE_HALTED,
        ethercat_rt::stream_halt::ERR_PIECES_WHILE_HALTED
    );
}

/// The endpoint's gate and the runtime's halt are different refusals that
/// travel the same wire, so they must stay distinguishable.
#[test]
fn the_two_halt_codes_stay_distinct() {
    assert_ne!(
        result_codes::EC_PIECES_WHILE_HALTED,
        result_codes::STREAM_HALTED
    );
}
