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
| 16 | The motion config reference cited line ranges; two of seven were already wrong, `[kinematics]` parsing having moved into a gap between two of them | `c0f6c15` |
| 17 | Three more line citations in the same document's body, one of them shifted by this branch's own edits | `b53b013` |
| 18 | `fuzz-piece-sink.sh` — ASan/UBSan over the MCU piece parser — was invoked by no job, workflow or document | `1dbab70` |
| 19 | Four documented config sections have no module and fail startup, with nothing saying so | `1420542` |
| 20 | `assemble_cartesian_state`'s cartesian one-motor-missing corner was rewritten and untested | `b8365aa` |
| 21 | `_buzz_kind` defaulted a kinematics-less object to cartesian instead of failing | `b8365aa` |
| 22 | The guide never explained the endpoint failures the audit made readable | `0b875c7` |
| 23 | `Feature_Status` Known limits said cartesian and corexy long after markforged shipped | `87d8cba` |
| 24 | Six gaps a first-time builder hits: no mains-safety warning, a wrong part reference, no tuning syntax, an `endpoint:` line Part 12 needs but the config lacked, no statement of where the config goes, and a See also missing this build's own host page | `3393b4a` |
| 25 | Six more on the CB2 host page, the worst an SSH lockout warned about only after the step that causes it, plus a missing udev rule, systemd unit, NetworkManager override and MAC format | `3e6f4db` |
| 26 | The bench checklist's worked example for this machine contradicted the guide on torque and following error, and showed a drive identity klippy accepts but no drive matches | `f9660dd` |
| 27 | Part 11 declared all three axis endstops bare, with no `^` pull-up; the inputs float when a switch opens, and the guard only checked the pin *name*, which `^PF4` contains | `cbbde86` |
| 28 | Seven guide statements against the ProNet V2.19 manual: a time-delayed RCD the manual forbids, the drives' own 0-55 C / 45 C limits and their 10/50 mm spacing absent, the 300 mm power-signal separation unstated, the manual's self-contradiction on filters unflagged, control power not located relative to the filter, `A.16` missing from the fault table, and `max_torque`'s 400 not distinguished from Pn401/Pn402's 0-300% | `cbbde86` |

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
- **Every option the motion reference documents is live.** Diffed both
  directions against what the code reads. Fourteen looked dead and none are:
  post-processor parameters arrive through the `algos` REGISTRY, kinematics
  roles through computed `{axis}_motors` lookups, `drive` through
  `get_str_required`, `dynamics_profile` through a named helper — all invisible
  to a plain grep.
- **`piece-sink-harness`** depends on nothing and nothing depends on it, which
  reads as an orphan crate. It is a test harness; its 15 tests run in the
  workspace suite, and a leaf is what it should look like.
- **`klippy/parsedump.py`** is referenced nowhere but still imports and runs. A
  standalone serial-dump utility, not dead code.
- **The guide's drive facts, read back out of ProNet V2.19 end to end.** All
  confirmed and not worth re-deriving: 0.9 kVA for the `04A` (so 7.83 A for the
  pair), `24V`/`GND` scoped to `10D-70D` so the `04A` has no 24 V control input,
  60 W / 50 ohm customer-supplied on `B1`/`B2` with the `B2`-`B3` short belonging
  to the larger frames, `Pn521` 0~1 shipping at `1`, `Pn004.0 = 0` as DB-then-
  release and factory, the DB-degradation warning, `Pn006.0`'s bus types
  stopping at `[3] CANopen`, the alarm table running `A.01`-`A.69`, `A.13`'s
  30x-inertia note, the CN2 serial pins 7/8/9/19 and 17/18, `F` as incremental
  1048576 P/R against `S` as absolute 131072, U/V/W to A(1)/B(2)/C(3),
  `Pn704` as the CANopen address, the 3.5 mm^2 grounding, and every `Pn` in
  Part 13 with its unit and range.
- **`A.21` on every emergency stop has no parameter escape.** `Pn000.3` looks
  like one and is not: the factory `0` already means "one period, no alarm",
  `A.21` is defined as power off for *more* than one period, and setting it to
  `1` only makes the drive stricter. So the latch on each press stands, and the
  clearing routes are the panel `ENTER`, `/ALM-RST`, or a main-circuit power
  cycle (5.1.2). `/ALM-RST` is `CN1-39` on the base 50-pin connector, and the
  `-EC`'s `CN1` is 20-pin with 5 sequence inputs, so whether it can be allocated
  there is open. The likely answer is CiA 402 fault reset over the bus, which
  needs the EtherCAT manual nobody has yet.
- **The emergency-stop chain, traced end to end.** Button callback ->
  `invoke_shutdown` -> `klippy:shutdown` -> `ethercat_node._handle_shutdown` ->
  `engine.stop_node` -> `Stop` then `SetTorque(false, 0)`. Driving the real
  `MCU_buttons.handle_buttons_state` and the real `EmergencyStop` callback
  across all three wirings reproduces the guide's truth table exactly: `^PF1`
  halts on both a press and a broken wire; `^!PF1` and `~PF1` halt on a press
  and do nothing at all with the wire off. What the runtime does about a
  dangerous polarity is settled below, under **Known, deliberately not
  changed** — do not re-open it from this entry.
