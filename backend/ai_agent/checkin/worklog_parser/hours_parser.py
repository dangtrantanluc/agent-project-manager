"""Regex-based hours extraction ported from checkin/parser.py prototype.

Handles Vietnamese time expressions:
  "từ 9h đến bây giờ"  → wall-clock delta (Asia/HCM)
  "9h-11h30"           → range
  "2h rưỡi"            → 2.5
  "1 tiếng 30 phút"    → 1.5
  "45p"                → 0.75

Returns None when no explicit time is found (caller decides how to handle).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional

import pytz

_VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

_RELATIVE_NOW = re.compile(
    r"(?:^|\s)(?:từ|tu)\s*(\d{1,2})(?:(?::|h)(\d{2}))?\s*(?:h|giờ|gio)?\s*"
    r"(sáng|sang|chiều|chieu|tối|toi)?\s*(?:-|–|—|đến|den|tới|toi)\s*"
    r"(?:bây\s*giờ|bay\s*gio|hiện\s*tại|hien\s*tai|bây\s*h|bay\s*h)(?=\s|$)",
    re.IGNORECASE,
)
_RANGE = re.compile(
    r"\b(?:từ\s*)?(\d{1,2})(?:(?::|h)(\d{2}))?\s*(?:h|giờ|gio)?\s*"
    r"(sáng|sang|chiều|chieu|tối|toi)?\s*(?:-|–|—|đến|den|tới|toi)\s*"
    r"(\d{1,2})(?:(?::|h)(\d{2}))?\s*(?:h|giờ|gio)?\s*(sáng|sang|chiều|chieu|tối|toi)?\b",
    re.IGNORECASE,
)


def _norm_period(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )


def _to_minutes(
    hour_raw: str,
    minute_raw: Optional[str],
    period_raw: Optional[str],
) -> Optional[int]:
    try:
        hour = int(hour_raw)
        minute = int(minute_raw) if minute_raw else 0
    except (TypeError, ValueError):
        return None
    period = _norm_period(period_raw or "")
    if period in ("chieu", "toi") and 1 <= hour <= 11:
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _vn_now_minutes() -> int:
    dt = datetime.now(_VN_TZ)
    return dt.hour * 60 + dt.minute


def has_relative_now_range(text: str) -> bool:
    """True if text contains 'từ Xh đến bây giờ' pattern."""
    return bool(_RELATIVE_NOW.search(text or ""))


def _relative_now_range(text: str) -> tuple[Optional[float], bool]:
    """Return (hours, needs_clarification). needs_clarification when start > now."""
    m = _RELATIVE_NOW.search(text or "")
    if not m:
        return None, False
    start = _to_minutes(m.group(1), m.group(2), m.group(3))
    if start is None:
        return None, False
    current = _vn_now_minutes()
    if current < start:
        return None, True
    return (current - start) / 60, False


def _range_hours(text: str) -> Optional[float]:
    m = _RANGE.search(text or "")
    if not m:
        return None
    start = _to_minutes(m.group(1), m.group(2), m.group(3))
    end = _to_minutes(m.group(4), m.group(5), m.group(6))
    if start is None or end is None:
        return None
    if end < start:
        end += 24 * 60
    duration = (end - start) / 60
    return duration if 0 < duration <= 24 else None


def extract_hours(text: str) -> Optional[float]:
    """Extract hours from Vietnamese text. Returns None if no explicit time found."""
    rel, _ = _relative_now_range(text)
    if rel is not None:
        return rel

    rng = _range_hours(text)
    if rng is not None:
        return rng

    if re.search(r"\b(?:nửa|nua)\s*(?:giờ|gio|tiếng|tieng)\b", text, re.IGNORECASE):
        return 0.5

    m = re.search(
        r"(\d+)\s*(?:giờ|gio|tiếng|tieng)\s*(?:rưỡi|ruoi)\b", text, re.IGNORECASE
    )
    if m:
        return int(m.group(1)) + 0.5

    m = re.search(
        r"(\d+)\s*(?:giờ|gio|tiếng|tieng|h)\s*(\d+)\s*(?:phút|phut|p)\b",
        text, re.IGNORECASE,
    )
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60

    m = re.search(r"\b(\d+)\s*h\s*(\d{1,2})\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60

    m = re.search(
        r"(\d+(?:[,.]\d+)?)\s*(?:h|giờ|gio|tiếng|tieng|hours?)\b", text, re.IGNORECASE
    )
    if m:
        return float(m.group(1).replace(",", "."))

    m = re.search(r"(\d+)\s*(?:phút|phut|minutes?|mins?|p)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1)) / 60

    return None
