import datetime as dt
import json
import os
import pathlib
import shutil

import pytest

from hevy import rows as hrows
from kunto import gymtab, render

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "kunto"
D = dt.date
TODAY = D(2026, 10, 4)


@pytest.fixture
def root(tmp_path):
    shutil.copytree(FIX / "data", tmp_path / "data")
    return tmp_path


def row(title, day, exercise, kg=None, reps=None, *, kind="normal", sec=None, km=None, rpe=None,
        note="", desc="", start="10:00", end="11:00"):
    """One set in Hevy's export layout; day is '3 Oct 2026'."""
    return [title, f"{day}, {start}", f"{day}, {end}", desc, exercise, None, note, 0, kind, kg, reps, km, sec, rpe]


def write_gym(root, rows):
    p = root / "data" / "gym.csv"
    p.parent.mkdir(exist_ok=True)
    p.write_text(hrows.to_csv(rows), encoding="utf-8", newline="\n")
    return p


def build(root, rows, today=TODAY):
    write_gym(root, rows)
    return gymtab.build_gym(root, today)


def ex_of(g, day, name):
    return next(e for s in g["sessions"] if s["d"] == day for e in s["ex"] if e["n"] == name)


# ---------- sessions ----------

def test_sessions_are_newest_first_under_one_top_line(root):
    g = gymtab.build_gym(root, TODAY)
    assert g["available"] is True
    assert g["line"] == "2 sessions · 25 Sep 2026 to 3 Oct 2026 · 4 exercises"
    assert [(s["d"], s["label"], s["t"]) for s in g["sessions"]] == [
        ("2026-10-03", "Sat 3 Oct 2026", "Legs"), ("2026-09-25", "Fri 25 Sep 2026", "Benchmark tests")]
    assert [s["meta"] for s in g["sessions"]] == ["1 h · 3 exercises · 5 sets", "1 h 30 min · 2 exercises · 2 sets"]


def test_sets_are_labelled_and_the_top_working_set_is_marked(root):
    g = gymtab.build_gym(root, TODAY)
    sq = ex_of(g, "2026-10-03", "Squat (Barbell)")
    assert sq["sets"] == [{"l": "60×5", "w": "warm-up"}, {"l": "100×5", "rpe": "RPE 8"},
                          {"l": "102.5×3", "rpe": "RPE 8.5"}, {"l": "80×10", "w": "drop set"}]
    assert sq["top"] == 2 and sq["v"] == 102.5
    wpu = ex_of(g, "2026-10-03", "Pull Up (Weighted)")
    assert [s["l"] for s in wpu["sets"]] == ["+15×5", "+20×3"] and wpu["top"] == 1
    pu = ex_of(g, "2026-10-03", "Pull Up")
    assert pu["sets"] == [{"l": "12"}] and pu["top"] == 0 and pu["v"] == 12       # "failure" is a working set


def test_set_labels_for_holds_distance_and_bare_weight(root):
    g = build(root, [row("W", "3 Oct 2026", "Dead Hang", sec=48), row("W", "3 Oct 2026", "Dead Hang", sec=120),
                     row("W", "3 Oct 2026", "Ski Erg", km=0.5, sec=125), row("W", "3 Oct 2026", "Sled Push", kg=60),
                     row("W", "3 Oct 2026", "Stretch")])
    labels = {e["n"]: [s["l"] for s in e["sets"]] for e in g["sessions"][0]["ex"]}
    assert labels == {"Dead Hang": ["48 s", "2:00"], "Ski Erg": ["0.5 km · 2:05"], "Sled Push": ["60 kg"],
                      "Stretch": ["-"]}
    assert ex_of(g, "2026-10-03", "Dead Hang")["top"] == 1


