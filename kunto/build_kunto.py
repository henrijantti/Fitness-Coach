"""build_kunto.py: bake the Garmin CSVs, the plan json and the gym log into one self-contained page,
kunto/index.html.

    python kunto/build_kunto.py [--root R] [--today YYYY-MM-DD] [--check] [--demo] [--out PATH]

No network. Writes only the output page (temp file, then rename: never a partial page).
--check builds everything in memory and writes nothing. --demo freezes the page as a snapshot (the public
sample site): the freshness stamp reads "Sample data" and never turns out of date. Exit 1 on any input error, except the gym log:
a missing or unreadable data/gym.csv leaves the Gym tab empty with a WARN line and the page still builds.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True          # no __pycache__ in the Drive folder (Google Drive syncs every file)

from kunto import data as kdata          # noqa: E402
from kunto import card, gym, gymtab, matching, overview, progression, render, training   # noqa: E402
from kunto import plan as kplan          # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = pathlib.Path(__file__).resolve().with_name("template.html")
PLAN_FILE = "training-plan-2026-27.json"


def helsinki_now() -> dt.datetime:
    """Now in Europe/Helsinki (zoneinfo + the installed tzdata); falls back to the PC's local zone."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Helsinki"))
    except Exception:
        return dt.datetime.now().astimezone()


def build_model(root: pathlib.Path, today: dt.date, now: dt.datetime) -> dict:
    """Load, validate and build the whole view model. Raises PlanError / DataError."""
    plan = kplan.load_plan(pathlib.Path(root) / PLAN_FILE)
    errors = kplan.validate_plan(plan)
    if errors:
        raise kplan.PlanError("plan json invalid:\n  " + "\n  ".join(errors))
    g = kdata.as_of(kdata.load_garmin(root), today)
    # a gym session is credited by what Hevy shows was lifted that day (matching.py); no gym log, no tags
    g = dataclasses.replace(g, activities=matching.with_gym_focus(g.activities, gym.load_day_focus(root, today)))
    raw = kdata.extras(g, today)
    sets = gym.load_sets_or_none(root)
    lasts = card.last_top_sets(sets, today)                              # the main lifts' last top sets
    sets = [s for s in sets or [] if s.date <= today] if sets is not None else None
    week = kplan.week_for_date(plan, today)
    swapped = {d["date"]: s["moved_to"] for d in (matching.plan_week_status(plan, week, g.activities, today)
                                                  if week else []) for s in d["sessions"] if s["status"] == "swapped"}
    nexts = progression.upcoming(plan, sets, today, g.daily, swapped=swapped)   # each lift's next load (section 6)
    return {"meta": {"built": now.isoformat(timespec="minutes"), "today": today.isoformat()},
            "overview": overview.build_overview(g, plan, today, now, raw, lasts, nexts),
            "training": training.build_training(plan, g, today, lasts, nexts),
            "gym": gymtab.build_gym(root, today)}


def write_atomic(path: pathlib.Path, text: str) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Build the Kunto dashboard page.")
    ap.add_argument("--root", default=str(ROOT), help="repo root holding data/ and the plan json")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today in Europe/Helsinki)")
    ap.add_argument("--check", action="store_true", help="validate and build in memory; write nothing")
    ap.add_argument("--out", default=None, help="output page (default: <root>/kunto/index.html)")
    ap.add_argument("--demo", action="store_true", help="a frozen snapshot: never shown as out of date")
    a = ap.parse_args(argv)
    now = helsinki_now()
    if a.today:
        try:
            today = dt.date.fromisoformat(a.today)
        except ValueError:
            print(f"ERROR --today {a.today!r} is not YYYY-MM-DD")
            return 1
        now = now.replace(year=today.year, month=today.month, day=today.day)
    else:
        today = now.date()
    root = pathlib.Path(a.root)
    try:
        model = build_model(root, today, now)
        if a.demo:
            model["meta"]["demo"] = True
            model["overview"]["fresh"]["label"] = "Sample data · " + model["overview"]["fresh"]["label"]
        page = render.render(TEMPLATE.read_text(encoding="utf-8"), model)
    except (kplan.PlanError, kdata.DataError, render.TemplateError, ValueError, OSError) as e:
        print(f"ERROR {e}")
        return 1
    hdr = model["overview"]["header"]["line"]
    fresh = model["overview"]["fresh"]["label"]
    gym_warn = None if model["gym"]["available"] else f"WARN Gym tab is empty: {model['gym']['reason']}"
    if a.check:
        print(f"OK (check only, nothing written): {hdr} · {fresh} · {len(page) // 1024} KB")
        if gym_warn:
            print(gym_warn)
        return 0
    out = pathlib.Path(a.out) if a.out else root / "kunto" / "index.html"
    try:
        write_atomic(out, page)
    except OSError as e:                     # e.g. Drive holding a lock on the old page: nothing is replaced
        print(f"ERROR could not write {out}: {e}")
        return 1
    print(f"wrote {out}: {hdr} · {fresh} · {len(page) // 1024} KB")
    if gym_warn:
        print(gym_warn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
