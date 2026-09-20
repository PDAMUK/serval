"""`ci.sh`'s tally is the result.

CLAUDE.md tells the reader not to re-run a gate to watch it pass — the one
`PASS <tally>` line is the answer. That only holds if the tally counts what
actually ran, so a gate whose tool is missing here must not land in the pass
column.
"""

import os
import pathlib
import subprocess

CI = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ci.sh"


def source():
    return CI.read_text(encoding="utf-8")


def run(*args, env=None):
    return subprocess.run(
        ["bash", str(CI), *args],
        capture_output=True,
        text=True,
        cwd=CI.parents[1],
        env=env,
    )


def test_the_script_parses():
    assert subprocess.run(["bash", "-n", str(CI)]).returncode == 0


def test_a_gate_whose_tool_is_absent_reports_skip_not_pass():
    """cargo-deny is not installed in the dev container, and before this the
    job echoed a note and returned 0 — so the tally counted a gate that had
    not run as a pass. A reader trusting the tally would believe the licence
    and advisory check had covered the tree."""
    result = run("deny")
    assert "SKIP" in result.stdout, result.stdout
    assert "PASS" not in result.stdout, result.stdout
    # Still zero, so a missing local tool does not block a developer.
    assert result.returncode == 0


def test_the_sanitizer_gate_skips_rather_than_passing():
    """fuzz-piece-sink probes whether the compiler can link the sanitizer
    runtime and stands down when it cannot. Forcing that probe to fail must
    reach the same SKIP as cargo-deny, not a green PASS for a fuzz run that
    never happened."""
    env = dict(os.environ, CC="false")
    result = run("fuzz-piece-sink", env=env)
    assert "SKIP" in result.stdout, result.stdout
    assert "PASS" not in result.stdout, result.stdout
    assert result.returncode == 0


def test_no_gate_still_claims_to_skip_while_returning_success():
    """The old shape was an echo saying "skipping locally" followed by a bare
    return 0, which the tally could not tell from real work. The phrase is
    gone; a gate that cannot run says so through SKIP_RC instead. Note ruff is
    deliberately not one of these: with ruff absent nothing was linted, so it
    fails rather than skips."""
    text = source()
    assert "skipping locally" not in text, (
        "a gate still narrates a skip in prose, which the tally reads as a pass"
    )
    assert "SKIP_RC=77" in text, "the skip sentinel is gone"


def test_the_summary_reports_skips_separately():
    text = source()
    assert "SKIP=$((SKIP + 1))" in text, "skips are not counted"
    assert "skipped" in text, "the summary never names the skip count"


def test_no_caller_inlines_docker_image_as_the_image_argument():
    """docker_image() prints the tag and returns non-zero on a failed build,
    but inside `$( )` that status cannot reach the caller's command line. The
    substitution yields an empty string, `docker run ""` runs anyway, and the
    reader gets "invalid reference format" printed after the real build error,
    with docker run's exit code standing in for the build's."""
    offenders = [
        line.strip()
        for line in source().splitlines()
        if "docker run" in line and "$(docker_image)" in line
    ]
    assert not offenders, (
        "a caller passes docker_image straight to docker run, so a failed "
        "build becomes an empty image name: %s" % offenders
    )


def test_the_build_image_does_not_pipe_the_rustup_installer_into_sh():
    """In `curl ... | sh` the pipeline's status is sh's, and sh reading empty
    stdin succeeds — so a failed download produced a layer with no cargo and
    surfaced three steps later as `cargo: not found`, against a Dockerfile
    that reads as correct."""
    dockerfile = (CI.parent / "Dockerfile-build").read_text(encoding="utf-8")
    assert "sh.rustup.rs \\\n    | sh" not in dockerfile, (
        "the rustup installer is piped into sh again; a failed download will "
        "build a cargo-less image and fail somewhere else"
    )
    assert "cargo --version" in dockerfile, (
        "nothing proves the toolchain landed in the layer that installs it"
    )
