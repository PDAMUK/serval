"""The interactive page and the Python model must not drift apart.

`tools/motion_budget.html` reimplements `tools/motion_budget.py` in JavaScript
so the numbers can be twiddled in a browser. Two implementations of the same
physics is exactly the arrangement that rots quietly: the tested one stays
right and the one people actually look at stops matching it.

Most of these pin the constants and the shape of the algebra by reading the
page as text. The last one goes further where a JavaScript engine is around:
it runs the page's own physics prelude and compares its answers with the
module's, which is the only check that catches an edit to the algebra rather
than to a number.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = (ROOT / "tools" / "motion_budget.html").read_text(encoding="utf-8")

sys.path.insert(0, str(ROOT))
from klippy import configfile  # noqa: E402
from tools import motion_budget as mb  # noqa: E402

ConfigDocument = configfile._config_doc.ConfigDocument


def js_number(name):
    match = re.search(r"var %s\s*=\s*([0-9.e-]+)\s*[;,]" % name, PAGE)
    assert match, "the page no longer defines %s" % name
    return float(match.group(1))


def js_object(name):
    match = re.search(r"var %s\s*=\s*\{(.*?)\n\};" % name, PAGE, re.S)
    assert match, "the page no longer defines %s" % name
    return match.group(1)


def page_belts():
    entries = re.findall(
        r'"([^"]+)":\s*\{pitch:\s*([0-9.]+),\s*tensionPerInch:\s*([0-9.]+),'
        r"\s*estimated:\s*(true|false)\}",
        js_object("BELTS"),
    )
    return {
        name: {
            "pitch_mm": float(pitch),
            "tension_n_per_inch": float(tension),
            "estimated": estimated == "true",
        }
        for name, pitch, tension, estimated in entries
    }


def page_materials():
    entries = re.findall(
        r'(\w+):\s*\{label:\s*"([^"]*)",\s*min:\s*(-?[0-9.]+),'
        r"\s*max:\s*(-?[0-9.]+)\}",
        js_object("MATERIALS"),
    )
    return {
        name: {"label": label, "min_c": float(low), "max_c": float(high)}
        for name, label, low, high in entries
    }


@pytest.mark.parametrize(
    "js_name,py_value",
    [
        ("MARKFORGED_Y_COUPLING", mb.MARKFORGED_Y_COUPLING),
        ("RATED_TORQUE_NM", mb.Motor().rated_torque_nm),
        ("ROTOR_INERTIA", mb.Motor().rotor_inertia_kgm2),
        ("MM_PER_INCH", mb.MM_PER_INCH),
    ],
)
def test_the_page_uses_the_same_constants_as_the_model(js_name, py_value):
    assert js_number(js_name) == pytest.approx(py_value)


def test_the_page_carries_the_same_belt_table():
    """Pitch sets `rotation_distance`, tension sets the belt ceiling, and the
    estimated flag is what keeps GT1.5 from reading like a datasheet."""
    assert page_belts() == mb.BELTS


def test_the_page_carries_the_same_belt_compounds():
    page = page_materials()
    assert set(page) == set(mb.BELT_MATERIALS)
    for name, spec in mb.BELT_MATERIALS.items():
        assert page[name]["label"] == spec["label"], name
        assert (page[name]["min_c"], page[name]["max_c"]) == (
            spec["min_c"],
            spec["max_c"],
        ), name


def test_the_page_offers_the_widths_the_model_knows():
    widths = [float(w) for w in re.findall(r'data-width="([0-9.]+)"', PAGE)]
    assert widths == list(mb.BELT_WIDTHS_MM)


def test_the_page_offers_every_belt_profile_and_kinematic():
    assert re.findall(r'data-profile="([^"]+)"', PAGE) == list(mb.BELTS)
    assert re.findall(r'data-kin="([^"]+)"', PAGE) == list(mb.FRAMES)
    assert re.findall(r'data-material="([^"]+)"', PAGE) == list(
        mb.BELT_MATERIALS
    )


def test_the_pulley_slider_and_the_chart_cover_the_same_teeth():
    """A slider that reaches further than the chart plots leaves the reader
    dragging past the end of the curve they are reading."""
    slider = re.search(r'id="teeth"[^>]*min="(\d+)"[^>]*max="(\d+)"', PAGE)
    assert slider, "the page no longer has a pulley-teeth slider"
    chart = re.search(r"for \(var n=(\d+);n<=(\d+);n\+=\d+\)", PAGE)
    assert chart, "the page no longer sweeps teeth for the chart"
    assert (chart.group(1), chart.group(2)) == (
        slider.group(1),
        slider.group(2),
    )
    assert int(slider.group(2)) == 140


def test_the_chart_axis_labels_end_where_the_sweep_ends():
    labels = re.search(r"\[([0-9,]+)\]\.forEach", PAGE)
    assert labels, "the page no longer labels the teeth axis"
    ticks = [int(t) for t in labels.group(1).split(",")]
    chart = re.search(r"for \(var n=(\d+);n<=(\d+);n\+=\d+\)", PAGE)
    assert (ticks[0], ticks[-1]) == (int(chart.group(1)), int(chart.group(2)))


def test_the_page_carries_the_same_frames():
    for name, frame in mb.FRAMES.items():
        match = re.search(
            r"%s:\s*\[\[([^\]]*)\],\s*\[([^\]]*)\]\]" % name, PAGE
        )
        assert match, "the page has no %s frame" % name
        rows = []
        for group in (match.group(1), match.group(2)):
            rows.append(
                [
                    float(v.replace("-MARKFORGED_Y_COUPLING", "-1.0"))
                    for v in group.split(",")
                ]
            )
        assert rows == [list(r) for r in frame], name


def test_the_page_applies_the_rotor_term_like_the_model():
    """`belt*m.r + ROTOR_INERTIA*slotAcc[slot]/m.r` is the SI form of
    dynamics.rs's lift plus the rotor the fitted profile folds into its mass.
    Losing the second half silently overstates every acceleration."""
    assert "ROTOR_INERTIA*slotAcc[slot]/m.r" in PAGE.replace(" ", "")
    assert "belt*m.r" in PAGE.replace(" ", "")


def test_the_page_separates_the_peak_from_the_continuous_ceiling():
    """The belt's allowable working tension is a life rating, not a wall, so
    it bounds `continuous` and never `peak`. A page that fed it back into the
    peak would report 8,844 mm/s² on Y where the drive gives 67,284."""
    flat = PAGE.replace(" ", "")
    assert "tension=belt.tensionPerInch*s.width/MM_PER_INCH" in flat
    assert "beltTorque=tension*r" in flat
    assert "peak:motorTorque" in flat
    assert "continuous:Math.min(RATED_TORQUE_NM,beltTorque)" in flat
    assert 'contLimiter:beltTorque<RATED_TORQUE_NM?"belt":"motor"' in flat
    assert 'ceiling==="continuous"?m.continuous:m.peak' in flat


def test_the_page_quotes_the_catalog_on_intermittent_peaks():
    """The sentence the whole distinction rests on. Without it the page is
    asserting that a belt may be worked past its rating, on its own say-so."""
    flat = re.sub(r"\s+", " ", PAGE)
    assert "intermittent peak torques can often be carried" in flat
    assert "tooth ratcheting" in flat
    assert "installation tension and teeth in mesh" in flat


def test_the_page_does_not_claim_a_peak_it_cannot_source():
    """No primary source here gives the force at which a belt jumps teeth, so
    the page says the peak assumes the belt does not, rather than implying a
    wall it has not established."""
    flat = re.sub(r"\s+", " ", PAGE)
    assert "No source here puts a number on it" in flat
    assert "assumes a properly tensioned belt that does not jump" in flat


def test_the_page_opens_from_disk_without_reaching_out():
    """It is opened from a checkout on a workshop machine, which may have no
    route off itself, and nothing this repository produces phones anywhere.
    A webfont link costs a blocked request and a reflow for a face that every
    `font-family` here already falls back from."""
    for attr, value in re.findall(r'\b(href|src)="([^"]*)"', PAGE):
        assert "//" not in value, "%s=%s leaves the machine" % (attr, value)
    assert "@import" not in PAGE
    assert "fetch(" not in PAGE and "XMLHttpRequest" not in PAGE


def test_the_page_says_what_it_is_not():
    """The number is a torque ceiling. A reader who takes it for a print
    acceleration will set max_accel an order of magnitude too high."""
    flat = re.sub(r"\s+", " ", PAGE)
    assert "torque ceiling, not a print acceleration" in flat
    assert "belt stretch" in flat and "resonance" in flat
    assert "carry</em>, not how stiff it is" in flat


def test_the_page_flags_the_extrapolated_tension():
    """GT1.5 has no Gates rating. The page must say so where the number is
    used, not only in a source comment nobody opens."""
    flat = re.sub(r"\s+", " ", PAGE)
    assert mb.BELTS["GT1.5"]["estimated"]
    assert "no published Gates tension" in flat
    assert "linear extrapolation" in flat


def test_the_page_names_its_sources():
    for path in (
        "rust/motion-core/src/kinematics.rs",
        "rust/ethercat-rt/src/dynamics.rs",
        "klippy/motion_setup.py",
        "tools/motion_budget.py",
    ):
        assert path in PAGE, "the page does not credit %s" % path


def test_the_torque_slider_stops_where_the_drive_does_not_the_config_field():
    """`max_torque` validates to 400 — the CiA 402 `6072h` ceiling — but
    ProNet clamps to `Pn401`/`Pn402`, which run 0-300 % of rated. A slider
    that reached 400 would plot torque the drive will never deliver; one that
    stopped at 100 would hide the range the drive actually has."""
    slider = re.search(r'id="torque"[^>]*min="(\d+)"[^>]*max="(\d+)"', PAGE)
    assert slider, "the page no longer has a torque slider"
    assert int(slider.group(2)) == 300


def test_the_page_flags_the_drive_limits_the_guide_establishes():
    flat = re.sub(r"\s+", " ", PAGE)
    assert "Pn401/Pn402 stop at 300" in flat
    assert "A.13" in flat


PHYSICS_START = "var MARKFORGED_Y_COUPLING"
PHYSICS_END = "var state = {"

CASES = [
    {
        "teeth": 20,
        "gantry": 1.6,
        "carriage": 0.6,
        "torque": 100,
        "rpm": 5000,
        "kin": "markforged",
        "profile": "GT2",
        "width": 6,
        "material": "standard",
    },
    {
        "teeth": 140,
        "gantry": 1.6,
        "carriage": 0.6,
        "torque": 300,
        "rpm": 3000,
        "kin": "markforged",
        "profile": "GT3",
        "width": 12,
        "material": "epdm",
    },
    {
        "teeth": 16,
        "gantry": 4.0,
        "carriage": 1.2,
        "torque": 100,
        "rpm": 5000,
        "kin": "corexy",
        "profile": "GT1.5",
        "width": 9,
        "material": "standard",
    },
    {
        "teeth": 60,
        "gantry": 0.9,
        "carriage": 0.3,
        "torque": 150,
        "rpm": 4000,
        "kin": "cartesian",
        "profile": "GT3",
        "width": 6,
        "material": "epdm",
    },
]


def page_physics_source():
    start = PAGE.find(PHYSICS_START)
    end = PAGE.find(PHYSICS_END)
    assert start >= 0 and end > start, "the page's physics prelude has moved"
    return PAGE[start:end]


def machine_for(case):
    motor = mb.Motor(
        torque_limit_pct=case["torque"],
        max_rpm=case["rpm"],
        pulley_teeth=case["teeth"],
    )
    belt = mb.Belt(
        profile=case["profile"],
        width_mm=case["width"],
        material=case["material"],
    )
    return mb.Machine(
        kinematics=case["kin"],
        motor=motor,
        belt=belt,
        gantry_mass_kg=case["gantry"],
        carriage_mass_kg=case["carriage"],
    )


def test_the_torque_caution_is_not_gated_on_the_motor_being_the_limit():
    """The dangerous case is the *belt* being the limit: the drive then pulls
    more than the belt carries and no number on the page moves, so a reader
    who raises the limit sees nothing happen and concludes it was harmless.
    Gating the caution on `limiter === "motor"` silenced it in exactly that
    case, which is how it was found."""
    flat = re.sub(r"\s+", " ", PAGE)
    assert "if (state.torque > 100)" in flat
    assert 'state.torque > 150 && m.limiter === "motor"' not in flat
    assert "burst torque, not continuous" in flat
    assert "8.4 A against 2.8 A continuous" in flat
    assert "ratcheting is the failure this invites" in flat


@pytest.mark.skipif(
    shutil.which("node") is None, reason="no JavaScript engine to run the page"
)
def test_the_config_the_page_hands_over_is_a_config_klippy_can_read():
    """`fmt` is `toLocaleString`, so the block printed `max_accel: 2,211`,
    which klippy's reader hands back with the comma still in it — and in a
    comma-decimal locale it prints `2.211`, which reads as valid and is a
    thousand times too small. Config values go through `cfgnum`, which
    localises nothing; the monkeypatch below is what proves it.

    Parsed with the reader klippy actually uses, so the trailing `#` comments
    are held to the same rule the machine will hold them to."""
    driver = (
        page_physics_source()
        + "\nNumber.prototype.toLocaleString = function(){"
        "  throw new Error('a config value was formatted for a reader'); };\n"
        "var out = " + json.dumps(CASES) + ".map(function(s){\n"
        "  var m = machine(s);\n"
        "  return cfgText(s, m, maxVel(m,[1,0]), maxVel(m,[0,1]),\n"
        "                 maxAccel(m,[1,0],'continuous'),\n"
        "                 maxAccel(m,[0,1],'continuous'));\n"
        "});\n"
        "console.log(JSON.stringify(out));\n"
    )
    result = subprocess.run(
        ["node", "-e", driver], capture_output=True, text=True, check=True
    )
    for case, text in zip(CASES, json.loads(result.stdout)):
        doc = ConfigDocument.parse(text, "motion_budget.html")
        machine = machine_for(case)
        values = {
            option: doc.get(section, option)
            for section, option in (
                ("motor motor_x", "rotation_distance"),
                ("motor motor_x", "max_torque"),
                ("printer", "max_velocity"),
                ("printer", "max_accel"),
            )
        }
        for option, raw in values.items():
            assert re.fullmatch(r"[0-9]+", raw), "%s: %r" % (option, raw)
        assert float(values["rotation_distance"]) == pytest.approx(
            machine.rotation_distance_mm
        )
        assert float(values["max_torque"]) == case["torque"]
        assert float(values["max_accel"]) <= min(
            mb.max_axis_accel_mm_s2(machine, (1.0, 0.0), "continuous"),
            mb.max_axis_accel_mm_s2(machine, (0.0, 1.0), "continuous"),
        )
        assert float(values["max_velocity"]) <= min(
            mb.max_axis_velocity_mm_s(machine, (1.0, 0.0)),
            mb.max_axis_velocity_mm_s(machine, (0.0, 1.0)),
        )


def test_a_suggested_ceiling_rounds_down_never_up():
    """`max_accel` is derived from a limit, so rounding it up publishes a
    config a hair over the number it was derived from."""
    assert "cfgnum(Math.floor(Math.min(Math.min(cx,cy), 25000)))" in PAGE
    assert "cfgnum(Math.floor(Math.min(Math.min(vx,vy), 1000)))" in PAGE


def test_a_raised_torque_limit_is_labelled_in_the_config_it_writes():
    """A pasted `max_torque: 300` with no comment reads like a setting someone
    chose. It is the drive's burst ceiling, and the guide ships 100."""
    assert "burst, not continuous; the guide ships 100" in PAGE


