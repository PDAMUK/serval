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

- Unplug the machine — every cord, if it has more than one — and lock the
  isolator off before touching drive terminals or motor leads.
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
apply here. A Raspberry Pi CM4 in the same socket is a different case: its
BCM2711 GENET MAC is exactly what IgH's `genet` driver is for, but that driver
carries kernels 5.10 to 6.12 only and nothing in this repository has built or
run it, so it is not one of the routes below.

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
- **"Dead" in this document means electrically dead** — not live, no dangerous
  voltage, in the sense of "made dead and proved dead" before working on
  something. A drive that has failed is a *destroyed* or *faulted* drive, never
  a dead one.
- **The emergency stop does not make the machine dead.** It removes torque by
  opening the contactor, and control power stays on so the drives can be halted
  cleanly — see Part 5. Only the isolator, locked off and proved, makes the
  enclosure safe to work in.
- **The button latches and takes a key to release; the circuit behind it does
  not.** There is no safety relay, so the contactor closes again the moment the
  key turns, with no separate reset step. Never release it as a way of checking
  what happened. **Take the key out** and nobody else can either — worth doing,
  and still not a lock-off.
- Never plug or unplug a drive connector with power applied.
- Power sequencing: control power (`L1C`/`L2C`) **on first**, main circuit
  (`L1`/`L2`) on second; reverse on shutdown.
- Keep belts uncoupled until Part 12 says otherwise. A servo with a wrong
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
| RCD | 1 | ABB `F202 A-25/0.03` | **488-6915** |
| EMC filter | 1 | Roxburgh/Deltron `DRF10`, or Schaffner `FN2412-16-44` if the filter's ambient reaches 50 C — Part 5 decides which | **761-5696** / **518-6389** |
| Contactor | 1 | ABB `ESB20-20N-06` | **211-1482** |
| Emergency stop | 1 | **Two NC contacts** — one breaks the contactor coil, one signals `PF1`. RS PRO key release, through hole, 1 NC/1 NC, IP65 | **139-972** |
| Coil suppressor | 1, optional | RC network, 0.1 uF + 100 ohm, **Class X2**. Not needed behind the `ESB20-20N-06`, which suppresses its own coil — see Part 5. Evox-Rifa/Kemet `PMR209MC6100M100`; RS has withdrawn its listing, Farnell and CPC still carry it | — |
| SPD | 1, optional | Schneider `A9L20500` iPRD20 | **654-748** |
| DIN rail | 1 | 35 mm top-hat, plus two end stops | — |
| Terminal blocks | 3 | L, N and PE feed-through with jumper links. Each drive takes main power at `L1`/`L2` **and** control power at `L1C`/`L2C`, but off opposite sides of the contactor — main through it, control from the filter output ahead of it. Both pairs come off the filter, so that is where the distribution sits | — |
| Mains cable, supply to drives | 1 run | 3-core flexible 300/500 V; 1.5 mm^2 carries 7.83 A, 2.5 mm^2 for volt-drop margin over a couple of metres | — |
| Mains inlet | 1 | **C20** (16 A). A C14 is rated 10 A, which the drives alone take 78% of. Schurter `EC11.0031.001`, panel mount | **870-3413** |
| Mains lead | 1 | C19 to **BS1363**, H05VV-F 3G1.5. Its CPC is the machine's only connection to earth. Check the title says BS1363 or Type G — RS lists C19 leads with Schuko plugs under nearly the same description | **311-9315** |
| Protective bonding | 1 run | 4 mm^2 green/yellow, main earth terminal to ground plate, ring-terminated. This is internal bonding, **not** the supply earth — see Part 5 | — |

### One for the machine

| Item | Qty | Part | RS stock no. |
| --- | --- | --- | --- |
| Drive debug cable | 1 | **mini-USB**, double shielded with ferrites. Moved between drives, not duplicated — the `-EC` variant uses mini-USB, not the base drive's RS-485 | — |

### Substitutions, and what each one removes

| Fit this | Instead of | Net |
| --- | --- | --- |
| RCBO — ABB `DSE201 M C16 A30` (**136-7786**) or Siemens `5SV1316-7KK16` (**187-3289**) | the MCB **and** the RCD | Two line items become one, and 53 mm of rail becomes 36 mm, or 18 mm with the Siemens |

That is the only substitution on this list. An `ESB24` was listed here as a
second one, on the reading that it brought coil suppression the `ESB20` lacked.
It does not: the `ESB20-20N-06` already has it, and the `ESB24` is two modules
against one. The savings that look like
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
Pi 5, `ec_dwmac-rk` on the CB2.

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
**0.9 kVA per drive** — 7.83 A at 230 V for the pair, which is the figure
every sizing decision below is made against.

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
which removes the premise the whole chain below is built on: the verification
at the end of this part proves the machine dead by locking one switch, and with
two cords it cannot.

If two cords are unavoidable:

- Both plugs into the **same socket**, so both are on one circuit and one RCD. Splitting them across two RCDs halves the measured leakage
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

Six devices between the wall and the drives. The order is not arbitrary —
each one either protects what follows it or has to sit somewhere specific to
work at all.

| # | Device | Why it is there | Where it must sit |
| --- | --- | --- | --- |
| 1 | **Isolator** (switch-disconnector, lockable) | The lock-off point. Everything downstream can be made dead and *proved* dead by one person holding the key — which requires it to break **every** incoming cord, not one of two | First thing inside the enclosure, on the incoming cable |
| 2 | **MCB**, 16 A Type C | Overcurrent and short-circuit protection | Immediately after the isolator |
| 3 | **RCD or RCBO**, 30 mA Type A | Earth-fault protection. Read the note below before buying — drives break the usual assumptions | With, or immediately after, the MCB |
| 4 | **Surge protection device**, Type 2 — optional, see below | Clamps mains transients that otherwise reach the drives' rectifiers | At the panel entry, as close to the origin as the wiring allows; its own leads as short and straight as possible |
| 5 | **EMC / noise filter**, sized for its own ambient rather than for the load alone — see below | Keeps drive switching noise off the supply, and mains noise out of the encoder feedback | **Directly beside the drives**, bolted metal-to-metal to the backplate. A filter on a long lead filters almost nothing |
| 6 | **Contactor**, ≥ 20 A AC-1, 230 V coil | The thing an emergency stop actually opens. Without it there is no way to drop drive power except pulling the isolator by hand | Last device before the drives |
| 7 | **Drives** | | |

