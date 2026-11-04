"""Display strings for the Kunto page. Every user-visible number is formatted here, so the page
never has to format (and never prints NaN or undefined). No em dashes: ranges use an en dash."""
from __future__ import annotations

import datetime as dt

MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def short_date(d: dt.date) -> str:
    """28 Sep"""
    return f"{d.day} {MON[d.month - 1]}"


def day_label(d: dt.date) -> str:
    """Mon 28 Sep"""
    return f"{DOW[d.weekday()]} {short_date(d)}"


def dated(d: dt.date) -> str:
    """28 Sep 2026"""
    return f"{short_date(d)} {d.year}"


def day_dated(d: dt.date) -> str:
    """Mon 28 Sep 2026"""
    return f"{day_label(d)} {d.year}"


def range_label(a: dt.date, b: dt.date) -> str:
    """13–19 Sep 2027 · 28 Sep – 4 Oct 2026 · 28 Dec 2026 – 3 Jan 2027"""
    if a.year != b.year:
        return f"{short_date(a)} {a.year} – {short_date(b)} {b.year}"
    if a.month != b.month:
        return f"{short_date(a)} – {short_date(b)} {b.year}"
    return f"{a.day}–{b.day} {MON[b.month - 1]} {b.year}"


def num(v, nd: int = 0) -> str | None:
    """54.0 -> '54'; 54.12 (nd=1) -> '54.1'; 23298 -> '23,298'; None -> None."""
    if v is None:
        return None
    return f"{v:,.{nd}f}"


def signed(v, nd: int = 1) -> str:
    """+0.7 · -1.0 (ASCII hyphen-minus) · +0.0"""
    return f"{v:+.{nd}f}"


def minutes_label(m) -> str | None:
    """42.4 -> '42 min'; 84.1 -> '1 h 24 min'; 60 -> '1 h'; None -> None."""
    if m is None:
        return None
    total = int(round(m))
    h, mm = divmod(total, 60)
    if h and mm:
        return f"{h} h {mm} min"
    return f"{h} h" if h else f"{mm} min"


def plan_minutes(m) -> str | None:
    """A planned duration as the plan writes it: 70 -> '70 min'; None -> None."""
    return None if m is None else f"{m} min"


def hours_label(h) -> str | None:
    """7.22 -> '7 h 13 min'"""
    return None if h is None else minutes_label(h * 60)


def hours_compact(h) -> str | None:
    """7.25 -> '7h15' (the mock's tile style); None -> None."""
    if h is None:
        return None
    total = int(round(h * 60))
    return f"{total // 60}h{total % 60:02d}"


def humanize_enum(s: str | None) -> str | None:
    """'PRODUCTIVE_9' -> 'Productive'; 'AEROBIC_LOW_SHORTAGE' -> 'Aerobic low shortage'."""
    if not s:
        return None
    words = [w for w in s.split("_") if not w.isdigit()]
    text = " ".join(words).lower()
    return text[:1].upper() + text[1:] if text else None


def activity_title(unit_or_row: dict, cls: str) -> str:
    """Run 5.07 km · Strength · Floorball · Cross country skiing"""
    t = unit_or_row.get("type") or ""
    if cls == "run":
        km = unit_or_row.get("km")
        return f"Run {km:.2f} km" if km else "Run"
    if cls == "gym":
        return "Strength"
    if cls == "floorball":
        return "Floorball"
    return humanize_enum(t.upper()) or "Activity"


def chip(text: str) -> str:
    """A plan chip as the page shows it, each ' · ' part capitalised: 'strict OHP 4×6–8 · ab wheel 8–10'
    -> 'Strict OHP 4×6–8 · Ab wheel 8–10'. "RPE 8" never breaks across lines. The plan json keeps its own casing."""
    return " · ".join(p[:1].upper() + p[1:] for p in text.split(" · ")).replace("RPE ", "RPE\u00a0")


def chips(items) -> list[str]:
    return [chip(c) for c in items]

