"""Gym tab view model: every Hevy workout in data/gym.csv, newest first, for the tab's three views
(Log, Calendar, By exercise).

A workout shows its date and its length, never its clock time: workouts imported from Motra read 2-3 h
late (kunto/gym.py). Working set = set_type normal or failure, as in the weekly log.
A missing, malformed or empty gym.csv gives {"available": False, "reason": ...} and the page still builds:
a bad Hevy pull must never stop the daily refresh. Free text typed into Hevy that carries medical text is
dropped for the same reason (the page refuses it, kunto/render.py).
"""
from __future__ import annotations

import datetime as dt
import itertools
import pathlib

from hevy.rows import MONTHS
from kunto import fmt, render
from kunto.data import DataError
from kunto.gym import WORKING, kg, number, read_rows

MAX_MINUTES = 240            # a longer "workout" is a timer left running: its length is not shown
CHART_FROM = 8               # sessions before an exercise gets a chart
CHART_LAST = 60              # the chart shows this many sessions at most
MEASURES = ("kg", "r", "s")  # what a top set is measured in: load, else reps, else seconds held
UNIT_WORD = {"kg": "kg", "r": "reps", "s": "s"}
OFF_LABEL = {"warmup": "warm-up", "dropset": "drop set"}


def _text(value: str, fallback: str = "") -> str:
    """Free text from Hevy, or the fallback when it is empty or carries medical text."""
    value = (value or "").strip()
    return fallback if not value or render.medical_hits(value) else value


def _count(n: int, word: str) -> str:
    """1 session · 2 sessions · 0 sets"""
    return f"{n} {word}" + ("" if n == 1 else "s")


def _stamp(row: dict, n: int, column: str) -> dt.datetime:
    """'25 Sep 2026, 12:14' -> datetime; DataError naming the line otherwise."""
    try:
        date, clock = row[column].split(", ")
        day, mon, year = date.split()
        hh, mm = clock.split(":")
        return dt.datetime(int(year), MONTHS.index(mon) + 1, int(day), int(hh), int(mm))
    except ValueError:
        raise DataError(f"gym.csv line {n}: {column} {row[column]!r} is not 'D Mon YYYY, HH:MM'") from None


def load_workouts(root) -> list[dict] | None:
    """Every workout in data/gym.csv, oldest first, with its exercises and sets. None when the file is
    missing; DataError when it is malformed."""
    rows = read_rows(root)
    if rows is None:
        return None
    out = []
    for _, group in itertools.groupby(rows, key=lambda x: (x[1]["title"], x[1]["start_time"], x[1]["end_time"])):
        group = list(group)
        line, first = group[0]
        start, end = _stamp(first, line, "start_time"), _stamp(first, line, "end_time")
        minutes = round((end - start).total_seconds() / 60)
        exercises: list[dict] = []
        for n, r in group:
            name = _text(r["exercise_title"], "Exercise")
            if not exercises or exercises[-1]["name"] != name:
                exercises.append({"name": name, "note": _text(r["exercise_notes"]), "sets": []})
            exercises[-1]["sets"].append({       # a 0 kg, 0 s or 0 km cell says nothing: treated as empty
                "type": r["set_type"], "kg": number(r, n, "weight_kg", float) or None,
                "r": number(r, n, "reps", int), "s": number(r, n, "duration_seconds", float) or None,
                "km": number(r, n, "distance_km", float) or None, "rpe": number(r, n, "rpe", float)})
        out.append({"date": start.date(), "start": start, "title": _text(first["title"], "Workout"),
                    "minutes": minutes if 0 < minutes <= MAX_MINUTES else None,
                    "note": _text(first["description"]), "exercises": exercises})
    out.sort(key=lambda w: w["start"])
    return out


def hold_label(seconds: float) -> str:
    """48 -> '48 s'; 125 -> '2:05'."""
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}" if total >= 60 else f"{total} s"


def set_label(name: str, s: dict) -> str:
    """'102.5×3' · '+20×3' (kg added to body weight) · '14' · '2:05' · '0.5 km · 2:05' · '60 kg' · '-'."""
    plus = "+" if name.endswith("(Weighted)") else ""
    if s["kg"] is not None and s["r"] is not None:
        return f"{plus}{kg(s['kg'])}×{s['r']}"
    if s["r"] is not None:
        return str(s["r"])
    bits = []
    if s["kg"] is not None:
        bits.append(f"{plus}{kg(s['kg'])} kg")
    if s["km"] is not None:
        bits.append(f"{kg(s['km'])} km")
    if s["s"] is not None:
        bits.append(hold_label(s["s"]))
    return " · ".join(bits) or "-"


def _set_view(name: str, s: dict) -> dict:
    view = {"l": set_label(name, s)}
    if s["type"] not in WORKING:
        view["w"] = OFF_LABEL.get(s["type"], s["type"])
    if s["rpe"] is not None:
        view["rpe"] = f"RPE {kg(s['rpe'])}"
    return view


