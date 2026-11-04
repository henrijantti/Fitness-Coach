"""hevy_fake.py: a stand-in for Hevy's API in tests. It has get() and nothing else,
so any attempt to write would fail loudly."""
from __future__ import annotations

import datetime as dt
import json
import pathlib

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "hevy"
BASE = "https://api.hevyapp.com"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status_code: int, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _page(items: list, params: dict, max_size: int, key: str) -> dict:
    size, page = int(params.get("pageSize", 5)), int(params.get("page", 1))
    assert 1 <= size <= max_size, f"pageSize {size} is over Hevy's max {max_size}"
    return {"page": page, "page_count": -(-len(items) // size), key: items[(page - 1) * size: page * size]}


class FakeSession:
    """Serves the four GET endpoints the client uses, from fixture data. `script` holds responses or
    exceptions served first, in order (for retry tests). Every call is recorded in `calls`."""

    def __init__(self, workouts=(), templates=(), history=None, count=None, script=()):
        self.workouts = list(workouts)
        self.templates = list(templates)
        self.history = dict(history or {})
        self.count = len(self.workouts) if count is None else count
        self.script = list(script)
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        path, params = url.removeprefix(BASE), params or {}
        if path == "/v1/workouts/count":
            return FakeResponse(200, {"workout_count": self.count})
        if path == "/v1/workouts":
            return FakeResponse(200, _page(self.workouts, params, 10, "workouts"))
        if path == "/v1/exercise_templates":
            return FakeResponse(200, _page(self.templates, params, 100, "exercise_templates"))
        if path.startswith("/v1/exercise_history/"):
            return FakeResponse(200, {"exercise_history": self.history.get(path.rsplit("/", 1)[1], [])})
        return FakeResponse(404, {"error": "no such endpoint"})

    def paths(self) -> list[str]:
        return [url.removeprefix(BASE) for url, _, _ in self.calls]


def synthetic_workouts(n: int, newest: dt.date = dt.date(2026, 9, 28)) -> list[dict]:
    """n one-set workouts, one a day back from `newest`, at 06:00 UTC (09:00 in Helsinki), newest first."""
    out = []
    for i in range(n):
        day = newest - dt.timedelta(days=i)
        out.append({"id": f"s{i}", "title": f"Session {day}", "description": None,
                    "start_time": f"{day}T06:00:00Z", "end_time": f"{day}T07:00:00Z",
                    "exercises": [{"index": 0, "title": "Squat (Barbell)", "notes": None,
                                   "exercise_template_id": "B0000005", "superset_id": None,
                                   "sets": [{"index": 0, "type": "normal", "weight_kg": 100.0, "reps": 5,
                                             "distance_meters": None, "duration_seconds": None,
                                             "rpe": None, "custom_metric": None}]}]})
    return out