Two placement rules carry most of the benefit and are the two most often got
wrong: the **filter belongs at the drives, not at the panel entry**, bonded to
bare metal rather than through a painted panel or a wire; and the **SPD's leads
must be short**, because its clamping voltage is what it lets through plus the
inductive kick of its own tails.

**One line in the ProNet manual reads as though this whole chain were wrong,
and it is a translation defect.** The Safety Precautions page carries, in a list
about signal-line noise, "Never use a line filter for the power supply in the
circuit." Chapter 3.6.1 then instructs the opposite — "install a noise filter on
the input side of the power supply line" — and the EMC conditions in 3.7 will
not be met without one, with the filter drawn feeding the drive directly. Two
sections of the same manual cannot both be followed. Take 3.6.1 and 3.7, which
are specific, worked and drawn; the page-2 line is a garbled rendering of a
caution about filters on the *motor output* side, where one genuinely does not
belong. Expect to meet it, and do not let it talk you out of the filter.

**The contactor brings its own coil suppression, so read the suffix.** ABB's
older `ESB20` is AC-operated with no built-in protection, and the catalogue
scopes built-in surge protection to `ESB24` and above. The `ESB20-20N-06` in
the bill is not that part: the `..N` generation has a DC control circuit — its
datasheet lists the control circuit as DC as well as 50/60/400 Hz — and ABB
describes the family as hum-free with an incorporated varistor protecting the
coil to 5 kV and limiting the solenoid's own interference peaks. On that part
an external RC snubber is redundant, which is why it sits under *optional*
below rather than in the chain.

**Where the coil is fed from.** The contactor coil takes its supply from the
**load side of the RCD**, with the emergency stop's NC contact in series with
it. Fed from upstream of the RCD the coil circuit sits outside the earth-fault
protection covering everything else in the enclosure, and a fault in the thin
wiring going out to a button on the machine's outside is exactly what that
protection is for.

### Halting the drives as the stop is pressed

The contactor dropping main power is the safety function and nothing below
changes it. What the second contact adds is that the host finds out. Without
it, klippy keeps streaming cyclic position targets into a bus that has just
gone dark, and the first thing anyone sees is an endpoint death and a spread of
drive faults rather than "the stop was pressed".

A second contact on the button drives an input on the Manta, and the
`klippy:shutdown` it raises reaches `ethercat_node`, which calls `stop_node` on
each node. Part 11 wires it up and explains why it is not a `[gcode_button]`
running `M112`.

**What `stop_node` actually does**, because the two halves are not what their
names suggest:

| Step | Where it acts |
| --- | --- |
| `Stop` | **Host only.** Discards the motion rings and halts the stream. Nothing goes on the EtherCAT wire |
| `SetTorque(false)` | Schedules a disable, which the next RT tick executes once the rings are empty — hence the ordering. It writes CiA 402 controlword **`0x0006`** to every drive, holding target position at the measured actual, for 100 cycles |

`0x0006` is **Shutdown**, not Quick Stop. It takes the drive from Operation
Enabled to Ready to Switch On — servo off. It does *not* command a ramp; there
is no `6084h` deceleration involved anywhere in this path.

What the machine then does is the drive's decision, and it is set by a
parameter rather than by anything the host sends. On `Pn004.0 = 0`, which is
the factory value, servo off means **stop by dynamic brake** — the motor
windings are shorted — and then coast. That is real braking and it needs no bus
voltage, which is why it still works with the contactor already open. Set
`Pn004.0 = 1` and the same command leaves a fast gantry coasting on friction
alone. Part 9 checks it.

So the honest description of what the second contact buys: the gantry is
dynamically braked rather than freewheeling, the queued motion is thrown away
so nothing resumes mid-move when power comes back, and the planner ends in a
clean shutdown instead of an endpoint death. It is **not** a profiled stop, and
the stopping distance is set by inertia, friction and the dynamic brake, not by
anything that can be tuned.

**In the language of EN 60204-1 this is a Stop Category 0 with dynamic
braking, and it is not Category 1.** Category 1 means a *controlled* stop with
power kept on to the machine actuators until it has stopped, then removed.
These drives cannot do that: on servo off, `Pn004.0` offers dynamic brake or
coast and nothing else, there is no `6084h` ramp anywhere in this path, and the
contactor removes the DC bus the moment the button opens its coil. Power is
removed immediately and the gantry stops because the windings are shorted, not
because anything is controlling it.

That is a deliberate choice for this machine rather than an omission, and it
follows from the hardware: **these drives have no STO** — no safety function of
any kind appears in the ProNet manual — so there is no safe torque-off to
sequence a controlled ramp against. The honest description is a Category 0
stop, with dynamic braking making it a better Category 0 than a coast, and with
no monitoring, no mirrored contacts and no safety relay anywhere in the chain.

The manual is worth heeding on one point: repeated dynamic braking degrades the
drive's internal elements. The emergency stop is not a routine way to stop the
machine.

**Every stop press latches an alarm, and clearing it is friction on every
single press.** Opening the contactor removes main power for longer than one AC
period, so the drives latch **`A.21`** (main power off for more than one
period) and/or **`A.14`**, and they will not run again until the alarm is
cleared.

`Pn000.3` looks like an escape and is not: the factory `0` already means "one
period, no alarm", `A.21` is *defined* as power off for more than one period,
and setting it to `1` only makes the drive stricter. So the clearing routes are
the panel **`ENTER`**, **`/ALM-RST`**, or a **main-circuit power cycle**
(manual §5.1.2).

Note what that leaves open: `/ALM-RST` is `CN1-39` on the base 50-pin
connector, and the `-EC` variant's `CN1` is 20-pin with 5 sequence inputs, so
whether it can be allocated there is unknown. The likely answer is a CiA 402
fault reset over the bus, which needs the EtherCAT manual nobody has yet.
Budget a panel reach or a power cycle after every press.

**Two things have to be true for that halt to land.**

