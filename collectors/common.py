"""Shared helpers for the radar collectors."""
import hashlib
import io
import re
import time

import requests

HEADERS = {"User-Agent": "EDW-Project-Radar/1.0 (public records monitor)"}

_UNITS = re.compile(
    r"\b(\d{2,4})[\s-]*(?:(?:multifamily|multi-family|residential|apartment|senior|age-restricted|market-rate|affordable|rental|independent|living|assisted|dwelling|memory|care)[\s-]+){0,2}"
    r"(?:unit|units|apartment|apartments|dwelling unit|dwelling units|"
    r"residence|residences|bed|beds)\b",
    re.I,
)


def http_get(url, params=None, retries=5, timeout=60):
    """GET with a few retries. Raises the last error if every try fails."""
    last = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # network and HTTP errors are all treated the same
            last = exc
            time.sleep(5 * 2 ** attempt)
    raise last


_ACRES = re.compile(r"\b(\d{1,4}(?:\.\d{1,2})?)\s*(?:\+/-\s*)?acres?\b", re.I)


def extract_acres(text):
    """Largest 'N acres' number in the text, or None."""
    nums = [float(m.group(1)) for m in _ACRES.finditer(text or "")]
    return max(nums) if nums else None


def pdf_text(content, max_pages=3):
    """Text of the first pages of a PDF. Raises if the file cannot be read."""
    import pdfplumber  # imported here so the rest of the repo works without it

    parts = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages[:max_pages]:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def extract_units(text):
    """Largest 'NNN units' style number in the text, or None."""
    nums = [int(m.group(1)) for m in _UNITS.finditer(text or "")]
    return max(nums) if nums else None


def match_keywords(text, include, exclude=()):
    """Keywords from `include` found in text. Empty if any `exclude` word appears."""
    low = (text or "").lower()
    if any(word in low for word in exclude):
        return []
    return [k for k in include if k in low]


def make_id(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def make_item(source, metro, kind, title, detail, when, url, ident, units=None, matched=None, extra=None):
    """One record in the shape every collector returns."""
    item = {
        "id": ident,
        "source": source,
        "metro": metro,
        "kind": kind,
        "title": (title or "").strip()[:300],
        "detail": (detail or "").strip()[:1200],
        "date": when or "",
        "url": url or "",
        "units": units,
        "matched": matched or [],
    }
    for key, value in (extra or {}).items():
        if value not in (None, "", [], {}):
            item[key] = value
    return item
