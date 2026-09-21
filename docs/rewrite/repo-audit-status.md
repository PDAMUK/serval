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
| 29 | `log_observability` armed a 60 s timer whose probe was a hardcoded `return None`, so it rescheduled forever and could never report anything; three tests covered the predicate it never called | `e129640` |
| 30 | `ci.sh` tallied gates whose tool was absent as passes, so a run claiming 20 passes had run 18 | `3a7df85` |
| 31 | `docker_image()`'s failure is invisible inside `$( )`, so a failed build became `docker run ""` — the real error buried under "invalid reference format", carrying docker run's exit code | `3a7df85` |
| 32 | `Dockerfile-build` piped the rustup installer into `sh`, where a failed download still exits 0 — a cargo-less image failing three layers later as `cargo: not found` | `3a7df85` |
| 33 | `MCU_bus_digital_out` reused the protocol lookup's `%c` format under Python's `%`, emitting `oid=\x05 value=\x01` where every sibling and `mcu_pins.py` write `%d` | `bfc9235` |
| 34 | The PDO map was two fixed arrays, so an object a drive family cannot accept could only be dropped by editing C and rebuilding — the worst shape for a failure that arrives as a bare `rc=-6` at first contact. Two of its groups were also dead on every profile: `tx.touch_probe` and `tx.phys_outputs` are written to the wire every cycle and assigned nowhere, and `60B9h`/`60BAh`/`60BCh`/`60FDh` are registered with not one `EC_READ` between them — 20 of 50 bytes per drive per cycle, at 4 kHz, for objects nothing consumes | `bc220d3` |
| 35 | Part 12 step 1 — stub endpoint, drives off, klippy must reach ready — was the one bring-up step no test stood behind. Both sides of that seam were covered (six Rust integration files spawn the stub, `ethercat_node`'s validation has unit tests with fakes) and the join where klippy spawns the binary and completes the claim had nothing | `8d2f1e6`, `c9421b5` |
| 36 | `ethercat-bench-bringup.md` described `SERVO_CAPTURE_START` (which ships here) and `SERVO_FIT_DYNAMICS` (a serval-dashboard macro) under one heading, so a reader typing the second gets "Unknown command" and goes hunting a build failure that is really a missing install | `929a4a2` |
| 37 | Both build documents specified a **latching, key-release** stop button (RS 139-972) in their bill of materials and then said "Nothing latches", describing release as twisting it back. The button latches and takes a key; the coil circuit is the half that does not. Stated the wrong way round it throws away the one real interlock the part buys — key out and nobody restores main power — while a reader could still take the key for isolation it does not give | `e933ab9` |
| 38 | The 300 mm cable-separation rule named categories — "power and signal" — and not cables. On a machine smaller than the separation that is unactionable: the reader has to identify the runs themselves. The source guide named three victims and one aggressor in one sentence and omitted the regenerative-resistor leads, the bed heater and the encoder and EtherCAT runs entirely; the collated guide had dropped even that. Neither said that a motor's power and encoder cables share a drive, a motor and a drag chain — the one pairing no distance can fix | `a4ec4a0` |
| 39 | Neither build document said that `SERVO_PARAM` and `params:` write drive **RAM**, never EEPROM. A console `SET` is therefore gone on the next restart while a `params:` entry is re-pushed every claim — so an evening's tuning at the console evaporates on a power cycle, with no documented way to persist deliberately (CiA 301 `0x1010`). The bench checklist had it; both guides dropped it, and the setup guide's "for values that must survive a restart" hid the failure. Three smaller drops with it: a rejected `params:` write **fails the claim**, objects wider than 4 bytes fail loudly, and SDO traffic is non-deterministic mailbox traffic | `f3641e1` |
| 40 | `ethercat-bench-bringup.md` cited `RUST_LOG`'s `EnvFilter` at `rust/motion-engine/src/logging/mod.rs`. The module lives in `motion-services` — it moved crates and the citation did not | `39a8168` |
| 41 | The same page attributed `CONFIG_MCU_SIM` to `tools/sim_klippy`, which exists nowhere in the tree and is referenced from nowhere else. The live MACH_LINUX configs carrying it are `tools/sim/configs/` | `39a8168` |
| 42 | `.claude/CLAUDE.md`'s two reference-doc links were written relative to the repository root rather than to the file holding them, so they resolve to `.claude/docs/rewrite/...` and 404 when clicked | `39a8168` |
| 43 | `Config_Reference_Motion.md` named `SERVO_FIT_DYNAMICS` as though this repository registered it — the third document with finding 36's defect | `39a8168` |
| 44 | The `[emergency_stop]` polarity guard was declined on the strength of the documentation, and `Config_Reference.md` — the document someone has open while writing `printer.cfg` — said to wire NC with a pull-up but never said not to invert the pin. `^!pin` and `~pin` still halt on a press, so the mistake looks like it works, and assert nothing with the wire off | `e66b989` |
| 45 | `ethercat-bench-bringup.md`'s headline sample config used `[servo_x]`, which the reader refuses outright, and split its options between motor and axis wrongly besides. The first config on the page, and it could not load | `3b4e6ae` |
| 46 | The same page's Markforged worked example named three axes in `[kinematics]` and defined none of them, and declared `z_motors: motor_z` with no `[motor motor_z]` | `3b4e6ae` |
| 47 | The collated CB2 guide had no counterpart to the host page's "confirm the bus before trusting it": its only cold-boot instruction sat in the closing done-criteria, three hundred lines past the point where a reader decides whether to carry on | `1dd5bf0` |
| 48 | The CB2 host page put `MASTER0_DEVICE` in `/etc/ethercat.conf` and started the master from `/etc/init.d/ethercat`, while building with `--prefix=/opt/etherlab` and using the prefixed path in its own `ExecStop`. Neither unprefixed path exists for this build, so the settings are silently never read and the master comes up with no link — indistinguishable from the wrong MAC its own troubleshooting table sends you to | `b7904e1` |
| 49 | The CB2 page never checked the built module's vermagic against the running kernel, where the Pi 5 page does — backwards, since the CB2 has you build the kernel yourself and a wrong `--with-linux-dir` surfaces only as `modprobe` refusing the module | `1d5aad7` |
| 50 | The Pi 5 host page told the reader to "pick any core and pass `--rt-cpu` to match". Nothing can pass it: klippy spawns the endpoint and `bridge/ethercat_endpoint.rs` never emits the flag, so the core is fixed at CPU 3. Following the advice is worse than being stuck — `sched_setaffinity(3)` succeeds for any online CPU, so the loop pins to a *non-isolated* core while `chrt -p` and `Cpus_allowed_list` both read exactly as the verification says they should. Every documented check passes and the machine drops frames on the first cold boot. The two CB2 pages had the right core and never said why it had to be that one; the bench checklist named both `--rt-cpu` and `--rt-prio` as knobs | `549b5c2` |
| 51 | Both guides warn that EtherCAT is direction-sensitive, then verified the chain with "the green `LINK/ACT` LED lights on each connected RJ45". The link is negotiated below EtherCAT, so a `CN4`-to-`CN4` link lights both LEDs identically — the check passes in the failure case it sits under. Direction is only proven where `ethercat slaves` counts the slaves, and neither page said so | `2c22d25` |
| 52 | Both guides spend a paragraph on the `^` pull-up — finding 27's defect — and then verified the wiring with "`QUERY_ENDSTOPS` reports all three switches changing state when pressed", which passes with or without it: closing to ground pulls the pin firmly low either way, and what a missing prefix breaks is the *released* state. The check sat directly under the defect it cannot see | `b616305` |
| 53 | Neither CB2 document listed a single package to install. A minimal Armbian image carries none of what the steps need, and the path fails at four separate points: `./bootstrap` with no autotools, `make modules` with no kernel headers, the Rust build inside the `serialport` crate for want of `libudev-dev` — which surfaces as a Rust compile error and reads as a toolchain problem — and the firmware at `arm-none-eabi-gcc: No such file or directory` | `c737643` |
| 54 | `build.rs` let the missing IgH master fail inside cc-rs. The headline was `error occurred in cc-rs: command did not execute successfully`, with `fatal error: ecrt.h: No such file or directory` demoted to a cargo warning above it. It now checks for the header before invoking cc and names the file, the document that installs the master, `IGH_DIR` for another prefix, and the stub build that needs no master | `c737643` |
| 55 | `IGH_DIR` and `IGH_LIB_DIR` are read by `build.rs` and documented nowhere, so a master installed outside `/opt/etherlab` had no documented route | `c737643` |
| 56 | Neither CB2 document ever got the repository onto the host. The IgH step runs `generate.py` out of `tools/`, the endpoint step builds in `rust/`, and the RT step writes a drop-in for a `klipper.service` that nothing created — so a reader following either page from a flashed image stops dead at the IgH build with no checkout and no klippy | `013e668` |
| 57 | The same missing step had to name **this fork**: `Quickstart.md` points at `dderg/kalico`, which carries no markforged kinematics, no `estun-pronet` profile, no `[emergency_stop]` and none of the `pdo_*` options, so following it verbatim produces a checkout that rejects the Stage K config outright | `013e668` |
| 58 | The prerequisites of finding 53 were placed *before* the step that erases them — the kernel step builds an Armbian image elsewhere and flashing it replaces the whole OS, so the Wi-Fi move and the package install were work done twice. Introduced by finding 53's own fix. Stage B is reordered kernel-first; on the host page the `eth0` move was an unnumbered preamble rather than a step, which is what let it drift there unnoticed | `013e668` |
| 59 | The motion budget took the motor's rated torque as the ceiling and had no belt term at all. On this machine's own belt — standard 2GT, 6 mm, 20 T — the belt carries 26.2 N, which is `0.167 N·m` at that pulley against the servo's `1.27`, so the tool overstated acceleration sevenfold and named the wrong part every time. Introduced by the tool's own first commit; the belt is now modelled from SDP/SI Table 3 and the ceiling is the lower of the two, with the limiting part named | `ca011f6` |
| 60 | The same page fetched a webfont from Google on open. It is a file read from a checkout on a workshop machine that may have no route off itself, nothing this branch produces is supposed to phone anywhere, and every `font-family` in it already falls back. The request bought a blocked load and a reflow for nothing | `ca011f6` |
| 61 | The motion budget's copyable `printer.cfg` block formatted its numbers for a reader: `max_velocity: 1,000` and `max_accel: 2,211`, which klippy's reader hands back with the separator still in them. Worse in a comma-decimal locale, where `toLocaleString` prints `2.211` — which parses cleanly and is a thousand times too small, so the machine crawls and nothing looks wrong. Config values now go through `cfgnum`, and the drift test runs the page's own `cfgText` with `toLocaleString` monkeypatched to throw | `ca011f6` |
| 62 | The same page's caution against a raised torque limit was gated on `m.limiter === "motor"` — so it was silent in the one case that can break something. When the belt is the limit, raising `max_torque` moves no number on the page (the ceiling is the belt's) while letting the drive pull 598 N through a belt rated for 26 N, and the reader who sees nothing change concludes it was harmless. The caution now fires above 100 % either way, says 300 % is the motor's burst rating rather than something it holds, and the `max_torque` line it writes into the config carries that in a comment | `ca011f6` |

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
- **The host's periodic work, swept for anything the CB2 need not run.** After
  finding 29 the rest is earned: `webhooks` unregisters its query timer when
  the last subscription drops, the non-critical-MCU reconnect timer only arms
  when `is_non_critical` is set, TMC driver checks are start/stop-gated, and
  `structured_log.event` goes through `queuelogger`'s background thread so
  event writes never touch the reactor. `support_bundle` holds a lock at init
  and starts its threads only inside its command. Of the seven modules klippy
  loads unconditionally, only `telemetry` is worth a config line: it is
  upstream Kalico's opt-in analytics and prompts at every ready, so set
  `enabled: False` rather than leave it asking.
