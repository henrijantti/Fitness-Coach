"""Tests for hevy/rows.py: Hevy's API JSON into the exact layout of Hevy's own CSV export."""
import csv
import io

from hevy import rows
from hevy_fake import FIXTURES, load


def test_export_time_is_helsinki_and_not_zero_padded():
    assert rows.export_time("2026-09-25T09:14:00Z") == "25 Sep 2026, 12:14"          # summer, UTC+3
    assert rows.export_time("2025-01-25T15:47:00Z") == "25 Jan 2025, 17:47"          # winter, UTC+2
    assert rows.export_time("2026-09-09T17:30:00Z") == "9 Sep 2026, 20:30"           # single-digit day
    assert rows.export_time("2026-10-24T21:30:00+00:00") == "25 Oct 2026, 00:30"     # crosses midnight


def test_num_matches_the_export_cells():
    assert rows.num(120.0) == 120 and isinstance(rows.num(120.0), int)
    assert rows.num(87.5) == 87.5
    assert rows.num(None) is None
    assert rows.num(6) == 6


def test_set_index_restarts_per_exercise_and_distance_is_km():
    w = {"title": "T", "description": None, "start_time": "2026-10-01T05:00:00Z", "end_time": "2026-10-01T06:00:00Z",
         "exercises": [
             {"index": 1, "title": "Run", "notes": None, "superset_id": 0,
              "sets": [{"index": 3, "type": "normal", "distance_meters": 400, "duration_seconds": 85, "rpe": 8.5}]},
             {"index": 0, "title": "Squat (Barbell)", "notes": "belt", "superset_id": None,
              "sets": [{"index": 2, "type": "normal", "weight_kg": 100.0, "reps": 5},
                       {"index": 1, "type": "warmup", "weight_kg": 60.0, "reps": 5}]}]}
    got = rows.workout_rows(w)
    assert [r[4] for r in got] == ["Squat (Barbell)", "Squat (Barbell)", "Run"]
    assert [r[7] for r in got] == [0, 1, 0]
    assert got[0][8:11] == ["warmup", 60, 5]
    assert got[0][3] == "" and got[0][6] == "belt"
    assert got[2][5] == 0 and got[2][11] == 0.4 and got[2][12] == 85 and got[2][13] == 8.5


def test_all_rows_are_newest_first():
    older = {"title": "Old", "start_time": "2025-01-01T10:00:00Z", "end_time": "2025-01-01T11:00:00Z",
             "exercises": [{"index": 0, "title": "A", "sets": [{"index": 0, "type": "normal", "reps": 1}]}]}
    newer = dict(older, title="New", start_time="2026-01-01T10:00:00Z", end_time="2026-01-01T11:00:00Z")
    assert [r[0] for r in rows.all_rows([older, newer])] == ["New", "Old"]


def test_csv_quoting_is_hevys():
    text = rows.to_csv([["T", "1 Oct 2026, 08:00", "1 Oct 2026, 09:00", "", "A", None, "", 0, "normal",
                         7.5, 5, None, None, None]])
    assert text.splitlines()[1] == '"T","1 Oct 2026, 08:00","1 Oct 2026, 09:00","","A",,"",0,"normal",7.5,5,,,'
    assert next(csv.reader(io.StringIO(text))) == rows.COLUMNS
    assert "\r" not in text


def test_bodyweight_zero_weight_is_no_weight():
    """The API sends weight_kg: 0 for a bodyweight set; Hevy's own export leaves that cell empty."""
    w = {"title": "T", "description": None, "start_time": "2026-10-01T05:00:00Z", "end_time": "2026-10-01T06:00:00Z",
         "exercises": [{"index": 0, "title": "Pull Up", "notes": None, "superset_id": None,
                        "sets": [{"index": 0, "type": "normal", "weight_kg": 0.0, "reps": 8}]}]}
    got = rows.workout_rows(w)
    assert got[0][9] is None
    assert rows.to_csv(got).splitlines()[1].endswith(',"normal",,8,,,')


def test_matches_a_real_export_line_for_line():
    """Four workouts adapted from a Sep 28, 2026 Hevy export (loads altered): a session logged in Hevy (summer), a single-digit
    date, exercise notes, and a winter date."""
    expected = (FIXTURES / "export_slice.csv").read_text(encoding="utf-8").splitlines()
    assert rows.to_csv(rows.all_rows(load("workouts.json"))).splitlines() == expected
