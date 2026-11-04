"""Plan v3.5 json: load, validate the day-level templates, resolve dates to weeks and sessions.

Pure functions, no writes. The json keeps its v3.5 keys untouched; Kunto reads the added
`templates` and `warmups` sections and each week's `template` / optional `overrides`.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
KINDS = ("run", "floorball", "gym", "ski", "test", "event", "rest")
SESSION_KEYS = {"kind", "title", "chips", "min", "hard", "optional", "first_to_go", "focus", "warmup", "note"}
FOCI = ("legs", "upper", "full")          # what a gym session trains; Kunto credits it by what Hevy shows was lifted
BOOL_KEYS = ("hard", "optional", "first_to_go")


class PlanError(Exception):
    """The plan json cannot be read or does not validate."""


def load_plan(path: pathlib.Path) -> dict:
    """Read the plan json. Raises PlanError on a missing file or invalid JSON."""
    path = pathlib.Path(path)
    if not path.exists():
        raise PlanError(f"missing plan file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PlanError(f"{path.name}: invalid JSON ({e})") from e


def _session_errors(where: str, s, warmups: dict) -> list[str]:
    if not isinstance(s, dict):
        return [f"{where}: a session must be an object"]
    errs = []
    extra = set(s) - SESSION_KEYS
    if extra:
        errs.append(f"{where}: unknown keys {sorted(extra)}")
    if s.get("kind") not in KINDS:
        errs.append(f"{where}: kind {s.get('kind')!r} is not one of {', '.join(KINDS)}")
    if not isinstance(s.get("title"), str) or not s["title"].strip():
        errs.append(f"{where}: title must be a non-empty string")
    chips = s.get("chips", [])
    if not isinstance(chips, list) or not all(isinstance(c, str) and c for c in chips):
        errs.append(f"{where}: chips must be a list of non-empty strings")
    m = s.get("min")
    if m is not None and (isinstance(m, bool) or not isinstance(m, int) or m <= 0):
        errs.append(f"{where}: min must be a positive integer")
    for k in BOOL_KEYS:
        if k in s and not isinstance(s[k], bool):
            errs.append(f"{where}: {k} must be true or false")
    if "focus" in s and (s.get("kind") != "gym" or s["focus"] not in FOCI):
        errs.append(f"{where}: focus is for gym sessions only and must be one of {', '.join(FOCI)}")
    if "note" in s and not _text(s["note"]):
        errs.append(f"{where}: note must be a non-empty string")
    if "warmup" in s and s["warmup"] not in warmups:
        errs.append(f"{where}: warmup {s['warmup']!r} is not in the warmups section")
    return errs


def _text(x) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _warmup_ok(w) -> bool:
    if not isinstance(w, dict) or not {"min", "steps"} <= set(w) <= {"min", "steps", "ramp"}:
        return False
    m, steps = w["min"], w["steps"]
    return not isinstance(m, bool) and isinstance(m, int) and m > 0 and isinstance(steps, list) and bool(steps) \
        and all(isinstance(x, list) and len(x) == 2 and all(_text(y) for y in x) for x in steps) \
        and ("ramp" not in w or _text(w["ramp"]))


def _warmup_errors(warmups) -> list[str]:
    """Each warm-up: {"min": 8, "steps": [["band pull-apart", "2×15"], ...], "ramp": "~50% ×5 → ~75% ×3"};
    the ramp (the lighter sets before each main lift) is optional."""
    if not isinstance(warmups, dict):
        return ["plan: warmups must map names to warm-ups"]
    return [f"warmup {name}: needs min (a positive integer), steps ([name, amount] pairs) and optionally ramp"
            for name, w in warmups.items() if not _warmup_ok(w)]


def _day_errors(where: str, sessions, warmups: dict) -> list[str]:
    if not isinstance(sessions, list) or not sessions:
        return [f"{where}: must be a non-empty list of sessions"]
    errs = []
    for i, s in enumerate(sessions):
        errs += _session_errors(f"{where}[{i}]", s, warmups)
    kinds = [s.get("kind") for s in sessions if isinstance(s, dict)]
    if "rest" in kinds and len(kinds) > 1:
        errs.append(f"{where}: a rest day holds only the rest session")
    return errs


def validate_plan(plan: dict) -> list[str]:
    """Every problem found, as readable lines. Empty list = valid."""
    errs: list[str] = []
    templates = plan.get("templates")
    weeks = plan.get("weeks")
    if not isinstance(templates, dict) or not templates:
        errs.append("plan: missing the templates section")
        templates = {}
    warmups = plan.get("warmups", {})
    errs += _warmup_errors(warmups)
    if not isinstance(warmups, dict):
        warmups = {}
    if not isinstance(weeks, list) or not weeks:
        return errs + ["plan: missing the weeks list"]
    for name, t in templates.items():
        if not isinstance(t, dict) or set(t) != set(DAYS):
            errs.append(f"template {name}: needs exactly the keys {', '.join(DAYS)}")
            continue
        for d in DAYS:
            errs += _day_errors(f"template {name}.{d}", t[d], warmups)
    prev_start = None
    for i, w in enumerate(weeks):
        n = w.get("week")
        where = f"week {n}"
        if n != i + 1:
            errs.append(f"{where}: weeks must be numbered 1..{len(weeks)} in order")
        try:
            start = dt.date.fromisoformat(w["start"])
            end = dt.date.fromisoformat(w["end"])
        except (KeyError, TypeError, ValueError):
            errs.append(f"{where}: start/end must be YYYY-MM-DD")
            continue
        if start.weekday() != 0 or end != start + dt.timedelta(days=6):
            errs.append(f"{where}: must run Monday {start} to Sunday {start + dt.timedelta(days=6)}")
        if prev_start is not None and start != prev_start + dt.timedelta(days=7):
            errs.append(f"{where}: does not follow the previous week")
        prev_start = start
        tname = w.get("template")
        if tname not in templates:
            errs.append(f"{where}: template {tname!r} is not in the templates section")
        ov = w.get("overrides", {})
        if not isinstance(ov, dict) or not set(ov) <= set(DAYS):
            errs.append(f"{where}: overrides must map day keys ({', '.join(DAYS)}) to session lists")
            continue
        for d, sessions in ov.items():
            errs += _day_errors(f"{where} overrides.{d}", sessions, warmups)
    return errs


def normalize_session(s: dict, warmups: dict | None = None) -> dict:
    """A session with every field present (defaults filled). Its warm-up is the one it names, else a gym
    session's focus warm-up (legs, upper, full), else None: {"min": 8, "steps": [...]}."""
    name = s.get("warmup", s.get("focus"))
    return {"kind": s["kind"], "title": s["title"], "chips": list(s.get("chips", [])),
            "min": s.get("min"), "hard": bool(s.get("hard", False)),
            "optional": bool(s.get("optional", False)), "first_to_go": bool(s.get("first_to_go", False)),
            "focus": s.get("focus"), "warmup": (warmups or {}).get(name) if name else None, "note": s.get("note")}


