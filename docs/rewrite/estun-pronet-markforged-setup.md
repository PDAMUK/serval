# Markforged servo build: ESTUN ProNet + BTT Manta M8P V2

A complete build-up from a mechanically assembled but electrically bare
printer to a homing, tuned Markforged machine.

**Starting point.** The frame, gantry, belts and bed are built. Nothing
electrical is fitted: no stepper drivers in the mainboard, no servos mounted,
no endstops, and none of the wiring for any of it.

**Finishing point.** X and Y driven by EtherCAT servos under closed-loop
control, Z and the extruder on TMC steppers, all axes homing, drives tuned.

## Before anything else

These drives run on **230 VAC mains**, and their DC bus stays charged after the
supply is removed. Every drive has a `CHARGE` lamp for exactly this reason.

- Isolate at the breaker before touching drive terminals or motor leads.
- After powering down, **wait five minutes and confirm `CHARGE` is out** before
  working. The lamp, not the clock, is the authority.
- Wire motors with the drives isolated. Part 5 ends powered down for that
  reason, and Part 6 assumes it.
- Nothing in this guide needs a drive opened. If a step seems to, stop.

Mains wiring is notifiable work in some jurisdictions. This document describes
what to connect, not who is competent to connect it.

## Hardware this targets

| Role | Part |
| --- | --- |
| X, Y motors | 2x ESTUN ProNet-04AEG-EC drive + EMJ-04AFD22 motor |
| Z | one TMC2209 stepper in the mainboard |
| Extruder | two TMC2209 steppers, driven in tandem as one axis |
| Mainboard | BigTreeTech Manta M8P V2.0 (**STM32H723ZET6**, 8 driver slots) |
| Host | BTT CB2 compute module in the Manta's BTB socket |
| Servo supply | single-phase 230 VAC, >= 1.8 kVA |