First, the drives have to still be powered when it arrives. `L1C`/`L2C` is
control power and `L1`/`L2` is the main circuit, and they are separate
terminals precisely so they can be switched separately. **Take control power
from between the filter and the contactor, and switch only the main circuit.**
The drive then stays alive with its bus collapsing, accepts the Stop, disables
torque, holds the EtherCAT link up and reports its own state. Put both behind
the contactor and the drive loses power mid-frame; the halt is sent into
nothing.

**Between the filter and the contactor, not simply upstream of the contactor** —
the distinction matters because the obvious tap is the wrong one. The filter
sits at the drives while the terminal rail sits at the enclosure edge, so the
convenient place to pick up two more conductors is back at the rail, ahead of
the filter. ESTUN's EMC conditions in 3.7 feed `L1C`/`L2C` from the filter
alongside `L1`/`L2`; tapping ahead of it puts the drive's own control
electronics and their switching straight onto unfiltered mains, which is the
conducted-emissions path the filter exists to close. One pole of the contactor
therefore lands on two conductors, not four, and the control pair branches off
the filter's output before it.

That costs something and it has to be said plainly: **with control power
upstream, pressing the emergency stop does not make the drive dead.** It makes
the motor safe to be near — no torque, nothing held, because the DC bus is
gone — while the drive's own electronics stay live at 230 V. Those are
different states and the stop only reaches the first. The isolator remains the
only lock-off point, and everything in **Before anything else** still applies:
the stop is not a substitute for it.

Second, the halt is **best effort and is not a protective measure**. The NC and
NO contacts of one button change over at the same instant, with no ordering
between them, and the Stop travels over a fieldbus at a 250 microsecond cycle
while the contactor takes tens of milliseconds to open. It usually wins. It is
not required to, and nothing should be built on the assumption that it does.
The reason to fit it is a clean stop and a readable log, not safety.

If a snubber does go in — behind some other contactor, or out of caution —
**it goes across the coil, never across the emergency stop's contact.** The
part is sold as a contact suppressor, and that is the wrong place for it in
this circuit. A 0.1 uF capacitor is 31.8 kohm at 50 Hz. ABB's AC-operated
`ESB20` draws 3.2 VA holding, 13.9 mA at 230 V, about 16.5 kohm — the same
order of magnitude, so a snubber bridging the open contact leaves a large
fraction of the coil voltage standing, and that contactor's drop-out band is
**20 to 75% of Uc**. The honest statement is that it might drop out. An
emergency stop that might work is not one. Coil impedances in this class are
all near enough that the arithmetic lands the same way.

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
threshold chosen by trial, and it is **not a time-delayed device**. ESTUN is
explicit on that second point: "always use a fast-response type or one designed
for PWM inverters. Do not use a time-delay type." A delayed device holds a
residual current through the window an instantaneous one would clear it in, and
that window is the whole protective function.

So a nuisance trip leaves two answers, not three. Either the standing leakage is
genuinely close to the trip band, in which case the fix is to reduce it — a
lower-leakage filter, shorter screened runs, the drives on their own RCBO so
they do not share a budget with a bed heater — or it is a real earth fault that
has just been found. Measuring the standing leakage with a clamp meter
distinguishes the two in a minute, which is why step 5 of the verification below
asks for the number before anything has gone wrong.

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

**Past 45 C the filter stops being the only thing derating.** The drives carry
their own limits, and they are tighter than they look: ESTUN specifies a working
range of **0 to 55 C**, and separately an **ambient of 45 C or less "to ensure
long-term reliability"**. So 45 C is where the drives begin trading life for
temperature, and 55 C is where they leave specification altogether — the same
two numbers that bracket the filter table above, which is a coincidence worth
not misreading. A chamber bay at 60 C is not a filter problem with a bigger
filter for an answer; it is a bay the drives should not be in.

The same section sets the spacing that keeps a bay near its ambient rather than
above it: **at least 10 mm between drives side by side, and at least 50 mm above
and below each one**, with a fan over them if natural convection cannot hold it.
Two ProNets shoulder to shoulder on a backplate is the arrangement this rules
out, and it is the arrangement a printer tempts you into.

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

Specifications first: those are arithmetic from this machine's 7.83 A and hold
whoever supplies the parts. The named parts are illustrations of the right
class, not a validated bill of materials — availability moves, and the drive
manual and local wiring regulations both outrank this table. RS stock numbers
are quoted because they pin one specific part down; any distributor's
equivalent is the same purchase.

**Needed.** Leaving any of these out makes the machine either unsafe or noisy
enough to corrupt encoder feedback.

| Item | Specification | Part, and RS stock no. |
| --- | --- | --- |
| Isolator | 2-pole, >= 16 A, lockable in the OFF position. On the rail behind a closed door, IP20 is enough; a through-wall rotary disconnector instead of this one would need IP65 | ABB `SD202/32` — 2-pole, 32 A, 440 V, two modules at 35 mm, padlockable, IP20 — RS **175-5085** |
| MCB | 16 A, **Type C**, 6 kA. One pole breaking line is enough here — the isolator and the RCD are both 2-pole, so the double-pole break exists | ABB `S201-C16` — 1 pole, 1 module — RS **489-0447** |
| RCD | 2-pole, 30 mA, **Type A** | ABB `F202 A-25/0.03` — 25 A, 2 pole, 2 modules — RS **488-6915** |
| EMC filter | Single phase, 250 VAC, rated above 7.83 A **at the temperature the filter sits at** | Roxburgh/Deltron `DRF10` — DIN rail, 100 g, 1.46 mA leakage, 10 A at 40 C — RS **761-5696**. Above 45 C ambient: Schaffner `FN2412-16-44` — DIN rail, 16 A at 50 C, 110 x 93 x 73 mm, 3.4 mA leakage — RS **518-6389** |
| Contactor | 2 pole, >= 20 A AC-1, **230 V coil**; a DC or universal control circuit rather than an AC solenoid, so the coil carries its own suppression | ABB `ESB20-20N-06` — 20 A AC-1, one module at 18 mm, control circuit DC/50/60/400 Hz — RS **211-1482** |
| Emergency stop | Latching, with **two NC contacts**: one in series with the contactor coil, one to the host input that triggers the halt. Not in the mains path | RS PRO key release, 1 NC/1 NC, IP65, through-hole so it needs a panel to sit in — RS **139-972**. The same family runs to a 2 NC + 1 NO variant, deliberately not given a code here because the NO contact is the one this circuit should not use |
| Mains inlet | 16 A appliance coupler, panel mounting. A C14 is rated 10 A and the drives alone take 78% of it | Schurter `EC11.0031.001` C20 — RS **870-3413** |
| Mains lead | C19 to **BS1363**, 13 A. RS lists C19 leads with Schuko plugs under nearly the same description, so check the title names BS1363 or Type G | RS PRO, 2 m, H05VV-F 3G1.5 — RS **311-9315** |
| Mains cable, supply to drives | 1.5 mm^2 is adequate at 7.83 A; **2.5 mm^2** for volt-drop margin on a run over a couple of metres | 3-core flexible, 300/500 V |
| Protective earth | ESTUN specifies **3.5 mm^2**, a JIS size with no IEC equivalent — use **4 mm^2** | Green/yellow, ring-terminated to the plate |
| Regenerative resistor | **50 ohm, 60 W**, one per drive — see the note below, because 60 W depends on how it is mounted | Arcol `HS100 50R J` — RS **252-2928** |

