"""Every section the config reference documents must either load or say it cannot.

A documented section whose module is absent fails startup with
`Module '<name>' not found`, and nothing in the document warns you. Four of the
ninety-eight were in that state — upstream features this fork does not ship.
They are still documented, because `klippy/plugins/` lets a user supply the
module themselves, but each now says so.

The check runs both ways: a section that stops loading must gain the notice,
and one that starts loading must lose it.
"""

import pathlib
import pkgutil
import re

import pytest

REFERENCE = (
    pathlib.Path(__file__).resolve().parents[1] / "docs" / "Config_Reference.md"
)
KLIPPY = pathlib.Path(__file__).resolve().parents[1] / "klippy"

NOT_SHIPPED = "**Not shipped in this fork.**"

# Handled outside the extras loader: parse-time, by a parent module, or by a
# numbered-section scan. Each was confirmed individually.
HANDLED_ELSEWHERE = {
    "printer",
    "mcu",
    "kinematics",
    "motor",
    "axis",
    "post_processor",
    "extruder",
    "heater_bed",
    "fan",
    "board_pins",
    "include",
    "duplicate_pin_override",
    "constants",
    "display_template",
    "display_glyph",
    "extruder1",
}


def loadable_modules():
    names = set()
    for sub in ("extras", "plugins"):
        path = KLIPPY / sub
        if path.is_dir():
            names |= {m.name for m in pkgutil.iter_modules([str(path)])}
    return names


def documented_sections():
    """Section name -> whether its heading carries the not-shipped notice."""
    text = REFERENCE.read_text(encoding="utf-8")
    names = set()
    for block in re.findall(r"```\n(.*?)```", text, re.S):
        for line in block.splitlines():
            m = re.match(r"^\[([a-z_0-9]+)(\s+\S+)?\]\s*$", line.strip())
            if m:
                names.add(m.group(1))
    marked = set()
    for m in re.finditer(r"^### \[([a-z_0-9]+)\]\n\n(.*)$", text, re.M):
        if m.group(2).startswith(NOT_SHIPPED):
            marked.add(m.group(1))
    return names, marked


def test_the_document_was_parsed_at_all():
    names, _ = documented_sections()
    assert len(names) >= 90


@pytest.mark.parametrize("section", sorted(documented_sections()[0]))
def test_section_loads_or_says_it_does_not(section):
    names, marked = documented_sections()
    if section in loadable_modules() or section in HANDLED_ELSEWHERE:
        assert section not in marked, (
            f"[{section}] loads now — drop its not-shipped notice"
        )
    else:
        assert section in marked, (
            f"[{section}] has no module and no notice; a config using it fails "
            f"startup with \"Module '{section}' not found\""
        )