The Manta carries the host on the board itself, so there is no separate SBC.
That is convenient for everything except EtherCAT — see
[The EtherCAT host problem](#the-ethercat-host-problem) below, which needs
settling before the servo wiring is worth starting.

## Architecture, and why steppers remain

The servos replace the X and Y **steppers only**. Everything else on the
printer stays conventional:

```
   ┌──────────────── Manta M8P V2 ────────────────┐
   │  CB2 module ── klippy + ethercat-rt endpoint │
   │      │                                       │
   │      │ (on-board link)                       │
   │  STM32H723 ── Motor3 TMC2209 ──> Z stepper   │
   │      │        Motor5 TMC2209 ──> extruder A  │
   │      │        Motor6 TMC2209 ──> extruder B  │
   │      └── endstops PF4 / PF3 / PF2, heaters, fans
   │  Motor1, Motor2 slots: EMPTY (X/Y are servos)│
   └───────────────────┬──────────────────────────┘
                       │ eth0
          [CN3] ProNet X [CN4] ──> [CN3] ProNet Y [CN4]
                │                        │
            EMJ motor X               EMJ motor Y
            (T-shaped belt)           (straight loop)
```

Mixed drive types are supported per **lane**: a lane's motors must all be the
same type, but different lanes may differ. X and Y are servo lanes, Z is a
stepper lane, and the extruder is a follower axis carrying **two** steppers
that always move together. This is the configuration the repository describes
as "industrial servo on X, steppers elsewhere".

The Manta also carries the **endstops for the servo axes**. A servo axis homes
against a GPIO endstop on any bridge MCU, so the X and Y switches land on the
mainboard exactly like a stepper machine's would.

## Coming from steppers: what is actually different

Nothing below assumes prior servo experience, but a handful of ideas make the
rest read much more easily. Anyone who has built a Klipper printer already knows
most of the machine; these are the parts that are genuinely new.

**A servo knows where it is; a stepper assumes.** A stepper is told "take 200
steps" and is trusted to have done it. A servo has an encoder on the motor
shaft, so the drive compares where it was told to go against where it actually
is, every cycle, and applies whatever current closes the gap. Skipped steps stop
being a failure mode. A jam or a crash becomes one, because the drive will push
harder rather than slip — which is why torque limits and supervised first moves
matter far more than on a stepper machine.

**The drive is a separate computer.** Each ProNet is its own controller with its
own parameters, its own faults and its own front panel. Klipper does not manage
it the way it manages a TMC2209. Parameters live in the drive, faults latch in
the drive, and some of them survive a host reboot — clearing those needs a drive
power cycle, not a `FIRMWARE_RESTART`.

**EtherCAT is the wire between them**, and it is hard real-time. Every cycle —
250 microseconds here, 4000 times a second — the host sends each drive a new
target position and reads back where it is. This is why the host needs a
real-time kernel and an isolated CPU core: not for throughput, but because a
frame that arrives *late* is a fault, not a delay.

**Distributed clocks (DC) and SYNC0.** All drives on the bus share one clock, so
they act on their targets at the same instant rather than whenever a frame
happens to land. SYNC0 is the pulse that marks that instant. If the host misses
it, the drive decides the master has lost the plot and latches
`A.70`. Most first-bring-up trouble is some version of this.

**Following error** is commanded position minus actual position. A healthy axis
has a small, steady one. A growing one means the machine is fighting something,
and the drive trips out rather than forcing through it.

**Torque limit** is how hard the drive is allowed to push, as a percentage of
the motor's rating. Keep it low during first moves.

**A few acronyms appear in drive documentation and in fault messages:**

| Term | Meaning |
| --- | --- |
| CiA 402 | the standard vocabulary drives speak for position, velocity and torque |
| CoE | that vocabulary carried over EtherCAT |
| PDO | data exchanged *every cycle* — target position, actual position, torque |
| SDO | occasional settings, sent once at startup or when a parameter changes |
| CSP | Cyclic Synchronous Position — the mode where the host streams positions, which is what this build uses |
| PREOP / SAFEOP / OP | the bus startup states a drive walks through; `OP` is running |
| ESI | the XML file describing a drive, published by its maker |

**Homing still happens.** These motors have incremental encoders, so the drive
knows its position relative to where it powered on, not where the machine's
origin is. Every axis homes against a switch on each power-up, exactly like a
stepper machine.

## The EtherCAT host problem

The endpoint's DC loop needs a **native** EtherCAT NIC driver. IgH's `generic`
driver pushes every frame through the Linux net stack, and that jitter is what
makes a drive miss SYNC0 and latch `A.70`.

The CB2 is a Rockchip **RK3566**, whose GbE is a Synopsys DesignWare MAC driven
by `stmmac`/`rk_gmac-dwmac`. IgH ships native drivers for `e1000e`, `igb`,
`r8169`, `genet` and `macb` — **none of which match it**. The `ec_macb` driver
in the host install guide is specific to the Pi 5's RP1 Cadence GEM and does not
apply here. A Raspberry Pi CM4 in the same socket does not help either: its
GENET MAC has no native IgH driver.

Three ways forward, in increasing order of risk:

1. **A separate Raspberry Pi 5 as the EtherCAT host**, with the Manta as a plain
   USB-attached MCU. This is the only path the repository has actually
   exercised, and the right choice for a first build. The CB2 is not wasted —
   it can still run the printer.
2. **Run the endpoint on the CB2 with `ec_dwmac-rk`**, following
   [`ethercat-host-cb2-rk3566.md`](ethercat-host-cb2-rk3566.md). The driver
   builds and its symbols resolve, but it has never been loaded on hardware.
3. **Accept `ec_generic`** and expect sync faults under load.

Everything below assumes one of these is settled. The wiring, firmware and
configuration are identical either way; only which machine runs the endpoint
changes.

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
| TMC2209 drivers | 3x (Z, extruder A, extruder B) | **Motor1 and Motor2 stay empty** — X/Y are servos |
| Encoder cable | ESTUN **PBP** series | `PBP` = incremental. The `F` encoder is incremental; a `PDP` (absolute) cable is the wrong part |
| Motor power cable | PDM-GD12-XX, or 1 mm^2 self-made | 1 mm^2 covers the 0.05-1 kW band |
| EtherCAT cable | 2x shielded Cat5 or better | 100BASE-TX |
| Drive debug cable | **mini-USB**, double shielded with ferrites | the `-EC` variant uses mini-USB, not the base drive's RS-485 |
| Mains parts | isolator, MCB, RCBO, SPD, EMC filter, contactor, coil snubber | specified with ratings and examples in **Part 5** — buy from that table, not this row |
| Regen resistor | external, sized to the gantry | see Part 5 — this frame size has no internal resistor |
| Endstop switches | 3x (X, Y, Z) | wired to the Manta |

---

## Part 2 — Host

Whichever machine runs the endpoint needs a PREEMPT_RT kernel, the IgH master,
and a **native** NIC driver for its own Ethernet controller — `ec_macb` on a
Pi 5, `ec_dwmac` on the CB2.

Follow the document matching the host **before wiring anything**:

- **Raspberry Pi 5** —
  [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md). Exercised on
  the bench; the path to use for a first build.
- **BTT CB2** — [`ethercat-host-cb2-rk3566.md`](ethercat-host-cb2-rk3566.md).
  Builds, never run.

Follow one or the other, not both: they need different kernels and different
NIC drivers. Three requirements common to both cause most failures:

- **`eth0` is given entirely to the EtherCAT master and receives no IP
  address.** SSH and LAN must live on Wi-Fi or a second NIC. Confirm with
  `ip route get 1.1.1.1` — the route must not leave via `eth0`. The CB2's
  dual-band Wi-Fi covers this.
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

## Part 3 — Firmware for the Manta

Build on the host, in the repository:

```sh
make menuconfig
```

Settings, taken from the board's own published Klipper config header:

| Option | Value |
| --- | --- |
| Micro-controller | STM32H723 |
| Bootloader offset | **128 KiB** (`0x8020000`) |
| Clock reference | **25 MHz crystal** |
| Communication | USB (PA11/PA12) |

Make the Communication choice in menuconfig rather than copying a `.config`
from the repository. `test/configs/stm32h723.config` carries the same MCU,
25 MHz reference and 128 KiB offset, but it is a firmware **build-matrix**
fixture, not a board config: it selects `CONFIG_SERIAL` — a hardware UART — and
never sets `CONFIG_USBSERIAL`. Copied to `.config` it produces a board that
never appears under `/dev/serial/by-id/`, and the `CONFIG_STM32_USB_PA11_PA12`
line in it is inert without USB selected, so it reads as though USB were
configured when it is not.

Then:

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

Power off the Manta completely.

The Manta has eight slots, Motor1 through Motor8. This build uses three:

| Slot | Driver | Purpose |
| --- | --- | --- |
| Motor1 | **empty** | X is an EtherCAT servo |
| Motor2 | **empty** | Y is an EtherCAT servo |
| Motor3 | TMC2209 | Z (single stepper) |
| Motor5 | TMC2209 | extruder A |
| Motor6 | TMC2209 | extruder B |
| Motor4, 7, 8 | **empty** | unused |

Set every fitted TMC2209 for **UART mode** per the driver documentation, seat it
in the correct orientation, and fit its heatsink. A reversed driver is destroyed
on power-up.

Leaving Motor1 and Motor2 empty is deliberate: those lanes have no stepper to
drive, and the pins that would serve them are simply unused. Their **endstop
inputs are still used** — the servo axes home on them.

**Verify.** Visual check of orientation on all three, before power.

---

## Part 5 — Mains and drive power

Each ProNet-04AEG-EC takes single-phase **200-230 VAC +10% / -15%, 50/60 Hz**.
At 230 V the supply sits at the top of nominal with headroom to 253 V. Budget
**0.9 kVA per drive** — about 8 A at 230 V for the pair.

### The chain, in order

Seven things between the wall and the drives. The order is not arbitrary —
each one either protects what follows it or has to sit somewhere specific to
work at all.

| # | Device | Why it is there | Where it must sit |
| --- | --- | --- | --- |
| 1 | **Isolator** (switch-disconnector, lockable) | The lock-off point. Everything downstream can be made dead and *proved* dead by one person holding the key | First thing inside the enclosure, on the incoming cable |
| 2 | **MCB**, 16 A Type C | Overcurrent and short-circuit protection | Immediately after the isolator |
| 3 | **RCD or RCBO**, 30 mA Type A | Earth-fault protection. Read the note below before buying — drives break the usual assumptions | With, or immediately after, the MCB |
| 4 | **Surge protection device**, Type 2 — optional, see below | Clamps mains transients that otherwise reach the drives' rectifiers | At the panel entry, as close to the origin as the wiring allows; its own leads as short and straight as possible |
| 5 | **EMC / noise filter**, ≥ 10 A | Keeps drive switching noise off the supply, and mains noise out of the encoder feedback | **Directly beside the drives**, bolted metal-to-metal to the backplate. A filter on a long lead filters almost nothing |
| 6 | **Contactor**, ≥ 20 A AC-1, 230 V coil | The thing an emergency stop actually opens. Without it there is no way to drop drive power except pulling the isolator by hand | Last device before the drives |
| 7 | **Drives** | | |

Two placement rules carry most of the benefit and are the two most often got
wrong: the **filter belongs at the drives, not at the panel entry**, bonded to
bare metal rather than through a painted panel or a wire; and the **SPD's leads
must be short**, because its clamping voltage is what it lets through plus the
inductive kick of its own tails.

Fit a surge suppressor across the contactor's coil — an RC snubber for an AC
coil. Without it the coil's collapse on de-energising is a sharp transient
directly alongside the encoder wiring. It is not structurally required, which
is why it appears under *optional* below, but it is a component solving a
fault that is expensive to diagnose.

### Earth leakage, and why a normal RCD is the wrong one

Servo drives leak current to earth by design. The EMC filter's Y-capacitors
connect line to earth, and that path carries current continuously, before any
fault.

This is not a vague caution — filter datasheets state it. A Roxburgh `DRF10`
is specified at **1.46 mA maximum leakage**. That is the filter alone, and the
drives carry their own internal filters on top. A 30 mA RCD is required to trip
between 15 and 30 mA, so the usable budget is 15 mA, and a few milliamps of
standing leakage before the machine has done anything is a real fraction of it.
Add a PSU, a bed heater and anything else sharing the circuit and the margin is
smaller than it looks.

Worse, the leakage is not a clean sine wave. A rectifier ahead of the DC bus
gives it a DC component, and a **Type AC RCD cannot see DC residual current at
all** — it can be blinded by exactly the fault it is fitted to catch.

For single-phase drives like these, **Type A is the minimum** and what IEC
61800-5-1 expects of a two-pulse rectifier. Type AC is not acceptable. If the
same board ever feeds anything with a three-phase rectifier, that becomes
Type B.

If the 30 mA device nuisance-trips on power-up, the answer is **not** a bigger
threshold chosen by trial. It is either a dedicated 300 mA time-delayed device
for the drive circuit with 30 mA kept for anything a person touches, or a
genuine earth fault that has just been found. Measuring the standing leakage
with a clamp meter distinguishes the two in a minute.

### What to buy

Specifications first: those are arithmetic from this machine's 7.8 A and hold
whoever supplies the parts. The named parts are illustrations of the right
class, not a validated bill of materials — availability moves, and the drive
manual and local wiring regulations both outrank this table. RS stock numbers
are quoted because they pin one specific part down; any distributor's
equivalent is the same purchase.

**Needed.** Leaving any of these out makes the machine either unsafe or noisy
enough to corrupt encoder feedback.

| Item | Specification | Part, and RS stock no. |
| --- | --- | --- |
| Isolator | 2-pole, >= 16 A, lockable in the OFF position; IP65 if it mounts through the enclosure wall rather than sitting on the rail behind a door | ABB `SD202/32` — 2-pole, 32 A, DIN, padlockable — RS **175-5085** |
| MCB | 16 A, **Type C**, 6 kA. One pole breaking line is enough here — the isolator and the RCD are both 2-pole, so the double-pole break exists | ABB `S201-C16` — 1 pole, 1 module — RS **489-0447** |
| RCD | 2-pole, 30 mA, **Type A** | ABB `F202 A-25/0.03` — 25 A, 2 pole, 2 modules — RS **232-0339** |
| EMC filter | Single phase, 250 VAC, **>= 10 A** | Roxburgh/Deltron `DRF10` — DIN rail, screw terminals, 1.46 mA max leakage — RS **761-5696** |
| Contactor | 2 pole, >= 20 A AC-1, **230 VAC coil** | ABB `ESB20-20N-06` — modular, 35 mm — RS **211-1482** |
| Mains cable, supply to drives | 1.5 mm^2 is adequate at 7.8 A; **2.5 mm^2** for volt-drop margin on a run over a couple of metres | 3-core flexible, 300/500 V |
| Protective earth | ESTUN specifies **3.5 mm^2**, a JIS size with no IEC equivalent — use **4 mm^2** | Green/yellow, ring-terminated to the plate |
| Regen resistor | Take the **minimum resistance** from the drive manual — see the note below | — |

**One part instead of two.** An RCBO is an MCB and an RCD in one device, and is
the only combination on this list worth making.

| Item | Replaces | Part, and RS stock no. |
| --- | --- | --- |
| RCBO | the MCB **and** the RCD | ABB `DSE201 M C16 A30` — 16 A Type C curve, 30 mA Type A earth leakage, 36 mm — RS **136-7786** |
| RCBO, narrower | the MCB **and** the RCD | Siemens `5SV1316-7KK16` — 16 A Type C curve, 30 mA Type A, 6 kA, in a single 18 mm module — RS **187-3289** |

What it buys is rail width, not money: separate parts are one module for the
MCB plus two for the RCD, about 53 mm, against 36 mm for the ABB and 18 mm for
the Siemens. Check the earth-leakage type on the datasheet and not on the
listing — distributors routinely print the *curve* letter (C) in the field
meaning the *RCD* type, and a Type AC device in that slot is the one failure
mode the section above is about.

**Optional.** Each of these is defensible to leave out, for a stated reason.

| Item | Specification | Part, and RS stock no. | When to skip it |
| --- | --- | --- | --- |
| SPD | Type 2, 230 V, L-N and N-PE modes | Schneider `A9L20500` iPRD20 — 1P+N, 20 kA, 1.4 kV — RS **065-4748** | If the board feeding the machine already carries a Type 2 SPD, this one is a second line of defence, not the first. It also costs more than the rest of the chain together |
| Coil suppressor | RC snubber matched to the coil | 100 ohm / 0.1 uF across the coil terminals; Schneider `LAD4RCU` for an LC1D-class coil | Only if the contactor sits well away from the encoder and EtherCAT runs. In a printer enclosure it does not, so fit it |
| Chassis EMC filter | Single phase, 250 VAC, >= 10 A | Schaffner `FN2090Z-10-06` — RS **708-4294** | Skip it by default. It replaces the `DRF10` rather than adding to it, and only earns its 113.5 x 57.5 x 45.4 mm if the `DRF10` is bonded correctly at the drives and noise still reaches the encoder |

### Fitting it in a printer enclosure

An industrial panel has room to spare and a printer does not, so it is worth
choosing for size deliberately rather than discovering it at assembly.

Keep the whole chain on **one 35 mm DIN rail**. Every device above exists in a
DIN form, and a rail costs a few millimetres over loose parts while making the
wiring shorter, the earthing a single bonded path, and the whole assembly
removable as a unit. Module widths run 17.5-18 mm; count modules rather than
millimetres when planning the rail, and add one spare module because something
always follows.

Three choices save the most space:

- **A DIN-rail filter rather than a chassis one.** The `FN2090` is a good
  filter and 113.5 mm long, which is most of a small enclosure's width for one
  part. A `DRF10` sits on the rail with everything else.
- **A modular installation contactor rather than a control contactor.** An
  `ESB20-20` is 35 mm wide and shallow; an `LC1D09` is wider, much deeper, and
  built for motor starting duty this circuit does not have.
- **One RCBO rather than a separate MCB and RCD.** Three modules become two,
  or one if the 18 mm device is available.

The filter's placement rule still stands, and it pulls against the rail: it
wants to be at the drives, not at the enclosure's edge. In a printer these are
usually within a few hundred millimetres of each other, so a rail sited near
the drives satisfies both. What must not happen is a filter at the incoming
gland with a metre of unfiltered cable running past the encoder leads to reach
the drives.

One trade-off to make knowingly. A modular contactor drops power when the
emergency stop opens its coil, which is what this circuit needs. It is not a
safety contactor: no mirrored contacts, no monitoring, nothing that detects a
welded pole. An industrial machine would use a safety relay and a contactor
with mirror contacts, and a printer on a bench generally does not. That is a
defensible choice, but it should be a choice.

**The 16 A rating is not about the 7.8 A load.** At 16 A the drives sit at
under half the breaker's rating, which looks generous until the inrush is
considered: energising two DC buses charges their capacitors through the
rectifiers, and that transient is tens of amps for a few milliseconds. Type C
trips instantaneously at 5-10× rating, so a 16 A Type C tolerates 80-160 A for
that instant. A 10 A Type B would trip on the *first* power-up, every time, and
look like a fault in the drives.

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

Sizing has two independent numbers and they fail in opposite directions:

- **Resistance** has a *minimum*, set by the drive's braking transistor and
  printed in the ProNet manual for this frame. Going below it lets the
  transistor pass more current than it is rated for, and destroys it — not a
  trip, a replacement drive. Take this figure from the manual, not from a
  calculation and not from a resistor a supplier happens to stock.
- **Wattage** has a *minimum* too, but undersizing it only cooks the resistor.
  Start at the manual's recommendation and go up if it runs hot; resistors in
  this class are cheap next to the drive they protect.

Mount it where it can dissipate — off the backplate, in free air, away from the
encoder and EtherCAT runs. It reaches temperatures that mark cable insulation.

**Grounding** — the usual cause of intermittent encoder faults:

- Single-point grounding for drives and motors, **<= 100 ohm**.
- Ground-plate wires at least **3.5 mm^2**.
- The noise filter's ground wire runs straight to the ground plate, never
  daisy-chained through another device, and stays separate from its output
  lines.
- Separate high- and low-voltage runs. Keep cables short.

**Verify (no motor connected).**

1. Before energising: the isolator locks OFF with the key out, and a meter
   across `L1`/`L2` at a drive reads zero with it locked.
2. Energise. `POWER` (green) lights on both drives and the panel shows a status
   rather than an alarm. `CHARGE` (red) lights with main power.
3. The RCD holds. A trip here is the leakage question above, not a reason to
   fit a larger one.
4. Clamp the standing earth leakage with the drives idle and write the number
   down. It is the baseline every future nuisance trip gets compared against,
   and it takes a minute now against an afternoon later.
5. Open the contactor — by the emergency stop, not by the isolator. Both drives
   must drop out. This is the one test that proves the E-stop does anything.
6. Power down, wait 5 minutes, confirm `CHARGE` is out.

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
host eth0 ──> CN3 [Drive X] CN4 ──> CN3 [Drive Y] CN4  (leave empty)
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

## Part 8 — Manta wiring

All of this is conventional Klipper wiring; the only unusual part is that the X
and Y endstops serve servo axes.

| Function | Pin | Slot |
| --- | --- | --- |
| Z stepper | step `PB8`, dir `!PB7`, enable `!PE0`, uart `PB9` | Motor3 |
| Extruder A | step `PG13`, dir `PG12`, enable `!PG15`, uart `PG14` | Motor5 |
| Extruder B | step `PG9`, dir `PD7`, enable `!PG11`, uart `PG10` | Motor6 |
| X endstop | `PF4` | serves the X **servo** axis |
| Y endstop | `PF3` | serves the Y **servo** axis |
| Z endstop | `PF2` | |
| Hotend heater / thermistor | `PA0` (HE0) / `PB0` (T0) | |
| Bed heater / thermistor | `PF5` / `PB1` (TB) | |
| Part cooling fan | `PF7` (Fan0) | |

Note `PG9`: it is the **step** pin of Motor6 on this board, unrelated to the
similarly-named pin on other boards. Pin names do not transfer between
mainboards.

Every row above is taken from BigTreeTech's own published configuration,
`V2.0/Firmware/generic-bigtreetech-manta-m8p-V2_0.cfg` in
[`bigtreetech/Manta-M8P`](https://github.com/bigtreetech/Manta-M8P) — including
the slot numbers, which **start at Motor1, not Motor0**. `PB8` is Motor3 there,
not Motor2; counting from zero puts every stepper in the wrong socket. The
three endstop pins are the ones that file uses for `stepper_x`, `stepper_y` and
`stepper_z` respectively. Check the row against that file rather than against
another board's config before plugging anything in.

Wire the motor coils in pairs by phase, not by wire colour. Route endstop and
thermistor wiring away from the servo motor cables — those carry PWM switching
noise.

**Verify.** With the Manta powered and no mains on the drives, klippy can be
started against a minimal config and `QUERY_ENDSTOPS` reports all three
switches changing state when pressed.

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

Both halves are required and both are checked at config time. A zero product
code is **not** a wildcard: the master would accept the slave configuration,
never attach it, and the run would die at the OP walk with nothing pointing
back here. So klippy refuses to start until both carry the values read off the
bus, naming whichever is still unset. Treat that refusal as the checkpoint for
this part.

**Verify.** `ethercat slaves` lists **two** slaves, in the wired order, both
reaching `PREOP`. One slave means the second drive's IN/OUT is reversed or its
cable is faulty. Zero means `Pn006.0` is not `4`, or `eth0` never reached the
host's native driver — `ec_macb` on a Pi 5, `ec_dwmac-rk` on the CB2.

---

## Part 11 — Configuration

This is the machine's `printer.cfg`, which klippy reads from
`~/printer_data/config/` on the CB2. Replace the file's contents rather than
appending: the classic `[stepper_x]` and `[printer] kinematics:` sections this
fork rejects will stop it starting. Coming from a mainline Klipper
configuration, [`Config_Migration.md`](../Config_Migration.md) covers the
conversion.

Apply it with `RESTART`, or `FIRMWARE_RESTART` after reflashing the Manta.

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
z_motors: motor_z

[ethercat_node node_xy]
socket: /tmp/kalico-ethercat.sock
interface: eth0
drive_profile: estun-pronet
vendor_id: 0x00000000       # <- replace, from Part 10
product_code: 0x00000000    # <- replace, from Part 10
cycle_us: 250
#endpoint: /home/biqu/serval/rust/target/release/ethercat-rt
#   Optional. Defaults to rust/target/release/ethercat-rt inside the
#   repository. Part 12 step 1 switches this to ethercat-rt-stub for the
#   drive-off dry run, so uncomment it at that point.

[motor motor_x]
drive: servo
protocol: ethercat
node: node_xy
ethercat_chain_index: 0     # first drive from the host
rotation_distance: 40       # set to the actual pulley
encoder_counts_per_rev: 1048576
max_torque: 100             # % of rated; see the note below before raising
following_error: 2.0        # mm; drive faults past this

[motor motor_y]
drive: servo
protocol: ethercat
node: node_xy
ethercat_chain_index: 1     # second drive
rotation_distance: 40
encoder_counts_per_rev: 1048576
max_torque: 100
following_error: 2.0

[motor motor_z]                 # Motor3
drive: stepper
step_pin: PB8
dir_pin: !PB7
enable_pin: !PE0
rotation_distance: 8
microsteps: 16

# The extruder pair. Both motors sit on one follower axis, so they are
# stepped from the same trajectory and cannot drift apart.
[motor motor_e0]                # Motor5
drive: stepper
step_pin: PG13
dir_pin: PG12
enable_pin: !PG15
rotation_distance: 33.5
microsteps: 16

[motor motor_e1]                # Motor6
drive: stepper
step_pin: PG9
dir_pin: PD7
enable_pin: !PG11
rotation_distance: 33.5
microsteps: 16

[axis e]
follows: x, y, z
motors: motor_e0, motor_e1

[extruder]
axis: e
heater_pin: PA0
sensor_pin: PB0
sensor_type: Generic 3950

[axis x]
endstop_pin: PF4
position_min: 0
position_max: 300
position_endstop: 0
homing_speed: 50

[axis y]
endstop_pin: PF3
position_min: 0
position_max: 300
position_endstop: 0
homing_speed: 50

[axis z]
endstop_pin: PF2
position_max: 250

[tmc2209 motor_z]
uart_pin: PB9
run_current: 0.8

[tmc2209 motor_e0]
uart_pin: PG14
run_current: 0.6

[tmc2209 motor_e1]
uart_pin: PG10
run_current: 0.6

[heater_bed]
heater_pin: PF5
sensor_pin: PB1
sensor_type: ATC Semitec 104GT-2

[fan]
pin: PF7
```

**The two drive limits are the only thing standing between a wrong number and
a bent frame.** `max_torque` is a percentage of *rated* torque, not a raw
value, and it goes up to 400. The EMJ-04AFD22 is a 400 W motor rated about
1.27 N·m, so at `max_torque: 300` — the motor's own peak — a 40 mm pulley pulls
on the order of 600 N. The value here is `100` instead: full continuous torque,
enough to move the gantry and short of anything that bends a part. Raise it
only once the machine homes and prints, and raise it because a move stalled,
not pre-emptively.

`following_error` is in millimetres and is written to the drive's `6065h`, so
the **drive** faults on a stall or a crash rather than continuing to push. It
has no default: leave it out and no session limit is written at all, and the
drive keeps whatever the last session left in `6065h`. Homing is separately
governed by `homing_following_error` (default 2.5 mm) and `homing_max_torque`
(default 50%), which apply only around `G28`.

On `estun-pronet` this is also a checkpoint. `6065h` belongs to the same CiA
group as the `60F4h` this drive family does not have, and ESTUN's dictionary
was never obtained — so if `6065h` is absent too, the endpoint now says exactly
that, naming the object, instead of failing somewhere downstream.

The tandem extruder is a **follower axis with two motors**, not two axes.
`build_follower_steppers` walks every motor of the axis, so both step from one
trajectory — there is no synchronisation to maintain and no way for them to
diverge.

`cycle_us: 250` (4 kHz) is the fast end of ProNet's DC range. ESTUN's manual
prints that range twice and the two disagree - 250 us to 8 ms in the
specification table, 250 us to 2 ms in object `0x1C32:02` - but both agree on
the 250 us floor, so this value is in spec either way.

A Markforged Y move drives **both** motors while an X move drives only its own.
A plain `endstop_pin` works on both axes; only the **per-motor keyed** endstop
form is rejected on Y, because that form requires an axis reaching exactly one
motor lane.

**Verify.** `./scripts/ci.sh quick` is green on the branch and klippy parses the
configuration.

---

## Part 12 — Staged bring-up

Belts stay uncoupled until the final step.

1. **Stub endpoint, drives off.** Build the stub if the host page has not
   already (`make -f Makefile.rust ethercat-stub`), point `endpoint:` at
   `rust/target/release/ethercat-rt-stub` and start klippy. It must reach
   `ready`. This proves planner -> bridge -> transport with zero hardware risk.
2. **Real endpoint, motors uncoupled.** Switch `endpoint:` back to
   `rust/target/release/ethercat-rt`, built by the host page's endpoint step
   (`make -f Makefile.rust ethercat-endpoint-hw`). klippy spawns it itself at
   claim time; it is never launched by hand. Expect `ready` and a log line
   naming the profile and matched identity.
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

   Both copies must change, and the Rust one compiles into
   `klippy/_motion_engine.so` — so the edit does nothing until the module is
   rebuilt:

   ```sh
   sudo service klipper stop
   scripts/build-native.sh
   ```

   Changing only the Python side, or changing both and skipping the rebuild,
   leaves the host and the planner disagreeing about the machine, which is
   worse than the wrong sign: the two halves then fight each other.
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

Two ways to write them. `SERVO_PARAM` from the console, for trying a value:

```
SERVO_PARAM SERVO=motor_x GET=0x3014.0
SERVO_PARAM SERVO=motor_x SET=0x3014.0 VALUE=40 TYPE=u16
```

`SERVO=` takes the `[motor]` name, or the axis name where the axis has a single
servo — both `motor_x` and `x` reach the same drive on this machine. A `SET`
reports the value read back from the drive, which is not always the one sent:
out-of-range writes settle at the drive's own limit.

A `params:` block on the `[motor]` section, for values that must survive a
restart, one per line as `0xINDEX.SUB: type value`:

```ini
[motor motor_x]
# ... the options from Part 11 ...
params:
  0x3016.0: u16 300
  0x3014.0: u16 40
```

These are written at claim time, every start, in the order given.

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
| `rc=-4` | a drive never reached OP | read the per-slot `al_state`/`al_status` lines printed with it |
| `rc=-6` | the drive refused the PDO map | an object in the map this drive does not have, or a fixed map |
| `rc=-21` | profile identity missing or zero | `vendor_id` **and** `product_code` both set, from Part 10 |

`rc=-2` deserves emphasis: a drive that is present but of a different identity
looks **exactly** like an absent one to the master. The endpoint names the
profile and identity it matched on, so read that line before suspecting wiring.

**`rc=-6` and `rc=-4` are the ones to expect first on ProNet**, because the
profile carries assumptions inherited from the drive family this fork was built
against. The endpoint prints what it assumed alongside either failure — the
touch-probe objects, the digital I/O, the variable `1600h`/`1A00h` remapping,
and the following-error window `6065h` and timeout `6066h` — so the message
names the assumption that broke rather than leaving a bare code.

`rc=-4` is also where a rejected configuration SDO surfaces. The master applies
those in PRE-OP, not at the call, so a drive that refuses one simply never
reaches OP; the endpoint says so and prints each slot's AL state and status
code. A drive rejecting `6065h` at the session-limit write is named directly
instead, with its abort code — likely if ESTUN's dictionary omits that object
the way it omits `60F4h`.

None of this is a reason to expect failure. It is what to read when it happens,
and it is the difference between a five-minute fix and an afternoon.

## What "done" looks like

The bench is finished when all of the following hold on a machine that has been
**cold booted**, not warm restarted:

| | Check |
| --- | --- |
| Bus | `ethercat slaves` lists both drives, in wired order, reaching `OP` |
| Host | endpoint runs `SCHED_FIFO` on the isolated core (`chrt -p`) |
| Drives | no `A.70` in the log after a full boot under load |
| Motion | `G1 X…` turns one motor; `G1 Y…` turns both |
| Homing | all three axes home and repeat without drift |
| Tracking | following error stays small and steady during a fast move |
| Extruder | both extruder motors turn together, always |

Anything short of that is a bench still being brought up, not a finished one.
The most common reason a machine passes every step and then misbehaves is that
the cold-boot test was skipped — a marginal real-time setup survives a warm
restart on an idle board and drops frames under boot load.

## Still unverified on hardware

Carried forward honestly. None of the following has run on real hardware:

- The ESTUN vendor ID and product code (no public ESI — read them off the bus
  at Part 10).
- The Markforged belt coupling sign (Part 12, step 5 checks it).
- `ec_dwmac-rk`, if the CB2 is the host: it compiles and its symbols resolve,
  but it has never been loaded. A Pi 5 host avoids this one entirely.

## See also

- [`ethercat-host-cb2-rk3566.md`](ethercat-host-cb2-rk3566.md) — the CB2 host:
  kernel, IgH master, `ec_dwmac-rk`, and the endpoint build.
- [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) — the Pi 5 host
  alternative, kernel and EtherCAT master build.
- [`ethercat-bench-bringup.md`](ethercat-bench-bringup.md) — drive profiles, SDO
  parameters, telemetry capture, and the real-time scheduling rules in depth.
