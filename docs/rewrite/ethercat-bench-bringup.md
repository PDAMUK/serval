# EtherCAT servo bring-up (bench checklist)

> Practical guide for bringing the EtherCAT servo axis up at the bench.
> Companion to
> [`motion-node-unification.md`](motion-node-unification.md) (the design).
> The trajectory math, fault handling, streaming, and stepper-path safety are
> already verified off-bench (see that doc); this is the on-hardware sequence.

## What's already proven without hardware
- MCU stepper hot-path codegen is **byte-identical** to pristine main (disasm-verified). Flashing this branch will not change stepper behavior.
- The servo runs the **same hardened walker** as the MCU (`runtime::motion_core`); its trajectory eval, origin/no-jump mapping, piece-boundary continuity, and the `PieceStartInPast` fault boundary are unit-tested.
- Sustained streaming past one ring depth works over the real `McuSerialConn ↔ FrameServer` socket (no stall — the "stopped after first move" class is covered).
- `klippy → motion-engine → endpoint` host wiring is ported and the stepper-path tests still pass.

## Stub validation: results (2026-06-01, no second MCU)

> Kept as the record of that run, in the syntax of the day. `[servo_x]` below
> is the section name as it then was; role-encoding sections are refused now —
> see **Sample config**. Nothing else in this block has changed meaning.

Validated the whole host path on the Pi 3B with **no second STM32** — a
Linux-process MCU (`klipper_mcu`, MACH_LINUX build) as the primary clock + Y/Z
steppers, and the EtherCAT servo on X talking to the `ethercat-rt-stub`.

**Proven end-to-end (servo path):**
- klippy reaches `ready`; `[ethercat_node]` + `[servo_x]` parse; the servo axis
  binds correctly (X excluded from stepper `runtime_bindings`: `present=0x6`,
  `steps_per_mm[0]=0`); the bridge claims the node (`claimed handle=1`) and
  `McuSerialConn` connects to the stub (`client connected`).
- `SET_KINEMATIC_POSITION` → position updates, axes home (`xyz`), no crash.
- `G1 X…` streams `PushPieces` to the endpoint; the stub's `retired_count`
  advances steadily; `M400` drain completes for servo-only moves; the endpoint
  **never faults** (`engine_state` stays running).

**Bug found + fixed during this validation** (commit `5ad6e3568`): the
`set_position` seed loop assumed every motion node is a serial MCU with a
`host_io` and aborted the klippy host with **SIGABRT** (`bridge.rs` panic
`set_position seed: mcu_id N has no host_io`) the moment an EtherCAT node was
present. EtherCAT endpoints self-seed their origin from the encoder at first
sample and were already re-seeded by `runtime_stream_open`, so the stepper-only
serial `runtime_seed_position` must be skipped for them (`build_serial_seed_sends`
filters EtherCAT `mcu_id`s; fail-loud panics preserved for genuine invariants).
This bug was **MCU-independent** — it would have crashed the real-drive bench
too, so catching it without the drive was the point of the stub step.

**Linux soft-MCU `TickIntervalExceeded` (-311) — root-caused and fixed.** The
Y/Z stepper path on the Pi-3B Linux MCU faulted `-311` (retired 0 pieces) because
the host tick loop ran at a hardwired `HOST_TICK_HZ=1000` while the MACH_LINUX
sample-rate default was 10000 — a 10× mismatch between the engine's expected
`sample_period` and the actual inter-tick gap, which trips the guard on the first
active tick. The MACH_LINUX first-class-MCU work fixes this: `HOST_TICK_HZ` now
derives from `CONFIG_MOTION_SAMPLE_RATE_HZ`, whose MACH_LINUX default is
1000 (the stock-kernel `clock_nanosleep` floor), and the tick thread inherits the
process SCHED_FIFO (`klipper_mcu -r`) instead of self-demoting to nice+19. A real
STM32 (hardware TIM5) never had this issue.