**One part instead of two.** One combination on this list is worth making.

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
| Coil suppressor | RC network, 0.1 uF + 100 ohm, rated for across-the-line use — the capacitor sits on 230 V, so **Class X2**, not a general-purpose film part | Evox-Rifa/Kemet `PMR209MC6100M100`, 250 V ac, 26 x 10.5 x 19 mm. RS has withdrawn its listing; Farnell and CPC carry it. Check the X2 marking on the part, because listings often omit the class | Skip it with the `ESB20-20N-06`, whose coil already carries a varistor. Fit one only behind a contactor with a plain AC solenoid and no built-in suppression |
| SPD | Type 2, 230 V, L-N and N-PE modes | Schneider `A9L20500` iPRD20 — 1P+N, 20 kA, 1.4 kV — RS **654-748** | If the board feeding the machine already carries a Type 2 SPD, this one is a second line of defence, not the first. It also costs more than the rest of the chain together |

### Fitting it in a printer enclosure

An industrial panel has room to spare and a printer does not, so it is worth
choosing for size deliberately rather than discovering it at assembly.

Keep the whole chain on **one 35 mm DIN rail**. Every device above exists in a
DIN form, and a rail costs a few millimetres over loose parts while making the
wiring shorter, the earthing a single bonded path, and the whole assembly
removable as a unit. A module is 17.5-18 mm, so count modules rather than
millimetres:

| Device | Modules |
| --- | --- |
| Isolator `SD202/32` | 2 |
| MCB `S201-C16` | 1 |
| RCD `F202 A-25/0.03` | 2 |
| Contactor `ESB20-20N-06` | 1 |
| **Rail needed** | **6** |

That is **about 105 mm**, before the filter, which is not a modular part and
has to be measured from whichever one the temperature picks. An `A9L20500` SPD
adds two more, and an RCBO takes one or two back. Add a spare module on top,
because something always follows.

Three choices save the most space:

- **The small filter, if the temperature allows it.** A `DRF10` is 100 g and
  sits on the rail with everything else; an `FN2412-16-44` is 110 x 93 x 73 mm
  and 600 g. The section above decides which, and the decision is thermal, not
  spatial — an undersized filter that fits is not a saving.
- **A modular installation contactor rather than a control contactor.** An
  `ESB20-20N-06` is one module — 18 x 85 x 65 mm, 140 g — against an `LC1D09`
  at 45 mm and far deeper, built for motor starting duty this circuit does not
  have.
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

**And the second half of that choice: releasing the button restores power.**
Two things get called latching here and only one of them is. **The button
latches** — pressed, it stays in with both NC contacts held open, and the
139-972 is **key release**, so it cannot be twisted back, thumbed back or
knocked back. **The coil circuit does not**: nothing holds the contactor
dropped out independently of the button, so the instant the key releases it the
coil re-energises, the contactor closes, and the drives have main power again.
The key is the reset and there is no other one.

That cuts both ways. **Take the key out and nobody restores power** — not the
person who wandered in, not you in five minutes having forgotten why it was
pressed. For a bench machine in a house that is a real interlock, and it is the
reason to buy this part rather than a twist-release button. But a key in a
pocket is not a proved dead state: control power at `L1C`/`L2C` was never
interrupted, so the enclosure was live at 230 V throughout the press, and the
key-release mechanism is not a lockable disconnector.

On release the motors stay still, because klippy is shut down and torque is
disabled until a `FIRMWARE_RESTART` — but the DC bus recharges and `CHARGE`
lights. That is the behaviour this circuit has, not a fault in it, and it is
exactly why the stop is not what makes the machine safe to reach into. Anyone
who pressed the stop to clear a jam and then turned the key to see what
happened has re-energised the enclosure they are standing in.

**Key out is an interlock; the isolator locked off is isolation.** They are
not alternatives, and the isolator is the only device in this chain that gives
a proved dead state. Lock it off, prove it, and wait for `CHARGE` before
reaching in — every time, key or no key. A safety relay with a separate
monitored reset is what an industrial build would add on top, and it would
also watch for the welded pole nothing here detects.

**The 16 A rating is not about the 7.83 A load.** At 16 A the drives sit at
under half the breaker's rating, which looks generous until the inrush is
considered: energising two DC buses charges their capacitors through the
rectifiers, and that transient is tens of amps for a few milliseconds. Type C
trips instantaneously at 5-10× rating, so a 16 A Type C tolerates 80-160 A for
that instant. A 10 A Type B would trip on the *first* power-up, every time, and
look like a fault in the drives. The plug's 13 A fuse sits above all of this
and rides the same inrush, for the reason given under **One plug or two**.

Per drive:

| Terminal | Connect |
| --- | --- |
| `L1`, `L2` | main circuit power (single phase; `L3` unused) |
| `L1C`, `L2C` | control power — **from the filter output, upstream of the contactor**, so the drive survives an emergency stop and can be told to halt |
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

