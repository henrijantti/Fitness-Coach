"""Overview tab view model (spec section 4): every card as display-ready data.

A card or tile whose data is missing is left out (None or dropped from its list), so the page never
prints NaN, undefined or a made-up number. Levels 1-5 drive the mock's five-segment meters; 0 = grey.
"""
from __future__ import annotations

import datetime as dt
import statistics

from kunto import card as kcard
from kunto import fmt
from kunto import matching
from kunto import plan as kplan

STALE_AFTER = dt.timedelta(hours=36)
LAST_RACE = "Last race: 21:05 (city 5K)"   # the latest official 5K result, shown under the estimate
DEVICE = "Fenix 9"
HRV_STATUS = {"BALANCED": ("Balanced", ""), "UNBALANCED": ("Unbalanced", "warn"), "LOW": ("Low", "warn"),
              "POOR": ("Poor", "warn"), "NONE": ("Baseline building", "neutral")}
FOCUS_LABEL = {"anaerobic": ("Anaerobic", "var(--s1)"), "high_aerobic": ("High aerobic", "var(--s2)"),
               "low_aerobic": ("Low aerobic", "var(--s3)")}


def _series(g, today: dt.date, key: str, n: int) -> list[dict]:
    """n days ending today: [{"d": iso, "v": value or None}]."""
    out = []
    for k in range(n - 1, -1, -1):
        d = today - dt.timedelta(days=k)
        out.append({"d": d.isoformat(), "v": (g.daily.get(d) or {}).get(key)})
    return out


def _vals(series: list[dict]) -> list[float]:
    return [p["v"] for p in series if p["v"] is not None]


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def freshness(g, now: dt.datetime) -> dict:
    """Data-as-of stamp. As-of = the CSV write time when it falls on the newest data day, else the start
    of that day (a git checkout can touch the mtime). Stale (amber) when older than 36 h."""
    if not g.daily:
        return {"label": "No Garmin data", "stale": True, "as_of_ms": None}
    newest = max(g.daily)
    tz = now.tzinfo
    mtime = g.csv_mtime.astimezone(tz) if g.csv_mtime else None
    if mtime and mtime.date() == newest:
        as_of, label = mtime, f"Data as of {mtime:%H:%M} {fmt.day_label(newest)}"
    else:
        as_of, label = dt.datetime.combine(newest, dt.time(0, 0), tzinfo=tz), f"Data as of {fmt.day_label(newest)}"
    return {"label": label, "stale": now - as_of > STALE_AFTER, "as_of_ms": int(as_of.timestamp() * 1000)}


def header(plan: dict, today: dt.date) -> dict:
    first, last = kplan.season_bounds(plan)
    n = kplan.current_week_number(plan, today)
    w = kplan.get_week(plan, n)
    total = len(plan["weeks"])
    if today < first:
        line = f"Season starts {fmt.day_label(first)} · Week 1 of {total} · {w['block']}"
    elif today > last:
        line = f"Season complete · Week {total} of {total}"
    else:
        line = f"Week {n} of {total} · {w['block']}"
    s, e = dt.date.fromisoformat(w["start"]), dt.date.fromisoformat(w["end"])
    return {"line": line, "dates": fmt.range_label(s, e), "week_pill": f"Week {n}", "plan_name": plan["meta"]["name"]}


def session_phrase(s: dict) -> str:
    """★ Power + Legs, 70 min (optional)"""
    text = ("★ " if s["hard"] else "") + s["title"]
    if s["min"]:
        text += f", {s['min']} min"
    if s["optional"]:
        text += " (optional)"
    return text


def readiness_card(g, plan: dict, today: dt.date) -> dict:
    row = g.daily.get(today) or {}
    score, level = row.get("readiness"), row.get("readiness_level")
    trend = _series(g, today, "readiness", 14)
    vals = _vals(trend)
    prior = _vals(_series(g, today - dt.timedelta(days=14), "readiness", 14))
    caption = None
    if vals:
        caption = f"avg {fmt.num(_mean(vals))}"
        if len(prior) >= 7:
            caption += f" · {fmt.signed(_mean(vals) - _mean(prior), 0)} vs prior"
    sessions = [s for s in kplan.sessions_for_date(plan, today) if s["kind"] != "rest"]
    first, last = kplan.season_bounds(plan)
    if not first <= today <= last:
        today_text = "no plan"
    elif not sessions:
        today_text = "rest"
    else:
        today_text = " + ".join(session_phrase(s) for s in sessions)
    headline = (f"{level} · " if level and score is not None else "") + f"Today: {today_text}"
    est = score is not None and row.get("readiness_src") == "est"   # ours: the Personal API has none
    missing = None if score is not None else (
        "No readiness today: no sleep score yet" if row and row.get("sleep_score") is None else "No readiness today")
    return {"score": None if score is None else int(score), "level": level if score is not None else None,
            "missing_text": missing, "trend": trend, "trend_caption": caption,
            "eyebrow": f"Training readiness{', our estimate' if est else ''} · {fmt.day_label(today)}",
            "headline": headline}


