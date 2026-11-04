# pull_garmin.py — pull Garmin Connect daily summaries + activities into data/garmin-daily.csv
# and data/garmin-activities.csv, then print a side-by-side against data/daily.csv (the Apple
# Health chain) for the dual-watch calibration window. Tooling, not coaching data.
#
# Data path: Garmin's official Personal API (the only source since Oct 24, 2026, decision-log 2026-10-24)
# whenever GARMIN_PERSONAL_API_KEY is set, and the pull prints a `SOURCE` line; without the key (the PC)
# the unofficial `garminconnect` login, whose tokens `python pull_garmin.py --login` (the athlete's alone)
# stores under ~/.garminconnect. Either way: raw JSON cache (data/garmin-raw/, gitignored) -> the CSVs.
# `--merge` (the cloud) fetches a window into a temp dir and merges it into the committed CSVs; with
# GARMINTOKENS set it prints a `TOKEN` line. The Personal API has no readiness, recovery time, training
# status or race predictor: readiness and a missing acute_load are our estimates (readiness_src est,
# acute_src approx), VO2max comes from the newest run's .FIT file and the threshold HR from the HR zones.
# Chronic load and the load focus are ours too (est_chronic_load, est_load_focus, read by Kunto and
# coach_brief.py); the focus reads each activity's te_label, and --merge refetches 4 weeks of activities
# that have none.
# Endpoints, reply shapes and gotchas: docs/superpowers/specs/2026-10-24-garmin-personal-api.md.
# Writes only inside data/. Never touches the .md authority files.
#
# Date semantics match daily.csv: sleep and overnight HRV sit on the WAKE date; RHR, steps,
# stress and Body Battery on the calendar date; runs on their start date.
#
# `--activity ID|YYYY-MM-DD|latest [--rep-pace M:SS]` prints one run rep by rep (laps, detected hard
# segments with 200 m sub-splits, recoveries, warm-up, cool-down, HR zones) from the per-second stream.
from __future__ import annotations

import argparse, base64, csv, datetime, getpass, json, math, os, pathlib, sys, tempfile
from collections import defaultdict
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent


def write_csv(path: pathlib.Path, columns: list[str], rows: list[dict], header_comment: str | None = None):
    # Own copy: build_history.py (where this came from) retired to archive/2026/tools/ at the Sep 27 reset.
    # Written to a temp file and swapped in, so a pull that dies mid-write (the unattended daily run)
    # leaves the previous CSV intact instead of a truncated one.
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            if header_comment:
                f.write("# " + header_comment + "\n")
            wr = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
            wr.writeheader()
            for r in rows:
                wr.writerow({c: ("" if r.get(c) is None else r.get(c, "")) for c in columns})
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()
TOKENSTORE = "~/.garminconnect"
FENIX_FIRST_DAY = datetime.date(2026, 9, 19)     # first full day on the Fenix 9

GARMIN_DAILY_COLUMNS = ["date", "rhr", "hrv_night", "hrv_weekly", "hrv_status", "sleep_h", "deep_h", "light_h",
                        "rem_h", "awake_h", "sleep_score", "bb_high", "bb_low", "stress_avg", "steps",
                        "run_km", "run_n", "run_avg_hr", "weight", "weight_n", "weight_src",
                        "resp_sleep", "resp_wake", "readiness", "readiness_level", "acute_load",
                        "recovery_min", "hrv_lo", "hrv_hi", "acute_src", "readiness_src"]
GARMIN_DAILY_HEADER = ("derived by pull_garmin.py from Garmin Connect — do not hand-edit. rhr = Garmin daily "
                       "resting HR. hrv_night = overnight RMSSD avg (NOT comparable to Apple's SDNN in daily.csv); "
                       "hrv_weekly/hrv_status = Garmin's 7-day HRV status (needs ~3 weeks of nights). sleep_h "
                       "excludes awake time, on the wake date. run_* from Garmin running activities. "
                       "weight = the day's latest Garmin weigh-in in kg (weight_src MANUAL = typed into Garmin "
                       "Connect, USER_SETTING = the profile value, not a scale read). resp_sleep/resp_wake = "
                       "breaths/min (a rise of ~2 over baseline = early illness flag). readiness/acute_load = "
                       "Garmin Training Readiness (composite, advisory only); readiness_src = est: ours, from the sleep "
                       "scores and the activities' load, in Garmin's levels (decision-log 2026-10-24; Sep 19 to Oct 22, "
                       "2026 it was off by 8 points on average, 32 at worst). recovery_min = Garmin's recovery time at "
                       "wake-up, minutes. hrv_lo/hrv_hi = Garmin's balanced HRV baseline (empty until ~3 weeks "
                       "of nights). acute_src = approx: Garmin had no acute_load, so it is approximated from the "
                       "activities' load, each day's faded by e^(-days/4.5) (Personal API, decision-log "
                       "2026-10-24; Oct 1 to 22, 2026 it was off by 12% on average, 33% at worst). Empty = Garmin had no data.")
GARMIN_ACTIVITY_COLUMNS = ["date", "start", "type", "name", "km", "min", "pace", "avg_hr", "max_hr", "cadence",
                           "activity_id", "te_aer", "te_anaer", "load", "te_label"]
GARMIN_ACTIVITY_HEADER = ("derived by pull_garmin.py from Garmin Connect — do not hand-edit. min = moving time; "
                          "pace = min/km on moving time (runs only); cadence = steps/min; te_aer/te_anaer = Garmin "
                          "aerobic/anaerobic training effect (0–5); load = Garmin activity training load; te_label = Garmin's "
                          "primary benefit (AEROBIC_BASE, TEMPO, ANAEROBIC_CAPACITY, ...), which our load focus reads.")
GARMIN_FITNESS_COLUMNS = ["date", "vo2max", "vo2max_date", "pred_5k", "pred_10k", "pred_hm", "lt_hr", "lt_date",
                          "status", "status_since", "load_acute", "load_chronic", "load_lo", "load_hi", "acwr",
                          "balance", "anaer", "anaer_lo", "anaer_hi", "aer_hi", "aer_hi_lo", "aer_hi_hi",
                          "aer_lo", "aer_lo_lo", "aer_lo_hi"]
GARMIN_FITNESS_HEADER = ("derived by pull_garmin.py from Garmin Connect — do not hand-edit. One row per pull date: "
                         "Garmin's running VO2max estimate, its race predictor (needs weeks of GPS+HR runs — do not "
                         "race by it) and the lactate-threshold HR estimate. Weekly-resolution numbers. On a "
                         "Personal API row only vo2max (from the newest run's .FIT file), vo2max_date "
                         "and lt_hr (the HR zones' threshold, no lt_date) are filled. "
                         "status/load_* = Garmin training status: acute and chronic load, load_lo/load_hi = the "
                         "optimal acute-load range, acwr = acute:chronic ratio. balance/anaer/aer_hi/aer_lo = the "
                         "4-week training load focus, each with its target _lo/_hi.")

RUN_KEYS = {"running", "street_running", "trail_running", "treadmill_running", "track_running",
            "indoor_running", "virtual_run", "ultra_run", "obstacle_run"}

# (label, key in daily.csv, key in garmin-daily.csv)
COMPARE_METRICS = [("rhr", "rhr", "rhr"), ("hrv", "hrv", "hrv_night"),
                   ("sleep_h", "sleep_h", "sleep_h"), ("run_km", "run_km", "run_km")]


# ---------- parsing (pure) ----------

def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _hours(sec) -> float | None:
    return None if sec is None else round(float(sec) / 3600, 2)


