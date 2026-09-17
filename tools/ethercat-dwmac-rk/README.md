# `ec_dwmac` — native EtherCAT driver for the Rockchip platform GMAC

Generates the missing IgH binding that lets a Rockchip-based host (RK3566 on a
BTT CB2, RK3588) drive EtherCAT natively instead of falling back to
`ec_generic`.

## Why this exists

The endpoint's DC loop needs a native NIC driver. IgH's `generic` driver pushes
every frame through the Linux net stack, and the resulting jitter makes a servo
drive miss its SYNC0 window and latch a sync-loss fault — `A.70` on ESTUN
ProNet, `ErC1.1` on the A6-EC. The reasoning is in
[`ethercat-igh-macb-install.md`](../../docs/rewrite/ethercat-igh-macb-install.md).

IgH ships native drivers for `e1000e`, `igb`, `r8169`, `genet`, `macb` and
others. None of them match a Rockchip SoC, whose GbE is a Synopsys DesignWare
MAC driven by `stmmac` through the `rk_gmac-dwmac` platform glue.

## What was already done upstream, and what was not

IgH stable-1.6 already carries the **entire stmmac core**, EtherCAT-ified for
kernels 6.1, 6.4 and 6.12:

- `stmmac_main-<kv>-ethercat.c` — 62 `ecdev` hook sites
- every HW layer — `dwmac4`, `dwmac1000`, `dwmac100`, `dwxgmac2`, `hwif`,
  `descs`, `ring_mode`, `chain_mode`
- two bindings — `stmmac_pci` and `dwmac-intel`

Missing is only the path a Rockchip board takes to reach that core:

| File | Role | State |
| --- | --- | --- |
| `stmmac_platform.{c,h}` | generic DT/platform binding | **absent from IgH** |
| `dwmac-rk.c` | Rockchip glue | **absent from IgH** |

So this is a binding port, not a driver written from scratch. The distinction
matters: no DMA, descriptor or NAPI logic is being authored here.

## The transform

IgH's bindings contain **no EtherCAT logic of their own** — verified by
`grep -c ecdev` returning 0 for both `stmmac_pci-6.12-ethercat.c` and
`dwmac-intel-6.12-ethercat.c`. Every hook lives in `stmmac_main`. Diffing
`stmmac_pci-6.12-orig.c` against its `-ethercat` twin therefore yields the
complete recipe, and `generate.py` implements exactly it:

1. Local includes rewritten to their versioned `-ethercat` form.
2. `stmmac_dvr_probe`/`stmmac_dvr_remove` → `stmmac_ec_dvr_probe`/
   `stmmac_ec_dvr_remove`, the EtherCAT-aware entry points the patched core
   exports (declared in `stmmac-6.12-ethercat.h`).
3. `MODULE_DEVICE_TABLE` commented out, so the EtherCAT module never
   auto-binds and races the stock driver for the device.
4. `module_platform_driver()` replaced by an explicit `init`/`exit` pair that
   brackets registration with `stmmac_init()`/`stmmac_exit()`, because the
   patched core no longer registers itself.
5. `MODULE_DESCRIPTION` marked EtherCAT-enabled.

## Running it

```sh
python3 tools/ethercat-dwmac-rk/generate.py \
    --igh ~/ethercat-igh/devices/stmmac \
    --work /tmp/ec-dwmac
```

Then copy `/tmp/ec-dwmac/devices-stmmac/*` into `~/ethercat-igh/devices/stmmac/`,
add the six new filenames to that directory's `Makefile.am` `EXTRA_DIST` list
alongside the `dwmac-intel` entries, and wire `dwmac-rk` into `Kbuild.in` and
`configure.ac` following how `dwmac-intel` is wired.

Build with `--enable-stmmac` (see the master's `configure --help` for the exact
flag as shipped) and load `ec_dwmac` in place of `ec_generic`.

## What the generator verifies, and what it cannot

Verified automatically, aborting on failure:

- Each `-orig` file reproduces upstream **byte for byte**, so the pair is a
  faithful baseline and later diffs mean something.
- Every local include resolves, to a file IgH ships or one generated here.
  This is the check that catches a missing dependency, and it is why
  `stmmac_platform` is generated at all.
- No call still reaches the non-EtherCAT probe path.
- The driver does not auto-bind and does bracket registration.

**Not verified: it has never been compiled or run.** The generator emits source
and checks its structure; it cannot substitute for a build against real kernel
headers, and nothing here has touched hardware. Treat a clean run as "the port
is structurally sound", not "the driver works".

Two further unknowns a build will surface first:

- **Kernel version.** IgH's stmmac file set stops at 6.12 while its `macb` set
  is at 6.18, so a Rockchip host should run a 6.12-series PREEMPT_RT kernel to
  match. A different kernel needs the file set rebased via IgH's `update.sh`.
- **ABI drift.** `dwmac-intel-6.12-ethercat.c` carries a `LINUX_VERSION_CODE`
  shim for a `plat_stmmacenet_data` member removed in 6.12.78. `dwmac-rk` may
  need its own shim; a compile error naming a struct member is that, not a
  mistake in the transform.

## Bench validation

Bring it up in this order, and stop at the first step that fails:

1. **Module loads.** `modprobe ec_dwmac`, then confirm the master attaches the
   NIC rather than falling back: `ethercat master` reports the device, and the
   log shows the device being claimed.
2. **Slaves enumerate.** `ethercat slaves` lists every drive at `PREOP`. Same
   count and order as under `ec_generic` — a different count means the binding
   is claiming the wrong device.
3. **Second NIC still works.** On a two-MAC board keep one interface on the
   stock `stmmac` for SSH; confirm it is unaffected.
4. **Cadence under load.** Run the endpoint at the target `cycle_us` and watch
   for `A.70`. The comparison that matters is a **cold boot**, not a warm
   restart: `ec_generic` typically survives an idle bench and fails under boot
   load, so a warm test proves nothing.
5. **Measure.** Compare against `ec_generic` on the same hardware before
   trusting it. Published RK3588 figures for this approach are a TX idle mean
   of 3.310 → 1.810 us and execution mean 5.529 → 4.275 us at a 1 ms cycle with
   three slaves; RX metrics did not improve.

## Prior art

[`VictorJiaxinWang/rk3588-igh-native-stmmac`](https://github.com/VictorJiaxinWang/rk3588-igh-native-stmmac)
does the same thing for RK3588 against IgH 1.5.3 and Linux 5.10.160-rt89 —
different versions on both sides, so not directly reusable, but a useful
cross-check. Its author notes long-duration and fault-injection validation are
still outstanding.