def _tile(name, value, lvl, text):
    return {"n": name, "v": value, "lvl": lvl, "t": text}


def factor_tiles(g, today: dt.date, raw: dict) -> list[dict]:
    row = g.daily.get(today) or {}
    tiles = []
    ss = row.get("sleep_score")
    if ss is not None:
        lvl, t = (5, "Excellent") if ss >= 90 else (4, "Good") if ss >= 80 else (3, "Fair") if ss >= 60 else \
            (2, "Poor") if ss >= 40 else (1, "Poor")
        tiles.append(_tile("Sleep score", fmt.num(ss), lvl, t))
    sleep7 = _vals(_series(g, today, "sleep_h", 7))
    if sleep7:
        avg = _mean(sleep7)
        lvl, t = (5, "Good") if avg >= 8 else (4, "Good") if avg >= 7.5 else (3, "Fair") if avg >= 7 else \
            (2, "Short") if avg >= 6.5 else (1, "Short")
        tiles.append(_tile("Sleep, 7 d", fmt.hours_compact(avg), lvl, t))
    hn, hw = row.get("hrv_night"), row.get("hrv_weekly")
    if hn is not None:
        if hw:
            r = hn / hw
            lvl, t = (4, "At or above 7-d avg") if r >= 1 else (3, "Near 7-d avg") if r >= 0.9 else \
                (2, "Below 7-d avg") if r >= 0.8 else (1, "Well below 7-d avg")
            t += f" ({fmt.num(hw)})"
        else:
            lvl, t = 0, "No 7-d avg yet"
        tiles.append(_tile("HRV", f"{fmt.num(hn)} ms", lvl, t))
    al = row.get("acute_load")
    st = raw.get("status") or {}
    if al is not None:
        lo, hi = st.get("lo"), st.get("hi")
        if lo is not None and hi is not None:
            lvl, t = (2, "Below optimal") if al < lo else (4, "Optimal") if al <= hi else (2, "Above optimal")
        else:
            lvl, t = 0, "7-day load"
        if row.get("acute_src") == "approx":
            t += " · approx."
        tiles.append(_tile("Acute load", fmt.num(al), lvl, t))
    stress3 = [(g.daily.get(today - dt.timedelta(days=k)) or {}).get("stress_avg") for k in (1, 2, 3)]
    stress3 = [v for v in stress3 if v is not None]
    if stress3:
        avg = _mean(stress3)
        lvl, t = (5, "Resting") if avg <= 25 else (4, "Low") if avg <= 37 else (3, "Low") if avg <= 50 else \
            (2, "Medium") if avg <= 75 else (1, "High")
        tiles.append(_tile("Stress, 3 d", fmt.num(avg), lvl, t))
    rhr = row.get("rhr")
    hist = _vals(_series(g, today - dt.timedelta(days=1), "rhr", 28))
    if rhr is not None:
        if len(hist) >= 5:
            med = statistics.median(hist)
            delta = rhr - med
            lvl = 5 if delta <= 0 else 4 if delta <= 1 else 3 if delta <= 3 else 2 if delta <= 5 else 1
            t = f"{fmt.signed(delta, 0)} vs 28-d median ({fmt.num(med)})"
        else:
            lvl, t = 0, "Median building"
        tiles.append(_tile("Resting HR", fmt.num(rhr), lvl, t))
    return tiles


