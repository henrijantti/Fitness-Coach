import json
import pathlib
import re
import shutil

import pytest

from kunto import build_kunto

REPO = pathlib.Path(__file__).resolve().parents[1]
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "kunto"
DATA_RE = re.compile(r'<script id="kunto-data" type="application/json">(.*?)</script>', re.S)


@pytest.fixture
def root(tmp_path):
    shutil.copytree(FIX / "data", tmp_path / "data")
    shutil.copy(REPO / "training-plan-2026-27.json", tmp_path / "training-plan-2026-27.json")
    return tmp_path


def run(root, *extra):
    return build_kunto.main(["--root", str(root), *extra])


def test_fixture_build_writes_a_page_whose_json_parses(root, capsys):
    out = root / "out" / "page.html"
    assert run(root, "--today", "2026-10-07", "--out", str(out)) == 0
    page = out.read_text(encoding="utf-8")
    model = json.loads(DATA_RE.search(page).group(1))
    assert model["meta"]["today"] == "2026-10-07"
    assert model["overview"]["header"]["line"] == "Week 2 of 51 · 1 Athletic base"
    assert model["training"]["current_week"] == 2
    assert model["training"]["weeks"][0]["summary_text"] == "4/5 required · 1/3 optional · 15.0 of 10–15 km"
    assert "—" not in page and "NaN" not in DATA_RE.search(page).group(1)     # the page's own script tests isNaN
    assert not list(out.parent.glob("*.tmp"))
    assert "wrote" in capsys.readouterr().out


def test_default_output_is_kunto_index_html(root):
    assert run(root, "--today", "2026-10-07") == 0
    assert (root / "kunto" / "index.html").exists()


def test_check_writes_nothing(root, capsys):
    out = root / "page.html"
    assert run(root, "--today", "2026-10-07", "--check", "--out", str(out)) == 0
    assert not out.exists() and not (root / "kunto").exists()
    assert capsys.readouterr().out.startswith("OK (check only, nothing written)")


def test_input_error_exits_1_and_keeps_the_last_good_page(root, capsys):
    out = root / "page.html"
    out.write_text("last good page", encoding="utf-8")
    (root / "data" / "garmin-activities.csv").unlink()
    assert run(root, "--today", "2026-10-07", "--out", str(out)) == 1
    assert out.read_text(encoding="utf-8") == "last good page"
    assert "ERROR missing input" in capsys.readouterr().out


def test_invalid_plan_exits_1(root, capsys):
    p = root / "training-plan-2026-27.json"
    plan = json.loads(p.read_text(encoding="utf-8"))
    plan["weeks"][4]["template"] = "nope"
    p.write_text(json.dumps(plan), encoding="utf-8")
    assert run(root, "--today", "2026-10-07", "--check") == 1
    assert "week 5: template 'nope'" in capsys.readouterr().out


def test_bad_today_exits_1(root):
    assert run(root, "--today", "07.10.2026", "--check") == 1


def test_medical_text_in_the_plan_exits_1(root, capsys):
    p = root / "training-plan-2026-27.json"
    plan = json.loads(p.read_text(encoding="utf-8"))
    plan["templates"]["re-entry"]["mon"][0]["chips"] = ["Medication day 4: keep it easy"]
    p.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    assert run(root, "--today", "2026-10-07", "--check") == 1
    assert "ERROR medical text on the page (medication)" in capsys.readouterr().out


def test_write_error_exits_1_and_leaves_no_temp_file(root, capsys):
    out = root / "busy"
    out.mkdir()                                          # a folder where the page should go: the rename fails
    assert run(root, "--today", "2026-10-07", "--out", str(out)) == 1
    assert "ERROR could not write" in capsys.readouterr().out
    assert not list(root.glob("*.tmp"))


def test_index_html_is_gitignored():
    assert "kunto/index.html" in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_python_and_pytest_write_no_caches_into_the_drive_folder():
    """The live checkout sits in Google Drive, which syncs every file: the entry scripts and the tests
    switch bytecode caching off, and pytest runs without its cache folder."""
    for script in ("kunto/build_kunto.py", "hevy/pull_hevy.py", "hevy/server.py",
                   "tests/conftest.py"):
        assert "sys.dont_write_bytecode = True" in (REPO / script).read_text(encoding="utf-8"), script
    assert "addopts = -p no:cacheprovider" in (REPO / "pytest.ini").read_text(encoding="utf-8")


