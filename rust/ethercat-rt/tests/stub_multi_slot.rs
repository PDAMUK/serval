use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use host_rt::mcu_call::McuCall;
use host_rt::mcu_serial_conn::McuSerialConn;
use mcu_protocol::codec::{Decode, Encode};
use mcu_protocol::messages::{
    MessageKind, PushPieces, PushPiecesResponse, SetTorque, SetTorqueResponse,
};
use runtime::piece_ring::PieceEntry;

const STUB_BIN: &str = env!("CARGO_BIN_EXE_ethercat-rt-stub");

struct KillOnDrop(Child);

impl Drop for KillOnDrop {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn call(conn: &McuSerialConn, kind: MessageKind, body: Vec<u8>) -> Vec<u8> {
    conn.mcu_call(kind, body, Duration::from_secs(5))
        .expect("stub call must succeed")
        .1
}

/// Two drives on one node, X in slot 0 and Y in slot 1, exactly as the bridge
/// spawns the endpoint for the Markforged CB2 machine. The stub used to keep
/// one ring and report one retired count, which the host reads as slot 0's —
/// so a Y piece was retired and credited to X, and the host waited on Y
/// forever. The real endpoint keeps a ring per slot; so must the stub.
#[test]
fn a_piece_on_the_second_slot_is_retired_on_the_second_slot() {
    let path = format!("/tmp/kalico-multi-{}.sock", std::process::id());
    let _ = std::fs::remove_file(&path);
    let _child = KillOnDrop(
        Command::new(STUB_BIN)
            .args(["--socket", &path])
            .args(["--slave", "0", "--axis", "0", "--slave", "1", "--axis", "1"])
            .spawn()
            .expect("stub binary must spawn"),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    while !std::path::Path::new(&path).exists() {
        assert!(Instant::now() < deadline, "stub socket never appeared");
        thread::sleep(Duration::from_millis(10));
    }
    let conn = McuSerialConn::connect(&path).expect("connect");
    call(&conn, MessageKind::ClaimHandshake, Vec::new());

    let latest: Arc<Mutex<Vec<u32>>> = Arc::default();
    let sink = Arc::clone(&latest);
    conn.attach_heartbeat_callback(Arc::new(move |hb| {
        *sink.lock().expect("heartbeat lock") = hb.retired_counts.clone();
    }));

    let now = ethercat_rt::clock::monotonic_ns();
    let enable = SetTorque {
        value: 1,
        execute_at_ns: now,
    }
    .encoded_to_vec();
    let resp = call(&conn, MessageKind::SetTorque, enable);
    assert_eq!(SetTorqueResponse::decode(&resp).expect("decode").result, 0);

    let entry = PieceEntry {
        start_time: now + 50_000_000,
        duration: 0.001,
        ..PieceEntry::zeroed()
    };
    let mut bytes = Vec::new();
    entry.to_wire_bytes(&mut bytes);
    let push = PushPieces::single(1, 1, 0, 1, bytes).encoded_to_vec();
    let resp = call(&conn, MessageKind::PushPieces, push);
    assert_eq!(PushPiecesResponse::decode(&resp).expect("decode").result, 0);

    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let counts = latest.lock().expect("heartbeat lock").clone();
        if counts == [0, 1] {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "slot 1's piece was never credited to slot 1; last heartbeat {counts:?}"
        );
        thread::sleep(Duration::from_millis(10));
    }
    let _ = std::fs::remove_file(&path);
}
