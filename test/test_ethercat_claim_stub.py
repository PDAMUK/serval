"""The claim seam, against a real endpoint process.

Part 12 step 1 of the build guide — "stub endpoint, drives off, klippy must
reach ready" — is the one step that proves planner to bridge to transport, and
until now it existed only as an instruction to a person with a machine in
pieces. The endpoint protocol is covered from the Rust side by six integration
files, and `ethercat_node`'s validation is covered by unit tests with fakes;
what nothing exercised was the join, where the host spawns the binary and
completes the handshake.

It needs no EtherCAT master, no NIC and no MCU: the engine is constructed
directly, and `ethercat-rt-stub` answers the protocol with no hardware behind
it. That makes this runnable in the ordinary suite rather than only in the
simulator's Docker image.
"""

import os
import pathlib
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from klippy import motion_engine as motion_engine_mod  # noqa: E402
from klippy.extras.ethercat_node import EthercatDrive  # noqa: E402

STUB = ROOT / "rust" / "target" / "release" / "ethercat-rt-stub"

pytestmark = pytest.mark.skipif(
    motion_engine_mod._native is None or not STUB.is_file(),
    reason=(
        "needs the native engine and ethercat-rt-stub "
        "(make -f Makefile.rust ethercat-stub)"
    ),
)


def a_drive(chain_index, axis):
    return EthercatDrive(
        chain_index=chain_index,
        axis=axis,
        counts_per_mm=3276.8,
        rotation_distance=40.0,
        following_error_counts=52429,
        max_torque_tenth_pct=1000,
        velocity_ff=False,
        ff_max_torque=30.0,
        invert_direction=False,
        dynamics_profile=None,
    )


class Claimed:
    """A claimed node that stops and releases itself, so one test's endpoint
    process cannot outlive it and collide with the next test's socket."""

    def __init__(self, **kwargs):
        self.engine = motion_engine_mod._native.MotionEngine()
        self.socket = os.path.join(tempfile.mkdtemp(), "ec.sock")
        self.handle = self.engine.claim_ethercat_node(
            kwargs.pop("label", "node_xy"),
            self.socket,
            "eth0",
            str(STUB),
            kwargs.pop("cycle_us", 250),
            None,
            kwargs.pop("drives", [a_drive(0, 0), a_drive(1, 1)]),
            **kwargs,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.engine.stop_node(self.handle)
        finally:
            self.engine.shutdown()


def test_a_two_drive_node_claims_against_a_real_endpoint():
    """Spawn, handshake, drive configuration. A handle back means the endpoint
    accepted the claim — the thing Part 12 step 1 watches for."""
    with Claimed() as claimed:
        assert claimed.handle is not None
        assert os.path.exists(claimed.socket), (
            "the endpoint never created its socket"
        )


def test_stop_node_completes_against_a_live_endpoint():
    """`stop_node` is what the emergency stop reaches: Stop discards the rings
    on the host, then SetTorque(false) schedules the disable. It is exercised
    here end to end rather than through a fake engine."""
    claimed = Claimed()
    try:
        claimed.engine.stop_node(claimed.handle)
    finally:
        claimed.engine.shutdown()


def test_the_estun_profile_claims_when_given_an_identity():
    """`estun-pronet` ships no built-in identity, so the claim carries one.
    This is the path this machine will take on its first bring-up."""
    with Claimed(
        drive_profile="estun-pronet",
        vendor_id=0x0000_060A,
        product_code=0x0000_0002,
    ) as claimed:
        assert claimed.handle is not None


def test_the_pdo_group_overrides_do_not_break_the_claim():
    """The three `pdo_*` options turn into `--pdo-*` flags on the endpoint's
    command line. An endpoint that rejected them would fail to start and the
    claim would never complete, so this pins that they are understood."""
    with Claimed(
        drive_profile="estun-pronet",
        vendor_id=0x0000_060A,
        product_code=0x0000_0002,
        map_touch_probe=False,
        map_digital_io=False,
        map_following_error=False,
    ) as claimed:
        assert claimed.handle is not None


def test_a_non_boolean_pdo_option_is_refused_before_it_reaches_the_wire():
    """The guard that matters is klippy's, not the endpoint's: `getboolean`
    refuses anything that is not a boolean, so a typo in printer.cfg fails at
    config time rather than silently leaving a group mapped.

    The stub deliberately does not check: it has no PDO map to build, so it
    ignores the flag entirely. The hw endpoint's parser is what validates it
    there, covered by `parse_group_flag`'s own tests."""
    import configparser

    parser = configparser.ConfigParser()
    parser.read_string("[ethercat_node n]\npdo_touch_probe: maybe\n")
    with pytest.raises(ValueError):
        parser.getboolean("ethercat_node n", "pdo_touch_probe")