def _top(sets: list[dict]) -> int | None:
    """Index of the top working set: the heaviest, then the most reps, then the longest; the first on a tie."""
    best, best_key = None, None
    for i, s in enumerate(sets):
        if s["type"] not in WORKING:
            continue
        key = tuple(-1 if s[m] is None else s[m] for m in MEASURES)
        if best_key is None or key > best_key:
            best, best_key = i, key
    return best


def _measures(workouts: list[dict]) -> dict[str, str | None]:
    """Per exercise, what its top set is measured in: kg if it was ever loaded, else reps, else seconds."""
    seen: dict[str, set] = {}
    for w in workouts:
        for ex in w["exercises"]:
            have = seen.setdefault(ex["name"], set())
            for s in ex["sets"]:
                if s["type"] in WORKING:
                    have.update(m for m in MEASURES if s[m] is not None)
    return {name: next((m for m in MEASURES if m in have), None) for name, have in seen.items()}


def _value(sets: list[dict], measure: str | None):
    """The session's best working number in the exercise's measure (102.5, 14, 120); None when it has none."""
    vals = [s[measure] for s in sets if s["type"] in WORKING and s[measure] is not None] if measure else []
    if not vals:
        return None
    v = max(vals)
    return int(v) if float(v).is_integer() else v


def _change(v, prev, measure: str) -> tuple[str, int]:
    """('+2.5 kg', 1) · ('-5 kg', -1) · ('+1 rep', 1) · ('same', 0): this session against the one before."""
    diff = round(v - prev, 2)
    if diff == 0:
        return "same", 0
    word = "rep" if measure == "r" and abs(diff) == 1 else UNIT_WORD[measure]
    return f"{diff:+g} {word}", 1 if diff > 0 else -1


def _top_label(view: dict) -> str:
    return view["sets"][view["top"]]["l"] if view["top"] is not None else "-"


def _sessions(workouts: list[dict], measures: dict) -> tuple[list[dict], dict[str, list]]:
    """Session views, oldest first, and each exercise's history as (workout, exercise view) pairs.
    best = the session beat every earlier one on that exercise; the first session can never be a best."""
    last: dict[str, float] = {}
    best: dict[str, float] = {}
    history: dict[str, list] = {}
    sessions = []
    for w in workouts:
        views = []
        for ex in w["exercises"]:
            name, measure = ex["name"], measures[ex["name"]]
            v = _value(ex["sets"], measure)
            view = {"n": name, "top": _top(ex["sets"]), "v": v, "up": 0,
                    "sets": [_set_view(name, s) for s in ex["sets"]]}
            if ex["note"]:
                view["note"] = ex["note"]
            if v is not None:
                if name in last:
                    view["df"], view["up"] = _change(v, last[name], measure)
                else:
                    view["df"] = "first"
                if name in best and v > best[name]:
                    view["best"] = True
                last[name], best[name] = v, max(v, best.get(name, v))
            views.append(view)
            history.setdefault(name, []).append((w, view))
        n_sets = sum(1 for ex in w["exercises"] for s in ex["sets"] if s["type"] in WORKING)
        session = {"d": w["date"].isoformat(), "label": fmt.day_dated(w["date"]), "t": w["title"],
                   "meta": " · ".join(b for b in (fmt.minutes_label(w["minutes"]), _count(len(views), "exercise"),
                                                  _count(n_sets, "set")) if b),
                   "ex": views}
        if w["note"]:
            session["note"] = w["note"]
        bests = sum(1 for v in views if v.get("best"))
        if bests:
            session["bests"] = bests
        sessions.append(session)
    return sessions, history


def _exercises(history: dict[str, list], measures: dict) -> list[dict]:
    """The exercise index, most sessions first: its count, last date, best set and chart caption."""
    out = []
    for name, occ in history.items():
        n = len({id(w) for w, _ in occ})
        count, word = _count(n, "session"), UNIT_WORD.get(measures[name])
        valued = [(w, e) for w, e in occ if e["v"] is not None]
        best_w, best_e = max(valued, key=lambda x: x[1]["v"]) if valued else (None, None)   # the earliest on a tie
        chart = len(valued) >= CHART_FROM
        cap = (f"Top set per session ({word})" + (f" · last {CHART_LAST} sessions" if len(occ) > CHART_LAST else "")
               if chart else f"Fewer than {CHART_FROM} sessions: no chart yet.")
        out.append((n, {"n": name, "unit": word, "count": count,
                        "sub": f"{count} · last {fmt.dated(occ[-1][0]['date'])}",
                        "best": _top_label(best_e) if best_e else "-",
                        "best_sub": f"best set · {fmt.dated(best_w['date'])}" if best_e else "",
                        "last_top": _top_label(occ[-1][1]), "chart": chart, "cap": cap}))
    out.sort(key=lambda x: (-x[0], x[1]["n"]))
    return [e for _, e in out]


