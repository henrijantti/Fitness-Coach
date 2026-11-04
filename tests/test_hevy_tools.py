"""Tests for hevy/tools.py: the five MCP answers, on four workouts adapted from a real Hevy export, loads altered (next_load on made-up ones)."""
import datetime as dt

from hevy import tools
from hevy.client import HevyClient
from hevy_fake import FakeResponse, FakeSession, load, synthetic_workouts

TEMPLATES = load("templates.json")
HISTORY = {"A000000A": load("history_weighted_pullup.json")}


def client(workouts=None, **kw):
    session = FakeSession(workouts=load("workouts.json") if workouts is None else workouts,
                          templates=TEMPLATES, history=HISTORY, **kw)
    return HevyClient("KEY", session=session, sleep=lambda s: None), session


def test_top_set_rules():
    sets = [{"type": "warmup", "weight_kg": 140.0, "reps": 1}, {"type": "normal", "weight_kg": 30.0, "reps": 8},
            {"type": "normal", "weight_kg": 30.0, "reps": 9}]
    assert tools.top_set(sets) is sets[2]                                   # warm-ups never count; a tie -> more reps
    assert tools.top_set([{"type": "normal", "reps": 14}, {"type": "normal", "reps": 9}])["reps"] == 14
    assert tools.top_set([{"type": "normal", "duration_seconds": 60},
                          {"type": "normal", "duration_seconds": 120}])["duration_seconds"] == 120
    assert tools.top_set([{"type": "warmup", "reps": 5}]) is None
    assert tools.top_set([{"set_type": "normal", "weight_kg": 7.5, "reps": 5}])["reps"] == 5    # history entries


def test_fmt_set():
    assert tools.fmt_set({"weight_kg": 120.0, "reps": 1}) == "120 kg x 1"
    assert tools.fmt_set({"reps": 14}) == "14 reps"
    assert tools.fmt_set({"duration_seconds": 120}) == "120 s"
    assert tools.fmt_set({"distance_meters": 400, "duration_seconds": 85, "rpe": 8.5}) == "85 s, 0.4 km @ RPE 8.5"
    assert tools.fmt_set({}) == "nothing logged"


def test_fmt_set_bodyweight_zero_is_no_weight():
    assert tools.fmt_set({"type": "normal", "weight_kg": 0, "reps": 8}) == "8 reps"
    assert tools.fmt_set({"weight_kg": 0.0, "reps": 8}) == "8 reps"


def test_list_sessions_defaults_to_the_last_14_days():
    c, _ = client()
    assert tools.list_sessions(c, today=dt.date(2026, 9, 29)) == (
        "Gym sessions 2026-09-16 to 2026-09-29 (Helsinki time): 1\n"
        "- 2026-09-25 Fri 12:14, 90 min, Morning workout ☀️: Pull Up 14 reps; "
        "Bench Press (Barbell) 102.5 kg x 1; Push Up 41 reps; Dead Hang 120 s")


def test_list_sessions_over_a_range():
    c, _ = client()
    assert tools.list_sessions(c, start="2025-01-01", end="2025-08-31").splitlines() == [
        "Gym sessions 2025-01-01 to 2025-08-31 (Helsinki time): 2",
        "- 2025-08-18 Mon 12:15, 22 min, Upper (Strength focus): Incline Bench Press (Dumbbell) 25 kg x 9; "
        "Pull Up 6 reps; Seated Cable Row - V Grip (Cable) 65 kg x 7; Machine Shoulder Press 35 kg x 10",
        "- 2025-01-25 Sat 17:47, 29 min, Pull - Heavy: Bent Over Row (Barbell) 75 kg x 11; "
        "Lat Pulldown (Cable) 67.5 kg x 5; Shoulder Press (Dumbbell) 15 kg x 3"]


def test_list_sessions_empty_ranges_and_bad_dates():
    c, _ = client()
    assert tools.list_sessions(c, start="2026-10-01", end="2026-10-05") == "No gym sessions from 2026-10-01 to 2026-10-05."
    assert tools.list_sessions(c, start="2026-10-05", end="2026-10-01") == "start (2026-10-05) is after end (2026-10-01)."
    assert tools.list_sessions(c, start="5.10.2026") == "Dates are YYYY-MM-DD; got '5.10.2026'."


