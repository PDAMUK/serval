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

## Part 1 — Bill of materials

Counts for the servo pair and the supply feeding it. The printer's own frame,
bed, hotend and host board are assumed and not listed; the last group holds
only the printer-side parts this conversion changes.

Part 5 carries the reasoning and the ratings behind every mains row. This is
the shopping list; that is the argument.

### Per drive — two of each

| Item | Qty | Part | RS stock no. |
| --- | --- | --- | --- |
| Servo drive | 2 | ESTUN `ProNet-04AEG-EC` | — |
| Servo motor | 2 | ESTUN `EMJ-04AFD22` | — |
| Encoder cable | 2 | ESTUN **PBP** series — `PBP` is incremental; a `PDP` (absolute) cable is the wrong part for the `F` encoder | — |
| Motor power cable | 2 | ESTUN `PDM-GD12-XX`, or 1 mm^2 self-made | — |
| Regenerative resistor | 2 | 50 ohm, and 60 W **at the mounting it gets**, which is the part of this row that catches people. An Arcol `HS100 50R J` makes 100 W bolted to metal and 30 W free-standing; an `HS300 50R` makes the 60 W with nothing attached. Part 5 has the table | **252-2928** |
| EtherCAT patch lead | 2 | Shielded Cat5e or better, 100BASE-TX | — |

The regenerative resistor is per drive, not per machine: each drive switches
its own braking transistor across its own `B1`/`B2`, and both axes of a
Markforged gantry decelerate hard.

Two EtherCAT leads for two drives, because the chain starts at the host:
host to drive 0, drive 0 to drive 1. A star topology would need a switch and
three leads, and EtherCAT does not work through a switch anyway.

### Once for the pair — the mains chain

Every row here is one, not two. The drives share the chain because they share
the supply: 7.83 A for the pair sits inside a single 16 A circuit, so a
per-drive chain would double every protective device and buy nothing.

| Item | Qty | Part | RS stock no. |
| --- | --- | --- | --- |
| Isolator | 1 | ABB `SD202/32` | **175-5085** |
| MCB | 1 | ABB `S201-C16` | **489-0447** |
| RCD | 1 | ABB `F202 A-25/0.03` | **232-0339** |
| EMC filter | 1 | Roxburgh/Deltron `DRF10`, or Schaffner `FN2412-16-44` if the filter's ambient reaches 50 C — Part 5 decides which | **761-5696** / **518-6389** |
| Contactor | 1 | ABB `ESB20-20N-06` | **211-1482** |
| Emergency stop | 1 | Schneider `XALK178` — enclosed, twist release, 1 NC, breaks the contactor coil | **795-1295** |
| Coil suppressor | 1 | RC snubber, 100 ohm / 0.1 uF across the contactor coil | — |
| SPD | 1, optional | Schneider `A9L20500` iPRD20 | **065-4748** |
| DIN rail | 1 | 35 mm top-hat, plus two end stops | — |
| Terminal blocks | 3 | L, N and PE feed-through with jumper links. Each drive takes main power at `L1`/`L2` **and** control power at `L1C`/`L2C` off the same pair, so one contactor pole lands on four conductors, not two | — |
| Mains cable, supply to drives | 1 run | 3-core flexible 300/500 V; 1.5 mm^2 carries 7.83 A, 2.5 mm^2 for volt-drop margin over a couple of metres | — |
| Mains inlet | 1 | **C20** (16 A). A C14 is rated 10 A, which the drives alone take 78% of | — |
| Mains lead | 1 | C19 to 13 A BS 1363 plug. Its CPC is the machine's only connection to earth | — |
| Protective bonding | 1 run | 4 mm^2 green/yellow, main earth terminal to ground plate, ring-terminated. This is internal bonding, **not** the supply earth — see Part 5 | — |

### One for the machine

| Item | Qty | Part | RS stock no. |
| --- | --- | --- | --- |
| Drive debug cable | 1 | **mini-USB**, double shielded with ferrites. Moved between drives, not duplicated — the `-EC` variant uses mini-USB, not the base drive's RS-485 | — |

### Substitutions, and what each one removes

| Fit this | Instead of | Net |
| --- | --- | --- |
| RCBO — ABB `DSE201 M C16 A30` (**136-7786**) or Siemens `5SV1316-7KK16` (**187-3289**) | the MCB **and** the RCD | Two line items become one, and 53 mm of rail becomes 36 mm, or 18 mm with the Siemens |

That is the only substitution on this list. The savings that look like
substitutions elsewhere are not: one filter and one contactor serve both
drives because they sit on a shared supply, which is the count above rather
than a reduction from it.