**Verified on the Pi 3B (2026-06-01)** with the real non-sim build (`mcu-linux`,
`MCU_SIM=n`): klippy reaches `ready` driving real `/dev/gpiochip0`, and a
stepper move now *executes* (`G1 Y110` moved Y 100→110) where the old binary
retired 0 pieces and instant-faulted `-311`. The runtime `-311` is resolved. A
**separate** residual remains: *sustained* motion still trips Klipper's **base**
scheduler guard (`Rescheduled timer in the past`, `src/linux/timer.c` / `sched.c`
— NOT the runtime `-311`) because the soft timer jitters under load on a
non-PREEMPT_RT kernel. Reliable sustained Linux-MCU stepping therefore needs a
PREEMPT_RT kernel (or the parallel soft-MCU timing work); the EtherCAT servo
path — the actual bench target — is unaffected and streams cleanly.

**Building a real (non-sim) Linux MCU:** `make` with `CONFIG_MACH_LINUX=y` and
`CONFIG_MCU_SIM` **unset** drives real `/dev/gpiochip` / `/dev/spidev`
(`test/configs/linux.config`). `CONFIG_MCU_SIM=y` (`.config.linux`, and the
firmware configs the simulator builds from in `tools/sim/configs/`) selects the in-memory sim shims. The Rust `mcu-linux`
feature carries the f64 host numeric profile plus the real-firmware marker that
links the C step/SPI FFI. Note: raw STEP/DIR GPIO pulse emission on a Linux MCU
is a follow-on; TMC phase-stepping over SPI is the supported real-hardware
stepping path today.

## Sample config

A complete minimal machine: one servo on X, steppers on Y and Z. It parses as
written — the annotations are the reference, and the section shapes are the
ones the config reader accepts.

**`[servo_x]` is not one of them.** Role-encoding sections (`[servo_x]`,
`[servo_y]`, `[servo_z]`, and `[stepper_x]` and friends) are refused outright:
a motor is named freely and assigned a role in `[kinematics]`. Motor properties
live on `[motor <name>]`; travel limits and homing live on `[axis <name>]`.

```ini
[kinematics]
type: cartesian
axis_x: x
x_motors: motor_x
axis_y: y
y_motors: motor_y
axis_z: z
z_motors: motor_z

# The EtherCAT motion endpoint, reached over a Unix socket (NOT a Klipper MCU).
# klippy SPAWNS the endpoint binary itself at claim time — you do not launch it.
[ethercat_node node_x]
socket: /tmp/kalico-ethercat.sock   # required; the Unix socket klippy connects on
interface: eth0                     # required; NIC the drive is wired to (raw EtherCAT)
# endpoint: optional. Absolute or repo-relative path to the binary klippy spawns.
#   Default: rust/target/release/ethercat-rt (the hw binary). Point this at
#   the stub for drive-off validation (see below).
#endpoint: rust/target/release/ethercat-rt-stub
# group_delay_us: optional. Leads curve sampling to compensate the drive's CSP
#   group delay; default is one DC cycle (cycle_us).
#group_delay_us: 250

# A position-commanded servo presented as the X axis. No step/dir, no microsteps.
[motor motor_x]
drive: servo                  # 'servo' or 'stepper'; a lane's motors must agree
protocol: ethercat            # only 'ethercat' is supported
node: node_x                  # must match an [ethercat_node <name>]
ethercat_chain_index: 0       # position on the wire, counting from the host
rotation_distance: 40         # mm of axis travel per motor revolution (your mechanics)
encoder_counts_per_rev: 131072  # required; drive encoder counts per motor rev (A6-EC: 131072)
#invert_direction: True         # reverse motion AND feedforward (position, velocity_ff, torque)
# Feedforward (optional; see servo-feedforward.md):
#velocity_ff: True              # stream 60B1h velocity feedforward
#dynamics_profile: dynamics_x.toml  # enables 60B2h torque feedforward
#ff_max_torque: 30.0          # torque-offset ceiling, % of rated
# Drive protection (homing-scoped: written to 6065h/6072h around each G28,
# restored after; a trip de-energizes the drive and fails the G28 loudly):
#homing_following_error: 2.5   # mm of commanded-vs-actual deviation (default 2.5)
#homing_max_torque: 50         # % of rated torque during homing (default 50)
# Session-wide variants (written once at bringup; unset = drive defaults):
#following_error: 10
#max_torque: 150

# Travel limits and homing belong to the axis, not the motor. With endstop_pin
# set, G28 homes the servo axis against a GPIO endstop on any bridge MCU;
# without it the axis has no endstop and G28 on it fails loudly.
[axis x]
position_min: 0
position_max: 300
#endstop_pin: ^PA13            # pin on the MCU that carries the switch
#position_endstop: 0           # at or beyond position_min or position_max; placing it
                               # past the range (e.g. 300.5 with position_max 300) keeps
                               # that margin between full-range moves and the crash point
                               # a sensorless home lands on (encoder noise, belt stretch)
#homing_speed: 50
#homing_retract_dist: 5        # back-off after endstop contact (default 5, 0 disables)
#homing_retract_speed: 50      # back-off speed (default: homing_speed)

[motor motor_y]
drive: stepper
step_pin: PB8
dir_pin: !PB7
enable_pin: !PE0
rotation_distance: 40
microsteps: 16

[axis y]
position_min: 0
position_max: 300

[motor motor_z]
drive: stepper
step_pin: PG13
dir_pin: PG12
enable_pin: !PG15
rotation_distance: 8
microsteps: 16

[axis z]
position_max: 250
```