def upcoming(plan: dict, g, today: dt.date, n: int = 4, lasts: dict | None = None,
             nexts: dict | None = None) -> list[dict]:
    """The next n sessions not yet done, from today on (rest days skipped). A gym session swapped to a
    later day (matching.py) is listed on that day. A gym or test session carries its card (the page shows the
    first one in full, the rest in short); a test or event due today or tomorrow keeps its kind as a tag."""
    out = []
    num = kplan.current_week_number(plan, today)
    for w in plan["weeks"][num - 1:]:
        week = []
        for d in matching.plan_week_status(plan, w, g.activities, today):
            for s in d["sessions"]:
                swapped = s["status"] == "swapped"
                due = s["moved_to"] if swapped else d["date"]
                if due < today or s["status"] not in ("today", "upcoming", "swapped"):
                    continue
                key = s["hard"] or s["kind"] in ("test", "event")
                if due == today:
                    status, cls = "Today", ""
                elif due == today + dt.timedelta(days=1):
                    status, cls = "Tomorrow", ""
                elif s["kind"] == "test":
                    status, cls = "Test", ""
                elif s["kind"] == "event":
                    status, cls = "Event", ""
                elif s["optional"]:
                    status, cls = "Optional", "neutral"
                else:
                    status, cls = "Planned", "neutral"
                bits = [x for x in (fmt.plan_minutes(s["min"]), "first to go" if s["first_to_go"] else None,
                                    f"swapped from {fmt.DOW[d['date'].weekday()]}" if swapped else None) if x]
                c = kcard.build(s, lasts, (nexts or {}).get(d["date"]))
                kind_tag = {"test": "Test", "event": "Event"}.get(s["kind"]) if due <= today + dt.timedelta(days=1) \
                    else None
                week.append((due, {"dow": fmt.DOW[due.weekday()].upper(), "day": str(due.day), "week": w["week"],
                                   "title": ("★ " if s["hard"] else "") + s["title"], "status": status,
                                   "status_cls": cls, "kind_tag": kind_tag, "d": " · ".join(bits),
                                   "chips": fmt.chips(s["chips"]), "card": c,
                                   "short": kcard.compact(c) if c else None, "key": key}))
        week.sort(key=lambda x: x[0])                 # stable: a swapped session leads its new day
        for _, item in week:
            out.append(item)
            if len(out) == n:
                return out
    return out


def recent_activities(g, today: dt.date, n: int = 5) -> dict:
    since = today - dt.timedelta(days=13)
    units = matching.units([a for a in g.activities if since <= a["date"] <= today])
    units.sort(key=lambda u: (u["date"], u["start"] or dt.datetime.min), reverse=True)
    items = []
    for u in units[:n]:
        cls = u["cls"]
        bits = [fmt.day_label(u["date"]), fmt.minutes_label(u["min"])]
        if cls == "run" and u["km"] and u["min"]:
            s = round(u["min"] * 60 / u["km"])
            bits.append(f"{s // 60}:{s % 60:02d} /km")
        if u["avg_hr"] is not None:
            bits.append(f"avg HR {fmt.num(u['avg_hr'])}")
        if len(u["parts"]) > 1:
            bits.append(f"{len(u['parts'])} files summed")
        te_aer = max((p.get("te_aer") for p in u["parts"] if p.get("te_aer") is not None), default=None)
        te_ana = max((p.get("te_anaer") for p in u["parts"] if p.get("te_anaer") is not None), default=None)
        loads = [p.get("load") for p in u["parts"] if p.get("load") is not None]
        icon = "run" if cls == "run" else "lift" if cls == "gym" else "ball"
        items.append({"t": fmt.activity_title(u, cls), "d": " · ".join(b for b in bits if b), "icon": icon,
                      "aer": te_aer, "ana": te_ana, "load": fmt.num(sum(loads)) if loads else None})
    return {"items": items, "empty_text": None if items else "No activities in 14 days"}


def hrv_card(g, today: dt.date, raw: dict) -> dict | None:
    series = _series(g, today, "hrv_night", 28)
    vals = _vals(series)
    if not vals:
        return None
    last7 = _vals(series[-7:])
    # Garmin sends an explicit "NONE" while the baseline builds; an empty cell (watch off, or no row after a
    # failed pull) is no status at all, so no pill.
    status = (g.daily.get(today) or {}).get("hrv_status")
    label, cls = HRV_STATUS.get(status, (fmt.humanize_enum(status), "neutral")) if status else (None, "")
    band = raw.get("hrv_band")
    return {"series": series, "metric": fmt.num(_mean(last7)) if last7 else fmt.num(vals[-1]),
            "unit": "ms · 7-night avg" if last7 else "ms · last night", "status": label, "status_cls": cls,
            "band": list(band) if band else None,
            "band_label": f"Baseline {fmt.num(band[0])}–{fmt.num(band[1])} ms" if band else None,
            "caption": None if band else "baseline building"}


