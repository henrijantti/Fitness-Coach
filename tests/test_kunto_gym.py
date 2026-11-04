import datetime as dt
import pathlib
import shutil

import pytest

from kunto import data as kdata
from kunto import gym

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "kunto"
D = dt.date
LIFT = {l.key: l for l in gym.LIFTS}


@pytest.fixture
def root(tmp_path):
    shutil.copytree(FIX / "data", tmp_path / "data")
    return tmp_path


@pytest.fixture
def sets(root):
    return gym.load_gym(root)


def test_lifts_are_the_six_plan_lifts_in_order():
    assert [l.key for l in gym.LIFTS] == ["PU", "WPU", "OHP", "Sq", "TB", "Bn"]
    assert LIFT["TB"].exercise == "Deadlift (Trap bar)"
    assert LIFT["WPU"].mode == "added" and LIFT["PU"].mode == "reps" and LIFT["Sq"].mode == "load"


def test_load_reads_every_set_dated_by_start_time(sets):
    assert len(sets) == 11
    s = sets[0]
    assert (s.date, s.exercise, s.set_type, s.weight, s.reps) == (D(2026, 9, 25), "Pull Up", "warmup", None, 6)
    assert sets[6].weight == 102.5 and sets[6].date == D(2026, 10, 3)


def test_missing_file_is_none(tmp_path):
    assert gym.load_gym(tmp_path) is None


