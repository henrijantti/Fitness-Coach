"""Tests for hevy/client.py: read-only by construction, paging, one retry, the key kept out of every message."""
import datetime as dt
import pathlib

import pytest
import requests

from hevy import client as hc
from hevy.client import HevyClient, HevyError
from hevy_fake import FakeResponse, FakeSession, synthetic_workouts

KEY = "SECRET-KEY-123"


def make(session, waits=None):
    return HevyClient(KEY, session=session, sleep=waits.append if waits is not None else (lambda s: None))


def test_from_env_without_a_key_says_how_to_fix_it():
    with pytest.raises(HevyError) as e:
        HevyClient.from_env(environ={})
    assert str(e.value) == hc.MISSING_KEY
    assert "hevy.com/settings?developer" in hc.MISSING_KEY


def test_from_env_reads_and_trims_the_key():
    session = FakeSession(count=3)
    client = HevyClient.from_env(environ={"HEVY_API_KEY": f"  {KEY}  "}, session=session)
    assert client.workout_count() == 3
    assert session.calls[0][2]["api-key"] == KEY


def test_workouts_page_ten_at_a_time_and_drop_repeats():
    workouts = synthetic_workouts(23)
    session = FakeSession(workouts=workouts + [workouts[0]])      # a shifted page repeats a workout
    got = make(session).workouts()
    assert [w["id"] for w in got] == [w["id"] for w in workouts]
    assert [c[1] for c in session.calls] == [{"page": 1, "pageSize": 10}, {"page": 2, "pageSize": 10},
                                             {"page": 3, "pageSize": 10}]


def test_no_workouts_is_one_request():
    session = FakeSession()
    assert make(session).workouts() == []
    assert session.paths() == ["/v1/workouts"]


def test_templates_are_fetched_once_per_client():
    session = FakeSession(templates=[{"id": f"T{i}", "title": f"Ex {i}", "is_custom": False} for i in range(150)])
    client = make(session)
    assert len(client.exercise_templates()) == 150
    assert len(client.exercise_templates()) == 150
    assert session.paths() == ["/v1/exercise_templates", "/v1/exercise_templates"]
    assert session.calls[0][1] == {"page": 1, "pageSize": 100}


def test_exercise_history_sends_utc_dates():
    session = FakeSession(history={"A000000A": [{"workout_id": "h1"}]})
    start = dt.datetime(2026, 9, 6, tzinfo=dt.timezone(dt.timedelta(hours=3)))
    assert make(session).exercise_history("A000000A", start=start) == [{"workout_id": "h1"}]
    assert session.calls[0][1] == {"start_date": "2026-09-05T21:00:00Z"}


def test_a_rejected_key_is_not_retried():
    waits = []
    session = FakeSession(script=[FakeResponse(401, {})])
    with pytest.raises(HevyError) as e:
        make(session, waits).workout_count()
    assert str(e.value) == hc.REJECTED_KEY
    assert waits == [] and len(session.calls) == 1


def test_a_busy_hevy_is_retried_once_after_two_seconds():
    waits = []
    session = FakeSession(count=7, script=[FakeResponse(429, {})])
    assert make(session, waits).workout_count() == 7
    assert waits == [2.0] and len(session.calls) == 2


def test_a_broken_download_is_retried_once():
    waits = []
    session = FakeSession(count=7, script=[requests.exceptions.ChunkedEncodingError("broken")])
    assert make(session, waits).workout_count() == 7
    assert waits == [2.0] and len(session.calls) == 2


def test_two_misses_give_a_clear_error():
    waits = []
    session = FakeSession(script=[requests.Timeout("slow"), requests.ConnectionError("down")])
    with pytest.raises(HevyError) as e:
        make(session, waits).workout_count()
    assert str(e.value) == "Hevy did not answer /v1/workouts/count (no answer, after one retry)."
    assert waits == [2.0]


def test_other_client_errors_are_refusals():
    with pytest.raises(HevyError) as e:
        make(FakeSession(script=[FakeResponse(404, {})])).exercise_history("NOPE")
    assert str(e.value) == "Hevy refused /v1/exercise_history/NOPE (HTTP 404)."


def test_an_unreadable_answer():
    with pytest.raises(HevyError) as e:
        make(FakeSession(script=[FakeResponse(200, ValueError("not json"))])).workout_count()
    assert str(e.value) == "Hevy sent an unreadable answer for /v1/workouts/count."


def test_the_key_never_appears_in_an_error():
    scripts = [[FakeResponse(401, {})], [FakeResponse(500, {}), FakeResponse(503, {})], [FakeResponse(404, {})],
               [FakeResponse(200, ValueError(KEY))], [requests.Timeout(KEY), requests.Timeout(KEY)]]
    for script in scripts:
        with pytest.raises(HevyError) as e:
            make(FakeSession(script=script)).workout_count()
        assert KEY not in str(e.value)


def test_the_client_can_only_read():
    """Read-only is a constraint on all of hevy/, not just client.py."""
    hevy_dir = pathlib.Path(hc.__file__).resolve().parent
    for path in sorted(hevy_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for verb in (".post(", ".put(", ".patch(", ".delete(", ".request("):
            assert verb not in source, f"{path.name} contains {verb!r}"
    assert not any(hasattr(HevyClient, name) for name in ("post", "put", "patch", "delete"))
