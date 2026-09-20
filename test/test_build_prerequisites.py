"""The host pages must name what has to be installed before their build steps.

A minimal Armbian image carries none of it, and the CB2 path fails at four
separate points without it — `./bootstrap` with no autotools, `make modules`
with no kernel headers, the Rust build inside the `serialport` crate for want
of `libudev-dev`, and the firmware at `arm-none-eabi-gcc: No such file or
directory`. Neither CB2 document listed a single package.

The `libudev-dev` one is the reason this file exists: it surfaces as a Rust
compile failure, so it reads as a toolchain problem rather than a missing
`-dev` package, and it was hit during the audit itself.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CB2_PAGES = [
    "docs/rewrite/ethercat-host-cb2-rk3566.md",
    "docs/rewrite/markforged-cb2-complete-build.md",
]

# Each package, and the build on that page which needs it.
REQUIRED = {
    "autoconf": "IgH ./bootstrap",
    "automake": "IgH ./bootstrap",
    "libtool": "IgH ./bootstrap",
    "libudev-dev": "the serialport crate the Rust build links",
    "pkg-config": "locating libudev",
    "python3-dev": "klippy's chelper",
    "libffi-dev": "klippy's chelper",
    "gcc-arm-none-eabi": "the Manta firmware",
    "rustup": "the pinned Rust toolchain and its ARM target",
}


@pytest.mark.parametrize("page", CB2_PAGES)
@pytest.mark.parametrize("pkg", sorted(REQUIRED))
def test_the_page_names_every_package_its_own_steps_need(page, pkg):
    """In the install command, not merely somewhere on the page. Every one of
    these is also named in the table explaining what it is for, so a
    whole-page search passes after the package is dropped from the line a
    reader actually runs."""
    text = (ROOT / page).read_text(encoding="utf-8")
    commands = "\n".join(re.findall(r"```sh\n(.*?)```", text, re.S))
    installs = "\n".join(
        block
        for block in commands.split("\n\n")
        if "apt install" in block or "rustup.rs" in block
    )
    assert pkg in installs, (
        "%s does not install %s in a command; it is needed for %s"
        % (page, pkg, REQUIRED[pkg])
    )


@pytest.mark.parametrize("page", CB2_PAGES)
def test_the_page_pins_the_toolchain_version_the_repo_pins(page):
    """rust-toolchain.toml pins the channel and the ARM target, so a distro
    rustc is the wrong version with no thumbv7em. The page has to say to use
    rustup, and the version it names has to be the one the repo pins."""
    toolchain = (ROOT / "rust" / "rust-toolchain.toml").read_text(
        encoding="utf-8"
    )
    channel = re.search(r'channel\s*=\s*"([^"]+)"', toolchain).group(1)
    assert "thumbv7em-none-eabi" in toolchain
    text = (ROOT / page).read_text(encoding="utf-8")
    assert channel in text, (
        "%s does not name the pinned Rust channel (%s), so a reader cannot "
        "tell a distro rustc is the wrong one" % (page, channel)
    )
    assert "thumbv7em-none-eabi" in text


@pytest.mark.parametrize("page", CB2_PAGES)
def test_the_page_says_no_gate_builds_the_c_firmware(page):
    """ci.sh rust-mcu-h7 builds the Rust half of the MCU for thumbv7em and
    stops there; no CI image carries an ARM toolchain, so nothing compiles the
    C firmware or links out/klipper.bin. A green gate does not mean the
    firmware builds, and a page that implies otherwise sends someone to the
    bench on a false positive."""
    ci = (ROOT / "scripts" / "ci.sh").read_text(encoding="utf-8")
    job = ci.split("job_rust_mcu_h7()")[1].split("\n}")[0]
    assert "thumbv7em-none-eabi" in job and "klipper.bin" not in job, (
        "rust-mcu-h7 changed shape; re-check whether it now covers the C "
        "firmware before relaxing the pages"
    )
    text = (ROOT / page).read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", text)
    assert (
        "no gate covers" in flat or "does not mean the firmware builds" in flat
    ), "%s does not say the firmware build is uncovered by CI" % page