### Printer side, changed by this conversion

| Item | Qty | Note |
| --- | --- | --- |
| TMC2209 drivers | 3 | Z, extruder A, extruder B. **Motor1 and Motor2 stay empty** — X/Y are servos |
| Endstop switches | 3 | X, Y, Z, wired to the Manta |

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

### Where the supply arrives, and what "earth" means at each point

A plug-connected machine in a UK house has three different conductors that
all get called earth, and they are sized and tested by different rules.
Collapsing them into one line is how a machine ends up with a 4 mm^2 strap
bolted to a chassis whose actual connection to earth is a 13 A plug.

| | What it is | Sized by | Tested by |
| --- | --- | --- | --- |
| **Supply PE** | The CPC in the mains lead, from the plug's earth pin to the machine's main earth terminal | The cord. A 13 A UK lead is 1.25 or 1.5 mm^2, and nothing inside the machine changes that | Continuity, plug pin to chassis, **under 0.1 ohm** |
| **Protective bonding** | Main earth terminal to the ground plate, and from the plate to every exposed metal part: drives, motors, filter body, enclosure panels | ESTUN's **3.5 mm^2** minimum, taken up to 4 mm^2 | Continuity to the same 0.1 ohm |
| **Functional earth** | Cable shields, the filter's earth wire, the ground plate itself as a reference | EMC, not fault current | Nothing. It either quietens the encoder or it does not |

The 4 mm^2 is a drive-maker's figure for a low-impedance bonding path, not a
fault-current calculation. A 1.5 mm^2 supply cord would take a 1.5 mm^2
protective conductor under the wiring regulations; 4 mm^2 is far above that,
and it buys noise performance rather than safety margin. It applies from the
main earth terminal inwards. It cannot be applied to the lead, because the
lead is a bought item.

**The ESTUN manual's grounding instruction does not transfer to a UK house.**
It says to ground "to an independent ground, use ground resistor 100 ohm max",
and that single point grounding is required "grounding resistance 100 ohm or
below". That is a JIS Class D earth: a local electrode, measured against true
earth, which is how the drive's home market earths machinery.

A UK domestic supply already provides the earth, as TN-C-S (PME) in most
houses or TN-S in older ones, and it arrives at the socket. The declared
maximum external loop impedance is **0.35 ohm for TN-C-S and 0.8 ohm for
TN-S** — two orders of magnitude inside ESTUN's 100 ohm, which is therefore
satisfied by plugging the machine in, with nothing to measure and nothing to
install.

Driving an earth rod and bonding the machine to it is the wrong reading, and
under PME it is actively dangerous: the machine would sit between the supply's
combined neutral-earth and a local electrode, giving diverted neutral current a
path through the chassis. **There is one earth, and it comes in on the lead.**

### One plug or two

The drives alone draw **7.83 A**. That number decides the inlet before it
decides anything else.

A **C13/C14 coupler is rated 10 A**. The drives take 78% of it with the bed,
hotend, PSU, host and fans still to be fed, so a C14 inlet cannot carry this
machine. The connector, not the circuit, is the limit. **C19/C20 is rated
16 A** and moves the limit back to where it belongs: the plug's 13 A fuse.

So the order of preference is:

1. **One cord.** A 13 A BS 1363 plug into a C19/C20 inlet. The 13 A fuse
   leaves 5.17 A — about 1.2 kW — for everything that is not a servo drive,
   which a 300 mm bed at 600 W fits inside with room. One plug, one fuse, one
   RCD, one thing to pull.
2. **A dedicated circuit,** if the total goes past 13 A: a 16 A radial to a
   BS EN 60309 socket, still one cord. Past 13 A the machine has outgrown a
   domestic socket, and the answer is a bigger circuit rather than more plugs.
3. **Two cords, reluctantly.** EN 60204-1 asks for a single incoming supply
   where practicable, and this is why.

Two cords are not primarily an earthing problem — each lead brings its own
CPC, both land on the same main earth terminal, and two parallel protective
conductors are redundancy rather than a hazard. The problem is isolation.
EN 60204-1 requires **a disconnecting device for each incoming supply**, and a
permanent warning label at each one where opening the other leaves circuits
energised. A machine with two cords and one isolator has no lock-off point,
which removes the premise the whole chain above is built on: Part 5 step 1
proves the machine dead by locking one switch, and it cannot.

If two cords are unavoidable:

- Both plugs into the **same socket**, so both are on one circuit, one RCD and
  one 32 A ring. Splitting them across two RCDs halves the measured leakage
  and hides the problem the leakage section exists to surface.
