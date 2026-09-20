"""Builds and runs the C PDO-map selection test.

The map used to be two fixed arrays, so the objects a drive family cannot
accept could only be removed by editing C and rebuilding. `pdo_map.h` makes the
optional groups droppable per profile, and this executes that logic against the
CI stub `ecrt.h` — no master, no libethercat, nothing linked from IgH.

The property that matters most is the first case: a profile keeping every group
must reproduce 18/32, because that is the map the A6-EC's drives are running
against and it must not move underneath them.
"""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSRC = ROOT / "rust" / "ethercat-rt" / "csrc"
STUB_INCLUDE = CSRC / "ci-igh" / "include"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    cc = shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler available")
    out = tmp_path_factory.mktemp("pdo") / "pdo_map_test"
    proc = subprocess.run(
        [
            cc,
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{STUB_INCLUDE}",
            f"-I{CSRC}",
            "-o",
            str(out),
            str(CSRC / "pdo_map_test.c"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return out


def test_the_map_selection_matches_every_expected_profile(built):
    proc = subprocess.run([str(built)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all pdo map checks passed" in proc.stdout


def test_a_profile_keeping_every_group_is_the_historic_map(built):
    """18 out / 32 in is what the fixed arrays declared before any of this was
    runtime-built, and what upstream hardcoded. An A6-EC drive is configured
    with that map today."""
    proc = subprocess.run([str(built)], capture_output=True, text=True)
    assert "ok   a6ec (all groups): rx 6/18 tx 10/32" in proc.stdout, (
        proc.stdout
    )


def test_dropping_the_optional_groups_shrinks_the_process_image(built):
    """The two optional groups are 20 of the 46 bytes a ProNet would otherwise
    exchange every cycle, for objects nothing here reads or writes."""
    proc = subprocess.run([str(built)], capture_output=True, text=True)
    assert "ok   estun-pronet (minimal): rx 4/12 tx 5/14" in proc.stdout, (
        proc.stdout
    )


def test_the_shim_builds_its_maps_from_the_shared_header():
    """libecrt_igh.c must not carry a second copy of the entry tables — that
    divergence is exactly what the header exists to prevent."""
    shim = (CSRC / "libecrt_igh.c").read_text(encoding="utf-8")
    assert '#include "pdo_map.h"' in shim
    assert "kalico_copy_entries" in shim
    assert "0x60B8, 0x00, 16" not in shim, (
        "the shim declares its own copy of the RxPDO entries again"
    )