def test_list_sessions_stops_paging_once_past_the_window():
    c, session = client(workouts=synthetic_workouts(25))
    got = tools.list_sessions(c, start="2026-09-26", today=dt.date(2026, 9, 28))
    assert got.startswith("Gym sessions 2026-09-26 to 2026-09-28 (Helsinki time): 3")
    assert session.paths() == ["/v1/workouts"]                  # page 1 already ends before Sep 26


def test_list_sessions_reads_every_page_when_not_newest_first():
    c, session = client(workouts=list(reversed(synthetic_workouts(25))))
    got = tools.list_sessions(c, start="2026-09-26", today=dt.date(2026, 9, 28))
    assert got.startswith("Gym sessions 2026-09-26 to 2026-09-28 (Helsinki time): 3")
    assert session.paths() == ["/v1/workouts"] * 3


def test_list_sessions_caps_at_60_lines_with_a_narrow_hint():
    c, _ = client(workouts=synthetic_workouts(70))
    got = tools.list_sessions(c, start="2026-07-01", end="2026-09-28").splitlines()
    assert len(got) == 62
    assert got[0] == "Gym sessions 2026-07-01 to 2026-09-28 (Helsinki time): 70"
    assert len([line for line in got if line.startswith("- ")]) == tools.MAX_SESSIONS == 60
    assert got[-1] == "...and 10 more: narrow the dates."


def test_session_detail():
    c, _ = client()
    assert tools.session_detail(c, "2026-09-25") == (
        "2026-09-25 Fri 12:14-13:44, 90 min: Morning workout ☀️\n"
        "  Pull Up: 6 reps (warm-up); 14 reps\n"
        "  Bench Press (Barbell): 42.5 kg x 8 (warm-up); 67.5 kg x 4 (warm-up); 77.5 kg x 2 (warm-up); "
        "85 kg x 1 (warm-up); 92.5 kg x 1 (warm-up); 102.5 kg x 1\n"
        "  Push Up: 41 reps; 9 reps; 11 reps; 10 reps; 5 reps\n"
        "  Dead Hang: 120 s")


def test_session_detail_notes_empty_days_and_missing_date():
    c, _ = client()
    assert ("  Seated Cable Row - V Grip (Cable) [Deficit pendlay row]: 65 kg x 7; 65 kg x 7"
            in tools.session_detail(c, "2025-08-18"))
    assert tools.session_detail(c, "2026-09-26") == "No gym session on 2026-09-26."
    assert tools.session_detail(c, "") == "Give the session's date as YYYY-MM-DD."


def test_lift_history_resolves_part_of_a_name():
    c, session = client()
    assert tools.lift_history(c, "weighted") == (
        "Pull Up (Weighted), all history: 2 sessions (Helsinki time)\n"
        "- 2026-09-13 Sun: top 6.5 kg x 5 | 6.5 kg x 5; 6.5 kg x 5; 6.5 kg x 5; 6.5 kg x 5; 6.5 kg x 5\n"
        "- 2026-09-05 Sat: top 6.5 kg x 7 | 6.5 kg x 7; 6.5 kg x 7; 6.5 kg x 6; 6.5 kg x 4; 6.5 kg x 4")
    assert session.paths() == ["/v1/exercise_templates", "/v1/exercise_history/A000000A"]


def test_lift_history_date_filter():
    c, session = client()
    got = tools.lift_history(c, "Pull Up (Weighted)", start="2026-09-06")
    assert got.splitlines()[0] == "Pull Up (Weighted), 2026-09-06 to today: 1 session (Helsinki time)"
    assert session.calls[-1][1] == {"start_date": "2026-09-05T21:00:00Z"}


def test_lift_history_exact_name_wins_and_ambiguity_is_listed():
    c, _ = client()
    assert tools.lift_history(c, "pull up") == "No Pull Up sets logged (all history)."
    assert tools.lift_history(c, "deadlift") == (
        "'deadlift' matches 3 exercises; say which: Deadlift (Barbell); Romanian Deadlift (Barbell); Trap Bar Deadlift")
    assert tools.lift_history(c, "zercher") == "No Hevy exercise matches 'zercher'. Try find_exercise."


