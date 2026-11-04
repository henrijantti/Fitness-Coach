"""tools.py: the five read-only questions the Hevy MCP answers, as plain functions.

Each takes a client (hevy.client.HevyClient, or a fake in tests) and returns compact text in Helsinki
time. A Hevy problem or a bad argument comes back as a one-line message, never as an exception.
"""
from __future__ import annotations

import csv
import datetime as dt
import functools
import pathlib

from hevy.client import HevyError
from hevy.rows import COLUMNS, HELSINKI, local, num, parse_utc, workout_rows

DEFAULT_DAYS = 14
MAX_CANDIDATES = 15
MAX_MATCHES = 25
MAX_SESSIONS = 60
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SET_LABELS = {"warmup": " (warm-up)", "dropset": " (drop set)", "failure": " (failure)"}


class InputError(Exception):
    """A tool argument that cannot be used, worded as the answer."""


def _answer(fn):
    """Turn a Hevy problem or a bad argument into the tool's answer."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (HevyError, InputError) as e:
            return str(e)
    return wrapper


def _day(text: str | None, default: dt.date | None) -> dt.date | None:
    if not text:
        return default
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise InputError(f"Dates are YYYY-MM-DD; got {text!r}.") from None


def _midnight(day: dt.date) -> dt.datetime:
    """The start of a Helsinki day, as an aware datetime."""
    return dt.datetime.combine(day, dt.time(0), HELSINKI)


def _today() -> dt.date:
    return dt.datetime.now(HELSINKI).date()


def _when(moment: dt.datetime) -> str:
    return f"{moment:%Y-%m-%d} {DAYS[moment.weekday()]} {moment:%H:%M}"


def _minutes(workout: dict) -> int:
    return round((parse_utc(workout["end_time"]) - parse_utc(workout["start_time"])).total_seconds() / 60)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _kind(s: dict) -> str:
    """Workout sets say 'type'; exercise-history entries say 'set_type'."""
    return s.get("type") or s.get("set_type") or "normal"


def fmt_set(s: dict) -> str:
    """'120 kg x 1', '14 reps', '120 s', '0.4 km', plus ' @ RPE 8' when an RPE was logged."""
    weight, reps, secs, meters, rpe = (s.get(k) for k in
                                       ("weight_kg", "reps", "duration_seconds", "distance_meters", "rpe"))
    weight = weight or None
    parts = []
    if weight is not None and reps is not None:
        parts.append(f"{num(weight)} kg x {num(reps)}")
    elif weight is not None:
        parts.append(f"{num(weight)} kg")
    elif reps is not None:
        parts.append(f"{num(reps)} reps")
    if secs is not None:
        parts.append(f"{num(secs)} s")
    if meters is not None:
        parts.append(f"{num(meters / 1000)} km")
    text = ", ".join(parts) or "nothing logged"
    return text + (f" @ RPE {num(rpe)}" if rpe is not None else "")


def top_set(sets: list[dict]) -> dict | None:
    """The heaviest set that is not a warm-up; a tie goes to more reps. With no weight, the most reps;
    for timed sets, the longest duration. None when every set is a warm-up."""
    work = [s for s in sets if _kind(s) != "warmup"]
    if not work:
        return None
    return max(work, key=lambda s: (s.get("weight_kg") or 0, s.get("reps") or 0, s.get("duration_seconds") or 0))


def _workouts_between(client, first: dt.date, last: dt.date) -> list[dict]:
    """Workouts whose Helsinki start date lies in [first, last], newest first. Paging stops after a page
    that is newest-first and ends before `first`; in any other order every page is read."""
    found = []
    for batch in client.workout_pages():
        starts = [parse_utc(w["start_time"]) for w in batch]
        found += [w for w in batch if first <= local(w["start_time"]).date() <= last]
        newest_first = all(a >= b for a, b in zip(starts, starts[1:]))
        if starts and newest_first and starts[-1] < _midnight(first):
            break
    return sorted(found, key=lambda w: parse_utc(w["start_time"]), reverse=True)


def _range(start: str | None, end: str | None, today: dt.date | None) -> tuple[dt.date, dt.date]:
    last = _day(end, today or _today())
    first = _day(start, last - dt.timedelta(days=DEFAULT_DAYS - 1))
    if first > last:
        raise InputError(f"start ({first}) is after end ({last}).")
    return first, last


def _by_index(items) -> list[dict]:
    return sorted(items or [], key=lambda x: x.get("index") or 0)


@_answer
def list_sessions(client, start: str | None = None, end: str | None = None,
                  today: dt.date | None = None) -> str:
    """One line per gym session in [start, end] (default: the last 14 days), with each exercise's top set."""
    first, last = _range(start, end, today)
    sessions = _workouts_between(client, first, last)
    if not sessions:
        return f"No gym sessions from {first} to {last}."
    lines = [f"Gym sessions {first} to {last} (Helsinki time): {len(sessions)}"]
    for w in sessions[:MAX_SESSIONS]:
        tops = []
        for ex in _by_index(w.get("exercises")):
            best = top_set(ex.get("sets") or [])
            tops.append(f"{ex.get('title')} {fmt_set(best) if best else 'warm-up only'}")
        lines.append(f"- {_when(local(w['start_time']))}, {_minutes(w)} min, "
                     f"{w.get('title') or 'Untitled'}: " + "; ".join(tops))
    if len(sessions) > MAX_SESSIONS:
        lines.append(f"...and {len(sessions) - MAX_SESSIONS} more: narrow the dates.")
    return "\n".join(lines)