@pytest.mark.skipif(
    shutil.which("node") is None, reason="no JavaScript engine to run the page"
)
def test_the_page_computes_what_the_model_computes():
    driver = (
        page_physics_source()
        + "\nvar out = "
        + json.dumps(CASES)
        + ".map(function(s){\n"
        "  var m = machine(s);\n"
        "  return {ax: maxAccel(m,[1,0],'peak'), ay: maxAccel(m,[0,1],'peak'),\n"
        "          vx: maxVel(m,[1,0]), vy: maxVel(m,[0,1]),\n"
        "          beltTorque: m.beltTorque, motorTorque: m.motorTorque,\n"
        "          peak: m.peak, continuous: m.continuous,\n"
        "          contLimiter: m.contLimiter, duty: beltDuty(m,[0,1]),\n"
        "          cont: maxAccel(m,[0,1],'continuous'),\n"
        "          reflected: m.reflected, rot: m.rot};\n"
        "});\n"
        "console.log(JSON.stringify(out));\n"
    )
    result = subprocess.run(
        ["node", "-e", driver], capture_output=True, text=True, check=True
    )
    got = json.loads(result.stdout)
    assert len(got) == len(CASES)
    for case, page in zip(CASES, got):
        machine = machine_for(case)
        assert page["rot"] == pytest.approx(machine.rotation_distance_mm)
        assert page["motorTorque"] == pytest.approx(machine.motor.torque_nm)
        assert page["beltTorque"] == pytest.approx(
            machine.belt_continuous_torque_nm
        )
        assert page["peak"] == pytest.approx(machine.peak_torque_nm)
        assert page["continuous"] == pytest.approx(machine.continuous_torque_nm)
        assert page["contLimiter"] == machine.continuous_limiting_part
        assert page["duty"] == pytest.approx(
            mb.belt_duty_ratio(machine, (0.0, 1.0))
        )
        assert page["reflected"] == pytest.approx(
            mb.reflected_rotor_mass_kg(machine)
        )
        assert page["ax"] == pytest.approx(
            mb.max_axis_accel_mm_s2(machine, (1.0, 0.0), "peak")
        ), case
        assert page["ay"] == pytest.approx(
            mb.max_axis_accel_mm_s2(machine, (0.0, 1.0), "peak")
        ), case
        assert page["cont"] == pytest.approx(
            mb.max_axis_accel_mm_s2(machine, (0.0, 1.0), "continuous")
        ), case
        assert page["ay"] >= page["cont"], case
        assert page["vx"] == pytest.approx(
            mb.max_axis_velocity_mm_s(machine, (1.0, 0.0))
        ), case
        assert page["vy"] == pytest.approx(
            mb.max_axis_velocity_mm_s(machine, (0.0, 1.0))
        ), case