Bring-up now performs the **variable PDO remap** (1600h/1A00h via SDO in
PRE-OP; exit rc -6 on failure) and the **FF-routing SDO writes** (C01.13/16 =
5, C01.14/17 = 0; exit rc -10 on failure) before the DC stabilize loop.
The percentage registers stay 0 because with source = 5 the drive applies
60B1h/60B2h at (100% + C01.14/C01.17) — bench-measured 2026-06-12: pct=1000
doubled the applied feedforward (cruise lead of exactly v/Kp), pct=0 gave
unity (cruise rms 55 counts at 400 mm/s).
Both are rewritten on every claim — they are not EEPROM-retained. See
[`servo-feedforward.md`](servo-feedforward.md) for the FF config keys and
identification workflow.

`counts_per_mm = encoder_counts_per_rev / rotation_distance` — the `CountMap` gain
the endpoint uses to convert host millimetres to drive counts. klippy derives it at
claim time from `[motor motor_x]` and hands it to the spawned endpoint. Get both keys right
before the drive moves.

## Drive profiles (which drive family is on the bus)

Everything the endpoint streams is standard CiA 402, but the identity it matches
on the bus, the optional objects it maps, and the vendor SDOs it writes in
PRE-OP all differ per drive family. `drive_profile:` on `[ethercat_node]`
selects one; `a6ec` is the default, so existing configs are unchanged.

| | `a6ec` | `estun-pronet` |
| --- | --- | --- |
| Drives | StepperOnline A6-EC | ESTUN ProNet with EC100 (`ProNet-…-EC`) |
| Identity | built in (`0x00400000` / `0x00000715`) | **not public — you must supply it** |
| Torque limit | `6072h` | `60E0h`/`60E1h`, written as a symmetric pair |
| Following error | `60F4h`, mapped into the TxPDO | not in the dictionary; derived from `607Ah - 6064h` |
| Feedforward routing | `0x2001:14/15/17/18` (C01.13/14/16/17) | none — CSP applies `60B1h`/`60B2h` directly |

Both offsets, `60B1h` velocity and `60B2h` torque, are PDO-mappable on ProNet,
so the feedforward path works unchanged. Both families also take the same DC
`AssignActivate` word, `0x0300` (SYNC0 only, one pulse per cycle period), and
ESTUN states it itself in chapter 4 of the ProNet EtherCAT manual - "DC mode
(ESC register: 0x980 = 0x0300)", worded identically in V1.05 and V1.06 - so the
shared value is documented for both, not inherited from the A6-EC.

ESTUN gives the DC cycle range twice and the two disagree: the communication
specification table says 250 us to 8 ms, while `0x1C32:02` gives `125000 * n`
ns with `n = 2..16`, which stops at 2 ms. The lower bound matches, so the
default 250 us (4 kHz) `cycle_us` is in spec under either reading; a cycle
slower than 2 ms is the part to check against the drive in hand.

**What `estun-pronet` assumes.** The profile captures three differences from the
A6-EC (no `60F4h`, split torque limit, no feedforward routing). Everything else
is the A6-EC's, carried over unconfirmed: the touch-probe objects
`60B8h`/`60B9h`/`60BAh`/`60BCh`, the digital I/O `60FEh:01`/`60FDh`, variable
remapping of RxPDO `1600h` and TxPDO `1A00h`, and the following-error window
`6065h` and timeout `6066h` — the last two from the same CiA group as the
`60F4h` this family does not have. ESTUN's dictionary was never obtained, so
none of it is verified.

