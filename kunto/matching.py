"""Planned sessions vs Garmin activities: done / moved / missed / skipped / today / upcoming / rest.

Rules (spec section 5 + owner decision 2, 2026-09-27):
- run = Garmin running types; gym = strength_training; ski = cross-country skiing types and SkiErg
  (the Fenix "XC Ski Indoor" profile, stored as cross_country_indoor_skiing).
- floorball = field_hockey: the Fenix 9 has no floorball profile, so the athlete records it as Field Hockey
  (decision-log 2026-09-30). The Garmin type alone decides: a running activity is always a run, whatever
  its cadence (decision-log 2026-10-11).
- test / event sessions accept any activity on their day except floorball: a game is never the gym or
  a test (2026-10-11: on a game day the gym is skipped).
- Two runs starting within 60 s are one (a duplicate upload); same-day runs are summed into one
  (a split session).
- Each activity satisfies at most one session. Required sessions are matched before optional ones;
  a required session is matched on its own day first, then (run/gym/ski only, and only once its day
  has passed) "moved" to another day of the same Mon-Sun week, preferring an unplanned extra activity.
- An optional session is credited on its own day only (amendment 2026-09-27, the weekly-close rule):
  it is never "moved"; not done on its day = "skipped", and an activity on another day stays an extra.
- A gym session is credited by what was lifted (decision-log 2026-10-04). The plan gives each gym session a
  focus (legs, upper or full); a strength activity carries the focus Hevy shows for its day (kunto/gym.py).
  A legs or upper session refuses an activity of the other focus, and what Hevy shows is matched before
  anything else, so swapped days come out as two "moved" sessions. Such a session is credited before its
  day when Hevy shows it was lifted on an earlier day that had no use for it; the session it displaced is
  "swapped" (not missed) until that later day has passed. No Hevy session, or a mixed one, fits any focus.
"""
from __future__ import annotations

import datetime as dt

from kunto.plan import resolve_week

RUN_TYPES = {"running", "street_running", "trail_running", "treadmill_running", "track_running",
             "indoor_running", "virtual_run", "ultra_run", "obstacle_run"}
GYM_TYPES = {"strength_training"}
SKI_TYPES = {"cross_country_skiing", "cross_country_skiing_ws", "skate_skiing_ws", "backcountry_skiing",
             "cross_country_indoor_skiing"}
FLOORBALL_TYPES = {"field_hockey"}
DUPLICATE_WINDOW_S = 60
MOVABLE = {"run", "gym", "ski"}           # floorball, test and event sessions are bound to their day
SPLIT = ("legs", "upper")                 # the gym focuses that tell two sessions apart; "full" fits either


def is_run_type(t: str | None) -> bool:
    t = t or ""
    return t in RUN_TYPES or t.endswith("_running")


def classify(act: dict) -> str:
    """'run', 'gym', 'ski', 'floorball' or 'other', by Garmin type alone."""
    t = act.get("type") or ""
    if is_run_type(t):
        return "run"
    if t in GYM_TYPES:
        return "gym"
    if t in SKI_TYPES or "skierg" in t:
        return "ski"
    if t in FLOORBALL_TYPES:
        return "floorball"
    return "other"


def dedupe_runs(acts: list[dict]) -> list[dict]:
    """Drop the shorter of two runs whose starts are within 60 s. Order kept."""
    runs = sorted((a for a in acts if is_run_type(a.get("type")) and a.get("start")), key=lambda a: a["start"])
    drop = set()
    for prev, cur in zip(runs, runs[1:]):
        if (cur["start"] - prev["start"]).total_seconds() <= DUPLICATE_WINDOW_S:
            drop.add(id(cur) if (cur.get("km") or 0) <= (prev.get("km") or 0) else id(prev))
    return [a for a in acts if id(a) not in drop]


