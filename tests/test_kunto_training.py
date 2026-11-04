import datetime as dt
import pathlib
import shutil

import pytest

from kunto import data as kdata
from kunto import gym
from kunto import plan as kplan
from kunto import training as tr

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "kunto"
TODAY = dt.date(2026, 10, 7)


@pytest.fixture(scope="module")
def plan():
    return kplan.load_plan(ROOT / "training-plan-2026-27.json")


@pytest.fixture(scope="module")
def view(plan, tmp_path_factory):
    root = tmp_path_factory.mktemp("kunto")
    shutil.copytree(FIX / "data", root / "data")
    return tr.build_training(plan, kdata.load_garmin(root), TODAY)


@pytest.mark.parametrize("block,family", [
    ("0 Re-entry", "reentry"), ("1 Athletic base", "base"), ("Holiday deload", "holiday"),
    ("2 Floorball peak", "floorball"), ("Transition", "transition"), ("3 Goal focus · wk 4", "goal"),
    ("Summer running block", "summer"), ("4 Peak · wk 7", "peak"), ("Test week", "test"), ("Mystery", "other")])
def test_block_family(block, family):
    assert tr.block_family(block) == family


def test_current_week_and_states(view):
    assert view["current_week"] == 2
    assert [w["state"] for w in view["weeks"][:3]] == ["past", "current", "future"]
    assert len(view["weeks"]) == 51 and view["past_weeks"] == [1]


def test_week_top_line_and_km(view):
    w1, w2 = view["weeks"][0], view["weeks"][1]
    assert w1["top"] == "Week 1 of 51 · 0 Re-entry · 28 Sep – 4 Oct 2026"
    assert (w1["km_actual"], w1["km_plan"], w1["km_state"]) == ("15.0", "10–15", "in")
    assert w2["km_text"] == "5.2 of 15–25 km" and w2["km_state"] == "none"       # in progress: not judged yet
    # the plan json flags re-entry, holiday, transition and block-4 wk 4 as deload; only the last is a
    # "gym sets -40%" wave deload, so the pill names the week type and the day cards carry the content
    assert w1["flags"] == ["Deload week"]


def _past_week_1(plan, kms, run_km=None):
    """Week 1 viewed the day after it ended, one run per km value (Mon, Tue, ...); run_km overrides its target."""
    w = plan["weeks"][0] if run_km is None else {**plan["weeks"][0], "run_km": run_km}
    mon = dt.date.fromisoformat(w["start"])
    acts = [{"date": mon + dt.timedelta(days=i), "start": dt.datetime.combine(mon + dt.timedelta(days=i), dt.time(7)),
             "type": "running", "name": "Run", "km": k, "min": 30.0, "avg_hr": 140.0, "cadence": 166.0}
            for i, k in enumerate(kms)]
    view_day = dt.date.fromisoformat(w["end"]) + dt.timedelta(days=1)
    # a daily row for the viewing day = that morning's pull ran, so the whole week is covered
    g = kdata.Garmin(daily={view_day: {"date": view_day}}, activities=acts, fitness=[], csv_mtime=None)
    return tr.week_view(plan, w, g, view_day)


@pytest.mark.parametrize("kms,text,state", [
    ([4.0, 4.0], "8.0 of 10–15 km", "under"),
    ([12.0], "12.0 of 10–15 km", "in"),
    ([9.0, 8.0], "17.0 of 10–15 km", "over")])
def test_past_week_under_in_and_over_its_range(plan, kms, text, state):
    v = _past_week_1(plan, kms)
    assert (v["km_text"], v["km_state"]) == (text, state)


@pytest.mark.parametrize("kms,text,state", [
    ([9.94], "9.9 of 10–15 km", "under"),
    ([9.96], "10.0 of 10–15 km", "in"),            # the page shows 10.0, so it is judged as 10.0
    ([15.04], "15.0 of 10–15 km", "in"),           # the page shows 15.0: not amber
    ([15.06], "15.1 of 10–15 km", "over")])
