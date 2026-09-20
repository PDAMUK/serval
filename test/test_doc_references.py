"""Every reference in this fork's own documents must still point at something.

Documents rot in a way code does not: a renamed crate, a deleted tool or a
moved heading leaves prose that still reads correctly and sends someone to a
path that is not there. Three of those were found by hand in one pass — a
crate that moved (`motion-engine` to `motion-services`), a tool that no longer
exists (`tools/sim_klippy`), and two links in `.claude/CLAUDE.md` written
relative to the repository root rather than to the file that holds them.

These checks cover only the twelve markdown files this fork wrote or changed.
The other ninety-three are byte-identical to upstream, and a broken reference
in one of those is upstream's to fix.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The fork's own markdown. A new one has to be added here deliberately, which
# is the point: it forces the question of whether it should be checked.
OURS = [
    ".claude/CLAUDE.md",
    "README.md",
    "docs/Config_Reference.md",
    "docs/Config_Reference_Motion.md",
    "docs/Feature_Status.md",
    "docs/rewrite/estun-pronet-markforged-setup.md",
    "docs/rewrite/ethercat-bench-bringup.md",
    "docs/rewrite/ethercat-host-cb2-rk3566.md",
    "docs/rewrite/ethercat-igh-macb-install.md",
    "docs/rewrite/markforged-cb2-complete-build.md",
    "docs/rewrite/repo-audit-status.md",
    "tools/ethercat-dwmac-rk/README.md",
]

# Links mkdocs rewrites to upstream GitHub, where the file does exist. The
# hook in docs/_kalico/mkdocs_hooks.py turns a leading "../" into repo_url,
# so these are not user-facing 404s. Inherited; low value to churn.
REWRITTEN_UPSTREAM = re.compile(r"^\.\./config/")

# Paths a document names precisely to say they are NOT here: the four
# upstream sections this fork does not ship, and the build artifacts that
# exist only after a build.
ABSENT_ON_PURPOSE = {
    "klippy/extras/load_cell_probe.py",
    "klippy/extras/manual_stepper.py",
    "klippy/extras/probe_eddy_current.py",
    "klippy/extras/trad_rack.py",
    "rust/target/release/ethercat-rt",
    "rust/target/release/ethercat-rt-stub",
}


def slug(heading):
    """python-markdown's slugify, which is what `ci.sh docs` enforces."""
    text = re.sub(r"[`*]", "", heading)
    text = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.U)
    return re.sub(r"[-\s]+", "-", text.strip())


def anchors_of(path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    found = {slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.M)}
    found |= set(re.findall(r'<a\s+(?:id|name)="([^"]+)"', text))
    return found


@pytest.fixture(scope="module")
def make_targets():
    text = (ROOT / "Makefile.rust").read_text(encoding="utf-8")
    return set(re.findall(r"^([a-z][\w-]*):", text, re.M))


@pytest.fixture(scope="module")
def ci_jobs():
    text = (ROOT / "scripts" / "ci.sh").read_text(encoding="utf-8")
    jobs = {
        j.replace("_", "-")
        for j in re.findall(r"^job_([a-z0-9_]+)\(", text, re.M)
    }
    return jobs | set(re.findall(r'"([a-z0-9-]+)"\)', text)) | {"quick", "all"}


@pytest.mark.parametrize("rel", OURS)
def test_every_relative_link_resolves(rel):
    """A link written relative to the repository root rather than to the file
    that holds it looks right in the source and 404s when clicked."""
    doc = ROOT / rel
    text = doc.read_text(encoding="utf-8")
    broken = []
    for label, target in re.findall(
        r"\[([^\]]*)\]\(((?!https?:|#|mailto:)[^)\s]+)\)", text
    ):
        path = target.split("#")[0]
        if not path or REWRITTEN_UPSTREAM.match(path):
            continue
        if not (doc.parent / path).resolve().exists():
            broken.append("[%s](%s)" % (label[:40], target))
    assert not broken, "%s: %s" % (rel, broken)


@pytest.mark.parametrize("rel", OURS)
def test_every_anchor_resolves(rel):
    """Cross-file anchors rot silently: the file still exists, the heading it
    pointed at does not."""
    doc = ROOT / rel
    text = doc.read_text(encoding="utf-8")
    dangling = []
    for label, target in re.findall(
        r"\[([^\]]*)\]\(((?!https?:|mailto:)[^)\s]*#[\w-]+)\)", text
    ):
        f, _, anchor = target.partition("#")
        found = anchors_of((doc if not f else doc.parent / f).resolve())
        if found is None:
            dangling.append("unreadable target: %s" % target)
        elif anchor not in found:
            dangling.append("[%s](%s)" % (label[:34], target))
    assert not dangling, "%s: %s" % (rel, dangling)


# The audit log's job is to record what was wrong, so a path it names may be
# exactly the path that did not exist — findings 40 and 41 are two of them.
# Holding it to this check would mean it could never describe a dead reference.
RECORDS_WHAT_WAS_BROKEN = {"docs/rewrite/repo-audit-status.md"}


@pytest.mark.parametrize("rel", OURS)
def test_every_repo_path_it_names_exists(rel):
    """`rust/motion-engine/src/logging/mod.rs` read perfectly well for as long
    as it took someone to go looking for it. The module had moved crates."""
    if rel in RECORDS_WHAT_WAS_BROKEN:
        pytest.skip("%s records dead references on purpose" % rel)
    doc = ROOT / rel
    text = doc.read_text(encoding="utf-8")
    missing = []
    for path in sorted(
        set(
            re.findall(
                r"`((?:rust|klippy|scripts|tools|test|src)/[\w./-]+?)`", text
            )
        )
    ):
        clean = path.rstrip("/.")
        if clean in ABSENT_ON_PURPOSE:
            continue
        if not (ROOT / clean).exists():
            missing.append(clean)
    assert not missing, "%s names paths that do not exist: %s" % (rel, missing)


@pytest.mark.parametrize("rel", OURS)
def test_every_make_target_it_names_exists(rel, make_targets):
    text = (ROOT / rel).read_text(encoding="utf-8")
    named = set(re.findall(r"make -f Makefile\.rust ([\w-]+)", text))
    assert not (named - make_targets), "%s: %s" % (
        rel,
        sorted(named - make_targets),
    )


@pytest.mark.parametrize("rel", OURS)
def test_every_ci_job_it_names_exists(rel, ci_jobs):
    text = (ROOT / rel).read_text(encoding="utf-8")
    named = set(re.findall(r"ci\.sh (?:-v )?([a-z0-9][a-z0-9-]*)", text))
    assert not (named - ci_jobs), "%s: %s" % (rel, sorted(named - ci_jobs))


def test_the_checked_list_covers_every_rewrite_document():
    """docs/rewrite/ is where this fork's own documents live. One added there
    and not listed above would be the only unchecked document in the set."""
    on_disk = {
        "docs/rewrite/%s" % p.name
        for p in (ROOT / "docs" / "rewrite").glob("*.md")
    }
    listed = {r for r in OURS if r.startswith("docs/rewrite/")}
    # Documents inherited unchanged from upstream are checked by upstream.
    inherited = on_disk - listed
    assert listed <= on_disk, "listed but absent: %s" % sorted(listed - on_disk)
    assert len(inherited) == 17, (
        "docs/rewrite/ gained or lost a document (%d inherited, expected 17) — "
        "if it is this fork's, add it to OURS" % len(inherited)
    )