def _weighted_hr(parts: list[dict]) -> float | None:
    num = sum(p["avg_hr"] * (p.get("min") or 0) for p in parts if p.get("avg_hr") is not None)
    den = sum(p.get("min") or 0 for p in parts if p.get("avg_hr") is not None)
    return round(num / den) if den else None


def with_gym_focus(acts: list[dict], focus_by_day: dict) -> list[dict]:
    """The activities with every strength activity tagged "focus": what Hevy shows was lifted that day
    (gym.day_focus: 'legs', 'upper' or 'full'). A day without a Hevy session stays untagged."""
    return [{**a, "focus": focus_by_day[a["date"]]} if a["date"] in focus_by_day and classify(a) == "gym" else a
            for a in acts]


def units(acts: list[dict]) -> list[dict]:
    """Matchable units: deduped, same-day runs summed into one unit, everything else one unit each.

    Unit keys: date, cls, type, name, km, min, avg_hr, start, focus (gym only, see with_gym_focus),
    parts (the source rows).
    """
    out, runs_by_day = [], {}
    for a in dedupe_runs(acts):
        cls = classify(a)
        if cls == "run":
            runs_by_day.setdefault(a["date"], []).append(a)
            continue
        out.append({"date": a["date"], "cls": cls, "type": a.get("type"), "name": a.get("name"),
                    "km": a.get("km"), "min": a.get("min"), "avg_hr": a.get("avg_hr"),
                    "start": a.get("start"), "focus": a.get("focus"), "parts": [a]})
    for day, parts in runs_by_day.items():
        out.append({"date": day, "cls": "run", "type": parts[0].get("type"), "name": parts[0].get("name"),
                    "km": round(sum(p.get("km") or 0 for p in parts), 2),
                    "min": round(sum(p.get("min") or 0 for p in parts), 1),
                    "avg_hr": _weighted_hr(parts), "start": min(p["start"] for p in parts if p.get("start"))
                    if any(p.get("start") for p in parts) else None, "parts": parts})
    out.sort(key=lambda u: (u["date"], u["start"] or dt.datetime.min))
    return out


def run_km(acts: list[dict], start: dt.date, end: dt.date) -> float:
    """Run km between start and end inclusive, deduped."""
    return round(sum(a.get("km") or 0 for a in dedupe_runs(acts)
                     if start <= a["date"] <= end and classify(a) == "run"), 2)


def _accepts(kind: str, cls: str) -> bool:
    if kind in ("test", "event"):
        return cls != "floorball"
    return {"run": "run", "gym": "gym", "ski": "ski", "floorball": "floorball"}.get(kind) == cls


def _rank(kind: str) -> int:
    return 0 if kind in MOVABLE else 1 if kind == "floorball" else 2


def _fits(s: dict, u: dict, strict: bool = False) -> bool:
    """Can unit u credit session s? A legs or upper gym session refuses a strength activity that Hevy shows
    trained the other one. strict: only a legs or upper session, and only an activity Hevy shows matches it."""
    if not _accepts(s["kind"], u["cls"]):
        return False
    split = s["kind"] == "gym" and s.get("focus") in SPLIT
    if strict:
        return split and u.get("focus") == s["focus"]
    return not split or u.get("focus") in (None, "full", s["focus"])


def _match(slots: list, week_units: list[dict], used: set, today: dt.date, same_day: bool,
           plan_by_day: dict, strict: bool = False) -> None:
    def own_day_use(u):                   # could a session planned on the activity's own day use it?
        return any(_fits(k, u) for k in plan_by_day.get(u["date"], ()))

    for d, s in slots:
        if s["status"]:
            continue
        if same_day:
            cands = [u for u in week_units if id(u) not in used and u["date"] == d["date"] and _fits(s, u, strict)]
            if s["kind"] in ("test", "event"):
                cands.sort(key=lambda u: -(u.get("min") or 0))
        else:
            early = d["date"] >= today
            if s["kind"] not in MOVABLE or (early and not strict):
                continue
            cands = [u for u in week_units if id(u) not in used and u["date"] != d["date"] and _fits(s, u, strict)]
            if early:                     # not its day yet: only what Hevy shows was lifted earlier, on a day
                cands = [u for u in cands if u["date"] < d["date"] and not own_day_use(u)]   # with no use for it
            # prefer an unplanned extra over an activity that its own day's plan could use
            cands.sort(key=lambda u: (own_day_use(u), abs((u["date"] - d["date"]).days), u["date"]))
        if cands:
            s["unit"], s["status"] = cands[0], "done" if same_day else "moved"
            s["moved_to"] = None if same_day else cands[0]["date"]
            used.add(id(cands[0]))