def season_bounds(plan: dict) -> tuple[dt.date, dt.date]:
    """(Monday of week 1, Sunday of the last week)."""
    return dt.date.fromisoformat(plan["weeks"][0]["start"]), dt.date.fromisoformat(plan["weeks"][-1]["end"])


def week_for_date(plan: dict, day: dt.date) -> dict | None:
    """The plan week holding `day`, or None outside the season."""
    for w in plan["weeks"]:
        if dt.date.fromisoformat(w["start"]) <= day <= dt.date.fromisoformat(w["end"]):
            return w
    return None


def get_week(plan: dict, number: int) -> dict:
    return plan["weeks"][number - 1]


def resolve_week(plan: dict, week: dict) -> list[dict]:
    """Seven day dicts, Mon..Sun: {"date": date, "dow": "mon", "sessions": [normalized...]}.

    A day in the week's overrides replaces the template's day wholesale.
    """
    start = dt.date.fromisoformat(week["start"])
    template = plan["templates"][week["template"]]
    overrides = week.get("overrides", {})
    days = []
    for i, d in enumerate(DAYS):
        raw = overrides.get(d, template[d])
        days.append({"date": start + dt.timedelta(days=i), "dow": d,
                     "sessions": [normalize_session(s, plan.get("warmups")) for s in raw]})
    return days


def sessions_for_date(plan: dict, day: dt.date) -> list[dict]:
    """The normalized sessions planned on `day` ([] outside the season)."""
    w = week_for_date(plan, day)
    if w is None:
        return []
    return resolve_week(plan, w)[day.weekday()]["sessions"]


def current_week_number(plan: dict, today: dt.date) -> int:
    """The week holding today; week 1 before the season, the last week after it."""
    first, last = season_bounds(plan)
    if today < first:
        return 1
    if today > last:
        return len(plan["weeks"])
    return week_for_date(plan, today)["week"]


def run_km_range(text: str) -> tuple[float, float] | None:
    """'10–15' -> (10.0, 15.0); '35' -> (35.0, 35.0); '' -> None. Accepts an en dash or a hyphen."""
    parts = [p.strip() for p in str(text).replace("–", "-").split("-") if p.strip()]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        return nums[0], nums[0]
    if len(nums) == 2:
        return nums[0], nums[1]
    return None


def season_markers(plan: dict) -> list[dict]:
    """One marker per week that holds a test or event session, for the season strips.

    {"week": n, "date": date, "label": label}: the week's first test/event session (its date and title);
    the test week itself is labelled "Test week" and dated its Monday.
    """
    out = []
    for w in plan["weeks"]:
        for d in resolve_week(plan, w):
            hit = next((s for s in d["sessions"] if s["kind"] in ("test", "event")), None)
            if hit:
                if w["block"].strip().lower() == "test week":
                    out.append({"week": w["week"], "date": dt.date.fromisoformat(w["start"]), "label": "Test week"})
                else:
                    out.append({"week": w["week"], "date": d["date"], "label": hit["title"]})
                break
    return out
