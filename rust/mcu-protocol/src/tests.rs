use super::result_codes;

/// These literals are the wire contract: both ends of the link are built from
/// them, so a value that moves breaks compatibility with every peer already
/// deployed. Pinned here as literals on purpose — `ethercat-rt`'s
/// `result_code_mirrors` is what checks they still agree with the runtime and
/// endpoint constants they mirror, which this crate cannot see.
#[test]
fn result_codes_are_stable() {
    assert_eq!(result_codes::OK, 0);
    assert_eq!(result_codes::RING_FULL, -309);
    assert_eq!(result_codes::STREAM_HALTED, -142);
    assert_eq!(result_codes::EC_PIECES_WHILE_HALTED, -315);
    assert_eq!(result_codes::INVALID_ARG, -26);
    assert_eq!(result_codes::PIECE_SLOT_GAP, -317);
    assert_ne!(result_codes::RING_FULL, result_codes::INVALID_ARG);
}
