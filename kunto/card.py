"""A gym or test session as a card (Oct 21): the plan's chips read as numbered exercise rows grouped
into sections, the warm-up, the session note, the last top set from Hevy under each main lift, and an estimated
time split. Display only: the plan json keeps its chips as written (and as the Sunday close writes them).

A chip reads "name prescription[, note | (note)][ · load]": "strict OHP 4×6–8 first · 47.5 kg",
"standing broad jump, best of 3", "strict OHP: work up to one top set of 5 @ RPE 8". A block chip
("core block, 2 rounds: a · b · c") becomes its own section with lettered rows.
"""
from __future__ import annotations

import datetime as dt
import re

from kunto import fmt
from kunto import gym

# The plan's main lifts (section 6: the trained and tested press, the squat, the hinge, the weighted pull-up)
MAIN = ("strict ohp", "front squat", "back squat", "trap bar", "weighted pull-up", "conventional deadlift",
        "back squat, deadlift")
POWER = ("sprint", "bound", "jump", "throw", "acceleration", "sled", "shuttle")
CONDITIONING = ("skierg",)
# The Hevy exercise behind a main lift, for its last top set (gym.LIFTS uses the same titles)
HEVY = (("strict ohp", "Overhead Press (Barbell)", "load"), ("front squat", "Front Squat", "load"),
        ("back squat", "Squat (Barbell)", "load"), ("trap bar", "Deadlift (Trap bar)", "load"),
        ("weighted pull-up", "Pull Up (Weighted)", "added"), ("conventional deadlift", "Deadlift (Barbell)", "load"),
        ("strict pull-up", "Pull Up", "reps"), ("bench", "Bench Press (Barbell)", "load"))

BLOCK = re.compile(r"^(core|power|station) block\b,?\s*([^:]*):\s*(.+)$", re.I)
LOAD = re.compile(r"^[~+]?\d+(?:\.\d+)?\s*kg\b")
BEST_OF = re.compile(r",?\s*best of (\d+)")
RX = re.compile("|".join((
    r"\d+\s*×\s*[\d.,–]+(?:\s*(?:s|m|′|kg))?(?:\s*/\s*\d+\s*s)?(?:/side|/leg)?"
    r"(?:\s*@\s*(?:RPE\s*[\d.–]+|~?\d+%\s*BW|\d+(?:\.\d+)?\s*kg))?",          # 4×6–8 · 3 × 15 m @ ~50% BW
    r"\d+ sets\b",                                                               # 2 sets, 2 reps short of failure
    r"\d+(?:–\d+)?\s*(?:s|m)?/side",                                             # 20–30 s/side · 10/side
    r"\b\d+–\d+$",                                                               # ab wheel 8–10
    r"\b\d+′ steady\b",                                                           # SkiErg 10′ steady
)))
TOP_SET = re.compile(r"^(?:work up to )?one top set of (\d+)")
LADDER = re.compile(r"^(\d+) sets of ([\d–]+), rising to one top set")
SET_COUNT = re.compile(r"^(\d+)\s*×|^(\d+) sets|best of (\d+)")
MIN_PER_SET = {"Tests": 3, "Main": 3, "Power": 2, "Accessories": 2, "Conditioning": 1}


def _strip(t: str) -> str:
    t = t.strip(" ,;")
    return t[1:-1].strip() if t.startswith("(") and t.endswith(")") else t


def parse_item(text: str) -> dict:
    """One exercise: {"name", "rx", "note", "load", "target"} ("" when absent); target: written as
    "name: target", the way a test states what to hit."""
    load = ""
    head, sep, tail = text.partition(" · ")
    if sep and LOAD.match(tail):
        text, (load, _, extra) = head, tail.partition(", ")
        text += f", {extra}" if extra else ""
    text = re.sub(r"^then\s+", "", text.strip())
    name, colon, rest = text.partition(": ")
    if colon and "(" not in name and not ("," in name and re.search(r"\d", name)):
        rx, note = rest, ""
        m = re.search(r"\s*\(([^)]*)\)$", rx)
        if m:
            rx, note = rx[:m.start()], m.group(1)
        if BEST_OF.match(rx):
            rx, note = f"best of {BEST_OF.match(rx).group(1)}", _strip(rx[BEST_OF.match(rx).end():]) or note
        return {"name": name.strip(), "rx": rx.strip(), "note": note, "load": load, "target": True}
    m = BEST_OF.search(text)
    if m:
        note = re.sub(r"^\(([^)]*)\)", r"\1", _strip(text[m.end():]))      # "(2–3 min rest), same damper"
        return {"name": text[:m.start()].strip(), "rx": f"best of {m.group(1)}", "note": note, "load": load,
                "target": False}
    m = RX.search(text)
    if not m:
        return {"name": text, "rx": "", "note": "", "load": load, "target": False}
    name, note = text[:m.start()].strip(" ,"), _strip(text[m.end():])
    if not name:                                     # "4 × 15 m accelerations": the name follows the sets
        name, note = note, ""
    return {"name": name, "rx": m.group(0).strip(" ,"), "note": note, "load": load, "target": False}


