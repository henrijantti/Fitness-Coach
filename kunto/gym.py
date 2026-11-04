"""The gym log for build_history's Key numbers: data/gym.csv (Hevy's export layout, written by hevy/pull_hevy.py).

A set is dated by its workout's start_time date. The clock time is never used: workouts imported from Motra
(dated on or before Sun Sep 20, 2026) read 2-3 h late (decision-log 2026-09-29); their dates are right.
Working set = set_type normal or failure.
"""
from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import io
import pathlib

from hevy.rows import COLUMNS, MONTHS
from kunto.data import DataError

WORKING = ("normal", "failure")


@dataclasses.dataclass(frozen=True)
class Set:
    date: dt.date
    exercise: str
    set_type: str
    weight: float | None
    reps: int | None
    rpe: float | None = None


@dataclasses.dataclass(frozen=True)
class Lift:
    key: str
    name: str
    exercise: str               # the exact Hevy exercise title
    mode: str                   # "reps" (bodyweight reps), "added" (added kg on body weight), "load" (bar kg)


LIFTS = (
    Lift("PU", "Strict pull-ups", "Pull Up", "reps"),
    Lift("WPU", "Weighted pull-up", "Pull Up (Weighted)", "added"),
    Lift("OHP", "Strict OHP", "Overhead Press (Barbell)", "load"),
    Lift("Sq", "Back squat", "Squat (Barbell)", "load"),
    Lift("TB", "Trap bar", "Deadlift (Trap bar)", "load"),
    Lift("Bn", "Bench (monitor)", "Bench Press (Barbell)", "load"),
)


@dataclasses.dataclass(frozen=True)
class Marker:
    key: str                    # its label in Key numbers
    name: str
    exercise: str               # the custom Hevy exercise it is logged in: one set per attempt, reps = the result
    unit: str


# The weekly athleticism check (plan section 2, decision-log 2026-10-25). Hevy holds no jump height, distance or
# watts for a set, so each marker is a custom exercise whose reps carry the number. Titles match ignoring case.
TEST_PREFIX = "test "
MARKERS = (
    Marker("CMJ", "Jump height", "Test Jump Height (cm)", "cm"),
    Marker("BJ", "Broad jump", "Test Broad Jump (cm)", "cm"),
    Marker("Ski", "SkiErg peak", "Test SkiErg Peak (W)", "W"),
)


def _title(name: str) -> str:
    return " ".join(name.lower().split())


def marker_days(sets: list[Set], m: Marker, start: dt.date, end: dt.date) -> list[tuple[dt.date, tuple[int, ...]]]:
    """Each day's attempts at one marker from start to end, oldest first, in logged order."""
    by_day: dict[dt.date, list[int]] = {}
    for s in sets:
        if _title(s.exercise) == _title(m.exercise) and s.set_type in WORKING and s.reps and start <= s.date <= end:
            by_day.setdefault(s.date, []).append(s.reps)
    return [(d, tuple(by_day[d])) for d in sorted(by_day)]


def fmt_marker(value: float, m: Marker) -> str:
    """'46 cm' · '2.31 m' (the broad jump, as the benchmarks read) · '590 W'."""
    return f"{value / 100:.2f} m" if m.key == "BJ" else f"{value:g} {m.unit}"


def _date(stamp: str) -> dt.date:
    """'25 Sep 2026, 12:14' -> 2026-09-25 (hevy.rows writes this layout)."""
    day, mon, year = stamp.split(",")[0].split()
    return dt.date(int(year), MONTHS.index(mon) + 1, int(day))


def read_rows(root) -> list[tuple[int, dict]] | None:
    """(line number, row keyed by COLUMNS) for every set in data/gym.csv, file order. None when the file is
    missing; DataError when it is cut off, has another header or a row of the wrong width."""
    p = pathlib.Path(root) / "data" / "gym.csv"
    if not p.exists():
        return None
    content = p.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        raise DataError(f"gym.csv line {content.count(chr(10)) + 1}: no line ending, the file looks cut off")
    rows = list(csv.reader(io.StringIO(content)))
    if not rows or rows[0] != COLUMNS:
        raise DataError("gym.csv: header differs from Hevy's export layout")
    out = []
    for n, r in enumerate(rows[1:], start=2):
        if len(r) != len(COLUMNS):
            raise DataError(f"gym.csv line {n}: expected {len(COLUMNS)} fields, found {len(r)}")
        out.append((n, dict(zip(COLUMNS, r))))
    return out


def number(row: dict, n: int, column: str, conv):
    """A numeric cell: None when empty; DataError naming the line when it is not a number."""
    v = row[column].strip()
    try:
        return conv(v) if v else None
    except ValueError:
        raise DataError(f"gym.csv line {n}: {column}={v!r} is not a number") from None


