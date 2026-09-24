"""The two EtherCAT host pages must cover the same ground.

One is exercised on the bench, the other has never been run, and the gap showed:
the CB2 page was missing the udev rule for /dev/EtherCAT0, the systemd unit, the
NetworkManager override that Armbian in particular needs, and its own See also.
Each gap was a first-boot failure on the path nobody has walked.

They are different SoCs, so their content differs. What must not differ is
whether a step exists at all.
"""

import pathlib

import pytest

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs" / "rewrite"
PI5 = DOCS / "ethercat-igh-macb-install.md"
CB2 = DOCS / "ethercat-host-cb2-rk3566.md"

# Each entry is a thing both pages must tell the reader to do, and a token that
# shows they did. Kept as substrings rather than prose so a rewording does not
# fail this, only a removal.
SHARED_STEPS = {
    "udev rule for /dev/EtherCAT0": "99-ethercat.rules",
    "the device node the endpoint opens": "/dev/EtherCAT0",
    "a boot service that hands the NIC over": "Before=klipper.service",
    "NetworkManager told to leave the NIC alone": "unmanaged-devices",
    "the master's device and module settings": "MASTER0_DEVICE",
    "lowercase MAC, which is matched as a string": "lowercase",
    "RT capabilities for the endpoint": "AmbientCapabilities",
    "building the endpoint binary": "ethercat-endpoint-hw",
    "the stub for the drive-off dry run": "ethercat-stub",
    "an isolated core for the DC loop": "isolcpus",
    "where to go next": "## See also",
    "the autotools IgH's ./bootstrap runs": "autoconf automake libtool",
    "the header the serialport crate links": "libudev-dev",
    "the pinned Rust toolchain": "sh.rustup.rs",
    "this fork, not the upstream it is built on": "PDAMUK/serval",
    "the klippy modules built from that checkout": "scripts/build-native.sh",
    "write access to the idle-state QoS the endpoint holds": (
        'KERNEL=="cpu_dma_latency", MODE="0660"'
    ),
}


@pytest.mark.parametrize(
    "what,token", sorted(SHARED_STEPS.items()), ids=lambda v: v[:38]
)
@pytest.mark.parametrize("doc", [PI5, CB2], ids=lambda p: p.stem)
def test_both_host_paths_cover_the_same_step(doc, what, token):
    assert token in doc.read_text(encoding="utf-8"), (
        f"{doc.name} never covers {what}"
    )


def test_both_host_pages_put_the_master_config_under_the_install_prefix():
    """Both pages build the master with `--prefix=/opt/etherlab`, which puts
    autoconf's sysconfdir at `/opt/etherlab/etc`. The init script and the file
    it reads are therefore under that prefix.

    The CB2 page had the config at `/etc/ethercat.conf` and started the master
    with `/etc/init.d/ethercat` — a distro-packaged master's layout, which
    this build does not install — while its own ExecStop already used the
    prefixed path. A MASTER0_DEVICE written to a file nothing reads produces a
    master that loads and finds no link, which is indistinguishable from a
    wrong MAC and is the row its own troubleshooting table sends you to."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    pages = [
        "docs/rewrite/ethercat-igh-macb-install.md",
        "docs/rewrite/ethercat-host-cb2-rk3566.md",
        "docs/rewrite/markforged-cb2-complete-build.md",
    ]
    for rel in pages:
        text = (root / rel).read_text(encoding="utf-8")
        assert "--prefix=/opt/etherlab" in text, (
            "%s no longer sets the prefix" % rel
        )
        # The unprefixed paths belong to a packaged master, so they may only
        # appear where the page is explaining that they do not apply.
        for stray in re.finditer(
            r"(?<!ld\.so\.conf\.d/)\betc/ethercat\.conf\b", text
        ):
            window = text[max(0, stray.start() - 220) : stray.end() + 120]
            assert "distro-packaged" in window, (
                "%s points MASTER0_DEVICE at /etc/ethercat.conf, which a "
                "--prefix=/opt/etherlab master never reads" % rel
            )
        for stray in re.finditer(r"(?<!etherlab/)etc/init\.d/ethercat", text):
            window = text[max(0, stray.start() - 220) : stray.end() + 120]
            assert "distro-packaged" in window, (
                "%s runs /etc/init.d/ethercat, which this build does not "
                "install" % rel
            )


def test_both_host_pages_check_the_module_against_the_running_kernel():
    """A module built against a different kernel tree is refused by modprobe
    with nothing that names the cause. The Pi 5 page checks `modinfo -F
    vermagic` against `uname -r`; the CB2 page only printed the first lines of
    modinfo and never said to compare them.

    The CB2 is the side where this is likelier, not less: the Pi 5 installs a
    distro RT kernel with matching headers, while the CB2 page has you build
    the kernel yourself in Step 1 and then build modules against it."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in [
        "docs/rewrite/ethercat-igh-macb-install.md",
        "docs/rewrite/ethercat-host-cb2-rk3566.md",
        "docs/rewrite/markforged-cb2-complete-build.md",
    ]:
        text = (root / rel).read_text(encoding="utf-8")
        # In a command block, not merely mentioned in prose: a troubleshooting
        # row telling you to check it after it has already failed is not the
        # same as a step that checks it before you go on.
        fences = "\n".join(re.findall(r"```sh\n(.*?)```", text, re.S))
        assert "modinfo -F vermagic" in fences, (
            "%s does not check the module's vermagic as a step, so a module "
            "built against the wrong kernel tree is found by modprobe "
            "refusing it" % rel
        )
        flat = re.sub(r"\s+", " ", text)
        assert re.search(r"wrong kernel tree", flat), (
            "%s checks vermagic without saying what a mismatch means" % rel
        )