def parse_chip(text: str) -> dict:
    """A chip as {"block": None, "items": [...]} or, for a block chip, {"block": "core", "detail": "2 rounds",
    "items": [...]}. A plain chip holding several exercises split by " · " (no load after the first) gives one
    item each."""
    m = BLOCK.match(text)
    if m:
        kind, detail, body = m.group(1).lower(), m.group(2).strip(" ,"), m.group(3)
        parts = body.split(" · ")
        items = [{"name": p, "rx": "", "note": "", "load": "", "target": False} for p in parts] if kind == "station" \
            else [parse_item(p) for p in parts]
        return {"block": kind, "detail": detail, "items": items}
    parts = text.split(" · ")
    if len(parts) > 1 and not LOAD.match(parts[1]):
        return {"block": None, "items": [parse_item(p) for p in parts]}
    return {"block": None, "items": [parse_item(text)]}


def section_of(item: dict, kind: str) -> str:
    name, rx = item["name"].lower(), item["rx"].lower()
    if kind == "test" and (item["target"] or "top set" in rx or "best of" in rx):
        return "Tests"
    if name.startswith(MAIN):
        return "Main"
    if any(k in name for k in POWER):
        return "Power"
    if any(k in name for k in CONDITIONING):
        return "Conditioning"
    return "Accessories"


def rx_text(rx: str) -> str:
    """'4×6–8' -> '4 × 6–8'; 'work up to one top set of 5 @ RPE 8' -> 'Top set 5 @ RPE 8'."""
    rx = TOP_SET.sub(lambda m: f"top set {m.group(1)}", rx)
    rx = LADDER.sub(lambda m: f"{m.group(1)} × {m.group(2)} → top set", rx)
    rx = re.sub(r"\s*×\s*(?=\d)", " × ", rx)
    return fmt.chip(rx)


def hevy_lift(name: str):
    n = name.lower()
    return next(((title, mode) for key, title, mode in HEVY if n.startswith(key)), None)


def last_top_sets(sets: list[gym.Set] | None, today: dt.date) -> dict[str, gym.Set]:
    """Per Hevy exercise title, the top working set (heaviest, then most reps) of its latest day up to today."""
    latest: dict[str, gym.Set] = {}
    for s in sets or []:
        if s.set_type not in gym.WORKING or not s.reps or s.date > today:
            continue
        cur = latest.get(s.exercise)
        if cur is None or (s.date, s.weight or 0.0, s.reps) > (cur.date, cur.weight or 0.0, cur.reps):
            latest[s.exercise] = s
    return latest


def last_text(s: gym.Set, mode: str) -> dict:
    """{"set": "47.5 kg × 7", "tail": "@ 8 · Sun 18 Oct"}"""
    w = s.weight or 0.0
    done = f"{s.reps} reps" if mode == "reps" else f"+{gym.kg(w)} kg × {s.reps}" if mode == "added" \
        else f"{gym.kg(w)} kg × {s.reps}"
    tail = [f"@ {gym.kg(s.rpe)}" if s.rpe is not None else None, fmt.day_label(s.date)]
    return {"set": done, "tail": " · ".join(t for t in tail if t)}


def _sets(rx: str) -> int:
    if "top set" in rx.lower():
        return 5                                     # the ramp to it plus the set itself
    m = SET_COUNT.search(rx)
    return int(next(g for g in m.groups() if g)) if m else 2


def time_split(sections: list[dict], warmup: dict | None, total: int | None) -> list[dict]:
    """Estimated minutes per part, scaled to the session's planned minutes: warm-up as planned, a block as its
    own minutes ("15′") or ~1.5 min per exercise per round, the rest by sets (3 min a main or test set,
    2 min other sets, 1 min a conditioning interval). [] when the session has no planned minutes."""
    if not total:
        return []
    est: dict[str, float] = {}
    for sec in sections:
        if sec["block"]:
            m = re.search(r"(\d+)′", sec["detail"])
            r = re.search(r"(\d+) rounds?", sec["detail"])
            mins = int(m.group(1)) if m else (int(r.group(1)) if r else 1) * len(sec["rows"]) * 1.5
        else:
            mins = sum(_sets(row["rx_raw"]) * MIN_PER_SET[sec["label"]] for row in sec["rows"])
        est[sec["label"]] = est.get(sec["label"], 0) + mins
    wu = warmup["min"] if warmup else 0
    left, raw = max(total - wu, 0), sum(est.values())
    out = [{"label": "Warm-up", "min": wu, "text": f"Warm-up {wu}′"}] if wu else []
    for label, mins in est.items():
        m = round(mins * left / raw) if raw else 0
        if m:
            out.append({"label": label, "min": m, "text": f"{label} ~{m}′"})
    return out


