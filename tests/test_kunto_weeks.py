import datetime as dt
import pathlib

import pytest

from kunto import plan as kplan

ROOT = pathlib.Path(__file__).resolve().parents[1]
D = dt.date


@pytest.fixture(scope="module")
def plan():
    return kplan.load_plan(ROOT / "training-plan-2026-27.json")


def test_season_bounds(plan):
    assert kplan.season_bounds(plan) == (D(2026, 9, 28), D(2027, 9, 19))


@pytest.mark.parametrize("day,week,block,template", [
    (D(2026, 9, 28), 1, "0 Re-entry", "re-entry"),
    (D(2026, 10, 4), 1, "0 Re-entry", "re-entry"),
    (D(2026, 10, 5), 2, "1 Athletic base", "in-season-b1"),
    (D(2026, 11, 9), 7, "1 Athletic base", "athletic-base"),
    (D(2026, 12, 25), 13, "Holiday deload", "holiday-deload"),
    (D(2027, 1, 4), 15, "2 Floorball peak", "in-season-b2"),
    (D(2027, 6, 24), 39, "3 Goal focus · wk 12 (strength turn)", "b3-strength"),
    (D(2027, 8, 2), 45, "4 Peak · wk 2", "b4-a"),
    (D(2027, 8, 9), 46, "4 Peak · wk 3", "event-week"),
    (D(2027, 9, 13), 51, "Test week", "test-week"),
    (D(2027, 9, 19), 51, "Test week", "test-week"),
])
def test_week_for_date(plan, day, week, block, template):
    w = kplan.week_for_date(plan, day)
    assert (w["week"], w["block"], w["template"]) == (week, block, template)


@pytest.mark.parametrize("day", [D(2026, 9, 27), D(2027, 9, 20), D(2025, 1, 1)])
def test_week_for_date_outside_season(plan, day):
    assert kplan.week_for_date(plan, day) is None
    assert kplan.sessions_for_date(plan, day) == []


def test_current_week_number_clamps(plan):
    assert kplan.current_week_number(plan, D(2026, 9, 27)) == 1
    assert kplan.current_week_number(plan, D(2026, 10, 7)) == 2
    assert kplan.current_week_number(plan, D(2027, 12, 1)) == 51


def test_resolve_week_uses_template_days(plan):
    days = kplan.resolve_week(plan, kplan.get_week(plan, 3))
    assert [d["dow"] for d in days] == list(kplan.DAYS)
    assert days[0]["date"] == D(2026, 10, 12) and days[6]["date"] == D(2026, 10, 18)
    assert days[1]["sessions"][0]["kind"] == "floorball"
    assert days[1]["sessions"][0]["hard"] is True
    assert [s["optional"] for s in days[2]["sessions"]] == [True, True]


def test_resolve_week_override_replaces_the_day(plan):
    sat = kplan.resolve_week(plan, kplan.get_week(plan, 2))[5]
    assert [s["kind"] for s in sat["sessions"]] == ["test"]
    assert sat["sessions"][0]["title"] == "Benchmarks + Legs"
    fri = kplan.resolve_week(plan, kplan.get_week(plan, 2))[4]
    assert fri["sessions"][0]["title"] == "Run in 5 km easy"      # not overridden: template day


def test_sessions_for_date_cooper_two(plan):
    [s] = kplan.sessions_for_date(plan, D(2027, 6, 24))
    assert (s["kind"], s["title"], s["hard"]) == ("test", "Cooper #2", True)


def test_block4_track_overrides(plan):
    assert kplan.sessions_for_date(plan, D(2027, 8, 3))[0]["title"] == "Track: 5 × 1 km @ ~4:20"
    assert kplan.sessions_for_date(plan, D(2027, 8, 19))[0]["title"] == "Easy run"       # wk 47 deload Thu


@pytest.mark.parametrize("text,expected", [("10–15", (10.0, 15.0)), ("35", (35.0, 35.0)),
                                           ("40-45", (40.0, 45.0)), ("", None), ("lots", None)])
def test_run_km_range(text, expected):
    assert kplan.run_km_range(text) == expected


def test_season_markers(plan):
    marks = kplan.season_markers(plan)
    assert [(m["week"], m["date"]) for m in marks] == [
        (2, D(2026, 10, 10)), (4, D(2026, 10, 22)), (11, D(2026, 12, 12)), (23, D(2027, 3, 6)),
        (34, D(2027, 5, 22)), (39, D(2027, 6, 24)), (46, D(2027, 8, 14)), (51, D(2027, 9, 13))]
    assert marks[-1]["label"] == "Test week"
    assert marks[1]["label"] == "Cooper #1" and marks[5]["label"] == "Cooper #2"
