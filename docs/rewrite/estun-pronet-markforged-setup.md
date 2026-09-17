# Markforged servo build: ESTUN ProNet + BTT Octopus Pro (H723)

A complete build-up from a mechanically assembled but electrically bare
printer to a homing, tuned Markforged machine.

**Starting point.** The frame, gantry, belts and bed are built. Nothing
electrical is fitted: no stepper drivers in the mainboard, no servos mounted,
no endstops, and none of the wiring for any of it.

**Finishing point.** X and Y driven by EtherCAT servos under closed-loop
control, Z and the extruder on TMC steppers, all axes homing, drives tuned.

## Hardware this targets

| Role | Part |
| --- | --- |
| X, Y motors | 2x ESTUN ProNet-04AEG-EC drive + EMJ-04AFD22 motor |
| Z, extruder | TMC2209 stepper drivers in the mainboard |
| Mainboard | BigTreeTech Octopus Pro V1.1, **STM32H723** variant |
| Host | Raspberry Pi 5, Debian 13 trixie |
| Servo supply | single-phase 230 VAC, >= 1.8 kVA |

> The Octopus Pro V1.1 ships in two MCU variants, **STM32F446** and
> **STM32H723**. This guide targets the H723; the repository already carries a
> matching firmware config at `test/configs/stm32h723.config`. Check the chip
> marking before flashing — the two are not interchangeable.

## Architecture, and why steppers remain

The servos replace the X and Y **steppers only**. Everything else on the
printer stays conventional:

```
                       ┌─────────────────────────────┐
   Raspberry Pi 5 ─────┤ klippy + ethercat-rt endpoint│
        │  │           └─────────────────────────────┘
        │  └── USB ──> Octopus Pro H723 ──> TMC2209 Driver2/3 ──> Z motors
        │                    │                TMC2209 Driver4  ──> extruder
        │                    └── endstops PG6 / PG9 / PG10, heaters, fans
        │
        └── eth0 ──> [CN3] ProNet X [CN4] ──> [CN3] ProNet Y [CN4]
                          │                        │
                      EMJ motor X               EMJ motor Y
                      (T-shaped belt)           (straight loop)
```

Mixed drive types are supported per **lane**: a lane's motors must all be the
same type, but different lanes may differ. X and Y are servo lanes, Z is a
stepper lane, and the extruder is a follower axis on a stepper. This is the
configuration the repository describes as "industrial servo on X, steppers
elsewhere".

The Octopus also carries the **endstops for the servo axes**. A servo axis
homes against a GPIO endstop on any bridge MCU, so the X and Y switches land on
the mainboard exactly like a stepper machine's would.

Markforged lane assignment, which everything downstream depends on:

- **Lane 0 = X motor**, on the T-shaped belt. Carries `x + y`.
- **Lane 1 = Y motor**, on the straight frame loop. Pure `y`.

---

## Safety, before anything is energised

- The drive's bus capacitor stays charged after power is removed. **Wait 5
  minutes** and confirm the `CHARGE` lamp is out before touching terminals.
- Never plug or unplug a drive connector with power applied.
- Power sequencing: control power (`L1C`/`L2C`) **on first**, main circuit
  (`L1`/`L2`) on second; reverse on shutdown.
- Keep belts uncoupled until Part 11 says otherwise. A servo with a wrong
  parameter moves faster and harder than a stepper.

---

## Part 1 — Parts and cables to have in hand

| Item | Spec | Note |
| --- | --- | --- |
| TMC2209 drivers | 3x (Z, Z1, extruder) | **Driver0 and Driver1 stay empty** — X/Y are servos |
| Encoder cable | ESTUN **PBP** series | `PBP` = incremental. The `F` encoder is incremental; a `PDP` (absolute) cable is the wrong part |
| Motor power cable | PDM-GD12-XX, or 1 mm^2 self-made | 1 mm^2 covers the 0.05-1 kW band |
| EtherCAT cable | 2x shielded Cat5 or better | 100BASE-TX |
| Drive debug cable | **mini-USB**, double shielded with ferrites | the `-EC` variant uses mini-USB, not the base drive's RS-485 |
| Mains parts | breaker, surge protector, noise filter, contactor | plus a surge suppressor for the contactor coil |
| Regen resistor | external, sized to the gantry | see Part 4 — this frame size has no internal resistor |
| Endstop switches | 3x (X, Y, Z) | wired to the Octopus |

