"""Feature_Status.md is the first document the README sends people to.

It decides whether someone bothers with this fork at all, so a capability it
understates costs more than one it merely describes badly. Its "Known limits"
section named cartesian and corexy long after markforged shipped, while the
table forty lines above already listed markforged — the document disagreed
with itself.
"""

import pathlib
import re

from klippy import motion_kinematics

STATUS = (
    pathlib.Path(__file__).resolve().parents[1] / "docs" / "Feature_Status.md"
)


def kinematics_limit_entry():
    text = STATUS.read_text(encoding="utf-8")
    match = re.search(r"- \*\*Kinematics:\*\*(.*?)(?=\n- \*\*)", text, re.S)
    assert match, "the Kinematics entry under Known limits has moved or gone"
    return match.group(1)


def kinematics_claim():
    """Just the claim, not the caveats after it.

    Checking the whole entry would pass on an understated claim whenever a
    later sentence happened to mention the missing kinematics — which is
    exactly how the first version of this test failed to catch anything."""
    return re.split(r"[—.]", kinematics_limit_entry(), maxsplit=1)[0]


def test_known_limits_names_every_kinematics_the_code_supports():
    claim = kinematics_claim()
    for kind in motion_kinematics._KIN_TAGS:
        assert kind in claim, (
            f"{kind} is supported but Known limits does not name it; the first "
            f"document a reader is sent to would understate the fork"
        )


def test_known_limits_is_specific_about_markforged_being_untested():
    """Naming markforged without that caveat would read as a shipped, proven
    kinematics. It is neither — no belt has ever moved under it."""
    assert "untested on hardware" in kinematics_limit_entry()
