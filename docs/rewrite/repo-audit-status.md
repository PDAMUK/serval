# Repository audit — status

A running record of what has been audited in this fork, what was found, and
what has not been looked at yet. The point is that the next pass does not
re-derive the same ground, and that "checked and clean" is written down as
plainly as "fixed" — an area nobody has examined and an area examined and
found sound are very different things, and only one of them is safe to skip.

Scope so far is the servo/EtherCAT bench and the seams around it. Findings
that need a drive on the bench to settle are **not** here; those live in the
"Still unverified on hardware" section of
[`estun-pronet-markforged-setup.md`](estun-pronet-markforged-setup.md).

## Fixed

| # | Finding | Commit |
| --- | --- | --- |
| 1 | `product_code` validated on neither side; a zero code is not a wildcard, so the master accepts the config, never attaches, and the run dies at the OP walk | `82b4062` |
| 2 | `estun-pronet` carried the A6-EC's whole PDO map and two following-error objects unconfirmed, failing as a bare `rc=-6` or a timeout | `82b4062` |
| 3 | The CB2 host page never built the endpoint binary klippy spawns; the Pi 5 page had that step | `82b4062` |
| 4 | The worked config set `max_torque: 300` — the motor's peak — with no unit stated, and omitted `following_error` entirely | `82b4062` |
| 5 | Flipping `MARKFORGED_Y_COUPLING` is inert until the module is rebuilt; nothing said so and nothing checked | `82b4062` |
| 6 | Pi-5 leftovers on the CB2 path (chain diagram, driver named in the zero-slaves hint) | `82b4062` |
| 7 | klippy's `_KIN_TAGS` unchecked against the planner's discriminants | `9f8759a` |
| 8 | `mcu-protocol`'s result-code test restated its literals instead of comparing them, and two cited line numbers had gone stale | `9f8759a` |
| 9 | `py-typecheck` ran in no workflow at all — which is how it spent its life red | `be1e2b0` |
| 10 | The sim unit subset ran nowhere; `pyproject` defers to a job nothing called | `be1e2b0` |
| 11 | Part 3 offered a UART build-matrix fixture as the board config; copying it flashes a board that never enumerates | `c91d63a` |
| 12 | Diag ring tags 9 and 10 resolved as `unknown`, dropping the positions and counts that explain a step-overrun fault | `c8bf0fd` |
| 13 | `RT_PHASE_*`, `DIAG_EV_*` and the transport `RUNTIME_ERR_*` codes all claimed "must match" with nothing checking | `33c3658` |
| 14 | The log-level scale was half-named, its comment pointed at the wrong crate, and `mcu_level_str` had no test | `84b385f` |
| 15 | The step-queue depth target was written down twice and rounded by two different expressions | `84b385f` |

Earlier in the same branch: `74b9e7d` (`py-typecheck` pointed at three files
that never existed), `e86ba4c` (c-api host tests could not link), `3215df9`
(the nurbs ratio tests timed their two windows back to back and misfired under
load), `7b5bf96` (the ProNet DC word settled from ESTUN's own manual).

## Checked and found sound

Not defects. Recorded so the next pass does not spend the time again.

- **`StepEntry` / `StepQueue` layout.** Pinned three ways: a `_Static_assert`
  in `src/step_queue.h`, compile-time asserts in `step_queue.rs`, and `c-smoke`
  compiling the real header against the Rust side.
- **klippy's `RUNTIME_FAULT_NAMES`** against the Rust `FaultCode` enum —
  complete and in agreement. `-317` is a return code, not an enum variant, and
  is correctly absent.
- **The Markforged matrix** matches upstream Klipper's convention
  (`x = m0 - m1`, `y = m1`), and `markforged_stepper_alloc` is a pure-Python
  projector, not a missing C symbol.
- **The Manta M8P V2.0 pin table** in the setup guide — every pin and slot
  label matches BigTreeTech's published config. Their slots start at **Motor1**,
  so counting from zero is what makes the table look wrong.
- **Shutdown** disables torque and parks through CiA 402 Ready-to-Switch-On.
- **RT capabilities** are granted as systemd ambient caps, which survive a
  rebuild where a file capability would not.
- **`docs`, `ruff` and `deny`** are covered by their own workflows despite not
  calling `ci.sh`; `rust-build` and `rust-host` are dispatch-only aliases that
  `run_all` does not include.
- **18 "broken" relative doc links** — mkdocs rewrites them to upstream GitHub
  URLs, so they are not user-facing 404s. Inherited, low value to churn.

## Not yet audited

- Dead and orphaned code: modules nothing imports, Rust items nothing calls.
- `Config_Reference*.md` against what the config reader actually accepts. A
  documented option the reader ignores is the same silent-wrongness as a
  mirrored constant that drifted.
- The planner itself — `motion-core`, the pipeline stages, snapshot coverage.
- `klippy/extras/` beyond the servo path.
- `tools/sim` beyond confirming its unit subset now runs in CI.

## Resuming on a fresh container

Everything is committed and pushed; the branch is the state. Nothing needs
carrying over but the build artifacts, which are regenerated:

```sh
scripts/build-native.sh          # klippy/_*.so — klippy will not start without them
cargo install cargo-nextest --locked   # if absent; the Rust suite needs it
./scripts/ci.sh quick            # expect 5 pass
uv run pytest test/ -q           # expect 823 passed, 5 skipped
```

Use `uv run`, not ad-hoc `pip install` — every dependency is already declared
in `pyproject.toml`.

Two environment notes, neither a repo defect:

- **Docker** gates (`py`, `sim`, `sim-e2e`) need a daemon. Without one, run the
  Python suite directly as above; `ci.sh py` will not fall back, because the
  docker binary exists and only the daemon is missing.
- **Disk.** `rust/target` reaches ~19–25 GB. A full volume shows up as
  `ld terminated with signal 7 [Bus error]` during linking, which reads like a
  toolchain fault and is not one. `rust/target/debug/incremental` is the
  largest regenerable directory to clear.