def test_a_zero_distance_or_weight_is_not_shown(root):
    """Hevy writes 0 km for a SkiErg piece logged by time only: '0 km · 2:00' would be noise."""
    g = build(root, [row("W", "3 Oct 2026", "Ski Erg", km=0, sec=120), row("W", "3 Oct 2026", "Pull Up", 0, 5)])
    assert [e["sets"][0]["l"] for e in g["sessions"][0]["ex"]] == ["2:00", "5"]
    assert [e["unit"] for e in g["exercises"]] == ["reps", "s"]


def test_an_exercise_with_only_warmups_has_no_top_set(root):
    g = build(root, [row("W", "3 Oct 2026", "Squat (Barbell)", 60, 5, kind="warmup")])
    sq = g["sessions"][0]["ex"][0]
    assert sq["top"] is None and sq["v"] is None and g["sessions"][0]["meta"] == "1 h · 1 exercise · 0 sets"


def test_clock_times_never_reach_the_page(root):
    """Workouts imported from Motra read 2-3 h late (decision-log 2026-09-29): only the date and length show."""
    text = json.dumps(gymtab.build_gym(root, TODAY), ensure_ascii=False)
    assert "12:14" not in text and "13:44" not in text and "10:00" not in text


def test_a_silly_duration_is_left_out(root):
    g = build(root, [row("Left running", "3 Oct 2026", "Pull Up", reps=5, start="08:00", end="13:30"),
                     row("Backwards", "2 Oct 2026", "Pull Up", reps=5, start="11:00", end="10:00")])
    assert [s["meta"] for s in g["sessions"]] == ["1 exercise · 1 set", "1 exercise · 1 set"]


def test_workouts_after_today_are_cut(root):
    g = gymtab.build_gym(root, D(2026, 9, 30))
    assert [s["d"] for s in g["sessions"]] == ["2026-09-25"]
    assert g["line"] == "1 session · 25 Sep 2026 · 2 exercises"


def test_notes_and_the_description_ride_along(root):
    g = build(root, [row("Pull", "3 Oct 2026", "Pull Up", reps=8, note="Hammer grip", desc="Motra effort 8/10")])
    s = g["sessions"][0]
    assert s["note"] == "Motra effort 8/10" and s["ex"][0]["note"] == "Hammer grip"
    plain = build(root, [row("Pull", "3 Oct 2026", "Pull Up", reps=8)])["sessions"][0]
    assert "note" not in plain and "note" not in plain["ex"][0]                  # empty notes are omitted


# ---------- best yet and the change since last time ----------

def test_best_yet_needs_an_earlier_session_to_beat(root):
    g = build(root, [row("A", "1 Sep 2026", "Bench Press (Barbell)", 100, 5),
                     row("B", "8 Sep 2026", "Bench Press (Barbell)", 100, 6),
                     row("C", "15 Sep 2026", "Bench Press (Barbell)", 102.5, 1),
                     row("D", "22 Sep 2026", "Bench Press (Barbell)", 97.5, 8)])
    by_day = {s["d"]: s for s in g["sessions"]}
    seen = {d: (s["ex"][0].get("best", False), s["ex"][0]["df"], s["ex"][0]["up"], s.get("bests", 0))
            for d, s in by_day.items()}
    assert seen == {"2026-09-01": (False, "first", 0, 0), "2026-09-08": (False, "same", 0, 0),
                    "2026-09-15": (True, "+2.5 kg", 1, 1), "2026-09-22": (False, "-5 kg", -1, 0)}


def test_change_is_in_reps_or_seconds_when_there_is_no_weight(root):
    g = build(root, [row("A", "1 Sep 2026", "Pull Up", reps=10), row("A", "1 Sep 2026", "Dead Hang", sec=45),
                     row("B", "8 Sep 2026", "Pull Up", reps=11), row("B", "8 Sep 2026", "Dead Hang", sec=60),
                     row("C", "15 Sep 2026", "Pull Up", reps=14), row("C", "15 Sep 2026", "Dead Hang", sec=50)])
    assert [ex_of(g, d, "Pull Up")["df"] for d in ("2026-09-08", "2026-09-15")] == ["+1 rep", "+3 reps"]
    assert [ex_of(g, d, "Dead Hang")["df"] for d in ("2026-09-08", "2026-09-15")] == ["+15 s", "-10 s"]
    assert ex_of(g, "2026-09-15", "Pull Up")["best"] is True and "best" not in ex_of(g, "2026-09-15", "Dead Hang")


