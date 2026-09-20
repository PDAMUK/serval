"""The hw endpoint must say what is missing, not leave cc-rs to.

Building `ethercat-endpoint-hw` without the IgH master installed used to fail
as `error occurred in cc-rs: command did not execute successfully`, with the
real cause — `fatal error: ecrt.h: No such file or directory` — demoted to a
cargo warning above it. That is the first build a person runs on the host, and
the headline told them nothing about what to install.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD_RS = ROOT / "rust" / "ethercat-rt" / "build.rs"


def test_the_igh_header_is_checked_before_cc_is_invoked():
    """A guard after `cc::Build::new()` is no guard: cc fails first and the
    panic never runs."""
    text = BUILD_RS.read_text(encoding="utf-8")
    guard = text.index("ecrt_h.is_file()")
    compile_call = text.index("cc::Build::new()")
    assert guard < compile_call, (
        "the ecrt.h check runs after cc::Build, so cc still owns the error"
    )


def test_the_failure_names_the_thing_to_install_and_the_way_round_it():
    """Someone hitting this is at a terminal on the host with the machine in
    pieces. The message has to name the file, the document that installs it,
    the escape hatch for a different prefix, and the build that needs no
    master at all."""
    text = BUILD_RS.read_text(encoding="utf-8")
    panic = text[
        text.index("ecrt_h.is_file()") : text.index("cc::Build::new()")
    ]
    flat = re.sub(r"\s+", " ", panic)
    assert "IGH_DIR" in flat, "the message does not offer the prefix override"
    assert "ethercat-host-cb2-rk3566.md" in flat, (
        "the message does not name the document that installs the master"
    )
    assert "ethercat-igh-macb-install.md" in flat, (
        "the message names only one host path"
    )
    assert "ethercat-stub" in flat, (
        "the message does not say the stub endpoint needs no master, which is "
        "the build that works on a machine without one"
    )


def test_the_documents_name_the_prefix_override():
    """IGH_DIR and IGH_LIB_DIR are read by build.rs and were documented
    nowhere, so a master installed anywhere but /opt/etherlab had no
    documented route."""
    for rel in [
        "docs/rewrite/ethercat-host-cb2-rk3566.md",
        "docs/rewrite/markforged-cb2-complete-build.md",
        "docs/rewrite/ethercat-igh-macb-install.md",
    ]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "IGH_DIR" in text, (
            "%s does not say how to build against a master installed outside "
            "/opt/etherlab" % rel
        )
