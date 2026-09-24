# EtherCAT host on a BTT CB2 (RK3566)

Turns a BTT CB2 — the compute module in a Manta M8P's BTB socket — into the
real-time EtherCAT host that drives the servo endpoint.

The companion document
[`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) does the same job
for a Raspberry Pi 5. **Follow one or the other, not both**: they need different
kernels and different NIC drivers, and mixing their version numbers is the
easiest way to end up with a master that will not build.

| | Pi 5 | CB2 |
| --- | --- | --- |
| SoC | BCM2712 + RP1 | Rockchip RK3566 |
| Ethernet MAC | Cadence GEM (`macb`) | Synopsys DesignWare (`stmmac`) |
| Native driver | `ec_macb` | `ec_dwmac-rk` |
| Kernel | 6.18.33, Raspberry Pi OS RT build | **6.12+, PREEMPT_RT built in** |
| Status | exercised on the bench | **builds; never run** |

## Read this first

The CB2 path has **never been run**. The driver compiles and its symbols
resolve, but nothing here has been loaded on hardware. Anyone bringing up a
printer for the first time should use a Pi 5, get the machine working, and come
back to this afterwards — that way a fault has one candidate cause instead of
two.

## Why the kernel version is not negotiable

Two independent requirements happen to meet at 6.12:

- **PREEMPT_RT is built into mainline from 6.12.** Before that it was an
  out-of-tree patch that had to match the kernel exactly. From 6.12 it is
  `CONFIG_PREEMPT_RT`, a menuconfig option, on arm64 among others.
- **IgH's stmmac file set stops at 6.12.** The master ships its EtherCAT-ified
  copies of the stmmac driver for 6.1, 6.4 and 6.12 only, and `ec_dwmac-rk` is
  generated against that set.

So: **a 6.12-series kernel with `CONFIG_PREEMPT_RT=y`.** BTT's own CB2 image
ships Debian bookworm with kernel 6.1, which is too old on both counts and
cannot be used as-is.

## Step 1 — A 6.12 PREEMPT_RT kernel

The CB2 is a supported Armbian board (`bigtreetech-cb2`). Its device tree,
`rk3566-bigtreetech-pi2.dts`, reached mainline Linux only in 6.14; on 6.12 it
comes from Armbian's own patch set, which is one more reason to build the image
with Armbian rather than from a plain 6.12 tree. Build an image with the kernel
configured for real time:

```sh
git clone --depth 1 --branch v25.11.1 https://github.com/armbian/build
cd build
./compile.sh BOARD=bigtreetech-cb2 BRANCH=current RELEASE=trixie \
             BUILD_MINIMAL=yes BUILD_DESKTOP=no \
             INSTALL_HEADERS=yes BSPFREEZE=yes \
             KERNEL_CONFIGURE=yes
```

`KERNEL_CONFIGURE=yes` opens menuconfig. Set, and confirm each one:

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
clone offers no branch this build can use. Flash the resulting image and boot it.

**Two more options on that line, and one in the table, are not optional.**
`INSTALL_HEADERS=yes` puts this kernel's own headers on the image, which the
IgH modules build against. `BSPFREEZE=yes` holds the kernel, headers, device
tree and bootloader packages: Armbian's repository publishes newer builds under
the same names — `linux-image-current-rockchip64` is 6.18 there, not RT — so
without the hold the first `apt upgrade` replaces this kernel and the EtherCAT
module no longer loads. And `CONFIG_NO_HZ_FULL` is what `nohz_full=3` and
`rcu_nocbs=3` in the core-isolation step need; without it the kernel ignores
both, and the isolation check still passes because `isolcpus` works regardless.

**Verify.** On the booted CB2, all three must hold:

```sh
uname -r                      # 6.12.x
uname -v | grep -i preempt_rt # must mention PREEMPT_RT
zgrep CONFIG_PREEMPT_RT /proc/config.gz   # =y  (if config.gz is present)
apt-mark showhold | grep linux-image      # linux-image-current-rockchip64
ls -d /lib/modules/$(uname -r)/build      # the headers step 6 builds against
```

A kernel that boots but reports `PREEMPT` rather than `PREEMPT_RT` is the
ordinary low-latency kernel and is **not** sufficient — it is exactly the
configuration that holds cadence on an idle bench and drops frames under load.

## Step 2 — Get off `eth0`, on the newly booted image

Step 8 gives `eth0` to the EtherCAT master, and once it does the interface
leaves the normal network stack. On a CB2 in a Manta socket there is often no
display attached, so **if SSH is on `eth0` when that happens, the board becomes
unreachable** — and the handover runs at every boot from then on.

Put SSH on the CB2's Wi-Fi, reboot, and confirm you can still
log in with the Ethernet cable unplugged:

```sh
ip route get 1.1.1.1      # must not leave via eth0
```

Keep a serial console to hand regardless. Recovering a headless board whose only
route went to the EtherCAT master otherwise means pulling the eMMC.

## Step 3 — What to install on the CB2 first

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
| `autoconf automake libtool` | IgH's `./bootstrap` (step 6) has nothing to run |
| kernel headers for the running kernel | already on the image from step 1's `INSTALL_HEADERS=yes`. **Do not** `apt install linux-headers-current-rockchip64`: the repository's package of that name is the 6.18 build, and `make modules` (step 6) needs this kernel's |
| `libudev-dev pkg-config` | the Rust build (step 11) fails in the `serialport` crate, which links `libudev`. This one is easy to mistake for a Rust problem |
| `python3-dev libffi-dev` | klippy's `chelper` cannot compile its C at first start |
| `gcc-arm-none-eabi` and friends | the Manta firmware build stops at `arm-none-eabi-gcc: No such file or directory` |
| `rustup` | `rust/rust-toolchain.toml` pins Rust **1.85.0** and the `thumbv7em-none-eabi` target, so rustup fetches both on first build. A distro `rustc` is the wrong version and has no ARM target |

**The firmware build is the one no gate covers.** `ci.sh rust-mcu-h7` compiles
the Rust half of the MCU for `thumbv7em-none-eabi`; nothing in CI compiles the
C firmware or links `out/klipper.bin`, because no CI image carries an ARM
toolchain. A green gate therefore does not mean the firmware builds — the
first machine to find out is this one.

## Step 4 — Get this repository, and a klippy to run it

Everything after this runs inside a checkout, and nothing so far has made one:
step 6 runs `generate.py` out of `tools/`, step 11 builds in `rust/`, and step 9
writes a drop-in for a `klipper.service` that does not exist yet.

Install Klipper or Kalico first, by whatever route you normally would —
[KIAUH](../Installation.md#installing-via-kiauh) is the usual one on an SBC.
That creates `~/printer_data/`, the klippy virtualenv and the `klipper.service`
the RT drop-in extends. Then bring it onto this fork:

```sh
cd ~/klipper
git remote add serval https://github.com/PDAMUK/serval.git
git fetch serval
git checkout <the branch carrying this document>
~/klippy-env/bin/pip install -r scripts/klippy-requirements.txt
```

The last line matters if KIAUH installed mainline Klipper: this fork's klippy
imports `numpy` at startup, and Klipper's own requirements do not carry it.

**It must be this fork.** `docs/Quickstart.md` points at `dderg/kalico`, the
upstream this is built on, which carries no markforged kinematics, no
`estun-pronet` drive profile, no `[emergency_stop]` section and none of the
`pdo_*` options. If you are reading this from a checkout you are already on the
right branch.

## Step 5 — Isolate a core for the DC loop

The endpoint pins its cycle loop to one CPU and needs that CPU contention-free.
Add to the kernel command line (on Armbian, `/boot/armbianEnv.txt`, via
`extraargs=`):

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

**Verify.**

```sh
cat /sys/devices/system/cpu/isolated     # 3
cat /sys/devices/system/cpu/nohz_full    # 3 — absent or empty means CONFIG_NO_HZ_FULL is off
cat /proc/irq/default_smp_affinity       # 7 — CPUs 0-2
cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor   # performance
grep -lx 3 /proc/irq/*/effective_affinity_list   # prints nothing
```

## Step 6 — Build the IgH master with `ec_dwmac-rk`

The headers are already on the image — step 1's `INSTALL_HEADERS=yes` — and
step 1's check confirmed `/lib/modules/$(uname -r)/build`.

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

**Verify.**

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

## Step 7 — Find the MAC's device path

The handover script needs the **platform device name of the CB2's GMAC**, which
is a property of the board and must be read off it rather than copied from a
guide:

```sh
ls -l /sys/bus/platform/drivers/rk_gmac-dwmac/
```

The entry that is not `bind`, `unbind`, `uevent` or `module` is the device —
something of the form `<address>.ethernet`. Record it; Step 8 needs it.

Cross-check that it is the interface carrying `eth0`:

```sh
basename "$(readlink -f /sys/class/net/eth0/device)"
```

Both commands must name the same device.

## Step 8 — Hand the NIC to `ec_dwmac-rk` at boot

The in-tree `stmmac` driver claims the MAC at boot, so a service must hand it
over before the master starts. Install as `/usr/local/sbin/ethercat-dwmac-up.sh`
(root, `chmod 755`), replacing `DEV` with the value from Step 7:

```bash
#!/bin/bash
# Hand the RK3566 GMAC from the in-tree stmmac driver to ec_dwmac-rk, then
# start the IgH master. Idempotent.
set -u
DEV=<from-step-4>.ethernet          # e.g. fe010000.ethernet
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

The MAC is matched as a string, so **lowercase with colons** — an uppercase one
produces a master that loads and finds no link, which is the third row of the
troubleshooting table below. `DEVICE_MODULES` takes the name without the `ec_`
prefix, exactly as the Pi 5 path writes `macb` for `ec_macb`.

Run it at boot, before klipper. `/etc/systemd/system/ethercat-dwmac.service`:

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

The master creates `/dev/EtherCAT0` root-owned, and klippy spawns the endpoint
as the klipper user, so it needs a udev rule or the endpoint cannot open the
master at all. `/etc/udev/rules.d/99-ethercat.rules`:

```
KERNEL=="EtherCAT[0-9]*", MODE="0660", GROUP="<your-user>"
```

**Armbian runs NetworkManager by default**, and it will fight the handover at
boot by reclaiming the interface. Tell it not to manage `eth0` —
`/etc/NetworkManager/conf.d/99-ethercat-unmanaged.conf`:

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

**Verify.**

```sh
basename "$(readlink /sys/bus/platform/devices/<DEV>/driver)"   # ec_rk_gmac-dwmac
ethercat master            # must report the master up with a link
ls -l /dev/EtherCAT0       # must exist, and be readable by the klipper user
ip link show eth0          # the interface should no longer be managed normally
```

`eth0` disappearing from the normal network stack is **correct** — the master
owns it now. This is why SSH must be on Wi-Fi before starting.

## Step 9 — Real-time capabilities for the endpoint

Identical to the Pi 5 path. The endpoint needs `CAP_SYS_NICE` (for
`SCHED_FIFO`) and `CAP_IPC_LOCK` (for `mlockall`), granted on the klipper
service so they survive endpoint rebuilds:

`/etc/systemd/system/klipper.service.d/10-ethercat-rt.conf`

```ini
[Service]
AmbientCapabilities=CAP_SYS_NICE CAP_IPC_LOCK
LimitRTPRIO=infinity
LimitMEMLOCK=infinity
```

Then `systemctl daemon-reload`.

The endpoint also opens `/dev/cpu_dma_latency` and holds it at `0`, keeping
every core out of deep idle states. The device is root-only and neither
capability covers it, so add a second line to the udev rule file from step 8,
`/etc/udev/rules.d/99-ethercat.rules`:

```
KERNEL=="cpu_dma_latency", MODE="0660", GROUP="<your-user>"
```

Without it the hardware endpoint fails its claim with `rc=-20`.

**Verify, once the endpoint is running** (sample the steady-state pid, not the
first 200 ms):

```sh
pid=$(pgrep -f release/ethercat-rt)
chrt -p $pid                              # SCHED_FIFO priority 80
grep Cpus_allowed_list /proc/$pid/status  # 3
sudo journalctl -b | grep -c 'al_status=0x001a'   # 0 — any hit is DC sync loss
```

That needs drives in `OP`, which means a claimed node and a config: run it at
the build guide's first real-endpoint step, and on a cold boot, not here.

## Step 10 — Confirm the bus before trusting it

With drives wired and powered:

```sh
ethercat slaves
```

Every drive must appear, in wired order, reaching `PREOP`.

**The test that matters is a cold boot.** `ec_generic` — and a
not-quite-real-time kernel — will both survive a warm restart on an idle bench
and fail under boot load. Power the machine down fully, boot it, and watch for
`A.70` on the drives. A warm restart proves nothing.

## Step 11 — Build the kalico endpoint

klippy spawns the endpoint itself at claim time and never launches it by hand,
so the binary has to exist before the first claim. `[ethercat_node].endpoint`
defaults to `rust/target/release/ethercat-rt`.

Build it on the CB2 — the `hw` build compiles the IgH C shim and links
`libethercat` from `/opt/etherlab`, so it cannot be cross-compiled:

```sh
make -f Makefile.rust ethercat-endpoint-hw     # -> rust/target/release/ethercat-rt
```

> **If the master is not at `/opt/etherlab`.** `build.rs` reads `IGH_DIR` for
> the prefix and `IGH_LIB_DIR` for the library directory, defaulting to
> `/opt/etherlab` and `$IGH_DIR/lib`. Build against a different prefix with
> `IGH_DIR=/usr/local make -f Makefile.rust ethercat-endpoint-hw`. Without the
> headers the build now stops and says so, naming the file it wanted, rather
> than failing inside the C compiler.

**Budget for this before starting it.** What this build compiles — the
endpoint, the stub and the three klippy modules, all release — leaves about
1.1 GB in `rust/target` (measured on x86_64; an arm64 build is the same order).
The 19-25 GB figure that goes with this workspace is the contributor gate's —
every crate's debug test binaries — which is the thing not to run here. RAM is
the tighter limit on a CB2: 2-4 GB, and four parallel `rustc` processes linking
the larger crates will run a 2 GB board out of memory, so pass `-j2` or set
`CARGO_BUILD_JOBS=2` rather than discovering it as a killed compiler. A full
disk surfaces as `ld terminated with signal 7 [Bus error]`, which reads like a
broken toolchain and is not one; all of `rust/target` regenerates, and
`cargo clean` in `rust/` frees it.

Build only what the printer runs. The endpoint and the klippy modules below are
the whole list. **Do not run `./scripts/ci.sh` on this board** — it compiles and
runs every crate's test binaries as well, which is an hour of A55 and disk this
machine does not have spare. That gate belongs on a development machine, and
the build guide's Part 11 says so.

The staged bring-up starts with a **drive-off dry run** against the stub, which
is a separate binary and a separate build:

```sh
make -f Makefile.rust ethercat-stub            # -> rust/target/release/ethercat-rt-stub
```

`scripts/build-native.sh` builds both klippy extension modules and, with
`--bench`, an endpoint — but its auto-detection picks *one*: with `/opt/etherlab`
installed it builds `ethercat-rt` and skips the stub. Since this page installs
`/opt/etherlab`, ask for each one explicitly rather than relying on the
detection:

```sh
scripts/build-native.sh --bench --ethercat stub   # Part 12 step 1
scripts/build-native.sh --bench --ethercat hw     # Part 12 step 2 onwards
```

Then return to
[`estun-pronet-markforged-setup.md`](estun-pronet-markforged-setup.md) Part 10.

## If the module will not load

| Symptom | Cause |
| --- | --- |
| `ec_dwmac-rk: Unknown symbol ecdev_*` | `ec_master.ko` not loaded first; `/opt/etherlab/etc/init.d/ethercat start` loads it |
| `modprobe: module not found` | `depmod -a` not run after `modules_install` |
| `modprobe: ... Invalid module format` or a version-magic complaint | built against a different kernel tree than the running one — check `modinfo -F vermagic` against `uname -r` |
| Builds, but `ethercat master` shows no link | `MASTER0_DEVICE` MAC does not match `eth0` |
| Device stays bound to `stmmac` | `driver_override` written after the driver already bound — the unbind step is what fixes it |
| Compile error naming a struct member | kernel is not 6.12-series; see the version note above |

## See also

- [`markforged-cb2-complete-build.md`](markforged-cb2-complete-build.md) —
  every step of this build collated into one document for the CB2 route,
  with wiring diagrams and what this fork adds over base Serval. Follow
  that one to build; read these for the reasoning behind each decision.
- [`estun-pronet-markforged-setup.md`](estun-pronet-markforged-setup.md) — the
  build this host serves; return to it at Part 10.
- [`ethercat-igh-macb-install.md`](ethercat-igh-macb-install.md) — the Pi 5
  path, exercised on the bench. Worth reading alongside this one: where the two
  differ it is the SoC, not the method.
- [`tools/ethercat-dwmac-rk/README.md`](../../tools/ethercat-dwmac-rk/README.md)
  — what the generator does to IgH's tree, and what it verifies.
- [`ethercat-bench-bringup.md`](ethercat-bench-bringup.md) — drive profiles,
  SDO parameters and the real-time scheduling rules in depth.

## Still unverified

Everything on this page beyond the build itself. `ec_dwmac-rk` compiles and its
symbols resolve against `ec_master.ko`; it has never been inserted into a
running kernel, bound to a MAC, or used to reach a drive. The handover script
follows the shape of the working `ec_macb` one but has not been executed. Treat
the first bring-up as debugging, not installation.