The endpoint no longer lets those assumptions fail silently. A refused PDO map
names `1600h`/`1A00h` and the `1C12h`/`1C13h` assignment; a rejected config SDO
names the object; a slave that never reaches OP prints its AL state and status
code per slot, with a reminder that the master applies config SDOs in PRE-OP so
a refusal can only surface there. Each of those prints the profile's assumption
list, so the first bring-up says which assumption broke instead of leaving a
bare `rc=-6` or an OP timeout.

**ESTUN identity.** ESTUN ships it only in `ESTUN_ProNet_CoE.xml`, which is not
published — request it with the order, or read the live values off the bus:

```sh
ethercat slaves -v | grep -iE 'vendor|product'
```

Then set them on the node. Without them the claim fails loudly naming what is
missing, rather than enumerating nothing and blaming the cable:

```ini
[ethercat_node node_xy]
drive_profile: estun-pronet
vendor_id: 0x00000000       # replace, from the ESI or `ethercat slaves -v`
product_code: 0x00000000    # both halves; a zero either side is refused
```

The placeholders are zeros deliberately. **Both** halves are required and both
must be non-zero, and klippy names whichever is missing before anything is
claimed. A plausible-looking wrong value is the worse failure: it passes config
time, then never matches a drive, and the bus dies at the OP walk with nothing
pointing back at the identity.

A drive that is present but of a different identity looks exactly like an absent
one to the master (`rc=-2`), so the endpoint now names the profile and the
identity it matched on in that error.

**Two ESTUN bring-up steps that are not on the EtherCAT side at all.** Set them
from the panel operator or ESView before the bus will do anything:

- `Pn006.0 = 4` selects EtherCAT communication mode.
- `Pn704` sets the station alias.

**ESTUN sync-loss alarm.** `A.70` ("EtherCAT synchronous error — the cycle the
master set is not correct, or SYNC0 has not kept up") is ProNet's version of the
A6-EC's ErC1.1 trap. Same root cause, same fix: the DC loop must hold `SCHED_FIFO`
on an isolated core. See the real-time scheduling section below.

## Markforged with two ESTUN drives (worked example)

> Wiring, mains, encoder cabling and the staged first power-on for exactly this
> machine are in
> [`estun-pronet-markforged-setup.md`](estun-pronet-markforged-setup.md).


A Markforged gantry with the Y motor on a straight frame loop and the X motor on
the T-shaped loop, one drive per belt — not AWD, so each lane owns exactly one
drive and the pair-specific machinery (diff damper, diff trim, strain map) is
not in play.

`encoder_counts_per_rev` is the motor's, not the drive's: an EMJ-04AFD22 carries
the **20-bit incremental** encoder, so it is **1048576**, not the 131072 of a
17-bit absolute. Getting this wrong scales every move by 8.

```ini
[kinematics]
type: markforged
axis_x: x
x_motors: motor_x          # the T-belt motor (lane 0, carries x + y)
axis_y: y
y_motors: motor_y          # the straight-loop motor (lane 1, pure y)
axis_z: z
z_motors: motor_z

[ethercat_node node_xy]
socket: /tmp/kalico-ethercat.sock
interface: eth0
drive_profile: estun-pronet
vendor_id: 0x00000000       # replace: klippy refuses to start until you do
product_code: 0x00000000    # both halves, and both non-zero
cycle_us: 250

[motor motor_x]
drive: servo
protocol: ethercat
node: node_xy
ethercat_chain_index: 0
rotation_distance: 40                 # your pulley, not a default
encoder_counts_per_rev: 1048576       # EMJ-04AFD22, 20-bit incremental
max_torque: 100                       # % of rated. 300 is the motor's peak
following_error: 2.0                  # mm; unset writes no session limit

[motor motor_y]
drive: servo
protocol: ethercat
node: node_xy
ethercat_chain_index: 1
rotation_distance: 40
encoder_counts_per_rev: 1048576
max_torque: 100
following_error: 2.0

[motor motor_z]
drive: stepper
step_pin: PB8
dir_pin: !PB7
enable_pin: !PE0
rotation_distance: 8
microsteps: 16

# Travel limits and homing are the axis's, not the motor's.
[axis x]
endstop_pin: ^PF4
position_min: 0
position_max: 300
position_endstop: 0
homing_speed: 50

[axis y]
endstop_pin: ^PF3
position_min: 0
position_max: 300
position_endstop: 0
homing_speed: 50

[axis z]
endstop_pin: ^PF2
position_max: 250
```

`max_torque` is a percentage of *rated* torque and accepts up to 400, so 300 is
the EMJ-04A's full peak — roughly 600 N at a 20-tooth pulley (40 mm of belt
per turn). Bring a machine up at
100 and raise it because a move stalled, not before. `following_error` has no
default: leave it out and no session limit is written at all, and the drive
keeps whatever the last session left in `6065h`.

