import datetime as dt
import json
import pathlib
import shutil

import pytest

import pull_garmin as pg
from kunto import data as kdata
from kunto import overview as ov
from kunto import plan as kplan

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "kunto"
HEL = dt.timezone(dt.timedelta(hours=3))           # Helsinki summer time (EEST), fixed for the tests
TODAY = dt.date(2026, 10, 7)
NOW = dt.datetime(2026, 10, 7, 7, 30, tzinfo=HEL)
NO_RAW = dict(kdata.EMPTY_EXTRAS)
RAW = {"status": {"phrase": "PRODUCTIVE_9", "since": "2026-10-03", "acute": 300, "chronic": 240, "lo": 192.0,
                  "hi": 360.0, "acwr": 1.3},
       "focus": {"phrase": "AEROBIC_LOW_SHORTAGE", "rows": [
           {"key": "anaerobic", "value": 176.7, "lo": 0, "hi": 262},
           {"key": "high_aerobic", "value": 274.0, "lo": 268, "hi": 531},
           {"key": "low_aerobic", "value": 73.2, "lo": 212, "hi": 475}]},
       "recovery_min": 3204, "hrv_band": (24, 34)}


@pytest.fixture(scope="module")
def plan():
    return kplan.load_plan(ROOT / "training-plan-2026-27.json")


@pytest.fixture
def g(tmp_path):
    shutil.copytree(FIX / "data", tmp_path / "data")
    garmin = kdata.load_garmin(tmp_path)
    garmin.csv_mtime = dt.datetime(2026, 10, 7, 4, 15, tzinfo=dt.timezone.utc)      # 07:15 in Helsinki
    return garmin


def all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from all_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from all_strings(v)


# ---------- extras (from the CSV columns pull_garmin.py fills since Oct 21) ----------

FIT_EXTRAS = {"status": "PRODUCTIVE_9", "status_since": "2026-09-26", "load_acute": 384.0, "load_chronic": 219.0,
              "load_lo": 175.2, "load_hi": 328.5, "acwr": 1.7, "balance": "AEROBIC_LOW_SHORTAGE",
              "anaer": 176.7, "anaer_lo": 0.0, "anaer_hi": 262.0, "aer_hi": 274.0, "aer_hi_lo": 268.0,
              "aer_hi_hi": 531.0, "aer_lo": 73.2, "aer_lo_lo": 212.0, "aer_lo_hi": 475.0}


def test_extras_absent_from_csvs_written_before_the_columns(g):
    assert "load_lo" not in (FIX / "data" / "garmin-fitness.csv").read_text(encoding="utf-8")
    assert g.fitness[-1]["load_lo"] is None and g.daily[TODAY]["recovery_min"] is None
    assert kdata.extras(g, TODAY) == kdata.EMPTY_EXTRAS


def test_extras_from_the_csv_rows(g):
    g.fitness[0].update(FIT_EXTRAS, date=dt.date(2026, 10, 1))   # the newer Oct 5 row has no status
    g.daily[TODAY].update(recovery_min=3204.0)
    g.daily[dt.date(2026, 10, 5)].update(hrv_lo=24.0, hrv_hi=34.0)
    x = kdata.extras(g, TODAY)
    assert x["status"] == {"phrase": "PRODUCTIVE_9", "since": "2026-09-26", "acute": 384.0, "chronic": 219.0,
                           "lo": 175.2, "hi": 328.5, "acwr": 1.7}
    assert x["focus"]["phrase"] == "AEROBIC_LOW_SHORTAGE"
    assert [(r["key"], r["value"], r["lo"], r["hi"]) for r in x["focus"]["rows"]] == [
        ("anaerobic", 176.7, 0.0, 262.0), ("high_aerobic", 274.0, 268.0, 531.0), ("low_aerobic", 73.2, 212.0, 475.0)]
    assert x["recovery_min"] == 3204.0 and x["hrv_band"] == (24.0, 34.0)
    assert ov.load_card(g, TODAY, x)["band"] == [175.2, 328.5]