- The isolator breaks **both**, or there are two isolators and a label on each
  saying so.
- Both CPCs land on the one main earth terminal, not on separate studs.
- Label each inlet with what it feeds.

**The plug fuse is the overcurrent device, not the MCB.** A 13 A BS 1362 fuse
upstream of a 16 A MCB clears first on any overload the MCB would eventually
see, so the internal breaker is a local isolating and short-circuit device
rather than the thing protecting the flex. It is still worth fitting — it is
half of the RCBO, and it switches — but the coordination runs from the plug.
The fuse rides the rectifier inrush without trouble: tens of amps for a few
milliseconds is a handful of A^2s against a 13 A fuse's pre-arcing energy.

### The chain, in order

Seven things between the wall and the drives. The order is not arbitrary —
each one either protects what follows it or has to sit somewhere specific to
work at all.

| # | Device | Why it is there | Where it must sit |
| --- | --- | --- | --- |
| 1 | **Isolator** (switch-disconnector, lockable) | The lock-off point. Everything downstream can be made dead and *proved* dead by one person holding the key — which requires it to break **every** incoming cord, not one of two | First thing inside the enclosure, on the incoming cable |
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

### The filter's rating is the one that depends on where it sits

A filter's headline current is quoted at an ambient temperature, and an
enclosure beside two servo drives is not that temperature. The `DRF10` is
rated 10 A at 40 C and derates from there:

| Ambient | 40 C | 45 C | 50 C | 55 C | 60 C |
| --- | --- | --- | --- | --- | --- |
| `DRF10` ampacity | 10.00 A | 9.34 A | 8.65 A | 7.94 A | 7.18 A |

The machine draws **7.83 A**. At 45 C that is 84% of the filter; at 55 C it is
99%; at 60 C the filter is rated below the load. A bay holding two drives can
sit at 45 C without anything being wrong with it, and a bay inside a heated
chamber goes past 55 C by design.

So the filter choice follows the temperature where the filter is mounted:

- **Filter ambient stays at or below 45 C** — the `DRF10` is the right part.
  It is 100 g, sits on the rail, and leaks 1.46 mA.
- **Filter ambient reaches 50 C or more** — step up to a Schaffner
  `FN2412-16-44`, rated 16 A *at 50 C*, which leaves the load at half the
  filter with room above it.

The step up is not free, and the cost is leakage rather than money. The
`FN2412-16-44` leaks **3.4 mA** at 230 V, against the `DRF10`'s 1.46 mA, and
its datasheet notes that an interrupted neutral can double that. Against the
15 mA a 30 mA RCD may trip at, a 3.4 mA standing leak is most of a quarter of
the budget before the drives have contributed anything. Measure the standing
leakage after fitting either one — step 5 of the verification below exists
for this.

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
| EMC filter | Single phase, 250 VAC, rated above 7.83 A **at the temperature the filter sits at** | Roxburgh/Deltron `DRF10` — DIN rail, 100 g, 1.46 mA leakage, 10 A at 40 C — RS **761-5696**. Above 45 C ambient: Schaffner `FN2412-16-44` — DIN rail, 16 A at 50 C, 110 x 93 x 73 mm, 3.4 mA leakage — RS **518-6389** |
| Contactor | 2 pole, >= 20 A AC-1, **230 VAC coil** | ABB `ESB20-20N-06` — modular, 35 mm — RS **211-1482** |
| Emergency stop | Latching, twist release, at least one **NC** contact, in its own enclosure. Wired in series with the contactor coil, not in the mains path | Schneider `XALK178` — enclosed, 40 mm head, 1 NC, IP69K — RS **795-1295** |
| Mains cable, supply to drives | 1.5 mm^2 is adequate at 7.8 A; **2.5 mm^2** for volt-drop margin on a run over a couple of metres | 3-core flexible, 300/500 V |
| Protective earth | ESTUN specifies **3.5 mm^2**, a JIS size with no IEC equivalent — use **4 mm^2** | Green/yellow, ring-terminated to the plate |
| Regenerative resistor | **50 ohm, 60 W**, one per drive — see the note below, because 60 W depends on how it is mounted | Arcol `HS100 50R J` — RS **252-2928** |

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

- **The small filter, if the temperature allows it.** A `DRF10` is 100 g and
  sits on the rail with everything else; an `FN2412-16-44` is 110 x 93 x 73 mm
  and 600 g. The section above decides which, and the decision is thermal, not
  spatial — an undersized filter that fits is not a saving.
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

The ProNet manual gives one figure for this whole band: for
`ProNet-A5A`-`04A` the external resistor is customer-supplied and **60 W,
50 ohm is recommended**. One per drive.

