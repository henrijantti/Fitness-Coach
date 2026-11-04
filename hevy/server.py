"""server.py: the read-only Hevy MCP server over stdio, for Claude sessions on the athlete's PC.

Registered in .mcp.json (python hevy/server.py). It registers the five tools in hevy/tools.py and
nothing else. Nothing here may print to stdout: stdio carries the protocol.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True          # no __pycache__ in the Drive folder (Google Drive syncs every file)

from mcp.server import MCPServer                  # noqa: E402

from hevy import tools                            # noqa: E402
from hevy.client import HevyClient, HevyError     # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
GYM_CSV = ROOT / "data" / "gym.csv"
INSTRUCTIONS = ("The athlete's Hevy gym log, read-only. Times are Helsinki time. Workouts imported from Motra "
                "(dated on or before 2026-09-20) show clock times 2-3 h late; their dates are right.")

app = MCPServer("hevy", instructions=INSTRUCTIONS)
_client: HevyClient | None = None


def _get_client() -> HevyClient:
    global _client
    if _client is None:
        _client = HevyClient.from_env()
    return _client


def _call(fn, *args) -> str:
    try:
        return fn(_get_client(), *args)
    except HevyError as e:          # a missing key is an answer, not a crash
        return str(e)


@app.tool(structured_output=False)
def list_sessions(start: str = "", end: str = "") -> str:
    """The athlete's gym sessions between two dates (YYYY-MM-DD, Helsinki time), one line each with every
    exercise's top set. Leave both empty for the last 14 days."""
    return _call(tools.list_sessions, start or None, end or None)


@app.tool(structured_output=False)
def session_detail(date: str) -> str:
    """Every set of the athlete's gym session(s) on one date (YYYY-MM-DD): type, kg, reps, seconds, RPE."""
    return _call(tools.session_detail, date)


@app.tool(structured_output=False)
def lift_history(exercise: str, start: str = "", end: str = "") -> str:
    """One lift across sessions, newest first: date, top set and working sets. `exercise` is a Hevy
    exercise name or part of one; several matches come back as a list to choose from. Dates are
    optional, YYYY-MM-DD."""
    return _call(tools.lift_history, exercise, start or None, end or None)


@app.tool(structured_output=False)
def find_exercise(text: str) -> str:
    """Hevy exercise names containing `text`, each marked [used] if it is in the athlete's log, so every
    lift keeps one name (for example, which trap-bar exercise to pick)."""
    return _call(tools.find_exercise, text, GYM_CSV)


@app.tool(structured_output=False)
def next_load(exercise: str = "") -> str:
    """The load for each planned lift's next session, by the plan's section 6 load rule on the athlete's latest
    Hevy sets and RPEs (the same rule as Kunto's gym cards). `exercise` narrows it, e.g. "ohp" or
    "front squat"; leave it empty for every lift planned in the next 4 weeks."""
    return _call(tools.next_load, ROOT, exercise or None)


if __name__ == "__main__":
    app.run()