def test_km_is_judged_at_the_precision_the_page_shows(plan, kms, text, state):
    v = _past_week_1(plan, kms)
    assert (v["km_actual"], v["km_text"], v["km_state"]) == (text.split()[0], text, state)


@pytest.mark.parametrize("kms,text", [
    ([40.0], "40.0 of 40 km"), ([40.3], "40.3 of 40 km"), ([39.8], "39.8 of 40 km"), ([20.0], "20.0 of 40 km")])
def test_single_number_target_is_shown_but_not_judged(plan, kms, text):
    # A plan week of "40" has no range; no tolerance is agreed, so it is never marked under, in or over.
    v = _past_week_1(plan, kms, run_km="40")
    assert (v["km_text"], v["km_state"], v["state"]) == (text, "none", "past")


def test_week_summary_counts_required_and_optional(view):
    w1 = view["weeks"][0]
    assert w1["summary"] == {"req_done": 4, "req_total": 5, "opt_done": 1, "opt_total": 3}
    assert w1["summary_text"] == "4/5 required · 1/3 optional · 15.0 of 10–15 km"


def test_session_statuses_and_details(view):
    days = view["weeks"][0]["days"]
    mon, thu, sun = days[0]["sessions"][0], days[3]["sessions"][0], days[6]["sessions"][0]
    assert (mon["status"], mon["status_label"], mon["detail"]) == (
        "done", "✓ Done", "6.1 km · 32 min · avg HR 140")
    assert (thu["status"], thu["status_label"], thu["detail"]) == (
        "moved", "Moved to Sat", "3.9 km · 21 min · avg HR 142")
    assert (sun["status"], sun["status_label"], sun["detail"]) == ("missed", "✗ Missed", None)
    wed = days[2]["sessions"]
    assert [(s["status_label"], s["optional"], s["first_to_go"]) for s in wed] == [
        ("Skipped", True, True), ("Skipped", True, True)]


def test_today_and_upcoming_in_the_current_week(view):
    days = view["weeks"][1]["days"]
    assert days[2]["is_today"] is True and days[2]["label"] == "Wed 7 Oct"
    assert [s["status"] for s in days[2]["sessions"]] == ["today", "today"]
    sat = days[5]["sessions"][0]
    assert (sat["title"], sat["kind"], sat["hard"], sat["min"], sat["status_label"]) == (
        "Benchmarks + Legs", "test", True, "70 min", "Planned")
    tue = days[1]["sessions"][0]
    assert tue["detail"] == "55 min · avg HR 150"


def test_rest_days_show_rest(view):
    test_week = view["weeks"][50]
    fri = test_week["days"][4]["sessions"]
    assert [(s["kind"], s["status"], s["status_label"]) for s in fri] == [("rest", "rest", "Rest")]
    assert test_week["summary"]["req_total"] == 4          # Mon, Tue, Wed lifts, Sat Cooper; rest days do not count


def test_markers(view):
    assert [m["week"] for m in view["markers"]] == [2, 4, 11, 23, 34, 39, 46, 51]
    assert view["markers"][0] == {"week": 2, "d": "2026-10-10", "label": "Benchmarks + Legs", "sub": "Sat 10 Oct"}


def test_before_the_season_everything_is_upcoming(plan, tmp_path):
    shutil.copytree(FIX / "data", tmp_path / "data")
    v = tr.build_training(plan, kdata.as_of(kdata.load_garmin(tmp_path), dt.date(2026, 9, 27)), dt.date(2026, 9, 27))
    assert v["current_week"] == 1 and v["past_weeks"] == []
    assert {s["status"] for s in v["weeks"][0]["days"][0]["sessions"]} == {"upcoming"}