Treat 50 ohm as a floor rather than a target: below it the braking transistor
passes more current than it is rated for. The drive does watch for this — `A.23`
is "brake overcurrent alarm", which the manual attributes to a bleeder resistor
that is too small — so the first symptom is a trip rather than a destroyed
drive.
That is a backstop, not a licence to guess: a resistor a supplier happens to
stock is not a substitute for the manual's number.

**Set `Pn521.0` from `1` to `0` on both drives** when the external resistor
goes in. `Pn521` runs `0~1` and ships at `1`, which the manual glosses as "does
not connect externally regenerative resistor" — so the factory setting is the
wrong one for this build, and the instruction to change it is a footnote under
a wiring table rather than a step. Without it the resistor is fitted and the
drive does not use it.

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

The manual pairs `A.13` with **`A.16` regeneration error** in the same
paragraph, and the two want different responses: `A.13` says the resistor could
not absorb what the decel produced, while `A.16` says the regenerative circuit
objects to the resistor that is fitted. The manual's remedies for either are to
decrease the torque limit, decrease the deceleration, or decrease top speed —
worth knowing as the answer when the resistor is right and the gantry is simply
asking for more than 60 W.

More wattage at 50 ohm is always safe, and only the resistance has a wrong
answer. The drive holds no parameter describing the resistor — `Pn521.0` is a
bare on/off — so all the braking transistor sees is the 50 ohm that sets its
peak current. Below that value `A.23` follows; above it braking weakens and
`A.13` follows. Two 100 ohm in parallel or two 25 ohm in series both hold
50 ohm at double the dissipation, and on a burst duty like a gantry the
element's thermal mass matters more than the headline continuous rating.

Mount it away from the encoder and EtherCAT runs. It reaches temperatures that
mark cable insulation — and whatever it dissipates lands in the same bay as the
drives, against the 45 C they want for long-term reliability. Vent it or site it
outside the electronics bay.

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
6. Open the contactor — by the emergency stop, not by the isolator. `CHARGE`
   goes out on both drives and the motors lose torque, while `POWER` stays lit,
   because control power is upstream. This is the one test that proves the
   stop does anything. If `POWER` drops too, control power is on the wrong
   side of the contactor and the halt configured in Part 11 will never arrive.

   This tests the contactor only. The second contact — the one that halts the
   drives — needs klippy and the config from Part 11, so it is tested at
   **Part 12, step 2**.
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
CN2 uses the serial pinout rather than the 2500 P/R quadrature one. One caveat
on where that table comes from: the manual prints the serial pinout under the
heading "17 Bit Incremental/Absolute Encoder" and gives no separate 20-bit
layout. The four signals below are the only serial pinout it publishes, and the
alternative — the 2500 P/R wire-saving layout — is quadrature and plainly not
this encoder, so the mapping is an inference from elimination rather than a
quotation. Confirm it against the cable before crimping anything.

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

**Verify — and be clear what it does not prove.** The green `LINK/ACT` LED
lights on each connected RJ45. That confirms the cable and the PHY link, and
**nothing about direction**: a `CN4`-to-`CN4` link lights both LEDs exactly the
same way, because the link is negotiated below EtherCAT.

Direction is proven at **Part 10**, where `ethercat slaves` must list *two*
slaves in the wired order. One slave there is the reversed link showing up.
Until then, the only guard is having wired IN to OUT deliberately and labelled
the drives.

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
| Emergency stop signal | `PF1` | Motor4's endstop input, free in this build |
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
`stepper_z` respectively, and `PF1` is the one it gives Motor4, which this
build leaves empty. Check the row against that file rather than against
another board's config before plugging anything in.

**Every one of those inputs wants the `^` pull-up**, and BigTreeTech's file
writes them that way — `^PF4`, `^PF3`, `^PF2`, and `^PF1` on the Motor4 line it
leaves commented. Nothing supplies one by default: an `endstop_pin` without the
prefix configures the STM32 input with no pull-up at all, so a switch wired to
ground floats the moment it opens and the axis homes against noise. The Part 11
config carries the prefix on all four inputs for this reason. It is three
characters, it is invisible when wrong, and it is the kind of thing that reads
as a flaky switch.

Wire the motor coils in pairs by phase, not by wire colour.

**Which cables, because "power and signal" is not a list.** The aggressors on
this machine are the servo motor power cables (`U`/`V`/`W`, PWM at the drive's
carrier with high dV/dt — much the worst), the regenerative resistor leads
(`B1`/`B2`, switched hard by the braking transistor and only on decel, so the
noise arrives when the gantry is moving fastest), the mains runs either side of
the filter, the bed heater leads to `PF5`, and the stepper leads on Motor3,
Motor5 and Motor6. The victims are the encoder cables (`CN2`, 20-bit serial and
the most sensitive run here), the EtherCAT patch leads, the emergency-stop
signal on `^PF1`, the three endstops, the thermistors on `PB0`/`PB1`, and the
TMC2209 UART lines. The MCU link is not on either list: on a CB2 in the BTB
socket it never leaves the board.

**And the pair that cannot be separated at all:** a motor's power cable and its
encoder cable leave the same drive and arrive at the same motor, sharing a drag
chain on a moving gantry. Worst aggressor, most sensitive victim, no distance
available — which is why ESTUN sells both as screened assemblies and why, if
they must share a chain, they go on opposite sides of it.

**ESTUN's number for "away" is 300 mm**, stated twice: keep power and signal
lines separated by at least 300 mm, and never run them in the same duct or
bundle. A printer cannot give you 300 mm and this document is not going to
pretend otherwise — the whole machine is smaller than the separation. What
replaces the distance, in descending order of how much it buys:

- **Cross at right angles where runs must meet**, never parallel. Coupling
  falls off sharply with angle, and a crossing is nearly free.
- **Twisted pair with the return in the same twist** for every signal, so the
  loop area the noise couples into is small rather than the whole run.
- **Screened cable for the signal runs**, with the screen landed at the
  Manta end only — one end, or it becomes a ground loop between two earths.
- **Separate looms and separate ducts.** Losing the distance is not a reason
  to also lose the separation; the manual's "not in the same duct" costs
  nothing in a printer and is the half of the rule you can actually keep.

Be honest about what that leaves: 300 mm is what the drives were qualified
against, and everything above is a substitute for it rather than an equivalent.
So if an endstop or the stop input starts misbehaving once the servos are
moving, this is the first place to look and the code is the last.

