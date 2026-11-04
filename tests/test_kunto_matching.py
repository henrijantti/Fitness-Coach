import datetime as dt
import pathlib
import shutil

import pytest

from kunto import data as kdata
from kunto import matching as km
from kunto import plan as kplan

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "kunto"
MON = dt.date(2026, 10, 5)


def act(day, hhmm, type_="running", km_=5.0, min_=30.0, hr=140.0, cad=166.0):
    d = MON + dt.timedelta(days=day)
    h, m = hhmm.split(":")
    return {"date": d, "start": dt.datetime(d.year, d.month, d.day, int(h), int(m)), "type": type_, "name": type_,
            "km": km_, "min": min_, "avg_hr": hr, "cadence": cad}


def sess(kind, title="x", optional=False):
    return kplan.normalize_session({"kind": kind, "title": title, "optional": optional})


def week(**days):
    """days: mon=[sessions], ...; missing days are rest days."""
    return [{"date": MON + dt.timedelta(days=i), "dow": d,
             "sessions": days.get(d, [sess("rest", "Rest")])} for i, d in enumerate(kplan.DAYS)]


def statuses(result):
    return {d["dow"]: [s["status"] for s in d["sessions"]] for d in result}


# ---------- classification, dedupe, units ----------

def test_classify():
    assert km.classify(act(0, "07:00")) == "run"
    assert km.classify(act(0, "07:00", "treadmill_running")) == "run"
    assert km.classify(act(0, "07:00", cad=72)) == "run"            # a run is a run, whatever its cadence (Oct 11)
    assert km.classify(act(0, "07:00", cad=None)) == "run"
    assert km.classify(act(0, "07:00", "strength_training")) == "gym"
    assert km.classify(act(0, "07:00", "cross_country_skiing_ws")) == "ski"
    assert km.classify(act(0, "07:00", "cross_country_indoor_skiing")) == "ski"    # the Fenix "XC Ski Indoor" (SkiErg)
    assert km.classify(act(0, "07:00", "field_hockey")) == "floorball"            # the athlete's floorball type (Sep 30)
    assert km.classify(act(0, "07:00", "indoor_cardio")) == "other"


def test_floorball_title():
    from kunto import fmt
    assert fmt.activity_title({"type": "field_hockey"}, "floorball") == "Floorball"


def test_duplicate_runs_within_60_s_count_once():
    a, b = act(0, "07:40", km_=5.2), act(0, "07:40", km_=5.19)
    b["start"] += dt.timedelta(seconds=30)
    assert km.dedupe_runs([a, b]) == [a]
    c = act(0, "07:42", km_=5.19)                      # 2 min later: a second file, not a duplicate
    assert km.dedupe_runs([a, c]) == [a, c]


def test_same_day_runs_are_summed_into_one_unit():
    [u] = km.units([act(0, "07:30", km_=3.0, min_=16.0, hr=138.0), act(0, "07:52", km_=3.1, min_=16.5, hr=142.0)])
    assert (u["cls"], u["km"], u["min"], u["avg_hr"], len(u["parts"])) == ("run", 6.1, 32.5, 140, 2)


def test_run_km_excludes_duplicates_and_floorball_but_keeps_a_low_cadence_run():
    dup = act(0, "07:40", km_=5.19)
    dup["start"] += dt.timedelta(seconds=20)
    acts = [act(0, "07:40", km_=5.2), dup, act(1, "19:30", "field_hockey", km_=4.1), act(3, "08:00", km_=6.0),
            act(4, "08:30", km_=5.4, cad=72), act(9, "08:00", km_=9.0)]
    assert km.run_km(acts, MON, MON + dt.timedelta(days=6)) == 16.6


# ---------- statuses ----------

def test_done_missed_today_upcoming_rest():
    days = week(mon=[sess("run")], tue=[sess("gym")], wed=[sess("run")], thu=[sess("run")])
    res = km.match_week(days, km.units([act(0, "07:00")]), today=MON + dt.timedelta(days=2))
    assert statuses(res) == {"mon": ["done"], "tue": ["missed"], "wed": ["today"], "thu": ["upcoming"],
                             "fri": ["rest"], "sat": ["rest"], "sun": ["rest"]}
    assert res[0]["sessions"][0]["unit"]["km"] == 5.0


def test_optional_not_done_is_skipped_never_missed():
    days = week(wed=[sess("gym", optional=True), sess("run", optional=True)])
    res = km.match_week(days, [], today=MON + dt.timedelta(days=5))
    assert statuses(res)["wed"] == ["skipped", "skipped"]