def test_a_failed_pull_holds_back_the_verdicts(plan):
    # Week 1 viewed on Mon Oct 5 but the newest daily row is Sun Oct 4 (the Monday pull failed):
    # Sunday is not fully covered, so its sessions read "No data yet" and the km is not judged
    w = plan["weeks"][0]
    sun = dt.date.fromisoformat(w["end"])
    g = kdata.Garmin(daily={sun: {"date": sun}}, activities=[], fitness=[], csv_mtime=None)
    v = tr.week_view(plan, w, g, sun + dt.timedelta(days=1))
    sun_sessions = [s for d in v["days"] if d["date"] == w["end"] for s in d["sessions"]]
    assert sun_sessions and {s["status"] for s in sun_sessions} == {"nodata"}
    assert {s["status_label"] for s in sun_sessions} == {"No data yet"}
    assert v["km_state"] == "none"
    sat_sessions = [s for d in v["days"] if d["date"] == (sun - dt.timedelta(days=1)).isoformat() for s in d["sessions"]]
    assert {s["status"] for s in sat_sessions} == {"missed"}           # Saturday is covered: judged


def upper_on_saturday():
    """Week 1's Saturday strength activity, tagged the way build_kunto tags it when Hevy shows an upper session."""
    sat = dt.date(2026, 10, 3)
    lift = {"date": sat, "start": dt.datetime(2026, 10, 3, 17, 2), "type": "strength_training", "name": "Strength",
            "km": None, "min": 26.0, "avg_hr": 94.0, "cadence": None, "focus": "upper"}
    return kdata.Garmin(daily={sat: {"date": sat}}, activities=[lift], fitness=[], csv_mtime=None)


def test_a_swapped_gym_weekend_is_read_from_hevy(plan):
    """Sat planned Legs, Hevy shows upper (decision-log 2026-10-04): on the Sunday the Upper is credited to
    Saturday and says why; the Legs is swapped to Sunday, not done and not missed."""
    v = tr.week_view(plan, plan["weeks"][0], upper_on_saturday(), dt.date(2026, 10, 4))
    gym = {d["label"]: s for d in v["days"] for s in d["sessions"] if s["kind"] == "gym" and not s["optional"]}
    legs, upper = gym["Sat 3 Oct"], gym["Sun 4 Oct"]
    assert (legs["title"], legs["status"], legs["status_label"], legs["detail"]) == (
        "Legs @ RPE 6, no power block", "swapped", "Swapped to Sun", None)
    assert (upper["title"], upper["status"], upper["status_label"], upper["detail"]) == (
        "Upper @ RPE 6", "moved", "Moved to Sat", "26 min · avg HR 94 · Hevy: upper body")


def test_gym_sessions_show_a_card_and_runs_keep_their_chips(view):
    """Oct 21: exercises as rows with capitals, the warm-up first, the session note on top."""
    sun = view["weeks"][3]["days"][6]["sessions"][0]               # Sun Oct 25, Upper
    c = sun["card"]
    assert c["note"].startswith("RPE\u00a0≤7 all session")
    assert c["warmup"]["label"] == "Warm-up · 8 min" and c["warmup"]["steps"][1] == {"name": "Band pull-apart",
                                                                                     "rx": "2 × 15"}
    assert [(s["label"], [r["name"] for r in s["rows"]][:2]) for s in c["sections"]] == [
        ("Main", ["Strict OHP", "Weighted pull-ups"]), ("Accessories", ["Body-weight pull-ups", "Chest-supported DB row"])]
    assert "last" not in c["sections"][0]["rows"][0]              # no gym log given
    run = view["weeks"][3]["days"][0]["sessions"][0]
    assert run["card"] is None and run["chips"] == ["Calf raises + pogos 2×20", "4–6 × 20 s strides"]


def test_only_sessions_ahead_show_the_last_top_set(plan, tmp_path):
    root = tmp_path / "k"
    shutil.copytree(FIX / "data", root / "data")
    lasts = {"Overhead Press (Barbell)": gym.Set(dt.date(2026, 10, 4), "Overhead Press (Barbell)", "normal", 45.0, 6, 8.0)}
    v = tr.build_training(plan, kdata.load_garmin(root), TODAY, lasts)
    ohp = lambda w, d: next(r for s in v["weeks"][w]["days"][d]["sessions"] for r in s["card"]["sections"][0]["rows"])
    assert ohp(1, 6)["last"] == {"set": "45 kg × 6", "tail": "@ 8 · Sun 4 Oct"}   # Sun Oct 11, ahead of Oct 7
    assert "last" not in ohp(0, 6)                                                # Sun Oct 4, past
