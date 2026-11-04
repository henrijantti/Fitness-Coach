"""Tests for kunto/progression.py: plan section 6's load rule as each lift's next load, on the real plan json."""
import datetime as dt
import pathlib

from kunto import gym
from kunto import plan as kplan
from kunto import progression as pr

REPO = pathlib.Path(__file__).resolve().parents[1]
PLAN = kplan.load_plan(REPO / "training-plan-2026-27.json")
D = dt.date
OHP = "Overhead Press (Barbell)"
FSQ = "Front Squat"
ROW = "Chest Supported Incline Row (Dumbbell)"
FACE = "Face Pull"
SUN_NOV_1, SAT_NOV_7, SUN_NOV_15 = D(2026, 11, 1), D(2026, 11, 7), D(2026, 11, 15)   # Nov 7: week 6 upper, Sunday games


def sets(day, exercise, load, reps, rpes):
    return [gym.Set(day, exercise, "normal", load, r, e) for r, e in zip(reps, rpes)]


TEST = sets(D(2026, 10, 24), OHP, 60.0, [5], [None])


def test_after_the_test_the_first_session_starts_at_the_plan_chip_load():
    n = pr.suggest(PLAN, TEST, "strict ohp", SUN_NOV_1)
    assert (n.load, n.code, n.why) == (45.0, "start", "the plan's start after the test")
    assert n.basis == "60 kg × 5 RPE – · Sat 24 Oct"


def test_every_set_at_the_top_at_rpe_9_or_under_adds_2_5_kg():
    log = TEST + sets(SUN_NOV_1, OHP, 52.5, [5, 5, 5, 5], [7, 7.5, 8, 8])
    n = pr.suggest(PLAN, log, "strict ohp", SUN_NOV_15)
    assert (n.load, n.code, n.text) == (55.0, "up", "55 kg")
    assert n.why == "+2.5 kg: every set at the top at RPE ≤9"
    assert n.basis == "52.5 kg × 5,5,5,5 @ 7–8 · Sun 1 Nov"


def test_a_deload_week_keeps_the_load_and_its_session_moves_nothing():
    log = TEST + sets(SUN_NOV_1, OHP, 52.5, [5, 5, 5, 5], [7, 7.5, 8, 8])
    assert pr.suggest(PLAN, log, "strict ohp", SAT_NOV_7).code == "deload"          # week 6
    assert pr.suggest(PLAN, log, "strict ohp", SAT_NOV_7).load == 52.5
    # the week-6 session at 52.5 × 3,3 is skipped: week 7 still reads Nov 1's sets
    log += sets(SAT_NOV_7, OHP, 52.5, [3, 3], [6, 6])
    assert pr.suggest(PLAN, log, "strict ohp", SUN_NOV_15).load == 55.0


def test_a_missed_rep_or_a_set_over_rpe_9_keeps_the_load():
    missed = TEST + sets(SUN_NOV_1, OHP, 52.5, [5, 5, 4, 2], [8, 8.5, 9, 9])
    assert (pr.suggest(PLAN, missed, "strict ohp", SUN_NOV_15).load,
            pr.suggest(PLAN, missed, "strict ohp", SUN_NOV_15).why) == (52.5, "same load: missed reps")
    grind = TEST + sets(SUN_NOV_1, OHP, 52.5, [5, 5, 5, 5], [8, 9, 9, 9.5])
    assert pr.suggest(PLAN, grind, "strict ohp", SUN_NOV_15).code == "repeat"


def test_missing_rpe_shows_both_loads():
    log = TEST + sets(SUN_NOV_1, OHP, 52.5, [5, 5, 5, 5], [7, None, 8, 8])
    n = pr.suggest(PLAN, log, "strict ohp", SUN_NOV_15)
    assert (n.code, n.text) == ("confirm", "52.5 kg (55 kg if every set was ≤9)")


def test_trap_bar_steps_by_5_and_weighted_pull_up_shows_added_kg():
    log = sets(D(2026, 10, 31), "Deadlift (Trap bar)", 100.0, [5, 5, 5], [7, 7, 7.5])
    assert pr.suggest(PLAN, log, "trap bar", D(2026, 11, 14)).load == 105.0
    pu = sets(SUN_NOV_1, "Pull Up (Weighted)", 7.5, [6, 6, 6, 6], [7, 8, 8, 8.5])
    assert pr.suggest(PLAN, pu, "weighted pull-up", SUN_NOV_15).text == "+10 kg"


def test_no_session_and_no_chip_load_gives_no_load():
    n = pr.suggest(PLAN, [], "trap bar", D(2026, 10, 31))           # week 5: "3×5 @ RPE 7, find the load"
    assert (n.load, n.text, n.why) == (None, "", "no session yet: find the load")