# ---------- the exercise index ----------

def test_exercises_are_listed_by_session_count(root):
    g = gymtab.build_gym(root, TODAY)
    assert [e["n"] for e in g["exercises"]] == ["Pull Up", "Bench Press (Barbell)", "Pull Up (Weighted)",
                                                "Squat (Barbell)"]
    assert g["exercises"][0] == {"n": "Pull Up", "unit": "reps", "count": "2 sessions",
                                 "sub": "2 sessions · last 3 Oct 2026", "best": "14",
                                 "best_sub": "best set · 25 Sep 2026", "last_top": "12", "chart": False,
                                 "cap": "Fewer than 8 sessions: no chart yet."}
    assert g["exercises"][3]["unit"] == "kg" and g["exercises"][3]["best"] == "102.5×3"


def test_an_exercise_gets_a_chart_from_eight_sessions(root):
    g = build(root, [row("W", f"{d} Sep 2026", "Squat (Barbell)", 100 + d, 5) for d in range(1, 9)])
    e = g["exercises"][0]
    assert e["chart"] is True and e["cap"] == "Top set per session (kg)" and e["best_sub"] == "best set · 8 Sep 2026"
    many = build(root, [row("W", f"{d} {m} 2026", "Squat (Barbell)", 100, 5)
                        for m in ("Jun", "Jul", "Aug") for d in range(1, 22)])
    assert many["exercises"][0]["cap"] == "Top set per session (kg) · last 60 sessions"


# ---------- rhythm, calendar, months ----------

def test_rhythm_tiles(root):
    assert gymtab.build_gym(root, TODAY)["rhythm"] == [
        {"k": "Last 4 weeks", "v": "2", "sub": "sessions"}, {"k": "Per week", "v": "0.2", "sub": "12-wk avg"},
        {"k": "Last session", "v": "1", "sub": "day ago"}, {"k": "All time", "v": "2", "sub": "sessions"}]
    last = {t["k"]: (t["v"], t["sub"]) for t in gymtab.build_gym(root, D(2026, 10, 3))["rhythm"]}["Last session"]
    assert last == ("Today", "")
    assert gymtab.build_gym(root, D(2026, 10, 7))["rhythm"][2] == {"k": "Last session", "v": "4", "sub": "days ago"}


def test_calendar_runs_monday_to_sunday_from_the_first_session_to_today(root):
    cal = gymtab.build_gym(root, D(2026, 10, 3))["calendar"]
    assert [w["label"] for w in cal] == ["Sep 2026", "Oct"]
    fri = {"d": "2026-09-25", "lvl": 1, "tip": "Fri 25 Sep 2026 · 2 sets"}
    sat = {"d": "2026-10-03", "lvl": 1, "tip": "Sat 3 Oct 2026 · 5 sets"}
    assert cal[0]["days"] == [0, 0, 0, 0, fri, 0, 0]
    assert cal[1]["days"] == [0, 0, 0, 0, 0, sat, None]                  # Sunday is still ahead


def test_calendar_shade_follows_the_days_working_sets(root):
    def day(n_sets):
        g = build(root, [row("W", "3 Oct 2026", "Pull Up", reps=5) for _ in range(n_sets)])
        return g["calendar"][0]["days"][5]["lvl"]
    assert [day(n) for n in (1, 9, 10, 17, 18, 30)] == [1, 1, 2, 2, 3, 3]