---

## Part 2 — Host

The host runs klippy and the real-time EtherCAT endpoint. It needs a
PREEMPT_RT kernel, the IgH master, and the native `ec_macb` NIC driver.

Follow [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) end to
end before wiring anything. Three of its requirements cause most failures:

- **`eth0` is given entirely to the EtherCAT master and receives no IP
  address.** SSH and LAN must live on Wi-Fi or a second NIC. Confirm with
  `ip route get 1.1.1.1` — the route must not leave via `eth0`.
- **An isolated CPU core** on the kernel command line, for the DC loop to pin
  to.
- **The systemd drop-in** granting the endpoint `CAP_SYS_NICE` and
  `CAP_IPC_LOCK`.

Real-time scheduling is not best-effort here. A DC loop that misses SYNC0 makes
the drive latch **`A.70` — "EtherCAT synchronous error"**. The classic signature
is a machine that behaves on a warm idle bench and faults on a cold boot.

**Verify.** `/dev/EtherCAT0` exists and `ethercat master` reports the master up.
Re-check after a **cold reboot**, not a warm restart.

---

## Part 3 — Firmware for the Octopus Pro

Build on the host, in the repository:

```sh
make menuconfig
```

Settings for the H723 variant:

| Option | Value |
| --- | --- |
| Micro-controller | STM32H723 |
| Bootloader offset | **128 KiB** (`0x8020000`) |
| Clock reference | **25 MHz crystal** |
| Communication | USB (PA11/PA12) |

`test/configs/stm32h723.config` already encodes exactly this and can be copied
to `.config` instead of stepping through menuconfig. Then:

```sh
make clean && make -j"$(nproc)"
```

Flash by copying `out/klipper.bin` to the board's SD card as `firmware.bin`,
power-cycling, and confirming the file is renamed to `FIRMWARE.CUR`.

**Verify.** The board enumerates on the host:

```sh
ls /dev/serial/by-id/
```

Record the `usb-Klipper_stm32h723xx_*` path — Part 10 needs it.

---

## Part 4 — Fit the stepper drivers

Power off the Octopus completely.

| Slot | Driver | Purpose |
| --- | --- | --- |
| Driver0 | **empty** | X is an EtherCAT servo |
| Driver1 | **empty** | Y is an EtherCAT servo |
| Driver2 | TMC2209 | Z |
| Driver3 | TMC2209 | Z1 (second Z, if fitted) |
| Driver4 | TMC2209 | extruder |

Set every fitted TMC2209 for **UART mode** per the driver documentation, seat it
in the correct orientation, and fit its heatsink. A reversed driver is destroyed
on power-up.

Leaving Driver0 and Driver1 empty is deliberate: those lanes have no stepper to
drive, and the pins that would serve them are simply unused.

**Verify.** Visual check of orientation on all three, before power.

---

## Part 5 — Mains and drive power

Each ProNet-04AEG-EC takes single-phase **200-230 VAC +10% / -15%, 50/60 Hz**.
At 230 V the supply sits at the top of nominal with headroom to 253 V. Budget
**0.9 kVA per drive** — about 8 A at 230 V for the pair.

Feed order from the supply: **breaker -> surge protector -> noise filter ->
contactor -> drives.** Fit a surge suppressor across the contactor's excitation
coil.

Per drive:

| Terminal | Connect |
| --- | --- |
| `L1`, `L2` | main circuit power (single phase; `L3` unused) |
| `L1C`, `L2C` | control power, same supply |
| `+1`, `+2` | DC reactor terminals — **leave the factory link fitted** |
| `B1`, `B2` | external regenerative resistor — see below |
| PE | ground plate |

**Regeneration.** The 200 V `A5A`-`04A` frames ship with **no internal
regenerative resistor**. The manual's instruction for this band is an external
resistor between `B1` and `B2`. (The `B2`-`B3` jumper that selects an internal
resistor belongs to the larger `08A`-`50A` drives and does not apply.)

This matters on a fast gantry, which dumps real energy back on deceleration.
The symptom of insufficient capacity is **`A.13` overvoltage**, which the manual
notes can appear when load inertia exceeds roughly 30x the rotor inertia during
acceleration. The EMJ-04AFD22 rotor inertia is 0.31e-4 kg.m^2. Treat a first
`A.13` under hard decel as "fit or size up the resistor", not as a tuning
problem.