def test_extras_drop_status_and_focus_older_than_a_week(g):
    g.fitness[0].update(FIT_EXTRAS)                      # Sep 28: 9 days before TODAY
    assert kdata.extras(g, TODAY)["status"] is None and kdata.extras(g, TODAY)["focus"] is None
    assert kdata.extras(g, dt.date(2026, 10, 4))["status"]["phrase"] == "PRODUCTIVE_9"


def test_extras_respect_today(g):
    g.fitness[-1].update(FIT_EXTRAS)                     # pulled Oct 5
    g.daily[TODAY].update(recovery_min=600.0, hrv_lo=24.0, hrv_hi=34.0)
    assert kdata.extras(g, dt.date(2026, 10, 8))["recovery_min"] is None    # not this morning's
    early = kdata.extras(kdata.as_of(g, dt.date(2026, 10, 1)), dt.date(2026, 10, 1))   # a --today preview
    assert early == kdata.EMPTY_EXTRAS


def test_extras_read_what_pull_garmin_writes(tmp_path):
    shutil.copytree(FIX / "data", tmp_path / "data")
    fit = [dict(dict.fromkeys(pg.GARMIN_FITNESS_COLUMNS), date="2026-10-07", **FIT_EXTRAS)]
    pg.write_csv(tmp_path / "data" / "garmin-fitness.csv", pg.GARMIN_FITNESS_COLUMNS, fit, "fixture")
    x = kdata.extras(kdata.load_garmin(tmp_path), TODAY)
    assert (x["status"]["lo"], x["status"]["hi"], x["focus"]["rows"][2]["hi"]) == (175.2, 328.5, 475.0)


# ---------- header + freshness ----------

def test_header(plan):
    h = ov.header(plan, TODAY)
    assert h == {"line": "Week 2 of 51 · 1 Athletic base", "dates": "5–11 Oct 2026", "week_pill": "Week 2",
                 "plan_name": "Sample Training Plan"}
    assert ov.header(plan, dt.date(2026, 9, 27))["line"] == "Season starts Mon 28 Sep · Week 1 of 51 · 0 Re-entry"
    assert ov.header(plan, dt.date(2027, 10, 1))["line"] == "Season complete · Week 51 of 51"


def test_freshness_normal_under_36_h(g):
    f = ov.freshness(g, NOW)
    assert f["label"] == "Data as of 07:15 Wed 7 Oct" and f["stale"] is False
    assert ov.freshness(g, NOW + dt.timedelta(hours=35))["stale"] is False


def test_freshness_amber_over_36_h(g):
    assert ov.freshness(g, dt.datetime(2026, 10, 8, 19, 16, tzinfo=HEL))["stale"] is True


def test_freshness_mtime_on_another_day_uses_the_data_date(g):
    g.csv_mtime = dt.datetime(2026, 10, 9, 9, 0, tzinfo=dt.timezone.utc)          # e.g. a git checkout
    f = ov.freshness(g, dt.datetime(2026, 10, 9, 12, 0, tzinfo=HEL))
    assert f["label"] == "Data as of Wed 7 Oct" and f["stale"] is True


def test_freshness_without_data(g):
    g.daily = {}
    assert ov.freshness(g, NOW) == {"label": "No Garmin data", "stale": True, "as_of_ms": None}


# ---------- readiness + factor tiles ----------

def test_readiness_card(g, plan):
    r = ov.readiness_card(g, plan, TODAY)
    assert (r["score"], r["level"], r["missing_text"]) == (58, "MODERATE", None)
    assert r["headline"] == ("MODERATE · Today: Bonus, 50 min (optional) + Run home 5 km easy, 30 min (optional)")
    assert r["eyebrow"] == "Training readiness · Wed 7 Oct"
    assert len(r["trend"]) == 14 and r["trend"][0] == {"d": "2026-09-24", "v": None}
    assert r["trend_caption"] == "avg 73"                     # 9 mornings with a score