def test_two_workouts_on_one_day_share_a_square_and_january_names_its_year(root):
    g = build(root, [row("Morning", "30 Dec 2026", "Pull Up", reps=5, start="08:00", end="08:30"),
                     row("Evening", "30 Dec 2026", "Pull Up", reps=6, start="18:00", end="18:40")], D(2027, 1, 12))
    assert [s["t"] for s in g["sessions"]] == ["Evening", "Morning"]
    assert [w["label"] for w in g["calendar"]] == ["Jan 2027", "", ""]
    assert g["calendar"][0]["days"][2] == {"d": "2026-12-30", "lvl": 1, "tip": "Wed 30 Dec 2026 · 2 sets"}
    assert g["exercises"][0]["count"] == "2 sessions"


def test_months_and_years_include_the_empty_ones(root):
    g = build(root, [row("A", "30 Dec 2025", "Pull Up", reps=5), row("B", "2 Feb 2026", "Pull Up", reps=5),
                     row("C", "9 Feb 2026", "Pull Up", reps=5)], D(2026, 3, 1))
    assert g["months"] == [{"k": "2025-12", "label": "Dec 2025", "n": 1}, {"k": "2026-01", "label": "Jan 2026", "n": 0},
                           {"k": "2026-02", "label": "Feb 2026", "n": 2}, {"k": "2026-03", "label": "Mar 2026", "n": 0}]
    assert g["month_max"] == 2
    assert g["years"] == [{"y": "2025", "n": 1}, {"y": "2026", "n": 2}]


def test_source_names_the_day_the_file_was_written(root):
    p = root / "data" / "gym.csv"
    stamp = dt.datetime(2026, 10, 4, 8, 27).timestamp()
    os.utime(p, (stamp, stamp))
    assert gymtab.build_gym(root, TODAY)["source"] == "Hevy · pulled 4 Oct"


# ---------- a bad or missing log never stops the page ----------

def test_missing_file_is_unavailable_with_a_reason(tmp_path):
    assert gymtab.build_gym(tmp_path, TODAY) == {
        "available": False, "reason": "data/gym.csv is missing: run hevy/pull_hevy.py"}


@pytest.mark.parametrize("mutate,msg", [
    (lambda t: t.replace('"title",', '"name",', 1), "header"),
    (lambda t: t.rstrip("\n"), "cut off"),
    (lambda t: t.replace(',"normal",100,5,,,8', ',"normal",abc,5,,,8', 1), "weight_kg"),
    (lambda t: t.replace('"25 Sep 2026, 13:44","","Pull Up",,"",0', '"later","","Pull Up",,"",0', 1), "end_time"),
])
def test_malformed_file_is_unavailable_with_a_reason(root, mutate, msg):
    p = root / "data" / "gym.csv"
    p.write_text(mutate(p.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    g = gymtab.build_gym(root, TODAY)
    assert g["available"] is False and msg in g["reason"] and "run hevy/pull_hevy.py again" in g["reason"]


def test_a_log_with_no_workouts_yet_is_unavailable(root):
    assert build(root, [])["reason"] == "data/gym.csv has no workouts yet"
    assert gymtab.build_gym(root, D(2026, 1, 1)) == {"available": False, "reason": "data/gym.csv has no workouts yet"}


def test_medical_text_typed_into_hevy_is_dropped_not_published(root):
    """The page refuses medical text (render.MEDICAL_TOKENS); a Hevy title or note must never stop the build."""
    g = build(root, [row("Medication day 4", "3 Oct 2026", "Pull Up", reps=5, note="post-shot, easy",
                         desc="injection yesterday"),
                     row("Fine", "2 Oct 2026", "Medical ball throw", reps=5, note="Hammer grip")])
    assert render.medical_hits(json.dumps(g, ensure_ascii=False)) == []
    assert [s["t"] for s in g["sessions"]] == ["Workout", "Fine"]
    assert "note" not in g["sessions"][0] and "note" not in g["sessions"][0]["ex"][0]
    assert g["sessions"][1]["ex"][0] == {**g["sessions"][1]["ex"][0], "n": "Exercise", "note": "Hammer grip"}
