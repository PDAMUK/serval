use super::mcu_level_str;

/// The wire carries the level as a bare number; this is where it becomes the
/// word a reader sees in the JSONL. The same scale is written down in
/// src/event_log.h as EVENT_LOG_LEVEL_* and in runtime's fault_helpers, whose
/// c_header_mirrors test compares those two. This is the third copy, and a
/// renumber here silently relabels every record instead of failing anything.
#[test]
fn every_wire_level_maps_to_its_word() {
    assert_eq!(mcu_level_str(0), "trace");
    assert_eq!(mcu_level_str(1), "debug");
    assert_eq!(mcu_level_str(2), "warn");
    assert_eq!(mcu_level_str(3), "error");
}

/// An MCU that learns a level this host does not know must still produce a
/// record. Erring towards "error" keeps an unknown level visible rather than
/// filtering it out as trace.
#[test]
fn an_unknown_level_reads_as_error_rather_than_vanishing() {
    assert_eq!(mcu_level_str(4), "error");
    assert_eq!(mcu_level_str(u8::MAX), "error");
}