def load_gym(root) -> list[Set] | None:
    """Every set in data/gym.csv, file order. None when the file is missing; DataError when it is malformed."""
    rows = read_rows(root)
    if rows is None:
        return None
    out = []
    for n, r in rows:
        try:
            d = _date(r["start_time"])
        except (ValueError, IndexError):
            raise DataError(f"gym.csv line {n}: start_time {r['start_time']!r} is not 'D Mon YYYY, HH:MM'") from None
        out.append(Set(d, r["exercise_title"], r["set_type"], number(r, n, "weight_kg", float),
                       number(r, n, "reps", int), number(r, n, "rpe", float)))
    return out


# What an exercise trains, read from its Hevy title (lower case, first list that matches wins). Core work,
# carries, ergs and anything unknown do not count either way.
NO_REGION = ("ab wheel", "crunch", "sit-up", "sit up", "plank", "pallof", "copenhagen", "knee raise", "leg raise",
             "toes to bar", "carry", "farmer", "throw", "slam", "back extension", "erg", "rowing", "treadmill",
             "running", "cycling", "bike", "clean", "snatch", "stretch", "mobility")
LEGS = ("squat", "deadlift", "lunge", "leg press", "leg extension", "leg curl", "calf", "hip thrust", "hip abduction",
        "hip adduction", "glute", "nordic", "hamstring", "step up", "step-up", "sled", "jump", "bound",
        "good morning", "pull through")
UPPER = ("press", "row", "pull", "chin", "curl", "fly", "raise", "dip", "push", "tricep", "skull", "shrug", "hang",
         "pec", "delt", "kickback")
LEGS_FROM, UPPER_TO = 0.6, 0.25         # share of a day's counted working sets that are leg sets


def region(exercise: str) -> str | None:
    """'legs' or 'upper' for a Hevy exercise title; None when it counts for neither."""
    name = exercise.lower()
    if name.startswith(TEST_PREFIX) or any(k in name for k in NO_REGION):     # a test measures, it trains neither
        return None
    if any(k in name for k in LEGS):
        return "legs"
    return "upper" if any(k in name for k in UPPER) else None


def day_focus(sets: list[Set]) -> dict[dt.date, str]:
    """What each gym day trained, from its working sets: 'legs' (60 % or more leg sets), 'upper' (25 % or
    fewer) or 'full' (in between: a mixed session). A day with no leg or upper working sets is left out: its focus is unknown."""
    counts: dict[dt.date, list[int]] = {}
    for s in sets:
        r = region(s.exercise) if s.set_type in WORKING else None
        if r:
            counts.setdefault(s.date, [0, 0])[0 if r == "legs" else 1] += 1
    out = {}
    for d, (legs, upper) in counts.items():
        share = legs / (legs + upper)
        out[d] = "legs" if share >= LEGS_FROM else "upper" if share <= UPPER_TO else "full"
    return out


def load_day_focus(root, today: dt.date) -> dict[dt.date, str]:
    """day_focus of data/gym.csv up to today; {} when the file is missing or unreadable, so the page and its
    ticks never depend on a good Hevy pull."""
    try:
        sets = load_gym(root)
    except (DataError, OSError, ValueError):
        return {}
    return day_focus([s for s in sets or [] if s.date <= today])


def load_sets_or_none(root) -> list[Set] | None:
    """load_gym, or None when the file is missing or unreadable: the cards then show no last sets."""
    try:
        return load_gym(root)
    except (DataError, OSError, ValueError):
        return None


def working(sets: list[Set], lift: Lift, start: dt.date, end: dt.date) -> list[Set]:
    return [s for s in sets if s.exercise == lift.exercise and s.set_type in WORKING and start <= s.date <= end]


def _added(s: Set) -> float:
    return s.weight or 0.0


def top_set(sets: list[Set], lift: Lift, start: dt.date, end: dt.date) -> Set | None:
    """The heaviest working set (PU: the most reps); ties go to more reps, then the earlier date."""
    cands = [s for s in working(sets, lift, start, end) if s.reps]
    if lift.mode == "load":
        cands = [s for s in cands if s.weight is not None]
    if not cands:
        return None
    key = (lambda s: (s.reps, -s.date.toordinal())) if lift.mode == "reps" else \
        (lambda s: (_added(s), s.reps, -s.date.toordinal()))
    return max(cands, key=key)


def kg(x: float) -> str:
    """100.0 -> '100'; 102.5 -> '102.5'."""
    return f"{x:g}"


def fmt_set(s: Set, lift: Lift) -> str:
    """'14' (PU), '+15×5' (WPU), '102.5×5'."""
    if lift.mode == "reps":
        return str(s.reps)
    if lift.mode == "added":
        return f"+{kg(_added(s))}×{s.reps}"
    return f"{kg(s.weight)}×{s.reps}"