def test_a_test_day_gets_no_suggestion():
    assert pr.suggest(PLAN, [], "strict ohp", D(2026, 10, 24)) is None


def test_accessories_step_at_the_top_at_rpe_8_to_a_weight_already_used():
    log = sets(D(2026, 9, 1), FACE, 28.75, [12], [8]) + sets(SUN_NOV_1, FACE, 27.5, [15, 15, 15], [7, 7.5, 8])
    n = pr.suggest(PLAN, log, "face pull", SUN_NOV_15)
    assert (n.load, n.why) == (28.75, "+1.25 kg: every set at the top at RPE ≤8")
    hard = sets(SUN_NOV_1, ROW, 24.0, [10, 10, 10], [8, 8.5, 9])
    assert pr.suggest(PLAN, hard, "chest-supported db row", SUN_NOV_15).code == "hold"
    new = sets(SUN_NOV_1, ROW, 24.0, [10, 10, 10], [7, 7, 8])
    assert pr.suggest(PLAN, new, "chest-supported db row", SUN_NOV_15).load == 26.5   # nothing used above: +2.5


def test_upcoming_puts_each_lift_on_its_next_planned_session():
    log = TEST + sets(SUN_NOV_1, OHP, 52.5, [5, 5, 5, 5], [7, 7.5, 8, 8])
    up = pr.upcoming(PLAN, log, D(2026, 11, 2))
    assert up[SAT_NOV_7]["strict ohp"].code == "deload"
    assert "strict ohp" not in up.get(D(2026, 11, 15), {})                 # only the next session gets one
    assert pr.upcoming(PLAN, None, D(2026, 11, 2)) == {}


def test_a_session_done_on_a_swapped_day_counts_for_its_plan_day():
    # Sunday's OHP done on Saturday Oct 31: the next OHP is week 6's, not Sun Nov 1
    log = TEST + sets(D(2026, 10, 31), OHP, 52.5, [5, 5, 5, 5], [7, 7, 8, 8])
    up = pr.upcoming(PLAN, log, D(2026, 10, 31))
    assert "strict ohp" not in up.get(SUN_NOV_1, {}) and up[SAT_NOV_7]["strict ohp"].load == 52.5


def test_an_ease_off_sign_caps_the_next_hard_gym_session_at_rpe_7():
    daily = {D(2026, 10, 27) + dt.timedelta(days=i): {"rhr": v, "hrv_status": "BALANCED"}
             for i, v in enumerate((50, 51, 52, 53, 54))}                     # climbing Oct 28 to Oct 31
    up = pr.upcoming(PLAN, TEST, D(2026, 10, 31), daily)
    assert up[D(2026, 10, 31)]["front squat"].ease == "RPE ≤7: resting HR climbing 3 days"
    assert up[SUN_NOV_1]["strict ohp"].ease == ""                           # only the next hard gym session
    assert pr.ease_signs({D(2026, 10, 31): {"rhr": 50, "hrv_status": "UNBALANCED"}}, D(2026, 10, 31)) == \
        ["HRV status off Balanced"]
    assert pr.ease_signs({}, D(2026, 10, 31)) == []


def test_label():
    assert [pr.label(k) for k in ("strict ohp", "db curl", "single-leg rdl")] == ["Strict OHP", "DB curl",
                                                                                  "Single-leg RDL"]


def test_a_pending_swapped_session_keeps_its_next_loads_under_its_plan_day():
    # Sunday's upper done on Sat Oct 31, Saturday's legs swapped to Sun Nov 1 (matching.plan_week_status)
    log = TEST + sets(D(2026, 10, 24), FSQ, 70.0, [5], [None]) + sets(D(2026, 10, 31), OHP, 52.5, [5] * 4, [7] * 4)
    daily = {D(2026, 10, 28) + dt.timedelta(days=i): {"rhr": v, "hrv_status": "BALANCED"}
             for i, v in enumerate((50, 51, 52, 53, 54))}                     # climbing Oct 29 to Nov 1
    up = pr.upcoming(PLAN, log, SUN_NOV_1, daily, swapped={D(2026, 10, 31): SUN_NOV_1})
    fsq = up[D(2026, 10, 31)]["front squat"]
    assert (fsq.load, fsq.ease) == (55.0, "RPE ≤7: resting HR climbing 3 days")      # due today: the eased one
    assert "strict ohp" not in up.get(SUN_NOV_1, {}) and up[SAT_NOV_7]["strict ohp"].code == "deload"
    # without the swap the legs session is past: front squat waits for week 6
    assert "front squat" in pr.upcoming(PLAN, log, SUN_NOV_1)[D(2026, 11, 7)]
