"""Garmin inputs for Kunto: the three CSVs pull_garmin.py writes, and the extras read from them.

Pure readers. A CSV starts with one "# " comment line, then a header. Empty cell = None.
A row with too few or too many cells, a file that ends mid-line (a cut-off write) or a repeated
daily date is a DataError, never a silent blank or overwrite.
"""
from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import io
import pathlib

import pull_garmin as pg

DAILY_NUM = ("rhr", "hrv_night", "hrv_weekly", "sleep_h", "deep_h", "light_h", "rem_h", "awake_h", "sleep_score",
             "bb_high", "bb_low", "stress_avg", "steps", "run_km", "run_n", "run_avg_hr", "weight", "weight_n",
             "resp_sleep", "resp_wake", "readiness", "acute_load", "recovery_min", "hrv_lo", "hrv_hi")
DAILY_TEXT = ("hrv_status", "weight_src", "readiness_level", "acute_src", "readiness_src")
ACT_NUM = ("km", "min", "avg_hr", "max_hr", "cadence", "te_aer", "te_anaer", "load")
ACT_TEXT = ("start", "type", "name", "pace", "activity_id", "te_label")
FIT_NUM = ("vo2max", "lt_hr", "load_acute", "load_chronic", "load_lo", "load_hi", "acwr",
           "anaer", "anaer_lo", "anaer_hi", "aer_hi", "aer_hi_lo", "aer_hi_hi", "aer_lo", "aer_lo_lo", "aer_lo_hi")
FIT_TEXT = ("vo2max_date", "pred_5k", "pred_10k", "pred_hm", "lt_date", "status", "status_since", "balance")
# columns pull_garmin.py added on Oct 21, 2026 (the extras, until then read from the PC's raw cache): a CSV
# written before that has none of them, and every row then reads them as empty
LATER = {"recovery_min", "hrv_lo", "hrv_hi", *FIT_NUM[2:], "status", "status_since", "balance",
         "acute_src",   # Oct 24: "approx" = pull_garmin.py's estimate, Garmin had no acute load that day
         "readiness_src",   # Oct 24: "est" = pull_garmin.py's readiness estimate (the Personal API has none)
         "te_label"}   # Oct 24: Garmin's primary benefit per activity, which our load focus reads
STALE_DAYS = 7   # Garmin's status and focus older than this give way to ours: the Personal API stopped them on Oct 24
OPTIMAL = (0.8, 1.5)   # Garmin's optimal acute-load range as a share of chronic load (Oct 21, 2026: 393.6-738 on 492)


class DataError(Exception):
    """A Garmin input is missing or malformed."""


@dataclasses.dataclass
class Garmin:
    daily: dict            # date -> row dict (numbers as float, text as str, empty = None)
    activities: list       # row dicts sorted by start; "date" is a date, "start" a naive local datetime
    fitness: list          # row dicts sorted by date
    csv_mtime: dt.datetime | None   # when garmin-daily.csv was last written (aware, UTC)