@_answer
def session_detail(client, date: str) -> str:
    """Every set of the gym session(s) on one Helsinki date."""
    day = _day(date, None)
    if day is None:
        raise InputError("Give the session's date as YYYY-MM-DD.")
    sessions = _workouts_between(client, day, day)
    if not sessions:
        return f"No gym session on {day}."
    blocks = []
    for w in reversed(sessions):
        start, end = local(w["start_time"]), local(w["end_time"])
        lines = [f"{_when(start)}-{end:%H:%M}, {_minutes(w)} min: {w.get('title') or 'Untitled'}"]
        if w.get("description"):
            lines.append(f"  Note: {w['description']}")
        for ex in _by_index(w.get("exercises")):
            note = f" [{ex['notes']}]" if ex.get("notes") else ""
            sets = "; ".join(fmt_set(s) + SET_LABELS.get(_kind(s), "") for s in _by_index(ex.get("sets")))
            lines.append(f"  {ex.get('title')}{note}: {sets}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _resolve(templates: list[dict], name: str) -> list[dict]:
    """An exact name (any case) wins; otherwise every exercise whose name contains `name`."""
    want = name.strip().casefold()
    exact = [t for t in templates if (t.get("title") or "").casefold() == want]
    if exact:
        return exact[:1]
    return sorted((t for t in templates if want and want in (t.get("title") or "").casefold()),
                  key=lambda t: t["title"])


@_answer
def lift_history(client, exercise: str, start: str | None = None, end: str | None = None) -> str:
    """One lift across sessions, newest first: date, top set and working sets."""
    first, last = _day(start, None), _day(end, None)
    if first and last and first > last:
        raise InputError(f"start ({first}) is after end ({last}).")
    matches = _resolve(client.exercise_templates(), exercise or "")
    if not matches:
        return f"No Hevy exercise matches {exercise!r}. Try find_exercise."
    if len(matches) > 1:
        names = [t["title"] for t in matches]
        more = f" (and {len(names) - MAX_CANDIDATES} more)" if len(names) > MAX_CANDIDATES else ""
        return (f"{exercise!r} matches {len(names)} exercises; say which: "
                + "; ".join(names[:MAX_CANDIDATES]) + more)
    title = matches[0]["title"]
    entries = client.exercise_history(matches[0]["id"],
                                      _midnight(first) if first else None,
                                      _midnight(last + dt.timedelta(days=1)) if last else None)
    span = f"{first or 'the start'} to {last or 'today'}" if (first or last) else "all history"
    sessions: dict[str, list[dict]] = {}
    for e in entries:
        day = local(e["workout_start_time"]).date()
        if (first and day < first) or (last and day > last):
            continue
        sessions.setdefault(e["workout_id"], []).append(e)
    if not sessions:
        return f"No {title} sets logged ({span})."
    ordered = sorted(sessions.values(), key=lambda es: parse_utc(es[0]["workout_start_time"]), reverse=True)
    lines = [f"{title}, {span}: {_count(len(ordered), 'session')} (Helsinki time)"]
    for es in ordered:
        when = local(es[0]["workout_start_time"])
        best = top_set(es)
        working = "; ".join(fmt_set(e) for e in es if _kind(e) != "warmup")
        lines.append(f"- {when:%Y-%m-%d} {DAYS[when.weekday()]}: top "
                     f"{fmt_set(best) if best else 'warm-up only'} | {working}")
    return "\n".join(lines)


def _used_titles(gym_csv: pathlib.Path) -> set[str] | None:
    try:
        with open(gym_csv, encoding="utf-8", newline="") as f:
            return {row["exercise_title"] for row in csv.DictReader(f)}
    except FileNotFoundError:
        return None


@_answer
def find_exercise(client, text: str, gym_csv: pathlib.Path) -> str:
    """Hevy exercise names containing `text`, the ones in the athlete's log first and marked [used]."""
    want = (text or "").strip().casefold()
    if not want:
        raise InputError("Give part of an exercise name, e.g. 'trap bar'.")
    used = _used_titles(gym_csv)
    marked = used or set()
    hits = [t for t in client.exercise_templates() if want in (t.get("title") or "").casefold()]
    if not hits:
        return f"No Hevy exercise contains {text!r}."
    hits.sort(key=lambda t: (t["title"] not in marked, t["title"]))
    missing = "" if used is not None else "; data/gym.csv not found, so nothing is marked"
    lines = [f"Exercises matching {text!r} ([used] = in your log{missing}):"]
    for t in hits[:MAX_MATCHES]:
        lines.append(f"- {t['title']}" + (" (custom)" if t.get("is_custom") else "")
                     + (" [used]" if t["title"] in marked else ""))
    if len(hits) > MAX_MATCHES:
        lines.append(f"...and {len(hits) - MAX_MATCHES} more: be more specific.")
    return "\n".join(lines)


def _gym_sets(workouts: list[dict]):
    """Live workouts as kunto.gym.Set rows, the way data/gym.csv would hold them once pulled."""
    from kunto import gym
    out = []
    for w in workouts:
        day = local(w["start_time"]).date()
        for row in workout_rows(w):
            r = dict(zip(COLUMNS, row))
            out.append(gym.Set(day, r["exercise_title"], r["set_type"],
                               None if r["weight_kg"] is None else float(r["weight_kg"]), r["reps"],
                               None if r["rpe"] is None else float(r["rpe"])))
    return out


@_answer
def next_load(client, root: pathlib.Path, exercise: str | None = None, today: dt.date | None = None) -> str:
    """Each planned lift's load for its next session by plan section 6's load rule (kunto/progression.py, the
    same rule as Kunto's cards and the Sunday close), from live Hevy, so a session logged minutes ago counts."""
    from kunto import data as kdata
    from kunto import plan as kplan
    from kunto import progression
    day = today or _today()
    try:
        plan = kplan.load_plan(pathlib.Path(root) / "training-plan-2026-27.json")
    except kplan.PlanError as e:
        raise InputError(f"The plan could not be read: {e}") from None
    season = dt.date.fromisoformat(plan["weeks"][0]["start"])
    sets = _gym_sets(_workouts_between(client, season, day))
    try:                                  # the ease-off signs; without the Garmin CSVs the loads still answer
        daily = kdata.as_of(kdata.load_garmin(pathlib.Path(root)), day).daily
    except Exception:
        daily = {}
    want = (exercise or "").strip().casefold()
    found = [n for d, by_key in sorted(progression.upcoming(plan, sets, day, daily).items())
             for k, n in by_key.items() if want in k]
    hevy_through = max((s.date for s in sets), default=None)
    garmin = f"Garmin through {max(daily):%Y-%m-%d}" if daily else "no Garmin data, so no ease-off check"
    hevy = f"Hevy through {hevy_through:%Y-%m-%d}" if hevy_through else "no Hevy session this season"
    head = f"Next loads by plan section 6 ({hevy}, {garmin}):"
    if not found:
        return f"No planned lift matches {exercise!r} in the next 4 weeks." if want else \
            "No planned lift with a load in the next 4 weeks."
    lines = [head]
    for n in found:
        load = n.text or "no load yet"
        basis = f" (from {n.basis})" if n.basis else ""
        ease = f" · {n.ease}" if n.ease else ""
        lines.append(f"- {n.day:%Y-%m-%d} {DAYS[n.day.weekday()]}, {progression.label(n.key)} {n.rx}: {load} · "
                     f"{n.why}{basis}{ease}")
    return "\n".join(lines)