def test_optional_session_never_moves():
    # amendment 2026-09-27: an optional session is credited on its own day only, so a run on
    # Saturday does not make Friday's optional run "moved"; it stays an unplanned extra
    days = week(fri=[sess("run", "Run in 5 km easy", optional=True)])
    res = km.match_week(days, km.units([act(5, "16:00")]), today=MON + dt.timedelta(days=6))
    fri = res[4]["sessions"][0]
    assert (fri["status"], fri["unit"], fri["moved_to"]) == ("skipped", None, None)
    assert all(s["unit"] is None for d in res for s in d["sessions"])    # no session holds Saturday's run


def test_moved_to_another_day_of_the_week():
    days = week(mon=[sess("run")], tue=[sess("floorball")])
    res = km.match_week(days, km.units([act(2, "18:00")]), today=MON + dt.timedelta(days=3))
    s = res[0]["sessions"][0]
    assert (s["status"], s["moved_to"]) == ("moved", MON + dt.timedelta(days=2))
    assert statuses(res)["tue"] == ["missed"]            # floorball never moves


def test_moved_prefers_an_unplanned_extra():
    days = week(thu=[sess("run")], fri=[sess("run", optional=True)], sat=[sess("gym")])
    acts = [act(4, "08:00"), act(5, "10:00", "strength_training"), act(5, "16:00")]
    res = km.match_week(days, km.units(acts), today=MON + dt.timedelta(days=6))
    assert statuses(res)["thu"] == ["moved"] and res[3]["sessions"][0]["moved_to"] == MON + dt.timedelta(days=5)
    assert statuses(res)["fri"] == ["done"] and statuses(res)["sat"] == ["done"]


def test_one_activity_cannot_satisfy_two_sessions():
    days = week(mon=[sess("run")], thu=[sess("run")])
    res = km.match_week(days, km.units([act(0, "07:00")]), today=MON + dt.timedelta(days=6))
    assert statuses(res)["mon"] == ["done"] and statuses(res)["thu"] == ["missed"]


def test_required_matched_before_optional():
    days = week(wed=[sess("run", "Run home", optional=True)], thu=[sess("run", "Commute")])
    res = km.match_week(days, km.units([act(2, "18:00")]), today=MON + dt.timedelta(days=5))
    assert statuses(res)["thu"] == ["moved"]             # once Thu has passed, the run goes to the required session
    assert statuses(res)["wed"] == ["skipped"]


def test_only_a_passed_day_can_be_moved():
    days = week(wed=[sess("run", "Run home", optional=True)], thu=[sess("run", "Commute")])
    res = km.match_week(days, km.units([act(2, "18:00")]), today=MON + dt.timedelta(days=2))
    assert statuses(res)["wed"] == ["done"] and statuses(res)["thu"] == ["upcoming"]
    days = week(mon=[sess("run")])
    res = km.match_week(days, km.units([act(1, "18:00")]), today=MON)
    assert statuses(res)["mon"] == ["today"]


def test_floorball_matches_its_field_hockey_type_only():
    days = week(tue=[sess("floorball")])
    res = km.match_week(days, km.units([act(1, "19:30", "field_hockey")]), today=MON + dt.timedelta(days=6))
    assert statuses(res)["tue"] == ["done"]
    for type_ in ("indoor_cardio", "strength_training", "other", "walking"):
        res = km.match_week(days, km.units([act(1, "19:30", type_)]), today=MON + dt.timedelta(days=6))
        assert statuses(res)["tue"] == ["missed"], type_


def test_floorball_never_takes_a_run_whatever_its_cadence():
    days = week(tue=[sess("floorball")])
    for cad in (72, 170):
        res = km.match_week(days, km.units([act(1, "19:30", cad=cad)]), today=MON + dt.timedelta(days=6))
        assert statuses(res)["tue"] == ["missed"], cad


def test_low_cadence_run_satisfies_a_run_session():
    days = week(fri=[sess("run", optional=True)])
    res = km.match_week(days, km.units([act(4, "08:30", km_=5.4, hr=98.0, cad=72)]), today=MON + dt.timedelta(days=6))
    assert statuses(res)["fri"] == ["done"] and res[4]["sessions"][0]["unit"]["km"] == 5.4


def test_test_and_event_accept_any_activity_same_day_only():
    days = week(sat=[sess("test", "Benchmarks")], sun=[sess("event", "Race")])
    res = km.match_week(days, km.units([act(5, "10:00", "strength_training"), act(4, "10:00", "indoor_cardio")]),
                        today=MON + dt.timedelta(days=7))
    assert statuses(res)["sat"] == ["done"] and statuses(res)["sun"] == ["missed"]


