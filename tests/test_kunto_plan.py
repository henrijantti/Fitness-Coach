import copy
import datetime as dt
import json
import pathlib

import pytest

from kunto import plan as kplan

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "training-plan-2026-27.json"
V35_WEEK_KEYS = {"week", "start", "end", "block", "run_km", "key", "note", "flags"}


@pytest.fixture(scope="module")
def real_plan():
    return kplan.load_plan(PLAN_PATH)


def mini_plan():
    day = [{"kind": "run", "title": "Easy run", "min": 40}]
    t = {d: copy.deepcopy(day) for d in kplan.DAYS}
    return {"templates": {"base": t},
            "weeks": [{"week": 1, "start": "2026-09-28", "end": "2026-10-04", "block": "0 Re-entry",
                       "run_km": "10–15", "flags": [], "template": "base"},
                      {"week": 2, "start": "2026-10-05", "end": "2026-10-11", "block": "1 Athletic base",
                       "run_km": "15–25", "flags": [], "template": "base"}]}


# ---------- the real plan json ----------

def test_real_plan_validates(real_plan):
    assert kplan.validate_plan(real_plan) == []


def test_real_plan_every_week_has_a_known_template(real_plan):
    assert len(real_plan["weeks"]) == 51
    for w in real_plan["weeks"]:
        assert w["template"] in real_plan["templates"], w["week"]


def test_real_plan_has_the_thirteen_templates(real_plan):
    assert set(real_plan["templates"]) == {
        "re-entry", "in-season-b1", "athletic-base", "in-season-b2", "holiday-deload", "transition", "b3-early", "b3-strength",
        "summer", "b4-a", "b4-b", "event-week", "test-week"}


def test_real_plan_keeps_v35_keys(real_plan):
    assert real_plan["meta"]["name"] == "Sample Training Plan"
    assert list(real_plan)[:6] == ["meta", "events", "targets", "zones", "weeks", "open_items"]
    for w in real_plan["weeks"]:
        assert V35_WEEK_KEYS <= set(w)
        assert set(w) - V35_WEEK_KEYS <= {"template", "overrides"}


def test_real_plan_file_stays_in_canonical_form():
    raw = PLAN_PATH.read_text(encoding="utf-8")
    assert json.dumps(json.loads(raw), indent=2, ensure_ascii=False) == raw


def test_real_plan_optional_sessions_follow_the_cut_order(real_plan):
    b1 = real_plan["templates"]["athletic-base"]
    wed = [kplan.normalize_session(s) for s in b1["wed"]]
    fri = [kplan.normalize_session(s) for s in b1["fri"]]
    assert all(s["optional"] and s["first_to_go"] for s in wed + fri)
    assert [s["kind"] for s in wed] == ["gym", "run"]
    core = [kplan.normalize_session(s) for d in ("mon", "tue", "thu", "sat", "sun") for s in b1[d]]
    # the Thursday-lunch extra sits on top: optional, never one of the three (decision-log 2026-10-04); in block 1
    # it is speed + jumps (decision-log 2026-10-25), block 2 keeps the SkiErg 4 × 4′
    assert [(s["title"], s["kind"], s["first_to_go"]) for s in core if s["optional"]] == [("Speed + jumps, lunch", "gym", False)]
    for name in ("in-season-b1", "in-season-b2"):          # v3.5 block 1 (weeks 2-4) and block 2 keep the SkiErg
        t = real_plan["templates"][name]
        assert [s["title"] for s in t["thu"] if s.get("optional")] == ["SkiErg 4 × 4′, lunch"]
    required = [s for s in core if not s["optional"]]
    assert sum(s["hard"] for s in required) == 3            # three hard sessions, never four


CUT_ORDER = ("Bonus", "Run home", "Run in 5 km")          # Wed bonus, Wed run home, Fri commute run


