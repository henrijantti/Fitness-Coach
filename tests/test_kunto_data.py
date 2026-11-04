import datetime as dt
import pathlib
import re
import shutil

import pytest

from kunto import data as kdata

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "kunto"


@pytest.fixture
def root(tmp_path):
    shutil.copytree(FIX / "data", tmp_path / "data")
    return tmp_path


def test_load_garmin_fixture(root):
    g = kdata.load_garmin(root)
    assert len(g.daily) == 10
    day = g.daily[dt.date(2026, 10, 7)]
    assert day["rhr"] == 53.0 and day["readiness"] == 58.0 and day["readiness_level"] == "MODERATE"
    assert day["hrv_weekly"] is None                        # empty cell = None, never 0
    assert g.daily[dt.date(2026, 10, 6)]["sleep_h"] is None
    assert [a["activity_id"] for a in g.activities][:2] == ["1001", "1002"]
    first = g.activities[0]
    assert first["date"] == dt.date(2026, 9, 28) and first["start"] == dt.datetime(2026, 9, 28, 7, 30)
    assert first["km"] == 3.0 and first["cadence"] == 166.0 and first["type"] == "running"
    assert g.activities[2]["cadence"] is None
    assert [r["vo2max"] for r in g.fitness] == [54.1, 54.4]
    assert g.csv_mtime is not None and g.csv_mtime.tzinfo is not None


def test_fitness_csv_is_optional(root):
    (root / "data" / "garmin-fitness.csv").unlink()
    assert kdata.load_garmin(root).fitness == []


@pytest.mark.parametrize("name", ["garmin-daily.csv", "garmin-activities.csv"])
def test_missing_required_csv(root, name):
    (root / "data" / name).unlink()
    with pytest.raises(kdata.DataError, match="missing input"):
        kdata.load_garmin(root)


def test_bad_number_names_file_line_and_column(root):
    p = root / "data" / "garmin-daily.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace("2026-09-28,50,", "2026-09-28,fifty,")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(kdata.DataError, match=r"garmin-daily.csv line 3: rhr='fifty' is not a number"):
        kdata.load_garmin(root)


def test_bad_date_and_missing_column(root):
    p = root / "data" / "garmin-activities.csv"
    text = p.read_text(encoding="utf-8")
    p.write_text(text.replace("2026-10-03,2026-10-03 10:00:00", "03.10.2026,2026-10-03 10:00:00"), encoding="utf-8")
    with pytest.raises(kdata.DataError, match="is not YYYY-MM-DD"):
        kdata.load_garmin(root)
    p.write_text(text.replace(",cadence,", ",cad,"), encoding="utf-8")
    with pytest.raises(kdata.DataError, match=r"missing columns \['cadence'\]"):
        kdata.load_garmin(root)


@pytest.mark.parametrize("name,cut,msg", [
    # An interrupted pull can leave a partial last row: its missing cells must not load as blanks
    # (the daily row below used to load as hrv_night 2.0, with sleep and readiness None).
    ("garmin-daily.csv", "2026-10-07,53,2", "garmin-daily.csv line 12: expected 26 fields, found 3"),
    ("garmin-activities.csv", "2026-10-06,2026-10-06 19:30:00,running,Floorb",
     "garmin-activities.csv line 11: expected 14 fields, found 4"),
    ("garmin-fitness.csv", "2026-10-05,54.4,2026-10-03,19:0", "garmin-fitness.csv line 4: expected 8 fields, found 4"),
])
def test_short_row_is_an_error(root, name, cut, msg):
    p = root / "data" / name
    lines = p.read_text(encoding="utf-8").splitlines()
    lines[-1] = cut
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(kdata.DataError, match=re.escape(msg)):
        kdata.load_garmin(root)


def test_extra_cell_is_an_error(root):
    p = root / "data" / "garmin-daily.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    lines[2] += ",999"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(kdata.DataError, match=re.escape("garmin-daily.csv line 3: expected 26 fields, found 27")):
        kdata.load_garmin(root)


def test_cut_inside_the_last_field_is_an_error(root):
    # "...,MODERATE,3" still has 26 fields (acute_load 300 read as 3): only the missing line ending shows the cut.
    p = root / "data" / "garmin-daily.csv"
    text = p.read_text(encoding="utf-8")
    assert text.endswith(",MODERATE,300\n")
    p.write_text(text[:-len("00\n")], encoding="utf-8")
    with pytest.raises(kdata.DataError, match=re.escape("garmin-daily.csv line 12: no line ending")):
        kdata.load_garmin(root)


def test_repeated_daily_date_is_an_error(root):
    p = root / "data" / "garmin-daily.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    lines.append(lines[-1].replace("2026-10-07,53,", "2026-10-07,60,"))       # used to win silently
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(kdata.DataError, match=re.escape("garmin-daily.csv: date 2026-10-07 is on two rows")):
        kdata.load_garmin(root)


def test_real_csvs_load():
    g = kdata.load_garmin(pathlib.Path(__file__).resolve().parents[1])
    assert g.daily and g.activities


def test_as_of_drops_later_rows(root):
    g = kdata.as_of(kdata.load_garmin(root), dt.date(2026, 10, 2))
    assert max(g.daily) == dt.date(2026, 10, 2)
    assert max(a["date"] for a in g.activities) == dt.date(2026, 10, 2)
    assert [r["date"] for r in g.fitness] == [dt.date(2026, 9, 28)]
