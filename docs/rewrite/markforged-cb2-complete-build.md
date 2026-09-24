# One machine, start to finish: Markforged servo printer on a CB2 host

Everything needed to take a mechanically assembled, electrically bare
Markforged printer to a homing, tuned, closed-loop machine — collated from the
separate documents in this repository into one sequence, for the **CB2 host
route**, written to be read top to bottom by someone who has built a Klipper
printer but never touched a servo drive.

---

## Read this before anything else

> ### This is a personal project. Do not follow this guide.
>
> This document describes one person's machine. It is published because the
> repository is public, not because it is an instruction anyone else should
> act on. **It is not a product, not a kit, not a validated design, and it has
> not been reviewed by anyone qualified to review it.**
>
> Three specific reasons not to treat it as a build guide:
>
> 1. **It involves 230 VAC mains wiring inside a machine you are standing
>    next to.** Mains work is notifiable in some jurisdictions and lethal in
>    all of them. This document says what to connect. It says nothing about
>    who is competent to connect it, and nothing here constitutes a
>    qualification.
> 2. **The machine has no safety-rated stop of any kind.** These drives have
>    **no STO** — no safety function appears anywhere in the ProNet manual.
>    The emergency stop here is a plain contactor dropping out, which is a
>    Category 0 stop with no monitoring, no mirrored contacts and no safety
>    relay. The button latches and takes a key to release — that part is
>    sound — but nothing watches the contactor, nothing detects a welded pole,
>    and nothing holds the circuit dropped out once the key turns. An
>    industrial machine would use a safety relay and a contactor with mirror
>    contacts. This one does not.
> 3. **Large parts of it have never run on hardware.** The CB2 host path in
>    particular compiles and has never been loaded. See
>    [Still unverified](#still-unverified-on-hardware) for the honest list.
>
> Servo motors are not steppers. A stepper that meets an obstruction slips. A
> servo pushes harder until something yields. On this gantry's 20-tooth
> pulley — 40 mm of belt per turn — a drive at Stage K's 100 % limit pulls
> about 200 N, and about 600 N at the 300 % the drive allows. There is no
> skipped-step failure mode to save you.
>
> If you are reading this for ideas, take the ideas. Do not take the wiring.

### Safety rules that apply to every stage

- These drives run on **230 VAC** and their DC bus **stays charged after the
  supply is removed**. Every drive has a `CHARGE` lamp for exactly this
  reason.
- Unplug the machine — every cord, if it has more than one — and **lock the
  isolator off** before touching drive terminals or motor leads.
- After powering down, **wait five minutes and confirm `CHARGE` is out**. The
  lamp is the authority, not the clock.
- **"Dead" in this document means electrically dead** — made dead and proved
  dead. A drive that has failed is *destroyed* or *faulted*, never "dead".
- **The emergency stop does not make the machine dead.** It removes torque by
  opening the contactor. Control power stays on deliberately, so the drives
  can be told to halt cleanly. Only the isolator, locked off and proved,
  makes the enclosure safe to work in.
- **The button latches and takes a key to release; the circuit behind it does
  not latch.** Turn the key and main power comes straight back, with no
  separate reset step. Never release it to "see what happened" — you have just
  re-energised the enclosure you are standing in. **Take the key out** and
  nobody else can, which is worth doing and is still not a lock-off.
- Never plug or unplug a drive connector with power applied.
- Power sequencing: control power (`L1C`/`L2C`) **on first**, main circuit
  (`L1`/`L2`) second. Reverse on shutdown.
- **Keep the belts uncoupled** until Stage L says otherwise.
- Nothing here needs a drive opened. If a step seems to, stop.

---

## What you are building

| Role | Part |
| --- | --- |
| X, Y motors | 2x ESTUN `ProNet-04AEG-EC` drive + `EMJ-04AFD22` motor |
| Z | one TMC2209 stepper, Manta slot Motor3 |
| Extruder | two TMC2209 steppers (Motor5, Motor6), driven as one tandem axis |
| Mainboard | BigTreeTech Manta M8P V2.0 (**STM32H723ZET6**, 8 driver slots) |
| Host | BTT CB2 (Rockchip **RK3566**) in the Manta's BTB socket |
| Servo supply | single-phase 230 VAC, >= 1.8 kVA |

The servos replace the X and Y **steppers only**. Everything else stays a
conventional Klipper printer.

```
   ┌──────────────────── Manta M8P V2 ─────────────────────┐
   │  CB2 module (RK3566) ── klippy + ethercat-rt endpoint │
   │      │                                                │
   │      │ (on-board BTB link)                            │
   │  STM32H723 ── Motor3 TMC2209 ──> Z stepper            │
   │      │        Motor5 TMC2209 ──> extruder A           │
   │      │        Motor6 TMC2209 ──> extruder B           │
   │      └── endstops ^PF4 / ^PF3 / ^PF2, e-stop ^PF1,    │
   │          heaters, fans                                 │
   │  Motor1, Motor2 slots: EMPTY (X/Y are servos)         │
   └───────────────────┬───────────────────────────────────┘
                       │ eth0  (EtherCAT — no IP address)
          [CN3] ProNet X [CN4] ──> [CN3] ProNet Y [CN4]
                │                        │
            EMJ motor X               EMJ motor Y
            (T-shaped belt)           (straight loop)
```

**Lane assignment — everything downstream depends on this:**

- **Lane 0 = X motor**, on the T-shaped belt. Carries `x + y`.
- **Lane 1 = Y motor**, on the straight frame loop. Pure `y`.

A lane's motors must all be the same drive type, but lanes may differ. X and Y
are servo lanes, Z is a stepper lane, and the extruder is a **follower axis**
carrying two steppers that always move together.

The Manta also carries the **endstops for the servo axes** — a servo axis homes
against a GPIO endstop on any bridge MCU, exactly like a stepper machine's.

---

## Coming from steppers: the six ideas that make the rest readable

**A servo knows where it is; a stepper assumes.** A stepper is told "take 200
steps" and trusted. A servo has an encoder on the shaft, so the drive compares
commanded against actual every cycle and applies whatever current closes the
gap. Skipped steps stop being a failure mode. A jam becomes one.

**The drive is a separate computer.** Each ProNet is its own controller with
its own parameters, faults and front panel. Klipper does not manage it the way
it manages a TMC2209. Faults latch *in the drive*, and some survive a host
reboot — clearing those needs a drive power cycle, not a `FIRMWARE_RESTART`.

**EtherCAT is the wire between them, and it is hard real-time.** Every cycle —
250 microseconds here, 4000 times a second — the host sends each drive a new
target position and reads back where it is. A frame that arrives *late* is a
fault, not a delay. This is the whole reason for the real-time kernel and the
isolated CPU core.

**Distributed clocks (DC) and SYNC0.** All drives share one clock so they act
on their targets at the same instant. SYNC0 is the pulse marking that instant.
Miss it and the drive decides the master has lost the plot and latches `A.70`.
Most first bring-up trouble is a version of this.

**Following error** is commanded minus actual position. Healthy is small and
steady. Growing means the machine is fighting something, and the drive trips
rather than forcing through.

**Torque limit** is how hard the drive may push, as a percentage of rated.
Keep it low during first moves.

**Homing still happens.** These motors have incremental encoders, so the drive
knows its position relative to power-on, not to the machine origin. Every axis
homes on every power-up.

| Term | Meaning |
| --- | --- |
| CiA 402 | the standard vocabulary drives speak for position, velocity, torque |
| CoE | that vocabulary carried over EtherCAT |
| PDO | data exchanged *every cycle* — target position, actual position, torque |
| SDO | occasional settings, sent once at startup or on a parameter change |
| CSP | Cyclic Synchronous Position — the mode this build streams positions in |
| PREOP / SAFEOP / OP | the bus states a drive walks through; `OP` is running |
| ESI | the XML file describing a drive, published by its maker |

---

## Wiring diagrams

Five drawings. Everything in the stages below refers back to one of them.

### 1. Mains chain, wall to drives

The order is not arbitrary: each device either protects what follows it or has
to sit somewhere specific to work at all.

```
  BS1363 13 A plug
        │  (H05VV-F 3G1.5 — its CPC is the machine's ONLY earth)
        ▼
   ┌─ C20 inlet (16 A) ──────────────────────────────────────────────┐
   │                                                                  │
   │   L ─► [1] ISOLATOR ─► [2] MCB ─► [3] RCD ─► ... ──┐             │
   │   N ─►  SD202/32       S201-C16   F202 A-25/0.03   │             │
   │        2-pole          16 A       30 mA            │             │
   │        LOCKABLE        Type C     TYPE A           │             │
   │        ▲                                            │            │
   │   the ONE lock-off point                            │            │
   │                                                     ▼            │
   │                              [4] SPD (optional, short leads)     │
   │                                    A9L20500                      │
   │                                          │                       │
   │                                          ▼                       │
   │                          [5] EMC FILTER ── bolted metal-to-metal │
   │                              DRF10           AT THE DRIVES       │
   │                                 │                                │
   │             ┌───────────────────┴──────────────┐                 │
   │             │                                  │                 │
   │      L1C/L2C tap                        [6] CONTACTOR            │
   │   (CONTROL POWER —                       ESB20-20N-06            │
   │    bypasses the                          230 V coil              │
   │    contactor                                  │                  │
   │    ON PURPOSE)                                ▼                  │
   │             │                            L1 / L2                 │
   │             └──────────────┐            (MAIN CIRCUIT)           │
   │                            ▼                  │                  │
   │                    ┌───────────────┬──────────┴────────┐         │
   │                    ▼               ▼                   ▼         │
   │              ProNet X        ProNet Y             (both drives)  │
   └──────────────────────────────────────────────────────────────────┘

   CONTACTOR COIL CIRCUIT  (fed from the LOAD side of the RCD):

        RCD load ──► [E-STOP NC contact #1] ──► A1 ┌─────┐ A2 ──► N
                          (breaks coil)            │COIL │
                                                   └─────┘
```

**Two placement rules carry most of the benefit and are the two most often got
wrong:** the **filter belongs at the drives**, bonded to bare metal, not at the
panel entry — a filter on a long lead filters almost nothing; and the **SPD's
leads must be short**, because what it lets through is its clamping voltage
plus the inductive kick of its own tails.

**Why control power bypasses the contactor.** `L1C`/`L2C` is control power and
`L1`/`L2` is the main circuit, and they are separate terminals precisely so
they can be switched separately. Take control power **from between the filter
and the contactor** and switch only the main circuit. The drive then stays
alive with its bus collapsing, accepts the `Stop`, disables torque, holds the
EtherCAT link up and reports its own state. Put both behind the contactor and
the drive loses power mid-frame; the halt is sent into nothing.

**Between the filter and the contactor, not simply upstream of the contactor.**
The convenient tap is the terminal rail at the enclosure edge, ahead of the
filter — and that is the wrong one. It puts the drive's own control
electronics and their switching straight onto unfiltered mains, which is the
conducted-emissions path the filter exists to close.

**The cost of that choice, stated plainly: pressing the emergency stop does
not make the drive dead.** It makes the motor safe to be near — no torque,
nothing held, because the DC bus is gone — while the drive's electronics stay
live at 230 V. Those are different states and the stop only reaches the first.

### 2. Emergency stop — two contacts, both NC

```
                     ┌──────────────────────────┐
                     │   E-STOP (RS 139-972)    │
                     │   LATCHING, KEY RELEASE  │
                     │   — stays in until a key │
                     │     turns it; no twist   │
                     │   TWO NC CONTACTS        │
                     └───┬──────────────────┬───┘
                         │                  │
        contact #1 ──────┘                  └────── contact #2
        (mains side)                               (signal side)
             │                                           │
             ▼                                           ▼
   in series with the                        Manta  ^PF1 ◄── contact ──► GND
   CONTACTOR COIL                                    (Motor4 endstop input,
   (RCD load side)                                    free in this build)
             │                                           │
             ▼                                           ▼
   opens contactor:                          klippy invoke_shutdown:
   MAIN POWER OFF                            ethercat_node.stop_node()
   (this is the safety function)             (this is the clean halt)
```

**Use NC contacts, both of them.** With `pin: ^PF1` the input is pulled up and
the contact goes to ground, so:

| Contact | | Not pressed | Pressed | Wire pulled off |
| --- | --- | --- | --- | --- |
| **NC** — `pin: ^PF1` | pin reads | low | high | high |
| | **asserted** | no | **yes — halts** | **yes — halts** |
| NO — `pin: ^!PF1` | pin reads | high | low | high |
| | **asserted** | no | yes — halts | no — **nothing** |

A broken signal wire on an NC contact looks exactly like a pressed button and
the machine stops. On NO the same fault is silent, and you discover it by
pressing the stop and watching nothing happen. A button with two NC contacts
needs no NO contact anywhere.

### 3. One drive's terminals

```
   ┌──────────── ESTUN ProNet-04AEG-EC ─────────────┐
   │                                                 │
   │  L1  L2  ◄── main circuit, THROUGH the contactor│
   │  L3      ◄── unused (single phase)              │
   │  L1C L2C ◄── control power, from the FILTER,    │
   │              upstream of the contactor          │
   │                                                 │
   │  +1  +2  ◄── DC reactor — LEAVE FACTORY LINK IN │
   │  B1  B2  ◄── external regen resistor, 50 Ω 60 W │
   │              (04A frame ships with NO internal  │
   │               resistor; B2-B3 belongs to 08A+)  │
   │                                                 │
   │  U  V  W ──► motor A(1), B(2), C(3)             │
   │  PE      ──► ground plate (4 mm²)               │
   │                                                 │
   │  CN2 ◄────── encoder (20-bit serial incremental)│
   │  CN3 ◄────── EtherCAT IN                        │
   │  CN4 ──────► EtherCAT OUT                       │
   │  CN1        20-pin, 5 sequence inputs (unused)  │
   │  mini-USB   panel/ESView parameter access       │
   │                                                 │
   │  [POWER] green — control power present          │
   │  [CHARGE] red  — DC BUS LIVE. WAIT FOR IT TO GO │
   └─────────────────────────────────────────────────┘
```

**Motor phase order is not cosmetic.** `U`→`A(1)`, `V`→`B(2)`, `W`→`C(3)`,
`PE`→`D(4)`. A swapped pair makes the drive fight its own feedback and trips
`A.25` (motor power line U overcurrent) on the first enable.

**Encoder, CN2.** The `F` encoder is 20-bit serial incremental, 1,048,576 P/R,
so CN2 uses the serial pinout:

| CN2 pin | Signal | Note |
| --- | --- | --- |
| 7 | `PS` | serial data |
| 8 | `/PS` | serial data |
| 9 | `PG5V` | encoder +5 V |
| 19 | `GND` | encoder 0 V |
| Shell | Shield | terminate properly |
| 17, 18 | `BAT+`, `BAT-` | **absolute encoders only — leave unused** |

⚠ **This table is an inference, not a quotation.** The manual prints this
pinout under the heading "17 Bit Incremental/Absolute Encoder" and publishes no
separate 20-bit layout; the only alternative it gives is the 2500 P/R
quadrature wire-saving layout, which is plainly not this encoder. **Confirm it
against the cable before crimping anything.**

Because the encoder is incremental there is **no backup battery and no battery
cable**, and both axes home on every power cycle.

### 4. EtherCAT chain

```
   CB2 eth0 ──► [CN3] ProNet X [CN4] ──► [CN3] ProNet Y [CN4]  ← leave empty
                   index 0                    index 1
```

EtherCAT is **direction-sensitive**. IN to OUT, no switch, no ring. An
OUT-to-OUT link or a switch in the path gives a bus that enumerates
inconsistently or not at all.

**Physical order on the wire sets the chain index.** First drive from the host
is index 0, second is index 1. Label the drives now — Stage J must match.

### 5. Manta M8P V2.0 wiring

```
   Motor1  ─ EMPTY ─ X is an EtherCAT servo
   Motor2  ─ EMPTY ─ Y is an EtherCAT servo
   Motor3  ─ TMC2209 ─ Z        step PB8   dir !PB7  en !PE0  uart PB9
   Motor4  ─ EMPTY ─ (its endstop input PF1 becomes the e-stop signal)
   Motor5  ─ TMC2209 ─ extruder A  step PG13  dir PG12  en !PG15  uart PG14
   Motor6  ─ TMC2209 ─ extruder B  step PG9   dir PD7   en !PG11  uart PG10
   Motor7  ─ EMPTY
   Motor8  ─ EMPTY

   ENDSTOPS (all pulled up — the ^ is load-bearing, see below)
     ^PF4 ─ X endstop  → serves the X SERVO axis
     ^PF3 ─ Y endstop  → serves the Y SERVO axis
     ^PF2 ─ Z endstop
     ^PF1 ─ EMERGENCY STOP signal contact

   HEAT / FANS
     PA0 (HE0) hotend heater      PB0 (T0)  hotend thermistor
     PF5       bed heater          PB1 (TB) bed thermistor
     PF7 (Fan0) part cooling fan
```

Every row is taken from BigTreeTech's own published configuration,
`V2.0/Firmware/generic-bigtreetech-manta-m8p-V2_0.cfg` in
[`bigtreetech/Manta-M8P`](https://github.com/bigtreetech/Manta-M8P) —
**including the slot numbers, which start at Motor1, not Motor0.** `PB8` is
Motor3 there. Counting from zero puts every stepper in the wrong socket.
`PG9` is the **step** pin of Motor6 on this board and is unrelated to the
similarly named pin on other boards. Pin names do not transfer between
mainboards.

**Every one of those four inputs wants the `^` pull-up.** Nothing supplies one
by default: an `endstop_pin` without the prefix configures the STM32 input with
no pull-up at all, so a switch wired to ground floats the moment it opens and
the axis homes against noise. It is three characters, it is invisible when
wrong, and it reads exactly like a flaky switch.

**Cable separation — and which cables, because "power and signal" is not a
list.** ESTUN's number is **300 mm** between power and signal runs, never in
the same duct or bundle. On this machine that means these, specifically:

**The aggressors — route everything else away from these:**

| Cable | Why it is noisy |
| --- | --- |
| **Servo motor power**, drive `U`/`V`/`W` → motor (×2) | The worst one on the machine. PWM at the drive's carrier frequency with high dV/dt, and it runs to the same place as its own encoder cable |
| **Regenerative resistor leads**, `B1`/`B2` (×2) | The braking transistor switches these hard, and only on decel — so the noise arrives exactly when the gantry is moving fastest |
| **Mains, filter output to drives** — `L1`/`L2` and `L1C`/`L2C` | Filtered, but still 230 V carrying two rectifiers' inrush |
| **Mains upstream of the filter** | Unfiltered, and the reason the filter belongs at the drives rather than at the enclosure edge |
| **Bed heater leads** to `PF5` | High current, switched |
| **Stepper leads**, Motor3 / Motor5 / Motor6 | Chopper switching. Far less than the servos; not nothing |

**The victims — these are what the separation is protecting:**

| Cable | Why it is sensitive | What it looks like when it goes wrong |
| --- | --- | --- |
| **Encoder**, drive `CN2` → motor (×2) | 20-bit serial data, and the most sensitive run on the machine | `A.10` / `A.22`, or a panel position display that jumps or freezes |
| **EtherCAT patch leads**, host → `CN3`, `CN4` → `CN3` | 100BASE-TX is robust, but the failure is catastrophic rather than noisy | `A.70`, `al_status=0x001a`, endpoint halt on a working-counter fault |
| **Emergency-stop signal** to `^PF1` | The longest low-voltage run on the machine, held up through tens of kΩ | the machine stops mid-print for nothing |
| **Endstops** to `^PF4` / `^PF3` / `^PF2` | The same pull-up impedance, shorter runs | homing against noise instead of the switch |
| **Thermistors** to `PB0` / `PB1` | High-impedance analogue | temperature jitter, spurious heater errors |
| **TMC2209 UART**, `PB9` / `PG14` / `PG10` | Short, and inside the board's own loom | driver communication errors |

One cable that is *not* on either list: **the MCU link**. The CB2 sits in the
Manta's BTB socket and the USB link to the STM32 runs across the connector, so
there is no external cable to route. A Pi-5 host has one and has to.

**The pair you cannot separate, which is the whole problem.** The motor power
cable and the encoder cable go to the **same motor** — they leave the same
drive, arrive at the same place, and on a moving gantry they share a drag
chain. That is the worst aggressor and the most sensitive victim, with no
distance available between them. It is why ESTUN sells both as screened
assemblies (`PDM-GD12` power, `PBP` encoder), why the power cable's screen is
bonded at the drive end, and why — if they must share a chain — they go on
opposite sides of it with the quieter cables in between.

A printer cannot give you 300 mm and this document will not pretend otherwise:
the whole machine is smaller than the separation. What replaces the distance,
in descending order of value:

- **Cross at right angles** where runs must meet, never parallel. Coupling
  falls off sharply with angle and a crossing is nearly free.
- **Twisted pair with the return in the same twist**, so the loop area the
  noise couples into is small rather than the whole run.
- **Screened cable for signal runs**, screen landed at the **Manta end only** —
  one end, or it becomes a ground loop between two earths.
- **Separate looms and separate ducts.** Losing the distance is not a reason to
  also lose the separation; "not in the same duct" costs nothing in a printer
  and is the half of the rule you can actually keep.

Be honest about what that leaves: 300 mm is what the drives were qualified
against and everything above is a substitute, not an equivalent. If an endstop
or the stop input misbehaves once the servos are moving, **this** is the first
place to look and the code is the last.

The emergency-stop signal deserves the most care of the four. It is the longest
low-voltage run on the machine, out to a button on a panel, and `^PF1` holds it
up through the STM32's internal pull-up of tens of kilohms — a high impedance
looking at a cabinet full of switching. Noise cannot *mask* a press (an open
contact stays open) but it can *assert* one: the machine stops mid-print for
nothing. Twisted pair with the return to ground, off the motor loom, and if
trips still appear set `debounce_delay` on `[emergency_stop]` before suspecting
the button.

---

# Stage A — Parts

Counts are for the servo pair and the supply feeding it. The printer's frame,
bed, hotend and host board are assumed. RS stock numbers pin one specific part
down; any distributor's equivalent is the same purchase. **The named parts are
illustrations of the right class, not a validated bill of materials** — the
drive manual and local wiring regulations both outrank this table.

### Per drive — two of each

| Item | Part | RS |
| --- | --- | --- |
| Servo drive | ESTUN `ProNet-04AEG-EC` | — |
| Servo motor | ESTUN `EMJ-04AFD22` | — |
| Encoder cable | ESTUN **PBP** series — `PBP` is incremental; a `PDP` (absolute) cable is the wrong part for the `F` encoder | — |
| Motor power cable | ESTUN `PDM-GD12-XX`, or 1 mm² self-made | — |
| Regenerative resistor | 50 Ω, and 60 W **at the mounting it gets** — see the table below | **252-2928** |
| EtherCAT patch lead | Shielded Cat5e or better, 100BASE-TX | — |

The regenerative resistor is **per drive, not per machine**: each drive
switches its own braking transistor across its own `B1`/`B2`, and both axes of
a Markforged gantry decelerate hard.

Two EtherCAT leads for two drives, because the chain starts at the host: host
to drive 0, drive 0 to drive 1.

### Once for the pair — the mains chain

Every row here is **one**, not two. The drives share the chain because they
share the supply: 7.83 A for the pair sits inside a single 16 A circuit.

| Item | Part | RS |
| --- | --- | --- |
| Isolator | ABB `SD202/32` — 2-pole, 32 A, lockable, 2 modules | **175-5085** |
| MCB | ABB `S201-C16` — 16 A **Type C**, 1 module | **489-0447** |
| RCD | ABB `F202 A-25/0.03` — 30 mA **Type A**, 2 modules | **488-6915** |
| EMC filter | Roxburgh `DRF10` (≤45 °C ambient) **or** Schaffner `FN2412-16-44` (≥50 °C) | **761-5696** / **518-6389** |
| Contactor | ABB `ESB20-20N-06` — 20 A AC-1, 230 V coil, 1 module | **211-1482** |
| Emergency stop | **Latching, key release, with two NC contacts** — one in series with the contactor coil, one to `PF1`. RS PRO, 1 NC/1 NC, IP65, **through-hole** so it needs a panel to sit in. The same family runs to a 2 NC + 1 NO variant, deliberately not used: the NO contact is the one this circuit must not have | **139-972** |
| Coil suppressor | *Optional.* RC network 0.1 µF + 100 Ω, **Class X2**. Not needed behind the `ESB20-20N-06` | — |
| SPD | *Optional.* Schneider `A9L20500` iPRD20 | **654-748** |
| DIN rail | 35 mm top-hat + two end stops | — |
| Terminal blocks | 3 — L, N, PE feed-through with jumper links, sited at the filter output | — |
| Mains cable to drives | 3-core flexible 300/500 V; 1.5 mm² carries 7.83 A, **2.5 mm²** for volt-drop margin | — |
| Mains inlet | Schurter `EC11.0031.001` **C20** (16 A) | **870-3413** |
| Mains lead | C19 to **BS1363**, H05VV-F 3G1.5. Check the title says BS1363 or Type G — RS lists C19 leads with Schuko plugs under nearly the same description | **311-9315** |
| Protective bonding | 4 mm² green/yellow, main earth terminal to ground plate, ring-terminated | — |

**One substitution is worth making:** an RCBO — ABB `DSE201 M C16 A30`
(**136-7786**) or Siemens `5SV1316-7KK16` (**187-3289**) — replaces the MCB
**and** the RCD, turning 53 mm of rail into 36 mm or 18 mm. Check the
earth-leakage type on the datasheet, not the listing: distributors routinely
print the *curve* letter (C) in the field meaning the *RCD* type, and a Type AC
device there is the one failure mode that matters.

### One for the machine

| Item | Part |
| --- | --- |
| Drive debug cable | **mini-USB**, double shielded with ferrites. Moved between drives, not duplicated — the `-EC` variant uses mini-USB, not the base drive's RS-485 |

### Printer side, changed by this conversion

| Item | Qty | Note |
| --- | --- | --- |
| TMC2209 drivers | 3 | Z, extruder A, extruder B. **Motor1 and Motor2 stay empty** |
| Endstop switches | 3 | X, Y, Z |

### Regenerative resistor wattage — the row that catches people

An aluminium-housed resistor is rated for a heatsink it will not get in a
printer. Arcol's HS series publishes both numbers:

| | On the datasheet's heatsink | Free-standing |
| --- | --- | --- |
| `HS100` | 100 W | **30 W** |
| `HS150` | 150 W | 45 W |
| `HS300` | 300 W | **60 W** |

The heatsink earning the first column is about 995 cm² of 3 mm plate for an
`HS100` — roughly a 315 mm square, which no printer has spare. Either bolt the
resistor to real metal with thermal compound and count on something between the
columns, or read the right-hand column: an `HS300 50R` free-standing meets the
manual's 60 W with nothing attached.

**50 Ω is a floor, not a target.** Below it the braking transistor passes more
current than it is rated for; the drive watches for this and trips `A.23`. More
wattage at 50 Ω is always safe — only the resistance has a wrong answer. Two
100 Ω in parallel or two 25 Ω in series both hold 50 Ω at double the
dissipation, and on burst duty the element's thermal mass matters more than the
headline continuous rating.

**Mount it away from the encoder and EtherCAT runs.** It reaches temperatures
that mark cable insulation, and whatever it dissipates lands in the same bay as
the drives, against the 45 °C they want for long-term reliability. Vent it or
site it outside the electronics bay.

---

# Stage B — The CB2 host

> **Read this first.** The CB2 path has **never been run**. The driver
> compiles and its symbols resolve; nothing here has been loaded on hardware.
> The Raspberry Pi 5 route
> ([`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md)) *has* been
> exercised on the bench, and anyone bringing up a printer for the first time
> should use that instead — a fault then has one candidate cause instead of
> two. This document follows the CB2 because that is what this machine uses.

|  | Pi 5 | **CB2 (this build)** |
| --- | --- | --- |
| SoC | BCM2712 + RP1 | Rockchip RK3566 |
| Ethernet MAC | Cadence GEM (`macb`) | Synopsys DesignWare (`stmmac`) |
| Native driver | `ec_macb` | **`ec_dwmac-rk`** |
| Kernel | 6.18.33 RPi OS RT build | **6.12+, PREEMPT_RT built in** |
| Status | exercised on the bench | **builds; never run** |

**Why a native driver at all.** IgH's `generic` driver pushes every frame
through the Linux net stack, and that jitter is what makes a drive miss SYNC0
and latch `A.70`. IgH ships native drivers for `e1000e`, `igb`, `r8169`,
`genet` and `macb` — **none of which match the RK3566.** `ec_dwmac-rk` is
generated for it by this repository's own tool. A Raspberry Pi CM4 in the same
socket is a different case: its BCM2711 GENET MAC is exactly what IgH's `genet`
driver is for, but that driver carries kernels 5.10 to 6.12 only and nothing in
this repository has built or run it.

## B1 — A 6.12 PREEMPT_RT kernel

**This comes first because it replaces the whole OS.** The image is built on
another machine — Armbian's build system, not the CB2 — and flashing it wipes
anything already on the board. Anything done before this step is done twice, so
everything else in Stage B is written to run on the image this produces.

Two independent requirements meet at 6.12:

- **PREEMPT_RT is built into mainline from 6.12.** Before that it was an
  out-of-tree patch that had to match the kernel exactly. From 6.12 it is
  `CONFIG_PREEMPT_RT`, a menuconfig option.
- **IgH's stmmac file set stops at 6.12.** The master ships EtherCAT-ified
  copies of the stmmac driver for 6.1, 6.4 and 6.12 only, and `ec_dwmac-rk` is
  generated against that set.

**BTT's own CB2 image ships Debian bookworm with kernel 6.1, which is too old
on both counts and cannot be used as-is.**

The CB2 is a supported Armbian board (`bigtreetech-cb2`). Its device tree,
`rk3566-bigtreetech-pi2.dts`, reached mainline Linux only in 6.14; on 6.12 it
comes from Armbian's own patch set, which is one more reason to build the image
with Armbian rather than from a plain 6.12 tree:

```sh
git clone --depth 1 --branch v25.11.1 https://github.com/armbian/build
cd build
./compile.sh BOARD=bigtreetech-cb2 BRANCH=current RELEASE=trixie \
             BUILD_MINIMAL=yes BUILD_DESKTOP=no \
             INSTALL_HEADERS=yes BSPFREEZE=yes \
             KERNEL_CONFIGURE=yes
```

`KERNEL_CONFIGURE=yes` opens menuconfig. Set, and confirm, each one:

| Menu path | Option | Value |
| --- | --- | --- |
| General setup → Preemption Model | `CONFIG_PREEMPT_RT` | Fully Preemptible Kernel (Real-Time) |
| General setup → Timers subsystem → Timer tick handling | `CONFIG_NO_HZ_FULL` | Full dynticks system (tickless) |
| Device Drivers → Network device support → Ethernet → STMicro | `CONFIG_STMMAC_ETH` | M |
| same | `CONFIG_STMMAC_PLATFORM` | M |
| same | `CONFIG_DWMAC_ROCKCHIP` | M |

**The tag is what makes this 6.12.** Armbian's `current` branch for this board
family moves with its releases, and `v25.11.1` is the last release where it is
6.12: from `v26.2.1` it is 6.18, and on `main` the board offers only 6.18
(`current`) and 7.2 (`edge`). IgH's stmmac set stops at 6.12, so an unpinned
clone offers no branch this build can use. Flash the image and boot it.

**Two more options on that line, and one in the table, are not optional.**
`INSTALL_HEADERS=yes` puts this kernel's own headers on the image, which the
IgH modules build against. `BSPFREEZE=yes` holds the kernel, headers, device
tree and bootloader packages: Armbian's repository publishes newer builds under
the same names — `linux-image-current-rockchip64` is 6.18 there, not RT — so
without the hold the first `apt upgrade` replaces this kernel and the EtherCAT
module no longer loads. And `CONFIG_NO_HZ_FULL` is what `nohz_full=3` and
`rcu_nocbs=3` in the core-isolation step need; without it the kernel ignores
both, and the isolation check still passes because `isolcpus` works regardless.

**✅ Check — all three must hold:**

```sh
uname -r                                  # 6.12.x
uname -v | grep -i preempt_rt             # must mention PREEMPT_RT
zgrep CONFIG_PREEMPT_RT /proc/config.gz   # =y  (if config.gz is present)
apt-mark showhold | grep linux-image      # linux-image-current-rockchip64
ls -d /lib/modules/$(uname -r)/build      # the headers B6 builds against
```

A kernel reporting `PREEMPT` rather than `PREEMPT_RT` is the ordinary
low-latency kernel and is **not sufficient** — it is exactly the configuration
that holds cadence on an idle bench and drops frames under load.

## B2 — Get off `eth0`, on the newly booted image

Step B7 gives `eth0` to the EtherCAT master, and once it does the interface
leaves the normal network stack **at every boot from then on**. On a CB2 in a
Manta socket there is usually no display attached, so **if SSH is on `eth0`
when that happens the board becomes unreachable.**

Put SSH on the CB2's Wi-Fi, reboot, and confirm you can still log in with the
Ethernet cable unplugged:

```sh
ip route get 1.1.1.1      # must NOT leave via eth0
```

Keep a serial console to hand regardless. Recovering a headless board whose
only route went to the EtherCAT master otherwise means pulling the eMMC.

## B3 — What to install on the CB2 first

A minimal Armbian image has none of this, and the steps below fail at four
different points without it. Install it all in one go rather than discovering
each one:

```sh
sudo apt update
sudo apt install -y \
    build-essential pkg-config git curl ca-certificates \
    autoconf automake libtool \
    libudev-dev libffi-dev \
    python3 python3-dev python3-pip python3-venv \
    gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
. "$HOME/.cargo/env"
```

What each is for, because a missing one fails somewhere that does not name it:

| Needed by | Without it |
| --- | --- |
| `autoconf automake libtool` | IgH's `./bootstrap` (B6) has nothing to run |
| kernel headers for the running kernel | already on the image from B1's `INSTALL_HEADERS=yes`. **Do not** `apt install linux-headers-current-rockchip64`: the repository's package of that name is the 6.18 build, and `make modules` (B6) needs this kernel's |
| `libudev-dev pkg-config` | the Rust build (B9) fails in the `serialport` crate, which links `libudev`. This one is easy to mistake for a Rust problem |
| `python3-dev libffi-dev` | klippy's `chelper` cannot compile its C at first start |
| `gcc-arm-none-eabi` and friends | the Manta firmware build stops at `arm-none-eabi-gcc: No such file or directory` |
| `rustup` | `rust/rust-toolchain.toml` pins Rust **1.85.0** and the `thumbv7em-none-eabi` target, so rustup fetches both on first build. A distro `rustc` is the wrong version and has no ARM target |

**The firmware build is the one no gate covers.** `ci.sh rust-mcu-h7` compiles
the Rust half of the MCU for `thumbv7em-none-eabi`; nothing in CI compiles the
C firmware or links `out/klipper.bin`, because no CI image carries an ARM
toolchain. A green gate therefore does not mean the firmware builds — the
first machine to find out is this one.

## B4 — Get this repository, and a klippy to run it

Everything from here on runs *inside a checkout*, and nothing so far has made
one: B6 runs `generate.py` out of `tools/`, B9 builds in `rust/`, and B8 writes
a drop-in for a `klipper.service` that does not exist yet.

**Install Klipper or Kalico first**, by whatever route you normally would —
[KIAUH](../Installation.md#installing-via-kiauh) is the usual one on an SBC.
That is what creates `~/printer_data/`, the klippy virtualenv, and the
`klipper.service` B8 extends.

**Install only what the printer needs from it** — klippy, Moonraker and one web
front end. Everything else on this board shares CPUs 0-2, the memory bus and
the one CPU clock with the DC loop, and the real-time gate at Stage L step 3
has to be passed with it running. A webcam streamer or KlipperScreen is load
the loop then lives with; add it before that gate, so the gate covers it, or
not at all.

Then bring it onto this fork:

```sh
cd ~/klipper                     # wherever your install put it
git remote add serval https://github.com/PDAMUK/serval.git
git fetch serval
git checkout <the branch carrying this document>
~/klippy-env/bin/pip install -r scripts/klippy-requirements.txt
```

The last line matters if KIAUH installed mainline Klipper: this fork's klippy
imports `numpy` at startup, and Klipper's own requirements do not carry it.

**It must be this fork, not base Serval.** `docs/Quickstart.md` points at
`dderg/kalico`, which is the upstream this one is built on and which carries
**no markforged kinematics, no `estun-pronet` drive profile, no
`[emergency_stop]` section and none of the `pdo_*` options**. A config written
to Stage K will be rejected by it. If you are reading this file from a
checkout, you are already on the right branch — it lives in `docs/rewrite/`.

[`../Quickstart.md`](../Quickstart.md) covers the rest of the switch and
[`../Config_Migration.md`](../Config_Migration.md) the config conversion; take
the branch and the build steps from here rather than from Quickstart, because
they differ for a CB2.

**✅ Check.**

```sh
cd ~/klipper && git log --oneline -1     # a commit from this fork
ls docs/rewrite/markforged-cb2-complete-build.md   # this document
~/klippy-env/bin/python -c "import numpy"          # no error
systemctl status klipper                 # the unit B8 will extend
```

## B5 — Isolate a core for the DC loop

The endpoint pins its cycle loop to one CPU and needs that CPU
contention-free. On Armbian, add to `/boot/armbianEnv.txt` via `extraargs=`:

```
isolcpus=domain,managed_irq,3 nohz_full=3 rcu_nocbs=3 irqaffinity=0-2 cpufreq.default_governor=performance
```

The RK3566 is quad-core, so CPU 3 is the last one.

**The last two keep the rest of the board off that core and its clock steady.**
`irqaffinity=0-2` makes CPUs 0-2 the default home of every device interrupt;
`managed_irq` covers only the drivers that ask for it. The governor matters
because the RK3566's four cores share one clock: Armbian ships `ondemand`, which
drops the whole cluster to 408 MHz whenever the board is quiet — and a board
running only the DC loop is quiet — so the loop's own work per cycle can take
four times as long as at 1.8 GHz, and every change reprograms the clock and
voltage the loop is running on.

**Then stop Armbian undoing the first one.** `armbian-hardware-optimize` runs at
every boot and, for this board family, writes CPU 3 into the affinity of every
`eth0` interrupt — the GMAC this build hands to EtherCAT, whose EtherCAT
driver requests the same interrupt line — and sets `ondemand`. It does this in the background,
racing the NIC handover, so no service ordering fixes it. Mask it:

```sh
sudo systemctl mask armbian-hardware-optimize.service
```

Its other work — the I/O scheduler, USB storage quirks — does not matter on
this board, and its log-rotation edit was made on the first boot already.

Reboot.

**It must be CPU 3, not "a core".** The endpoint pins to CPU 3 and nothing
reachable changes that: `--rt-cpu` exists on the binary, but klippy spawns the
endpoint itself and never passes it, and no `printer.cfg` option reaches it.
Isolate a different core and `sched_setaffinity(3)` still succeeds — it only
fails for a CPU that is offline or absent — so the loop pins to a core that is
*not* isolated while `chrt -p` reports `SCHED_FIFO 80` and
`Cpus_allowed_list` reports `3`. Every check in this guide passes and the loop
shares a contended core, which is the sync-loss failure that shows up only on
a cold boot under load.

**✅ Check:**

```sh
cat /sys/devices/system/cpu/isolated     # 3
cat /sys/devices/system/cpu/nohz_full    # 3 — absent or empty means CONFIG_NO_HZ_FULL is off
cat /proc/irq/default_smp_affinity       # 7 — CPUs 0-2
cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor   # performance
grep -lx 3 /proc/irq/*/effective_affinity_list   # prints nothing
```

## B6 — Build the IgH master with `ec_dwmac-rk`

The headers are already on the image — B1's `INSTALL_HEADERS=yes` — and B1's
check confirmed `/lib/modules/$(uname -r)/build`.

```sh
git clone -b stable-1.6 https://gitlab.com/etherlab.org/ethercat.git ~/ethercat-igh

# Generate the Rockchip binding and wire it into the tree.
python3 ~/klipper/tools/ethercat-dwmac-rk/generate.py \
    --igh  ~/ethercat-igh/devices/stmmac \
    --work /tmp/ec-dwmac \
    --install ~/ethercat-igh

cd ~/ethercat-igh
./bootstrap
./configure --prefix=/opt/etherlab \
            --with-linux-dir=/lib/modules/$(uname -r)/build \
            --with-stmmac-kernel=6.12 \
            --enable-dwmac-rk \
            --disable-8139too --disable-eoe
make && make modules
sudo make install && sudo make modules_install
sudo depmod -a
sudo ln -sf /opt/etherlab/bin/ethercat /usr/local/bin/ethercat   # the tool every later check runs
```

See [`tools/ethercat-dwmac-rk/README.md`](../../tools/ethercat-dwmac-rk/README.md)
for what the generator does and what it verifies.

Put the library on the linker path, or the endpoint fails at runtime with
`libethercat.so.1: cannot open shared object file`:

```sh
echo /opt/etherlab/lib | sudo tee /etc/ld.so.conf.d/ethercat.conf
sudo ldconfig
```

**✅ Check:**

```sh
ls /lib/modules/$(uname -r)/ethercat/devices/stmmac/ec_dwmac-rk.ko
modinfo ec_dwmac-rk | head -5
```

Then confirm the module was built against the **running** kernel, not some
other tree. This matters more here than on a Pi 5: there you install a distro
RT kernel and its matching headers, while Step 1 above had you *build* the
kernel, so a module compiled against a different tree is an easy mistake and
`modprobe` refuses it with nothing that names the cause.

```sh
/usr/sbin/modinfo -F vermagic /lib/modules/$(uname -r)/ethercat/devices/stmmac/ec_dwmac-rk.ko
uname -r
```

The two must agree, and both must mention `preempt_rt`. A mismatch means it
built against the wrong kernel tree — fix `--with-linux-dir` and rebuild.

`generate.py` refuses to write anything if the IgH tree is not the one it
expects: a missing rename map, or an anchor it cannot find exactly once in
`configure.ac`, `Kbuild.in` or `Makefile.am`, raises rather than producing a
half-wired tree. That is the guard against pointing `--igh` at the wrong
checkout.

## B7 — Find the MAC's device path, then hand the NIC over at boot

The handover script needs the **platform device name of the CB2's GMAC**, which
is a property of the board and must be read off it rather than copied:

```sh
ls -l /sys/bus/platform/drivers/rk_gmac-dwmac/
```

The entry that is not `bind`, `unbind`, `uevent` or `module` is the device —
something of the form `<address>.ethernet`. Cross-check it carries `eth0`:

```sh
basename "$(readlink -f /sys/class/net/eth0/device)"
```

**Both commands must name the same device.**

The in-tree `stmmac` driver claims the MAC at boot, so a service must hand it
over before the master starts. Install as `/usr/local/sbin/ethercat-dwmac-up.sh`
(root, `chmod 755`), replacing `DEV`:

```bash
#!/bin/bash
# Hand the RK3566 GMAC from the in-tree stmmac driver to ec_dwmac-rk, then
# start the IgH master. Idempotent.
set -u
DEV=<from-above>.ethernet          # e.g. fe010000.ethernet
SYS=/sys/bus/platform

[ -e "$SYS/devices/$DEV/driver_override" ] && \
    echo ec_rk_gmac-dwmac > "$SYS/devices/$DEV/driver_override"

cur=$(basename "$(readlink "$SYS/devices/$DEV/driver" 2>/dev/null)" 2>/dev/null || true)
if [ -n "$cur" ] && [ "$cur" != ec_rk_gmac-dwmac ]; then
    echo "$DEV" > "$SYS/drivers/$cur/unbind" 2>/dev/null || true
fi

/opt/etherlab/etc/init.d/ethercat start
```

**The module and the driver it registers have different names.** The module
is `ec_dwmac-rk`; the platform driver inside it is `ec_rk_gmac-dwmac`, the
in-tree `rk_gmac-dwmac` with IgH's `ec_` prefix. `driver_override` matches the
driver, so that is the name it takes.

**The script loads no module itself.** `init.d/ethercat start` loads
`ec_master` with `main_devices` set from `MASTER0_DEVICE`, then unloads the
in-tree `dwmac-rk` and loads `ec_dwmac-rk` in its place, which binds through
the override. A `modprobe ec_dwmac-rk` ahead of it would drag `ec_master` in as
a dependency with no `main_devices`, and the init script's own load would then
do nothing: a master with no device, which reads exactly like a wrong MAC. The
Pi 5's `ec_macb` handover, the one that has run, has the same shape.

Configure the master to expect this MAC, in
`/opt/etherlab/etc/sysconfig/ethercat`:

```
MASTER0_DEVICE="<eth0 MAC, lowercase, e.g. 2c:cf:67:7d:37:1b>"
DEVICE_MODULES="dwmac-rk"
```

Both live under the `--prefix` the master was built with. `./configure
--prefix=/opt/etherlab` puts `sysconfdir` at `/opt/etherlab/etc`, so the init
script is `/opt/etherlab/etc/init.d/ethercat` and the file it reads is
`/opt/etherlab/etc/sysconfig/ethercat`. `/etc/ethercat.conf` and
`/etc/init.d/ethercat` belong to a distro-packaged master and do not exist for
this build — a `MASTER0_DEVICE` written there is silently never read, and the
symptom is a master that loads and finds no link, which reads exactly like a
wrong MAC.

The MAC is matched as a **string**, so lowercase with colons — an uppercase one
gives a master that loads and finds no link. `DEVICE_MODULES` takes the name
**without** the `ec_` prefix.

Run it at boot, before klipper — `/etc/systemd/system/ethercat-dwmac.service`:

```ini
[Unit]
Description=EtherCAT master on native ec_dwmac-rk (RK3566 GMAC)
DefaultDependencies=no
After=sysinit.target
Wants=sysinit.target
Before=klipper.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/ethercat-dwmac-up.sh
ExecStop=/opt/etherlab/etc/init.d/ethercat stop

[Install]
WantedBy=multi-user.target
```

The master creates `/dev/EtherCAT0` root-owned and klippy spawns the endpoint
as the klipper user, so it needs a udev rule or the endpoint cannot open the
master at all — `/etc/udev/rules.d/99-ethercat.rules`:

```
KERNEL=="EtherCAT[0-9]*", MODE="0660", GROUP="<your-user>"
```

**Armbian runs NetworkManager by default** and it will fight the handover at
boot by reclaiming the interface. `/etc/NetworkManager/conf.d/99-ethercat-unmanaged.conf`:

```ini
[keyfile]
unmanaged-devices=interface-name:eth0
```

Enable and start:

```sh
sudo udevadm control --reload-rules
sudo systemctl daemon-reload
sudo systemctl enable --now ethercat-dwmac.service
```

**✅ Check:**

```sh
basename "$(readlink /sys/bus/platform/devices/<DEV>/driver)"   # ec_rk_gmac-dwmac
ethercat master            # master up, with a link
ls -l /dev/EtherCAT0       # exists, readable by the klipper user
ip link show eth0          # no longer managed normally
```

`eth0` disappearing from the normal network stack is **correct** — the master
owns it now. This is why SSH had to be on Wi-Fi first.

## B8 — Real-time capabilities for the endpoint

The endpoint needs `CAP_SYS_NICE` (for `SCHED_FIFO`) and `CAP_IPC_LOCK` (for
`mlockall`). Grant them on the **klipper service** rather than on the binary:
ambient caps survive endpoint rebuilds, and a `cargo build` writes a fresh
inode and drops file-caps. Skipping this is the direct cause of "sync fault
after rebuilding".

`/etc/systemd/system/klipper.service.d/10-ethercat-rt.conf`:

```ini
[Service]
AmbientCapabilities=CAP_SYS_NICE CAP_IPC_LOCK
LimitRTPRIO=infinity
LimitMEMLOCK=infinity
```

Then `systemctl daemon-reload`. The spawned endpoint inherits the ambient caps
from klippy.

**One more thing the capabilities do not cover: `/dev/cpu_dma_latency`.** The
endpoint opens it and writes `0` for as long as it runs, which holds every core
out of deep idle states — on an idle board the exit latency from those is what
makes the loop wake late. The device is `crw------- root root`, and neither
capability grants a write to a root-only file. Add a second line to the udev
rule file from B7, `/etc/udev/rules.d/99-ethercat.rules`:

```
KERNEL=="cpu_dma_latency", MODE="0660", GROUP="<your-user>"
```

`sudo udevadm control --reload-rules && sudo udevadm trigger`, then
`ls -l /dev/cpu_dma_latency` shows the group. Without it the hardware endpoint
fails its claim with `rc=-20`; the stub never goes real-time, so Stage L step 1
passes regardless and step 3 is where it would stop.

> **There is a second route, and it is the worse one.**
> `make -f Makefile.rust setcap-ethercat` puts `cap_net_raw`, `cap_sys_nice`
> and `cap_ipc_lock` on the binary as **file capabilities**. It works — but a
> `cargo build` writes a fresh inode and **drops them**, so it has to be re-run
> after *every* endpoint rebuild. Forgetting it is the direct cause of "sync
> fault after rebuilding", and it is a failure you only meet at the machine.
> Ambient caps on the service survive rebuilds, which is why B8 uses them.
> (If the binary carries file-caps too, those take precedence and the ambient
> set reads back empty — harmless, since file-caps already include
> `cap_sys_nice`.) On that route the check below gains a line:
> `/usr/sbin/getcap rust/target/release/ethercat-rt` must report
> `...cap_sys_nice=ep`. On the ambient route it reads back empty, correctly,
> which is why it is not in the check as written.

There is **no silent `SCHED_OTHER` fallback**. If any of the four requirements
is missing, `go_realtime()` aborts the claim loudly and names which:

| Code | Missing |
| --- | --- |
| `rc=-10` | `mlockall` / `CAP_IPC_LOCK` |
| `rc=-11` | CPU pin (the isolated core) |
| `rc=-12` | `SCHED_FIFO` / `CAP_SYS_NICE` |
| `rc=-20` | write access to `/dev/cpu_dma_latency` — the udev line above |

**✅ Check, once the endpoint is running** — sample the *steady-state* pid, not
the first 200 ms, because `go_realtime()` runs just after `main()`:

```sh
pid=$(pgrep -f release/ethercat-rt)
chrt -p $pid                              # SCHED_FIFO priority 80
grep Cpus_allowed_list /proc/$pid/status  # 3
sudo journalctl -b | grep -c 'al_status=0x001a'  # 0
```

`SCHED_OTHER` with `cpus 0-1` on the live endpoint is the bug, not health.

## B9 — Build the endpoint and the klippy modules

klippy spawns the endpoint itself at claim time and never launches it by hand,
so the binary has to exist before the first claim.
`[ethercat_node].endpoint` defaults to `rust/target/release/ethercat-rt`.

Build **on the CB2** — the `hw` build compiles the IgH C shim and links
`libethercat` from `/opt/etherlab`, so it cannot be cross-compiled:

```sh
make -f Makefile.rust ethercat-endpoint-hw   # -> rust/target/release/ethercat-rt
make -f Makefile.rust ethercat-stub          # -> rust/target/release/ethercat-rt-stub
scripts/build-native.sh                      # klippy/_*.so — klippy will not start without them
```

> **If the master is not at `/opt/etherlab`.** `build.rs` reads `IGH_DIR` for
> the prefix and `IGH_LIB_DIR` for the library directory, defaulting to
> `/opt/etherlab` and `$IGH_DIR/lib`. Build against a different prefix with
> `IGH_DIR=/usr/local make -f Makefile.rust ethercat-endpoint-hw`. Without the
> headers the build now stops and says so, naming the file it wanted, rather
> than failing inside the C compiler.

`scripts/build-native.sh --bench` auto-detects which endpoint to build and
picks **one**: with `/opt/etherlab` installed it builds `ethercat-rt` and skips
the stub. Since this page installs `/opt/etherlab`, ask for each explicitly:

```sh
scripts/build-native.sh --bench --ethercat stub   # Stage L step 1
scripts/build-native.sh --bench --ethercat hw     # Stage L step 3 onwards
```

> **Budget for this before starting it.** What this build compiles — the
> endpoint, the stub and the three klippy modules, all release — leaves about
> 1.1 GB in `rust/target` (measured on x86_64; an arm64 build is the same order).
> The 19-25 GB figure that goes with this workspace is the contributor gate's —
> every crate's debug test binaries — which is the thing not to run here. RAM is
> the tighter limit on a CB2: 2-4 GB, and four parallel `rustc` processes linking
> the larger crates will run a 2 GB board out of memory, so pass `-j2` or set
> `CARGO_BUILD_JOBS=2` rather than discovering it as a killed compiler. A full
> disk surfaces as `ld terminated with signal 7 [Bus error]`, which reads like a
> broken toolchain and is not one; all of `rust/target` regenerates, and
> `cargo clean` in `rust/` frees it.

> ### Do not run `./scripts/ci.sh` on this board
>
> That is the **contributor gate** — ruff over the repository, the whole Rust
> workspace's test suite, and clippy with `-D warnings`. It belongs on a
> development machine before pushing a branch. Run on a CB2 it is actively
> harmful: an hour of four Cortex-A55 cores, a `rust/target` the eMMC cannot
> hold, and if klippy is live it competes with the DC loop for the very core
> B5 isolated for it. A machine that passes every step and then drops frames
> under load is the exact failure mode the real-time setup exists to avoid.
> Do not manufacture it with a test run.
>
> Building is different and unavoidable: it links what the printer needs.
> `ci.sh quick` additionally compiles and runs every crate's test binaries.

## B10 — Turn off the analytics prompt

Of the modules klippy loads unconditionally, `telemetry` is upstream Kalico's
opt-in analytics and prompts at every ready. Put this in `printer.cfg` rather
than leaving it asking:

```ini
[telemetry]
enabled: False
```

> **Stage B is not proved yet.** Everything above was built with no drives
> wired. **Stage J1** proves the NIC handover and the bus on a cold boot once
> the chain is wired; the real-time loop itself is proved only at **Stage L
> step 3**, the first point it runs against drives in `OP`. Until then treat
> the host as assembled, not working.

## If the module will not load

| Symptom | Cause |
| --- | --- |
| `ec_dwmac-rk: Unknown symbol ecdev_*` | `ec_master.ko` not loaded first; `/opt/etherlab/etc/init.d/ethercat start` loads it |
| `modprobe: module not found` | `depmod -a` not run after `modules_install` |
| `modprobe: ... Invalid module format` or a version-magic complaint | built against a different kernel tree than the running one — check `modinfo -F vermagic` against `uname -r` |
| Builds, but `ethercat master` shows no link | `MASTER0_DEVICE` MAC does not match `eth0` |
| Device stays bound to `stmmac` | `driver_override` written after the driver already bound — the unbind step is what fixes it |
| Compile error naming a struct member | kernel is not 6.12-series |

---

# Stage C — Firmware for the Manta

Build on the CB2, in the repository:

```sh
make menuconfig
```

| Option | Value |
| --- | --- |
| Micro-controller | STM32H723 |
| Bootloader offset | **128 KiB** (`0x8020000`) |
| Clock reference | **25 MHz crystal** |
| Communication | **USB (PA11/PA12)** |

**Make the Communication choice in menuconfig rather than copying a `.config`
from the repository.** `test/configs/stm32h723.config` carries the same MCU,
25 MHz reference and 128 KiB offset, but it is a firmware **build-matrix
fixture**, not a board config: it selects `CONFIG_SERIAL` — a hardware UART —
and never sets `CONFIG_USBSERIAL`. Copied to `.config` it produces a board that
never appears under `/dev/serial/by-id/`, and the
`CONFIG_STM32_USB_PA11_PA12` line in it is inert without USB selected, so it
reads as though USB were configured when it is not.

```sh
make clean && make -j"$(nproc)"
```

Flash by copying `out/klipper.bin` to the board's SD card as `firmware.bin`,
power-cycling, and confirming the file is renamed to `FIRMWARE.CUR`.

**✅ Check:**

```sh
ls /dev/serial/by-id/
```

Record the `usb-Klipper_stm32h723xx_*` path — Stage K needs it.

---

# Stage D — Fit the stepper drivers

**Power off the Manta completely.**

| Slot | Driver | Purpose |
| --- | --- | --- |
| Motor1 | **empty** | X is an EtherCAT servo |
| Motor2 | **empty** | Y is an EtherCAT servo |
| Motor3 | TMC2209 | Z (single stepper) |
| Motor4 | **empty** | its endstop input `PF1` becomes the e-stop signal |
| Motor5 | TMC2209 | extruder A |
| Motor6 | TMC2209 | extruder B |
| Motor7, 8 | **empty** | unused |

Set every fitted TMC2209 for **UART mode** per the driver documentation, seat
it in the correct orientation, and fit its heatsink. **A reversed driver is
destroyed on power-up.**

Leaving Motor1 and Motor2 empty is deliberate: those lanes have no stepper, and
the pins that would serve them are unused. Their **endstop inputs are still
used** — the servo axes home on them.

**✅ Check:** visual check of orientation on all three, before power.

---

# Stage E — Mains and drive power

Each `ProNet-04AEG-EC` takes single-phase **200–230 VAC +10% / −15%,
50/60 Hz**. Budget **0.9 kVA per drive** — **7.83 A at 230 V for the pair**,
which is the figure every sizing decision is made against.

Build the chain in [diagram 1](#1-mains-chain-wall-to-drives).

## E1 — Three things called "earth", and why they differ

A plug-connected machine in a UK house has three conductors that all get called
earth, sized and tested by different rules. Collapsing them is how a machine
ends up with a 4 mm² strap bolted to a chassis whose actual connection to earth
is a 13 A plug.

| | What it is | Sized by | Tested by |
| --- | --- | --- | --- |
| **Supply PE** | The CPC in the mains lead, plug earth pin to the machine's main earth terminal | The cord. A 13 A UK lead is 1.25 or 1.5 mm², and nothing inside the machine changes that | Continuity, plug pin to chassis, **under 0.1 Ω** |
| **Protective bonding** | Main earth terminal to ground plate, and plate to every exposed metal part | ESTUN's **3.5 mm²** minimum, taken up to 4 mm² | Continuity to the same 0.1 Ω |
| **Functional earth** | Cable shields, the filter's earth wire, the plate as a reference | EMC, not fault current | Nothing. It either quietens the encoder or it does not |

**ESTUN's grounding instruction does not transfer to a UK house.** It says to
ground "to an independent ground, use ground resistor 100 Ω max". That is a JIS
Class D earth — a local electrode measured against true earth, which is how the
drive's home market earths machinery.

A UK domestic supply already provides the earth, as TN-C-S (PME) in most houses
or TN-S in older ones, and it arrives at the socket. The declared maximum
external loop impedance is **0.35 Ω for TN-C-S and 0.8 Ω for TN-S** — two orders
of magnitude inside ESTUN's 100 Ω, satisfied by plugging the machine in, with
nothing to measure and nothing to install.

**Driving an earth rod and bonding the machine to it is the wrong reading, and
under PME it is actively dangerous** — the machine would sit between the
supply's combined neutral-earth and a local electrode, giving diverted neutral
current a path through the chassis. **There is one earth, and it comes in on
the lead.**

Inside the machine:

- **One star point.** The main earth terminal. Drives, motors, filter body and
  enclosure panels each get their own conductor back to the ground plate, and
  the plate gets one conductor to the main earth terminal. ESTUN's "single
  point grounding" means this, not a local electrode.
- Ground-plate wires at least **3.5 mm²**, taken up to 4 mm².
- The filter's ground wire runs **straight to the plate**, never daisy-chained
  through another device, and stays separate from its output lines.
- **Paint is an insulator.** Every bond that matters is to bare metal, with a
  serrated washer or a scraped landing.

## E2 — One plug, and why the connector decides

The drives alone draw **7.83 A**, and that number decides the inlet before
anything else. A **C13/C14 coupler is rated 10 A** — the drives take 78% of it
with the bed, hotend, PSU, host and fans still to be fed. **C19/C20 is rated
16 A** and moves the limit back to where it belongs: the plug's 13 A fuse.

1. **One cord.** A 13 A BS 1363 plug into a C19/C20 inlet. The 13 A fuse leaves
   5.17 A — about 1.2 kW — for everything that is not a servo drive, which a
   300 mm bed at 600 W fits inside with room.
2. **A dedicated circuit** if the total goes past 13 A: a 16 A radial to a
   BS EN 60309 socket, still one cord.
3. **Two cords, reluctantly.** EN 60204-1 asks for a single incoming supply
   where practicable.

Two cords are not primarily an earthing problem — each lead brings its own CPC
and both land on the same main earth terminal. **The problem is isolation.**
EN 60204-1 requires a disconnecting device for each incoming supply, and the
verification at the end of this stage proves the machine dead by locking one
switch. With two cords it cannot.

If two cords are unavoidable: both plugs into the **same socket** so both are
on one circuit and one RCD (splitting them across two RCDs halves the measured
leakage and hides the problem); the isolator breaks **both**, or there are two
isolators and a label on each; both CPCs land on the one main earth terminal;
label each inlet with what it feeds.

**The plug fuse is the overcurrent device, not the MCB.** A 13 A BS 1362 fuse
upstream of a 16 A MCB clears first on any overload the MCB would eventually
see. The internal breaker is a local isolating and short-circuit device; the
coordination runs from the plug.

**And the 16 A rating is not about the 7.83 A load.** Energising two DC buses
charges their capacitors through the rectifiers — tens of amps for a few
milliseconds. Type C trips instantaneously at 5–10× rating, so a 16 A Type C
tolerates 80–160 A for that instant. **A 10 A Type B would trip on the first
power-up, every time, and look like a fault in the drives.**

## E3 — The RCD: why the usual one is the wrong one

**Servo drives leak current to earth by design.** The EMC filter's
Y-capacitors connect line to earth and that path carries current continuously,
before any fault. A Roxburgh `DRF10` is specified at **1.46 mA maximum
leakage** — the filter alone, with the drives' internal filters on top. A 30 mA
RCD is required to trip between **15 and 30 mA**, so the usable budget is
15 mA.

Worse, the leakage is not a clean sine wave. A rectifier ahead of the DC bus
gives it a DC component, and **a Type AC RCD cannot see DC residual current at
all** — it can be blinded by exactly the fault it is fitted to catch.

**Type A is the minimum** for single-phase drives like these, and what
IEC 61800-5-1 expects of a two-pulse rectifier. Type AC is not acceptable. A
three-phase rectifier on the same board would make it Type B.

**If the 30 mA device nuisance-trips on power-up, the answer is not a bigger
threshold and it is not a time-delayed device.** ESTUN is explicit: *"always
use a fast-response type or one designed for PWM inverters. Do not use a
time-delay type."* A delayed device holds a residual current through the window
an instantaneous one would clear it in, and that window is the whole protective
function.

So a nuisance trip leaves **two** answers. Either the standing leakage is
genuinely close to the trip band — in which case reduce it: a lower-leakage
filter, shorter screened runs, the drives on their own RCBO so they do not
share a budget with a bed heater — or it is a real earth fault that has just
been found. A clamp meter distinguishes the two in a minute, which is why
**check 5 below asks for the number before anything has gone wrong.**

## E4 — The filter's rating depends on where it sits

A filter's headline current is quoted at an ambient temperature, and an
enclosure beside two servo drives is not that temperature.

| Ambient | 40 °C | 45 °C | 50 °C | 55 °C | 60 °C |
| --- | --- | --- | --- | --- | --- |
| `DRF10` ampacity | 10.00 A | 9.34 A | 8.65 A | 7.94 A | 7.18 A |

The machine draws **7.83 A**. At 45 °C that is 84% of the filter; at 55 °C it
is 99%; at 60 °C the filter is rated below the load.

**Past 45 °C the filter stops being the only thing derating.** ESTUN specifies
a working range of **0–55 °C**, and separately an ambient of **45 °C or less
"to ensure long-term reliability"**. So 45 °C is where the drives begin trading
life for temperature and 55 °C is where they leave specification altogether. A
chamber bay at 60 °C is not a filter problem with a bigger filter for an
answer; it is a bay the drives should not be in.

The same section sets the spacing that keeps a bay near its ambient: **at least
10 mm between drives side by side, and at least 50 mm above and below each
one**, with a fan if natural convection cannot hold it. Two ProNets shoulder to
shoulder on a backplate is the arrangement this rules out, and it is the
arrangement a printer tempts you into.

- **Filter ambient ≤ 45 °C** — `DRF10`. 100 g, on the rail, 1.46 mA leakage.
- **Filter ambient ≥ 50 °C** — Schaffner `FN2412-16-44`, 16 A *at 50 °C*. It
  leaks **3.4 mA**, and its datasheet notes an interrupted neutral can double
  that. Against a 15 mA budget that is most of a quarter before the drives
  contribute anything.

## E5 — The manual contradicts itself about the filter

One line in the ProNet manual reads as though this whole chain were wrong, and
it is a translation defect. The Safety Precautions page carries, in a list
about *signal-line* noise: *"Never use a line filter for the power supply in
the circuit."* Chapter 3.6.1 then instructs the opposite — *"install a noise
filter on the input side of the power supply line"* — and the EMC conditions in
3.7 will not be met without one, with the filter drawn feeding the drive
directly.

Two sections of the same manual cannot both be followed. **Take 3.6.1 and 3.7**,
which are specific, worked and drawn. The page-2 line is a garbled rendering of
a caution about filters on the *motor output* side, where one genuinely does
not belong. Expect to meet it; do not let it talk you out of the filter.

## E6 — The contactor, its coil, and what not to snub

**Where the coil is fed from.** The contactor coil takes its supply from the
**load side of the RCD**, with the emergency stop's NC contact in series.
Fed from upstream of the RCD, the coil circuit sits outside the earth-fault
protection covering everything else — and a fault in thin wiring going out to a
button on the machine's outside is exactly what that protection is for.

**The contactor brings its own coil suppression, so read the suffix.** ABB's
older `ESB20` is AC-operated with no built-in protection, and the catalogue
scopes built-in surge protection to `ESB24` and above. The `ESB20-20N-06` is
not that part: the `..N` generation has a DC control circuit, and ABB describes
the family as hum-free with an incorporated varistor protecting the coil to
5 kV. An external RC snubber is redundant on it.

**If a snubber does go in, it goes across the coil — never across the emergency
stop's contact.** A 0.1 µF capacitor is 31.8 kΩ at 50 Hz. An AC-operated
`ESB20` draws 3.2 VA holding, 13.9 mA at 230 V, about 16.5 kΩ — the same order
of magnitude. A snubber bridging the open contact leaves a large fraction of
the coil voltage standing, and that contactor's drop-out band is **20 to 75% of
Uc**. The honest statement is that it *might* drop out. **An emergency stop
that might work is not one.**

## E7 — What the stop actually does, and what it does not

The contactor dropping main power is the safety function and nothing else
changes it. What the second contact adds is that **the host finds out**.
Without it, klippy keeps streaming cyclic position targets into a bus that has
just gone dark, and the first thing anyone sees is an endpoint death and a
spread of drive faults rather than "the stop was pressed".

`stop_node` has two halves, and they are not what their names suggest:

| Step | Where it acts |
| --- | --- |
| `Stop` | **Host only.** Discards the motion rings and halts the stream. Nothing goes on the EtherCAT wire |
| `SetTorque(false)` | Schedules a disable, executed by the next RT tick once the rings are empty. It writes CiA 402 controlword **`0x0006`** to every drive, holding target position at the measured actual, for 100 cycles |

**`0x0006` is Shutdown, not Quick Stop.** It takes the drive from Operation
Enabled to Ready to Switch On — servo off. It does *not* command a ramp; there
is no `6084h` deceleration anywhere in this path.

What the machine then does is **the drive's decision**, set by a parameter
rather than by anything the host sends. On `Pn004.0 = 0` (factory), servo off
means **stop by dynamic brake** — the motor windings are shorted — and then
coast. That is real braking and it needs no bus voltage, which is why it still
works with the contactor already open. Set `Pn004.0 = 1` and the same command
leaves a fast gantry coasting on friction alone. Stage I checks it.

**This is a Stop Category 0 with dynamic braking. It is not Category 1.** There
is no controlled ramp available: on servo-off the drive offers dynamic brake or
coast only (`Pn004.0`), never a profiled deceleration. Stopping distance is set
by inertia, friction and the dynamic brake, and nothing about it can be tuned.
That is a deliberate choice for this machine — these drives have **no STO**, no
safety function of any kind appears in the ProNet manual, and a Category 1 stop
would need the drive to remain powered and controlled through the ramp, which
is precisely what dropping the contactor removes.

**Two things have to be true for the halt to land.** First, the drives must
still be powered when it arrives — which is why control power is upstream of
the contactor. Second, **the halt is best effort and is not a protective
measure**: the NC contacts change over at the same instant with no ordering
between them, and the `Stop` travels over a fieldbus at 250 µs while the
contactor takes tens of milliseconds to open. It usually wins. It is not
required to. **The reason to fit it is a clean stop and a readable log, not
safety.**

**Repeated dynamic braking degrades the drive's internal elements.** The
emergency stop is not a routine way to stop the machine.

## E8 — Every stop press will latch an alarm. Plan for it.

This is friction on *every single press* and it is worth knowing before the
first one.

Opening the contactor removes main power for **longer than one AC period**, so
the drives latch **`A.21`** (main power off for more than one period) and/or
**`A.14`**, and they need an alarm clear before the machine will run again.
`Pn000.3` looks like an escape and is not: the factory `0` already means "one
period, no alarm", `A.21` is *defined* as power off for more than one period,
and setting it to `1` only makes the drive stricter.

So the clearing routes are: the **panel `ENTER`**, **`/ALM-RST`**, or a
**main-circuit power cycle** (manual §5.1.2). Note that `/ALM-RST` is `CN1-39`
on the base 50-pin connector, and the `-EC`'s `CN1` is 20-pin with 5 sequence
inputs — so whether it can be allocated there is open. The likely answer is
**CiA 402 fault reset over the bus**, which needs the EtherCAT manual nobody
has yet.

Budget a panel reach or a power cycle after every emergency stop.

## E9 — Fitting it in a printer enclosure

Keep the whole chain on **one 35 mm DIN rail**. A module is 17.5–18 mm, so
count modules:

| Device | Modules |
| --- | --- |
| Isolator `SD202/32` | 2 |
| MCB `S201-C16` | 1 |
| RCD `F202 A-25/0.03` | 2 |
| Contactor `ESB20-20N-06` | 1 |
| **Rail needed** | **6** ≈ 105 mm |

Before the filter, which is not a modular part. An `A9L20500` SPD adds two; an
RCBO takes one or two back. Add a spare module, because something always
follows.

**One trade-off to make knowingly.** A modular contactor drops power when the
stop opens its coil, which is what this circuit needs. It is **not a safety
contactor**: no mirrored contacts, no monitoring, nothing that detects a welded
pole. An industrial machine would use a safety relay and a contactor with
mirror contacts.

**And the second half of that choice — but read which half latches, because
the two are routinely confused.**

| | Latches here? |
| --- | --- |
| **The button** (RS 139-972) | **Yes.** Pressed, it stays in with both NC contacts held open. It is **key release**: it cannot be twisted back, thumbed back or knocked back. A key goes in and turns, or it stays pressed |
| **The coil circuit** | **No.** There is no safety relay holding the contactor dropped out independently of the button. The instant the key releases it, the coil re-energises and the contactor closes |

So **the key is the reset**, and there is no other one — nothing else asks for
a deliberate action before main power returns. Two things follow, and the
build depends on both being understood.

**The good half: take the key out and nobody restores power.** Not the person
who wandered in, not the person who thinks the jam is cleared, not you in five
minutes having forgotten why it was pressed. For a machine on a bench in a
house, a key in a pocket is a real interlock and it is the main reason to buy
this part rather than a twist-release button.

**The half that is not a substitute for anything.** Releasing it restores
main power immediately: the motors stay still, because klippy is shut down and
torque disabled until a `FIRMWARE_RESTART`, but **the DC bus recharges and
`CHARGE` lights**. And throughout the press, control power at `L1C`/`L2C` was
never interrupted — that is deliberate, it is what lets the drives be halted
cleanly, and it means **the enclosure was live at 230 V the whole time the
stop was pressed.** The key-release mechanism is not a lockable disconnector
and gives no proved dead state.

**So: key out is an interlock, the isolator locked off is isolation.** They are
not alternatives. Before reaching into the enclosure, lock the isolator off,
prove it dead, and wait for `CHARGE` — every time, key or no key. A latching
safety relay with a separate monitored reset is what an industrial build would
add on top, and it would also watch for the welded pole nothing here detects.

## E10 — Regeneration

The 200 V `A5A`–`04A` frames ship with **no internal regenerative resistor**.
The manual's instruction for this band is an **external resistor between `B1`
and `B2`**. The `B2`–`B3` jumper that selects an internal resistor belongs to
the larger `08A`–`50A` drives and does not apply.

One figure covers the whole band: for `ProNet-A5A`–`04A` the external resistor
is customer-supplied and **60 W, 50 Ω is recommended**. One per drive.

**Set `Pn521.0` from `1` to `0` on both drives** when the external resistor
goes in. `Pn521` runs `0~1` and **ships at `1`**, which the manual glosses as
"does not connect externally regenerative resistor" — so the factory setting is
the wrong one for this build, and the instruction to change it is a footnote
under a wiring table rather than a step. **Without it the resistor is fitted
and the drive does not use it.**

The symptom of insufficient capacity is **`A.13` overvoltage**, which the
manual notes can appear when load inertia exceeds roughly 30× the rotor inertia
during acceleration. The EMJ-04AFD22 rotor inertia is 0.31e-4 kg·m². Treat a
first `A.13` under hard decel as "fit, re-mount, or size up the resistor", not
as a tuning problem.

The manual pairs `A.13` with **`A.16` regeneration error**, and the two want
different responses: `A.13` says the resistor could not absorb what the decel
produced; `A.16` says the regenerative circuit objects to the resistor that is
fitted. The manual's remedies for either are to decrease the torque limit,
decrease the deceleration, or decrease top speed.

Per drive:

| Terminal | Connect |
| --- | --- |
| `L1`, `L2` | main circuit power (single phase; `L3` unused) |
| `L1C`, `L2C` | control power — **from the filter output, upstream of the contactor** |
| `+1`, `+2` | DC reactor terminals — **leave the factory link fitted** |
| `B1`, `B2` | external regenerative resistor |
| PE | ground plate |

## ✅ Stage E checks — no motor connected

1. **Before energising:** continuity from the plug's earth pin to the ground
   plate, to a drive's PE stud, and to the enclosure reads **under 0.1 Ω**. A
   reading in ohms rather than milliohms is a bond onto paint.
2. **Before energising:** the isolator locks OFF with the key out, and a meter
   across `L1`/`L2` at a drive reads zero with it locked. With two cords, that
   must hold with either one plugged in alone.
3. **Energise.** `POWER` (green) lights on both drives and the panel shows a
   status rather than an alarm. `CHARGE` (red) lights with main power.
4. **The RCD holds.** A trip here is the leakage question in E3, not a reason
   to fit a larger one.
5. **Clamp the standing earth leakage with the drives idle and write the number
   down.** It is the baseline every future nuisance trip gets compared against,
   and it takes a minute now against an afternoon later.
6. **Open the contactor — by the emergency stop, not by the isolator.**
   `CHARGE` goes out on both drives and the motors lose torque, while `POWER`
   **stays lit**, because control power is upstream. This is the one test that
   proves the stop does anything. **If `POWER` drops too, control power is on
   the wrong side of the contactor and the halt configured in Stage K will
   never arrive.**
   *(This tests the contactor only. The second contact — the one that halts the
   drives — needs klippy and the config, so it is tested at Stage L step 2.)*
7. **Power down, wait 5 minutes, confirm `CHARGE` is out.**

---

# Stage F — Drives to motors

**Drives isolated, `CHARGE` out.** See [diagram 3](#3-one-drives-terminals).

**Power.** `U`→`A(1)`, `V`→`B(2)`, `W`→`C(3)`, `PE`→`D(4)`. Use 1 mm²
conductors and bond the cable shield at the drive end. **A swapped pair trips
`A.25` on the first enable**, which the manual attributes to exactly this or to
mechanical seizure.

**Encoder.** CN2 per the table in diagram 3. Pins 17/18 (`BAT+`/`BAT-`) are for
absolute encoders only — leave them unused.

**✅ Check.** With the motor **uncoupled from the belt**, energise **control
power only**. No `A.10` (encoder break) or `A.22` (sensor break). Turning the
shaft by hand moves the panel's position display smoothly in both directions. A
display that jumps or freezes indicates a shield or 5 V problem, not a tuning
problem.

---

# Stage G — EtherCAT chain

On the `-EC` variant the two RJ45 jacks are the fieldbus, replacing the base
ProNet's RS-485/CAN roles: **`CN3` = IN, `CN4` = OUT**. Daisy chain IN to OUT,
per [diagram 4](#4-ethercat-chain). No switch, no ring.

Two further `-EC` differences worth knowing before building a loom: `CN1` is a
**20-pin** connector rather than the standard 50-pin, and it carries **5
sequence input channels** rather than 8.

**✅ Check — and be clear what it does not prove.** The green `LINK/ACT` LED
lights on each connected RJ45. That confirms the cable and the PHY link, and
**nothing about direction**: a `CN4`-to-`CN4` link lights both LEDs exactly the
same way, because the link is negotiated below EtherCAT.

Direction is proven at **Stage J**, where `ethercat slaves` must list *two*
slaves in the wired order. One slave there is the reversed link showing up.
Until then, the only guard is having wired IN to OUT deliberately and labelled
the drives.

---

# Stage H — Manta wiring

All conventional Klipper wiring; the only unusual part is that the X and Y
endstops serve **servo** axes. Build to [diagram 5](#5-manta-m8p-v20-wiring),
and read the cable-separation notes there — they are the difference between a
machine that homes and one that appears to have a flaky switch.

Wire the motor coils in pairs **by phase, not by wire colour**.

**✅ Check.** With the Manta powered and no mains on the drives, klippy
starts against a minimal config and `QUERY_ENDSTOPS` reports all three
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
  L homes slowly with a hand on the power.
- Read the config back: all four inputs — `^PF4`, `^PF3`, `^PF2` and `^PF1` —
  carry the prefix. It is three characters and invisible when wrong.

---

# Stage I — Drive parameters

Set from the panel operator or ESView over the mini-USB cable, on **both**
drives.

| Parameter | Value | Meaning |
| --- | --- | --- |
| `Pn006.0` | `4` | select EtherCAT communication mode |
| `Pn004.0` | `0` | stop by dynamic brake on servo off — the factory value, worth **confirming** rather than assuming |
| `Pn521.0` | `0` | use the external regenerative resistor (**ships at `1`** — see E10) |

`Pn004.0` is what the emergency stop relies on. The host writes controlword
`0x0006`, and this parameter decides whether the drive answers by shorting the
motor windings or by letting the gantry coast.

**Both `Pn004` and `Pn006` take effect after restart**, and `Pn004` wants main
*and* control power cycled.

⚠ `Pn006.0` is the bus-mode nibble on every ProNet, but **the value `4` comes
from the `-EC` variant rather than from the base manual**, whose whole `Pn006`
range stops at `0x2133` — a non-`EC` drive rejects `4` as out of range. It is
listed under [Still unverified](#still-unverified-on-hardware).

**Leave the drives' station alias alone.** The endpoint passes alias `0` to
`ecrt_master_slave_config` (`SLAVE_ALIAS` in
[`rust/ethercat-rt/csrc/libecrt_igh.c`](../../rust/ethercat-rt/csrc/libecrt_igh.c)),
and with alias 0 the master reads the position argument as the **absolute
position on the wire**. `ethercat_chain_index` is that position. Physical cable
order is therefore the single source of truth, and configuring an alias only
adds a second one that can disagree.

Do not assume `Pn704` holds that alias — in the base manual it is the CANopen
node address (range `1~127`, default `1`), and an EtherCAT station alias
normally lives in the slave's EEPROM rather than in a drive parameter.

---

# Stage J — Read the drive identity

The endpoint matches drives on an EtherCAT **vendor ID** and **product code**.
ESTUN publishes these only in `ESTUN_ProNet_CoE.xml`, which is not a public
download — request it with the order, or read the live values off the bus:

```sh
ethercat slaves -v | grep -iE 'vendor|product'
```

**Both halves are required and both are checked at config time.** A zero
product code is **not** a wildcard: the master would accept the slave
configuration, never attach it, and the run would die at the OP walk with
nothing pointing back here. klippy refuses to start until both carry the values
read off the bus, naming whichever is still unset. **Treat that refusal as the
checkpoint for this stage.**

**✅ Check.** `ethercat slaves` lists **two** slaves, in the wired order, both
reaching `PREOP`.

- **One slave** means the second drive's IN/OUT is reversed, or its cable is
  faulty.
- **Zero slaves** means `Pn006.0` is not `4`, or `eth0` never reached
  `ec_dwmac-rk`.

## J1 — Confirm the bus on a cold boot, before trusting any of it

**This is the first gate on Stage B, and the first moment it can be run** —
the host was built with no drives wired. Do it now, before a line of
`printer.cfg` is written.

**Power the machine down fully, boot it, and watch.** Not a `systemctl
restart`, not a `FIRMWARE_RESTART` — a cold boot, because the handover runs at
boot: a service that only works when started by hand, or loses a race with
NetworkManager, passes a restart and fails here.

| | Must hold after the cold boot |
| --- | --- |
| `basename "$(readlink /sys/bus/platform/devices/<DEV>/driver)"` | `ec_rk_gmac-dwmac` — the handover ran |
| `ethercat master` | reports the master up, with a link |
| `ethercat slaves` | both drives, in wired order, reaching `PREOP` |
| `grep -lx 3 /proc/irq/*/effective_affinity_list` | prints nothing — the GMAC's interrupt, now EtherCAT's, is off CPU 3 |

If this fails, the fault is in B5, B6 or B7 — the driver or the handover — and not
in anything since.

**What J1 cannot prove is the real-time loop, because nothing runs it yet.**
klippy spawns the endpoint only when it claims a node, which needs Stage K's
config. A drive sitting in `PREOP` has no SYNC0 to lose, so no `A.70` can
appear here, and the endpoint that would log `al_status=0x001a` has not
started. A clean panel at J1 says nothing about B1, B5 or B8. Those checks
belong where the loop runs — [Stage L step 3](#3-real-endpoint-motors-uncoupled)
— and they need a cold boot there too.

---

# Stage K — `printer.cfg`

klippy reads this from `~/printer_data/config/` on the CB2. **Replace the
file's contents rather than appending**: the classic `[stepper_x]` and
`[printer] kinematics:` sections this fork rejects will stop it starting.
Coming from mainline Klipper, [`Config_Migration.md`](../Config_Migration.md)
covers the conversion. Apply with `RESTART`, or `FIRMWARE_RESTART` after
reflashing the Manta.

`encoder_counts_per_rev` is the **motor's** resolution: **1048576** for the
20-bit incremental EMJ-04AFD22. Using the 131072 of a 17-bit absolute scales
every move by 8.

```ini
[mcu]
serial: /dev/serial/by-id/usb-Klipper_stm32h723xx_...   # from Stage C

[telemetry]
enabled: False

[printer]
max_velocity: 300           # bring-up limits: raise after Stage M, not before
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
vendor_id: 0x00000000       # <- replace, from Stage J
product_code: 0x00000000    # <- replace, from Stage J
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
#   Uncomment it for Stage L steps 1-2 only. Absolute: klippy does not
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
#debounce_delay: 0.05
#   Optional. Raise it only if noise on the long run to the button produces
#   spurious stops — see the cable-separation notes in diagram 5.
#message: emergency stop 'estop' asserted
#   Optional. What the shutdown reports.
```

## K1 — Why `[emergency_stop]` and not a `[gcode_button]` running `M112`

G-code runs through a queue behind a mutex. An `M112` typed at the console or
sent by the front-end **does** jump that queue — but by a route nothing inside
klippy can use: `GCodeIO` scans lines as they arrive on its input descriptor
and calls `cmd_M112` directly, outside the lock, before anything is queued.

**A `[gcode_button]` callback does not arrive on that descriptor.** It calls
`run_script`, which takes the G-Code mutex and waits for whatever holds it.
Most of the time that wait is short, because dispatching a move queues it into
the lookahead rather than executing it. But `G4`, `M400`, `TEMPERATURE_WAIT`
and a homing move all hold the mutex for real time, and a print is full of
them. The halt would arrive late by an amount nothing bounds — **which is the
one property an emergency stop cannot have.**

`[emergency_stop]` registers the button with `buttons` directly and calls
`printer.invoke_shutdown` from the callback. That runs every `klippy:shutdown`
handler there and then, on the reactor, with no queue and no mutex in the way.
`ethercat_node` is one of those handlers, and `stop_node` is what it does.

**Releasing the button does nothing on its own.** A shutdown latches, and
clearing it is a `FIRMWARE_RESTART` once the stop has been released
deliberately.

`QUERY_EMERGENCY_STOP STOP=estop` reports the input without touching it, which
is how to check the wiring before trusting it. It answers during a shutdown —
which is the point — but **what it answers with is the last sample taken before
the shutdown, not a live reading.** An MCU shutdown drops every user timer,
including the one sampling the button, so the value freezes at whatever caused
the stop. Releasing the button will not change it. Only `FIRMWARE_RESTART`
starts the sampling again.

## K2 — The two drive limits, which are the only thing between a wrong number and a bent frame

**`max_torque` is a percentage of *rated* torque, not a raw value.** The config
field accepts up to **400**, which is the CiA 402 `6072h` ceiling rather than
anything this drive will honour: ProNet's own `Pn401`/`Pn402` internal torque
limits run **0 to 300 %**, so a value above 300 is clamped by the drive and the
number in the config stops describing the machine. **Treat 300 as the real
ceiling.**

The EMJ-04AFD22 is a 400 W motor rated about 1.27 N·m, so at `max_torque: 300`
— the motor's own peak, and the same 3× its 2.8 A continuous to 8.4 A maximum
output current implies — a 20-tooth pulley, 40 mm of belt per turn, pulls on
the order of **600 N**. The
value here is `100` instead: full continuous torque, enough to move the gantry
and short of anything that bends a part. **Raise it only once the machine homes
and prints, and raise it because a move stalled, not pre-emptively.**

> On `estun-pronet` the limit is **not** written to `6072h`. ProNet's object
> dictionary has no `6072h`, so this profile sets `split_torque_limit` and
> writes the **`60E0h`/`60E1h` pair** (forward/reverse) instead, whose
> 0.1 %-of-rated unit already matches what the host sends. The `a6ec` profile
> writes `6072h`. The 400 ceiling is the *config field's* validation limit in
> either case.

**`following_error` is in millimetres and is written to the drive's `6065h`**,
so the **drive** faults on a stall or a crash rather than continuing to push.
It has **no default**: leave it out and no session limit is written at all, and
the drive keeps whatever the last session left in `6065h`.

Homing is separately governed by `homing_following_error` (default **2.5 mm**)
and `homing_max_torque` (default **50 %**), which apply only around `G28`.
Those are the *tighter* pair, so a swap that fails partway leaves the machine
safer rather than looser.

**On `estun-pronet` this is also a checkpoint.** `6065h` belongs to the same
CiA group as the `60F4h` this drive family does not have, and ESTUN's
dictionary was never obtained — so if `6065h` is absent too, the endpoint says
exactly that, naming the object, instead of failing somewhere downstream.

## K3 — Three more things about this config

**The tandem extruder is a follower axis with two motors, not two axes.**
`build_follower_steppers` walks every motor of the axis, so both step from one
trajectory. There is no synchronisation to maintain and no way for them to
diverge.

**`cycle_us: 250` (4 kHz) is the fast end of ProNet's DC range.** ESTUN's
manual prints that range twice and the two disagree — 250 µs to 8 ms in the
specification table, 250 µs to 2 ms in object `0x1C32:02` — but both agree on
the 250 µs floor, so this value is in spec either way. It is also the
setting that has run only on a Pi 5: nothing has yet run the loop on the CB2's
Cortex-A55 cores. If Stage L step 3 fails on frame timing with B5 and B8
confirmed, `cycle_us: 500` is the next thing to try — still inside both of
ESTUN's ranges, and a multiple of the 250 µs quantum the node requires.

**A Markforged Y move drives both motors while an X move drives only its own.**
A plain `endstop_pin` works on both axes; only the **per-motor keyed** endstop
form is rejected on Y, because that form requires an axis reaching exactly one
motor lane.

**✅ Check.** klippy starts and parses the configuration, naming any section it
rejects.

---

# Stage L — Staged bring-up

**Belts stay uncoupled until step 8.** Each step is cheap to pass and expensive
to skip.

### 1. Stub endpoint, drives off

Build the stub if Stage B9 has not (`make -f Makefile.rust ethercat-stub`),
uncomment the `endpoint:` line in `[ethercat_node]` with your user name in it,
and start klippy. The path must be absolute — klippy does not expand `~`, and
resolves a relative path against its own working directory, which depends on
how the service was installed.
**It must reach `ready`.** This proves planner → bridge → transport with zero
hardware risk.

klippy **spawns the endpoint itself** at claim time — you never launch it.

This step has an automated counterpart, so a failure here is more likely to be
this machine than the software: `test/test_ethercat_claim_stub.py` spawns the
same binary and completes the same handshake in the ordinary test suite (no
master, no NIC, no MCU), and the simulator carries an EtherCAT world
(`tools/sim/tests/test_ethercat_world.py`) that boots **this guide's own Stage K
config** against it — only the pins, the serial path, the endpoint and the
Stage J identity swapped — then moves X, Y and a diagonal, enables torque with
step 4's command, homes X and Y on their endstops and presses the stop. **If
those are green and this step is not, suspect the host or the wiring, not the
config or the claim path.**

### 2. Test the halt, still on the stub

The drives are off and the stub answers `Stop` and `SetTorque` exactly as the
real endpoint does, so **this costs nothing and proves the wiring before any
drive is live.**

- `QUERY_EMERGENCY_STOP STOP=estop` reports `clear`.
- **Press the stop.** klippy shuts down naming it, and the same query — which
  still answers during a shutdown — reports `ASSERTED`.
- That reading is **frozen** at the moment of the stop, so releasing the button
  will not clear it. `FIRMWARE_RESTART` first, then the query reads `clear`.

| Symptom | Cause |
| --- | --- |
| `clear` with the button held | the second contact is not on `PF1` |
| no shutdown at all | the contact is **NO** where the config expects **NC** |

### 3. Real endpoint, motors uncoupled

Comment the `endpoint:` line out again: unset, it is the hardware endpoint in
this checkout, built by Stage B9 (`make -f Makefile.rust ethercat-endpoint-hw`). Expect `ready` and a log line
naming the profile and matched identity.

If the drive is powered off, the master finds no slaves at all and klippy fails
the claim loudly:

> `ethercat node_xy: EtherCAT bus on eth0: no slaves responding (bringup rc=-2)
> — check cable and drive power, then FIRMWARE_RESTART`

If the drive **is** found but fails the SAFE-OP/OP/CiA402-enable walk
(`rc=-3..-5`) you get the per-drive variant instead. Fix the cause, then
`FIRMWARE_RESTART` — klippy re-spawns the endpoint and re-runs the claim.

**Then the real-time gate, on a cold boot.** This is the first point the loop
runs against drives in `OP` with DC active, so it is the first point Stage B's
real-time setup can fail. Power everything down, boot, let klippy claim, and
leave it running for several minutes — with everything this board normally
runs running too: Moonraker, the web front end open in a browser, and a webcam
stream if the machine has one. The gate proves the loop under the load it will
live with, not on an idle board:

```sh
pid=$(pgrep -f release/ethercat-rt)
chrt -p $pid                                     # SCHED_FIFO priority 80
grep Cpus_allowed_list /proc/$pid/status         # 3
sudo journalctl -b | grep -c 'al_status=0x001a'  # 0
```

and no `A.70` on either drive's panel.

**A warm restart proves nothing here, and that is the whole point.**
`ec_generic` and a kernel that reports `PREEMPT` rather than `PREEMPT_RT` will
both hold cadence on an idle bench and drop frames under boot load. The
failure they produce — `A.70`, latched in the drive and surviving host reboots
until the drive is power-cycled — arrives on the first cold start of a machine
that has passed every other step, which is the most expensive place to find
it.

If this fails, the fault is in Stage B and not in anything since. Go back to
B1 (is it really `PREEMPT_RT`?), B5 (is the core really isolated?) and B8 (is
the endpoint really `SCHED_FIFO` on it?) before touching drive parameters.

### 4. Torque on, no motion

```
SET_STEPPER_ENABLE STEPPER="axis x" ENABLE=1
```

Torque belongs to the node, so this enables **both** drives; `M18` disables it
again. The quotes are needed — the servo rails are registered under their
section names, `axis x` and `axis y`, and `STEPPER=x` is refused as an invalid
stepper.

Both drives reach **Operation Enabled** and hold position: with the belts off,
each shaft pushes back when turned gently by hand, and turns freely again after
`M18`. Do not force it — at `rotation_distance: 40` the 2 mm `following_error`
is about 18° of shaft, and past it the drive faults, which is that limit doing
its job. `engine_state` stays running and never reaches `Fault (3)`.

**Before the first move:** the endpoint captures the rotor's current count as
the origin at first sample, so the first commanded position maps to the actual
rotor position — **there should be no startup jump.** If the axis lurches on
the first command, stop and check `encoder_counts_per_rev`,
`rotation_distance`, and origin capture.

### 5. Small supervised jog

`SET_KINEMATIC_POSITION`, then short `G1 X…` and `G1 Y…` moves.

**An X move turns one motor; a Y move turns both.** Seeing that is the cheapest
confirmation the kinematics matches the mechanics.

Watch for:

- **`engine_state == Fault (3)`** in the `StatusHeartbeat` — the host pump fell
  behind more than 2 ms (`PieceStartInPast`). The endpoint latches the fault
  and propagates it so the host can shut down; the hw binary also disables the
  drive. Expected on a gross stall, not on a healthy stream.
- **`wkc != 3`** — EtherCAT working-counter fault. The endpoint halts and dumps
  `al_status=0x…`. **`al_status=0x001a` is DC sync loss**, and the usual cause is the loop not
  running `SCHED_FIFO` on the isolated core.

### 6. Check the coupling sign

With belts slack, **hold the X motor still and move the gantry to +Y.**

| Carriage slides | Meaning |
| --- | --- |
| **−X** | correct — `MARKFORGED_Y_COUPLING = 1.0` (the default) |
| **+X** | flip the constant to `-1.0` |

A wrong sign turns a commanded X move into a diagonal.

**Both copies must change** — `rust/motion-core/src/kinematics.rs` and the
mirror in `klippy/motion_kinematics.py` — and the Rust one compiles into
`klippy/_motion_engine.so`, so **the edit does nothing until the module is
rebuilt**:

```sh
sudo service klipper stop
scripts/build-native.sh
```

Changing only the Python side, or changing both and skipping the rebuild,
leaves the host and the planner disagreeing about the machine, which is worse
than the wrong sign: the two halves then fight each other.

> This particular trap is guarded now. `motion_kinematics` compares its
> constant against the value the compiled module reports and **fails loudly**
> on a mismatch, or on a module too old to answer — so the rebuild cannot be
> forgotten silently. See [what this fork adds](#what-this-fork-adds-over-base-serval).

### 7. Home Z and the extruder

As on any stepper machine.

### 8. Couple the belts and home slowly

Low `homing_speed`, hand on the power.

### Recovery, at any step

Any fault or claim failure is recovered the same way: **fix the cause, then
`FIRMWARE_RESTART`.** klippy SIGTERMs the old endpoint (which cleanly disables
the drive), re-spawns it, and re-runs the claim. There is no manual pre-launch,
socket cleanup or endpoint restart to do by hand.

**A latched sync-loss fault — `ErC1.1` "synchronization loss" in ESTUN's
documentation, `ErC11` on the drive's own panel, CoE error register `0x8700`,
EtherCAT AL status `0x001a` — is the exception.**
`FIRMWARE_RESTART` re-spawns the endpoint but does **not** clear the drive's
stored fault — the EtherCAT INIT bounce resets the network state machine, not
the CiA 402 fault. With the drive on its own supply it stays faulted across
host restarts. **Power-cycle the drive** to clear it, then fix the root cause
(almost always RT scheduling) so it does not re-latch on the next boot.

And remember **E8**: every emergency-stop press latches `A.21`/`A.14` and needs
an alarm clear before the machine runs again.

---

# Stage M — Closed-loop tuning

ESTUN exposes its tuning parameters in the manufacturer object area at
`0x3xxx`:

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

**Two ways to write them.** `SERVO_PARAM` from the console, for trying a value:

```
SERVO_PARAM SERVO=motor_x GET=0x3014.0
SERVO_PARAM SERVO=motor_x SET=0x3014.0 VALUE=40 TYPE=u16
```

`SERVO=` takes the `[motor]` name, or the axis name where the axis has a single
servo — both `motor_x` and `x` reach the same drive here. A `SET` reports the
value **read back from the drive**, which is not always the one sent:
out-of-range writes settle at the drive's own limit. A `GET` **without** `TYPE=`
prints raw hex plus both the unsigned and the signed decimal reading, which is
how to tell a negative value from a large positive one when an object's
signedness is not documented.

A `params:` block on the `[motor]` section, for values that must come back on
their own, one per line as `0xINDEX.SUB: [type] value`:

```ini
[motor motor_x]
# ... the options from Stage K ...
params:
  0x3016.0: u16 300
  0x3014.0: u16 40
  0x3012.0: 500        # type omitted: the size is probed by an SDO upload,
                       # which costs one extra mailbox round-trip at claim
```

These are written **at claim time, every start, in the order given**.

### Where a tuned value actually lives — read this before a long tuning session

**Nothing you tune is written to the drive's EEPROM.** Both routes push to
drive **RAM**, and kalico never persists implicitly. What differs is who puts
the value back:

| | Survives a `FIRMWARE_RESTART`? | Survives a **drive** power cycle? |
| --- | --- | --- |
| `SERVO_PARAM SET` at the console | **No.** Nothing re-sends it | **No** |
| `params:` on the `[motor]` section | **Yes** — klippy re-pushes every claim | **Yes**, same reason: the next claim writes it again |
| Neither | — | the drive reverts to whatever its EEPROM holds |

So the console is for **trying** a value and the `params:` block is for
**keeping** one, and a value that only ever existed at the console is gone the
moment anything restarts. Move each value you settle on into `params:` as you
find it, rather than at the end of the session.

**To write the drive's EEPROM deliberately**, SET the CiA 301 store-parameters
object **`0x1010`** — the magic value is in the drive manual. Nothing in this
repository does that for you, by design: the config file is meant to be the
record of how the machine is tuned, so a drive can be swapped and brought back
from `printer.cfg` rather than from whatever happens to be in its EEPROM.

**A bad `params:` line stops the machine starting, on purpose.** Every write is
read back, and a mismatch — the drive clamped the value, or rejected it —
**fails the claim**, naming the offending address, the value written and what
the drive settled on. That is intended behaviour and not a fault: a silently
clamped gain is a machine tuned to a number nobody chose.

Two more limits worth meeting here rather than at the bench:

- **Objects wider than 4 bytes** (strings, segmented transfers) are
  unsupported and fail loudly.
- **SDO traffic is mailbox traffic.** It rides between DC cycles — fast, but
  not deterministic. Anything needing hard-real-time parameter changes has to
  be mapped into the PDO instead, which is a code change, not a config one.

**Order of work:** establish the load inertia ratio (Pn106) first, raise the
speed loop gain (Pn102) until the axis is stiff without audible ringing, then
the position loop gain (Pn104), then add feedforward.

ESTUN's feedforward percentages run **0–100**. The A6-EC's bench-measured
feedforward calibration **does not transfer**.

Notch filters for mechanical resonances are Pn407/Pn408 (filter 1) and
Pn409/Pn410 (filter 2).

**Telemetry.** This repository registers four servo commands and no more:
`SERVO_CAPTURE_START`, `SERVO_CAPTURE_STOP`, `SERVO_PARAM` and
`QUERY_EMERGENCY_STOP`. `SERVO_CAPTURE_START AXIS=<axis>` records the servo on
that axis on its `[ethercat_node]`, even when the node carries several drives;
`SERVO=<motor name>` also works, so nothing depends on a motor being named
`motor_<axis>`. Analyse a capture with `scripts/servo_capture.py --drive
<motor>`.

The calibration macros — `SERVO_FIT_DYNAMICS` among them — are **not in this
repository**. They live in
[serval-dashboard](https://github.com/dderg/serval-dashboard), and a console
that reports "Unknown command" for one of them is missing that install, not a
broken build.

---

# Fault quick reference

| Code | Meaning | First thing to check |
| --- | --- | --- |
| `A.70` | EtherCAT sync error / SYNC0 missed | RT scheduling: `SCHED_FIFO` on the isolated core |
| klippy: `EtherCAT frame-timing fault` / `cycle-skip fault` | the host sent a frame late or missed a whole cycle — the host, not the drive | the Stage L step 3 gate: B5 and B8 first, then `cycle_us: 500` (K3) |
| `A.71` | comms chip internal error | drive firmware or hardware |
| `ERR` | EtherCAT init timeout | `Pn006.0 = 4`? cabling IN/OUT? |
| `A.21` / `A.14` | main power off for more than one AC period | **expected after every emergency stop** — clear it (E8) |
| `A.13` | overvoltage | regenerative capacity — external resistor on `B1`/`B2` |
| `A.23` | brake overcurrent | bleeder resistor too small — below the manual's 50 Ω |
| `A.15` | bleeder resistor error | the external resistor itself: open circuit, or wired to the wrong pair |
| `A.16` | regeneration error | the regenerative *circuit* — check the value and that `Pn521.0` is `0` |
| `A.06` | position error pulse overflow | `Pn504`; also a phase-order or tuning symptom |
| `A.25` | motor line U overcurrent | U/V/W phase order, or mechanical seizure |
| `A.10` / `A.22` | encoder / sensor break | CN2 wiring, shield, 5 V |
| `rc=-2` | no slave matched | vendor/product identity, not necessarily the cable |
| `rc=-4` | a drive never reached OP | read the per-slot `al_state`/`al_status` lines printed with it |
| `rc=-6` | the drive refused the PDO map | `pdo_touch_probe` / `pdo_digital_io` / `pdo_following_error` drop the optional groups **without a rebuild** |
| `rc=-7` | PDO size mismatch | the drive powered up with a different RxPDO assigned to `0x1C12` |
| `rc=-10` | `mlockall` failed | `CAP_IPC_LOCK` — Stage B8 |
| `rc=-11` | CPU pin failed | the isolated core — Stage B5 |
| `rc=-12` | `SCHED_FIFO` failed | `CAP_SYS_NICE` — Stage B8 |
| `rc=-20` | could not hold `/dev/cpu_dma_latency` at 0 | the udev line in Stage B8 — the device is root-only by default |
| `rc=-21` | profile identity missing or zero | `vendor_id` **and** `product_code` both set, from Stage J |

**`rc=-2` deserves emphasis:** a drive that is present but of a *different
identity* looks **exactly** like an absent one to the master. The endpoint
names the profile and identity it matched on — read that line before suspecting
wiring.

**`rc=-4` is the one to expect first on ProNet**, because the profile still
carries assumptions inherited from the drive family this fork was built
against. The endpoint prints what it assumed alongside the failure — the
variable `1600h`/`1A00h` remapping, and the following-error window `6065h` and
timeout `6066h` — so the message names the assumption that broke rather than
leaving a bare code. It is also where a **rejected configuration SDO** surfaces:
the master applies those in PRE-OP, not at the call, so a drive that refuses one
simply never reaches OP.

**`rc=-6` was the other one to expect**, and the `estun-pronet` profile now maps
less to make it less likely. The endpoint prints the map it built at bring-up —
which groups are on and the resulting byte counts — so the log says what the
drive was actually asked for. If a map is still refused, the three `pdo_*`
options move the remaining groups without a rebuild.

None of this is a reason to expect failure. It is what to read when it happens,
and it is the difference between a five-minute fix and an afternoon.

---

# What "done" looks like

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

**The most common reason a machine passes every step and then misbehaves is
that the cold-boot test was skipped.** A marginal real-time setup survives a
warm restart on an idle board and drops frames under boot load. A warm restart
proves nothing.

---

# What this fork adds over base Serval

This repository is a fork of [`dderg/serval`](https://github.com/dderg/serval).
Its `main` at the time of writing is **`14f6296`**, which is the base every
statement below is measured against — by comparing files, not by remembering.

**The size of the change, counted:** of **1876** tracked files here, **76**
differ from upstream's copy of the same path and **25** do not exist upstream
at all. Of those 76, **48 are code** — **11 under `klippy/`** and **37 under
`rust/`**, most of the latter being tests. Everything else is documents,
scripts and CI.

**What that means for trust:** `motion-core` is **byte-identical** to upstream
apart from `kinematics.rs` and `motion_history.rs`, and `bridge/servo.rs` — the
host-to-endpoint servo seam — **is byte-identical**. The planner, fitter,
lowerer, shaper, ingress and pump are upstream's, which the snapshot gate
confirms independently at **51 ok / 0 changed**: the planner's output is the
same as base, byte for byte. **Servo control works exactly as it does in
`dderg/serval`**, because it is the same code.

## 1. Markforged kinematics

Upstream carries **no markforged at all** — this is new ground with no upstream
counterpart, not a modification of something existing.

- `rust/motion-core/src/kinematics.rs` — the matrix (`x = m0 − m1`, `y = m1`),
  matching upstream Klipper's convention, and `MARKFORGED_Y_COUPLING`.
- `klippy/motion_kinematics.py` — the host-side mirror, **runtime-guarded**: it
  compares its constant against the value the compiled module reports and fails
  loudly on a mismatch or a module too old to answer. Stage L step 6's rebuild
  trap cannot come back silently.
- `klippy/stepper.py`, `klippy/extras/homing.py`,
  `klippy/extras/resonance_buzz.py`, `klippy/extras/servo_strain_comp.py`,
  `rust/planner-config/src/from_doc.rs`,
  `rust/motion-engine/src/bridge/homing_api.rs` — markforged branches added.
  **Verified equivalent to upstream for cartesian and corexy on all three
  axes**, by computing the predicates for every (kinematics, axis) pair rather
  than by reading them.
- `klippy/extras/servo_axis.py` — `corexy_fit_layout` now also *refuses*
  markforged, because this fork widened `coupled_xy()` to mean "x and y share
  lanes", which would otherwise newly admit it.

## 2. ESTUN ProNet support, and a configurable PDO map

- **The `estun-pronet` drive profile** in
  `rust/ethercat-rt/csrc/libecrt_igh.c`. It carries no built-in identity (ESTUN
  publishes theirs only in a non-public ESI), so `vendor_id` and
  `product_code` must be supplied — and **both are validated**, because a zero
  product code is not a wildcard.
- It sets `split_torque_limit`, writing the **`60E0h`/`60E1h` pair** instead of
  `6072h`, which ProNet's dictionary does not have; and it derives the
  following error from `607Ah − 6064h` instead of the absent `60F4h`.
- It carries an `assumed_objects` string naming every assumption it makes
  without ESTUN's dictionary, **printed on the failures those assumptions
  cause** — so a first bring-up says which assumption broke rather than
  emitting a bare code.
- **`rust/ethercat-rt/csrc/pdo_map.h`** (new) makes the PDO map runtime-built
  and per-profile. Previously it was two fixed arrays, so an object a drive
  family cannot accept could only be dropped by **editing C and rebuilding** —
  the worst possible shape for a failure that arrives as a bare `rc=-6` at
  first contact. `pdo_touch_probe`, `pdo_digital_io` and `pdo_following_error`
  now move those groups from `printer.cfg`.
- **Two of those groups turned out to be dead on every profile.**
  `tx.touch_probe` and `tx.phys_outputs` are written to the wire every cycle
  and assigned nowhere, and `60B9h`/`60BAh`/`60BCh`/`60FDh` are registered with
  not one `EC_READ` between them — **20 of 50 bytes per drive per cycle, at
  4 kHz, for objects nothing consumes.** `estun-pronet` drops them and exchanges
  **26 bytes instead of 50**. `a6ec` keeps everything and is byte-identical to
  upstream's map; `build_pdo_maps` aborts loudly if that ever drifts.

## 3. The emergency stop

- **`klippy/extras/emergency_stop.py`** is new in this fork. It registers the
  button with `buttons` directly and calls `printer.invoke_shutdown` from the
  callback, bypassing the G-Code mutex — see [K1](#k1-why-emergency_stop-and-not-a-gcode_button-running-m112).

**Four deliberate behavioural differences from upstream, all toward safety**,
all in the stop path. Worth knowing before anyone calls this branch "upstream
plus markforged":

| Where | Upstream | Here |
| --- | --- | --- |
| `ethercat-rt/src/torque.rs` | a disable while one is pending is rejected, and `handle_set_torque` answers a reject by exiting the endpoint | takes the **earlier** of the two times, so a stop can always bring a disable forward |
| `ethercat-rt/src/endpoint/commands.rs` | `ResumeStream` always honoured | **refused** while torque is parked or a disable is pending, closing the homing-thread race |
| `klippy/extras/ethercat_node.py` | a `stop_node` exception propagates out of the shutdown handler | logged loudly and swallowed, so the remaining `klippy:shutdown` handlers **still run** |
| `ethercat-rt/src/endpoint/cycle.rs` | torque-gate fault reported to the host as code `0` | reports the **real** truncated code (`0xFEC7`) and logs it |

## 4. CB2 host support

- **`tools/ethercat-dwmac-rk/`** (new) — generates IgH's Rockchip
  `ec_dwmac-rk` binding from its stmmac file set and wires it into the tree.
  Upstream has no equivalent; IgH ships no native driver matching the RK3566.
- `docs/rewrite/ethercat-host-cb2-rk3566.md` (new) — the host page Stage B
  collates.

## 5. Diagnostics the base fork did not have

Found by auditing and fixed here, each with a test that fails without the fix:

- **Diag ring tags 9 and 10** resolved as `unknown`, dropping the positions and
  counts that explain a step-overrun fault (`rust/runtime/src/log_codes.rs`).
- **`RT_PHASE_*`, `DIAG_EV_*` and the transport `RUNTIME_ERR_*` codes** all
  claimed "must match" across the C/Rust boundary with **nothing checking**.
  `rust/runtime/src/c_header_mirrors.rs` and
  `rust/ethercat-rt/tests/result_code_mirrors.rs` (both new) now check them.
- **The log-level scale** was half-named and its comment pointed at the wrong
  crate; **the step-queue depth target** was written down twice and rounded by
  two different expressions.
- **`klippy/extras/bus.py`** reused the protocol lookup's `%c` format under
  Python's `%`, emitting `oid=\x05 value=\x01` where every sibling writes `%d`.
- **`klippy/extras/log_observability.py`** armed a 60 s timer whose probe was a
  hardcoded `return None` — it rescheduled forever and could never report
  anything. Removed; 31 lines of dead code went with it.
- **`scripts/ci.sh`** counted gates whose tool was absent as **passes**, so a
  run claiming 20 passes had run 18. They now report `SKIP`.

## 6. Documentation and tests

All of `docs/rewrite/estun-pronet-markforged-setup.md`,
`ethercat-host-cb2-rk3566.md`, `repo-audit-status.md` and this page are new
here, as are eleven test files that hold them to the code — among them
`test_setup_guide_config.py` (the guide's worked config must parse through the
same reader klippy uses), `test_host_docs_parity.py`, `test_emergency_stop.py`,
`test_pdo_map.py`, `test_ethercat_claim_stub.py` and
`tools/sim/tests/test_ethercat_world.py`.

**Upstream internals are deliberately left alone.** Base Serval runs on
hardware; the planner's pipeline stages, `geometry` and `motion-pipeline` are
untouched here, because a change there moves motion output and needs a
regenerated snapshot baseline — which is the owner's call, not an auditor's.

---

# Still unverified on hardware

Carried forward honestly. **None of the following has run on real hardware.**

1. **The whole CB2 host path beyond the build itself.** `ec_dwmac-rk` compiles
   and its symbols resolve against `ec_master.ko`; it has **never been inserted
   into a running kernel, bound to a MAC, or used to reach a drive**. The
   handover script follows the shape of the working `ec_macb` one but has not
   been executed. **Treat the first bring-up as debugging, not installation.**
   A Pi 5 host avoids this one entirely.
2. **The ESTUN vendor ID and product code** — no public ESI; read them off the
   bus at Stage J.
3. **The Markforged belt coupling sign** — Stage L step 6 checks it.
4. **Whether 60 W per drive is enough regenerative capacity for this gantry.**
   The figure is the drive manual's recommendation, not a measurement against
   this machine's moving mass. `A.13` under hard decel is what says otherwise.
5. **Three values belonging to the `-EC` variant** that cannot be confirmed
   against the base ProNet manual: `Pn006.0 = 4` (that manual's `Pn006` range
   stops at `0x2133`), and the alarm codes **`A.70`** and **`A.71`** (its alarm
   table runs `A.00` to `A.69`).
6. **The CN2 encoder pinout**, which is an inference by elimination rather than
   a quotation — see [diagram 3](#3-one-drives-terminals).

Every other drive value in this document — the `A.06`, `A.10`, `A.13`, `A.22`
and `A.25` meanings, the U/V/W to A/B/C mapping, the encoder resolutions, the
0.9 kVA figure, `Pn004.0`, `Pn521`, the 0–55 °C and 45 °C limits, the 10/50 mm
spacing, the 300 mm separation, and every `Pn` in Stage M with its unit and
range — **was read back out of ProNet manual V2.19 and matches.**

## Known limits that are decisions, not oversights

- **`[emergency_stop]` accepts an inverted or pulled-down pin without
  complaint.** `^!PF1` and `~PF1` both halt on a press and both do nothing at
  all with the wire off, so the wrong polarity disables the input silently.
  Refusing `!` and `~` at config time was proposed and **declined by the
  repository owner**: the polarity stays a configuration choice, and a machine
  wired the documented way is unaffected. Wire NC to ground on `^PF1` and this
  cannot bite you.
- **`stop_node` blocks the reactor** rather than using the
  `_start`/`endpoint_call_done` split, against a comment in
  `klippy/motion_engine.py` naming that as the cause of "Timer too close".
  Recorded, deliberately not changed.

---

# See also

- [`estun-pronet-markforged-setup.md`](estun-pronet-markforged-setup.md) — the
  source build document this page collates, with the full reasoning behind
  every mains decision.
- [`ethercat-host-cb2-rk3566.md`](ethercat-host-cb2-rk3566.md) — the CB2 host
  page, in its own right.
- [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) — the Pi 5
  host alternative, which **has** been exercised on the bench.
- [`ethercat-bench-bringup.md`](ethercat-bench-bringup.md) — drive profiles,
  SDO parameters, telemetry capture and the real-time scheduling rules in
  depth.
- [`repo-audit-status.md`](repo-audit-status.md) — what has been audited in
  this fork, what was found, and what was checked and found sound.
- [`../Config_Reference_Motion.md`](../Config_Reference_Motion.md) — every
  motion config option this fork reads.
