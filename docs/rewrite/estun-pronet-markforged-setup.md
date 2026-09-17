# ESTUN ProNet EtherCAT servo setup (Markforged, two drives)

Physical and electrical bring-up for a Markforged gantry driven by two
**ProNet-04AEG-EC** drives and two **EMJ-04AFD22** motors on single-phase
230 VAC, from mains terminal to a homing axis.

This is the wiring and first-power layer. It hands off to:

- [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) — building the
  PREEMPT_RT kernel and the IgH master on the host.
- [`ethercat-bench-bringup.md`](ethercat-bench-bringup.md) — klippy config,
  drive profiles, SDO parameters, and the RT scheduling rules.

Work the stages in order. Each ends in a **Verify** gate; do not carry a failed
gate forward, because every later symptom looks like the same "drive not
responding" error.

> **Before anything is energised.** The bus capacitor stays charged after power
> is removed — wait **5 minutes** before touching terminals. Never plug or
> unplug a drive connector with power on. Both are from the manual's safety
> section, and both destroy hardware rather than merely inconveniencing you.

---

## What you are building

```
   230 VAC 1-ph ──┬── breaker ── surge ── filter ── contactor ──┬── Drive X (L1/L2, L1C/L2C)
                  │                                             └── Drive Y (L1/L2, L1C/L2C)
                  └── PE ── ground plate (single point, <=100 ohm)

   Drive X ── U/V/W/PE ──> Motor X (T-belt)      CN2 ── encoder cable ──> Motor X encoder
   Drive Y ── U/V/W/PE ──> Motor Y (straight)    CN2 ── encoder cable ──> Motor Y encoder

   Host (Pi 5) eth0 ──> [CN3 IN] Drive X [CN4 OUT] ──> [CN3 IN] Drive Y [CN4 OUT] (empty)
```

Lane assignment follows the Markforged kinematics: **lane 0 is the X motor on
the T-shaped belt** (it carries `x + y`), **lane 1 is the Y motor on the
straight frame loop** (pure `y`). Chain index must match — see Stage 6.

## Bill of materials

| Item | Part / spec | Notes |
| --- | --- | --- |
| Drives | 2x ProNet-04AEG-EC | `E` control mode and `-EC` are both required for EtherCAT |
| Motors | 2x EMJ-04AFD22 | 400 W, 1.27 N.m rated / 3.82 N.m peak, 3000 rpm (4500 max), 2.7 Arms |
| Encoder cable | **PBP** series | `PBP` = incremental, `PDP` = absolute, `PRP` = resolver. The `F` encoder is **incremental** — a PDP cable is the wrong part |
| Motor power cable | PDM-GD12-XX | or self-made at **1 mm^2** (0.05-1 kW band) |
| EtherCAT cable | Cat5 or better, shielded | 100BASE-TX; one host-to-drive plus one drive-to-drive |
| Debug cable | **mini-USB**, double shielded with ferrites | the EC-bus variant uses mini-USB, not the RS-485/RJ45 of the base ProNet |
| Host | Raspberry Pi 5, Debian 13 trixie | see the IgH install doc |
| Supply | >= 1.8 kVA at 230 V (~8 A) | 0.9 kVA per drive |

---

## Stage 1 — Mains to the drives

Both drives take single-phase **200-230 VAC +10% / -15%, 50/60 Hz**. At 230 V
you sit at the top of nominal with headroom to 253 V, which is fine.

Per drive, from the single-phase wiring diagram:

| Terminal | Connect |
| --- | --- |
| `L1`, `L2` | main circuit power (single phase — `L3` unused) |
| `L1C`, `L2C` | control power, same supply |
| `+1`, `+2` | DC reactor terminals — **normally shorted**; leave the link fitted |
| `B1`, `B2`, `B3` | regenerative resistor — see below |
| PE (ground) | ground plate |

**Regeneration on this frame size.** The 200 V `A5A`-`04A` drives — yours — ship
with **no internal regenerative resistor**. The manual's instruction for this
band is to connect an external resistor, customer-supplied, **between `B1` and
`B2`**. (The `B2`-`B3` jumper that selects an internal resistor belongs to the
larger `08A`-`50A` frames and does not apply here.)

Whether you need one depends on how much kinetic energy the gantry dumps back
on deceleration. A fast Markforged gantry is exactly the case where it matters:
the symptom of insufficient regen capacity is **`A.13` overvoltage**, which the
manual notes can appear when the load inertia exceeds ~30x the rotor inertia
during acceleration. Size it against your moving mass, and treat a first `A.13`
under hard decel as "fit or increase the resistor", not as a tuning problem.

Upstream, in order from the supply: **molded-case circuit breaker -> surge
protector -> noise filter -> magnetic contactor -> drives.** Fit a surge
suppressor across the contactor's excitation coil.

Grounding is not optional and is the usual cause of intermittent encoder faults:

- **Single-point** grounding for drive and motor, **<=100 ohm**.
- Ground-plate wires at least **3.5 mm^2**.
- Keep the noise-filter ground wire separate from its output lines; run it
  straight to the ground plate, not daisy-chained through another device.