**Grounding** — the usual cause of intermittent encoder faults:

- Single-point grounding for drives and motors, **<= 100 ohm**.
- Ground-plate wires at least **3.5 mm^2**.
- The noise filter's ground wire runs straight to the ground plate, never
  daisy-chained through another device, and stays separate from its output
  lines.
- Separate high- and low-voltage runs. Keep cables short.

**Verify (no motor connected).** Energise. `POWER` (green) lights on both
drives and the panel shows a status rather than an alarm. `CHARGE` (red) lights
with main power. Power down, wait 5 minutes, confirm `CHARGE` is out.

---

## Part 6 — Drives to motors

### Power

Drive `U` -> motor `A(1)`, `V` -> `B(2)`, `W` -> `C(3)`, PE -> `D(4)`.

Phase order is not cosmetic. A swapped pair makes the drive fight its own
feedback and trips **`A.25` — motor power line U overcurrent** on the first
enable, which the manual attributes to exactly this or to mechanical seizure.

Use 1 mm^2 conductors and bond the cable shield at the drive end.

### Encoder

The `F` encoder is a **20-bit serial incremental** device, 1,048,576 P/R, so
CN2 uses the serial pinout rather than the 2500 P/R quadrature one:

| CN2 pin | Signal | Note |
| --- | --- | --- |
| 7 | `PS` | serial data |
| 8 | `/PS` | serial data |
| 9 | `PG5V` | encoder +5 V |
| 19 | `GND` | encoder 0 V |
| Shell | Shield | terminate properly |
| 17, 18 | `BAT+`, `BAT-` | **absolute encoders only — leave unused** |

Because the encoder is incremental there is **no backup battery and no battery
cable**, and both axes home on every power cycle. Absolute position retention
would require the `S` encoder option (`EMJ-04ASD22`, 17-bit absolute, 131072
P/R) and a battery on pins 17/18.

**Verify.** With the motor uncoupled from the belt, energise control power
only. No `A.10` (encoder break) or `A.22` (sensor break). Turning the shaft by
hand moves the panel's position display smoothly in both directions. A display
that jumps or freezes indicates a shield or 5 V problem, not a tuning problem.

---

## Part 7 — EtherCAT chain

On the `-EC` variant the two RJ45 jacks are the fieldbus, replacing the base
ProNet's RS-485/CAN roles:

- **`CN3` = EtherCAT IN**
- **`CN4` = EtherCAT OUT**

Daisy chain IN to OUT. No switch, no ring:

```
Pi 5 eth0 ──> CN3 [Drive X] CN4 ──> CN3 [Drive Y] CN4  (leave empty)
```

EtherCAT is direction-sensitive. An OUT-to-OUT link or a switch in the path
produces a bus that enumerates inconsistently or not at all.

**Physical order on the wire sets the chain index**: the first drive from the
host is index 0, the second is index 1. Label the drives now — Part 10 must
match.

Two further `-EC` differences worth knowing before building a loom: `CN1` is a
**20-pin** connector rather than the standard 50-pin, and it carries **5
sequence input channels** rather than 8.

**Verify.** The green `LINK/ACT` LED lights on each connected RJ45.

---

## Part 8 — Octopus wiring

All of this is conventional Klipper wiring; the only unusual part is that the X
and Y endstops serve servo axes.

| Function | Pin | Slot |
| --- | --- | --- |
| Z stepper | step `PF11`, dir `PG3`, enable `!PG5`, uart `PC6` | Driver2 |
| Z1 stepper | step `PG4`, dir `PC1`, enable `!PA2`, uart `PC7` | Driver3 |
| Extruder | step `PF9`, dir `PF10`, enable `!PG2`, uart `PF2` | Driver4 |
| X endstop | `PG6` | serves the X **servo** axis |
| Y endstop | `PG9` | serves the Y **servo** axis |
| Z endstop | `PG10` | |
| Hotend heater / thermistor | `PA0` / `PF4` | |
| Bed heater / thermistor | `PA1` / `PF3` | |
| Part cooling fan | `PA8` | |

Wire the motor coils in pairs by phase, not by wire colour. Route endstop and
thermistor wiring away from the servo motor cables — those carry PWM switching
noise.

