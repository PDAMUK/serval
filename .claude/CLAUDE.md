# Non-negotiable constraints

- The goal of this repository is to expand the boundaries of ultra fast printing at good quality.

- Fail loudly. When adding checks for unexpected things to the code, instead of trying
  to recover, unless it was discussed and agreed on explicitly, the default solution is
  to fail loudly with a clear error code. This helps us catch bugs quicker. Example: movement segment arrives to the planner late, causing the start time to be in the past. Do not advance or pad the
  start time, raise an error instead. this way we notice the issue and have a chance to address it

- Comments are a failure of expression. Instead of writing one, make the code say it:
  rename, extract, assert, or compute the value. If you need a comment it means you need to make the code better. 
  TODO-style markers are fine. If you notice some useless pre-existing comments in the file you are editing - remove them.

- Unit tests live in a separate file from the tested code.

# Testing

Run the Rust suite with `cargo nextest run` from `rust/`, not `cargo test`.
`cargo test` executes the ~110 test binaries one at a time (each only
parallelizes internally), which leaves most cores idle — the full suite takes
~100s. `nextest` schedules every test into one global pool: same suite, ~11s.
Use `cargo nextest run -p <crate>` or `-E 'test(<name>)'` to scope down.
Doc-tests are the one gap — `nextest` skips them, so run `cargo test --doc`
when you touch doc examples.

Test output is quiet by design: `ci.sh <job>` prints one `PASS <tally>` line
off a terminal, and dumps the last 100 lines of the log when the job fails;
nextest prints failures and slow tests only. Never re-run a gate verbosely to
"see" a green result — the tally line is the result.

When you do need the detail, the complete log of every job is already on disk
at `.ci-logs/<job>.log` — read or grep that instead of re-running. `ci.sh -v
<job>` streams live if you really want it in the transcript. For a simulator
post-mortem, `tools/sim/run.sh test --keep-logs` (also via `ci.sh sim-e2e
--keep-logs`) leaves each world's `klippy.log`, MCU logs, `printer.cfg` and
`events/*.jsonl` under `.sim-logs/run/<test>/world0/`; without it the `--rm`
container deletes them.

# Before opening or updating a PR

Run `./scripts/ci.sh quick` and get it fully green — it bundles ruff
(check + format) over the whole repo, the Rust workspace tests, clippy
with `-D warnings`, `cargo fmt --check`, and the watchdog canary. This is
the same set CI runs first, so a red gate here is a red PR. `quick` does
NOT include the Python host tests — if the change touches `klippy/`, also
run `./scripts/ci.sh py`. Individual jobs: `./scripts/ci.sh <job>` (see
the header of `scripts/ci.sh` for the full list, e.g. `ruff`,
`rust-clippy`, `rust-mcu-h7`).

# Observability / structured logging

Log via the structured pipeline (`event_log_emit` → `events/*.jsonl`), not
`printf`/`output()` — it replaces `klippy.log` for MCU/structured diagnostics;
the wire-stable event table is `rust/runtime/src/log_codes.rs`. To read or add
logs — `DIAG_DUMP`, crash forensics, filtering — use the `mcu-diagnostics`
and `query-logs` skills.

# Reference docs

- **MCU C/Rust boundary — architectural invariant:** [`docs/rewrite/mcu-c-rust-boundary.md`](docs/rewrite/mcu-c-rust-boundary.md). Read this before adding shared state between C and Rust on the MCU, or before reaching for `#[link_section]` on a Rust static. Rules: C owns boot, safety-critical paths, and all shared-memory placement; Rust owns the motion engine; the seam is `extern "C"` + `#[repr(C)]` only.

- **Repository audit status:** [`docs/rewrite/repo-audit-status.md`](docs/rewrite/repo-audit-status.md). What has been audited, what was found, and — as usefully — what was checked and found sound, so a later pass does not re-derive the same ground. Read it before starting an audit or a broad cleanup.

- **Motion planner entry point:** `setup_pipeline` in `rust/motion-core/src/worker.rs` wires the streaming stages (fitter → planner → lowerer → shaper); the pipe's front door (ingress guard, pacing, control tokens) is `rust/motion-core/src/worker/ingress.rs` — read those first when exploring the planner.

# Git

Never rewrite git history, never amend commits, never force-push.

**Push only to `PDAMUK/serval`. Never interact with the upstream
`KalicoCrew/kalico` in any way — not a fetch, not a read, not a PR.** This is
absolute. Public vendor repositories (`bigtreetech/manta-m8p` and similar) and
general web research are fine and have been used freely.

Work lands on `claude/ethercat-support-ke49we`.

# If you are picking this up with fresh eyes

Read this section, then `docs/rewrite/repo-audit-status.md`, then stop and ask
before starting anything broad. What follows is the state of play, not a task
list.

**What the branch is.** EtherCAT servo support for a Markforged-kinematics
printer: 2x ESTUN ProNet-04AEG-EC drives on X/Y, steppers on Z and a tandem
extruder, BTT Manta M8P V2 mainboard. The build document is
`docs/rewrite/estun-pronet-markforged-setup.md` and it is the primary
deliverable — it is written to be *followed*, by one person, with a machine in
pieces in front of them.

**How the auditing has been done, because it works.** The instruction has been
"find three issues, then look for a fourth, a fifth, and so on" — never stop
because the count feels sufficient. Every finding gets a fix, a test that fails
without the fix, and a mutation check proving the test bites. Findings that
turn out not to be bugs get recorded as checked-and-sound in the audit
document, because disproving a hypothesis is most of the work and nobody should
pay for it twice.

**Two habits that have repeatedly mattered.** First, verify against primary
sources — the ProNet manual, the C source, the distributor listing — not
against what an earlier pass concluded. Several defects were only reachable
because a previous pass had recorded a wrong conclusion, and the wrong
conclusion hid the bug. Second, when a fix goes in, check the *description* of
what the code does as carefully as the code: the last several passes found more
errors in prose about behaviour than in behaviour.

**Open threads, in rough priority order.**

- The emergency stop is `Stop Category 0` with dynamic braking, not Category 1.
  That is a deliberate and defensible choice for this machine, but the build
  document does not yet say so in those terms, and it should.
- Every stop press removes main power for longer than one AC period, so the
  drives latch `A.21` and/or `A.14` and need an alarm clear before the machine
  runs again. Not documented, and it is friction on every single press.
- `docs/rewrite/repo-audit-status.md` lists what has never been audited: the
  planner itself (`motion-core`, the pipeline stages), `klippy/extras/` beyond
  the servo path, and `tools/sim` beyond its unit subset.
- `stop_node` is the only endpoint round-trip that blocks the reactor rather
  than using the `_start`/`endpoint_call_done` split, against a comment in
  `klippy/motion_engine.py` naming that as the cause of "Timer too close".
  Recorded, deliberately not changed.

**Hardware facts worth not re-deriving.** These drives have **no STO** — no
safety function of any kind appears in the ProNet manual. The `04A` frame has
**no 24 V control input**; `24V`/`GND` belongs to the 400 V `10D`-`70D` class,
and our control power is `L1C`/`L2C` at 230 VAC. On servo-off the drive offers
dynamic brake or coast only (`Pn004.0`), never a controlled ramp.

# Snapshots

Baseline files define how it is in the base branch. It doesn't mean baseline represents correct behavior. Snapshot tests exist so user can compare before/after to see what exactly changed in the motion planner behavior. New baseline is always generated by the user.
