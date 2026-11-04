"""rows.py: Hevy workouts (API JSON) as rows in the layout of Hevy's own CSV export.

The API sends UTC; the export shows Helsinki time as "25 Sep 2026, 12:14" (day not zero-padded).
Strings are quoted, numbers bare and missing values empty: csv.QUOTE_STRINGS (Python 3.12+).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from zoneinfo import ZoneInfo

HELSINKI = ZoneInfo("Europe/Helsinki")
COLUMNS = ["title", "start_time", "end_time", "description", "exercise_title", "superset_id",
           "exercise_notes", "set_index", "set_type", "weight_kg", "reps", "distance_km",
           "duration_seconds", "rpe"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse_utc(stamp: str) -> dt.datetime:
    """An API timestamp (ISO 8601) as an aware datetime; a stamp without a zone is UTC."""
    moment = dt.datetime.fromisoformat(stamp)
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def local(stamp: str) -> dt.datetime:
    """An API timestamp in Helsinki time."""
    return parse_utc(stamp).astimezone(HELSINKI)


def export_time(stamp: str) -> str:
    """Hevy's export format, independent of the PC's locale: '9 Sep 2026, 20:30'."""
    t = local(stamp)
    return f"{t.day} {MONTHS[t.month - 1]} {t.year}, {t:%H:%M}"


def num(value):
    """None stays None; a whole float becomes an int (120.0 -> 120), like the export's cells."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def workout_rows(workout: dict) -> list[list]:
    """One row per set. set_index counts from 0 within each exercise (the API's index runs across the workout)."""
    head = [workout.get("title") or "", export_time(workout["start_time"]),
            export_time(workout["end_time"]), workout.get("description") or ""]
    rows = []
    for ex in sorted(workout.get("exercises") or [], key=lambda e: e.get("index") or 0):
        sets = sorted(ex.get("sets") or [], key=lambda s: s.get("index") or 0)
        for i, s in enumerate(sets):
            meters = s.get("distance_meters")
            rows.append(head + [
                ex.get("title") or "", num(ex.get("superset_id")), ex.get("notes") or "", i,
                s.get("type") or "normal", num(s.get("weight_kg") or None), num(s.get("reps")),
                num(meters / 1000) if meters is not None else None,
                num(s.get("duration_seconds")), num(s.get("rpe")),
            ])
    return rows


def all_rows(workouts: list[dict]) -> list[list]:
    """Every set of every workout, newest workout first."""
    newest_first = sorted(workouts, key=lambda w: parse_utc(w["start_time"]), reverse=True)
    return [row for w in newest_first for row in workout_rows(w)]


def to_csv(rows: list[list]) -> str:
    """Header plus rows with LF line ends (the repo's convention; the values match Hevy's CRLF file)."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_STRINGS, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return buf.getvalue()