- **The per-axis step budget is guarded on both sides; the aggregate is a
  deliberate margin.** `src/stepper.c` gives each axis half a sample window
  and says in the same breath that the ISR is shared across axes, so three
  busy axes can in principle ask for more than one window. That is the 0.5
  factor's job. Both ends do enforce the per-axis half: the host clamps
  planned velocity through `motor_velocity_ceiling`, and `dispatch_stepper`
  raises `steps_per_sample_exceeded` with fault context rather than dropping
  steps. Worth knowing for the tandem extruder, whose two motors step from one
  trajectory and so draw their budgets together.
- **Post-processor parameters cannot reach a divide by zero.** Every
  `ParamSpec` carries a `Bound`; `frequency_hz` is `Positive`, `damping_ratio`
  is `UnitInterval`, and `check` rejects non-finite values before compile. The
  `omega` divisions in `mode_inverse` are safe by that construction.
- **`endstop_pin` tells the keyed form from a plain pin by a newline, not a
  colon**, so a remote-MCU pin like `toolboard:PB1` parses as the single pin it
  is. The keyed form is inherently multi-line.
- **`[extruder] axis:` is validated**, not merely accepted: the named axis must
  exist and must declare `follows:`. `build_follower_steppers` really does walk
  every motor of every follower, which is what makes the tandem pair one
  trajectory rather than two.