def test_a_leftover_temp_page_is_gitignored():
    # write_atomic cleans up its .tmp on any exception, but a killed build leaves it behind with full
    # health data: git must never pick it up
    import subprocess
    r = subprocess.run(["git", "check-ignore", "-q", "kunto/index.html.tmp"], cwd=REPO)
    assert r.returncode == 0


def test_the_gym_log_rides_on_the_page(root):
    out = root / "page.html"
    assert run(root, "--today", "2026-10-07", "--out", str(out)) == 0
    gym = json.loads(DATA_RE.search(out.read_text(encoding="utf-8")).group(1))["gym"]
    assert gym["available"] is True and [s["d"] for s in gym["sessions"]] == ["2026-10-03", "2026-09-25"]


@pytest.mark.parametrize("breakage", ["bad header", "missing"])
def test_a_broken_gym_csv_never_breaks_the_page(root, capsys, breakage):
    """A bad Hevy pull cannot stop the daily refresh: the Gym tab is empty with its reason, the rest builds."""
    p = root / "data" / "gym.csv"
    if breakage == "missing":
        p.unlink()
    else:
        p.write_text("bad header\n", encoding="utf-8")
    out = root / "page.html"
    assert run(root, "--today", "2026-10-07", "--out", str(out)) == 0
    model = json.loads(DATA_RE.search(out.read_text(encoding="utf-8")).group(1))
    assert set(model) == {"meta", "overview", "training", "gym"}
    assert model["gym"]["available"] is False and "hevy/pull_hevy.py" in model["gym"]["reason"]
    assert model["training"]["current_week"] == 2
    printed = capsys.readouterr().out.splitlines()
    assert printed[0].startswith("wrote") and printed[1].startswith("WARN Gym tab is empty: ")


def test_gym_ticks_follow_what_hevy_shows_was_lifted(root):
    """Sat Oct 3 is planned Legs. With an upper-only Hevy session that day, the page credits Sunday's Upper
    to Saturday and the Legs stays undone (decision-log 2026-10-04)."""
    from hevy import rows as hrows
    sets = [["Upper", "3 Oct 2026, 10:00", "3 Oct 2026, 11:00", "", "Pull Up (Weighted)", None, "", i, "normal",
             15, 5, None, None, None] for i in range(3)]
    (root / "data" / "gym.csv").write_text(hrows.to_csv(sets), encoding="utf-8", newline="\n")
    out = root / "page.html"
    assert run(root, "--today", "2026-10-07", "--out", str(out)) == 0
    week1 = json.loads(DATA_RE.search(out.read_text(encoding="utf-8")).group(1))["training"]["weeks"][0]
    gym = {d["label"]: (s["status_label"], s["detail"]) for d in week1["days"] for s in d["sessions"]
           if s["kind"] == "gym" and not s["optional"]}
    assert gym == {"Sat 3 Oct": ("✗ Missed", None), "Sun 4 Oct": ("Moved to Sat", "58 min · avg HR 101 · Hevy: upper body")}
    assert week1["summary_text"].startswith("4/5 required")


def test_medical_text_typed_into_hevy_never_breaks_the_page(root):
    p = root / "data" / "gym.csv"
    p.write_text(p.read_text(encoding="utf-8").replace('"Legs"', '"Medication day 4"'), encoding="utf-8", newline="\n")
    out = root / "page.html"
    assert run(root, "--today", "2026-10-07", "--out", str(out)) == 0
    assert "Medication" not in out.read_text(encoding="utf-8")


def test_a_demo_build_is_a_frozen_snapshot(root):
    out = root / "page.html"
    assert run(root, "--today", "2026-10-07", "--demo", "--out", str(out)) == 0
    model = json.loads(DATA_RE.search(out.read_text(encoding="utf-8")).group(1))
    assert model["meta"]["demo"] is True
    assert model["overview"]["fresh"]["label"].startswith("Sample data · ")