def test_readiness_missing_today(g, plan):
    r = ov.readiness_card(g, plan, dt.date(2026, 10, 6))
    assert r["score"] is None and r["missing_text"] == "No readiness today: no sleep score yet"
    assert r["headline"] == "Today: ★ Floorball, 60 min"
    g.daily[dt.date(2026, 10, 6)]["sleep_score"] = 80.0
    assert ov.readiness_card(g, plan, dt.date(2026, 10, 6))["missing_text"] == "No readiness today"


def test_readiness_card_marks_our_estimate(g, plan):
    g.daily[TODAY]["readiness_src"] = "est"
    r = ov.readiness_card(g, plan, TODAY)
    assert r["eyebrow"] == "Training readiness, our estimate · Wed 7 Oct" and r["score"] == 58


def test_factor_tiles_full_day(g):
    tiles = {t["n"]: t for t in ov.factor_tiles(g, TODAY, NO_RAW)}
    assert list(tiles) == ["Sleep score", "Sleep, 7 d", "HRV", "Acute load", "Stress, 3 d", "Resting HR"]
    assert (tiles["Sleep score"]["v"], tiles["Sleep score"]["lvl"], tiles["Sleep score"]["t"]) == ("68", 3, "Fair")
    assert tiles["Sleep, 7 d"]["v"] == "7h15"                            # 6 nights, Oct 6 missing
    assert tiles["HRV"]["v"] == "26 ms" and tiles["HRV"]["lvl"] == 0 and tiles["HRV"]["t"] == "No 7-d avg yet"
    assert tiles["Acute load"]["t"] == "7-day load"                      # no optimal band without Garmin's range
    assert (tiles["Resting HR"]["v"], tiles["Resting HR"]["t"]) == ("53", "+3 vs 28-d median (50)")


def test_factor_tiles_hide_missing_fields(g):
    names = [t["n"] for t in ov.factor_tiles(g, dt.date(2026, 10, 6), NO_RAW)]
    assert names == ["Sleep, 7 d", "Acute load", "Stress, 3 d"]


def test_acute_load_tile_uses_the_optimal_band(g):
    tile = next(t for t in ov.factor_tiles(g, TODAY, RAW) if t["n"] == "Acute load")
    assert (tile["lvl"], tile["t"]) == (4, "Optimal")


# ---------- cards ----------

def test_upcoming_next_four(g, plan):
    up = ov.upcoming(plan, g, TODAY)
    assert [(u["dow"], u["title"], u["status"]) for u in up] == [
        ("WED", "Bonus", "Today"), ("WED", "Run home 5 km easy", "Today"),
        ("THU", "Run commute, easy 5–8 km", "Tomorrow"), ("FRI", "Run in 5 km easy", "Optional")]
    assert up[0]["d"] == "50 min · first to go"


def test_upcoming_flags_tests_and_hard_sessions(g, plan):
    up = ov.upcoming(plan, g, dt.date(2026, 10, 10))
    assert up[0]["title"] == "★ Benchmarks + Legs" and up[0]["key"] is True and up[0]["status"] == "Today"


def test_recent_activities(g):
    a = ov.recent_activities(g, TODAY)
    assert [x["t"] for x in a["items"]] == ["Floorball", "Run 5.20 km", "Run 3.90 km",
                                            "Strength", "Run 5.00 km"]
    assert a["items"][1]["d"] == "Mon 5 Oct · 28 min · 5:23 /km · avg HR 141"
    assert a["empty_text"] is None
    assert ov.recent_activities(g, dt.date(2026, 11, 30)) == {"items": [], "empty_text": "No activities in 14 days"}


def test_hrv_card_baseline_building(g):
    h = ov.hrv_card(g, TODAY, NO_RAW)
    assert h["band"] is None and h["caption"] == "baseline building" and h["status"] == "Baseline building"
    assert len(h["series"]) == 28 and h["series"][-1] == {"d": "2026-10-07", "v": 26.0}
    assert ov.hrv_card(g, TODAY, RAW)["band_label"] == "Baseline 24–34 ms"


