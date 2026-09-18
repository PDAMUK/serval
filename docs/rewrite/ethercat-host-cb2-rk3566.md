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

## Get off `eth0` first

Step 5 gives `eth0` to the EtherCAT master, and once it does the interface
leaves the normal network stack. On a CB2 in a Manta socket there is often no
display attached, so **if SSH is on `eth0` when that happens, the board becomes
unreachable** — and the handover runs at every boot from then on.

Before Step 5, put SSH on the CB2's Wi-Fi, reboot, and confirm you can still
log in with the Ethernet cable unplugged:

```sh
ip route get 1.1.1.1      # must not leave via eth0
```

Keep a serial console to hand regardless. Recovering a headless board whose only
route went to the EtherCAT master otherwise means pulling the eMMC.

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

The CB2 is a supported Armbian board (`bigtreetech-cb2`), and its device tree
`rk3566-bigtreetech-pi2.dts` is in mainline Linux. Build an image with the
kernel configured for real time:

```sh
git clone --depth 1 https://github.com/armbian/build
cd build
./compile.sh BOARD=bigtreetech-cb2 RELEASE=trixie \
             BUILD_MINIMAL=yes BUILD_DESKTOP=no \
             KERNEL_CONFIGURE=yes
```

`KERNEL_CONFIGURE=yes` opens menuconfig. Set, and confirm each one:

| Menu path | Option | Value |
| --- | --- | --- |
| General setup → Preemption Model | `CONFIG_PREEMPT_RT` | Fully Preemptible Kernel (Real-Time) |
| Device Drivers → Network device support → Ethernet → STMicro | `CONFIG_STMMAC_ETH` | M |
| same | `CONFIG_STMMAC_PLATFORM` | M |
| same | `CONFIG_DWMAC_ROCKCHIP` | M |

Pick a kernel branch that lands on **6.12**; Armbian's branch names move, so
check what the build offers rather than assuming. Flash the resulting image and
boot it.

**Verify.** On the booted CB2, all three must hold:

```sh
uname -r                      # 6.12.x
uname -v | grep -i preempt_rt # must mention PREEMPT_RT
zgrep CONFIG_PREEMPT_RT /proc/config.gz   # =y  (if config.gz is present)
```

A kernel that boots but reports `PREEMPT` rather than `PREEMPT_RT` is the
ordinary low-latency kernel and is **not** sufficient — it is exactly the
configuration that holds cadence on an idle bench and drops frames under load.

## Step 2 — Isolate a core for the DC loop

The endpoint pins its cycle loop to one CPU and needs that CPU contention-free.
Add to the kernel command line (on Armbian, `/boot/armbianEnv.txt`, via
`extraargs=`):

```
isolcpus=domain,managed_irq,3 nohz_full=3 rcu_nocbs=3
```

The RK3566 is quad-core, so CPU 3 is the last one. Reboot.

**Verify.**

```sh
cat /sys/devices/system/cpu/isolated     # 3
```

## Step 3 — Build the IgH master with `ec_dwmac-rk`

Kernel headers matching the running kernel must be installed first; Armbian
ships them as `linux-headers-*` for the branch that was built.

```sh
git clone -b stable-1.6 https://gitlab.com/etherlab.org/ethercat.git ~/ethercat-igh

# Generate the Rockchip binding and wire it into the tree.
python3 /path/to/serval/tools/ethercat-dwmac-rk/generate.py \
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
ls /lib/modules/$(uname -r)/extra/ec_dwmac-rk.ko   # or wherever modules_install put it
modinfo ec_dwmac-rk | head -5
```

## Step 4 — Find the MAC's device path

The handover script needs the **platform device name of the CB2's GMAC**, which
is a property of the board and must be read off it rather than copied from a
guide:

```sh
ls -l /sys/bus/platform/drivers/rk_gmac-dwmac/
```

The entry that is not `bind`, `unbind`, `uevent` or `module` is the device —
something of the form `<address>.ethernet`. Record it; Step 5 needs it.

