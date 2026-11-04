import datetime as dt
import pathlib

import pytest

from kunto import card, progression
from kunto import gym
from kunto import plan as kplan

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real_plan():
    return kplan.load_plan(ROOT / "training-plan-2026-27.json")


def item(text):
    it = card.parse_item(text)
    return it["name"], it["rx"], it["note"], it["load"]


# ---------- reading a chip ----------

@pytest.mark.parametrize("text,expected", [
    ("strict OHP 4×6–8 first · 47.5 kg", ("strict OHP", "4×6–8", "first", "47.5 kg")),
    ("weighted pull-ups 4×5–6 · +5 kg", ("weighted pull-ups", "4×5–6", "", "+5 kg")),
    ("trap bar 3×5 · ~100 kg, a new lift: start light", ("trap bar", "3×5", "a new lift: start light", "~100 kg")),
    ("single-leg RDL 3×8/side, one dumbbell", ("single-leg RDL", "3×8/side", "one dumbbell", "")),
    ("external rotation 2×15/side (cable or band)", ("external rotation", "2×15/side", "cable or band", "")),
    ("body-weight pull-ups 2 sets, 2 reps short of failure",
     ("body-weight pull-ups", "2 sets", "2 reps short of failure", "")),
    ("front squat 4×4–5 @ RPE 7–9", ("front squat", "4×4–5 @ RPE 7–9", "", "")),
    ("sled push 3 × 15 m @ ~50% BW", ("sled push", "3 × 15 m @ ~50% BW", "", "")),
    ("4 × 15 m accelerations", ("accelerations", "4 × 15 m", "", "")),
    ("SkiErg 8 × 30 s / 30 s (Nov–Feb: alternate weeks 3 × 5′ steady double poling)",
     ("SkiErg", "8 × 30 s / 30 s", "Nov–Feb: alternate weeks 3 × 5′ steady double poling", "")),
    ("SkiErg 10′ steady", ("SkiErg", "10′ steady", "", "")),
    ("ab wheel 8–10", ("ab wheel", "8–10", "", "")),
    ("Copenhagen side plank 20–30 s/side", ("Copenhagen side plank", "20–30 s/side", "", "")),
    ("standing broad jump, best of 3", ("standing broad jump", "best of 3", "", "")),
    ("10-s SkiErg sprint, best of 3 (2–3 min rest), same damper each time: record peak and 10-s average watts",
     ("10-s SkiErg sprint", "best of 3", "2–3 min rest, same damper each time: record peak and 10-s average watts", "")),
    ("strict OHP: work up to one top set of 5 @ RPE 8", ("strict OHP", "work up to one top set of 5 @ RPE 8", "", "")),
    ("weighted pull-up: work up to one top set of 5 @ RPE 8 (log body weight)",
     ("weighted pull-up", "work up to one top set of 5 @ RPE 8", "log body weight", "")),
    ("15 m sprint or sled time: best of 3 (the tests take ~20 min)",
     ("15 m sprint or sled time", "best of 3", "the tests take ~20 min", "")),
    ("back squat, deadlift, push press: work up to an RPE-8 triple",
     ("back squat, deadlift, push press", "work up to an RPE-8 triple", "", "")),
    ("then front squat 4×6–8 · 65 kg", ("front squat", "4×6–8", "", "65 kg")),
    ("triceps", ("triceps", "", "", "")),
])
def test_parse_item(text, expected):
    assert item(text) == expected


def test_a_block_chip_becomes_lettered_items():
    c = card.parse_chip("core block, 2 rounds: Copenhagen side plank 20–30 s/side · Pallof press 10/side · "
                        "ab wheel 8–10 · suitcase carry 40 m/side")
    assert (c["block"], c["detail"]) == ("core", "2 rounds")
    assert [(i["name"], i["rx"]) for i in c["items"]] == [
        ("Copenhagen side plank", "20–30 s/side"), ("Pallof press", "10/side"), ("ab wheel", "8–10"),
        ("suitcase carry", "40 m/side")]
    st = card.parse_chip("station block 15′, alternating weeks: A wall balls 3 × 25 @ 6 kg + SkiErg 1,000 m · B row")
    assert (st["block"], st["detail"], [i["name"] for i in st["items"]]) == (
        "station", "15′, alternating weeks", ["A wall balls 3 × 25 @ 6 kg + SkiErg 1,000 m", "B row"])


def test_a_chip_of_several_exercises_splits_unless_a_load_follows():
    assert [i["name"] for i in card.parse_chip("then front squat 4×6–8 · trap bar 3×5")["items"]] == [
        "front squat", "trap bar"]
    assert len(card.parse_chip("strict OHP 4×6–8 · 42.5 kg")["items"]) == 1


def test_rx_text():
    assert card.rx_text("4×6–8") == "4 × 6–8"
    assert card.rx_text("work up to one top set of 5 @ RPE 8") == "Top set 5 @ RPE 8"
    assert card.rx_text("4 sets of 3–5, rising to one top set @ RPE 8") == "4 × 3–5 → top set @ RPE 8"