def parse_day(date: str, stats: dict | None, hrv: dict | None, sleep: dict | None,
              resp: dict | None = None, readiness: list | dict | None = None) -> dict:
    """One garmin-daily row from the raw blocks. Every block may be None or {}."""
    stats, hrv, sleep, resp = stats or {}, hrv or {}, sleep or {}, resp or {}
    dto = sleep.get("dailySleepDTO") or {}
    hs = hrv.get("hrvSummary") or {}
    scores = dto.get("sleepScores") or {}
    rds = readiness if isinstance(readiness, list) else [readiness or {}]
    rd = next((x for x in rds if x and x.get("score") is not None), {})
    # The morning's value, not the first entry: the list is newest first and every synced workout adds an
    # AFTER_POST_EXERCISE_RESET entry on top (2026-09-26: 3456 after the race, 2093 at wake-up).
    wake = next((x for x in rds if isinstance(x, dict) and x.get("inputContext") == "AFTER_WAKEUP_RESET"
                 and x.get("recoveryTime") is not None), {})
    base = hs.get("baseline") or {}
    return {
        "date": date,
        # Live pull (Sep 19, 2026): the sleep payload also carries restingHeartRate + avgOvernightHrv
        # at its top level (the DTO copies were null), so those are the fallbacks after stats/hrvSummary.
        "rhr": _first(stats.get("restingHeartRate"), sleep.get("restingHeartRate"), dto.get("restingHeartRate")),
        "hrv_night": _first(hs.get("lastNightAvg"), sleep.get("avgOvernightHrv"), dto.get("avgOvernightHrv"),
                            dto.get("avgSleepHRV")),
        "hrv_weekly": hs.get("weeklyAvg"),
        "hrv_status": hs.get("status"),
        "sleep_h": _hours(dto.get("sleepTimeSeconds")),
        "deep_h": _hours(dto.get("deepSleepSeconds")),
        "light_h": _hours(dto.get("lightSleepSeconds")),
        "rem_h": _hours(dto.get("remSleepSeconds")),
        "awake_h": _hours(dto.get("awakeSleepSeconds")),
        "sleep_score": (scores.get("overall") or {}).get("value"),
        "bb_high": stats.get("bodyBatteryHighestValue"),
        "bb_low": stats.get("bodyBatteryLowestValue"),
        "stress_avg": stats.get("averageStressLevel"),
        "steps": stats.get("totalSteps"),
        "run_km": None, "run_n": None, "run_avg_hr": None,
        "resp_sleep": resp.get("avgSleepRespirationValue"),
        "resp_wake": resp.get("avgWakingRespirationValue"),
        "readiness": rd.get("score"),
        "readiness_level": rd.get("level"),
        "acute_load": rd.get("acuteLoad"),
        "recovery_min": wake.get("recoveryTime"),
        "hrv_lo": base.get("balancedLow"),
        "hrv_hi": base.get("balancedUpper"),
    }


def parse_activity(a: dict) -> dict:
    key = (a.get("activityType") or {}).get("typeKey") or ""
    is_run = key in RUN_KEYS or key.endswith("_running")
    km = round(float(a.get("distance") or 0) / 1000, 2)
    # an indoor activity with no distance has a moving time of 0: use the timer instead
    sec = float(a.get("movingDuration") or a.get("duration") or 0)
    pace = None
    if is_run and km > 0:
        s = round(sec / km)
        pace = f"{s // 60}:{s % 60:02d}"
    cad = a.get("averageRunningCadenceInStepsPerMinute")
    return {
        "date": (a.get("startTimeLocal") or "")[:10],
        "start": a.get("startTimeLocal"),
        "type": key,
        "name": a.get("activityName"),
        "km": km,
        "min": round(sec / 60, 1),
        "pace": pace,
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "cadence": None if cad is None else round(float(cad)),
        "activity_id": a.get("activityId"),
        "te_aer": None if a.get("aerobicTrainingEffect") is None else round(float(a["aerobicTrainingEffect"]), 1),
        "te_anaer": None if a.get("anaerobicTrainingEffect") is None else round(float(a["anaerobicTrainingEffect"]), 1),
        "load": None if a.get("activityTrainingLoad") is None else round(float(a["activityTrainingLoad"])),
        "te_label": a.get("trainingEffectLabel"),
        "is_run": is_run,
    }


def run_rollup(activities: list[dict]) -> dict[str, dict]:
    """Per-date run totals; avg_hr is time-weighted across the day's runs."""
    acc: dict[str, dict] = defaultdict(lambda: {"km": 0.0, "n": 0, "hr_x_min": 0.0, "min_with_hr": 0.0})
    for a in activities:
        if not a.get("is_run"):
            continue
        r = acc[a["date"]]
        r["km"] += a["km"]; r["n"] += 1
        if a.get("avg_hr") is not None and a["min"] > 0:
            r["hr_x_min"] += a["avg_hr"] * a["min"]; r["min_with_hr"] += a["min"]
    return {d: {"run_km": round(r["km"], 2), "run_n": r["n"],
                "run_avg_hr": round(r["hr_x_min"] / r["min_with_hr"]) if r["min_with_hr"] else None}
            for d, r in acc.items()}


def parse_weighins(raw: dict) -> dict[str, dict]:
    """date -> {weight kg, weight_n, weight_src} from the cached dailyWeightSummaries (grams in the API)."""
    out: dict[str, dict] = {}
    for d, s in (raw or {}).items():
        lw = s.get("latestWeight") or {}
        if lw.get("weight") is None:
            continue
        out[d] = {"weight": round(float(lw["weight"]) / 1000, 2), "weight_n": s.get("numOfWeightEntries"),
                  "weight_src": lw.get("sourceType")}
    return out