@pytest.mark.parametrize("mutate,msg", [
    (lambda t: t.replace('"title",', '"name",', 1), "header"),
    (lambda t: t.replace(',"normal",,14,,,', ',"normal",,14,,', 1), "line 3"),
    (lambda t: t.rstrip("\n"), "cut off"),
    (lambda t: t.replace(',"normal",100,5,,,8', ',"normal",abc,5,,,8', 1), "weight_kg"),
    (lambda t: t.replace('"25 Sep 2026, 12:14","25 Sep 2026, 13:44","","Pull Up",,"",0',
                         '"Sept 25","25 Sep 2026, 13:44","","Pull Up",,"",0', 1), "start_time"),
])
def test_malformed_file_is_a_data_error(root, mutate, msg):
    p = root / "data" / "gym.csv"
    p.write_text(mutate(p.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    with pytest.raises(kdata.DataError, match=msg):
        gym.load_gym(root)


def test_working_sets_drop_warmups_and_dropsets(sets):
    sq = gym.working(sets, LIFT["Sq"], D(2026, 10, 3), D(2026, 10, 3))
    assert [(s.weight, s.reps) for s in sq] == [(100, 5), (102.5, 3)]
    pu = gym.working(sets, LIFT["PU"], D(2026, 9, 1), D(2026, 10, 31))
    assert [s.reps for s in pu] == [14, 12]                   # "failure" counts, "warmup" does not


def test_top_set_is_heaviest_then_most_reps(sets):
    assert gym.fmt_set(gym.top_set(sets, LIFT["Sq"], D(2026, 9, 28), D(2026, 10, 4)), LIFT["Sq"]) == "102.5×3"
    assert gym.fmt_set(gym.top_set(sets, LIFT["WPU"], D(2026, 9, 28), D(2026, 10, 4)), LIFT["WPU"]) == "+20×3"
    assert gym.fmt_set(gym.top_set(sets, LIFT["PU"], D(2026, 9, 1), D(2026, 10, 4)), LIFT["PU"]) == "14"
    assert gym.fmt_set(gym.top_set(sets, LIFT["Bn"], D(2026, 9, 25), D(2026, 9, 25)), LIFT["Bn"]) == "100×5"
    assert gym.top_set(sets, LIFT["TB"], D(2026, 1, 1), D(2026, 12, 31)) is None


def test_top_set_ties_go_to_more_reps_then_earlier_date():
    a = gym.Set(D(2026, 10, 1), "Squat (Barbell)", "normal", 100.0, 3)
    b = gym.Set(D(2026, 10, 2), "Squat (Barbell)", "normal", 100.0, 5)
    c = gym.Set(D(2026, 10, 3), "Squat (Barbell)", "normal", 100.0, 5)
    assert gym.top_set([a, c, b], LIFT["Sq"], D(2026, 10, 1), D(2026, 10, 3)) is b


def test_kg_drops_trailing_zero():
    assert gym.kg(100.0) == "100" and gym.kg(102.5) == "102.5" and gym.kg(0.0) == "0"


# ---------- what a gym day trained (decision-log 2026-10-04) ----------

@pytest.mark.parametrize("exercise,expected", [
    ("Squat (Barbell)", "legs"), ("Front Squat", "legs"), ("Deadlift (Trap bar)", "legs"),
    ("Seated Leg Curl (Machine)", "legs"), ("Leg Press (Machine)", "legs"), ("Leg Press Calf Raise", "legs"),
    ("Standing Calf Raise (Machine)", "legs"), ("Walking Lunge (Dumbbell)", "legs"), ("Sled Push", "legs"),
    ("Overhead Press (Barbell)", "upper"), ("Pull Up (Weighted)", "upper"), ("Lateral Raise (Dumbbell)", "upper"),
    ("Chest Supported Incline Row (Dumbbell)", "upper"), ("Bicep Curl (Dumbbell)", "upper"), ("Dead Hang", "upper"),
    ("Chest Dip", "upper"), ("Butterfly (Pec Deck)", "upper"),
    ("Hanging Leg Raise", None), ("Leg Raise Parallel Bars", None), ("Ab Wheel", None), ("Pallof Press", None),
    ("Suitcase Carry", None), ("Ski Erg", None), ("Copenhagen Plank", None), ("Something New", None),
    ("Test Jump Height (cm)", None), ("test broad jump (cm)", None), ("Box Jump", "legs")])
def test_region_reads_the_hevy_title(exercise, expected):
    assert gym.region(exercise) == expected


def day_of(*counts):
    """Sets for one day: (exercise, working sets) pairs, plus a warm-up squat that must not count."""
    d = D(2026, 10, 3)
    out = [gym.Set(d, "Squat (Barbell)", "warmup", 60.0, 5)]
    for exercise, n in counts:
        out += [gym.Set(d, exercise, "normal", 50.0, 5)] * n
    return out


@pytest.mark.parametrize("counts,expected", [
    ([("Squat (Barbell)", 9), ("Ab Wheel", 4)], "legs"),                              # the Saturday session
    ([("Squat (Barbell)", 6), ("Pull Up", 4)], "legs"),                               # 60 % leg sets
    ([("Overhead Press (Barbell)", 16), ("Romanian Deadlift (Barbell)", 3)], "upper"),  # Sunday, with its RDL
    ([("Pull Up", 3), ("Squat (Barbell)", 1)], "upper"),                              # 25 % leg sets
    ([("Squat (Barbell)", 2), ("Pull Up", 3)], "full"),                               # 40 %: a mixed session
    ([("Ab Wheel", 3), ("Ski Erg", 1)], None),                                        # nothing that counts
])
def test_day_focus_by_the_share_of_leg_sets(counts, expected):
    assert gym.day_focus(day_of(*counts)).get(D(2026, 10, 3)) == expected


def test_day_focus_of_the_fixture_and_its_safe_loader(root, sets):
    assert gym.day_focus(sets) == {D(2026, 9, 25): "upper", D(2026, 10, 3): "full"}
    assert gym.load_day_focus(root, D(2026, 9, 30)) == {D(2026, 9, 25): "upper"}          # cut at today
    (root / "data" / "gym.csv").write_text("bad header\n", encoding="utf-8")
    assert gym.load_day_focus(root, D(2026, 10, 4)) == {}                                   # never an error
    (root / "data" / "gym.csv").unlink()
    assert gym.load_day_focus(root, D(2026, 10, 4)) == {}


# ---------- the weekly athleticism check (decision-log 2026-10-25) ----------

def test_marker_days_read_each_attempt_by_title_ignoring_case_and_spaces():
    m = gym.MARKERS[0]
    sets = [gym.Set(D(2026, 10, 31), "Test Jump Height (cm)", "normal", None, 44),
            gym.Set(D(2026, 10, 31), "test  jump height (cm)", "normal", None, 46),
            gym.Set(D(2026, 10, 31), "Test Jump Height (cm)", "warmup", None, 30),       # a warm-up jump: not a try
            gym.Set(D(2026, 11, 7), "Test Jump Height (cm)", "normal", None, 47),
            gym.Set(D(2026, 11, 7), "Test Broad Jump (cm)", "normal", None, 231)]
    assert gym.marker_days(sets, m, D(2026, 10, 26), D(2026, 11, 8)) == [(D(2026, 10, 31), (44, 46)),
                                                                          (D(2026, 11, 7), (47,))]
    assert gym.marker_days(sets, m, D(2026, 11, 1), D(2026, 11, 8)) == [(D(2026, 11, 7), (47,))]


def test_fmt_marker_gives_the_broad_jump_in_metres():
    cmj, bj, ski = gym.MARKERS
    assert gym.fmt_marker(46, cmj) == "46 cm" and gym.fmt_marker(231, bj) == "2.31 m" and gym.fmt_marker(590, ski) == "590 W"
