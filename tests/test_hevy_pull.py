"""Tests for hevy/pull_hevy.py: all or nothing, never a half-written data/gym.csv."""
import pytest

from hevy import pull_hevy
from hevy.client import HevyClient, HevyError
from hevy_fake import FIXTURES, FakeResponse, FakeSession, load


def client_for(session):
    return HevyClient("KEY", session=session, sleep=lambda s: None)


def test_pull_writes_the_export_layout(tmp_path):
    out = tmp_path / "data" / "gym.csv"
    summary = pull_hevy.pull(client_for(FakeSession(workouts=load("workouts.json"))), out)
    assert summary == f"ok: 4 workouts, 36 sets -> {out}"
    expected = (FIXTURES / "export_slice.csv").read_text(encoding="utf-8").splitlines()
    assert out.read_text(encoding="utf-8").splitlines() == expected
    assert not list(out.parent.glob("*.tmp"))


def test_a_count_mismatch_writes_nothing(tmp_path):
    out = tmp_path / "gym.csv"
    out.write_text("old\n", encoding="utf-8")
    with pytest.raises(HevyError) as e:
        pull_hevy.pull(client_for(FakeSession(workouts=load("workouts.json"), count=5)), out)
    assert str(e.value) == "Hevy listed 4 workouts but counts 5; nothing written."
    assert out.read_text(encoding="utf-8") == "old\n"


def test_a_failed_page_writes_nothing(tmp_path):
    out = tmp_path / "gym.csv"
    out.write_text("old\n", encoding="utf-8")
    session = FakeSession(workouts=load("workouts.json"), script=[FakeResponse(500, {}), FakeResponse(502, {})])
    with pytest.raises(HevyError):
        pull_hevy.pull(client_for(session), out)
    assert out.read_text(encoding="utf-8") == "old\n"


def test_main_without_a_key_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HEVY_API_KEY", raising=False)
    out = tmp_path / "gym.csv"
    assert pull_hevy.main(["--out", str(out)]) == 1
    assert "HEVY PULL FAILED: HEVY_API_KEY is not set" in capsys.readouterr().err
    assert not out.exists()


def test_main_writes_data_gym_csv_under_root(tmp_path, monkeypatch, capsys):
    session = FakeSession(workouts=load("workouts.json"))
    monkeypatch.setattr(pull_hevy.HevyClient, "from_env", classmethod(lambda cls, **kw: client_for(session)))
    assert pull_hevy.main(["--root", str(tmp_path)]) == 0
    assert (tmp_path / "data" / "gym.csv").exists()
    assert capsys.readouterr().out.startswith("ok: 4 workouts, 36 sets")


def test_main_reports_any_other_failure_without_a_raw_traceback(tmp_path, monkeypatch, capsys):
    """A count mismatch or a dropped connection raises HevyError; anything else (e.g. a PermissionError
    on the rename because Drive or Excel holds data/gym.csv open) is hard to fake through the client, so
    patch pull_hevy.pull itself."""
    monkeypatch.setattr(pull_hevy.HevyClient, "from_env",
                        classmethod(lambda cls, **kw: client_for(FakeSession())))

    def broken_pull(client, out):
        raise PermissionError("data/gym.csv is locked")

    monkeypatch.setattr(pull_hevy, "pull", broken_pull)
    out = tmp_path / "gym.csv"
    assert pull_hevy.main(["--out", str(out)]) == 1
    assert "HEVY PULL FAILED: PermissionError: data/gym.csv is locked" in capsys.readouterr().err