- **The markforged coupling mirror is runtime-guarded.** `motion_kinematics`
  compares its constant against the value the compiled module reports and
  fails loudly on a mismatch or a module too old to answer — so finding 5's
  rebuild trap cannot come back silently.
- **The stub endpoint is well covered.** Six Rust integration files spawn the
  real binary: `torque_lifecycle`, `sensorless_homing`, `endpoint_supervision`,
  `stub_lifecycle`, `sdo_lifecycle`, `capture_lifecycle`. A grep that excludes
  `*.rs` suggests otherwise and is wrong.
- **Snapshots carry no markforged case on purpose.** The planner is
  kinematics-agnostic — snapshots pin the trajectory in axis space, and the
  markforged matrix is pinned separately. Its absence there is not a gap.
- **The PDO byte accounting is right for both profiles.** `rx_entries` sums to
  18 (`OUT_BYTES`), the first nine `tx_entries` to 28 (`IN_BYTES_BASE`), and
  adding `60F4h` gives the 32 that upstream hardcoded. `60F4h` really is last
  in the array, so the short map is a prefix of the long one as its comment
  claims, and a profile that drops it maps a contiguous run.
- **Homing's drive-limit swap cannot start a move with limits half applied.**
  `_servo_drive_limits` is a context manager: a failing `set_drive_limits`
  raises before the `with` body, so homing never runs; an exception inside
  attempts a restore, logs if that also fails, and re-raises the original. The
  one residue is that a swap failing partway leaves the earlier drives on
  homing limits, which are the *tighter* pair — 50% torque and a smaller
  following-error window — so the machine is left safer rather than looser, and
  the next successful swap or a drive power cycle clears it.
