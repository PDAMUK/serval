use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use host_rt::mcu_call::McuCall;
use host_rt::mcu_serial_conn::McuSerialConn;
use mcu_protocol::codec::{Decode, Encode};
use mcu_protocol::messages::{
    MessageKind, PushPieces, PushPiecesResponse, SetTorque, SetTorqueResponse, StatusHeartbeat,
};
use runtime::error::FaultCode;
use runtime::piece_ring::PieceEntry;

const STUB_BIN: &str = env!("CARGO_BIN_EXE_ethercat-rt-stub");
const MS: u64 = 1_000_000;
const PIECE_START_IN_PAST: u16 = FaultCode::PieceStartInPast.as_i32() as i16 as u16;

struct KillOnDrop(Child);

impl Drop for KillOnDrop {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

struct Stub {
    child: KillOnDrop,
    conn: McuSerialConn,
    heartbeats: Arc<Mutex<Vec<StatusHeartbeat>>>,
    socket: String,
}

impl Drop for Stub {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.socket);
    }
}

fn call(conn: &McuSerialConn, kind: MessageKind, body: Vec<u8>) -> Vec<u8> {
    conn.mcu_call(kind, body, Duration::from_secs(5))
        .expect("stub call must succeed")
        .1
}

fn stub(name: &str) -> Stub {
    let socket = format!("/tmp/kalico-{name}-{}.sock", std::process::id());
    let _ = std::fs::remove_file(&socket);
    let child = KillOnDrop(
        Command::new(STUB_BIN)
            .args(["--socket", &socket])
            .spawn()
            .expect("stub binary must spawn"),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    while !std::path::Path::new(&socket).exists() {
        assert!(Instant::now() < deadline, "stub socket never appeared");
        thread::sleep(Duration::from_millis(10));
    }
    let conn = McuSerialConn::connect(&socket).expect("connect");
    call(&conn, MessageKind::ClaimHandshake, Vec::new());
    let heartbeats: Arc<Mutex<Vec<StatusHeartbeat>>> = Arc::default();
    let sink = Arc::clone(&heartbeats);
    conn.attach_heartbeat_callback(Arc::new(move |hb| {
        sink.lock().expect("heartbeat lock").push(hb.clone());
    }));
    Stub {
        child,
        conn,
        heartbeats,
        socket,
    }
}

fn enable(stub: &Stub) {
    let enable = SetTorque {
        value: 1,
        execute_at_ns: ethercat_rt::clock::monotonic_ns(),
    }
    .encoded_to_vec();
    let resp = call(&stub.conn, MessageKind::SetTorque, enable);
    assert_eq!(SetTorqueResponse::decode(&resp).expect("decode").result, 0);
}

fn enabled_stub(name: &str) -> Stub {
    let stub = stub(name);
    enable(&stub);
    stub
}

fn push(stub: &Stub, start_ns: u64, count: u8, duration_ns: u64) {
    let mut bytes = Vec::new();
    for i in 0..u64::from(count) {
        PieceEntry {
            start_time: start_ns + i * duration_ns,
            duration: duration_ns as f32 * 1e-9,
            coeff_count: 1,
            ..PieceEntry::zeroed()
        }
        .to_wire_bytes(&mut bytes);
    }
    let msg = PushPieces::single(0, count, 0, u32::from(count), bytes).encoded_to_vec();
    let resp = call(&stub.conn, MessageKind::PushPieces, msg);
    assert_eq!(PushPiecesResponse::decode(&resp).expect("decode").result, 0);
}

fn signal(stub: &Stub, sig: &str) {
    let status = Command::new("kill")
        .args([sig, &stub.child.0.id().to_string()])
        .status()
        .expect("kill must run");
    assert!(status.success(), "kill {sig} failed");
}

fn faults(stub: &Stub) -> Vec<u16> {
    let seen = stub.heartbeats.lock().expect("heartbeat lock");
    seen.iter()
        .map(|hb| hb.fault_code)
        .filter(|&code| code != 0)
        .collect()
}

fn wait_for(stub: &Stub, what: &str, done: impl Fn(&[StatusHeartbeat]) -> bool) {
    let deadline = Instant::now() + Duration::from_secs(3);
    while !done(&stub.heartbeats.lock().expect("heartbeat lock")) {
        assert!(
            Instant::now() < deadline,
            "{what}; faults {:?}",
            faults(stub)
        );
        thread::sleep(Duration::from_millis(5));
    }
}

/// The real endpoint samples its rings once per DC cycle, and the runtime's
/// start-in-past tolerance is one `EC_DC_PERIOD_NS` plus 200 µs of drift. The
/// stub used to sample at whenever its unprivileged 1 ms sleep woke, so a
/// wake 150 µs late at a piece boundary faulted a stream that was on time —
/// the CB2 guide's homing test failed that way about one run in three. Held
/// off the CPU across a boundary, the stub must still play every DC cycle.
#[test]
fn a_stub_held_off_the_cpu_plays_the_dc_cycles_it_missed() {
    let stub = enabled_stub("dc-grid");
    let start = ethercat_rt::clock::monotonic_ns() + 30 * MS;
    push(&stub, start, 60, MS);

    thread::sleep(Duration::from_millis(50));
    signal(&stub, "-STOP");
    thread::sleep(Duration::from_millis(15));
    signal(&stub, "-CONT");

    wait_for(&stub, "the stream never finished", |seen| {
        seen.iter().any(|hb| hb.retired_counts.first() == Some(&60))
    });
    assert_eq!(faults(&stub), Vec::<u16>::new());
}

#[test]
fn a_piece_that_starts_in_the_past_still_faults() {
    let stub = enabled_stub("dc-late");
    let start = ethercat_rt::clock::monotonic_ns() - 50 * MS;
    push(&stub, start, 1, 100 * MS);

    wait_for(&stub, "a late piece was played", |seen| {
        seen.iter().any(|hb| hb.fault_code == PIECE_START_IN_PAST)
    });
}