def _read_rows(path: pathlib.Path, num: tuple, text: tuple) -> list[dict]:
    content = path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):     # every written line ends in "\n": this file was cut off
        last = content.count("\n") + 1
        raise DataError(f"{path.name} line {last}: no line ending, the file looks cut off")
    lines = [l for l in content.splitlines() if not l.startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    fields = reader.fieldnames or []
    need = {"date", *num, *text} - LATER
    missing = need - set(fields)
    if missing:
        raise DataError(f"{path.name}: missing columns {sorted(missing)}")
    rows = []
    for n, r in enumerate(reader, start=3):
        # DictReader pads a short row with None and puts extra cells under the key None; an empty cell is "".
        if None in r or None in r.values():
            found = len(fields) + len(r[None]) if None in r else sum(v is not None for v in r.values())
            raise DataError(f"{path.name} line {n}: expected {len(fields)} fields, found {found}")
        row: dict = {}
        try:
            row["date"] = dt.date.fromisoformat(r["date"])
        except (TypeError, ValueError):
            raise DataError(f"{path.name} line {n}: date {r.get('date')!r} is not YYYY-MM-DD") from None
        for c in num:
            v = (r.get(c) or "").strip()
            try:
                row[c] = float(v) if v else None
            except ValueError:
                raise DataError(f"{path.name} line {n}: {c}={v!r} is not a number") from None
        for c in text:
            v = (r.get(c) or "").strip()
            row[c] = v or None
        rows.append(row)
    return rows


def load_garmin(root: pathlib.Path) -> Garmin:
    """Read data/garmin-daily.csv and data/garmin-activities.csv (required) and
    data/garmin-fitness.csv (optional: [] when absent). Raises DataError on any problem."""
    d = pathlib.Path(root) / "data"
    daily_p, acts_p, fit_p = d / "garmin-daily.csv", d / "garmin-activities.csv", d / "garmin-fitness.csv"
    for p in (daily_p, acts_p):
        if not p.exists():
            raise DataError(f"missing input: {p}")
    daily: dict = {}
    for r in _read_rows(daily_p, DAILY_NUM, DAILY_TEXT):
        if r["date"] in daily:                        # one row per day: a repeat must not overwrite silently
            raise DataError(f"{daily_p.name}: date {r['date']} is on two rows")
        daily[r["date"]] = r
    acts = _read_rows(acts_p, ACT_NUM, ACT_TEXT)
    for a in acts:
        try:
            a["start"] = dt.datetime.fromisoformat(a["start"]) if a["start"] else None
        except ValueError:
            raise DataError(f"{acts_p.name}: start {a['start']!r} is not a timestamp") from None
    acts.sort(key=lambda a: (a["date"], a["start"] or dt.datetime.min))
    fitness = sorted(_read_rows(fit_p, FIT_NUM, FIT_TEXT), key=lambda r: r["date"]) if fit_p.exists() else []
    mtime = dt.datetime.fromtimestamp(daily_p.stat().st_mtime, tz=dt.timezone.utc)
    return Garmin(daily=daily, activities=acts, fitness=fitness, csv_mtime=mtime)


def as_of(g: Garmin, today: dt.date) -> Garmin:
    """The data as it stood on `today`: rows and activities dated after it are dropped (a --today preview
    of an earlier day must not see later activities)."""
    return Garmin(daily={d: r for d, r in g.daily.items() if d <= today},
                  activities=[a for a in g.activities if a["date"] <= today],
                  fitness=[r for r in g.fitness if r["date"] <= today], csv_mtime=g.csv_mtime)


EMPTY_EXTRAS = {"status": None, "focus": None, "recovery_min": None, "hrv_band": None}


def extras(g: Garmin, today: dt.date) -> dict:
    """Garmin's training status, load focus, recovery time and HRV baseline, from the CSV columns
    pull_garmin.py fills since Oct 21, 2026 (shapes in its parse_fitness and parse_day):

    status       the newest fitness row of the last STALE_DAYS days with a status: {"phrase", "since", "acute",
                 "chronic", "lo", "hi", "acwr"}; lo/hi = Garmin's optimal acute-load range. Without one, ours:
                 the same keys plus "src": "est", phrase and since None, chronic from pull_garmin's
                 est_chronic_load, acute the newest acute_load of today or yesterday, lo/hi = OPTIMAL x chronic
    focus        the newest such fitness row with a load focus: {"phrase", "rows": [{"key", "value", "lo", "hi"}]
                 for anaerobic, high aerobic, low aerobic}. Without one, ours from est_load_focus: phrase,
                 lo and hi None, plus "src": "est"
    recovery_min today's row only: this morning's recovery time (minutes). None when today's row is not in
                 yet (a failed pull) or has none, because another day's value would be shown as "this morning"
    hrv_band     the newest daily row with both baseline ends: (hrv_lo, hrv_hi); none until Garmin has
                 ~3 weeks of nights

    Pass the as_of() data, so a --today preview sees nothing later. A missing value gives None; only status
    and focus have estimates.
    """
    out = dict(EMPTY_EXTRAS)
    recent = [r for r in g.fitness if r["date"] > today - dt.timedelta(days=STALE_DAYS)]
    st = next((r for r in reversed(recent) if r.get("status") or r.get("load_acute") is not None), None)
    if st:
        out["status"] = {"phrase": st["status"], "since": st["status_since"], "acute": st["load_acute"],
                         "chronic": st["load_chronic"], "lo": st["load_lo"], "hi": st["load_hi"], "acwr": st["acwr"]}
    fo = next((r for r in reversed(recent) if r.get("anaer") is not None), None)
    if fo:
        out["focus"] = {"phrase": fo["balance"], "rows": [
            {"key": key, "value": fo[c], "lo": fo[c + "_lo"], "hi": fo[c + "_hi"]}
            for key, c in (("anaerobic", "anaer"), ("high_aerobic", "aer_hi"), ("low_aerobic", "aer_lo"))]}
    if out["status"] is None:
        out["status"] = est_status(g, today)
    if out["focus"] is None:
        fo = pg.est_load_focus(g.activities, today.isoformat())
        if fo:
            out["focus"] = {"phrase": None, "src": "est", "rows": [
                {"key": key, "value": float(fo[c]), "lo": None, "hi": None}
                for key, c in (("anaerobic", "anaer"), ("high_aerobic", "aer_hi"), ("low_aerobic", "aer_lo"))]}
    out["recovery_min"] = (g.daily.get(today) or {}).get("recovery_min")
    band = next(((r["hrv_lo"], r["hrv_hi"]) for _, r in sorted(g.daily.items(), reverse=True)
                 if r.get("hrv_lo") is not None and r.get("hrv_hi") is not None), None)
    out["hrv_band"] = band
    return out


def est_status(g: Garmin, today: dt.date) -> dict | None:
    """Our chronic load, optimal range and acute:chronic ratio (see extras), or None without 28 days of activities."""
    loads = {str(k): v for k, v in pg._day_loads(g.activities).items()}
    chronic = pg.est_chronic_load(loads, today.isoformat())
    if not chronic:
        return None
    acute = next((r["acute_load"] for d in (today, today - dt.timedelta(days=1))
                  if (r := g.daily.get(d)) and r.get("acute_load") is not None), None)
    return {"phrase": None, "since": None, "acute": acute, "chronic": float(chronic),
            "lo": round(OPTIMAL[0] * chronic, 1), "hi": round(OPTIMAL[1] * chronic, 1),
            "acwr": None if acute is None else round(acute / chronic, 1), "src": "est"}