- **Lint sweeps, and what they are worth here.** ruff's bug-focused rules over
  `klippy/` (`B`, `PLE`, `RUF`, `C4`) found finding 33 and nothing else — 161
  hits, 158 of them style, one real, two false positives (`%d` with a bool is
  valid). Clippy at `pedantic` over `ethercat-rt`, `motion-engine` and
  `motion-core` is dominated by 510 `cast_possible_truncation`, which is too
  coarse to triage and is knowingly outside the gate's enabled set. Of the ten
  `float_cmp` sites, eight are tests and the two that are not —
  `geometry/src/velocity/disk.rs` and `motion-pipeline/src/shaper.rs` — are
  byte-identical to upstream, so they are upstream's planner internals. Left
  alone deliberately: changing them would move motion output and oblige the
  owner to regenerate snapshot baselines.
- **Line citations in `beacon-fork-survey.md` and `external-probe-homing.md`**
  (48 of the 55 in `docs/`) are historical analyses pointing at upstream files,
  not references anyone configures from. Left alone deliberately.
- **The collated CB2 build guide was verified against the code, not against
  its sources.** `markforged-cb2-complete-build.md` gathers the build document,
  the CB2 host page and the bench checklist into one sequence, and
  `test_cb2_build_guide.py` holds it there: its worked config parses through
  the same native reader klippy uses and yields markforged with two servo lanes
  and a two-motor follower; every `[section]` it sets resolves to a module;
  every `rc=` it explains is a real `EC_RT_ERR_*`; every make target, file path
  and `pdo_*` option it names exists; every endstop carries its `^`; the
  torque ceiling still tells the config field's 400 from the drive's 300; the
  disable hold is still `0x0006` for 100 cycles; and the anchors are slugged
  the way `ci.sh docs` slugs them, so a stale cross-reference fails here before
  it fails the build. That sweep produced finding 36 and nothing else — every
  other claim checked out, including all 21 Manta pins against BigTreeTech's
  own configuration and the whole mains chain against ProNet V2.19.
- **What this branch actually is, counted rather than estimated.** Against
  `dderg/serval` at `14f6296`: 1876 tracked files here, 76 of which differ from
  upstream's copy of the same path, and 25 that upstream does not have at all.
  Of the 76, 48 are code — 11 under `klippy/`, 37 under `rust/` — and the rest
  are documents, scripts and CI. All 48 have now been read. That is the honest
  boundary of this audit: what is left is upstream's code running on upstream's
  hardware, which is a different job (see **Not yet audited**).