Homing note specific to Markforged: a Y move drives **both** motors, an X move
drives only the X motor. Y therefore cannot take a per-motor `endstop_pin` and
the config rejects it; X can.

The ESTUN tuning parameters reachable as `params:` / `SERVO_PARAM` live in the
manufacturer area at `0x3xxx` — `0x3012.0` = Pn102 speed loop gain, `0x3014.0`
= Pn104 position loop gain, `0x3016.0` = Pn106 load inertia ratio, `0x301C.0`
= Pn112 position feedforward, `0x301E.0` = Pn114 torque feedforward. Note
ESTUN's feedforward percentages are 0-100, so the A6-EC's bench-measured
feedforward calibration does not carry over.

## Drive parameters (SDO)

Drive tuning lives in config, not drive EEPROM. `params:` entries on `[motor <name>]`
are raw CoE object addresses pushed to drive RAM (never EEPROM) on every claim,
after bringup succeeds and before the claim is reported healthy. Each write is
read back; a mismatch (drive clamped or rejected the value) fails the claim with
the offending address, the value written, and what the drive settled on.

```ini
[motor motor_x]
# ... options above ...
params:
    0x2002.0: 100          # size probed via SDO upload (one extra mailbox round-trip)
    0x2003.0: u16 250      # explicit type (u8/u16/u32/i8/i16/i32) skips the probe
    0x2010.1: i32 -4096
```

Ad-hoc access while tuning:

```
SERVO_PARAM SERVO=motor_x GET=0x2002.0
SERVO_PARAM SERVO=motor_x GET=0x2002.0 TYPE=i16
SERVO_PARAM SERVO=motor_x SET=0x2002.0 VALUE=100 TYPE=u16
```

GET without `TYPE=` prints raw hex plus both unsigned and signed decimal
interpretations. SET reads the value back and reports what the drive settled on.
Objects wider than 4 bytes (strings, segmented transfers) are unsupported and
fail loudly. SDO traffic is mailbox traffic — it rides between DC cycles, fast
but not deterministic; anything needing hard-real-time parameter changes gets
mapped into the PDO instead.

To deliberately persist parameters to drive EEPROM, SET the drive's
store-parameters object (CiA 301 object 0x1010 — check the A6-EC manual for the
magic value) — kalico never does this implicitly.

The stub endpoint serves a small fake object dictionary (0x2002.0, 0x2003.0
clamping at 500, 0x2010.1, 0x6041.0 read-only), so the whole path — claim-push,
verify-mismatch claim failure, SERVO_PARAM — can be validated drive-off.

## Bring-up sequence

> **This is the original A6-EC bench's sequence**, kept as the record of how
> that machine was brought up: a Pi host, two MCUs, and config backups
> (`.config.h7.bak`, `.config.f446.test`) that live on that bench and not in
> this repository. A Markforged servo build follows
> [`estun-pronet-markforged-setup.md`](estun-pronet-markforged-setup.md)
> Part 12 instead, which stages the same idea for one Manta and two ESTUN
> drives. Read this one for *why* each stage exists; take the steps from that
> one.

The endpoint is **spawned by klippy** at node-claim time (mcu-identify), using the
`endpoint:` path and the derived `counts_per_mm`. There is no manual endpoint launch
and no pre-flight script — you choose stub vs hw by setting `endpoint:`, then start
klippy.

### 1. Deploy + flash (low risk — stepper path unchanged)
- Commit/push the branch; pull on the Pi; build there (never cross-compile + scp).
- Flash **both** MCUs with their respective configs (H7 from `.config.h7.bak`, F446 from `.config.f446.test`); `make clean` between them. `make -j$(nproc)`.
- `CONFIG_MOTION_MODULE_STEPPER=y` is the default on STM32 — leave it on.