def test_floorball_never_credits_a_test_or_event():
    # Sat Oct 10: two floorball games on the Benchmarks + Legs day; the gym was skipped
    days = week(sat=[sess("test", "Benchmarks + Legs")])
    games = [act(5, "15:00", "field_hockey", min_=47.1), act(5, "17:19", "field_hockey", min_=33.8)]
    res = km.match_week(days, km.units(games), today=MON + dt.timedelta(days=6))
    assert statuses(res)["sat"] == ["missed"]


def test_fixture_weeks_end_to_end(tmp_path):
    shutil.copytree(FIX / "data", tmp_path / "data")
    g = kdata.load_garmin(tmp_path)
    plan = kplan.load_plan(ROOT / "training-plan-2026-27.json")
    today = dt.date(2026, 10, 7)
    w1 = km.plan_week_status(plan, kplan.get_week(plan, 1), g.activities, today)
    assert statuses(w1) == {"mon": ["done"], "tue": ["done"], "wed": ["skipped", "skipped"], "thu": ["moved"],
                            "fri": ["done"], "sat": ["done"], "sun": ["missed"]}
    assert w1[0]["sessions"][0]["unit"]["km"] == 6.1            # 3.0 + 3.1, one session saved as two files
    assert w1[3]["sessions"][0]["moved_to"] == dt.date(2026, 10, 3)
    w2 = km.plan_week_status(plan, kplan.get_week(plan, 2), g.activities, today)
    assert statuses(w2)["tue"] == ["done"]                      # floorball, recorded as Field Hockey
    assert statuses(w2)["wed"] == ["today", "today"]
    assert statuses(w2)["sat"] == ["upcoming"]
    assert km.run_km(g.activities, dt.date(2026, 9, 28), dt.date(2026, 10, 4)) == 15.0
    assert km.run_km(g.activities, dt.date(2026, 10, 5), dt.date(2026, 10, 11)) == 5.2


# ---------- data coverage: a day the Garmin data does not cover yet is "nodata", never "missed" ----------

def test_past_day_not_covered_by_the_data_is_nodata_not_missed():
    # today = Wed; the newest Garmin daily row is Mon (the Tue and Wed pulls failed): Mon is only
    # covered up to its morning pull, so Mon and Tue cannot be judged yet
    res = km.match_week(week(mon=[sess("run")], tue=[sess("floorball")], wed=[sess("run")]), [],
                        MON + dt.timedelta(days=2), data_through=MON)
    assert statuses(res)["mon"] == ["nodata"] and statuses(res)["tue"] == ["nodata"]
    assert statuses(res)["wed"] == ["today"]


def test_covered_days_are_still_judged():
    # the pull ran today (Wed): Mon and Tue are fully covered, so an unmatched required session is missed
    res = km.match_week(week(mon=[sess("run")], tue=[sess("run", optional=True)]), [],
                        MON + dt.timedelta(days=2), data_through=MON + dt.timedelta(days=2))
    assert statuses(res)["mon"] == ["missed"] and statuses(res)["tue"] == ["skipped"]


def test_a_done_session_stays_done_even_on_an_uncovered_day():
    res = km.match_week(week(mon=[sess("run")]), km.units([act(0, "07:00")]),
                        MON + dt.timedelta(days=2), data_through=MON)
    assert statuses(res)["mon"] == ["done"]


def test_no_garmin_data_at_all_means_nodata_for_every_past_session():
    res = km.match_week(week(mon=[sess("run")]), [], MON + dt.timedelta(days=2), data_through=dt.date.min)
    assert statuses(res)["mon"] == ["nodata"]


# ---------- gym sessions are credited by what Hevy shows was lifted (decision-log 2026-10-04) ----------

SAT, SUN = MON + dt.timedelta(days=5), MON + dt.timedelta(days=6)
NEXT_MON = MON + dt.timedelta(days=7)


def gym(focus, optional=False):
    return kplan.normalize_session({"kind": "gym", "title": focus, "focus": focus, "optional": optional})


def lift(day, focus=None):
    a = act(day, "10:00", "strength_training", km_=None, cad=None)
    return {**a, "focus": focus} if focus else a


def split_week(**extra):
    return week(sat=[gym("legs")], sun=[gym("upper")], **extra)


def seen(result):
    """{dow: (status, the day it moved to)} for every non-rest session."""
    return {d["dow"]: (s["status"], s["moved_to"]) for d in result for s in d["sessions"] if s["kind"] != "rest"}