- **The seven `runtime/` files never opened by name during the sweeps.**
  `fault_helpers.rs`, `dispatch_stepper.rs`, `log_codes.rs`, `segment.rs`,
  `mcu_log.rs`, `lib.rs` and `build.rs` read as a hole in the coverage and are
  not one: what this branch changed in them is findings 12, 14 and 15 — fixed,
  tested, and listed above — plus additive markforged wiring. Nothing in them is
  both branch-specific and unexamined.
- **All twelve of this fork's markdown files, swept mechanically and by
  hand.** 105 markdown files, 93 byte-identical to upstream and out of scope.
  The other twelve now have `test_doc_references.py` over them: relative links,
  anchors including cross-file ones, repo paths, make targets and `ci.sh` jobs,
  with two documented allowlists — the five `../config/*.cfg` links mkdocs
  rewrites to upstream GitHub, and the paths a document names precisely to say
  they are *not* here. `test_doc_config_examples.py` parses every whole-machine
  config example through the reader klippy uses. Checked and sound in the same
  sweep: no rejected section name survives in any ini fence; every
  `[ethercat_node]` key in every fragment is one the module reads; every
  documented script invocation and flag exists; every stated default matches the
  code (`homing_following_error` 2.5, `homing_max_torque` 50,
  `homing_retract_dist` 5.0 from `rail.py`, retract speed defaulting to
  `homing_speed`, RT priority 80); and `tools/ethercat-dwmac-rk/README.md`'s
  6.1/6.4/6.12 claim holds, because `kv` is parameterised throughout
  `generate.py`.

  One exemption is deliberate and documented in the test: **this document is
  not held to the path check**. An audit log's job is to record what was
  wrong, so a path it names may be exactly the path that did not exist —
  findings 40 and 41 are two of them, and holding it to the check would mean
  it could never describe a dead reference.
- **Every documented knob has a path to the code that reads it, bar the three
  now named as unreachable.** Of the endpoint's 25 CLI flags the bridge emits
  22; the three it does not are `--rt-cpu`, `--rt-prio` (finding 50) and
  `--mailbox-cpu`, which no document mentions and nothing tells a reader to
  set. In the other direction, every `[motor]` servo option `servo_axis.py`
  reads is documented in at least one servo document — checked by extracting
  the reads and searching all six.
- **The collated guide's electrical bill is faithful to the source's.** All 13
  RS stock codes it quotes appear in the source guide and none is invented;
  both rail budgets sum to the six modules they declare. The arithmetic tests
  that guard the source bill did not look at the collation — that is now
  closed rather than left to drift.
- **This document's own integrity.** 39 findings at the time of the check, no
  gaps, no duplicates, in order, and all 28 commits it cites resolve in this
  repository. The one hash that does not is `14f6296`, which is upstream's head
  and correctly absent.
- **The vendored MCU SDKs upstream carries and this fork does not.** All 1115
  files present upstream and absent here are under `lib/`: `pico-sdk`, the
  SAM/SAMD/SAME families, `hc32f460`. Not damage, and not this branch's doing —
  no commit in the history this checkout carries touches `lib/`. What remains is
  `stm32f1`, `stm32f4`, `stm32g0` and `stm32h7`, exactly the set `ci.sh`'s four
  `rust-mcu-*` jobs build, and `stm32h7` is the one this machine needs: the
  Manta M8P V2 is an STM32H723. Worth knowing before anyone plans an RP2040 or
  SAMD toolboard on this fork — `lib/rp2040_flash` is still here, the SDK it
  flashes is not.

### Every verification step in the two build guides, evaluated

Findings 51 and 52 came from one question asked of each in turn: *would this
check pass if the thing it verifies were broken?* Twelve steps, two that
failed it — the chain LED, which lights identically on a reversed link, and
`QUERY_ENDSTOPS`, which swings the same way with or without the pull-up. The
other ten discriminate, and are recorded here so the question is not asked of
them again: the three kernel checks (which name the `PREEMPT` vs `PREEMPT_RT`
trap), the isolated-core read, the module vermagic (added by finding 49), the
master/`/dev/EtherCAT0`/`ip link` trio, the encoder check (`A.10`/`A.22` plus a
smooth position display), the mains sequence — especially step 6, where `POWER`
staying lit while `CHARGE` drops is what proves control power is on the correct
side of the contactor — `ethercat slaves` counting two in wired order, klippy
parsing the config, and the coupling-sign test.

