"""make_sample_data.py: write the synthetic sample data the public showcase builds from.

    python tools/make_sample_data.py [--until YYYY-MM-DD]

A fictional athlete follows the sample plan (training-plan-2026-27.json) from two weeks before week 1 to
--until: Garmin daily rows, activities and fitness rows in pull_garmin.py's layout, and a Hevy export
(data/gym.csv) whose sessions follow the plan's gym chips. Seeded, so every run writes the same files.
Nothing here is anyone's real data.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from kunto import plan as kplan          # noqa: E402

NOTE = "# SYNTHETIC SAMPLE DATA for the public Kunto showcase, written by tools/make_sample_data.py; same layout as pull_garmin.py writes"
DAILY_COLS = ("date,rhr,hrv_night,hrv_weekly,hrv_status,sleep_h,deep_h,light_h,rem_h,awake_h,sleep_score,bb_high,bb_low,"
              "stress_avg,steps,run_km,run_n,run_avg_hr,weight,weight_n,weight_src,resp_sleep,resp_wake,readiness,"
              "readiness_level,acute_load,recovery_min,hrv_lo,hrv_hi,acute_src,readiness_src").split(",")
ACT_COLS = "date,start,type,name,km,min,pace,avg_hr,max_hr,cadence,activity_id,te_aer,te_anaer,load,te_label".split(",")
FIT_COLS = ("date,vo2max,vo2max_date,pred_5k,pred_10k,pred_hm,lt_hr,lt_date,status,status_since,load_acute,"
            "load_chronic,load_lo,load_hi,acwr,balance,anaer,anaer_lo,anaer_hi,aer_hi,aer_hi_lo,aer_hi_hi,aer_lo,"
            "aer_lo_lo,aer_lo_hi").split(",")
GYM_COLS = ["title", "start_time", "end_time", "description", "exercise_title", "superset_id", "exercise_notes",
            "set_index", "set_type", "weight_kg", "reps", "distance_km", "duration_seconds", "rpe"]

# plan chip (lower case, starts with) -> Hevy exercise, starting load in kg (None = body weight), weekly step
LIFTS = [
    ("front squat", "Front Squat", 55.0, 2.5), ("trap bar", "Deadlift (Trap bar)", 85.0, 5.0),
    ("strict ohp", "Overhead Press (Barbell)", 35.0, 2.5), ("weighted pull-up", "Pull Up (Weighted)", 4.0, 1.25),
    ("seated leg curl", "Seated Leg Curl (Machine)", 55.0, 2.5), ("chest-supported", "Chest Supported Incline Row (Dumbbell)", 20.0, 1.0),
    ("single-leg rdl", "Single Leg Romanian Deadlift (Dumbbell)", 16.0, 1.0), ("face pull", "Face Pull", 20.0, 1.25),
    ("db curl", "Bicep Curl (Dumbbell)", 12.0, 0.5), ("db bench", "Bench Press (Dumbbell)", 24.0, 1.0),
    ("db lateral raise", "Lateral Raise (Dumbbell)", 8.0, 0.5), ("rope pushdown", "Triceps Rope Pushdown", 20.0, 1.25),
    ("dips", "Triceps Dip", None, 0), ("hanging leg raise", "Hanging Leg Raise", None, 0),
    ("body-weight pull-ups", "Pull Up", None, 0), ("nordics", "Nordic Hamstring Curl", None, 0),
    ("farmer carry", "Farmers Walk", 28.0, 1.0), ("box jump", "Box Jump", None, 0),
]
SETS_RE = re.compile(r"(\d+)\s*×\s*(\d+)(?:–(\d+))?")
KG_RE = re.compile(r"· ~?\+?(\d+(?:\.\d+)?) kg")


def r1(x: float) -> float:
    return round(x, 1)


def fmt_hevy(t: dt.datetime) -> str:
    return f"{t.day} {t:%b %Y, %H:%M}"


def gym_rows(day: dt.date, session: dict, week_no: int, rng: random.Random, deload: bool) -> tuple[list, int]:
    start = dt.datetime.combine(day, dt.time(rng.choice((10, 11, 17, 18)), rng.randrange(0, 50)))
    end = start + dt.timedelta(minutes=session["min"] or 60)
    rows = []
    for chip in session["chips"]:
        low = chip.lower().removeprefix("then ")
        hit = next((l for l in LIFTS if low.startswith(l[0]) or (l[0] == "weighted pull-up" and low.startswith("weighted pull-ups"))), None)
        if hit is None:
            continue
        _, title, base, step = hit
        m = SETS_RE.search(chip)
        n_sets, reps = (int(m.group(1)), int(m.group(3) or m.group(2))) if m else (3, 8)
        top = "top set of 5" in low                    # a baseline test: one top set of 5 @ RPE 8
        if deload:
            n_sets = max(1, round(n_sets * 0.6))
        k = KG_RE.search(chip)
        load = float(k.group(1)) if k else (None if base is None else base + step * max(0, week_no - 1))
        if top:
            n_sets, reps = 1, 5
            load = None if load is None else round(load * 1.12 / 2.5) * 2.5
        for i in range(n_sets):
            rows.append({"title": session["title"], "start_time": fmt_hevy(start), "end_time": fmt_hevy(end),
                         "description": "", "exercise_title": title, "superset_id": None, "exercise_notes": "",
                         "set_index": i, "set_type": "normal", "weight_kg": load if load is None else (int(load) if load == int(load) else load),
                         "reps": reps, "distance_km": None, "duration_seconds": None,
                         "rpe": (8 if top else rng.choice((7, 7.5, 8))) if load is not None else None})
    return rows, int((end - start).total_seconds() // 60)


def newest_first(rows: list[dict]) -> list[dict]:
    """Hevy's export order: the newest workout first, each workout's sets in the order they were done."""
    by_start: dict[str, list] = {}
    for r in rows:
        by_start.setdefault(r["start_time"], []).append(r)
    order = sorted(by_start, key=lambda t: dt.datetime.strptime(t, "%d %b %Y, %H:%M"), reverse=True)
    return [r for t in order for r in by_start[t]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--until", default="2026-11-04")
    a = ap.parse_args(argv)
    until = dt.date.fromisoformat(a.until)
    plan = kplan.load_plan(ROOT / "training-plan-2026-27.json")
    first = dt.date.fromisoformat(plan["weeks"][0]["start"]) - dt.timedelta(days=14)
    rng = random.Random(7)

    acts, gym, daily, fitness = [], [], [], []
    aid = 900000000
    loads: list[float] = []
    weight = 78.6
    hrv7: list[float] = []
    day = first
    while day <= until:
        week = kplan.week_for_date(plan, day)
        deload = bool(week and "deload" in week.get("flags", []))
        sessions = kplan.sessions_for_date(plan, day) if week else (
            [{"kind": "run", "title": "Easy run", "min": 35, "optional": False, "chips": []}] if day.weekday() in (1, 3, 5) else [])
        today_acts = []
        for s in sessions:
            if s["kind"] == "rest" or (s.get("optional") and rng.random() < 0.45):
                continue
            if day == until and s["kind"] != "run":
                continue
            if rng.random() < 0.06:                    # an ordinary missed session
                continue
            hour = 7 if s["kind"] == "run" and not today_acts else rng.choice((12, 17, 18, 19))
            start = dt.datetime.combine(day, dt.time(hour, rng.randrange(0, 59), rng.randrange(0, 59)))
            aid += rng.randrange(1000, 90000)
            kind = s["kind"]
            if kind == "run" or (kind == "test" and "cooper" in s["title"].lower()):
                if kind == "test":
                    km, mins, hr, mx = 2.95, 12.0, 176, 188
                else:
                    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)(?=(?:–\d+)? km)", s["title"])] or [6.0]
                    km = r1(rng.uniform(min(nums), max(nums) + (2 if len(nums) == 1 else 0)) if len(nums) else 6.0)
                    pace = rng.uniform(5.35, 5.75)
                    mins, hr, mx = r1(km * pace), rng.randrange(132, 142), rng.randrange(148, 160)
                p = mins / km
                act = dict(type="running", name="City Running", km=km, min=mins, pace=f"{int(p)}:{round((p % 1) * 60):02d}",
                           avg_hr=float(hr), max_hr=float(mx), cadence=rng.randrange(166, 178),
                           te_aer=r1(rng.uniform(2.4, 3.4)), te_anaer=r1(rng.uniform(0, 0.8)), te_label="AEROBIC_BASE")
            elif kind == "floorball":
                act = dict(type="field_hockey", name="Field Hockey", km=0.0, min=r1(rng.uniform(55, 65)), pace="",
                           avg_hr=float(rng.randrange(128, 140)), max_hr=float(rng.randrange(170, 182)), cadence="",
                           te_aer=r1(rng.uniform(2.6, 3.4)), te_anaer=r1(rng.uniform(1.5, 2.5)), te_label="ANAEROBIC_CAPACITY")
            elif kind == "ski":
                act = dict(type="cross_country_indoor_skiing", name="XC Ski Indoor", km=0.0, min=float(s["min"] or 30), pace="",
                           avg_hr=140.0, max_hr=165.0, cadence="", te_aer=2.8, te_anaer=1.0, te_label="AEROBIC_BASE")
            elif kind in ("gym", "test"):
                rows, mins = gym_rows(day, s, week["week"] if week else 1, rng, deload)
                gym += rows
                act = dict(type="strength_training", name="Strength", km=0.0, min=float(mins), pace="",
                           avg_hr=float(rng.randrange(98, 112)), max_hr=float(rng.randrange(140, 158)), cadence="",
                           te_aer=r1(rng.uniform(0.8, 1.6)), te_anaer=r1(rng.uniform(0.8, 1.8)), te_label="ANAEROBIC_CAPACITY")
            else:
                continue
            act["load"] = int(act["min"] * (act["te_aer"] + act["te_anaer"]) * 0.55)
            act.update(date=day.isoformat(), start=start.strftime("%Y-%m-%d %H:%M:%S"), activity_id=str(aid))
            today_acts.append(act)
        acts += today_acts
        loads.append(sum(x["load"] for x in today_acts))

        # the body: a calm baseline, a dip after hard days, a short bad patch in week 4
        hard = loads[-1] > 120
        patch = dt.date(2026, 10, 19) <= day <= dt.date(2026, 10, 22)
        rhr = round(55 + rng.gauss(0, 1.2) + (1.5 if hard else 0) + (3 if patch else 0))
        hrv = round(64 + rng.gauss(0, 5) - (6 if hard else 0) - (12 if patch else 0))
        hrv7 = (hrv7 + [hrv])[-7:]
        sleep = r1(min(8.9, max(5.9, rng.gauss(7.45, 0.45) - (0.8 if patch else 0))))
        deep, rem = r1(sleep * rng.uniform(0.14, 0.2)), r1(sleep * rng.uniform(0.2, 0.26))
        score = int(min(95, max(55, 60 + (sleep - 6) * 12 + rng.gauss(0, 4) - (8 if patch else 0))))
        acute = int(sum(loads[-7:]) * 1.05)
        ready = int(min(96, max(25, score * 0.7 + (hrv - 50) * 0.6 - (10 if hard else 0) + rng.gauss(0, 4))))
        level = "HIGH" if ready >= 75 else "MODERATE" if ready >= 50 else "LOW"
        weight += rng.gauss(-0.01, 0.25)
        run = [x for x in today_acts if x["type"] == "running"]
        weighed = rng.random() < 0.8
        daily.append({
            "date": day.isoformat(), "rhr": rhr, "hrv_night": hrv,
            "hrv_weekly": round(sum(hrv7) / len(hrv7)) if len(hrv7) == 7 else "",
            "hrv_status": "BALANCED" if len(daily) >= 21 else "NONE",
            "sleep_h": sleep, "deep_h": deep, "light_h": r1(sleep - deep - rem), "rem_h": rem,
            "awake_h": r1(rng.uniform(0.05, 0.5)), "sleep_score": score,
            "bb_high": rng.randrange(70, 96), "bb_low": rng.randrange(8, 30), "stress_avg": rng.randrange(20, 34),
            "steps": rng.randrange(6000, 14000) if day < until else rng.randrange(1500, 4000),
            "run_km": r1(sum(x["km"] for x in run)) if run else "", "run_n": len(run) or "",
            "run_avg_hr": round(sum(x["avg_hr"] for x in run) / len(run)) if run else "",
            "weight": r1(weight) if weighed else "", "weight_n": 1 if weighed else "",
            "weight_src": "MANUAL" if weighed else "",
            "resp_sleep": 14.0, "resp_wake": 14.0 + rng.choice((0, 0, 1)), "readiness": ready,
            "readiness_level": level, "acute_load": acute, "recovery_min": "", "hrv_lo": 55, "hrv_hi": 74,
            "acute_src": "approx", "readiness_src": "est"})
        if day.weekday() in (0, 3) or day == until:
            vo2 = r1(47.5 + (day - first).days * 0.012)
            fitness.append({c: "" for c in FIT_COLS} | {"date": day.isoformat(), "vo2max": vo2,
                                                       "vo2max_date": day.isoformat(), "lt_hr": 158})
        day += dt.timedelta(days=1)

    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    for name, cols, rows in (("garmin-daily.csv", DAILY_COLS, daily), ("garmin-activities.csv", ACT_COLS, acts),
                             ("garmin-fitness.csv", FIT_COLS, fitness)):
        with open(data / name, "w", encoding="utf-8", newline="") as f:
            f.write(NOTE + "\n")
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    with open(data / "gym.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=GYM_COLS, quoting=csv.QUOTE_STRINGS, lineterminator="\n")
        w.writeheader()
        w.writerows(newest_first(gym))
    print(f"wrote data/: {len(daily)} days, {len(acts)} activities, {len(fitness)} fitness rows, {len(gym)} gym sets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