def test_real_plan_cut_order_sessions_are_optional_in_every_template(real_plan):
    """Owner decision 1: the Wed bonus, the Wed run home and the Fri commute run are optional and first to go
    wherever they appear; nothing else is first to go; the other optional sessions are the five listed extras."""
    templates = [s for t in real_plan["templates"].values() for d in kplan.DAYS for s in t[d]]
    overrides = [s for w in real_plan["weeks"] for day in w.get("overrides", {}).values() for s in day]
    sessions = [kplan.normalize_session(s) for s in templates + overrides]
    cut = [s for s in sessions if s["title"].startswith(CUT_ORDER)]
    others = [s for s in sessions if not s["title"].startswith(CUT_ORDER)]
    # 10 templates × (bonus, run home, Friday run); not holiday/summer/test. A week's overrides (the Sunday
    # check-in's adjustments) may repeat them: those are checked below, never counted
    assert sum(s["title"].startswith(CUT_ORDER) for s in templates) == 30
    assert all(s["optional"] and s["first_to_go"] for s in cut)
    assert not any(s["first_to_go"] for s in others)
    assert sorted({s["title"] for s in others if s["optional"]}) == [
        "Easy run 30–40′", "Floorball, if the season still runs", "Ski race 25 km",
        "SkiErg 4 × 4′, lunch", "Speed + jumps, lunch", "XC skiing, holiday trip"]


def test_real_plan_has_no_em_dash_in_templates(real_plan):
    text = json.dumps({"templates": real_plan["templates"],
                       "overrides": [w.get("overrides") for w in real_plan["weeks"]]}, ensure_ascii=False)
    assert "—" not in text


# ---------- the validator ----------

def test_validate_accepts_mini_plan():
    assert kplan.validate_plan(mini_plan()) == []


def test_validate_rejects_unknown_kind():
    p = mini_plan()
    p["templates"]["base"]["tue"][0]["kind"] = "yoga"
    errs = kplan.validate_plan(p)
    assert any("template base.tue[0]" in e and "yoga" in e for e in errs)


def test_validate_rejects_unknown_template():
    p = mini_plan()
    p["weeks"][1]["template"] = "missing"
    assert any(e.startswith("week 2: template 'missing'") for e in kplan.validate_plan(p))


def test_validate_rejects_missing_day_and_empty_title():
    p = mini_plan()
    del p["templates"]["base"]["sun"]
    assert any("needs exactly the keys" in e for e in kplan.validate_plan(p))
    p = mini_plan()
    p["templates"]["base"]["mon"][0]["title"] = " "
    assert any("title must be a non-empty string" in e for e in kplan.validate_plan(p))


def test_validate_rejects_bad_fields():
    p = mini_plan()
    p["templates"]["base"]["mon"][0].update({"min": "40", "hard": "yes", "colour": "red"})
    errs = " | ".join(kplan.validate_plan(p))
    assert "min must be a positive integer" in errs
    assert "hard must be true or false" in errs
    assert "unknown keys ['colour']" in errs


def test_validate_rejects_rest_mixed_with_sessions():
    p = mini_plan()
    p["templates"]["base"]["sun"] = [{"kind": "rest", "title": "Rest"}, {"kind": "run", "title": "Run"}]
    assert any("a rest day holds only the rest session" in e for e in kplan.validate_plan(p))


def test_validate_rejects_a_session_without_a_title():
    p = mini_plan()
    p["templates"]["base"]["sun"] = [{"kind": "rest"}]
    assert kplan.validate_plan(p) == ["template base.sun[0]: title must be a non-empty string"]


def test_validate_rejects_a_session_that_is_not_an_object():
    p = mini_plan()
    p["templates"]["base"]["mon"] = ["Easy run"]
    assert kplan.validate_plan(p) == ["template base.mon[0]: a session must be an object"]


@pytest.mark.parametrize("chips", [[""], [3], "Back squat"], ids=["empty-chip", "number-chip", "bare-string"])
def test_validate_rejects_bad_chips(chips):
    p = mini_plan()
    p["templates"]["base"]["mon"][0]["chips"] = chips
    assert kplan.validate_plan(p) == ["template base.mon[0]: chips must be a list of non-empty strings"]