### Followability, checked by walking the guide rather than reading it

Findings 56-58 came from one question asked of each stage in turn: *what does
this need that an earlier stage was supposed to provide?* It is a different
question from "is this true", and it found what four rounds of truth-checking
had not — a guide every statement of which was correct, and which could not be
followed from a flashed image because nothing ever cloned the repository.

`test_host_step_order.py` now holds both CB2 documents to the shape: steps
numbered in the order they appear with no gap or repeat, the kernel step first
with the `eth0` and package steps after it, a repository step before anything
that builds inside one, this fork named with the reason base Serval will not
do, and no reference to a step that does not exist.

### Readiness for the bench, checked by building rather than by reading

Asked directly whether the repository is ready for hardware, so each thing a
bench needs was built rather than asserted:

- **`scripts/build-native.sh`** produces all three klippy modules.
- **`ethercat-stub`** builds, and `test_ethercat_claim_stub.py` completes a
  real handshake against it — the planner-to-bridge-to-transport path Part 12
  step 1 proves.
- **`ethercat-endpoint-hw`** cannot build without IgH, which is correct and is
  finding 54's subject.
- **The Manta firmware does not build here** for want of `arm-none-eabi-gcc`.
  The guide's four menuconfig settings do produce the intended `.config`
  (`MACH_STM32H723`, `FLASH_START_20000`, `CLOCK_REF_25M`, `USBSERIAL` on
  `PA11_PA12`), and the Rust half compiles for `thumbv7em-none-eabi`.
- **No gate covers the C firmware.** `ci.sh rust-mcu-h7` builds `c-api` for
  `thumbv7em-none-eabi` and stops; no CI image carries an ARM toolchain, so
  nothing compiles the firmware or links `out/klipper.bin`. A green gate does
  not mean the firmware builds, and both CB2 documents now say so.

## Known, deliberately not changed

- **`set_clock_est_rebased` mixes an injectable clock with a real one, and
  that makes one of its tests flaky.** `router.rs` reads
  `instant_to_f64(self.clock.now())` — the injectable `Clock`, a `MockClock`
  under test — and `crate::clock::monotonic_raw_secs()`, which is the real
  monotonic raw clock and is not injectable, then takes their difference.
  Any test comparing two calls therefore also measures the real time that
  elapsed between them. `set_clock_est_rebased_epsilon_independent` asserts a
  2-tick tolerance at 1 MHz and was seen failing at 4 ticks under load; it
  passes 8/8 in isolation.

  The property it names is not the one at risk: `host_now_raw` is bound as
  `_host_now_raw` and never read, so epsilon-independence holds by
  construction and every failure is measurement noise. Two separately
  constructed `MockClock`s partially cancel the skew, because each seeds from
  `Instant::now()` at its own construction — which is why the test usually
  passes, and why *sharing* one clock between the two routers makes it
  strictly worse rather than better. That was tried during this pass and
  reverted: the mutation check disproved the hypothesis it was built on.

  Not fixed here because the only real fix is to make the raw clock
  injectable alongside `Clock`, which is a production change to clocksync
  rather than a test repair, and widening the tolerance would hide the one
  signal the test still carries. Flagged for whoever owns that seam. Do not
  "fix" it by putting both routers on one clock.

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

### Re-checked against upstream directly, not from this table

The table above was written from the branch side. A later pass cloned
`dderg/serval` and diffed against it: upstream `main` is `14f6296`, so the base
named here *is* upstream, and every row could be verified rather than trusted.
All of them hold. What the diff adds:

- **Only 37 files under `rust/` differ at all**, most of them tests.
  `motion-core` is byte-identical to upstream apart from `kinematics.rs` and
  `motion_history.rs`, and **`bridge/servo.rs` — the host-to-endpoint servo
  seam — is byte-identical**. The planner, fitter, lowerer, shaper, ingress and
  pump are upstream's, which the snapshot gate independently confirms at
  51 ok / 0 changed.
- **`resonance_buzz`, `homing.py` and `homing_api` were verified by computing
  their predicates for every (kinematics, axis) pair** rather than by reading:
  identical to upstream across cartesian and corexy on all three axes, in all
  three files. Markforged is new ground with no upstream counterpart — upstream
  carries no markforged at all.
