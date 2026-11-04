"""Training plan tab view model (spec section 5): all 51 weeks with per-session status, the season
strip (blocks + markers + current week) and the past-weeks list."""
from __future__ import annotations

import datetime as dt

from kunto import card
from kunto import fmt
from kunto import matching
from kunto import plan as kplan

FLAG_LABEL = {"deload": "Deload week", "taper": "Taper", "test": "Test",
              "event": "Event", "event-optional": "Optional event", "travel": "Travel"}
STATUS_LABEL = {"done": "✓ Done", "missed": "✗ Missed", "skipped": "Skipped", "nodata": "No data yet",
                "today": "Today", "upcoming": "Planned", "rest": "Rest"}
DATED_LABEL = {"moved": "Moved to", "swapped": "Swapped to"}       # followed by the weekday of moved_to
FOCUS_LABEL = {"legs": "legs", "upper": "upper body", "full": "full body"}


def data_through(g) -> dt.date:
    """Newest Garmin daily date (that day is covered only up to its morning pull); dt.date.min when there
    is no daily data, so nothing counts as covered."""
    return max(g.daily) if g.daily else dt.date.min


def block_family(block: str) -> str:
    """CSS family key for a block name: reentry, base, holiday, floorball, transition, goal, summer, peak, test."""
    b = block.strip().lower()
    for prefix, fam in (("0", "reentry"), ("1", "base"), ("2", "floorball"), ("3", "goal"), ("4", "peak"),
                        ("holiday", "holiday"), ("transition", "transition"), ("summer", "summer"), ("test", "test")):
        if b.startswith(prefix):
            return fam
    return "other"


def _detail(s: dict) -> str | None:
    u = s["unit"]
    if not u:
        return None
    bits = []
    if u["cls"] == "run" and u.get("km"):
        bits.append(f"{u['km']:.1f} km")
    bits.append(fmt.minutes_label(u.get("min")))
    if u.get("avg_hr") is not None:
        bits.append(f"avg HR {fmt.num(u['avg_hr'])}")
    if u.get("focus"):                    # what Hevy shows was lifted: why this session got the tick
        bits.append(f"Hevy: {FOCUS_LABEL[u['focus']]}")
    return " · ".join(b for b in bits if b)


AHEAD = ("today", "upcoming", "swapped")        # the statuses whose lifts show Hevy's last top set and next load


def session_view(s: dict, lasts: dict | None = None, nexts: dict | None = None) -> dict:
    status = s["status"]
    label = f"{DATED_LABEL[status]} {fmt.DOW[s['moved_to'].weekday()]}" if status in DATED_LABEL \
        else STATUS_LABEL[status]
    return {"kind": s["kind"], "title": s["title"], "chips": fmt.chips(s["chips"]),
            "card": card.build(s, *((lasts, nexts) if status in AHEAD else (None, None))),
            "min": fmt.plan_minutes(s["min"]),
            "hard": s["hard"], "optional": s["optional"], "first_to_go": s["first_to_go"],
            "status": status, "status_label": label, "detail": _detail(s)}


def week_view(plan: dict, week: dict, g, today: dt.date, lasts: dict | None = None, nexts: dict | None = None) -> dict:
    start, end = dt.date.fromisoformat(week["start"]), dt.date.fromisoformat(week["end"])
    covered = data_through(g)
    days = matching.plan_week_status(plan, week, g.activities, today, covered)
    sessions = [s for d in days for s in d["sessions"] if s["kind"] != "rest"]
    req = [s for s in sessions if not s["optional"]]
    opt = [s for s in sessions if s["optional"]]
    ok = ("done", "moved")
    summary = {"req_done": sum(s["status"] in ok for s in req), "req_total": len(req),
               "opt_done": sum(s["status"] in ok for s in opt), "opt_total": len(opt)}
    km = round(matching.run_km(g.activities, start, end), 1)      # judged at the 1 decimal the page shows
    rng = kplan.run_km_range(week.get("run_km", ""))
    state = "past" if end < today else "future" if start > today else "current"
    km_state = "none"
    # A single-number target ("40") is shown but not judged: no under/over tolerance has been agreed.
    # judged only once the data covers the whole week (the pull after Sunday ran)
    if rng and rng[0] != rng[1] and state == "past" and covered > end:
        km_state = "under" if km < rng[0] else "over" if km > rng[1] else "in"
    km_text = f"{km:.1f} of {week['run_km']} km" if rng else f"{km:.1f} km"
    total = len(plan["weeks"])
    dates = fmt.range_label(start, end)
    return {"week": week["week"], "start": week["start"], "end": week["end"], "dates": dates,
            "block": week["block"], "family": block_family(week["block"]),
            "top": f"Week {week['week']} of {total} · {week['block']} · {dates}",
            "km_actual": f"{km:.1f}", "km_plan": week.get("run_km", ""), "km_text": km_text,
            "km_state": km_state, "state": state,
            "flags": [FLAG_LABEL.get(f, f) for f in week.get("flags", [])],
            "summary": summary,
            "summary_text": f"{summary['req_done']}/{summary['req_total']} required · "
                            f"{summary['opt_done']}/{summary['opt_total']} optional · {km_text}",
            "days": [{"date": d["date"].isoformat(), "label": fmt.day_label(d["date"]),
                      "is_today": d["date"] == today, "sessions": [session_view(s, lasts, (nexts or {}).get(d["date"]))
                                                                 for s in d["sessions"]]}
                     for d in days]}


def build_training(plan: dict, g, today: dt.date, lasts: dict | None = None, nexts: dict | None = None) -> dict:
    """lasts: card.last_top_sets() of the gym log, for the main lifts of the sessions still ahead; nexts:
    progression.upcoming(), each lift's next load on its next planned session."""
    weeks = [week_view(plan, w, g, today, lasts, nexts) for w in plan["weeks"]]
    markers = [{"week": m["week"], "d": m["date"].isoformat(), "label": m["label"], "sub": fmt.day_label(m["date"])}
               for m in kplan.season_markers(plan)]
    past = [w["week"] for w in reversed(weeks) if w["state"] == "past"]
    return {"current_week": kplan.current_week_number(plan, today), "weeks": weeks, "markers": markers,
            "past_weeks": past}
