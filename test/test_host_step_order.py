"""A host page has to be followable in the order it is written.

Two ways it stopped being, both found by walking it as a reader rather than
reading it as a reference:

The kernel step builds an Armbian image on another machine and flashes it,
replacing the whole OS. Putting SSH on Wi-Fi and installing packages ahead of
that is work done twice, and the pages had both before it.

And everything from the IgH build onward runs inside a checkout — `generate.py`
out of `tools/`, the endpoint out of `rust/`, a systemd drop-in for
`klipper.service` — which no step created. A reader following either page from
a flashed image is stopped at the IgH build with no repository and no klippy.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLLATED = ROOT / "docs" / "rewrite" / "markforged-cb2-complete-build.md"
HOST = ROOT / "docs" / "rewrite" / "ethercat-host-cb2-rk3566.md"


def steps(path, pattern):
    text = path.read_text(encoding="utf-8")
    return [
        (int(m.group(1)), m.group(0), m.start())
        for m in re.finditer(pattern, text, re.M)
    ]


CASES = [
    (COLLATED, r"^## B(\d+) — (.+)$", "B"),
    (HOST, r"^## Step (\d+) — (.+)$", "Step "),
]


@pytest.mark.parametrize(
    "path,pattern,label", CASES, ids=lambda v: getattr(v, "stem", v)
)
def test_the_steps_are_numbered_in_the_order_they_appear(path, pattern, label):
    found = [n for n, _h, _i in steps(path, pattern)]
    assert found == sorted(found), "%s: steps out of order: %s" % (
        path.name,
        found,
    )
    assert found == list(range(1, len(found) + 1)), (
        "%s: numbering has a gap or a repeat: %s" % (path.name, found)
    )


@pytest.mark.parametrize(
    "path,pattern,label", CASES, ids=lambda v: getattr(v, "stem", v)
)
def test_the_kernel_step_comes_before_anything_it_would_erase(
    path, pattern, label
):
    """Flashing the image wipes the board, so the Wi-Fi move and the package
    install have to follow it."""
    found = steps(path, pattern)

    def index_of(word):
        hits = [n for n, head, _i in found if word in head.lower()]
        assert hits, "%s has no step mentioning %r" % (path.name, word)
        return hits[0]

    kernel = index_of("preempt_rt")
    assert kernel == 1, "%s: the kernel step is %d, not first" % (
        path.name,
        kernel,
    )
    for later in ("eth0", "install"):
        assert index_of(later) > kernel, (
            "%s: %r is numbered before the step that reflashes the board"
            % (path.name, later)
        )


@pytest.mark.parametrize(
    "path,pattern,label", CASES, ids=lambda v: getattr(v, "stem", v)
)
def test_the_repository_exists_before_a_step_builds_inside_it(
    path, pattern, label
):
    """`generate.py`, the Rust build and the klipper.service drop-in all
    assume a checkout and an install. One step has to produce them, and it has
    to come first."""
    found = steps(path, pattern)
    text = path.read_text(encoding="utf-8")
    repo = [n for n, head, _i in found if "repository" in head.lower()]
    assert repo, "%s never gets the repository onto the host" % path.name
    igh = [n for n, head, _i in found if "igh master" in head.lower()]
    assert igh and repo[0] < igh[0], (
        "%s builds IgH from the checkout before creating it" % path.name
    )
    assert "PDAMUK/serval" in text, (
        "%s does not name this fork; base Serval rejects the Stage K config"
        % path.name
    )
    assert "no markforged" in text, (
        "%s does not say why base Serval will not do" % path.name
    )


@pytest.mark.parametrize(
    "path,pattern,label", CASES, ids=lambda v: getattr(v, "stem", v)
)
def test_no_step_reference_points_at_a_step_that_does_not_exist(
    path, pattern, label
):
    text = path.read_text(encoding="utf-8")
    highest = max(n for n, _h, _i in steps(path, pattern))
    # `label` is "B" or "Step ", so the separator is optional — an earlier
    # version stripped it and matched only "Step18", which never occurs and
    # made the check silently vacuous.
    cited = {
        int(m)
        for m in re.findall(r"(?:^|\s)%s\s?(\d+)\b" % label.strip(), text)
    }
    beyond = sorted(n for n in cited if n > highest)
    assert not beyond, "%s cites steps that do not exist: %s" % (
        path.name,
        beyond,
    )
