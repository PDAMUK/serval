import logging

import pytest

from klippy import structured_log
from klippy.extras import log_observability as lo


class CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture(autouse=True)
def _reset():
    structured_log.clear_print()
    structured_log.bind_session("k-test-1")
    yield
    structured_log.clear_session()
    structured_log.clear_print()


def test_heartbeat_emits_observability_event():
    cap = CaptureHandler()
    evlog = logging.getLogger("kalico.event")
    # In a bare test env the root logger defaults to WARNING, which would
    # filter the INFO heartbeat before it reaches the handler. klippy sets the
    # level at startup; here we lower it explicitly to observe the record.
    prev_level = evlog.level
    evlog.setLevel(logging.DEBUG)
    evlog.addHandler(cap)
    try:
        lo.emit_heartbeat()
    finally:
        evlog.removeHandler(cap)
        evlog.setLevel(prev_level)
    rec = next(
        r for r in cap.records if getattr(r, "event", None) == "heartbeat"
    )
    assert rec.subsystem == "observability"


class RecordingReactor:
    def __init__(self):
        self.timers = []

    def monotonic(self):
        return 0.0

    def register_timer(self, callback, waketime):
        self.timers.append((callback.__name__, waketime))
        return callback


class FakePrinter:
    def __init__(self, reactor):
        self.reactor = reactor
        self.handlers = {}

    def get_reactor(self):
        return self.reactor

    def get_start_args(self):
        return {}

    def register_event_handler(self, event, cb):
        self.handlers[event] = cb


class FakeConfig:
    def __init__(self, printer):
        self.printer = printer

    def get_printer(self):
        return self.printer


def test_ready_arms_only_the_heartbeat():
    """Every timer here wakes the reactor on a host that shares cores with the
    EtherCAT DC loop, so each one has to earn its place. The heartbeat does:
    it watches for the swap-out that stalls piece emission. A shipper-lag
    timer used to run beside it at 60 s forever, reading a probe hardcoded to
    return None, so it could never report anything however long it ran."""
    reactor = RecordingReactor()
    printer = FakePrinter(reactor)
    lo.LogObservability(FakeConfig(printer))
    printer.handlers["klippy:ready"]()

    assert [name for name, _ in reactor.timers] == ["_heartbeat_timer"]
    assert reactor.timers[0][1] == lo.HEARTBEAT_INTERVAL


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))


def _fake_proc(tmp_path, psi=True):
    (tmp_path / "meminfo").write_text(
        "MemTotal:        1998848 kB\n"
        "MemFree:           28672 kB\n"
        "MemAvailable:    1331200 kB\n"
        "SwapTotal:       4194304 kB\n"
        "SwapFree:        3738368 kB\n"
    )
    selfdir = tmp_path / "self"
    selfdir.mkdir()
    (selfdir / "status").write_text(
        "Name:\tklippy\nVmRSS:\t  78932 kB\nVmSwap:\t  1024 kB\n"
    )
    if psi:
        pressure = tmp_path / "pressure"
        pressure.mkdir()
        (pressure / "memory").write_text(
            "some avg10=1.50 avg60=0.80 avg300=0.20 total=1234\n"
            "full avg10=0.30 avg60=0.10 avg300=0.00 total=567\n"
        )
    return str(tmp_path)


def test_memory_snapshot_reads_fake_proc(tmp_path):
    fields = lo.host_memory_snapshot(_fake_proc(tmp_path))
    assert fields["mem_available_kb"] == 1331200
    assert fields["swap_used_kb"] == 4194304 - 3738368
    assert fields["own_rss_kb"] == 78932
    assert fields["own_swap_kb"] == 1024
    assert fields["psi_mem_some_avg10"] == 1.50
    assert fields["psi_mem_full_avg10"] == 0.30


def test_memory_snapshot_omits_missing_psi(tmp_path):
    fields = lo.host_memory_snapshot(_fake_proc(tmp_path, psi=False))
    assert "psi_mem_some_avg10" not in fields
    assert fields["mem_available_kb"] == 1331200


def test_memory_snapshot_of_absent_proc_is_empty(tmp_path):
    assert lo.host_memory_snapshot(str(tmp_path / "nope")) == {}


def test_swap_growth_detection():
    assert lo.swapped_out_since(None, {"own_swap_kb": 5}) is None
    assert lo.swapped_out_since(5, {"own_swap_kb": 5}) is None
    assert lo.swapped_out_since(5, {}) is None
    assert lo.swapped_out_since(5, {"own_swap_kb": 3}) is None
    assert lo.swapped_out_since(5, {"own_swap_kb": 40}) == 35


def test_heartbeat_carries_memory_fields():
    cap = CaptureHandler()
    evlog = logging.getLogger("kalico.event")
    prev_level = evlog.level
    evlog.setLevel(logging.DEBUG)
    evlog.addHandler(cap)
    try:
        lo.emit_heartbeat({"mem_available_kb": 12345, "own_swap_kb": 7})
    finally:
        evlog.removeHandler(cap)
        evlog.setLevel(prev_level)
    rec = next(
        r for r in cap.records if getattr(r, "event", None) == "heartbeat"
    )
    assert rec.mem_available_kb == 12345
    assert rec.own_swap_kb == 7
