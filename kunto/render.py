"""Inject the view model into kunto/template.html as one JSON blob, safe inside a <script> element."""
from __future__ import annotations

import json
import pathlib

PLACEHOLDER = "__KUNTO_DATA__"
EM_DASH = "\u2014"
# No medical text on the page. A generic default list; a real deployment adds its own terms in
# kunto/private-terms.txt (gitignored, one lower-case term per line), so the terms themselves stay private.
DEFAULT_TOKENS = ("medical", "medication", "prescription", "diagnosis", "injection", "post-shot")
PRIVATE_TERMS = pathlib.Path(__file__).resolve().with_name("private-terms.txt")


def _private_terms() -> tuple[str, ...]:
    try:
        lines = PRIVATE_TERMS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    return tuple(t.strip().lower() for t in lines if t.strip() and not t.startswith("#"))


MEDICAL_TOKENS = DEFAULT_TOKENS + _private_terms()


class TemplateError(Exception):
    """The template does not hold exactly one data placeholder."""


class MedicalTextError(TemplateError):
    """The rendered page would carry medical text."""


def medical_hits(text: str) -> list[str]:
    """The MEDICAL_TOKENS found in text (case-insensitive); [] = clean."""
    low = text.lower()
    return [t for t in MEDICAL_TOKENS if t in low]


def scrub_dashes(obj):
    """Every string in obj with the em dash replaced by a hyphen (house rule: no em dashes on the page)."""
    if isinstance(obj, str):
        return obj.replace(EM_DASH, "-")
    if isinstance(obj, list):
        return [scrub_dashes(x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub_dashes(v) for k, v in obj.items()}
    return obj


def to_script_json(model: dict) -> str:
    r"""JSON that cannot end its <script> element: <, > and & become \u003c-style escapes, as do
    U+2028/U+2029. NaN/Infinity raise ValueError (allow_nan=False), so the page never receives them."""
    text = json.dumps(scrub_dashes(model), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return (text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render(template: str, model: dict) -> str:
    """The page: template with its single placeholder replaced by the model's JSON.
    Raises MedicalTextError if the result carries medical text (fix the plan json; never publish it)."""
    if template.count(PLACEHOLDER) != 1:
        raise TemplateError(f"template must contain {PLACEHOLDER} exactly once")
    page = template.replace(PLACEHOLDER, to_script_json(model))
    hits = medical_hits(page)
    if hits:
        raise MedicalTextError(f"medical text on the page ({', '.join(hits)}); remove it from the plan json")
    return page