- **`motion_history.rs`'s `AT_REST` substitution is safe by construction**: a
  lane `lanes_feeding_axis` marks false has weight `0.0` in that same
  `motor_to_axis` row, so the stand-in cannot reach the reconstructed axis.
  Cartesian's one-motor-missing corner behaves as upstream did.
- **The `a6ec` bring-up SDOs survive exactly.** `0x6060=8` and `0x6066=0` are
  still written unconditionally, then `a6ec_cfg_sdos` supplies
  `0x2001:14=5, :15=0, :17=5, :18=0` — upstream's six writes, same order, same
  values, alongside the same identity, DC word, `60F4h` mapping and `6072h`
  limit. The `#define`s became a table; the numbers did not move. The branch
  additionally checks the SDO calls' return values, which upstream ignored.

**One correction to this table's reasoning, not its verdicts.** The
`servo_axis.corexy_fit_layout` row says the old `coupled_xy()` test "wrongly
allowed markforged". Upstream's `coupled_xy()` is literally
`return self.kind == "corexy"`, so it would have rejected markforged too. What
happened is the reverse: *this branch* widened `coupled_xy()` to mean "x and y
share lanes", which would newly admit markforged, and the call site was pinned
to `kind != "corexy"` to hold upstream's behaviour. Right change, wrong reason
recorded.

**Three deliberate behavioural differences from upstream**, all toward safety,
all in the emergency-stop path — worth knowing before anyone calls this branch
"upstream plus markforged":

| Where | Upstream | Here |
| --- | --- | --- |
| `torque.rs` | a disable while one is pending is rejected, and `handle_set_torque` answers a reject by exiting the endpoint | takes the earlier of the two times, so a stop can always bring a disable forward |
| `endpoint/commands.rs` | `ResumeStream` always honoured | refused while torque is parked or a disable is pending, closing the homing-thread race |
| `ethercat_node.py` | a `stop_node` exception propagates out of the shutdown handler | logged loudly and swallowed, so the remaining `klippy:shutdown` handlers still run |
| `endpoint/cycle.rs` | torque-gate fault reported to the host as code `0` | reports the real truncated code (`0xFEC7`) and logs it |

## Where this stopped

Rounds went 6, 6, 4 and the character of the fourth changed: one theme rather
than several independent gaps, and more checks confirming things were sound
than finding faults. That reads like the place to stop rather than manufacture
another pass — and it was not, which is the more useful lesson.

Seven more followed (29-35), and not one of them came from re-reading the servo
path. Finding 29 came from asking what the CB2 runs that it need not. Findings
30-32 came from reading the gates themselves instead of their output — a gate
that reports a pass it did not run is the one defect no amount of running it
will surface. Finding 33 came from pointing a bug-focused lint at `klippy/`,
where 161 hits contained exactly one real bug. Findings 34 and 35 came out of
building what the owner asked for: the PDO map turned out to have two dead
groups on the way to making it configurable, and giving the simulator an
EtherCAT world is what exposed that the claim seam had no test.

So the pattern worth keeping is not "look harder", it is *change what is being
looked at*. A converged sweep is converged; the next finding is in a place
nobody has framed as a place yet — the harness, the gates, the host's idle
work, the thing you are about to build.

As of `c9421b5`, every gate that can run in this container runs green:
`ci.sh quick` at 5 pass, the Rust suite 2488 passed / 5 skipped, the Python
suite 1046 passed / 5 skipped, nine doc tests, and all thirteen workflows
parsing. Snapshots read 51 ok / 0 changed, which is the load-bearing one: the
planner's output is byte-identical to base. The five Python skips are the
matplotlib plot tests recorded above under **Known, deliberately not changed**.

Three gates are **not** green here, and none of the three is red for a reason
in this repository — say so plainly rather than let the tally imply otherwise:

- `deny` and `fuzz-piece-sink` **skip**: `cargo-deny` is not installed and the
  sanitizer runtime cannot be linked. Since finding 30 they report that as SKIP
  instead of counting themselves as passes, which is the whole point of that
  fix — an absent tool now looks like an absent tool.