def _rhythm(dates: list[dt.date], today: dt.date) -> list[dict]:
    within = lambda days: sum(1 for d in dates if 0 <= (today - d).days < days)   # noqa: E731
    gap = (today - max(dates)).days
    return [{"k": "Last 4 weeks", "v": str(within(28)), "sub": "sessions"},
            {"k": "Per week", "v": f"{within(84) / 12:.1f}", "sub": "12-wk avg"},
            {"k": "Last session", "v": "Today" if gap == 0 else str(gap),
             "sub": "" if gap == 0 else "day ago" if gap == 1 else "days ago"},
            {"k": "All time", "v": str(len(dates)), "sub": "sessions"}]


def _calendar(sets_by_day: dict[dt.date, int], first: dt.date, today: dt.date) -> list[dict]:
    """One entry per Mon-Sun week from the first session's week to today's. A day is None (still ahead),
    0 (no gym) or {d, lvl, tip}; lvl 1-3 by the day's working sets. A week holding the 1st is labelled
    with its month (January with the year)."""
    monday = first - dt.timedelta(days=first.weekday())
    weeks = []
    while monday <= today:
        days, label = [], ""
        for i in range(7):
            d = monday + dt.timedelta(days=i)
            if d.day == 1:
                label = fmt.MON[d.month - 1] + (f" {d.year}" if d.month == 1 else "")
            if d > today:
                days.append(None)
            elif d in sets_by_day:
                n = sets_by_day[d]
                days.append({"d": d.isoformat(), "lvl": 1 if n < 10 else 2 if n < 18 else 3,
                             "tip": f"{fmt.day_dated(d)} · {_count(n, 'set')}"})
            else:
                days.append(0)
        if not weeks and not label:
            label = f"{fmt.MON[monday.month - 1]} {monday.year}"
        weeks.append({"label": label, "days": days})
        monday += dt.timedelta(days=7)
    return weeks


def _months(dates: list[dt.date], today: dt.date) -> list[dict]:
    """Sessions per calendar month from the first session's month to today's, empty months included."""
    per: dict[str, int] = {}
    for d in dates:
        per[d.isoformat()[:7]] = per.get(d.isoformat()[:7], 0) + 1
    out, (y, m) = [], (min(dates).year, min(dates).month)
    while (y, m) <= (today.year, today.month):
        k = f"{y}-{m:02d}"
        out.append({"k": k, "label": f"{fmt.MON[m - 1]} {y}", "n": per.get(k, 0)})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


def build_gym(root, today: dt.date) -> dict:
    """The Gym tab's view model, or {"available": False, "reason": ...} when there is no usable gym log."""
    again = "run hevy/pull_hevy.py again"
    try:
        workouts = load_workouts(root)
        pulled = dt.datetime.fromtimestamp((pathlib.Path(root) / "data" / "gym.csv").stat().st_mtime) \
            if workouts is not None else None
    except (DataError, OSError, ValueError) as e:
        return _unavailable(_text(f"the gym log could not be read ({e}): {again}",
                                  f"the gym log could not be read: {again}"))
    if workouts is None:
        return _unavailable("data/gym.csv is missing: run hevy/pull_hevy.py")
    workouts = [w for w in workouts if w["date"] <= today]
    if not workouts:
        return _unavailable("data/gym.csv has no workouts yet")
    measures = _measures(workouts)
    sessions, history = _sessions(workouts, measures)
    dates = [w["date"] for w in workouts]
    first, newest = min(dates), max(dates)
    span = fmt.dated(first) if first == newest else f"{fmt.dated(first)} to {fmt.dated(newest)}"
    sets_by_day: dict[dt.date, int] = {}
    years: dict[str, int] = {}
    for w in workouts:
        n = sum(1 for ex in w["exercises"] for s in ex["sets"] if s["type"] in WORKING)
        sets_by_day[w["date"]] = sets_by_day.get(w["date"], 0) + n
        years[str(w["date"].year)] = years.get(str(w["date"].year), 0) + 1
    months = _months(dates, today)
    return {"available": True,
            "line": f"{_count(len(sessions), 'session')} · {span} · {_count(len(measures), 'exercise')}",
            "source": f"Hevy · pulled {fmt.short_date(pulled.date())}",
            "sessions": sessions[::-1],
            "exercises": _exercises(history, measures),
            "chart_last": CHART_LAST,
            "rhythm": _rhythm(dates, today),
            "calendar": _calendar(sets_by_day, first, today),
            "months": months, "month_max": max(m["n"] for m in months),
            "years": [{"y": y, "n": years[y]} for y in sorted(years)]}