- Separate high- and low-voltage runs; keep cables short.

**Power sequencing matters and is easy to get wrong:**

- **On:** control power (`L1C`/`L2C`) first, *then* main circuit (`L1`/`L2`).
- **Off:** main circuit first, *then* control power.

**Verify (no motor connected yet).** Energise. `POWER` (green) lights on both
drives and the panel shows a status, not an alarm. `CHARGE` (red) lights with
main power and stays lit while the bus capacitor holds charge. Power down, wait
5 minutes, and confirm `CHARGE` is out before touching anything.

---

## Stage 2 — Drive to motor

### Power

Drive `U` -> motor `A(1)`, `V` -> `B(2)`, `W` -> `C(3)`, PE -> `D(4)`.

Phase order is not cosmetic: a swapped pair makes the drive fight its own
feedback and trips *Motor power line U over current* (`A.25`) on the first
enable, which the manual attributes to exactly this or to mechanical seizure.

Use 1 mm^2 conductors and bond the cable shield at the drive end.

### Encoder

The `F` encoder is a **20-bit serial incremental** device (1,048,576 P/R), so
CN2 uses the serial pinout, not the 2500 P/R quadrature one:

| CN2 pin | Signal | Note |
| --- | --- | --- |
| 7 | `PS` | serial data |
| 8 | `/PS` | serial data |
| 9 | `PG5V` | encoder +5 V |
| 19 | `GND` | encoder 0 V |
| Shell | Shield | terminate properly |
| 17, 18 | `BAT+`, `BAT-` | **absolute encoders only — leave unused** |

Because the encoder is incremental there is **no backup battery and no battery
cable**, and the axis must home on every power cycle. If you were expecting
absolute position retention, that needs the `S` encoder option
(`EMJ-04ASD22`, 17-bit absolute, 131072 P/R) and a battery in CN2 pins 17/18.

**Verify.** With the motor unpowered and uncoupled from the belt, energise
control power only. No `A.10` (encoder break) or `A.22` (sensor break). Turn the
shaft by hand and confirm the panel's position display moves smoothly in both
directions — a display that jumps or freezes is a shield or 5 V problem, not a
tuning problem.

---

## Stage 3 — EtherCAT chain

On the `-EC` variant the two RJ45 jacks are the fieldbus, replacing the base
ProNet's RS-485/CAN roles:

- **`CN3` = EtherCAT IN**
- **`CN4` = EtherCAT OUT**

Daisy chain, IN to OUT, no switch and no ring:

```
Host eth0 ──> CN3 [Drive X] CN4 ──> CN3 [Drive Y] CN4  (leave empty)
```

100BASE-TX over Cat5 twisted pair. EtherCAT is direction-sensitive — an
OUT-to-OUT or a switch in the path gives you a bus that enumerates
inconsistently or not at all.

Physical order on the wire sets the **chain index**: the first drive from the
host is index 0, the next is 1. Decide now which physical drive is X and label
it, because Stage 6 has to match.

Two more EC-variant differences worth knowing before you plan endstop wiring:
`CN1` is a **20-pin** connector (not the standard 50-pin), and it carries
**5 sequence input channels** (not 8).

**Verify.** With drives powered and the host up, the green `LINK/ACT` LED lights
on each connected RJ45. Full bus verification happens in Stage 5 once the master
is running.

---

## Stage 4 — Host

The recommended host is a **Raspberry Pi 5 on Debian 13 trixie** with a
PREEMPT_RT kernel, the IgH master, and the native `ec_macb` driver.

Follow [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) end to
end. Its requirements that most often bite:

- **`eth0` is given entirely to the EtherCAT master and gets no IP.** Put SSH
  and LAN on Wi-Fi or a second NIC. Check with `ip route get 1.1.1.1` — it must
  not leave via `eth0`.
- An **isolated CPU core** on the kernel cmdline for the DC loop to pin to.
- The systemd drop-in granting the endpoint `CAP_SYS_NICE` and `CAP_IPC_LOCK`.

The RT requirement is not best-effort. A DC loop that misses SYNC0 makes the
drive latch **`A.70` — "EtherCAT synchronous error: the cycle the master set is
not correct, or SYNC0 has not kept up"**. That is ProNet's equivalent of the
A6-EC `ErC1.1` trap, and it has the same signature: fine on a warm idle bench,
faults under cold-boot load.

**Verify.** `/dev/EtherCAT0` exists, `ethercat master` reports the master up and
linked, and a **cold reboot** (not a warm restart) leaves it healthy.

---

## Stage 5 — Drive-side EtherCAT enablement, and reading the identity

One setting lives on the drive, not on the bus, and the bus does nothing until
it is right. Set it from the panel operator or ESView over the mini-USB cable,
on **both** drives:

| Parameter | Value | Meaning |
| --- | --- | --- |
| `Pn006.0` | `4` | select EtherCAT communication mode |