### 2. Build the endpoint binaries (on the Pi)
```sh
# hw endpoint — build.rs compiles csrc/libecrt_igh.c + links IgH (libethercat). On the Pi (never CI):
make -f Makefile.rust ethercat-endpoint-hw
# Grant capabilities so it runs unprivileged. sudo, ONCE PER REBUILD of the binary:
make -f Makefile.rust setcap-ethercat   # cap_net_raw, cap_sys_nice, cap_ipc_lock
# no-hardware stub (no FFI, no setcap needed):
make -f Makefile.rust ethercat-stub
```

### 3. Stub validation FIRST (no drive — zero hardware risk)
Confirm the whole host path before energizing anything. Point the node at the stub:
```ini
[ethercat_node node_x]
socket: /tmp/kalico-ethercat.sock
interface: eth0
endpoint: rust/target/release/ethercat-rt-stub
```
- Start klippy. It **spawns the stub itself** at claim time — you do not launch it.
  Confirm klippy reaches **`ready`**.
- `SET_KINEMATIC_POSITION X=100`, then a small `G1 X105 F600`, `M400`.
- Watch the stub's stderr (klippy redirects it): `PushPieces` frames arrive, `retired`
  counts advance, `engine_state` stays running (1), never `Fault` (3). This proves
  planner → bridge → transport → endpoint end-to-end with no servo.

### 4. Real drive (supervised)
- Switch `endpoint:` back to the hw binary (or drop the key to use the default
  `rust/target/release/ethercat-rt`) and restart klippy.
- **Dark drive (powered off / disconnected):** with the drive as the only slave on
  the bus, a powered-off drive means the master finds no slaves at all (rc=-2); klippy
  fails the claim loudly with:

  > `ethercat node_x: EtherCAT bus on eth0: no slaves responding (bringup rc=-2) — check cable and drive power, then FIRMWARE_RESTART`

  If the drive IS found but fails the SAFE-OP/OP/CiA402-enable walk (rc=-3..-5),
  you get the per-drive variant instead:

  > `ethercat node_x: drive (slave 1) offline (bringup rc=-{N}) — check drive power, then FIRMWARE_RESTART`

  Power the drive on (and/or fix the cable), then `FIRMWARE_RESTART` — klippy re-spawns
  the endpoint and the claim succeeds, reaching `ready`.
- **Before the first move:** the endpoint captures the rotor's current count as the
  origin at first sample, so the first commanded position maps to the actual rotor
  position — there should be **no startup jump**. If the axis lurches on the first
  command, stop and check `encoder_counts_per_rev` / `rotation_distance` / origin
  capture.
- Do a small supervised jog. Watch for:
  - `engine_state == Fault (3)` in the `StatusHeartbeat` → the host pump fell behind >2 ms (`PieceStartInPast`). The endpoint latches the fault and propagates it so the host can shut down; the hw binary also disables the drive. This is expected on a gross stall, not on a healthy stream.
  - `wkc != 3` → EtherCAT bus working-counter fault (drive comms), the endpoint
    halts and dumps `al_status=0x…`. `al_status=0x001a` is a DC sync loss (ErC1.1) — see the
    real-time scheduling section; the usual cause is the loop not running
    `SCHED_FIFO` on the isolated core.

### 5. Recovery
- Any fault or claim failure is recovered the same way: fix the cause, then
  **`FIRMWARE_RESTART`**. klippy SIGTERMs the old endpoint (which cleanly disables the
  drive), re-spawns it, and re-runs the claim. There is no manual pre-launch, socket
  cleanup, or endpoint restart to do by hand.
- The old `bench-hw-up.sh` choreography is **obsolete** — klippy owns the endpoint
  lifecycle now. Delete that script from the bench host if it's still there.
- **A latched `0x8700` / ErC1.1 is the exception:** `FIRMWARE_RESTART` re-spawns
  the endpoint but does **not** clear the drive's stored sync-loss fault (the
  EtherCAT INIT bounce resets the network state machine, not the CiA402 fault).
  With the drive on its own supply it stays faulted across host restarts —
  **power-cycle the drive** to clear it, then fix the root cause (almost always
  RT scheduling; see that section) so it does not re-latch on the next boot.