def test_with_gym_focus_tags_strength_activities_only():
    acts = [act(5, "10:00", "strength_training"), act(5, "16:00"), act(6, "10:00", "strength_training")]
    tagged = km.with_gym_focus(acts, {SAT: "upper"})
    assert [a.get("focus") for a in tagged] == ["upper", None, None]
    assert "focus" not in acts[0]                                        # the input rows are left alone
    assert [u["focus"] for u in km.units(tagged) if u["cls"] == "gym"] == ["upper", None]


def test_a_gym_session_ticks_when_hevy_shows_its_focus():
    res = km.match_week(split_week(), km.units([lift(5, "legs"), lift(6, "upper")]), NEXT_MON)
    assert seen(res) == {"sat": ("done", None), "sun": ("done", None)}


def test_swapped_gym_days_show_as_moved():
    res = km.match_week(split_week(), km.units([lift(5, "upper"), lift(6, "legs")]), NEXT_MON)
    assert seen(res) == {"sat": ("moved", SUN), "sun": ("moved", SAT)}


def test_a_session_lifted_a_day_early_is_credited_at_once_and_its_partner_waits():
    """Sat planned Legs, Hevy shows upper: on Sunday the Upper is done (on Sat) and the Legs is swapped to
    Sunday, not missed. The same already holds on the Saturday itself."""
    for today in (SUN, SAT):
        res = km.match_week(split_week(), km.units([lift(5, "upper")]), today)
        assert seen(res) == {"sat": ("swapped", SUN), "sun": ("moved", SAT)}, today


def test_a_swap_never_finished_is_a_miss_once_the_week_is_over():
    res = km.match_week(split_week(), km.units([lift(5, "upper")]), NEXT_MON)
    assert seen(res) == {"sat": ("missed", None), "sun": ("moved", SAT)}


def test_a_swap_finishes_before_hevy_is_pulled_for_the_second_day():
    """Sunday evening: Saturday's session is in Hevy (upper), Sunday's strength activity is not yet."""
    res = km.match_week(split_week(), km.units([lift(5, "upper"), lift(6)]), SUN)
    assert seen(res) == {"sat": ("moved", SUN), "sun": ("moved", SAT)}


def test_one_logged_day_settles_a_swap_with_an_unlogged_day():
    res = km.match_week(split_week(), km.units([lift(5), lift(6, "legs")]), NEXT_MON)
    assert seen(res) == {"sat": ("moved", SUN), "sun": ("moved", SAT)}


def test_the_wrong_focus_is_an_extra_not_a_tick():
    res = km.match_week(split_week(), km.units([lift(5, "upper"), lift(6, "upper")]), NEXT_MON)
    assert seen(res) == {"sat": ("missed", None), "sun": ("done", None)}


@pytest.mark.parametrize("focus", [None, "full"])
def test_without_a_clear_hevy_focus_any_strength_activity_ticks_its_day(focus):
    res = km.match_week(split_week(), km.units([lift(5, focus)]), NEXT_MON)
    assert seen(res) == {"sat": ("done", None), "sun": ("missed", None)}
    assert seen(km.match_week(split_week(), km.units([lift(5, focus)]), SUN))["sun"] == ("today", None)


def test_a_full_body_session_takes_whatever_was_lifted():
    days = week(wed=[gym("full")])
    for focus in ("legs", "upper", "full", None):
        assert seen(km.match_week(days, km.units([lift(2, focus)]), NEXT_MON)) == {"wed": ("done", None)}, focus


def test_early_credit_needs_a_day_that_had_no_use_for_the_activity():
    thu = MON + dt.timedelta(days=3)
    days = split_week(wed=[gym("upper", optional=True)])
    res = km.match_week(days, km.units([lift(2, "upper")]), thu)          # the Wed bonus was simply done
    assert seen(res) == {"wed": ("done", None), "sat": ("upcoming", None), "sun": ("upcoming", None)}
    res = km.match_week(days, km.units([lift(3, "upper")]), SAT)          # an upper session on a free Thursday
    assert seen(res)["sun"] == ("moved", thu) and seen(res)["sat"] == ("today", None)
    res = km.match_week(days, km.units([lift(3)]), SAT)                   # not in Hevy: it may be anything
    assert seen(res)["sun"] == ("upcoming", None)


def test_a_past_session_takes_a_matching_activity_from_another_day():
    days = split_week(wed=[gym("upper", optional=True)])
    res = km.match_week(days, km.units([lift(2, "legs")]), NEXT_MON)      # legs on Wednesday, nothing else
    assert seen(res) == {"wed": ("skipped", None), "sat": ("moved", MON + dt.timedelta(days=2)), "sun": ("missed", None)}