def test_hrv_card_without_a_status_shows_no_pill(g):
    # Garmin sends an explicit "NONE" while the baseline builds; an empty cell means no HRV data that night
    # (Oct 6: watch off) or no row at all (Oct 8: a failed pull). Neither may be shown as "Baseline building".
    for day in (dt.date(2026, 10, 6), dt.date(2026, 10, 8)):
        h = ov.hrv_card(g, day, NO_RAW)
        assert (h["status"], h["status_cls"]) == (None, ""), day
    h = ov.hrv_card(g, dt.date(2026, 10, 6), RAW)
    assert h["band_label"] == "Baseline 24–34 ms" and h["status"] is None and h["caption"] is None


def test_sleep_card_missing_night_is_an_empty_slot(g):
    s = ov.sleep_card(g, TODAY)
    assert [n["missing"] for n in s["nights"]] == [False, False, False, False, False, True, False]
    assert s["nights"][-1]["asleep"] == "6 h 30 min"


def test_load_card(g):
    c = ov.load_card(g, TODAY, NO_RAW)
    assert c["metric"] == "300" and c["band"] is None and c["status"] is None
    assert c["chips"] == ["+11% vs last wk"]
    c = ov.load_card(g, TODAY, RAW)
    assert c["band"] == [192.0, 360.0] and c["status"] == "Optimal"
    assert c["chips"][0] == "Acute : chronic 1.3"


def test_status_card(g):
    s = ov.status_card(g, NO_RAW)
    assert s["phrase"] is None and s["focus"] == []
    assert s["kv"] == [{"k": "VO₂ max", "v": "54.4", "sub": "+0.3 since 28 Sep"},
                       {"k": "LT heart rate", "v": "165", "sub": "bpm"},
                       {"k": "5K, Garmin estimate", "v": "19:05", "sub": "Last race: 21:05 (city 5K)"}]
    s = ov.status_card(g, RAW)
    assert s["phrase"] == "Productive" and s["since"] == "Garmin training status since 3 Oct"
    assert s["kv"][-1] == {"k": "Recovery time", "v": "53 h", "sub": "Garmin, this morning"}
    assert [f["n"] for f in s["focus"]] == ["Anaerobic", "High aerobic", "Low aerobic"]
    assert s["focus_caption"] == "Aerobic low shortage"


def test_season_card(plan):
    s = ov.season_card(plan, TODAY)
    assert s["countdown"] == "341" and s["countdown_text"] == "days to test week · 13 Sep 2027"
    assert len(s["markers"]) == 8 and s["markers"][-1]["label"] == "Test week"
    assert s["targets"][0] == {"n": "Cooper", "target": "3,100 m", "stretch": "3,200 m",
                               "baseline": "baseline est. 2,950 m"}
    assert s["targets"][-1]["baseline"] == "no baseline yet"


def test_today_tiles(g):
    assert ov.today_tiles(g, TODAY) == [{"v": "53", "label": "Resting HR, bpm"},
                                        {"v": "64", "label": "Body Battery high"},
                                        {"v": "35", "label": "Avg stress, yesterday"},
                                        {"v": "9,500", "label": "Steps, yesterday"}]


def test_a_day_without_any_data_hides_every_garmin_card(g, plan):
    o = ov.build_overview(g, plan, dt.date(2026, 11, 30), NOW, NO_RAW)
    assert o["readiness"]["score"] is None and o["factors"] == [] and o["today"] == []
    assert o["hrv"] is None and o["sleep"] is None and o["load"] is None


def test_overview_never_carries_nan_or_undefined(g, plan):
    for today in (TODAY, dt.date(2026, 10, 6), dt.date(2026, 11, 30)):
        o = ov.build_overview(g, plan, today, NOW, RAW)
        json.dumps(o, allow_nan=False)
        for s in all_strings(o):
            assert "nan" not in s.lower().split() and "None" not in s and "undefined" not in s, s