- **Line citations in `beacon-fork-survey.md` and `external-probe-homing.md`**
  (48 of the 55 in `docs/`) are historical analyses pointing at upstream files,
  not references anyone configures from. Left alone deliberately.

## Known, deliberately not changed

- **`[emergency_stop]` accepts an inverted or pulled-down pin without
  complaint.** `^!PF1` and `~PF1` both halt on a press and both do nothing at
  all with the wire off, so the wrong polarity disables the input silently and
  `QUERY_EMERGENCY_STOP` cannot tell a severed wire from an idle button. The
  module passes `config.get("pin")` straight to `register_debounce_button`, and
  the only guard in the repository reads the *guide's* example config rather
  than a user's `printer.cfg`. Refusing `!` and `~` on this section at config
  time would fit the "fail loudly" constraint, and it was proposed on those
  grounds.

  Not doing it, by the repository owner's decision: the polarity stays a
  configuration choice. The documented wiring is an NC contact to ground on
  `^PF1`, `Config_Reference.md` says so, the guide's truth table shows why, and
  `test_the_halt_input_is_wired_to_fail_safe` holds the guide to it. A machine
  wired the documented way is unaffected either way, and the guard would close
  off polarities another build may have a reason for. Recorded so the next pass
  does not re-propose it — it is a decision, not an oversight.

- **Five plot-rendering tests never run anywhere.**
  `test_servo_capture_analysis.py` guards five cases with
  `pytest.importorskip("matplotlib")`. matplotlib sits in the `prototype`
  dependency group, `tool.uv.default-groups` is unset so only `dev` installs,
  and the CI image's entrypoint is the same `uv run` — so they skip in CI
  exactly as they do locally. Run with `uv run --group prototype pytest
  test/test_servo_capture_analysis.py` all 51 pass, so the `servo_capture.py
  --png` path works; it is simply unexercised.

  Left as it is because both fixes cost more than the gap. Moving matplotlib
  into `dev` adds it plus pillow, fontTools, kiwisolver and contourpy to every
  install and to the CI image across six Python versions; adding `--group
  prototype` to `ci.sh py` makes that job resolve and download them at runtime,
  six times over. Ten scripts under `scripts/` already import matplotlib, so
  there is a reasonable case for `dev` — but that is a call about dependency
  weight for whoever owns the repo, not one to make from an audit.

## What the later rounds looked like

The code audit converged after the cross-language mirrors: sweeps started
returning one finding against several clean results. Rereading the documents as
someone *following* them rather than checking them started it again — six, six
and four across three rounds, because correctness and followability fail
differently. A page can be accurate and still strand a reader who has no
display attached, no idea where the config file lives, or a plausible-looking
drive identity that the code accepts and the bus does not.

The recurring cause was drift between documents describing one machine, and
between a path that has been walked and one that has not. Both are now tests:
`test_servo_doc_consistency.py` holds the guide and the bench checklist to the
same drive limits and refuses any identity klippy would accept, and
`test_host_docs_parity.py` requires the two host pages to cover the same eleven
steps.

## The diff against base, reviewed for regression

Base Serval runs on hardware, so the risk this branch carries is in the shared
code it rewrote under cartesian and corexy machines, not in the Markforged
code. Every behavioural change against `14f6296` was walked for equivalence:

| Changed | Verdict |
| --- | --- |
| `homing.py` per-motor endstop rule | equivalent — the predicate counts matrix rows, so multi-Z cartesian is unaffected |
| `stepper.py` | purely additive; cartesian and corexy branches untouched |
| `motion_history.rs` | equivalent; the cartesian corner was untested and now is |
| `resonance_buzz.py` masks | equivalent — corexy and cartesian pinned to the pre-rewrite bitmasks |
| `servo_axis.corexy_fit_layout` | equivalent for corexy and cartesian; also stops accepting markforged, which the old `coupled_xy()` test wrongly allowed |
| `servo_strain_comp` kin tag | equivalent; also stops tagging markforged as corexy |
| `homing_api.required_motor_axes` | equivalent for every axis of both kinematics |
| `from_doc.rs` roles | purely additive |
| EtherCAT endpoint args, FFI, `libecrt.h` | additive; the `a6ec` default resolves to the same identity, PDO map and SDOs as base, and a test pins that no identity flags are passed |

## Where this stopped

Rounds went 6, 6, 4 and the character of the fourth changed: one theme rather
than several independent gaps, and more checks confirming things were sound
than finding faults. That is the point to stop rather than manufacture another
pass. What remains unexamined is listed below and is genuinely unexamined, not
quietly skipped.

Every gate this repository has was run green at that point: the eighteen
`ci.sh` jobs a container without Docker can execute, the Python suite at 979,
nine doc tests, the piece-sink sanitizer fuzz, and all thirteen workflows
parsing. Snapshots read 51 ok / 0 changed, which is the load-bearing one: the
planner's output is byte-identical to base.

## Not yet audited

- `Config_Reference.md` — the non-motion half. Only
  `Config_Reference_Motion.md` has been checked.
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