**Leave `Pn704` (station alias) at its default 0.** The endpoint addresses
slaves by *ring position* — it passes alias 0 to `ecrt_master_slave_config`, and
with alias 0 the position argument is the absolute position on the wire. Your
`ethercat_chain_index` is that position. Physical cable order is therefore the
only thing that decides which drive is which, and configuring aliases buys
nothing here while adding a second, disagreeing source of truth.

Now read the identity the endpoint must match. ESTUN publishes it only in
`ESTUN_ProNet_CoE.xml`, which is not a public download — request it with the
order, or take the values straight off the live bus:

```sh
ethercat slaves -v | grep -iE 'vendor|product|alias'
```

**Verify.** `ethercat slaves` lists **two** slaves in the physical order you
wired them, both reaching `PREOP`. One slave means the second drive's IN/OUT is
reversed or its cable is bad. Zero means `Pn006.0` is not `4`, or `eth0` never
reached `ec_macb`.

---

## Stage 6 — klippy configuration

Fill in the identity from Stage 5. `encoder_counts_per_rev` is the **motor's**
resolution — 1048576 for the 20-bit incremental EMJ-04AFD22. Using the 131072 of
a 17-bit absolute scales every move by 8.

```ini
[kinematics]
type: markforged
axis_x: x
x_motors: motor_x          # lane 0 — T-belt, carries x + y
axis_y: y
y_motors: motor_y          # lane 1 — straight loop, pure y
axis_z: z
z_motors: motor_z

[ethercat_node node_xy]
socket: /tmp/kalico-ethercat.sock
interface: eth0
drive_profile: estun-pronet
vendor_id: 0x00000000       # <- from `ethercat slaves -v`
product_code: 0x00000000    # <- from `ethercat slaves -v`
cycle_us: 250

[motor motor_x]
drive: servo
protocol: ethercat
node: node_xy
ethercat_chain_index: 0     # first drive from the host
rotation_distance: 40       # your pulley
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
```

`cycle_us: 250` (4 kHz) is inside ProNet's documented 250 us - 8 ms DC range.

Markforged homing asymmetry: a Y move drives **both** motors, an X move drives
only its own. Y therefore cannot take a per-motor `endstop_pin` and the config
rejects it; X can.

**Verify.** `./scripts/ci.sh quick` green on the branch, and klippy parses the
config without reaching the drives yet.

---

## Stage 7 — First power-on, staged

Do these in order, belts **off** until the last step.

1. **Stub first, no drives.** Point `endpoint:` at
   `rust/target/release/ethercat-rt-stub` and start klippy. It must reach
   `ready`. This proves planner -> bridge -> transport with zero hardware risk.
   See "Stub validation" in the bring-up doc.
2. **Real endpoint, motors uncoupled.** Switch `endpoint:` back. klippy spawns
   the endpoint at claim time — you never launch it. Expect `ready` and a log
   line naming the profile and identity it matched.
3. **Torque on, no motion.** Confirm both drives reach Operation Enabled and
   hold position. `engine_state` stays running, never `Fault (3)`.
4. **Small supervised jog, uncoupled.** `SET_KINEMATIC_POSITION`, then a short
   `G1 X…` and `G1 Y…`. Watch that an X move turns **one** motor and a Y move
   turns **both** — that is the Markforged coupling, and seeing it is the
   cheapest confirmation the kinematics matches the mechanics.
5. **Check the coupling sign.** Still uncoupled or with belts slack: hold the X
   motor and move the gantry to +Y. If the carriage slides **-X**, the default
   `MARKFORGED_Y_COUPLING = 1.0` is right. If it slides **+X**, flip that
   constant to `-1.0` in `rust/motion-core/src/kinematics.rs` and the mirror in
   `klippy/motion_kinematics.py`. A wrong sign turns a commanded X move into a
   diagonal.
6. **Couple the belts. Home slowly.** Low `homing_speed`, hand on the power.

---

## Fault quick reference

| Code | Meaning | First thing to check |
| --- | --- | --- |
| `A.70` | EtherCAT sync error / SYNC0 missed | RT scheduling: `SCHED_FIFO` on the isolated core |
| `A.71` | comms chip internal error | drive firmware / hardware |
| `ERR` | EtherCAT init timeout | `Pn006.0 = 4`? cabling IN/OUT? |
| `A.06` | position error pulse overflow | `Pn504`; also a phase-order or tuning symptom |
| `A.25` | motor line U overcurrent | U/V/W phase order, or mechanical seizure |
| `A.13` | overvoltage | regenerative capacity — external resistor on `B1`/`B2` |
| `A.10` / `A.22` | encoder / sensor break | CN2 wiring, shield, 5 V |
| `rc=-2` | no slave matched | vendor/product identity, not necessarily the cable |

`rc=-2` deserves emphasis: a drive that is present but of a different identity
looks **exactly** like an absent one to the master. The endpoint names the
profile and identity it matched on, so read that line before suspecting wiring.

## Still unverified on hardware

Carried forward honestly — none of this has run on a real ProNet:

- The ESTUN vendor ID and product code (no public ESI).
- The DC `AssignActivate` word: the `estun-pronet` profile reuses the A6-EC's
  `0x0300`, which the ESI may contradict.
- The Markforged belt coupling sign.
