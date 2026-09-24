use super::DropReport;

#[test]
fn no_report_while_nothing_dropped() {
    let report = DropReport::new();
    assert_eq!(report.newly_dropped(0), None);
    assert_eq!(report.newly_dropped(0), None);
}

#[test]
fn first_growth_reports_cumulative_count() {
    let report = DropReport::new();
    assert_eq!(report.newly_dropped(7), Some(7));
}

#[test]
fn unchanged_count_after_a_report_stays_quiet() {
    let report = DropReport::new();
    assert_eq!(report.newly_dropped(7), Some(7));
    assert_eq!(report.newly_dropped(7), None);
    assert_eq!(report.newly_dropped(7), None);
}

#[test]
fn each_growth_reports_the_new_cumulative_total() {
    let report = DropReport::new();
    assert_eq!(report.newly_dropped(3), Some(3));
    assert_eq!(report.newly_dropped(3), None);
    assert_eq!(report.newly_dropped(150), Some(150));
    assert_eq!(report.newly_dropped(150), None);
}

use super::{render_line, LogRecord};
use serde_json::{Map, Value};
use time::OffsetDateTime;

fn record(fields: Map<String, Value>) -> LogRecord {
    LogRecord {
        time: OffsetDateTime::UNIX_EPOCH,
        level: "info",
        target: "obs_tests",
        message: Some("hello".into()),
        fields,
    }
}

#[test]
fn render_line_carries_the_wire_fields() {
    let mut fields = Map::new();
    fields.insert("event".into(), Value::String("unit".into()));
    fields.insert("count".into(), Value::from(3));
    let line = render_line(record(fields));
    let parsed: Value = serde_json::from_str(line.trim_end()).unwrap();
    assert_eq!(parsed["_time"], "1970-01-01T00:00:00.000Z");
    assert_eq!(parsed["_msg"], "hello");
    assert_eq!(parsed["level"], "info");
    assert_eq!(parsed["source"], "host-ec");
    assert_eq!(parsed["subsystem"], "ethercat");
    assert_eq!(parsed["event"], "unit");
    assert_eq!(parsed["count"], 3);
    assert!(line.ends_with('\n'));
}

#[test]
fn render_line_hoists_subsystem_out_of_the_field_map() {
    let mut fields = Map::new();
    fields.insert("subsystem".into(), Value::String("trip-relay".into()));
    let line = render_line(record(fields));
    let parsed: Value = serde_json::from_str(line.trim_end()).unwrap();
    assert_eq!(parsed["subsystem"], "trip-relay");
}

#[test]
fn a_full_channel_drops_instead_of_blocking() {
    let (sender, receiver) = crossbeam_channel::bounded::<LogRecord>(1);
    sender.try_send(record(Map::new())).unwrap();
    let started = std::time::Instant::now();
    let verdict = sender.try_send(record(Map::new()));
    assert!(matches!(
        verdict,
        Err(crossbeam_channel::TrySendError::Full(_))
    ));
    assert!(started.elapsed() < std::time::Duration::from_millis(10));
    drop(receiver);
    let verdict = sender.try_send(record(Map::new()));
    assert!(matches!(
        verdict,
        Err(crossbeam_channel::TrySendError::Disconnected(_))
    ));
}

use super::{RotatingLog, BACKUP_COUNT, MAX_BYTES};

/// `host-ec.jsonl` was opened append-only and never rotated. With two drives
/// at the default 250 us cycle the endpoint writes two per-slot telemetry
/// lines and a stage-timing line every half second — about 1.8 kB a beat as
/// `render_line` formats them, some 300 MB a day for as long as the node is
/// claimed — onto a CB2's 8-16 GB eMMC. The host's own files are capped.
#[test]
fn the_endpoint_log_rotates_and_keeps_a_bounded_number_of_backups() {
    let dir = std::env::temp_dir().join(format!("obs-rotate-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("host-ec.jsonl");
    let line = vec![b'x'; 99];
    let mut log = RotatingLog::open(&path, 1000, 3).unwrap();
    for _ in 0..100 {
        log.write_line(&line).unwrap();
    }
    let mut names: Vec<String> = std::fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    names.sort();
    assert_eq!(
        names,
        [
            "host-ec.jsonl",
            "host-ec.jsonl.1",
            "host-ec.jsonl.2",
            "host-ec.jsonl.3"
        ]
    );
    for name in &names {
        assert!(std::fs::metadata(dir.join(name)).unwrap().len() <= 1000);
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn the_endpoint_log_is_capped_like_the_host_logs() {
    let host_writer = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../motion-services/src/logging/writer.rs"
    ))
    .unwrap();
    assert!(host_writer.contains("pub const DEFAULT_MAX_BYTES: u64 = 32 * 1024 * 1024;"));
    assert!(host_writer.contains("pub const DEFAULT_BACKUP_COUNT: u32 = 5;"));
    assert_eq!(MAX_BYTES, 32 * 1024 * 1024);
    assert_eq!(BACKUP_COUNT, 5);
}