def sleep_card(g, today: dt.date) -> dict | None:
    nights = []
    for k in range(6, -1, -1):
        d = today - dt.timedelta(days=k)
        r = g.daily.get(d) or {}
        base = {"d": d.isoformat(), "dow": fmt.DOW[d.weekday()], "label": fmt.day_label(d)}
        if r.get("sleep_h") is None:
            nights.append({**base, "missing": True})
            continue
        nights.append({**base, "missing": False, "deep": r.get("deep_h") or 0, "rem": r.get("rem_h") or 0,
                       "light": r.get("light_h") or 0, "awake": r.get("awake_h") or 0,
                       "score": None if r.get("sleep_score") is None else int(r["sleep_score"]),
                       "asleep": fmt.hours_label(r["sleep_h"])})
    have = [x for x in nights if not x["missing"]]
    if not have:
        return None
    scores = [x["score"] for x in have if x["score"] is not None]
    hours = _mean([g.daily[dt.date.fromisoformat(x["d"])]["sleep_h"] for x in have])
    avg = _mean(scores)
    status, cls = (None, "") if avg is None else ("Good", "") if avg >= 80 else ("Fair", "warn") if avg >= 60 \
        else ("Poor", "warn")
    return {"nights": nights, "metric": fmt.num(avg) if avg is not None else fmt.hours_label(hours),
            "unit": f"avg score · {fmt.hours_label(hours)}" if avg is not None else "avg asleep",
            "status": status, "status_cls": cls}


def load_card(g, today: dt.date, raw: dict) -> dict | None:
    series = _series(g, today, "acute_load", 28)
    vals = _vals(series)
    if not vals:
        return None
    latest = next(p for p in reversed(series) if p["v"] is not None)
    st = raw.get("status") or {}
    lo, hi = st.get("lo"), st.get("hi")
    band = [lo, hi] if lo is not None and hi is not None else None
    status, cls = None, ""
    if band:
        v = latest["v"]
        status, cls = ("Below optimal", "warn") if v < lo else ("Optimal", "") if v <= hi else ("Above optimal", "warn")
    chips = []
    if (g.daily.get(dt.date.fromisoformat(latest["d"])) or {}).get("acute_src") == "approx":
        chips.append("Approx. from activity loads")
    est = st.get("src") == "est"   # ours from activity loads: the Personal API has no training status
    if st.get("acwr") is not None:
        chips.append(f"Acute : chronic {fmt.num(st['acwr'], 1)}" + (", ours" if est else ""))
    week_ago = (g.daily.get(dt.date.fromisoformat(latest["d"]) - dt.timedelta(days=7)) or {}).get("acute_load")
    if week_ago:
        chips.append(f"{fmt.signed((latest['v'] / week_ago - 1) * 100, 0)}% vs last wk")
    return {"series": series, "metric": fmt.num(latest["v"]), "status": status, "status_cls": cls, "chips": chips,
            "band": band,
            "band_label": (f"Optimal range {fmt.num(lo)}–{fmt.num(hi)} (from "
                           + ("our chronic load estimate, " + fmt.num(st["chronic"]) if est else "chronic load") + ")")
            if band else None}