def next_text(n) -> dict:
    """A progression.Next as the row shows it: {"load": "55 kg", "why": "+2.5 kg: ...", "ease": ""}."""
    return {"load": n.text, "why": n.why, "ease": n.ease}


def build(s: dict, lasts: dict[str, gym.Set] | None = None, nexts: dict | None = None) -> dict | None:
    """The card for a gym session or a session with a warm-up; None for the rest (they keep their chips).
    lasts: last_top_sets(); nexts: progression.upcoming()'s entry for the session's plan day (lift key ->
    Next); both given only for sessions still ahead."""
    if s["kind"] != "gym" and not s.get("warmup"):
        return None
    sections: list[dict] = []
    n = 0
    for chip in s["chips"]:
        parsed = parse_chip(chip)
        if parsed["block"]:
            n += 1
            label = {"core": "Core", "power": "Power", "station": "Stations"}[parsed["block"]]
            rows = [{"n": f"{n}{chr(97 + i)}", "name": fmt.chip(it["name"]), "rx": rx_text(it["rx"]),
                     "rx_raw": it["rx"], "note": fmt.chip(it["note"]) if it["note"] else "", "key": False}
                    for i, it in enumerate(parsed["items"])]
            sections.append({"label": label, "sub": parsed["detail"], "detail": parsed["detail"],
                             "block": parsed["block"], "rows": rows, "mini": True})
            continue
        for it in parsed["items"]:
            n += 1
            label = section_of(it, s["kind"])
            nxt = next((v for k, v in (nexts or {}).items() if it["name"].lower().startswith(k)), None)
            # the plan's chip load stays beside a Next that differs from it, so a disagreement shows
            plan_load = it["load"] if it["load"] and not (nxt and nxt.text == it["load"]) else ""
            row = {"n": str(n), "name": fmt.chip(it["name"]), "rx": rx_text(it["rx"]), "rx_raw": it["rx"],
                   "note": " · ".join(x for x in (fmt.chip(it["note"]) if it["note"] else "",
                                                  f"Plan {plan_load}" if plan_load else "") if x),
                   "key": label in ("Main", "Tests")}
            if nxt and nxt.load is not None:          # no load yet: the chip says how to find it
                row["next"] = next_text(nxt)
            lift = hevy_lift(it["name"]) if row["key"] and lasts else None
            if lift and lift[0] in lasts:
                row["last"] = last_text(lasts[lift[0]], lift[1])
            if sections and not sections[-1]["block"] and sections[-1]["label"] == label:
                sections[-1]["rows"].append(row)
            else:
                sections.append({"label": label, "sub": "", "detail": "", "block": None, "rows": [row],
                                 "mini": False})
    w = s.get("warmup")
    ramp = w.get("ramp") if w else None
    if ramp:
        first = next((x for x in sections if x["label"] in ("Tests", "Main")), None)
        if first:
            first["sub"] = f"ramp: {ramp}"
    time = time_split(sections, w, s.get("min"))
    for sec in sections:
        for row in sec["rows"]:
            del row["rx_raw"]
        del sec["block"], sec["detail"]
    warm = None
    if w:
        warm = {"label": f"Warm-up · {w['min']} min", "min": w["min"],
                "summary": " · ".join(fmt.chip(name) for name, _ in w["steps"]),
                "steps": [{"name": fmt.chip(name), "rx": rx_text(amount)} for name, amount in w["steps"]]}
    return {"note": fmt.chip(s["note"]) if s.get("note") else None, "warmup": warm, "sections": sections,
            "time": time}


def compact(card: dict, limit: int = 2) -> dict:
    """The Overview's short form: the main lifts or tests (else the first rows) and how many rows are left."""
    rows = [r for sec in card["sections"] for r in sec["rows"]]
    lead = [r for r in rows if r["key"]][:limit] or rows[:limit]
    return {"lead": [{"name": r["name"], "rx": r["rx"]} for r in lead], "more": len(rows) - len(lead),
            "warmup": f"warm-up {card['warmup']['min']}′" if card["warmup"] else None}