def test_every_plan_chip_reads_as_rows(real_plan):
    """Each gym or test card row has a name, and a prescription unless it is one of the few plain names."""
    plain = {"triceps", "cuff", "rear delts + curls"}
    for w in real_plan["weeks"]:
        for d in kplan.resolve_week(real_plan, w):
            for s in d["sessions"]:
                c = card.build(s)
                if c is None:
                    assert s["kind"] != "gym"
                    continue
                for sec in c["sections"]:
                    for r in sec["rows"]:
                        assert r["name"], (w["week"], s["title"])
                        assert r["rx"] or r["name"].lower() in plain or sec["label"] == "Stations", (
                            w["week"], s["title"], r)


# ---------- the card ----------

def lift_baselines(real_plan):
    return kplan.sessions_for_date(real_plan, dt.date(2026, 10, 24))[0]


def test_lift_baselines_card(real_plan):
    c = card.build(lift_baselines(real_plan))
    assert [(s["label"], s["sub"]) for s in c["sections"]] == [
        ("Tests", "ramp: bar ×5 → ~50% ×5 → ~70% ×3 → ~85% ×1–2 → rest 3′"), ("Accessories", ""),
        ("Core", "1 round")]
    tests = c["sections"][0]["rows"]
    assert [(r["n"], r["name"], r["rx"], r["key"]) for r in tests] == [
        ("1", "Strict OHP", "Top set 5 @ RPE 8", True), ("2", "Front squat", "Top set 5 @ RPE 8", True),
        ("3", "Weighted pull-up", "Top set 5 @ RPE 8", True)]
    assert tests[2]["note"] == "Log body weight"
    assert [r["n"] for r in c["sections"][2]["rows"]] == ["5a", "5b", "5c", "5d"]
    assert c["warmup"]["label"] == "Warm-up · 12 min"
    assert c["warmup"]["summary"].startswith("Easy rower or SkiErg · Band pull-apart · ")
    assert [t["label"] for t in c["time"]] == ["Warm-up", "Tests", "Accessories", "Core"]
    assert c["time"][0]["min"] == 12 and abs(sum(t["min"] for t in c["time"]) - 70) <= 2


def test_the_card_shows_the_last_top_set_of_each_main_lift(real_plan):
    D = dt.date
    sets = [gym.Set(D(2026, 10, 11), "Front Squat", "normal", 65.0, 6, 8.0),
            gym.Set(D(2026, 10, 18), "Front Squat", "warmup", 40.0, 5),
            gym.Set(D(2026, 10, 18), "Front Squat", "normal", 60.0, 4, 8.0),
            gym.Set(D(2026, 10, 18), "Front Squat", "normal", 60.0, 5, 8.0),
            gym.Set(D(2026, 10, 18), "Pull Up (Weighted)", "normal", 10.0, 5, 8.5),
            gym.Set(D(2026, 10, 25), "Front Squat", "normal", 80.0, 5)]          # after today: not yet
    lasts = card.last_top_sets(sets, D(2026, 10, 21))
    assert lasts["Front Squat"] == sets[3]
    rows = card.build(lift_baselines(real_plan), lasts)["sections"][0]["rows"]
    assert "last" not in rows[0]                                                    # no OHP in this log
    assert rows[1]["last"] == {"set": "60 kg × 5", "tail": "@ 8 · Sun 18 Oct"}
    assert rows[2]["last"] == {"set": "+10 kg × 5", "tail": "@ 8.5 · Sun 18 Oct"}
    assert card.last_top_sets(None, D(2026, 10, 21)) == {}


def test_the_card_shows_each_lifts_next_load_and_keeps_a_differing_plan_load(real_plan):
    D = dt.date
    sets = [gym.Set(D(2026, 10, 24), "Overhead Press (Barbell)", "normal", 60.0, 5),
            gym.Set(D(2026, 10, 18), "Pull Up (Weighted)", "normal", 10.0, 6, 8.0)]
    sun = kplan.sessions_for_date(real_plan, D(2026, 11, 1))[0]
    nexts = progression.upcoming(real_plan, sets, D(2026, 10, 26))[D(2026, 11, 1)]
    rows = {r["name"]: r for sec in card.build(sun, {}, nexts)["sections"] for r in sec["rows"]}
    ohp = rows["Strict OHP"]
    assert ohp["next"] == {"load": "45 kg", "why": "the plan's start after the test", "ease": ""}
    assert "Plan" not in ohp["note"]                                    # the same load is not shown twice
    assert "next" not in rows["Hanging leg raises"]                     # body weight: no load
    assert card.build(sun)["sections"][1]["rows"][0].get("next") is None


def test_only_gym_sessions_and_sessions_with_a_warmup_get_a_card(real_plan):
    cooper = kplan.sessions_for_date(real_plan, dt.date(2026, 10, 22))[0]
    assert cooper["title"] == "Cooper #1" and card.build(cooper) is None
    run = kplan.sessions_for_date(real_plan, dt.date(2026, 10, 19))[0]
    assert card.build(run) is None


def test_compact_leads_with_the_main_lifts(real_plan):
    sun = kplan.sessions_for_date(real_plan, dt.date(2026, 10, 25))[0]
    assert card.compact(card.build(sun)) == {
        "lead": [{"name": "Strict OHP", "rx": "4 × 6–8"}, {"name": "Weighted pull-ups", "rx": "4 × 5–6"}],
        "more": 6, "warmup": "warm-up 8′"}


def test_time_split_needs_planned_minutes():
    assert card.time_split([], None, None) == []