The emergency-stop signal deserves the most care of the three. It is the
longest low-voltage run on the machine, out to a button on a panel, and `^PF1`
holds it up through the STM32's internal pull-up of tens of kilohms — a high
impedance looking at a cabinet full of switching. Noise on it cannot mask a
press, because an open contact stays open, but it can assert one: the machine
stops mid-print for nothing. Use a twisted pair with the return to ground, keep
it off the motor loom, and if trips still appear set `debounce_delay` on the
`[emergency_stop]` section before suspecting the button.

**Verify.** With the Manta powered and no mains on the drives, klippy
can be started against a minimal config and `QUERY_ENDSTOPS` reports all three
switches changing state when pressed.

**That proves the switch reaches the right pin. It does not prove the pull-up.**
An input declared without `^` still swings when the contact closes to ground —
closing to ground pulls it firmly low either way — so a missing prefix passes
this check exactly like a correct one. What a missing pull-up breaks is the
*released* state, which floats rather than resting high.

So check the released state, not the press:

- Query it several times with nothing pressed. Every read must return the same
  value. A reading that changes between queries, or with a hand near the loom,
  is a floating input.
- Re-run it later with the servos moving, which is when the noise is there to
  be picked up. This is the check that actually bites, and it is why Stage
  12 homes slowly with a hand on the power.
- Read the config back: all four inputs — `^PF4`, `^PF3`, `^PF2` and `^PF1` —
  carry the prefix. It is three characters and invisible when wrong.

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
| `Pn004.0` | `0` | stop by dynamic brake on servo off — the factory value, worth confirming rather than assuming |

`Pn004.0` is what the emergency stop in Part 5 relies on. The host writes
controlword `0x0006`, and this parameter decides whether the drive answers that
by shorting the motor windings or by letting the gantry coast. Both `Pn004` and
`Pn006` take effect **after restart**, and `Pn004` wants main *and* control
power cycled.

`Pn006.0` is the bus-mode nibble on every ProNet, but the value `4` comes from
the `-EC` variant rather than from the base manual, whose whole `Pn006` range
stops at `0x2133` — so a non-`EC` drive rejects `4` as out of range. It is
listed under **Still unverified on hardware** for that reason.

