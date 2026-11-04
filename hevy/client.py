"""client.py: the only code that talks to Hevy's public API. Read-only by construction:
it sends GET requests and nothing else, so it can never change the athlete's log.

The key comes from the HEVY_API_KEY environment variable (the athlete sets it; agents never do)
and never appears in an error message or an answer.
"""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any, Callable, Iterator

import requests

BASE_URL = "https://api.hevyapp.com"
KEY_VAR = "HEVY_API_KEY"
WORKOUT_PAGE = 10      # Hevy's largest page for /v1/workouts
TEMPLATE_PAGE = 100    # and for /v1/exercise_templates
MISSING_KEY = ("HEVY_API_KEY is not set: create a key at hevy.com/settings?developer, "
               "add it as a Windows user environment variable, then restart the Claude app.")
REJECTED_KEY = "Hevy rejected the key: create a new one at hevy.com/settings?developer."


class HevyError(Exception):
    """A Hevy problem worded for the athlete. Never carries the key."""


def iso_utc(moment: dt.datetime) -> str:
    """An aware datetime as the ISO 8601 UTC stamp Hevy's date filters take."""
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class HevyClient:
    def __init__(self, api_key: str, session: Any = None, timeout: float = 10.0,
                 retry_wait: float = 2.0, sleep: Callable[[float], None] = time.sleep):
        self._key = api_key
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._sleep = sleep
        self._templates: list[dict] | None = None

    @classmethod
    def from_env(cls, environ: dict | None = None, **kwargs) -> "HevyClient":
        env = os.environ if environ is None else environ
        key = (env.get(KEY_VAR) or "").strip()
        if not key:
            raise HevyError(MISSING_KEY)
        return cls(key, **kwargs)

    def _get(self, path: str, params: dict | None = None) -> dict:
        """One GET, retried once after a timeout, a dropped connection, 429 or 5xx."""
        problem = "no answer"
        for attempt in (1, 2):
            try:
                resp = self._session.get(BASE_URL + path, params=params, timeout=self._timeout,
                                         headers={"api-key": self._key, "accept": "application/json"})
            except requests.RequestException:
                problem = "no answer"
            else:
                status = resp.status_code
                if status in (401, 403):
                    raise HevyError(REJECTED_KEY)
                if status == 429 or status >= 500:
                    problem = f"HTTP {status}"
                elif status >= 400:
                    raise HevyError(f"Hevy refused {path} (HTTP {status}).")
                else:
                    try:
                        return resp.json()
                    except ValueError:
                        raise HevyError(f"Hevy sent an unreadable answer for {path}.") from None
            if attempt == 1:
                self._sleep(self._retry_wait)
        raise HevyError(f"Hevy did not answer {path} ({problem}, after one retry).")

    def _pages(self, path: str, key: str, size: int) -> Iterator[list[dict]]:
        page = 1
        while True:
            data = self._get(path, {"page": page, "pageSize": size})
            yield data.get(key) or []
            if page >= int(data.get("page_count") or 0):
                return
            page += 1

    def workout_pages(self) -> Iterator[list[dict]]:
        """Workouts a page at a time, in Hevy's order."""
        return self._pages("/v1/workouts", "workouts", WORKOUT_PAGE)

    def workouts(self) -> list[dict]:
        """Every workout once (a workout saved while paging can shift a page)."""
        seen: set[str] = set()
        out: list[dict] = []
        for batch in self.workout_pages():
            for w in batch:
                if w["id"] not in seen:
                    seen.add(w["id"])
                    out.append(w)
        return out

    def workout_count(self) -> int:
        return int(self._get("/v1/workouts/count")["workout_count"])

    def exercise_templates(self) -> list[dict]:
        """Hevy's exercises plus the athlete's custom ones, fetched once per client."""
        if self._templates is None:
            self._templates = [t for batch in self._pages("/v1/exercise_templates", "exercise_templates",
                                                          TEMPLATE_PAGE) for t in batch]
        return self._templates

    def exercise_history(self, template_id: str, start: dt.datetime | None = None,
                         end: dt.datetime | None = None) -> list[dict]:
        """Every logged set of one exercise, optionally between two instants."""
        params = {}
        if start is not None:
            params["start_date"] = iso_utc(start)
        if end is not None:
            params["end_date"] = iso_utc(end)
        data = self._get(f"/v1/exercise_history/{template_id}", params or None)
        return data.get("exercise_history") or []
