"""progression.py: the next load for a lift by plan section 6's load rule, from the Hevy log (Oct 25, 2026).

One rule for three readers: coach_brief.py's Sunday ledger, the Kunto gym cards ("Next" under each lift's last
top set) and the hevy MCP's next_load. Read-only: nothing here writes the plan json or Hevy.

Section 6: main lifts, every set at the top of the rep range at RPE 9 or under -> +2.5 kg next session (trap bar
+5 kg) and back to the bottom of the range; a missed rep or a set over RPE 9 -> repeat the load. Accessories: the
same load until every set reaches the top of the range at RPE <= 8, then the next step. A deload week keeps the
loads (section 1: sets -40 % at the same loads). An ease-off sign sends the next hard session to RPE <= 7.
Where the plan is silent the code takes a reading, marked "Reading:" in a comment; the athlete can change it.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import re

from kunto import card, fmt, gym
from kunto import plan as kplan

MAIN = ("strict ohp", "front squat", "back squat", "trap bar", "weighted pull-up", "conventional deadlift")
STEP = {"trap bar": 5.0}                 # section 6: +2.5 kg next session, trap bar +5 kg
DEFAULT_STEP = 2.5
RPE_MAX = 9.0                            # section 6: a set over RPE 9 repeats the load
ACC_RPE_MAX = 8.0                        # section 6: accessories step up at the top of the range at RPE ≤8
EASE_RPE = 7                             # section 6: the next hard session after an ease-off sign
# The Hevy exercise behind an accessory chip (the chip's name starts with the key). Reading: only accessories
# with a bar, dumbbell, cable or machine load; body-weight work moves by reps and gets no load.
ACCESSORY = (("chest-supported db row", "Chest Supported Incline Row (Dumbbell)"), ("face pull", "Face Pull"),
             ("db bench", "Bench Press (Dumbbell)"), ("incline db press", "Incline Bench Press (Dumbbell)"),
             ("seated leg curl", "Seated Leg Curl (Machine)"), ("db lateral raise", "Lateral Raise (Dumbbell)"),
             ("db curl", "Bicep Curl (Dumbbell)"), ("rope pushdown", "Triceps Rope Pushdown"))
MAX_USED_STEP = 5.0                      # Reading: an accessory's next step is a weight already used, if this close
SCHEME = re.compile(r"(\d+)\s*×\s*(\d+)(?:–(\d+))?")
CAP = re.compile(r"RPE\s*≤\s*(\d+(?:\.\d+)?)")
KG = re.compile(r"[~+]?(\d+(?:\.\d+)?)\s*kg")
SIGN_DAYS = 2                            # an ease-off sign counts while it is this many days old or newer
OK_HRV = ("BALANCED",)
NO_HRV = (None, "NONE")                  # no status yet (Garmin is still learning the baseline)


@dataclasses.dataclass(frozen=True)
class Rx:
    """One planned prescription of a lift: '4×6–8' gives sets 4, lo 6, hi 8; a test chip ('work up to one
    top set of 5') gives test=True and lo = hi = 5."""
    day: dt.date
    sets: int | None
    lo: int | None
    hi: int | None
    test: bool
    load: str                            # a load written on the chip (' · 47.5 kg'), else ""
    cap: float | None                    # a whole-session cap from its note ('RPE ≤7 all session')
    text: str                            # the prescription as written, for the printout


@dataclasses.dataclass(frozen=True)
class Done:
    """One Hevy day of a lift: its working sets at that day's top load (lighter sets are ramp or back-off)."""
    day: dt.date
    load: float
    reps: tuple
    rpe: tuple


@dataclasses.dataclass(frozen=True)
class Next:
    """The load for one lift's next planned session. load None: nothing to set it from yet."""
    key: str                             # the chip name's start: a MAIN key or an ACCESSORY key
    day: dt.date                         # the plan day of that session
    rx: str                              # its prescription as written
    load: float | None
    mode: str                            # "load" (bar kg) or "added" (kg on body weight)
    code: str                            # "up" | "hold" | "repeat" | "confirm" | "deload" | "start" | "none"
    why: str                             # the rule's reason, short
    basis: str                           # the session it reads, "52.5 kg × 5,5,5,5 @ 7–8 · Sun 1 Nov", or ""
    ease: str = ""                       # "RPE ≤7: resting HR climbing 3 days" when an ease-off sign is live
    alt: float | None = None             # code "confirm": the load if every set was at or under the RPE gate

    @property
    def text(self) -> str:
        """'55 kg', '+10 kg', '47.5 kg (50 if every set was ≤9)', or '' with no load."""
        if self.load is None:
            return ""
        t = load_text(self.load, self.mode)
        return f"{t} ({load_text(self.alt, self.mode).lstrip('+')} if every set was ≤{_gate(self.key)})" \
            if self.alt is not None else t


def kg(x: float) -> str:
    return gym.kg(x)


def load_text(load: float, mode: str) -> str:
    return f"+{kg(load)} kg" if mode == "added" else f"{kg(load)} kg"


def rpe_text(rpe: tuple) -> str:
    vals = sorted(r for r in rpe if r is not None)
    if not vals:
        return "RPE –"
    return f"@ {kg(vals[0])}" if vals[0] == vals[-1] else f"@ {kg(vals[0])}–{kg(vals[-1])}"


def _gate(key: str) -> str:
    return kg(RPE_MAX if key in MAIN else ACC_RPE_MAX)


def label(key: str) -> str:
    """'strict ohp' -> 'Strict OHP', 'chest-supported db row' -> 'Chest-supported DB row'."""
    t = re.sub(r"\b(ohp|db|rdl)\b", lambda m: m.group(1).upper(), key)
    return t[:1].upper() + t[1:]


def hevy_title(key: str) -> tuple[str, str] | None:
    """(Hevy title, mode) of a MAIN or ACCESSORY key."""
    if key in MAIN:
        return card.hevy_lift(key)
    return next(((title, "load") for k, title in ACCESSORY if k == key), None)


def lift_key(name: str) -> str | None:
    """The MAIN or ACCESSORY key a chip item's name starts with, else None."""
    n = name.lower()
    return next((k for k in MAIN if n.startswith(k)), None) or next((k for k, _ in ACCESSORY if n.startswith(k)), None)


def _rx_from_item(it: dict, day: dt.date, note: str | None) -> Rx:
    cap = CAP.search(note or "")
    cap = float(cap.group(1)) if cap else None
    top = card.TOP_SET.search(it["rx"])
    if top or it["target"]:
        reps = int(top.group(1)) if top else None
        return Rx(day, 1, reps, reps, True, it["load"], cap, it["rx"])
    m = SCHEME.search(it["rx"])
    if not m:
        return Rx(day, None, None, None, False, it["load"], cap, it["rx"])
    lo = int(m.group(2))
    return Rx(day, int(m.group(1)), lo, int(m.group(3) or lo), False, it["load"], cap, it["rx"])


def planned(plan: dict, key: str, start: dt.date, end: dt.date) -> list[Rx]:
    """Every prescription of the lift in the plan's gym and test sessions from start to end, by date."""
    out = []
    d = start
    while d <= end:
        for s in kplan.sessions_for_date(plan, d):
            if s["kind"] not in ("gym", "test"):
                continue
            for chip in s["chips"]:
                for it in card.parse_chip(chip)["items"]:
                    if it["name"].lower().startswith(key):
                        out.append(_rx_from_item(it, d, s["note"]))
        d += dt.timedelta(days=1)
    return out


def rx_for(plan: dict, key: str, day: dt.date) -> Rx | None:
    """The prescription a Hevy day of the lift answered: that day's own, else the nearest one in the same
    plan week (a swapped Saturday and Sunday still read against their plan)."""
    week = kplan.week_for_date(plan, day)
    if week is None:
        return None
    rxs = planned(plan, key, dt.date.fromisoformat(week["start"]), dt.date.fromisoformat(week["end"]))
    return min(rxs, key=lambda r: (abs((r.day - day).days), r.day), default=None)


def sessions(sets: list[gym.Set], title: str, start: dt.date, end: dt.date) -> list[Done]:
    """The Hevy days of one exercise from start to end, oldest first."""
    by_day: dict[dt.date, list[gym.Set]] = {}
    for s in sets:
        if s.exercise == title and s.set_type in gym.WORKING and s.reps and start <= s.date <= end:
            by_day.setdefault(s.date, []).append(s)
    out = []
    for d in sorted(by_day):
        top = max(s.weight or 0.0 for s in by_day[d])
        work = [s for s in by_day[d] if (s.weight or 0.0) == top]
        out.append(Done(d, top, tuple(s.reps for s in work), tuple(s.rpe for s in work)))
    return out


def verdict(done: Done, rx: Rx | None, key: str) -> tuple[str, str]:
    """The section 6 load rule on one session: ("up" | "hold" | "repeat" | "confirm" | "test" | "none", why)."""
    if rx is None or rx.lo is None:
        return "none", "no prescription in the plan that week"
    if rx.test:
        return "test", "a test top set: the review sets the next loads"
    gate = RPE_MAX if key in MAIN else ACC_RPE_MAX
    if key in MAIN and any(r is not None and r > gate for r in done.rpe):
        return "repeat", "a set over RPE 9"
    if key in MAIN and any(r < rx.lo for r in done.reps):
        return "repeat", "missed reps"
    # The rule reads the sets done: a trimmed session still moves (45 × 9, 8, 8 of 4×6–8 passed it, decision-log
    # 2026-10-12); the shortfall is shown, never hidden
    short = f" ({len(done.reps)} of {rx.sets} sets)" if rx.sets and len(done.reps) < rx.sets else ""
    step = f"+{kg(STEP.get(key, DEFAULT_STEP))} kg" if key in MAIN else "the next step"
    if all(r >= rx.hi for r in done.reps):
        if any(r is not None and r > gate for r in done.rpe):
            return "hold", f"every set at the top, but over RPE {kg(gate)}{short}"
        if any(r is None for r in done.rpe):
            return "confirm", f"every set at the top, RPE not logged on all: {step} if all were ≤{kg(gate)}{short}"
        return "up", f"every set at the top at RPE ≤{kg(gate)}: {step}{short}"
    return "hold", f"build reps toward {rx.hi}{short}"


def next_load(last: Done, code: str, key: str, used: list[float] | None = None) -> float:
    """The load after `last` under its verdict code. An accessory steps to the lightest weight above it that
    `used` (every weight logged for it) holds within MAX_USED_STEP, else +2.5 kg (Reading)."""
    if code != "up":
        return last.load
    if key in MAIN:
        return last.load + STEP.get(key, DEFAULT_STEP)
    above = sorted(w for w in (used or []) if last.load < w <= last.load + MAX_USED_STEP)
    return above[0] if above else last.load + DEFAULT_STEP


def is_deload(plan: dict, day: dt.date) -> bool:
    w = kplan.week_for_date(plan, day)
    return bool(w and "deload" in w.get("flags", []))


def chip_kg(load: str) -> float | None:
    """'52.5 kg' -> 52.5, '+7.5 kg' -> 7.5, '24 kg each' -> 24, '' -> None."""
    m = KG.search(load or "")
    return float(m.group(1)) if m else None


def done_text(d: Done, mode: str) -> str:
    """'52.5 kg × 5,5,5,5 @ 7–8 · Sun 1 Nov'"""
    reps = ",".join(str(r) for r in d.reps)
    return f"{load_text(d.load, mode)} × {reps} {rpe_text(d.rpe)} · {fmt.day_label(d.day)}"


def suggest(plan: dict, sets: list[gym.Set], key: str, day: dt.date, ease: str = "",
            due: dt.date | None = None) -> Next | None:
    """The load for the lift's session planned on `day` (and due on `due`, a swapped session's new day), from
    the Hevy days before it is due; None when the plan has no prescription of it that day, or it is a test (a
    test works up to its own top set)."""
    rx = next((r for r in planned(plan, key, day, day)), None)
    lift = hevy_title(key)
    if rx is None or rx.test or lift is None:
        return None
    title, mode = lift
    season = dt.date.fromisoformat(plan["weeks"][0]["start"])
    hist = sessions(sets, title, season, (due or day) - dt.timedelta(days=1))
    # A deload-week session neither raises nor lowers the load (section 1: the same loads)
    rated = [(d, rx_for(plan, key, d.day)) for d in hist if not is_deload(plan, d.day)]
    base = dict(key=key, day=day, rx=rx.text, mode=mode, ease=ease)
    if not rated or (rated[-1][1] and rated[-1][1].test):
        # Nothing trained since a test (or at all): the plan's chip load is the start (decision-log 2026-10-25:
        # about 10 % under the Oct 24 top sets). Reading: the newest chip load since the test, up to this day; with
        # no test, only this day's own chip (an older chip's load was written for sessions that have passed).
        since = rated[-1][0].day + dt.timedelta(days=1) if rated else day
        chips = [r for r in planned(plan, key, since, day) if not r.test and chip_kg(r.load) is not None]
        test = done_text(rated[-1][0], mode) if rated else ""
        if chips:
            why = "the plan's start after the test" if rated else "the plan's start"
            return Next(**base, load=chip_kg(chips[-1].load), code="start", why=why, basis=test)
        why = "after the test, the review sets the load" if rated else "no session yet: find the load"
        return Next(**base, load=None, code="none", why=why, basis=test)
    last, lrx = rated[-1]
    code, why = verdict(last, lrx, key)
    basis = done_text(last, mode)
    if is_deload(plan, day):
        return Next(**base, load=last.load, code="deload", why="deload week: the same load, fewer sets", basis=basis)
    used = [s.weight for s in sets if s.exercise == title and s.weight] if key not in MAIN else None
    load = next_load(last, code, key, used)
    alt = next_load(last, "up", key, used) if code == "confirm" else None
    short = {"up": f"+{kg(load - last.load)} kg: every set at the top at RPE ≤{_gate(key)}",
             "confirm": "every set at the top, RPE missing on some",
             "none": "same load: no plan for that session"}.get(code, f"same load: {why}")
    return Next(**base, load=load, code=code, why=short, basis=basis, alt=alt)


def rises(series: list[tuple[dt.date, float]]) -> list[tuple[dt.date, dt.date]]:
    """Runs of resting HR "climbing 3 days running", as (first, last) day of the climb.
    Reading: three days in a row, each higher than the day before (four consecutive readings rising)."""
    out, run = [], 0
    for (d0, v0), (d1, v1) in zip(series, series[1:]):
        run = run + 1 if (d1 - d0).days == 1 and v1 > v0 else 0
        if run >= 3:
            first = d1 - dt.timedelta(days=run - 1)
            out = [o for o in out if o[0] != first] + [(first, d1)]
    return out


def ease_signs(daily: dict, today: dt.date) -> list[str]:
    """Section 6's data signs that are live today: a resting HR climb or an HRV status off Balanced within the
    last SIGN_DAYS days (the third sign, the body saying so, is the athlete's). Reading: the coach_brief window."""
    days = [today - dt.timedelta(days=i) for i in range(SIGN_DAYS + 3, -1, -1)]
    rhr = [(d, daily[d]["rhr"]) for d in days if d in daily and daily[d].get("rhr") is not None]
    out = []
    if any(b >= today - dt.timedelta(days=SIGN_DAYS) for _, b in rises(rhr)):
        out.append("resting HR climbing 3 days")
    recent = [daily[d].get("hrv_status") for d in days[-(SIGN_DAYS + 1):] if d in daily]
    if any(s not in OK_HRV and s not in NO_HRV for s in recent):
        out.append("HRV status off Balanced")
    return out


def next_hard_gym_day(plan: dict, start: dt.date, horizon: int = 14) -> dt.date | None:
    """The first day from start with a required hard gym session. Reading: section 6's "next hard session goes
    easy (lifts at RPE ≤7)" is the next lifting one; floorball is not eased, and an optional extra is skipped on a
    sign anyway."""
    for i in range(horizon):
        d = start + dt.timedelta(days=i)
        if any(s["kind"] == "gym" and s["hard"] and not s["optional"] for s in kplan.sessions_for_date(plan, d)):
            return d
    return None


def upcoming(plan: dict, sets: list[gym.Set] | None, today: dt.date, daily: dict | None = None,
             horizon: int = 28, swapped: dict[dt.date, dt.date] | None = None) -> dict[dt.date, dict[str, Next]]:
    """Each lift's next planned session from today on, by plan day then key: one Next per lift, on the first
    plan day after the one its last Hevy day answered (a session done on a swapped day still counts for its
    plan day). swapped: the plan days of earlier sessions still pending, swapped to today or later (plan day ->
    due day, from matching.plan_week_status), scanned first. {} without a gym log."""
    if sets is None:
        return {}
    signs = ease_signs(daily or {}, today)
    trained_today = any(s.date == today for s in sets)        # today's session already took the easy day
    hard = next_hard_gym_day(plan, today + dt.timedelta(days=trained_today)) if signs else None
    swapped = {p: due for p, due in (swapped or {}).items() if p < today <= due}
    days: dict[str, dt.date] = {}
    for d in sorted(swapped) + [today + dt.timedelta(days=i) for i in range(horizon)]:
        for s in kplan.sessions_for_date(plan, d):
            if s["kind"] != "gym" or (d < today and s["optional"]):
                continue
            for chip in s["chips"]:
                for it in card.parse_chip(chip)["items"]:
                    k = lift_key(it["name"])
                    if k and k not in days:
                        days[k] = d
    out: dict[dt.date, dict[str, Next]] = {}
    season = dt.date.fromisoformat(plan["weeks"][0]["start"])
    for k, d in days.items():
        title = hevy_title(k)[0]
        hist = sessions(sets, title, season, today)
        if hist:                          # its plan session already done (today, or on a swapped day)
            answered = rx_for(plan, k, hist[-1].day)
            if answered and answered.day >= d:
                ahead = planned(plan, k, answered.day + dt.timedelta(days=1), today + dt.timedelta(days=horizon))
                later = [r for r in ahead if not r.test]
                if not later:
                    continue
                d = later[0].day
        due = swapped.get(d, d)
        ease = f"RPE ≤{EASE_RPE}: {' and '.join(signs)}" if hard == due else ""
        n = suggest(plan, sets, k, d, ease, due)
        if n:
            out.setdefault(d, {})[k] = n
    return out
