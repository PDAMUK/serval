"""Every source location the motion config reference cites must still exist.

The section used to cite line ranges. Two of its seven were wrong by the time
anyone looked: `[kinematics]` parsing had moved into a gap between two cited
ranges, and the gear-ratio parser had drifted past the end of its range. A
range rots on any edit above it and says nothing when it does, so the section
now cites symbols and this checks them.
"""

import pathlib
import re

import pytest

REFERENCE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "docs"
    / "Config_Reference_Motion.md"
)
REPO_ROOT = REFERENCE.parents[1]

ROW = re.compile(
    r"^\| [^|]+ \| `([^`]+)`(?: in `([^`]+)`)?(?:, (same file))? \|$"
)


def cited_symbols():
    """(symbol, path) pairs from the Source locations table, in order.

    "same file" rows inherit the path from the row above, which is how the
    table avoids repeating one long path five times.
    """
    section = REFERENCE.read_text(encoding="utf-8").split(
        "## Source locations"
    )[1]
    pairs = []
    last_path = None
    for line in section.splitlines():
        match = ROW.match(line.strip())
        if not match:
            continue
        symbol, path, same_file = match.groups()
        if path:
            last_path = path
        elif not same_file:
            continue
        assert last_path, f"row cites 'same file' with no earlier path: {line}"
        pairs.append((symbol, last_path))
    return pairs


def test_the_table_was_parsed_at_all():
    """A table that stops matching would make every check below vacuous."""
    assert len(cited_symbols()) >= 12


@pytest.mark.parametrize(
    "symbol,path", cited_symbols(), ids=lambda v: v.replace("/", "_")
)
def test_every_cited_symbol_exists_where_it_says(symbol, path):
    target = REPO_ROOT / path
    assert target.is_file(), f"{path} does not exist"
    assert symbol in target.read_text(encoding="utf-8"), (
        f"{path} no longer defines {symbol}"
    )


LINE_CITATION = re.compile(r"[\w./-]+\.(?:py|rs|c|h):\d+")


def test_no_line_number_citations_remain():
    """Line ranges are the defect this file exists for.

    Every one of them in this document had gone stale or was heading there —
    including one that this session's own edits to motion_kinematics.py shifted
    out from under the text. A symbol survives an edit above it; a line number
    does not, and says nothing when it stops being true.
    """
    found = LINE_CITATION.findall(REFERENCE.read_text(encoding="utf-8"))
    assert not found, f"cite these by symbol instead: {found}"