Treat 50 ohm as a floor rather than a target. Resistance below it lets the
braking transistor pass more current than it is rated for and destroys it —
not a trip, a replacement drive — so a resistor a supplier happens to stock is
not a substitute for the manual's number.

**Set `Pn521.0` from `1` to `0` on both drives** when the external resistor
goes in. The manual states this for exactly this frame band, and it is easy to
miss because it is a footnote under a wiring table rather than a step. Without
it the resistor is fitted and the drive does not use it.

Wattage is where this goes wrong quietly, because an aluminium-housed resistor
is rated for a heatsink it will not get in a printer. Arcol's HS series
publishes both numbers:

| | On the datasheet's heatsink | Free-standing |
| --- | --- | --- |
| `HS100` | 100 W | **30 W** |
| `HS150` | 150 W | 45 W |
| `HS300` | 300 W | 60 W |

The heatsink that earns the first column is about 995 cm^2 of 3 mm plate for
an `HS100` — roughly a 315 mm square, which no printer has spare. So either
bolt the resistor to real metal with thermal compound and count on something
between the two columns, or read the right-hand column and size from it: an
`HS300 50R` free-standing meets the manual's 60 W with nothing attached.

This matters on a fast gantry, which dumps real energy back on deceleration.
The symptom of insufficient capacity is **`A.13` overvoltage**, which the
manual notes can appear when load inertia exceeds roughly 30x the rotor inertia
during acceleration. The EMJ-04AFD22 rotor inertia is 0.31e-4 kg.m^2. Treat a
first `A.13` under hard decel as "fit, re-mount, or size up the resistor", not
as a tuning problem.

Mount it away from the encoder and EtherCAT runs. It reaches temperatures that
mark cable insulation.

**Grounding.** The supply earth is settled by the lead, as the section above
sets out. What remains is inside the machine, and it is the usual cause of
intermittent encoder faults:

- **One star point.** The main earth terminal is it. Drives, motors, filter
  body and enclosure panels each get their own conductor back to the ground
  plate, and the plate gets one conductor to the main earth terminal. ESTUN's
  "single point grounding" means this, not a local electrode.
- **Ground-plate wires at least 3.5 mm^2**, taken up to 4 mm^2.
- The noise filter's ground wire runs straight to the ground plate, never
  daisy-chained through another device, and stays separate from its output
  lines.
- Separate high- and low-voltage runs. Keep cables short.
- Paint is an insulator. Every bond that matters is to bare metal, with a
  serrated washer or a scraped landing.

**Verify (no motor connected).**

1. Before energising: continuity from the plug's earth pin to the ground
   plate, to a drive's PE stud and to the enclosure reads **under 0.1 ohm**.
   A reading in ohms rather than milliohms is a bond onto paint.
2. Before energising: the isolator locks OFF with the key out, and a meter
   across `L1`/`L2` at a drive reads zero with it locked. With two cords, that
   has to hold with either one plugged in alone.
3. Energise. `POWER` (green) lights on both drives and the panel shows a status
   rather than an alarm. `CHARGE` (red) lights with main power.
4. The RCD holds. A trip here is the leakage question above, not a reason to
   fit a larger one.
5. Clamp the standing earth leakage with the drives idle and write the number
   down. It is the baseline every future nuisance trip gets compared against,
   and it takes a minute now against an afternoon later.
6. Open the contactor — by the emergency stop, not by the isolator. Both drives
   must drop out. This is the one test that proves the E-stop does anything.
7. Power down, wait 5 minutes, confirm `CHARGE` is out.

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

One *fieldbus* setting lives on the drive rather than on the bus, and the bus
does nothing until it is correct. Set it from the panel operator or ESView over
the mini-USB cable, on **both** drives. (Part 5 sets a second panel parameter,
`Pn521.0`, when the regenerative resistor goes in — nothing to do with
EtherCAT, but reached the same way.)

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
- Whether 60 W per drive is enough regenerative capacity for this gantry. The
  figure is the drive manual's recommendation, not a measurement against this
  machine's moving mass; `A.13` under hard decel is what says otherwise.

## See also

- [`ethercat-host-cb2-rk3566.md`](ethercat-host-cb2-rk3566.md) — the CB2 host:
  kernel, IgH master, `ec_dwmac-rk`, and the endpoint build.
- [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) — the Pi 5 host
  alternative, kernel and EtherCAT master build.
- [`ethercat-bench-bringup.md`](ethercat-bench-bringup.md) — drive profiles, SDO
  parameters, telemetry capture, and the real-time scheduling rules in depth.