- `py`, `sim` and `sim-e2e` **fail at image build**: the container's outbound
  HTTPS goes through a MITM proxy and the Docker build has none of its CA, so
  `curl` inside the image exits 60. Not worked around, because the only
  workarounds weaken TLS. Finding 31 did improve what it looks like — it is now
  `FAIL (1)` at the line that failed rather than `FAIL (125)` with docker's
  "invalid reference format" on top.

## Not yet audited

Rescoped once the upstream diff made it clear what is actually this branch's
code. `motion-core` is byte-identical to upstream apart from `kinematics.rs`
and `motion_history.rs`, both now verified, and eight of the 163 files under
`klippy/extras/` are touched at all — so most of what this list used to name is
upstream's code, running on upstream's hardware, and auditing it is a different
job from auditing this branch.

- `Config_Reference.md` — the non-motion half. Only
  `Config_Reference_Motion.md` has been checked.
- **Upstream's planner internals** — the pipeline stages, `geometry`,
  `motion-pipeline`. Unexamined here, and deliberately so: a change there moves
  motion output and needs a regenerated baseline, which is the owner's call,
  not an auditor's.
- `klippy/extras/` beyond the servo path — the 155 files byte-identical to
  upstream. A bug found there is upstream's, not this branch's. The eight that
  are not are `emergency_stop.py` (new here) and `bus.py`, `ethercat_node.py`,
  `homing.py`, `log_observability.py`, `resonance_buzz.py`, `servo_axis.py`,
  `servo_strain_comp.py`, all read on this branch.
- `tools/sim` beyond its unit subset and the EtherCAT world added here. That
  world, plus `test_ethercat_claim_stub.py`, closes what used to be listed:
  the seam where klippy spawns the endpoint and completes the claim is no
  longer exercised only by hand at Part 12 step 1. The world itself is only
  half-run, though — its four `sim_unit` cases run in the ordinary suite, its
  two `needs_elf` cases need the sim image, and Docker cannot build that image
  in this container for want of the proxy's CA. Those two were checked against
  the harness they call, not against a run.
- **The five items in the guide's "Still unverified on hardware".** A drive on
  the bench settles them and nothing else does: the ESTUN vendor ID and product
  code, the Markforged belt-coupling sign, `ec_dwmac-rk` actually loading on the
  CB2, whether 60 W per drive is enough regenerative capacity for this gantry,
  and the three `-EC`-only values (`Pn006.0 = 4`, `A.70`, `A.71`) the base
  ProNet manual cannot confirm.

## Resuming on a fresh container

Everything is committed and pushed; the branch is the state. Nothing needs
carrying over but the build artifacts, which are regenerated:

```sh
scripts/build-native.sh          # klippy/_*.so — klippy will not start without them
cargo install cargo-nextest --locked   # if absent; the Rust suite needs it
./scripts/ci.sh quick            # expect 5 pass
uv run pytest test/ -q           # expect 1251 passed, 8 skipped
```

`test_ethercat_claim_stub.py` and `test_pdo_map.py` need artifacts the first
line does not build: the stub endpoint (`make -f Makefile.rust ethercat-stub`)
and a C compiler. Both skip cleanly when they are absent, so a short count
there means a missing artifact, not a regression.

The pytest figure is the count at the tip of this branch and it only grows as
findings land, so a *larger* number is new tests and a *smaller* one is a
missing artifact. The eight skips are five matplotlib plot tests, one
self-exempting doc-reference test, and two documents that legitimately carry
nothing for the rule being checked. `test_motion_budget_page.py` also runs the
page's own JavaScript where `node` is on PATH and skips where it is not, so
that one is a skip on a bare container and a pass on a developer's.

Use `uv run`, not ad-hoc `pip install` — every dependency is already declared
in `pyproject.toml`.

Two environment notes, neither a repo defect:

- **Docker** gates (`py`, `sim`, `sim-e2e`) need a daemon *and* a way to build
  the image. Without a daemon, run the Python suite directly as above; `ci.sh
  py` will not fall back, because the docker binary exists and only the daemon
  is missing. With a daemon but behind a MITM proxy, the build dies at `curl`
  exit 60 instead — the image has no copy of the proxy's CA. Give the build the
  CA; do not disable TLS verification to get past it.
- **Disk.** `rust/target` reaches ~19–25 GB. A full volume shows up as
  `ld terminated with signal 7 [Bus error]` during linking, which reads like a
  toolchain fault and is not one. `rust/target/debug/incremental` is the
  largest regenerable directory to clear.