Cross-check that it is the interface carrying `eth0`:

```sh
basename "$(readlink -f /sys/class/net/eth0/device)"
```

Both commands must name the same device.

## Step 5 — Hand the NIC to `ec_dwmac-rk` at boot

The in-tree `stmmac` driver claims the MAC at boot, so a service must hand it
over before the master starts. Install as `/usr/local/sbin/ethercat-dwmac-up.sh`
(root, `chmod 755`), replacing `DEV` with the value from Step 4:

```bash
#!/bin/bash
# Hand the RK3566 GMAC from the in-tree stmmac driver to ec_dwmac-rk, then
# start the IgH master. Idempotent.
set -u
DEV=<from-step-4>.ethernet          # e.g. fe010000.ethernet
SYS=/sys/bus/platform

[ -e "$SYS/devices/$DEV/driver_override" ] && \
    echo ec_dwmac-rk > "$SYS/devices/$DEV/driver_override"

cur=$(basename "$(readlink "$SYS/devices/$DEV/driver" 2>/dev/null)" 2>/dev/null || true)
if [ -n "$cur" ] && [ "$cur" != ec_dwmac-rk ]; then
    echo "$DEV" > "$SYS/drivers/$cur/unbind" 2>/dev/null || true
fi

modprobe ec_dwmac-rk
echo "$DEV" > "$SYS/drivers/ec_dwmac-rk/bind" 2>/dev/null || true
/etc/init.d/ethercat start
```

Configure the master to expect this MAC. In `/etc/ethercat.conf`:

```
MASTER0_DEVICE="<eth0 MAC, lowercase, e.g. 2c:cf:67:7d:37:1b>"
DEVICE_MODULES="dwmac-rk"
```

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
ethercat master            # must report the master up with a link
ls -l /dev/EtherCAT0       # must exist, and be readable by the klipper user
ip link show eth0          # the interface should no longer be managed normally
```

`eth0` disappearing from the normal network stack is **correct** — the master
owns it now. This is why SSH must be on Wi-Fi before starting.

## Step 6 — Real-time capabilities for the endpoint

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

**Verify, once the endpoint is running** (sample the steady-state pid, not the
first 200 ms):

```sh
pid=$(pgrep -f release/ethercat-rt)
chrt -p $pid                              # SCHED_FIFO priority 80
grep Cpus_allowed_list /proc/$pid/status  # 3
```

## Step 7 — Confirm the bus before trusting it

With drives wired and powered:

```sh
ethercat slaves
```

Every drive must appear, in wired order, reaching `PREOP`.

**The test that matters is a cold boot.** `ec_generic` — and a
not-quite-real-time kernel — will both survive a warm restart on an idle bench
and fail under boot load. Power the machine down fully, boot it, and watch for
`A.70` on the drives. A warm restart proves nothing.

## Step 8 — Build the kalico endpoint

klippy spawns the endpoint itself at claim time and never launches it by hand,
so the binary has to exist before the first claim. `[ethercat_node].endpoint`
defaults to `rust/target/release/ethercat-rt`.

Build it on the CB2 — the `hw` build compiles the IgH C shim and links
`libethercat` from `/opt/etherlab`, so it cannot be cross-compiled:

```sh
make -f Makefile.rust ethercat-endpoint-hw     # -> rust/target/release/ethercat-rt
```

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
| `ec_dwmac-rk: Unknown symbol ecdev_*` | `ec_master.ko` not loaded first; `/etc/init.d/ethercat start` loads it |
| `modprobe: module not found` | `depmod -a` not run after `modules_install` |
| Builds, but `ethercat master` shows no link | `MASTER0_DEVICE` MAC does not match `eth0` |
| Device stays bound to `stmmac` | `driver_override` written after the driver already bound — the unbind step is what fixes it |
| Compile error naming a struct member | kernel is not 6.12-series; see the version note above |

## See also

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