def test_upcoming_lists_a_swapped_gym_session_on_its_new_day(plan):
    """Sat planned Legs, Hevy shows upper: on the Sunday the Legs is what is due today, the Upper is done."""
    sat = dt.date(2026, 10, 3)
    lift = {"date": sat, "start": dt.datetime(2026, 10, 3, 17, 2), "type": "strength_training", "name": "Strength",
            "km": None, "min": 26.0, "avg_hr": 94.0, "cadence": None, "focus": "upper"}
    g = kdata.Garmin(daily={}, activities=[lift], fitness=[], csv_mtime=None)
    up = ov.upcoming(plan, g, dt.date(2026, 10, 4))
    assert (up[0]["dow"], up[0]["day"], up[0]["title"], up[0]["status"], up[0]["d"]) == (
        "SUN", "4", "Legs @ RPE 6, no power block", "Today", "60 min · swapped from Sat")
    assert "Upper @ RPE 6" not in [u["title"] for u in up] and len(up) == 4


def test_upcoming_gym_and_test_sessions_carry_their_card(g, plan):
    up = ov.upcoming(plan, g, dt.date(2026, 10, 23))
    sat = next(u for u in up if u["day"] == "24")
    assert (sat["status"], sat["kind_tag"], sat["week"]) == ("Tomorrow", "Test", 4)
    assert sat["card"]["sections"][0]["label"] == "Tests" and sat["short"]["more"] == 6
    run = up[0]
    assert run["card"] is None and run["short"] is None and run["kind_tag"] is None


def test_an_approximated_acute_load_says_so(g):
    g.daily[TODAY]["acute_src"] = "approx"                              # pull_garmin.py's estimate
    tile = next(t for t in ov.factor_tiles(g, TODAY, RAW) if t["n"] == "Acute load")
    assert tile["t"] == "Optimal · approx."
    assert ov.load_card(g, TODAY, NO_RAW)["chips"][0] == "Approx. from activity loads"


def _ours(today=dt.date(2026, 10, 21)):
    """4 weeks of activities (100 a day, every 5th a hard one) and today's acute load: no Garmin status."""
    acts = [{"date": today - dt.timedelta(days=k), "load": 100.0, "te_aer": 3.0, "te_anaer": 2.0 if k % 5 == 0 else 0.0,
             "te_label": "ANAEROBIC_CAPACITY" if k % 5 == 0 else "AEROBIC_BASE"} for k in range(28)]
    daily = {today: {"acute_load": 560.0}}
    return kdata.Garmin(daily=daily, activities=acts, fitness=[], csv_mtime=None), today


def test_extras_fall_back_to_our_chronic_load_and_focus():
    g, today = _ours()
    x = kdata.extras(g, today)
    assert x["status"] == {"phrase": None, "since": None, "acute": 560.0, "chronic": 700.0, "lo": 560.0, "hi": 1050.0,
                           "acwr": 0.8, "src": "est"}
    assert x["focus"]["src"] == "est" and [(r["key"], r["value"], r["lo"]) for r in x["focus"]["rows"]] == [
        ("anaerobic", 240.0, None), ("high_aerobic", 360.0, None), ("low_aerobic", 2200.0, None)]
    g.activities = g.activities[:20]                                     # under 4 weeks: nothing of ours
    assert kdata.extras(g, today)["status"] is None and kdata.extras(g, today)["focus"] is None


def test_cards_mark_our_chronic_load_and_focus():
    g, today = _ours()
    x = kdata.extras(g, today)
    load = ov.load_card(g, today, x)
    assert load["band"] == [560.0, 1050.0] and "Acute : chronic 0.8, ours" in load["chips"]
    assert load["band_label"] == "Optimal range 560–1,050 (from our chronic load estimate, 700)"
    st = ov.status_card(g, x)
    assert st["phrase"] is None and st["focus_caption"] == "Our estimate from activity loads, no Garmin targets"
    assert [f["range"] for f in st["focus"]] == [None, None, None]