def test_find_exercise_marks_what_is_in_the_log(tmp_path):
    gym = tmp_path / "gym.csv"
    gym.write_text('"title","exercise_title"\n"A","Pull Up"\n"B","Pull Up (Weighted)"\n', encoding="utf-8")
    c, _ = client()
    assert tools.find_exercise(c, "pull", gym) == (
        "Exercises matching 'pull' ([used] = in your log):\n"
        "- Pull Up [used]\n- Pull Up (Weighted) [used]\n- Hammer-Grip Pull-Up (custom)\n- Lat Pulldown (Cable)")
    assert tools.find_exercise(c, "trap bar", gym) == (
        "Exercises matching 'trap bar' ([used] = in your log):\n- Trap Bar Deadlift")
    assert tools.find_exercise(c, "zercher", gym) == "No Hevy exercise contains 'zercher'."
    assert tools.find_exercise(c, "  ", gym) == "Give part of an exercise name, e.g. 'trap bar'."


def test_find_exercise_without_gym_csv_and_the_cap(tmp_path):
    c, _ = client()
    assert tools.find_exercise(c, "squat", tmp_path / "missing.csv") == (
        "Exercises matching 'squat' ([used] = in your log; data/gym.csv not found, so nothing is marked):\n"
        "- Squat (Barbell)")
    many = [{"id": f"C{i}", "title": f"Curl {i:02d}", "is_custom": False} for i in range(30)]
    big = HevyClient("KEY", session=FakeSession(templates=many), sleep=lambda s: None)
    lines = tools.find_exercise(big, "curl", tmp_path / "missing.csv").splitlines()
    assert len(lines) == 27 and lines[-1] == "...and 5 more: be more specific."


def test_a_hevy_problem_is_the_answer_and_never_shows_the_key():
    c = HevyClient("SECRET-KEY-123", session=FakeSession(script=[FakeResponse(401, {})]), sleep=lambda s: None)
    got = tools.list_sessions(c, today=dt.date(2026, 9, 29))
    assert got.startswith("Hevy rejected the key") and "SECRET-KEY-123" not in got


def _ohp_workout(day: dt.date, sets: list[tuple]) -> dict:
    return {"id": f"o{day}", "title": "Upper", "description": None, "start_time": f"{day}T08:00:00Z",
            "end_time": f"{day}T09:00:00Z",
            "exercises": [{"index": 0, "title": "Overhead Press (Barbell)", "notes": None,
                           "exercise_template_id": "OHP", "superset_id": None,
                           "sets": [{"index": i, "type": "normal", "weight_kg": kg, "reps": reps, "rpe": rpe,
                                     "distance_meters": None, "duration_seconds": None, "custom_metric": None}
                                    for i, (kg, reps, rpe) in enumerate(sets)]}]}


def test_next_load_reads_live_hevy_against_the_plan(tmp_path):
    import json
    import pathlib
    import shutil
    shutil.copy(pathlib.Path(__file__).resolve().parents[1] / "training-plan-2026-27.json", tmp_path)
    live = [_ohp_workout(dt.date(2026, 11, 1), [(52.5, 5, 7), (52.5, 5, 7.5), (52.5, 5, 8), (52.5, 5, 8)]),
            _ohp_workout(dt.date(2026, 10, 24), [(60, 5, None)])]
    c, _ = client(live)
    out = tools.next_load(c, tmp_path, "ohp", dt.date(2026, 11, 9))
    assert out.splitlines() == [
        "Next loads by plan section 6 (Hevy through 2026-11-01, no Garmin data, so no ease-off check):",
        "- 2026-11-15 Sun, Strict OHP 4×3–5: 55 kg · +2.5 kg: every set at the top at "
        "RPE ≤9 (from 52.5 kg × 5,5,5,5 @ 7–8 · Sun 1 Nov)"]
    assert "No planned lift matches 'curtsy'" in tools.next_load(c, tmp_path, "curtsy", dt.date(2026, 11, 9))
    (tmp_path / "training-plan-2026-27.json").unlink()
    assert tools.next_load(c, tmp_path, None, dt.date(2026, 11, 9)).startswith("The plan could not be read")