def match_week(days: list[dict], week_units: list[dict], today: dt.date,
               data_through: dt.date | None = None) -> list[dict]:
    """Status every session of one Mon-Sun week.

    days: resolve_week output. week_units: units() of that week's activities.
    data_through: the newest Garmin daily date. That day is only covered up to its morning pull, so an
    unmatched past session on it or later is 'nodata' (a failed pull must never read as a miss).
    None = treat every past day as covered.
    Order: required sessions (what Hevy shows was lifted: own day, then moved; then the rest: own day, then
    moved), then optional sessions (own day only: an optional session never moves); within each, run/gym/ski
    before floorball before test/event. Only a required session whose day has passed can be "moved" (until
    then it may still happen on its day), except a gym session Hevy shows was lifted early (module docstring).
    Returns the days with each session extended by:
      status   'done' | 'moved' | 'swapped' | 'missed' | 'skipped' | 'nodata' | 'today' | 'upcoming' | 'rest'
      unit     the matched unit or None
      moved_to the unit's date when status is 'moved'; the day a 'swapped' session is now due; else None
    """
    out = [{**d, "sessions": [{**s, "status": None, "unit": None, "moved_to": None} for s in d["sessions"]]}
           for d in days]
    slots = [(d, s) for d in out for s in d["sessions"] if s["kind"] != "rest"]
    plan_by_day = {d["date"]: d["sessions"] for d in out}
    used: set[int] = set()
    for optional in (False, True):
        group = sorted((x for x in slots if x[1]["optional"] == optional),
                       key=lambda x: (_rank(x[1]["kind"]), x[0]["date"]))
        if not optional:
            _match(group, week_units, used, today, True, plan_by_day, strict=True)
            _match(group, week_units, used, today, False, plan_by_day, strict=True)
        _match(group, week_units, used, today, True, plan_by_day)
        if not optional:                  # an optional session is credited on its own day only, never moved
            _match(group, week_units, used, today, False, plan_by_day)
    # a day whose strength activity went to a later session that is not over yet: its own session swapped there
    swapped_to = {s["unit"]["date"]: d["date"] for d, s in slots
                  if s["status"] == "moved" and s["kind"] == "gym" and s["unit"]["date"] < d["date"] >= today}
    for d in out:
        for s in d["sessions"]:
            if s["status"]:
                continue
            if s["kind"] == "rest":
                s["status"] = "rest"
            elif s["kind"] == "gym" and not s["optional"] and d["date"] in swapped_to:
                s["status"], s["moved_to"] = "swapped", swapped_to[d["date"]]
            elif d["date"] < today and data_through is not None and d["date"] >= data_through:
                s["status"] = "nodata"
            elif d["date"] < today:
                s["status"] = "skipped" if s["optional"] else "missed"
            elif d["date"] == today:
                s["status"] = "today"
            else:
                s["status"] = "upcoming"
    return out


def plan_week_status(plan: dict, week: dict, activities: list[dict], today: dt.date,
                     data_through: dt.date | None = None) -> list[dict]:
    """resolve_week + units + match_week for one plan week."""
    start, end = dt.date.fromisoformat(week["start"]), dt.date.fromisoformat(week["end"])
    week_units = units([a for a in activities if start <= a["date"] <= end])
    return match_week(resolve_week(plan, week), week_units, today, data_through)