**Leave the drives' station alias alone.** This half is checkable: the endpoint
passes alias `0` to `ecrt_master_slave_config` — `SLAVE_ALIAS` in
[`rust/ethercat-rt/csrc/libecrt_igh.c`](https://github.com/PDAMUK/serval/blob/main/rust/ethercat-rt/csrc/libecrt_igh.c)
— and with alias 0 the master reads the position argument as the absolute
position on the wire. `ethercat_chain_index` is that position. Physical cable
order is therefore the single source of truth, and configuring an alias only
adds a second one that can disagree.

Do not assume `Pn704` holds that alias. In the base manual `Pn704` is the
CANopen node address, range `1~127`, default `1`, and an EtherCAT station alias
normally lives in the slave's EEPROM rather than in a drive parameter. If the
`-EC` drive exposes one at all, leave it as it ships.

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
`~/printer_data/config/` on whichever machine runs it — the Pi 5 on the path
Part 2 recommends, the CB2 if the endpoint ended up there. Replace the file's contents rather than
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

[printer]
max_velocity: 300           # bring-up limits: raise after Part 13, not before
max_accel: 3000
max_z_velocity: 5           # rotation_distance 8 lead screw; the default is max_velocity
max_z_accel: 100

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
#pdo_touch_probe: False
#pdo_digital_io: False
#   Optional PDO object groups, unset by default so the drive profile
#   decides. `estun-pronet` already drops both, because nothing in the
#   endpoint reads either one and they are the likeliest reason a ProNet
#   refuses the whole map. Set them True only if you have reason to want
#   them back on the wire.
#pdo_following_error: True
#   60F4h. `estun-pronet` drops it and derives the following error from
#   607Ah - 6064h instead; set it True if your drive turns out to have it.
#endpoint: /home/<your-user>/klipper/rust/target/release/ethercat-rt-stub
#   Optional. Unset, it is the hardware endpoint inside this checkout.
#   Uncomment it for Part 12 steps 1-2 only. Absolute: klippy does not
#   expand ~ and resolves a relative path against its own working directory.

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
nozzle_diameter: 0.4
filament_diameter: 1.75
heater_pin: PA0
sensor_pin: PB0
sensor_type: Generic 3950
min_temp: 0
max_temp: 250
control: pid
pid_Kp: 22.2                # starting values: PID_CALIBRATE HEATER=extruder replaces them
pid_Ki: 1.08
pid_Kd: 114

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
min_temp: 0
max_temp: 110
control: pid
pid_Kp: 54.027              # starting values: PID_CALIBRATE HEATER=heater_bed replaces them
pid_Ki: 0.770
pid_Kd: 948.182

[fan]
pin: PF7

[emergency_stop estop]
pin: ^PF1
```

**`[emergency_stop estop]` is the halt, and it is deliberately not a
`[gcode_button]` running `M112`.**

G-code runs through a queue behind a mutex. An `M112` typed at the console or
sent by the front-end does jump that queue, but by a route nothing inside
klippy can use: `GCodeIO` scans lines as they arrive on its input descriptor
and calls `cmd_M112` directly, outside the lock, before anything is queued. A
`[gcode_button]` callback does not arrive on that descriptor. It calls
`run_script`, which takes the G-Code mutex and waits for whatever holds it.

Most of the time that wait is short, because dispatching a move queues it into
the lookahead rather than executing it. But `G4`, `M400`, `TEMPERATURE_WAIT`
and a homing move all hold the mutex for real time, and a print is full of
them. The halt would arrive late by an amount nothing bounds — which is the
one property an emergency stop cannot have.

`[emergency_stop]` registers the button with `buttons` directly and calls
`printer.invoke_shutdown` from the callback. That runs every `klippy:shutdown`
handler there and then, on the reactor, with no queue and no mutex in the way.
`ethercat_node` is one of those handlers, and `stop_node` is what it does.

The pin polarity is the whole of the wiring, and it is worth being slow about.
`^PF1` pulls the input up, so the button's contact goes between `PF1` and
ground:

Two things get called "reads 1" and they are not the same: the voltage at the
pin, and the state `[emergency_stop]` acts on. `!` inverts the second and not
the first, so for an NO contact they disagree. The **asserted** column is the
one that decides whether the machine halts.

| Contact | | Not pressed | Pressed | Wire pulled off |
| --- | --- | --- | --- | --- |
| **NC** — `pin: ^PF1` | pin | low | high | high |
| | asserted | no | **yes — halts** | **yes — halts** |
| NO — `pin: ^!PF1` | pin | high | low | high |
| | asserted | no | yes — halts | no — **nothing** |

Use an **NC** contact. A broken signal wire then looks exactly like a pressed
button and the machine stops; on an NO contact the same fault is silent, and
the failure is discovered by pressing the stop and watching nothing happen. A
button with two NC contacts does this job with no NO contact anywhere: one for
the contactor coil, one for `PF1`.

Releasing the button does nothing on its own. A shutdown latches, and clearing
it is a `FIRMWARE_RESTART` once the stop has been released deliberately.

`QUERY_EMERGENCY_STOP STOP=estop` reports the input without touching it, which
is how to check the wiring before trusting it. It answers during a shutdown,
which is the point — but what it answers with is **the last sample taken before
the shutdown, not a live reading**. An MCU shutdown drops every user timer,
including the one sampling the button, so the value freezes at whatever caused
the stop. Releasing the button will not change it. Only a `FIRMWARE_RESTART`
starts the sampling again.

**The two drive limits are the only thing standing between a wrong number and
a bent frame.** `max_torque` is a percentage of *rated* torque, not a raw
value. The config field accepts up to 400, which is the CiA 402 `6072h`
ceiling rather than anything this drive will honour: ProNet's own
`Pn401`/`Pn402` internal torque limits run **0 to 300 %**, so a value above 300
is clamped by the drive and the number in the config stops describing the
machine. Treat 300 as the real ceiling. The EMJ-04AFD22 is a 400 W motor rated
about 1.27 N·m, so at `max_torque: 300` — the motor's own peak, and the same
3x its 2.8 A continuous to 8.4 A maximum output current implies — a 40 mm
pulley pulls on the order of 600 N. The value here is `100` instead: full
continuous torque, enough to move the gantry and short of anything that bends a
part. Raise it only once the machine homes and prints, and raise it because a
move stalled, not pre-emptively.

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

**Verify.** klippy starts and parses the configuration, naming any section it
rejects.

**That check runs on the printer. `./scripts/ci.sh quick` does not.** It is the
contributor gate — ruff over the repository, the whole Rust workspace's 2483
tests, and clippy with `-D warnings` — and it belongs on a development machine
before pushing a branch, not on the machine running the printer. Run on a CB2 it
is actively harmful: it is an hour of four Cortex-A55 cores, it wants a
`rust/target` that reaches 19-25 GB against an eMMC that may be 8 or 16 GB
in total, and if klippy is live it competes with the DC loop for the very core
Part 2 isolated for it. A machine that passes every step and then drops frames
under load is the failure mode the whole real-time setup exists to avoid; do not
manufacture it with a test run.

The CB2 does have to *build* — the native klippy modules and the endpoint, which
[Step 11 of the host page](ethercat-host-cb2-rk3566.md#step-11-build-the-kalico-endpoint)
explains cannot be cross-compiled. That is unavoidable
and is not this. Building links what the printer needs; `ci.sh quick` compiles
and runs the test binaries of every crate in the workspace as well.

---

## Part 12 — Staged bring-up

Belts stay uncoupled until the final step.

1. **Stub endpoint, drives off.** Build the stub if the host page has not
   already (`make -f Makefile.rust ethercat-stub`), uncomment the `endpoint:`
   line with your user name in it — an absolute path, because klippy does not
   expand `~` and resolves a relative one against its own working directory —
   and start klippy. It must reach
   `ready`. This proves planner -> bridge -> transport with zero hardware risk.

   This step now has an automated counterpart, so a failure here is more
   likely to be this machine than the software. `test/test_ethercat_claim_stub.py`
   spawns the same binary and completes the same handshake in the ordinary
   test suite — no master, no NIC, no MCU — and the simulator carries an
   EtherCAT world (`tools/sim/tests/test_ethercat_world.py`) that boots klippy
   against it with X and Y on servos and Z on a stepper. If those are green and
   this step is not, suspect the config or the host, not the claim path.
2. **Test the halt, still on the stub.** The drives are off and the stub
   answers `Stop` and `SetTorque` exactly as the real endpoint does, so this
   costs nothing and proves the wiring before any drive is live.
   `QUERY_EMERGENCY_STOP STOP=estop` reports `clear`. Press the stop: klippy
   shuts down naming it, and the same query — which still answers during a
   shutdown — reports `ASSERTED`. That reading is frozen at the moment of the
   stop, so releasing the button will not clear it; `FIRMWARE_RESTART` first,
   and then the query reads `clear` again.

   `clear` with the button held means the second contact is not on `PF1`.
   No shutdown at all means the contact is NO where the config expects NC.
3. **Real endpoint, motors uncoupled.** Comment the `endpoint:` line out
   again — unset, it is `rust/target/release/ethercat-rt` in this checkout, built
   by the host page's endpoint step
   (`make -f Makefile.rust ethercat-endpoint-hw`). klippy spawns it itself at
   claim time; it is never launched by hand. Expect `ready` and a log line
   naming the profile and matched identity.
4. **Torque on, no motion.** `SET_STEPPER_ENABLE STEPPER="axis x" ENABLE=1`
   enables torque on the node — both drives — and `M18` disables it; the
   quotes are needed, because the rails are registered as `axis x` and
   `axis y`. Both drives reach Operation Enabled and hold position: with the
   belts off each shaft pushes back when turned gently by hand. Do not force
   it — past the 2 mm `following_error`, about 18° of shaft at
   `rotation_distance: 40`, the drive faults. `engine_state` stays running and
   never reaches `Fault (3)`.
5. **Small supervised jog.** `SET_KINEMATIC_POSITION`, then short `G1 X…` and
   `G1 Y…` moves. An X move turns **one** motor; a Y move turns **both**. Seeing
   that is the cheapest confirmation the kinematics matches the mechanics.
6. **Check the coupling sign.** With belts slack, hold the X motor still and
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
7. **Home Z and the extruder** as on any stepper machine.
8. **Couple the belts and home slowly.** Low `homing_speed`, hand on the power.

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

A `params:` block on the `[motor]` section, for values that must come back on
their own, one per line as `0xINDEX.SUB: [type] value` — the type is optional,
and omitting it costs one SDO upload at claim to probe the object's size:

```ini
[motor motor_x]
# ... the options from Part 11 ...
params:
  0x3016.0: u16 300
  0x3014.0: u16 40
```

These are written at claim time, every start, in the order given.

**Nothing here writes the drive's EEPROM.** Both routes push to drive RAM and
kalico never persists implicitly, so what differs is who puts the value back: a
`SERVO_PARAM SET` at the console is gone the moment anything restarts, because
nothing re-sends it, while a `params:` entry is re-pushed on every claim and so
comes back after a host restart *and* a drive power cycle alike. The console is
for trying a value; `params:` is for keeping one. To write EEPROM deliberately,
SET the CiA 301 store-parameters object `0x1010` — the magic value is in the
drive manual. Leaving it alone is the point: `printer.cfg` is then the record of
how the machine is tuned, and a replacement drive is brought back from the
config rather than from whatever its EEPROM happens to hold.

**A bad `params:` line stops the machine starting, on purpose.** Each write is
read back, and a mismatch — clamped or rejected — fails the claim, naming the
address, the value written and what the drive settled on. Objects wider than
4 bytes fail loudly, and SDO traffic is mailbox traffic: it rides between DC
cycles, fast but not deterministic, so anything needing hard-real-time
parameter changes has to be mapped into the PDO instead.

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
| `A.23` | brake overcurrent | bleeder resistor too small — below the manual's 50 ohm |
| `A.15` | bleeder resistor error | the external resistor itself: open circuit, or wired to the wrong pair |
| `A.16` | regeneration error | the regenerative *circuit*, which the manual ties to the wrong resistor being fitted — check the value and that `Pn521.0` is `0` |
| `A.06` | position error pulse overflow | `Pn504`; also a phase-order or tuning symptom |
| `A.25` | motor line U overcurrent | U/V/W phase order, or mechanical seizure |
| `A.10` / `A.22` | encoder / sensor break | CN2 wiring, shield, 5 V |
| `rc=-2` | no slave matched | vendor/product identity, not necessarily the cable |
| `rc=-4` | a drive never reached OP | read the per-slot `al_state`/`al_status` lines printed with it |
| `rc=-6` | the drive refused the PDO map | an object in the map this drive does not have, or a fixed map — `pdo_touch_probe` / `pdo_digital_io` / `pdo_following_error` drop the optional groups without a rebuild |
| `rc=-21` | profile identity missing or zero | `vendor_id` **and** `product_code` both set, from Part 10 |

`rc=-2` deserves emphasis: a drive that is present but of a different identity
looks **exactly** like an absent one to the master. The endpoint names the
profile and identity it matched on, so read that line before suspecting wiring.

**`rc=-4` is the one to expect first on ProNet**, because the profile still
carries assumptions inherited from the drive family this fork was built
against. The endpoint prints what it assumed alongside either failure — the
variable `1600h`/`1A00h` remapping, and the following-error window `6065h` and
timeout `6066h` — so the message names the assumption that broke rather than
leaving a bare code.

`rc=-6` was the other one to expect, and the `estun-pronet` profile now maps
less to make it less likely: the touch-probe objects (`60B8h` out,
`60B9h`/`60BAh`/`60BCh` in) and the digital I/O (`60FEh:01` out, `60FDh` in)
are dropped, along with `60F4h`. That is not a guess about ESTUN's dictionary —
**nothing in the endpoint reads or writes any of them.** `touch_probe` and
`phys_outputs` are never assigned, so they were putting constant zeros on the
wire, and the four input entries were registered and never read. Dropping them
takes a ProNet's process image from 46 bytes per drive per cycle to 26.

The endpoint prints the map it built at bring-up — which groups are on and the
resulting byte counts — so the log says what the drive was actually asked for.
If a map is still refused, the three `pdo_*` options above move the remaining
groups without a rebuild.

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
- The Markforged belt coupling sign (Part 12, step 6 checks it).
- `ec_dwmac-rk`, if the CB2 is the host: it compiles and its symbols resolve,
  but it has never been loaded. A Pi 5 host avoids this one entirely.
- Whether 60 W per drive is enough regenerative capacity for this gantry. The
  figure is the drive manual's recommendation, not a measurement against this
  machine's moving mass; `A.13` under hard decel is what says otherwise.
- Three values that belong to the `-EC` variant and cannot be confirmed against
  the base ProNet manual: `Pn006.0 = 4` (that manual's `Pn006` range stops at
  `0x2133`), and the alarm codes **`A.70`** and **`A.71`** (its alarm table runs
  `A.00` to `A.69`).
- The CN2 encoder pinout, which is an inference by elimination rather than a
  quotation — the manual prints it only under a 17-bit heading (Part 6,
  *Encoder*).

Every other drive value in this document — the `A.06`, `A.10`, `A.13`, `A.22`
and `A.25` meanings, the U/V/W to A/B/C mapping, the encoder resolutions, and
every `Pn` in Part 13 with its unit and range — was read back out of that
manual and matches.

## See also

- [`markforged-cb2-complete-build.md`](markforged-cb2-complete-build.md) —
  every step of this build collated into one document for the CB2 route,
  with wiring diagrams and what this fork adds over base Serval. Follow
  that one to build; read these for the reasoning behind each decision.
- [`ethercat-host-cb2-rk3566.md`](ethercat-host-cb2-rk3566.md) — the CB2 host:
  kernel, IgH master, `ec_dwmac-rk`, and the endpoint build.
- [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) — the Pi 5 host
  alternative, kernel and EtherCAT master build.
- [`ethercat-bench-bringup.md`](ethercat-bench-bringup.md) — drive profiles, SDO
  parameters, telemetry capture, and the real-time scheduling rules in depth.