@pytest.mark.parametrize("minutes", [True, 0])
def test_validate_rejects_min_that_is_not_a_positive_integer(minutes):
    p = mini_plan()
    p["templates"]["base"]["mon"][0]["min"] = minutes
    assert kplan.validate_plan(p) == ["template base.mon[0]: min must be a positive integer"]


@pytest.mark.parametrize("flag", ["hard", "optional", "first_to_go"])
def test_validate_rejects_a_quoted_flag(flag):
    """normalize_session would read a quoted "false" as True, so every flag must be a JSON boolean."""
    p = mini_plan()
    p["templates"]["base"]["mon"][0][flag] = "false"
    assert kplan.validate_plan(p) == [f"template base.mon[0]: {flag} must be true or false"]


def test_validate_rejects_an_empty_or_bare_day():
    p = mini_plan()
    p["templates"]["base"]["wed"] = []
    assert kplan.validate_plan(p) == ["template base.wed: must be a non-empty list of sessions"]
    p = mini_plan()
    p["templates"]["base"]["wed"] = {"kind": "rest", "title": "Rest"}          # the list brackets forgotten
    assert kplan.validate_plan(p) == ["template base.wed: must be a non-empty list of sessions"]


def test_validate_rejects_overrides_that_are_not_a_day_map():
    p = mini_plan()
    p["weeks"][0]["overrides"] = {"sat": [{"kind": "test", "title": "Benchmarks"}], "funday": []}
    assert any("overrides must map day keys" in e for e in kplan.validate_plan(p))
    p = mini_plan()
    p["weeks"][0]["overrides"] = [{"sat": [{"kind": "test", "title": "Benchmarks"}]}]
    assert any("overrides must map day keys" in e for e in kplan.validate_plan(p))


def test_validate_checks_override_sessions():
    """Overrides are where in-season hand edits land: their days get the same checks as a template's."""
    p = mini_plan()
    p["weeks"][0]["overrides"] = {"sat": [{"kind": "floorbal", "title": ""}]}
    errs = kplan.validate_plan(p)
    assert any(e.startswith("week 1 overrides.sat[0]: kind 'floorbal' is not one of") for e in errs)
    assert "week 1 overrides.sat[0]: title must be a non-empty string" in errs
    p = mini_plan()
    p["weeks"][0]["overrides"] = {"sat": []}
    assert kplan.validate_plan(p) == ["week 1 overrides.sat: must be a non-empty list of sessions"]


def test_validate_rejects_weeks_out_of_order():
    p = mini_plan()
    p["weeks"][1]["week"] = 3
    assert kplan.validate_plan(p) == ["week 3: weeks must be numbered 1..2 in order"]


@pytest.mark.parametrize("start, end", [("2026-10-12", "2026-10-18"), ("2026-09-28", "2026-10-04")],
                         ids=["a-week-late", "week-1-repeated"])
def test_validate_rejects_weeks_that_do_not_run_back_to_back(start, end):
    """Monday to Sunday, but not the week after week 1. get_week indexes the list by week number and
    week_for_date scans the date ranges, so the weeks must run back to back."""
    p = mini_plan()
    p["weeks"][1]["start"], p["weeks"][1]["end"] = start, end
    assert kplan.validate_plan(p) == ["week 2: does not follow the previous week"]


def test_validate_rejects_a_week_that_is_not_monday_to_sunday():
    p = mini_plan()
    p["weeks"][1]["start"], p["weeks"][1]["end"] = "2026-10-06", "2026-10-12"      # Tuesday to Monday
    assert any(e.startswith("week 2: must run Monday") for e in kplan.validate_plan(p))
    p = mini_plan()
    p["weeks"][1]["end"] = "2026-10-10"                                               # Monday to Saturday
    assert kplan.validate_plan(p) == ["week 2: must run Monday 2026-10-05 to Sunday 2026-10-11"]


@pytest.mark.parametrize("edit", [lambda w: w.update(start="bad"), lambda w: w.update(start=None),
                                  lambda w: w.pop("end")], ids=["garbled", "null", "missing"])