def status_card(g, raw: dict) -> dict | None:
    kv = []
    fit = [r for r in g.fitness if r.get("vo2max") is not None]
    if fit:
        latest = fit[-1]
        cut = latest["date"] - dt.timedelta(days=28)
        ref = next((r for r in reversed(fit) if r["date"] <= cut), None)
        sub = None
        if ref:
            sub = f"{fmt.signed(latest['vo2max'] - ref['vo2max'])} in 4 wk"
        elif fit[0] is not latest:
            sub = f"{fmt.signed(latest['vo2max'] - fit[0]['vo2max'])} since {fmt.short_date(fit[0]['date'])}"
        kv.append({"k": "VO₂ max", "v": fmt.num(latest["vo2max"], 1), "sub": sub})
    lt = next((r["lt_hr"] for r in reversed(g.fitness) if r.get("lt_hr") is not None), None)
    if lt is not None:
        kv.append({"k": "LT heart rate", "v": fmt.num(lt), "sub": "bpm"})
    p5 = next((r["pred_5k"] for r in reversed(g.fitness) if r.get("pred_5k")), None)
    if p5:
        kv.append({"k": "5K, Garmin estimate", "v": p5, "sub": LAST_RACE})
    rec = raw.get("recovery_min")
    if rec is not None:
        kv.append({"k": "Recovery time", "v": f"{max(0, round(rec / 60))} h", "sub": "Garmin, this morning"})
    st = raw.get("status") or {}
    phrase = fmt.humanize_enum(st.get("phrase"))
    since = f"Garmin training status since {fmt.short_date(dt.date.fromisoformat(st['since']))}" \
        if st.get("since") else "Garmin training status"
    focus_rows, focus_caption, scale = [], None, None
    fo = raw.get("focus")
    if fo:
        rows = [r for r in fo["rows"] if r["value"] is not None]
        scale = max([r["value"] for r in rows] + [r["hi"] for r in rows if r["hi"] is not None] + [1]) * 1.1
        for r in rows:
            name, color = FOCUS_LABEL[r["key"]]
            rng = f"{fmt.num(r['lo'])}–{fmt.num(r['hi'])}" if r["lo"] is not None and r["hi"] is not None else None
            focus_rows.append({"n": name, "v": fmt.num(r["value"]), "value": r["value"], "lo": r["lo"], "hi": r["hi"],
                               "range": rng, "c": color})
        focus_caption = ("Our estimate from activity loads, no Garmin targets" if fo.get("src") == "est"
                         else fmt.humanize_enum(fo.get("phrase")))
    if not kv and not phrase and not focus_rows:
        return None
    return {"phrase": phrase, "since": since if phrase else None, "kv": kv, "focus": focus_rows,
            "focus_caption": focus_caption, "scale": scale}


def season_card(plan: dict, today: dt.date) -> dict:
    first, last = kplan.season_bounds(plan)
    test = next((w for w in plan["weeks"] if w["block"].strip().lower() == "test week"), plan["weeks"][-1])
    tstart = dt.date.fromisoformat(test["start"])
    days = (tstart - today).days
    if days > 0:
        big, text = str(days), f"days to test week · {fmt.short_date(tstart)} {tstart.year}"
    elif today <= last:
        big, text = "0", "Test week is here"
    else:
        big, text = "0", "Season complete"
    markers = [{"d": m["date"].isoformat(), "label": m["label"], "sub": fmt.short_date(m["date"]), "week": m["week"]}
               for m in kplan.season_markers(plan)]
    targets = []
    for name, base, target, stretch in plan.get("targets", []):
        b = (base or "").strip()
        btxt = "no baseline yet" if b in ("", "\u2014", "-") else f"baseline {b}"
        targets.append({"n": name, "target": target, "stretch": stretch, "baseline": btxt})
    return {"countdown": big, "countdown_text": text, "start": first.isoformat(), "end": last.isoformat(),
            "today": today.isoformat(), "markers": markers, "targets": targets,
            "targets_caption": f"{len(targets)} targets · primary, stretch"}


def today_tiles(g, today: dt.date) -> list[dict]:
    row = g.daily.get(today) or {}
    y = g.daily.get(today - dt.timedelta(days=1)) or {}
    tiles = []
    for v, label in ((row.get("rhr"), "Resting HR, bpm"), (row.get("bb_high"), "Body Battery high"),
                     (y.get("stress_avg"), "Avg stress, yesterday"), (y.get("steps"), "Steps, yesterday")):
        if v is not None:
            tiles.append({"v": fmt.num(v), "label": label})
    return tiles


def build_overview(g, plan: dict, today: dt.date, now: dt.datetime, raw: dict, lasts: dict | None = None,
                   nexts: dict | None = None) -> dict:
    return {"header": header(plan, today), "fresh": freshness(g, now), "device": DEVICE,
            "today_label": fmt.day_label(today),
            "readiness": readiness_card(g, plan, today), "factors": factor_tiles(g, today, raw),
            "upcoming": upcoming(plan, g, today, lasts=lasts, nexts=nexts),
            "activities": recent_activities(g, today),
            "hrv": hrv_card(g, today, raw), "sleep": sleep_card(g, today), "load": load_card(g, today, raw),
            "status": status_card(g, raw), "season": season_card(plan, today), "today": today_tiles(g, today)}