**Verify.** With the Octopus powered over USB only and no mains on the drives,
klippy can be started against a minimal config and `QUERY_ENDSTOPS` reports all
three switches changing state when pressed.

---

## Part 9 — Drive-side EtherCAT enablement

One setting lives on the drive rather than on the bus, and the bus does nothing
until it is correct. Set it from the panel operator or ESView over the mini-USB
cable, on **both** drives:

| Parameter | Value | Meaning |
| --- | --- | --- |
| `Pn006.0` | `4` | select EtherCAT communication mode |

**Leave `Pn704` (station alias) at its default 0.** The endpoint addresses
slaves by *ring position* — it passes alias 0 to `ecrt_master_slave_config`, and
with alias 0 the position argument is the absolute position on the wire.
`ethercat_chain_index` is that position. Physical cable order is therefore the
single source of truth, and configuring aliases only adds a second one that can
disagree.

---

## Part 10 — Reading the drive identity

The endpoint matches drives on an EtherCAT vendor ID and product code. ESTUN
publishes these only in `ESTUN_ProNet_CoE.xml`, which is not a public download —
request it with the order, or read the live values off the bus:

```sh
ethercat slaves -v | grep -iE 'vendor|product'
```

**Verify.** `ethercat slaves` lists **two** slaves, in the wired order, both
reaching `PREOP`. One slave means the second drive's IN/OUT is reversed or its
cable is faulty. Zero means `Pn006.0` is not `4`, or `eth0` never reached
`ec_macb`.

---

## Part 11 — Configuration

`encoder_counts_per_rev` is the **motor's** resolution: 1048576 for the 20-bit
incremental EMJ-04AFD22. Using the 131072 of a 17-bit absolute scales every move
by 8.

```ini
[mcu]
serial: /dev/serial/by-id/usb-Klipper_stm32h723xx_...   # from Part 3

[kinematics]
type: markforged
axis_x: x
x_motors: motor_x          # lane 0 — T-belt, carries x + y
axis_y: y
y_motors: motor_y          # lane 1 — straight loop, pure y
axis_z: z
z_motors: motor_z, motor_z1

[ethercat_node node_xy]
socket: /tmp/kalico-ethercat.sock
interface: eth0
drive_profile: estun-pronet
vendor_id: 0x00000000       # <- from Part 10
product_code: 0x00000000    # <- from Part 10
cycle_us: 250

[motor motor_x]
drive: servo
protocol: ethercat
node: node_xy
ethercat_chain_index: 0     # first drive from the host
rotation_distance: 40       # set to the actual pulley
encoder_counts_per_rev: 1048576
max_torque: 300

[motor motor_y]
drive: servo
protocol: ethercat
node: node_xy
ethercat_chain_index: 1     # second drive
rotation_distance: 40
encoder_counts_per_rev: 1048576
max_torque: 300

[motor motor_z]
drive: stepper
step_pin: PF11
dir_pin: PG3
enable_pin: !PG5
rotation_distance: 8
microsteps: 16

[motor motor_z1]
drive: stepper
step_pin: PG4
dir_pin: PC1
enable_pin: !PA2
rotation_distance: 8
microsteps: 16

[axis x]
endstop_pin: PG6
position_min: 0
position_max: 300
position_endstop: 0
homing_speed: 50

[axis y]
endstop_pin: PG9
position_min: 0
position_max: 300
position_endstop: 0
homing_speed: 50

[axis z]
endstop_pin: PG10
position_max: 250

[tmc2209 motor_z]
uart_pin: PC6
run_current: 0.8

[tmc2209 motor_z1]
uart_pin: PC7
run_current: 0.8
```

`cycle_us: 250` (4 kHz) sits inside ProNet's documented 250 us - 8 ms DC range.

A Markforged Y move drives **both** motors while an X move drives only its own.
A plain `endstop_pin` works on both axes; only the **per-motor keyed** endstop
form is rejected on Y, because that form requires an axis reaching exactly one
motor lane.

**Verify.** `./scripts/ci.sh quick` is green on the branch and klippy parses the
configuration.

---

## Part 12 — Staged bring-up

Belts stay uncoupled until the final step.

1. **Stub endpoint, drives off.** Point `endpoint:` at
   `rust/target/release/ethercat-rt-stub` and start klippy. It must reach
   `ready`. This proves planner -> bridge -> transport with zero hardware risk.
