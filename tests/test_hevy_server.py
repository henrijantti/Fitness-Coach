"""Tests for hevy/server.py: the five tools are registered, a missing key is an answer, and the real
stdio server starts and answers (no network: with an empty key it replies with the missing-key message)."""
import asyncio
import pathlib
import sys

import pytest

pytest.importorskip("mcp.server")

from mcp import ClientSession                                      # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client   # noqa: E402

from hevy import server                                            # noqa: E402
from hevy.client import MISSING_KEY, HevyClient                    # noqa: E402
from hevy_fake import FakeSession, load                            # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ["find_exercise", "lift_history", "list_sessions", "next_load", "session_detail"]


def test_the_five_tools_are_registered_with_descriptions():
    listed = asyncio.run(server.app.list_tools())
    assert sorted(t.name for t in listed) == TOOLS
    assert all(t.description for t in listed)


def test_a_missing_key_is_an_answer(monkeypatch):
    monkeypatch.delenv("HEVY_API_KEY", raising=False)
    monkeypatch.setattr(server, "_client", None)
    assert server.list_sessions() == MISSING_KEY


def test_tools_answer_through_the_client(monkeypatch):
    fake = HevyClient("KEY", session=FakeSession(workouts=load("workouts.json")), sleep=lambda s: None)
    monkeypatch.setattr(server, "_client", fake)
    assert server.session_detail("2026-09-09") == (
        "2026-09-09 Wed 20:30-20:35, 5 min: Wednesday Evening Lat Pull Up Focus with Biceps and Traps\n"
        "  Pull Up: 6 reps; 6 reps; 6 reps")


def test_the_stdio_server_starts_and_answers():
    async def run():
        params = StdioServerParameters(command=sys.executable, args=["hevy/server.py"], cwd=str(ROOT),
                                       env={"HEVY_API_KEY": ""})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                answer = await session.call_tool("list_sessions", {})
                return sorted(t.name for t in listed.tools), answer.content[0].text

    names, text = asyncio.run(asyncio.wait_for(run(), timeout=60))
    assert names == TOOLS
    assert text == MISSING_KEY


def test_every_tool_answers_through_the_client(monkeypatch, tmp_path):
    session = FakeSession(workouts=load("workouts.json"), templates=load("templates.json"),
                          history={"A000000A": load("history_weighted_pullup.json")})
    monkeypatch.setattr(server, "_client", HevyClient("KEY", session=session, sleep=lambda s: None))
    monkeypatch.setattr(server, "GYM_CSV", tmp_path / "missing.csv")
    assert server.list_sessions("2025-01-01", "2025-08-31").startswith(
        "Gym sessions 2025-01-01 to 2025-08-31 (Helsinki time): 2\n- 2025-08-18 Mon 12:15, 22 min")
    assert server.session_detail("2026-09-25").startswith("2026-09-25 Fri 12:14-13:44, 90 min: Morning workout")
    assert server.lift_history("weighted").startswith("Pull Up (Weighted), all history: 2 sessions (Helsinki time)")
    assert server.lift_history("Pull Up (Weighted)", "2026-09-06").startswith(
        "Pull Up (Weighted), 2026-09-06 to today: 1 session (Helsinki time)")
    assert server.find_exercise("trap bar") == (
        "Exercises matching 'trap bar' ([used] = in your log; data/gym.csv not found, so nothing is marked):\n"
        "- Trap Bar Deadlift")