def test_validate_rejects_unreadable_week_dates(edit):
    p = mini_plan()
    edit(p["weeks"][1])
    assert kplan.validate_plan(p) == ["week 2: start/end must be YYYY-MM-DD"]


def test_validate_reports_missing_templates_section():
    p = mini_plan()
    del p["templates"]
    errs = kplan.validate_plan(p)
    assert "plan: missing the templates section" in errs


def test_validate_reports_missing_weeks_list():
    p = mini_plan()
    del p["weeks"]
    assert kplan.validate_plan(p) == ["plan: missing the weeks list"]


def test_load_plan_errors(tmp_path):
    with pytest.raises(kplan.PlanError, match="missing plan file"):
        kplan.load_plan(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(kplan.PlanError, match="invalid JSON"):
        kplan.load_plan(bad)


def test_normalize_session_fills_defaults():
    assert kplan.normalize_session({"kind": "floorball", "title": "Floorball"}) == {
        "kind": "floorball", "title": "Floorball", "chips": [], "min": None,
        "hard": False, "optional": False, "first_to_go": False, "focus": None, "warmup": None, "note": None}
    assert kplan.normalize_session({"kind": "gym", "title": "Legs", "focus": "legs"})["focus"] == "legs"


# ---------- the gym focus (decision-log 2026-10-04) ----------

def test_real_plan_every_gym_session_names_its_focus(real_plan):
    """Kunto credits a gym session by what Hevy shows was lifted: a gym session without a focus would tick
    on any strength activity, so every one in the plan names legs, upper or full."""
    templates = [s for t in real_plan["templates"].values() for d in kplan.DAYS for s in t[d]]
    raw = templates + [s for w in real_plan["weeks"] for day in w.get("overrides", {}).values() for s in day]
    gym = [s for s in raw if s["kind"] == "gym"]
    assert sum(s["kind"] == "gym" for s in templates) == 34          # overrides come and go with the check-ins
    assert all(s.get("focus") in kplan.FOCI for s in gym)
    assert not any("focus" in s for s in raw if s["kind"] != "gym")
    b1 = real_plan["templates"]["athletic-base"]
    assert {s["title"]: s["focus"] for d in ("wed", "sat", "sun") for s in b1[d] if s["kind"] == "gym"} == {
        "Bonus": "upper", "Power + Legs": "legs", "Upper": "upper"}
    assert {s["title"] for s in gym if s["focus"] == "full"} == {"Maintenance gym", "Maintenance + RPE-8 triples",
                                                                 "Speed + jumps, lunch", "Legs + Upper"}


def test_validate_checks_the_gym_focus():
    p = mini_plan()
    p["templates"]["base"]["mon"] = [{"kind": "gym", "title": "Legs", "focus": "legs"}]
    assert kplan.validate_plan(p) == []
    wrong = "template base.mon[0]: focus is for gym sessions only and must be one of legs, upper, full"
    p["templates"]["base"]["mon"][0]["focus"] = "arms"
    assert kplan.validate_plan(p) == [wrong]
    p = mini_plan()
    p["templates"]["base"]["mon"][0]["focus"] = "legs"                 # a run
    assert kplan.validate_plan(p) == [wrong]


# ---------- warm-ups (Oct 21) ----------

def test_real_plan_every_gym_and_lift_test_session_has_a_warmup(real_plan):
    """A gym session takes its focus warm-up, block 1's Thursday speed + jumps the jumps-sprints one; the lift
    tests and the checkpoint name theirs."""
    days = [d for w in real_plan["weeks"] for d in kplan.resolve_week(real_plan, w)]
    gym = [s for d in days for s in d["sessions"] if s["kind"] == "gym"]
    speed = [s for s in gym if s["title"] == "Speed + jumps, lunch"]
    assert speed and all(s["warmup"] == real_plan["warmups"]["jumps-sprints"] for s in speed)
    assert all(s["warmup"] == real_plan["warmups"][s["focus"]] for s in gym if s not in speed)
    tests = {s["title"]: s["warmup"] for d in days for s in d["sessions"] if s["kind"] == "test"}
    assert tests["Lift baselines"] == tests["Test: lifts"] == real_plan["warmups"]["lift-test"]
    assert tests["Checkpoint + Legs"] == real_plan["warmups"]["jumps-sprints"]
    assert tests["Cooper #1"] is None                              # the Cooper warm-up is in its chips


def test_lift_baselines_state_each_lift_target(real_plan):
    """The Oct 24 test card names every lift with its own target, no shared header chip (Oct 21)."""
    sat = kplan.sessions_for_date(real_plan, dt.date(2026, 10, 24))[0]
    assert [c.split(":")[0] for c in sat["chips"][:3]] == ["strict OHP", "front squat", "weighted pull-up"]
    assert all("one top set of 5 @ RPE 8" in c for c in sat["chips"][:3])
    assert not any(c.startswith(("each lift", "then ")) for c in sat["chips"])


def test_normalize_session_resolves_the_warmup():
    wu = {"legs": {"min": 10, "steps": [["easy bike", "5′"]]}, "lift-test": {"min": 12, "steps": [["easy row", "5′"]]}}
    assert kplan.normalize_session({"kind": "gym", "title": "Legs", "focus": "legs"}, wu)["warmup"] == wu["legs"]
    assert kplan.normalize_session({"kind": "test", "title": "Lifts", "warmup": "lift-test"}, wu)["warmup"] == \
        wu["lift-test"]
    assert kplan.normalize_session({"kind": "gym", "title": "Legs", "focus": "legs"})["warmup"] is None
    assert kplan.normalize_session({"kind": "run", "title": "Run"}, wu)["warmup"] is None


def test_validate_checks_the_warmups_and_notes():
    p = mini_plan()
    p["warmups"] = {"legs": {"min": 10, "steps": [["easy bike", "5′"]], "ramp": "bar ×8 → ~50% ×5"}}
    p["templates"]["base"]["mon"] = [{"kind": "test", "title": "Lifts", "warmup": "legs", "note": "RPE ≤7"}]
    assert kplan.validate_plan(p) == []
    p["templates"]["base"]["mon"][0].update({"warmup": "arms", "note": " "})
    assert kplan.validate_plan(p) == ["template base.mon[0]: note must be a non-empty string",
                                      "template base.mon[0]: warmup 'arms' is not in the warmups section"]
    wrong = "warmup legs: needs min (a positive integer), steps ([name, amount] pairs) and optionally ramp"
    for bad in ({"min": 0, "steps": [["easy bike", "5′"]]}, {"min": 10, "steps": []},
                {"min": 10, "steps": ["5′ easy bike"]}, {"min": 10, "steps": [["easy bike", "5′"]], "ramp": ""},
                {"min": 10, "steps": [["easy bike", "5′"]], "colour": "red"}):
        p = mini_plan()
        p["warmups"] = {"legs": bad}
        assert kplan.validate_plan(p) == [wrong], bad


def test_real_plan_session_notes(real_plan):
    """Rules for a whole session are its note, not a chip that reads like an exercise."""
    sun = kplan.sessions_for_date(real_plan, dt.date(2026, 10, 25))[0]
    assert sun["note"].startswith("RPE ≤7 all session") and not any("RPE ≤7" in c for c in sun["chips"])
    assert real_plan["templates"]["in-season-b2"]["sat"][0]["note"] == "match week: sled and shuttles out"


def test_athletic_base_leaves_weeks_2_to_4_as_they_ran(real_plan):
    """decision-log 2026-10-25: weeks 5-12 run the athletic-base template; weeks 2-4 keep v3.5's block 1."""
    assert [kplan.get_week(real_plan, n)["template"] for n in range(2, 13)] == ["in-season-b1"] * 3 + ["athletic-base"] * 8
    wed = kplan.sessions_for_date(real_plan, dt.date(2026, 10, 14))[0]
    assert "DB bench 3×8–10" in wed["chips"] and not any(c.startswith("dips") for c in wed["chips"])