2. **Real endpoint, motors uncoupled.** Switch `endpoint:` back. klippy spawns
   the endpoint itself at claim time; it is never launched by hand. Expect
   `ready` and a log line naming the profile and matched identity.
3. **Torque on, no motion.** Both drives reach Operation Enabled and hold
   position. `engine_state` stays running and never reaches `Fault (3)`.
4. **Small supervised jog.** `SET_KINEMATIC_POSITION`, then short `G1 X…` and
   `G1 Y…` moves. An X move turns **one** motor; a Y move turns **both**. Seeing
   that is the cheapest confirmation the kinematics matches the mechanics.
5. **Check the coupling sign.** With belts slack, hold the X motor still and
   move the gantry to +Y. A carriage sliding **-X** confirms the default
   `MARKFORGED_Y_COUPLING = 1.0`. A carriage sliding **+X** means flipping that
   constant to `-1.0` in `rust/motion-core/src/kinematics.rs` and the mirror in
   `klippy/motion_kinematics.py`. A wrong sign turns a commanded X move into a
   diagonal.
6. **Home Z and the extruder** as on any stepper machine.
7. **Couple the belts and home slowly.** Low `homing_speed`, hand on the power.

---

## Part 13 — Closed-loop tuning

ESTUN exposes its tuning parameters in the manufacturer object area at
`0x3xxx`, reachable through `params:` blocks or `SERVO_PARAM`:

| CoE index | Parameter | Meaning |
| --- | --- | --- |
| `0x3011.0` | Pn101 | machine rigidity |
| `0x3012.0` | Pn102 | speed loop gain (rad/s) |
| `0x3013.0` | Pn103 | speed loop integral time (0.1 ms) |
| `0x3014.0` | Pn104 | **position loop gain (1/s)** |
| `0x3015.0` | Pn105 | torque reference filter (0.01 ms) |
| `0x3016.0` | Pn106 | load inertia ratio (%) |
| `0x301C.0` | Pn112 | position feedforward (%) |
| `0x301E.0` | Pn114 | torque feedforward (%) |
| `0x3068.0` | Pn401 | forward torque limit (%) |
| `0x3069.0` | Pn402 | reverse torque limit (%) |

Order of work: establish the load inertia ratio (Pn106) first, raise the speed
loop gain (Pn102) until the axis is stiff without audible ringing, then the
position loop gain (Pn104), then add feedforward.

ESTUN's feedforward percentages run **0-100**. The A6-EC's bench-measured
feedforward calibration does not transfer.

Notch filters for mechanical resonances are Pn407/Pn408 (filter 1) and
Pn409/Pn410 (filter 2).

---

## Fault quick reference

| Code | Meaning | First thing to check |
| --- | --- | --- |
| `A.70` | EtherCAT sync error / SYNC0 missed | RT scheduling: `SCHED_FIFO` on the isolated core |
| `A.71` | comms chip internal error | drive firmware or hardware |
| `ERR` | EtherCAT init timeout | `Pn006.0 = 4`? cabling IN/OUT? |
| `A.13` | overvoltage | regenerative capacity — external resistor on `B1`/`B2` |
| `A.06` | position error pulse overflow | `Pn504`; also a phase-order or tuning symptom |
| `A.25` | motor line U overcurrent | U/V/W phase order, or mechanical seizure |
| `A.10` / `A.22` | encoder / sensor break | CN2 wiring, shield, 5 V |
| `rc=-2` | no slave matched | vendor/product identity, not necessarily the cable |

`rc=-2` deserves emphasis: a drive that is present but of a different identity
looks **exactly** like an absent one to the master. The endpoint names the
profile and identity it matched on, so read that line before suspecting wiring.

## Still unverified on hardware

None of the following has run on a real ProNet:

- The ESTUN vendor ID and product code (no public ESI).
- The DC `AssignActivate` word: the `estun-pronet` profile reuses the A6-EC's
  `0x0300`, which the ESI may contradict.
- The Markforged belt coupling sign.

## See also

- [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) — host kernel
  and EtherCAT master build.
- [`ethercat-bench-bringup.md`](ethercat-bench-bringup.md) — drive profiles, SDO
  parameters, telemetry capture, and the real-time scheduling rules in depth.