def test_no_host_page_offers_a_core_choice_nothing_can_honour():
    """The endpoint pins to CPU 3. `--rt-cpu` exists on the binary, but klippy
    spawns the endpoint and never passes it, and no printer.cfg option reaches
    it — so the core is not a choice.

    The Pi 5 page said "pick any core and pass --rt-cpu to match". Following
    that is worse than being stuck on CPU 3: sched_setaffinity(3) succeeds for
    any online CPU, so the loop pins to a core that is not isolated while
    chrt -p and Cpus_allowed_list both read exactly as the guide says they
    should. Every documented check passes and the machine drops frames on the
    first cold boot under load."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]

    # The premise: nothing in the host or the bridge emits --rt-cpu.
    reachable = []
    for sub in ["klippy", "rust/motion-engine"]:
        for path in (
            (root / sub).rglob("*.p[y]")
            if sub == "klippy"
            else (root / sub).rglob("*.rs")
        ):
            if "--rt-cpu" in path.read_text(encoding="utf-8", errors="ignore"):
                reachable.append(str(path.relative_to(root)))
    assert not reachable, (
        "--rt-cpu is now reachable from %s; the pages saying the core is "
        "fixed need revisiting" % reachable
    )

    # The bench checklist names the flags too, and is the page that explains
    # the real-time rules in depth, so it carries the same burden.
    for rel in [
        "docs/rewrite/ethercat-bench-bringup.md",
        "docs/rewrite/ethercat-igh-macb-install.md",
        "docs/rewrite/ethercat-host-cb2-rk3566.md",
        "docs/rewrite/markforged-cb2-complete-build.md",
    ]:
        text = (root / rel).read_text(encoding="utf-8")
        flat = re.sub(r"\s+", " ", text)
        assert "must be CPU 3" in flat, (
            "%s names --rt-cpu without saying it cannot be reached" % rel
        )
        assert not re.search(r"pick any core", flat), (
            "%s offers a core choice that nothing can honour" % rel
        )
    for rel in [
        "docs/rewrite/ethercat-igh-macb-install.md",
        "docs/rewrite/ethercat-host-cb2-rk3566.md",
        "docs/rewrite/markforged-cb2-complete-build.md",
    ]:
        text = (root / rel).read_text(encoding="utf-8")
        flat = re.sub(r"\s+", " ", text)
        assert "isolcpus=domain,managed_irq,3" in flat, (
            "%s no longer isolates CPU 3, which is the only core the endpoint "
            "will pin to" % rel
        )


def test_every_clone_names_a_real_source():
    """The Pi 5 page cloned the IgH master from `<fork-url> -b <fork-branch>`,
    placeholders the page's own preamble presents as host values to fill in.
    They were never host values: nothing the reader has supplies a fork URL, so
    the recommended first-build path stopped at its second command. Upstream
    `stable-1.6` has shipped `ec_macb` since 1.6.10, which is what the page
    now clones."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in [
        "docs/rewrite/ethercat-igh-macb-install.md",
        "docs/rewrite/ethercat-host-cb2-rk3566.md",
        "docs/rewrite/markforged-cb2-complete-build.md",
    ]:
        text = (root / rel).read_text(encoding="utf-8")
        for clone in re.findall(r"^git clone .*$", text, re.M):
            assert "<" not in clone, "%s: %s" % (rel, clone)
    pi5 = (root / "docs/rewrite/ethercat-igh-macb-install.md").read_text(
        encoding="utf-8"
    )
    assert (
        "git clone -b stable-1.6 https://gitlab.com/etherlab.org/ethercat.git"
        in pi5
    )
    assert "1.6.10" in pi5, "the page no longer says which release has ec_macb"
    assert "PORTING-NOTES.md" not in pi5, (
        "upstream's devices/macb/ carries no PORTING-NOTES.md; that was the fork's"
    )


def test_no_page_denies_the_cm4_its_native_driver():
    """Both build guides listed `genet` among IgH's native drivers and, a
    sentence later, said a CM4's GENET MAC had none. IgH's `devices/genet/` is
    the BCM2711 GENET driver, for kernels 5.10 to 6.12 — the Pi 4 recipe the
    Pi 5 page says `ec_macb` was ported from."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in [
        "docs/rewrite/estun-pronet-markforged-setup.md",
        "docs/rewrite/markforged-cb2-complete-build.md",
    ]:
        flat = re.sub(r"\s+", " ", (root / rel).read_text(encoding="utf-8"))
        assert "GENET MAC has no native IgH driver" not in flat, rel
        assert "IgH's `genet` driver is for" in flat, rel


def test_a_step_cited_on_another_page_is_a_link():
    """The setup guide sent the reader to "Step 8 of the host page" for why
    the endpoint cannot be cross-compiled. The CB2 page's steps were reordered
    kernel-first and that explanation moved to Step 11, while Step 8 became
    the NIC hand-over — and plain prose has nothing to go stale against. As a
    link, a renumber breaks the anchor, which the anchor check catches."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    records_what_was_broken = "repo-audit-status.md"
    for path in sorted((root / "docs" / "rewrite").glob("*.md")):
        if path.name == records_what_was_broken:
            continue
        text = path.read_text(encoding="utf-8")
        flat = re.sub(r"\s+", " ", text)
        bare = re.findall(r"(?<!\[)\b[Ss]tep \d+ of the [\w -]*?page\b", flat)
        assert not bare, "%s cites %s as prose" % (path.name, bare)