## Servo telemetry capture (multi-drive)

The full `SERVO_*` calibration command and script reference lives in the
[serval-dashboard](https://github.com/dderg/serval-dashboard) repository.

**Which half of `SERVO_*` is which.** This repository registers four commands
and no more: `SERVO_CAPTURE_START`, `SERVO_CAPTURE_STOP`, `SERVO_PARAM` and
`QUERY_EMERGENCY_STOP`. Everything else named below — `SERVO_FIT_DYNAMICS`
among them — is a serval-dashboard macro. A console answering "Unknown
command" for one of those is missing that install, not a broken build, and the
distinction is worth stating because the two sets are described here in the
same breath.

`SERVO_CAPTURE_START AXIS=<axis>` records the servo on that axis on its
`[ethercat_node]`, even when the node carries several drives — the host resolves the
target to a `(node, slot)` and tells the endpoint which slot to sample.
`SERVO=<motor name>` also works for a direct by-name capture. The calibration macros
already know their axis, so they pass `AXIS=` — nothing depends on the motor being
named `motor_<axis>`. The `.scap` file holds one drive block per captured drive;
today the host lists a single slot, but the format and wire message already carry
N drives time-aligned on the shared DC cycle (`cycle_us`) (a future CoreXY axis expands
to multiple slots with no format change). A single-drive capture is byte-identical
to the pre-multi-drive layout.

The analysis tools select a drive by name (defaulting to the first drive in the
file): `scripts/servo_capture.py --drive <motor>` for a single manual capture,
and `servo-cal fit --axes <motor>` for the dynamics fit. `SERVO_FIT_DYNAMICS
AXIS=<axis>` works unchanged on a multi-drive node.

Each `.scap` header drive entry records the drive's `counts_per_mm` and
`rotation_distance`; `SERVO_FIT_DYNAMICS` resolves the rotation distance the
C00.06 recommendation needs from the `[motor]` config and passes it to
`servo-cal fit` as `--rotation-distance-mm`.

## Real-time scheduling — mandatory (the ErC1.1 / "ErC11" trap)

The endpoint's DC loop (at the configured `cycle_us` rate) **must** run `SCHED_FIFO` on an isolated CPU. This
is not best-effort. If it runs `SCHED_OTHER`, the loop keeps cadence on a warm,
idle Pi but misses SYNC0 under boot load — and the drive latches **ErC1.1
"synchronization loss"** (panel reads `ErC11`; CoE error register `0x8700`;
EtherCAT AL status `0x001a`, visible in the endpoint's `ec_rt: slave1 …
al_status=0x001a` dump on a working-counter halt). Because the drive is usually on its
own always-on supply, that latch **survives every host reboot**, so klippy's
auto-restart keeps re-claiming an already-faulted drive — only a **drive
power-cycle** clears `0x8700`. Classic signature: fails on cold boot / right
after a flash, "works once it's connected."

All three of the following are required, or `go_realtime()` aborts the claim
loudly — `rc=-10` (mlockall / `CAP_IPC_LOCK`), `rc=-11` (CPU pin), `rc=-12`
(`SCHED_FIFO` / `CAP_SYS_NICE`), each naming the missing capability. There is no
silent `SCHED_OTHER` fallback any more; that fallback was the original ErC11
heisenbug.

1. **`cap_sys_nice`** (for `SCHED_FIFO`) and **`cap_ipc_lock`** (for `mlockall`)
   on the endpoint binary: `make -f Makefile.rust setcap-ethercat`. **A
   `cargo build` writes a fresh inode and drops file-caps**, so re-run setcap
   after *every* endpoint rebuild — the flash script re-applies it, a bare
   rebuild does not. Skipping it is the direct cause of "ErC11 after flashing".
2. **An isolated core to pin to — and it must be CPU 3.** The bench reserves
   CPUs 2-3 on the kernel cmdline
   (`isolcpus=domain,managed_irq,2-3 nohz_full=2-3 rcu_nocbs=2-3`), which
   covers it with a core to spare. The endpoint pins to CPU 3 and nothing
   reachable changes that: `--rt-cpu` exists on the binary, but klippy spawns
   the endpoint and the bridge never emits the flag, so no config reaches it.
   Isolating a different core is worse than useless — `sched_setaffinity(3)`
   succeeds for any online CPU, so the loop pins to a contended core while
   every check below still reads correct. An isolated core stays
   contention-free even while the rest of the Pi is saturated booting — that is
   what holds cadence through the cold-boot window that used to fault.
3. **`SCHED_FIFO`** at priority 80 (`--rt-prio`, and unreachable for the same
   reason).

**Robust alternative to per-rebuild setcap** (ambient caps survive rebuilds; the
file-cap does not): grant the caps on the systemd service via a drop-in
`/etc/systemd/system/klipper.service.d/10-ethercat-rt.conf`, then
`systemctl daemon-reload`:

    [Service]
    AmbientCapabilities=CAP_SYS_NICE CAP_IPC_LOCK
    LimitRTPRIO=infinity
    LimitMEMLOCK=infinity

The spawned endpoint inherits the ambient caps from klippy. (If the binary also
carries file-caps, those take precedence and the ambient set reads back empty —
harmless, since file-caps already include `cap_sys_nice`.)

**Verify it is actually in force** — a green *warm* restart only proves the cap
took; only a **cold reboot** proves the loop holds cadence under boot load:

    pid=$(pgrep -f release/ethercat-rt)
    chrt -p $pid                                     # want: SCHED_FIFO priority 80
    grep Cpus_allowed_list /proc/$pid/status         # want: 3 (the isolated core)
    /usr/sbin/getcap rust/target/release/ethercat-rt   # want: ...cap_sys_nice=ep
    sudo journalctl -b | grep -c 'al_status=0x001a'         # want: 0

`SCHED_OTHER` + `cpus 0-1` on the live endpoint is the bug, not health — the cap
is not reaching it. (Endpoints sampled in their first ~200 ms read `SCHED_OTHER`
because `go_realtime()` runs just after `main()` startup; sample the
steady-state pid.)

## Variable RxPDO 0x1600 remap (rc=-6 / rc=-7)

`out_t` is the 18-byte variable RxPDO **`0x1600`** (`6040` controlword, `607A`
target position, `60B8` touch-probe function, `60FE:01` forced-DO, plus the two
feedforward offsets `60B1` velocity and `60B2` torque). The fixed `0x1701` the
bench used before carried only the first four — it physically can't hold the FF
offsets — so feedforward requires the variable map.

The drive can power up with a *different* RxPDO assigned to `0x1C12`, whose byte
count disagrees with `out_t` and aborts bringup at `EC_RT_ERR_PDO_SIZE` (`rc=-7`,
`ec_rt: PDO size mismatch — mapped out=… …`). Bringup now **forces** `0x1C12 →
0x1600` and rewrites the whole `0x1600` entry table before mapping (mirroring the
existing `0x1C13 → 0x1A00` TxPDO remap), so a clean 18-byte map no longer depends
on the drive's retained state. A failure to write that remap is `rc=-6`
(`EC_RT_ERR_PDO_REMAP`), the same code as the `0x1A00` TxPDO remap. See
[`servo-feedforward.md`](servo-feedforward.md) for the FF routing (C01 group →
60B1h/60B2h) that the FF entries feed.

## Fault-response reference
- **`PieceStartInPast`** (a piece adopted >2 ms late = 2× the 1 ms DC period): the walker faults, the endpoint latches it (allocation-free atomic) and reports `engine_state=Fault` to the host. Primary response is host-coordinated shutdown (mirrors the MCU model); the hw binary additionally disables the drive as a local backstop. It does **not** silently hold the last position.
- If `engine_state=Fault` fires during a *healthy* stream, the 2 ms tolerance may be too tight for your RT scheduling — that's a tuning knob (`EC_DC_PERIOD_NS` in `curves.rs`), not a logic change.

## If something's off
- Re-run `cargo test -p ethercat-rt -p motion-engine` on the Pi — these are the host-path regression tests.
- The stub-level path (step 2) isolates host bugs from drive/EtherCAT bugs — always confirm it green before blaming the drive.
- Per-piece dispatch projection diagnostics (`[dispatch-margin]` and `[project]`) are emitted at **trace** level to avoid flooding production logs. Enable them with `RUST_LOG=trace` (or a targeted filter such as `RUST_LOG=motion_engine=trace,host_rt=trace`). `RUST_LOG` is read by the `EnvFilter` in `rust/motion-services/src/logging/mod.rs` at bridge startup.