def _hms(sec) -> str | None:
    if sec is None:
        return None
    s = round(float(sec)); h, m = divmod(s // 60, 60)
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"


def _device_entry(dto_map) -> dict:
    """The primary-device entry of a Garmin {deviceId: {...}} map ({} when absent)."""
    entries = [v for v in (dto_map or {}).values() if isinstance(v, dict)]
    return next((v for v in entries if v.get("primaryTrainingDevice")), entries[0] if entries else {})


def parse_fitness(date: str, blob: dict | None) -> dict:
    """One garmin-fitness row from {training_status, race_predictions, lactate_threshold}."""
    blob = blob or {}
    ts = blob.get("training_status") or {}
    vo2 = (ts.get("mostRecentVO2Max") or {}).get("generic") or {}
    # shapes checked 2026-09-27 on the real files; load_lo/load_hi = Garmin's optimal acute-load range
    st = _device_entry((ts.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData"))
    acute = st.get("acuteTrainingLoadDTO") or {}
    lb = _device_entry((ts.get("mostRecentTrainingLoadBalance") or {}).get("metricsTrainingLoadBalanceDTOMap"))
    rp = blob.get("race_predictions") or {}
    if isinstance(rp, list):
        rp = rp[0] if rp else {}
    lt = (blob.get("lactate_threshold") or {}).get("speed_and_heart_rate") or {}
    return {"date": date,
            "vo2max": _first(vo2.get("vo2MaxPreciseValue"), vo2.get("vo2MaxValue")),
            "vo2max_date": vo2.get("calendarDate"),
            "pred_5k": _hms(rp.get("time5K")), "pred_10k": _hms(rp.get("time10K")),
            "pred_hm": _hms(rp.get("timeHalfMarathon")),
            "lt_hr": lt.get("heartRate"),
            "lt_date": (lt.get("calendarDate") or "")[:10] or None,
            "status": st.get("trainingStatusFeedbackPhrase"), "status_since": st.get("sinceDate"),
            "load_acute": acute.get("dailyTrainingLoadAcute"), "load_chronic": acute.get("dailyTrainingLoadChronic"),
            "load_lo": acute.get("minTrainingLoadChronic"), "load_hi": acute.get("maxTrainingLoadChronic"),
            "acwr": acute.get("dailyAcuteChronicWorkloadRatio"),
            "balance": lb.get("trainingBalanceFeedbackPhrase"),
            "anaer": lb.get("monthlyLoadAnaerobic"), "anaer_lo": lb.get("monthlyLoadAnaerobicTargetMin"),
            "anaer_hi": lb.get("monthlyLoadAnaerobicTargetMax"),
            "aer_hi": lb.get("monthlyLoadAerobicHigh"), "aer_hi_lo": lb.get("monthlyLoadAerobicHighTargetMin"),
            "aer_hi_hi": lb.get("monthlyLoadAerobicHighTargetMax"),
            "aer_lo": lb.get("monthlyLoadAerobicLow"), "aer_lo_lo": lb.get("monthlyLoadAerobicLowTargetMin"),
            "aer_lo_hi": lb.get("monthlyLoadAerobicLowTargetMax")}


# ---------- .FIT VO2max (pure; for the Personal API) ----------
# The Personal API has no VO2max reply, but the watch writes its estimate into each run's .FIT file:
# undocumented message 140, field 7, in units of 3.5/65536 ml/kg/min (other users' reverse engineering;
# 52.7 on the Oct 23, 2026 run, the committed vo2max then). Only that one field is decoded here.

FIT_VO2_MSG, FIT_VO2_FIELD = 140, 7


def fit_vo2max(data: bytes) -> float | None:
    """The VO2max in a .FIT file (one decimal), or None when the message is absent or out of range."""
    pos, defs, found = 0, {}, None
    while pos + 12 <= len(data) and data[pos + 8:pos + 12] == b".FIT":   # files may be chained
        hsize, size = data[pos], int.from_bytes(data[pos + 4:pos + 8], "little")
        i, end, defs = pos + hsize, pos + hsize + size, {}
        while i < end:
            h = data[i]; i += 1
            compressed = bool(h & 0x80)        # compressed timestamp header: a data record without field 253
            if compressed:
                local, is_def, dev = (h >> 5) & 3, False, False
            else:
                local, is_def, dev = h & 0x0F, bool(h & 0x40), bool(h & 0x20)
            if is_def:
                order = "big" if data[i + 1] else "little"
                num, n = int.from_bytes(data[i + 2:i + 4], order), data[i + 4]
                fields = [(data[i + 5 + 3 * k], data[i + 6 + 3 * k]) for k in range(n)]
                i += 5 + 3 * n
                dev_size = 0
                if dev:
                    nd = data[i]
                    dev_size = sum(data[i + 2 + 3 * k] for k in range(nd))
                    i += 1 + 3 * nd
                defs[local] = (num, order, fields, dev_size)
                continue
            if local not in defs:
                return found                  # a record without its definition: the file is damaged
            num, order, fields, dev_size = defs[local]
            for fnum, fsize in fields:
                if compressed and fnum == 253:   # its timestamp is in the header, not the payload
                    continue
                if num == FIT_VO2_MSG and fnum == FIT_VO2_FIELD and fsize == 4:
                    raw = int.from_bytes(data[i:i + 4], order)
                    v = raw * 3.5 / 65536
                    if raw != 0xFFFFFFFF and 20 <= v <= 90:
                        found = round(v, 1)
                i += fsize
            i += dev_size
        pos = end + 2                          # past the file CRC
    return found


# ---------- compare (pure) ----------

def compare(garmin_rows: list[dict], apple_rows: list[dict], start: datetime.date, end: datetime.date):
    """Per-day (apple, garmin, garmin-apple) triples + mean offsets over days where both exist."""
    g = {r["date"]: r for r in garmin_rows}
    a = {r["date"]: r for r in apple_rows}
    rows, deltas = [], defaultdict(list)
    d = start
    while d <= end:
        k = d.isoformat()
        row = {"date": k}
        for label, ak, gk in COMPARE_METRICS:
            av, gv = a.get(k, {}).get(ak), g.get(k, {}).get(gk)
            delta = round(gv - av, 2) if av is not None and gv is not None else None
            row[label] = (av, gv, delta)
            if delta is not None:
                deltas[label].append(delta)
        rows.append(row)
        d += datetime.timedelta(days=1)
    summary = {label: ((round(sum(v) / len(v), 2), len(v)) if (v := deltas.get(label)) else (None, 0))
               for label, _, _ in COMPARE_METRICS}
    return rows, summary


def _f(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return str(v)
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _d(v) -> str:
    if v is None:
        return "-"
    s = _f(abs(v))
    return ("+" if v > 0 else "-" if v < 0 else "") + s


def format_compare(rows: list[dict], summary: dict) -> str:
    cols = [label for label, _, _ in COMPARE_METRICS]
    w = 20
    out = ["Apple (daily.csv) vs Garmin — each cell: Apple / Garmin / Garmin-Apple",
           "date        " + "".join(f"{c:<{w}}" for c in cols)]
    for r in rows:
        cells = [f"{_f(r[c][0])} / {_f(r[c][1])} / {_d(r[c][2])}" for c in cols]
        out.append(f"{r['date']}  " + "".join(f"{c:<{w}}" for c in cells))
    out.append("mean offset (Garmin - Apple, n days both present):")
    means = [f"{_d(summary[c][0])} (n={summary[c][1]})" for c in cols]
    out.append("            " + "".join(f"{m:<{w}}" for m in means))
    out.append("note: hrv is Apple SDNN vs Garmin overnight RMSSD — a scale change, not an error; "
               "Garmin needs ~3 weeks of nights for its own baseline.")
    return "\n".join(out)


# ---------- raw cache <-> CSVs ----------

def _raw_dir(root: pathlib.Path) -> pathlib.Path:
    return root / "data" / "garmin-raw"


def _read_apple_daily(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#")]
    rows = []
    for r in csv.DictReader(lines):
        row = {"date": r["date"]}
        for _, ak, _ in COMPARE_METRICS:
            v = r.get(ak)
            row[ak] = float(v) if v not in (None, "") else None
        rows.append(row)
    return rows


def rows_from_raw(raw: pathlib.Path):
    """Rows for every day file in a raw cache dir. Returns (daily, activities, fitness or None)."""
    day_files = sorted(p for p in raw.glob("????-??-??.json"))
    acts_file = raw / "activities.json"
    acts_raw = json.loads(acts_file.read_text(encoding="utf-8")) if acts_file.exists() else {}
    activities = sorted((parse_activity(a) for a in acts_raw.values()), key=lambda x: x["start"] or "")
    runs = run_rollup(activities)
    wi_file = raw / "weighins.json"
    weighins = parse_weighins(json.loads(wi_file.read_text(encoding="utf-8")) if wi_file.exists() else {})
    loads = _day_loads(activities)
    daily = []
    for p in day_files:
        blob = json.loads(p.read_text(encoding="utf-8"))
        row = parse_day(p.stem, blob.get("stats"), blob.get("hrv"), blob.get("sleep"),
                        blob.get("resp"), blob.get("readiness"))
        if row["acute_load"] is None and acts_file.exists():   # no Garmin value: the approximation, marked
            row["acute_load"] = approx_acute_load(loads, p.stem)
            row["acute_src"] = None if row["acute_load"] is None else "approx"
        row.update(runs.get(p.stem, {}))
        row.update(weighins.get(p.stem, {"weight": None, "weight_n": None, "weight_src": None}))
        daily.append(row)
    if acts_file.exists():
        fill_est_readiness(daily, loads)
    fitness = None
    fit_file = raw / "fitness.json"
    if fit_file.exists():
        fit_raw = json.loads(fit_file.read_text(encoding="utf-8"))
        fitness = [parse_fitness(d, fit_raw[d]) for d in sorted(fit_raw)]
    return daily, activities, fitness


def _write_all(root: pathlib.Path, daily: list[dict], activities: list[dict], fitness: list[dict] | None):
    write_csv(root / "data" / "garmin-daily.csv", GARMIN_DAILY_COLUMNS, daily, GARMIN_DAILY_HEADER)
    write_csv(root / "data" / "garmin-activities.csv", GARMIN_ACTIVITY_COLUMNS, activities, GARMIN_ACTIVITY_HEADER)
    if fitness is not None:
        write_csv(root / "data" / "garmin-fitness.csv", GARMIN_FITNESS_COLUMNS, fitness, GARMIN_FITNESS_HEADER)


def build_from_raw(root: pathlib.Path):
    """Rebuild both CSVs from data/garmin-raw/. Returns (daily_rows, activity_rows)."""
    daily, activities, fitness = rows_from_raw(_raw_dir(root))
    _write_all(root, daily, activities, fitness)
    return daily, activities


# ---------- merge (cloud): a fetched window into the committed CSVs ----------
# A fresh cloud clone has no raw cache, so the fetched window is merged row by row. Old rows are
# kept as read (strings), so rows outside the window come back byte for byte. Like the PC's
# cumulative cache, nothing is ever deleted: activities and weigh-ins are upserted, and a call
# that failed (None blob, or no activities.json, which fetch() then leaves unwritten) keeps the
# old columns it feeds, so one flaky call never blanks committed data.

_RUN_COLS = ("run_km", "run_n", "run_avg_hr")
_WEIGHT_COLS = ("weight", "weight_n", "weight_src")
# columns each day call feeds (parse_day); rhr and hrv_night fall back to sleep, so a failed
# stats or hrv call keeps them too
_PART_COLS = {
    "stats": ("rhr", "bb_high", "bb_low", "stress_avg", "steps"),
    "hrv": ("hrv_night", "hrv_weekly", "hrv_status", "hrv_lo", "hrv_hi"),
    "sleep": ("sleep_h", "deep_h", "light_h", "rem_h", "awake_h", "sleep_score"),
    "resp": ("resp_sleep", "resp_wake"),
    "readiness": ("readiness", "readiness_level", "acute_load", "recovery_min", "acute_src", "readiness_src"),
}


def _day_loads(activities: list[dict]) -> dict[str, float]:
    """Garmin's activity load summed per date (CSV strings or parsed numbers)."""
    out: dict[str, float] = defaultdict(float)
    for a in activities:
        if a.get("load") not in (None, ""):
            out[a["date"]] += float(a["load"])
    return out


ACUTE_TAU, ACUTE_DAYS = 4.5, 42   # decay in days (a load k days old counts e^(-k/4.5)), window
_ACUTE_W = [math.exp(-k / ACUTE_TAU) for k in range(ACUTE_DAYS)]
_ACUTE_SCALE = 7 / sum(_ACUTE_W)   # a steady daily load x reads 7x, as a 7-day sum would


def approx_acute_load(loads: dict[str, float], day: str) -> int | None:
    """Garmin's acute load approximated from activity loads ending on `day`: a sum that fades each day's
    load by e^(-k/4.5). Against Garmin's own value Oct 1 to 22, 2026 it was off by 12% on average and 33%
    at worst (a plain 7-day sum: 18% and 51%); 4.5 days came out best on either half of Sep 26 to Oct 22.
    None when the activities don't reach back 14 days (the older weights add up to 4%)."""
    d = datetime.date.fromisoformat(day)
    days = [(d - datetime.timedelta(days=k)).isoformat() for k in range(ACUTE_DAYS)]
    if not loads or min(loads) > days[13]:
        return None
    return round(_ACUTE_SCALE * sum(w * loads.get(k, 0.0) for w, k in zip(_ACUTE_W, days)))


CHRONIC_DAYS = 28
LOW_AEROBIC_LABELS = {"AEROBIC_BASE", "RECOVERY"}


def est_chronic_load(loads: dict[str, float], day: str) -> int | None:
    """Our chronic load for `day`: the activity loads of the last 28 days (today's included) over 4, the average
    week. On Oct 21, 2026 it gave 471 against Garmin's 492 (its only training status the Personal API move left).
    None when the activities don't reach back 28 days."""
    d = datetime.date.fromisoformat(day)
    days = [(d - datetime.timedelta(days=k)).isoformat() for k in range(CHRONIC_DAYS)]
    if not loads or min(loads) > days[-1]:
        return None
    return round(sum(loads.get(k, 0.0) for k in days) / 4)


def est_load_focus(activities: list[dict], day: str) -> dict[str, int] | None:
    """Our 4-week load focus for `day`: {"anaer", "aer_hi", "aer_lo"}, the last 28 days' activity load split
    the way Garmin's Oct 21, 2026 focus reads (531, 562, 780; this gave 536, 577, 772): an activity whose
    te_label is AEROBIC_BASE or RECOVERY is all low aerobic, any other splits its load into anaerobic and high
    aerobic by its anaerobic and aerobic training effect. One with no te_label (Garmin gave none, or a row
    from before Oct 24, 2026 that the merge has not refetched yet) is low aerobic under an anaerobic effect
    of 2. Rows are CSV strings or parsed numbers, dates strings or dates. None when the activities don't
    reach back 28 days."""
    d = datetime.date.fromisoformat(day)
    lo = (d - datetime.timedelta(days=CHRONIC_DAYS - 1)).isoformat()
    dated = [(str(a["date"]), a) for a in activities]
    if not dated or min(k for k, _ in dated) > lo:
        return None
    out = {"anaer": 0.0, "aer_hi": 0.0, "aer_lo": 0.0}
    for k, a in dated:
        if not lo <= k <= day or a.get("load") in (None, ""):
            continue
        load, label = float(a["load"]), a.get("te_label") or None
        ae, an = (float(a[c]) if a.get(c) not in (None, "") else 0.0 for c in ("te_aer", "te_anaer"))
        if label in LOW_AEROBIC_LABELS or (label is None and an < 2) or ae + an == 0:
            out["aer_lo"] += load
        else:
            out["anaer"] += load * an / (ae + an)
            out["aer_hi"] += load * ae / (ae + an)
    return {k: round(v) for k, v in out.items()}


def missing_te_label(activities: list[dict], end: datetime.date) -> datetime.date | None:
    """The first date of the last 28 days with a loaded activity that has no te_label, else None."""
    lo = (end - datetime.timedelta(days=CHRONIC_DAYS - 1)).isoformat()
    days = [a["date"] for a in activities if lo <= a["date"] <= end.isoformat()
            and a.get("load") not in (None, "") and not a.get("te_label")]
    return datetime.date.fromisoformat(min(days)) if days else None


READY_TAU, READY_F = 1.5, 200   # fatigue fade in days, and the fatigue that halves the sleep base
_READY_W = [math.exp(-k / READY_TAU) for k in range(14)]


def readiness_level(score: int) -> str:
    """Garmin's bands for a readiness score."""
    return ("POOR" if score < 25 else "LOW" if score < 50 else "MODERATE" if score < 75
            else "HIGH" if score < 95 else "PRIME")


def est_readiness(sleep: dict[str, float], loads: dict[str, float], day: str) -> int | None:
    """Our training readiness for `day` (Garmin's own is not in the Personal API): a sleep base,
    0.8 x the night's sleep score + 0.2 x the mean of the last three, divided by 1 + (fatigue/200)^2,
    where fatigue sums the activity loads of the last 14 days, today's included, each faded by
    e^(-days/1.5). Against Garmin's readiness Sep 19 to Oct 22, 2026 (34 days) it was off by 8 points on
    average and 32 at worst (race days, where Garmin bottoms at 1) and gave Garmin's level on 26 days;
    fitted on earlier days only, it was off by 9. HRV did not improve it. None without the night's sleep score."""
    if sleep.get(day) is None:
        return None
    d = datetime.date.fromisoformat(day)
    days = [(d - datetime.timedelta(days=k)).isoformat() for k in range(14)]
    nights = [sleep[k] for k in days[:3] if sleep.get(k) is not None]
    base = 0.8 * sleep[day] + 0.2 * sum(nights) / len(nights)
    fatigue = sum(w * loads.get(k, 0.0) for w, k in zip(_READY_W, days))
    return max(1, min(100, round(base / (1 + (fatigue / READY_F) ** 2))))


def fill_est_readiness(rows: list[dict], loads: dict[str, float], days=None):
    """Fill readiness from est_readiness on the rows (of `days`, default all) that have no Garmin
    readiness, marked readiness_src est. Rows are CSV strings or parsed numbers."""
    sleep = {r["date"]: float(r["sleep_score"]) for r in rows if r.get("sleep_score") not in (None, "")}
    for r in rows:
        if days is not None and r["date"] not in days:
            continue
        if r.get("readiness") not in (None, "") and r.get("readiness_src") != "est":
            continue
        score = est_readiness(sleep, loads, r["date"])
        r["readiness"] = score
        r["readiness_level"] = None if score is None else readiness_level(score)
        r["readiness_src"] = None if score is None else "est"


def read_csv_rows(path: pathlib.Path) -> list[dict]:
    """Rows of a CSV write_csv wrote (comment lines skipped), values as strings; [] if missing."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(l for l in f if not l.startswith("#")))


def merge_into(root: pathlib.Path, raw: pathlib.Path, start: datetime.date, end: datetime.date,
               acts_start: datetime.date | None = None) -> tuple[int, int]:
    """Merge the start..end window cached in `raw` into root/data/*.csv; activities from acts_start (default
    start), which may be earlier. Returns (days replaced, window activities)."""
    data = root / "data"
    lo, hi = start.isoformat(), end.isoformat()
    acts_lo = min(start, acts_start or start).isoformat()
    acts_ok = (raw / "activities.json").exists()
    wi_file = raw / "weighins.json"
    window_wi = parse_weighins(json.loads(wi_file.read_text(encoding="utf-8"))) if wi_file.exists() else {}
    new_daily, new_acts, new_fit = rows_from_raw(raw)

    activities = read_csv_rows(data / "garmin-activities.csv")
    window_acts = [a for a in new_acts if acts_lo <= a["date"] <= hi] if acts_ok else []
    ids = {str(a["activity_id"]) for a in window_acts}
    kept = [r for r in activities if r["activity_id"] not in ids]
    # a day whose committed activity is missing from the reply (deleted in Garmin, or a short reply)
    # keeps its old run columns, as the PC's cache would
    short_days = {r["date"] for r in kept if lo <= r["date"] <= hi} if acts_ok else set()
    activities = sorted(kept + window_acts, key=lambda x: x["start"] or "")

    daily = {r["date"]: r for r in read_csv_rows(data / "garmin-daily.csv")}
    loads = _day_loads(activities) if acts_ok else None
    replaced = 0
    for row in new_daily:
        d = row["date"]
        if not lo <= d <= hi:
            continue
        blob = json.loads((raw / f"{d}.json").read_text(encoding="utf-8"))
        # an empty reply counts as failed too: at worst the day keeps its own earlier value
        if not any(blob.get(p) for p in _PART_COLS):   # every call failed: a blank row would hide good data
            continue
        old = daily.get(d)
        if old:
            for part, cols in _PART_COLS.items():
                if not blob.get(part):
                    row.update({c: old.get(c) for c in cols})
            if not acts_ok or d in short_days:
                row.update({c: old.get(c) for c in _RUN_COLS})
            if d not in window_wi:
                row.update({c: old.get(c) for c in _WEIGHT_COLS})
        if not blob.get("readiness") and loads is not None and (row.get("acute_load") in (None, "")
                                                               or row.get("acute_src") == "approx"):
            row["acute_load"] = approx_acute_load(loads, d)
            row["acute_src"] = None if row["acute_load"] is None else "approx"
        daily[d] = row
        replaced += 1
    if loads is not None:   # after the loop, so a night's estimate sees the merged nights before it
        merged = [daily[d] for d in sorted(daily)]
        fill_est_readiness(merged, loads, {r["date"] for r in new_daily if lo <= r["date"] <= hi})

    fitness = None
    if new_fit is not None:
        by_date = {r["date"]: r for r in read_csv_rows(data / "garmin-fitness.csv")}
        for r in new_fit:   # a rerun on the same date keeps what the earlier pull had and this one lacks
            old = by_date.get(r["date"]) or {}
            by_date[r["date"]] = {c: (old.get(c) if r.get(c) is None else r[c]) for c in GARMIN_FITNESS_COLUMNS}
        fitness = [by_date[d] for d in sorted(by_date)]

    _write_all(root, [daily[d] for d in sorted(daily)], activities, fitness)
    return replaced, len(window_acts)


# ---------- activity analysis (pure) ----------
# One run, rep by rep: hard segments are detected from the per-second speed stream (rolling mean
# faster than --rep-pace), so it works whether or not the lap button was pressed.

ACTIVITY_PARTS = ("summary", "splits", "typed_splits", "hrzones", "details")
DEFAULT_REP_PACE = "4:42"      # min/km; anything faster counts as a rep


def pace_str(metres, seconds) -> str | None:
    if not metres or metres <= 0:
        return None
    s = round(seconds / metres * 1000)
    return f"{s // 60}:{s % 60:02d}"


def pace_to_mps(p: str) -> float:
    m, s = p.split(":")
    return 1000 / (int(m) * 60 + int(s))


def _mmss(seconds) -> str:
    s = round(seconds)
    return f"{s // 60}:{s % 60:02d}"


def stream_columns(details: dict) -> dict[str, list]:
    keys = [m["key"] for m in details.get("metricDescriptors", [])]
    rows = [m["metrics"] for m in details.get("activityDetailMetrics", [])]
    return {k: [r[i] for r in rows] for i, k in enumerate(keys)}


def _smooth(x, w):
    out = []
    for i in range(len(x)):
        seg = [v for v in x[max(0, i - w // 2): i + w // 2 + 1] if v is not None]
        out.append(sum(seg) / len(seg) if seg else 0.0)
    return out


def detect_reps(t, dist, speed, thr_mps, min_s=45, gap_s=12, smooth_w=11) -> list[tuple[int, int]]:
    """Index pairs [a, b) where the smoothed speed stays above thr_mps; short gaps merge, blips drop."""
    ss = _smooth(speed, smooth_w)
    n = len(ss); segs: list[tuple[int, int]] = []; i = 0
    while i < n:
        if ss[i] > thr_mps:
            j = i
            while j < n and ss[j] > thr_mps:
                j += 1
            if segs and t[i] - t[segs[-1][1] - 1] < gap_s:
                segs[-1] = (segs[-1][0], j)
            else:
                segs.append((i, j))
            i = j
        else:
            i += 1
    return [(a, b) for a, b in segs if t[b - 1] - t[a] >= min_s]


def _avg(x):
    x = [v for v in x if v is not None]
    return round(sum(x) / len(x), 1) if x else None


def _max(x):
    x = [v for v in x if v is not None]
    return max(x) if x else None


def analyse_activity(cols: dict[str, list], reps: list[tuple[int, int]], sub_m: int = 200) -> dict:
    t, dist = cols["sumDuration"], cols["sumDistance"]
    n = len(t)
    hr = cols.get("directHeartRate") or [None] * n
    cad = cols.get("directDoubleCadence") or [None] * n          # steps/min, both feet
    stride = cols.get("directStrideLength") or [None] * n        # cm in the stream
    power, gct, vo = (cols.get(k) or [None] * n for k in
                      ("directPower", "directGroundContactTime", "directVerticalOscillation"))

    def seg(a, b):
        m, s = dist[b - 1] - dist[a], t[b - 1] - t[a]
        return {"m": round(m), "s": round(s), "pace": pace_str(m, s), "hr_avg": _avg(hr[a:b]), "hr_max": _max(hr[a:b])}

    out: dict = {"reps": [], "recoveries": [], "warmup": None, "cooldown": None}
    for k, (a, b) in enumerate(reps):
        r = seg(a, b)
        st = _avg(stride[a:b])
        r.update(hr_end=hr[b - 1], cad=_avg(cad[a:b]), stride_m=None if st is None else round(st / 100, 2),
                 power=_avg(power[a:b]), gct=_avg(gct[a:b]), vo=_avg(vo[a:b]))
        subs, start, tgt = [], a, dist[a] + sub_m
        for i in range(a, b):
            if dist[i] >= tgt:
                subs.append(pace_str(dist[i] - dist[start], t[i] - t[start])); start = i; tgt += sub_m
        r["subs"] = subs
        out["reps"].append(r)
        if k:
            pa, pb = reps[k - 1][1], a
            out["recoveries"].append({"s": round(t[pb] - t[pa]), "m": round(dist[pb] - dist[pa]),
                                      "hr_from": hr[pa], "hr_to": hr[pb],
                                      "hr_min": min((v for v in hr[pa:pb] if v is not None), default=None)})
    if reps:
        a, b = reps[0][0], reps[-1][1]
        out["warmup"] = seg(0, a + 1) if a > 0 else None
        out["cooldown"] = seg(b - 1, n) if b < n else None
    return out


def _f1(v, unit="", nd=0):
    return "-" if v is None else (f"{v:.{nd}f}{unit}" if isinstance(v, (int, float)) else str(v))


def format_activity(summary: dict, splits: dict, hrzones: list, analysis: dict, rep_pace: str) -> str:
    sd = summary.get("summaryDTO") or summary
    dist, dur = sd.get("distance") or 0, sd.get("duration") or 0
    head = (f"{summary.get('activityName') or '?'} · {sd.get('startTimeLocal') or summary.get('startTimeLocal') or '?'} · "
            f"{dist / 1000:.2f} km · {_mmss(dur)} · avg {pace_str(dist, dur) or '-'}/km · "
            f"HR {_f1(sd.get('averageHR'))}/{_f1(sd.get('maxHR'))} · aerobic TE {_f1(sd.get('trainingEffect'), nd=1)} / "
            f"anaerobic {_f1(sd.get('anaerobicTrainingEffect'), nd=1)} · load {_f1(sd.get('activityTrainingLoad'))}")
    out = [head, "LAPS:"]
    for i, l in enumerate(splits.get("lapDTOs") or [], 1):
        m, s = l.get("distance") or 0, l.get("duration") or 0
        out.append(f"  {i:2d}  {m:5.0f} m  {_mmss(s):>6}  {pace_str(m, s) or '-':>5}/km  HR {_f1(l.get('averageHR'))}/{_f1(l.get('maxHR'))}")
    out.append(f"REPS (rolling speed faster than {rep_pace}/km):")
    if not analysis["reps"]:
        out.append("  none — an easy run, or lower --rep-pace")
    for k, r in enumerate(analysis["reps"], 1):
        out.append(f"  {k:2d}  {r['m']:5d} m  {_mmss(r['s']):>6}  {r['pace'] or '-':>5}/km  HR {_f1(r['hr_avg'])}/{_f1(r['hr_max'])} "
                   f"end {_f1(r['hr_end'])}  cad {_f1(r['cad'])}  stride {_f1(r['stride_m'], ' m', 2)}  power {_f1(r['power'], ' W')}  "
                   f"GCT {_f1(r['gct'], ' ms')}  VO {_f1(r['vo'], ' cm', 1)}  200s: {' '.join(r['subs']) or '-'}")
        if k <= len(analysis["recoveries"]):
            rc = analysis["recoveries"][k - 1]
            out.append(f"      rec {_mmss(rc['s'])}  {rc['m']} m  HR {_f1(rc['hr_from'])} -> {_f1(rc['hr_to'])} (min {_f1(rc['hr_min'])})")
    for label, key in (("WARM-UP", "warmup"), ("COOL-DOWN", "cooldown")):
        w = analysis.get(key)
        if w:
            out.append(f"{label}: {w['m']} m  {_mmss(w['s'])}  {w['pace'] or '-'}/km  HR avg {_f1(w['hr_avg'])}")
    if hrzones:
        out.append("HR ZONES (min): " + " · ".join(f"z{z.get('zoneNumber')} {(z.get('secsInZone') or 0) / 60:.1f}" for z in hrzones))
    return "\n".join(out)


def _activity_files(root: pathlib.Path, aid: str) -> dict[str, pathlib.Path]:
    return {p: _raw_dir(root) / f"activity-{aid}-{p}.json" for p in ACTIVITY_PARTS}


def load_activity_parts(root: pathlib.Path, aid: str) -> dict[str, Any] | None:
    files = _activity_files(root, aid)
    if not all(p.exists() for p in files.values()):
        return None
    return {k: json.loads(p.read_text(encoding="utf-8")) for k, p in files.items()}


def report_activity(parts: dict[str, Any], rep_pace: str) -> str:
    cols = stream_columns(parts["details"])
    reps = detect_reps(cols["sumDuration"], cols["sumDistance"], cols["directSpeed"], pace_to_mps(rep_pace))
    return format_activity(parts["summary"], parts["splits"], parts["hrzones"], analyse_activity(cols, reps), rep_pace)


# ---------- Garmin Connect (network) ----------

def _cloud_token() -> str | None:
    """The cloud's GARMINTOKENS secret (inline token JSON), or None on the PC."""
    return os.getenv("GARMINTOKENS") or None


def _jwt_claim_date(token: str, claim: str) -> datetime.date | None:
    """UTC date of a numeric claim in a JWT's payload; None when unreadable. Only the date ever leaves here."""
    try:
        payload = token.split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))[claim]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).date()
    except Exception:
        return None


def _access_claim_date(tokens_json: str, claim: str) -> datetime.date | None:
    """`iat`/`exp` of the secret's access token. The refresh token is opaque: it carries no date at all."""
    try:
        return _jwt_claim_date(json.loads(tokens_json)["di_token"], claim)
    except Exception:
        return None


# What this run's token refresh showed (cloud only): flags, an HTTP status and a lifetime, never token text
TOKEN_SEEN: dict[str, Any] = {}


def _refresh_lifetime(body: dict) -> float | None:
    """Seconds a refresh token lives, if Garmin's refresh reply says (OAuth2 `refresh_token_expires_in`)."""
    v = body.get("refresh_token_expires_in")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        return None
    return float(v)


def _watch_refresh(client, seen: dict[str, Any]) -> None:
    """Wrap the library's private DI token POST (garminconnect 0.3.x) to note what a refresh reply says."""
    post = getattr(client, "_di_token_post", None)
    seen["watched"] = callable(post)
    if not callable(post):
        return
    def watched(client_id, accept, data):
        if data.get("grant_type") != "refresh_token":
            return post(client_id, accept, data)
        seen.update(refreshed=False, status=None)
        r = post(client_id, accept, data)
        seen["status"] = getattr(r, "status_code", None)
        if getattr(r, "ok", False):
            seen["refreshed"] = True
            try:
                body = r.json()
            except Exception:
                body = {}
            body = body if isinstance(body, dict) else {}
            new = body.get("refresh_token")
            seen["rotated"] = bool(new) and new != data.get("refresh_token")
            seen["lifetime_s"] = _refresh_lifetime(body)
        return r
    client._di_token_post = watched


def token_line(seen: dict[str, Any], tokens_json: str, today: datetime.date) -> str:
    """The daily report's TOKEN line: what this run learned about the frozen GARMINTOKENS refresh token."""
    if "watched" not in seen:
        return "TOKEN: not used this run"
    if not seen["watched"]:
        return "TOKEN: refresh not watched (garminconnect changed); a dead token still shows as PULL failed"
    if "refreshed" not in seen:
        good = _access_claim_date(tokens_json, "exp")
        return "TOKEN: no refresh needed" + (f", access token good until {good.isoformat()}" if good else "")
    if not seen["refreshed"]:
        if seen.get("status") is None:
            return "TOKEN: refresh got no reply (network); token state unknown"
        return f"TOKEN: WARN refresh rejected (HTTP {seen['status']}), update GARMINTOKENS from the PC"
    rotation = "Garmin rotates refresh tokens" if seen.get("rotated") else "Garmin kept the same refresh token"
    life = seen.get("lifetime_s")
    if not life:
        return f"TOKEN: refresh ok; {rotation}; no lifetime in the reply"
    days = round(life / 86400)
    issued = _access_claim_date(tokens_json, "iat") if seen.get("rotated") else None
    if issued is None:   # not rotated: the saved token may date from the PC's login, start unknown
        return f"TOKEN: refresh ok; {rotation}; lifetime {days} d, the saved token's start date unknown"
    ends = issued + datetime.timedelta(seconds=life)
    if (ends - today).days < 7:
        return f"TOKEN: WARN saved refresh token ends ~{ends.isoformat()}, update GARMINTOKENS from the PC"
    return f"TOKEN: refresh ok; {rotation}; saved refresh token ends ~{ends.isoformat()} ({days} d lifetime)"


def _connect():
    from garminconnect import Garmin   # lazy: tests and the lint never need the library
    api = Garmin()
    if _cloud_token():
        TOKEN_SEEN.clear()
        _watch_refresh(api.client, TOKEN_SEEN)
    # No argument makes the library read GARMINTOKENS; passing the path would override the secret.
    api.login(None if _cloud_token() else TOKENSTORE)
    return api


# ---------- Garmin Personal API (official; the only source since Oct 24, decision-log 2026-10-24) ----------
# Garmin's free read-only API (Oct 21, 2026): a key the athlete creates in Garmin Connect web, swapped for a
# 24 h bearer token on every run (Garmin's client, github.com/garmin/connect-personal-api-python).
# It has no Training Readiness, recovery time, training status or race predictor endpoints, so a
# run leaves those columns as they were; readiness is our estimate (est_readiness), VO2max comes from
# the newest run's .FIT file, the threshold HR from the HR zones, and the acute load is approximated.
# A reply without the fields parse_day reads raises, so the merge treats it as a failed call and
# keeps the committed values instead of blanking them.

PERSONAL_API_KEY_ENV = "GARMIN_PERSONAL_API_KEY"
PERSONAL_API_URL = "https://personal.connectapi.garmin.com"
PERSONAL_TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
_PERSONAL_STATS_KEYS = ("restingHeartRate", "totalSteps", "averageStressLevel", "bodyBatteryHighestValue")


def _personal_key() -> str | None:
    return os.getenv(PERSONAL_API_KEY_ENV) or None


class PersonalApi:
    """The getters fetch() calls, over the Personal API. `missing` = the parts it has no endpoint for."""
    missing = frozenset({"readiness", "race_predictions"})
    FIT_ACCEPT = "application/zip, application/x-zip-compressed, application/octet-stream"   # anything else: 406

    def __init__(self, key: str, session=None):
        import requests   # lazy, like garminconnect
        self._s = session or requests.Session()
        r = self._s.post(PERSONAL_API_URL + PERSONAL_TOKEN_PATH, timeout=30,
                         headers={"Accept": "*/*", "Authorization": f"ApiKey {key}"})
        if not r.ok:
            raise RuntimeError(f"Personal API key rejected (HTTP {r.status_code})")
        self._headers = {"Accept": "application/json", "Authorization": f"Bearer {r.text.strip()}"}
        self._stats: dict[str, dict] = {}
        self._sleep: dict[str, dict] = {}

    def _get(self, path: str, **params):
        r = self._s.get(PERSONAL_API_URL + path, headers=self._headers, params=params or None, timeout=30)
        if not r.ok:   # the reply text is left out: it may echo the request
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.json() if r.content else None

    def get_stats(self, day: str) -> dict:
        """Garmin's client reads v2 daily summaries ({"data": [...]}, even for one day); the Swagger also lists
        the unofficial daily path, tried when v2 fails or lacks the fields parse_day reads."""
        for path, params in (("/usersummary-service/v2/dailysummaries", {"startDate": day, "endDate": day}),
                             ("/usersummary-service/usersummary/daily", {"calendarDate": day})):
            try:
                reply = self._get(path, **params)
            except RuntimeError:
                continue
            rows = (reply.get("data") or []) if isinstance(reply, dict) and "data" in reply else [reply]
            for s in rows:
                if (isinstance(s, dict) and s.get("calendarDate") in (day, None)
                        and any(s.get(k) is not None for k in _PERSONAL_STATS_KEYS)):
                    self._stats[day] = s
                    return s
        raise ValueError("daily summary has none of the fields read here")

    def get_hrv_data(self, day: str) -> dict:
        h = self._get(f"/hrv-service/hrv/{day}")
        if not isinstance(h, dict) or not h.get("hrvSummary"):
            raise ValueError("no hrvSummary in the reply")
        return h

    def get_sleep_data(self, day: str) -> dict:
        s = self._get("/sleep-service/sleep/dailySleep", date=day)
        if isinstance(s, dict) and "dailySleepDTO" not in s and s.get("sleepTimeSeconds") is not None:
            s = {"dailySleepDTO": s}   # parse_day reads the unofficial shape
        if not isinstance(s, dict) or (s.get("dailySleepDTO") or {}).get("sleepTimeSeconds") is None:
            raise ValueError("no sleep time in the reply")
        self._sleep[day] = s
        return s

    def get_respiration_data(self, day: str) -> dict:
        """No endpoint of its own: the sleep record and the daily summary carry the two averages."""
        resp = {"avgSleepRespirationValue": (self._sleep.get(day, {}).get("dailySleepDTO") or {})
                .get("averageRespirationValue"),
                "avgWakingRespirationValue": self._stats.get(day, {}).get("avgWakingRespirationValue")}
        if all(v is None for v in resp.values()):
            raise ValueError("no respiration in the sleep record or the daily summary")
        return resp

    def get_lactate_threshold(self) -> dict:
        """No threshold endpoint: the HR zones carry the threshold HR they use (undated)."""
        zones = self._get("/biometric-service/heartRateZones/v2") or []
        by_sport = {z.get("sport"): z for z in zones if isinstance(z, dict)}
        lt = (by_sport.get("RUNNING") or by_sport.get("DEFAULT") or {}).get("lactateThresholdHeartRateUsed")
        if lt is None:
            raise ValueError("no lactate threshold HR in the HR zones")
        return {"speed_and_heart_rate": {"heartRate": lt}}

    def get_training_status(self, day: str) -> dict:
        """Only the VO2max part, in the unofficial shape: the newest of the last 14 days' runs whose .FIT
        file carries one (at most 3 files are downloaded)."""
        start = (datetime.date.fromisoformat(day) - datetime.timedelta(days=13)).isoformat()
        runs = sorted((a for a in self.get_activities_by_date(start, day) if parse_activity(a)["is_run"]),
                      key=lambda a: a.get("startTimeLocal") or "", reverse=True)
        for a in runs[:3]:
            v = fit_vo2max(self._activity_fit(a["activityId"]))
            if v is not None:
                return {"mostRecentVO2Max": {"generic": {"vo2MaxPreciseValue": v,
                                                         "calendarDate": (a.get("startTimeLocal") or "")[:10]}}}
        raise ValueError("no VO2max in the last runs' .FIT files")

    def _activity_fit(self, aid) -> bytes:
        import io, zipfile
        r = self._s.get(f"{PERSONAL_API_URL}/download-service/files/activity/{aid}", timeout=60,
                        headers={**self._headers, "Accept": self.FIT_ACCEPT})
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code}")
        if not r.content.startswith(b"PK"):
            return r.content
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".fit")), None)
            return z.read(name) if name else b""

    def get_activities_by_date(self, start: str, end: str) -> list:
        out: list = []
        while True:
            page = self._get("/activitylist-service/activities/search/activities",
                             startDate=start, endDate=end, start=len(out), limit=100) or []
            out += page
            if len(page) < 100:
                return out

    def get_weigh_ins(self, start: str, end: str) -> dict:
        w = self._get(f"/weight-service/weight/range/{start}/{end}", includeAll="true")
        if not isinstance(w, dict) or "dailyWeightSummaries" not in w:
            raise ValueError("no dailyWeightSummaries in the reply")
        return w


def _source():
    """The Garmin client: the Personal API whenever its key is set (the only source since Oct 24, 2026,
    decision-log 2026-10-24), else the unofficial login (the PC without a key). None after an error."""
    key = _personal_key()
    if key:
        try:
            api = PersonalApi(key)
        except Exception as e:
            print(f"ERROR Garmin Personal API failed ({type(e).__name__}: {e})")
            print(f"      a rejected key: the athlete renews {PERSONAL_API_KEY_ENV} in Garmin Connect web")
            return None
        print("SOURCE: Garmin Personal API; readiness and acute load are our estimates, "
              "no recovery time, training status or race predictor")
        return api
    try:
        return _connect()
    except Exception as e:                       # no/expired tokens, network, Cloudflare
        if _cloud_token():
            print("ERROR Garmin token rejected: update the GARMINTOKENS secret from the PC")
            print(f"      ({type(e).__name__}: {e})")
        else:
            print(f"ERROR Garmin login failed ({type(e).__name__}: {e})")
            print("      run `python pull_garmin.py --login` once in your own terminal, then retry")
        return None


def fetch(root: pathlib.Path, start: datetime.date, end: datetime.date,
          acts_start: datetime.date | None = None) -> bool:
    """Pull start..end into the raw cache, activities from acts_start (default start). Re-fetches every day in
    range (the window is small)."""
    api = _source()
    if api is None:
        return False
    missing = api.missing if isinstance(api, PersonalApi) else frozenset()
    raw = _raw_dir(root); raw.mkdir(parents=True, exist_ok=True)
    d = start
    while d <= end:
        k = d.isoformat(); blob: dict[str, Any] = {}
        for name, getter in (("stats", "get_stats"), ("hrv", "get_hrv_data"), ("sleep", "get_sleep_data"),
                             ("resp", "get_respiration_data"), ("readiness", "get_training_readiness")):
            if name in missing:
                blob[name] = None
                continue
            try:
                blob[name] = getattr(api, getter)(k)
            except Exception as e:
                print(f"WARN {k} {name}: {type(e).__name__}: {e}")
                blob[name] = None
        (raw / f"{k}.json").write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
        d += datetime.timedelta(days=1)
    fb: dict[str, Any] = {}
    for name, fn in (("training_status", lambda: api.get_training_status(end.isoformat())),
                     ("race_predictions", lambda: api.get_race_predictions()),
                     ("lactate_threshold", lambda: api.get_lactate_threshold())):
        if name in missing:
            fb[name] = None
            continue
        try:
            fb[name] = fn()
        except Exception as e:
            print(f"WARN fitness {name}: {type(e).__name__}: {e}")
            fb[name] = None
    if any(fb.values()):   # every call failed: fitness.json stays unwritten, no empty fitness row
        fit_file = raw / "fitness.json"
        fit = json.loads(fit_file.read_text(encoding="utf-8")) if fit_file.exists() else {}
        fit[end.isoformat()] = fb
        fit_file.write_text(json.dumps(fit, ensure_ascii=False, default=str), encoding="utf-8")
    acts_file = raw / "activities.json"
    acts = json.loads(acts_file.read_text(encoding="utf-8")) if acts_file.exists() else {}
    # activities.json / weighins.json are rewritten only when their call succeeded: --merge reads a
    # missing file as "that call failed, keep the old values"
    try:
        for a in api.get_activities_by_date(min(start, acts_start or start).isoformat(), end.isoformat()):
            acts[str(a["activityId"])] = a
        acts_file.write_text(json.dumps(acts, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"WARN activities: {type(e).__name__}: {e}")
    wi_file = raw / "weighins.json"
    wi = json.loads(wi_file.read_text(encoding="utf-8")) if wi_file.exists() else {}
    try:
        for s in (api.get_weigh_ins(start.isoformat(), end.isoformat()) or {}).get("dailyWeightSummaries") or []:
            if s.get("summaryDate"):
                wi[s["summaryDate"]] = s
        wi_file.write_text(json.dumps(wi, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"WARN weigh-ins: {type(e).__name__}: {e}")
    # the cloud never writes a renewed token back (spec 2026-10-19, 4.1); the Personal API has none to write
    if not _cloud_token() and not isinstance(api, PersonalApi):
        try:
            api.client.dump(str(pathlib.Path(TOKENSTORE).expanduser()))   # persist any refreshed token
        except Exception:
            pass
    return True


def fetch_activity_parts(api, root: pathlib.Path, aid: str) -> dict[str, Any]:
    """Pull summary / laps / typed splits / HR zones / per-second stream for one activity into the cache."""
    getters = {"summary": api.get_activity, "splits": api.get_activity_splits,
               "typed_splits": api.get_activity_typed_splits, "hrzones": api.get_activity_hr_in_timezones,
               "details": lambda i: api.get_activity_details(i, maxchart=5000)}
    files = _activity_files(root, aid); files["summary"].parent.mkdir(parents=True, exist_ok=True)
    parts: dict[str, Any] = {}
    for name, fn in getters.items():
        try:
            parts[name] = fn(aid)
        except Exception as e:
            print(f"WARN activity {aid} {name}: {type(e).__name__}: {e}")
            parts[name] = {} if name != "hrzones" else []
        files[name].write_text(json.dumps(parts[name], ensure_ascii=False), encoding="utf-8")
    return parts


def resolve_activity_ids(spec: str, root: pathlib.Path, api=None) -> list[str]:
    """`--activity` accepts an id, a YYYY-MM-DD (all runs that day) or `latest` (newest run in
    garmin-activities.csv, which the daily routine keeps current; the raw cache when there is no CSV)."""
    if spec.isdigit():
        return [spec]
    if spec == "latest":
        runs = [r for r in read_csv_rows(root / "data" / "garmin-activities.csv") if r["type"] in RUN_KEYS]
        if runs:
            return [max(runs, key=lambda r: r["start"])["activity_id"]]
    acts_file = _raw_dir(root) / "activities.json"
    acts = json.loads(acts_file.read_text(encoding="utf-8")) if acts_file.exists() else {}
    if api is not None and spec != "latest":
        for a in api.get_activities_by_date(spec, spec):
            acts[str(a["activityId"])] = a
        acts_file.parent.mkdir(parents=True, exist_ok=True)
        acts_file.write_text(json.dumps(acts, ensure_ascii=False), encoding="utf-8")
    runs = [a for a in acts.values() if parse_activity(a)["is_run"]]
    if spec == "latest":
        runs = sorted(runs, key=lambda a: a.get("startTimeLocal") or "")[-1:]
    else:
        runs = [a for a in runs if (a.get("startTimeLocal") or "").startswith(spec)]
    return [str(a["activityId"]) for a in runs]


def login_interactive() -> int:
    """One-time credential login; tokens land in ~/.garminconnect. Run by never by an agent."""
    from garminconnect import Garmin
    email = input("Garmin Connect email: ").strip()
    password = getpass.getpass("Garmin Connect password (not echoed): ")
    api = Garmin(email, password, prompt_mfa=lambda: input("MFA code from your email/app: ").strip())
    api.login(TOKENSTORE)
    print(f"logged in as {api.display_name or email}; tokens saved under {TOKENSTORE}")
    return 0


def _activity_mode(root: pathlib.Path, spec: str, rep_pace: str, no_fetch: bool) -> int:
    api = None
    if not no_fetch:
        try:
            api = _connect()
        except Exception as e:
            print(f"ERROR Garmin login failed ({type(e).__name__}: {e})")
            print("      run `python pull_garmin.py --login` once in your own terminal, or add --no-fetch for the cache")
            return 2
    ids = resolve_activity_ids(spec, root, api)
    if not ids:
        print(f"ERROR no run matches --activity {spec}" + (" in the cache (drop --no-fetch?)" if no_fetch else ""))
        return 1
    for aid in ids:
        parts = load_activity_parts(root, aid) if (no_fetch or api is None) else None
        if parts is None and api is not None:
            parts = fetch_activity_parts(api, root, aid)
        if parts is None:
            print(f"ERROR activity {aid} not in the cache (drop --no-fetch)")
            return 1
        print(report_activity(parts, rep_pace))
        print()
    return 0


def _merge_mode(root: pathlib.Path, start: datetime.date | None, end: datetime.date) -> int:
    rows = read_csv_rows(root / "data" / "garmin-daily.csv")
    if not rows:
        print("ERROR no garmin-daily.csv to merge into")
        return 1
    if start is None:   # catch up after a missed day instead of leaving a hole
        start = datetime.date.fromisoformat(max(r["date"] for r in rows)) - datetime.timedelta(days=2)
    # activities committed before te_label (Oct 24, 2026) are fetched again, so the load focus has its 4 weeks
    acts_start = missing_te_label(read_csv_rows(root / "data" / "garmin-activities.csv"), end)
    with tempfile.TemporaryDirectory() as tmp:   # the clone's data/ never gets a raw cache
        if not fetch(pathlib.Path(tmp), start, end, acts_start):
            return 2
        days, acts = merge_into(root, pathlib.Path(tmp) / "data" / "garmin-raw", start, end, acts_start)
    print(f"merged {days} days, {acts} activities ({start} → {end})")
    return 0


# ---------- CLI ----------

def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Pull Garmin Connect daily data and compare it with data/daily.csv.")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--login", action="store_true", help="one-time interactive login (stores tokens)")
    ap.add_argument("--start", default=None,
                    help="YYYY-MM-DD (default: first Fenix day; with --merge, the last CSV day minus 2)")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--no-fetch", action="store_true", help="rebuild the CSVs from the raw cache only")
    ap.add_argument("--merge", action="store_true",
                    help="fetch a window into a temp dir and merge it into the committed CSVs (cloud)")
    ap.add_argument("--activity", default=None, metavar="ID|YYYY-MM-DD|latest",
                    help="rep-by-rep report for one run (skips the daily pull)")
    ap.add_argument("--rep-pace", default=DEFAULT_REP_PACE, metavar="M:SS",
                    help=f"faster than this counts as a rep (default {DEFAULT_REP_PACE}/km)")
    a = ap.parse_args(argv)
    if a.login:
        return login_interactive()
    if not _cloud_token():
        return _run(a)
    try:
        return _run(a)
    finally:   # last, so it reports this run's refresh, even when the login failed
        print(token_line(TOKEN_SEEN, _cloud_token(), datetime.date.today()))


def _run(a) -> int:
    root = pathlib.Path(a.root)
    if a.activity:
        return _activity_mode(root, a.activity, a.rep_pace, a.no_fetch)
    end = datetime.date.fromisoformat(a.end) if a.end else datetime.date.today()
    if a.merge:
        return _merge_mode(root, datetime.date.fromisoformat(a.start) if a.start else None, end)
    start = datetime.date.fromisoformat(a.start) if a.start else FENIX_FIRST_DAY
    if not a.no_fetch and not fetch(root, start, end):
        return 2
    if not list(_raw_dir(root).glob("????-??-??.json")):
        print("ERROR no cached Garmin days under data/garmin-raw — run without --no-fetch (after --login)")
        return 1
    daily, acts = build_from_raw(root)
    print(f"garmin-daily.csv       {len(daily)} rows ({daily[0]['date']} → {daily[-1]['date']})")
    print(f"garmin-activities.csv  {len(acts)} rows ({sum(1 for x in acts if x['is_run'])} runs)")
    apple = _read_apple_daily(root / "data" / "daily.csv")
    rows, summary = compare(daily, apple, start, end)
    print(format_compare(rows, summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
