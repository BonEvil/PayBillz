"""Date-only recurrence rules for PayBillz.

All dates are inclusive. Rules are dictionaries with a ``kind`` key:

* ``{"kind": "once"}``
* ``{"kind": "interval", "unit": "days|weeks|months|years", "every": 1}``
* ``{"kind": "weekdays", "weekdays": [0, 4]}`` (Monday is 0)
* ``{"kind": "monthly_dates", "days": [1, 31]}``
* ``{"kind": "selected_months", "months": [1, 4], "day": 31}``
* ``{"kind": "ordinal_weekday", "weekday": 0, "ordinal": -1}``

Month-end clamps retain the original requested day: January 31 monthly produces
February 28 and then March 31. February 29 annual produces February 28 in
non-leap years and February 29 in leap years. Fifth weekdays occur only when
the month actually has a fifth such weekday. No weekend adjustment is made.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Iterator


def _is_int(value: object) -> bool:
    return type(value) is int


def _int_range(value: object, low: int, high: int, name: str) -> None:
    if not _is_int(value) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} through {high}")


def _int_list(value: object, low: int, high: int, name: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a nonempty list")
    if any(not _is_int(item) or not low <= item <= high for item in value):
        raise ValueError(f"{name} entries must be integers from {low} through {high}")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} must not contain duplicates")


def validate_rule(rule: dict) -> None:
    """Raise ValueError if a rule has unknown, missing, or invalid fields."""
    if not isinstance(rule, dict):
        raise ValueError("rule must be a dictionary")
    kind = rule.get("kind")
    fields = {
        "once": {"kind"},
        "interval": {"kind", "unit", "every"},
        "weekdays": {"kind", "weekdays"},
        "monthly_dates": {"kind", "days"},
        "selected_months": {"kind", "months", "day"},
        "ordinal_weekday": {"kind", "weekday", "ordinal"},
    }
    if not isinstance(kind, str) or kind not in fields:
        raise ValueError("unknown recurrence kind")
    if set(rule) != fields[kind]:
        raise ValueError(f"{kind} requires exactly {sorted(fields[kind])}")
    if kind == "interval":
        if rule["unit"] not in ("days", "weeks", "months", "years"):
            raise ValueError("interval unit must be days, weeks, months, or years")
        if not _is_int(rule["every"]) or rule["every"] <= 0:
            raise ValueError("every must be a positive integer")
    elif kind == "weekdays":
        _int_list(rule["weekdays"], 0, 6, "weekdays")
    elif kind == "monthly_dates":
        _int_list(rule["days"], 1, 31, "days")
    elif kind == "selected_months":
        _int_list(rule["months"], 1, 12, "months")
        _int_range(rule["day"], 1, 31, "day")
    elif kind == "ordinal_weekday":
        _int_range(rule["weekday"], 0, 6, "weekday")
        if not _is_int(rule["ordinal"]) or rule["ordinal"] not in (1, 2, 3, 4, 5, -1):
            raise ValueError("ordinal must be 1 through 5 or -1")


def _check_date(value: date, name: str) -> None:
    if type(value) is not date:
        raise ValueError(f"{name} must be a datetime.date")


def _month_index(day: date) -> int:
    return (day.year - 1) * 12 + day.month - 1


def _clamped(month_index: int, requested_day: int) -> date:
    year, month_zero = divmod(month_index, 12)
    year += 1
    month = month_zero + 1
    return date(year, month, min(requested_day, calendar.monthrange(year, month)[1]))


def _ordinal_day(year: int, month: int, weekday: int, ordinal: int) -> date | None:
    last = calendar.monthrange(year, month)[1]
    if ordinal == -1:
        day = last - (date(year, month, last).weekday() - weekday) % 7
    else:
        day = 1 + (weekday - date(year, month, 1).weekday()) % 7 + 7 * (ordinal - 1)
    return date(year, month, day) if day <= last else None


def _iter_occurrences(anchor: date, rule: dict, start: date, end: date) -> Iterator[date]:
    lower = max(anchor, start)
    if lower > end:
        return
    kind = rule["kind"]
    if kind == "once":
        if lower <= anchor <= end:
            yield anchor
    elif kind == "interval":
        every = rule["every"]
        unit = rule["unit"]
        if unit in ("days", "weeks"):
            step = every * (7 if unit == "weeks" else 1)
            index = max(0, ((lower - anchor).days + step - 1) // step)
            while (end - anchor).days >= index * step:
                yield anchor + timedelta(days=index * step)
                index += 1
        else:
            step = every * (12 if unit == "years" else 1)
            anchor_month = _month_index(anchor)
            index = max(0, (_month_index(lower) - anchor_month) // step)
            while anchor_month + index * step <= _month_index(end):
                candidate = _clamped(anchor_month + index * step, anchor.day)
                if lower <= candidate <= end:
                    yield candidate
                index += 1
    elif kind == "weekdays":
        selected = set(rule["weekdays"])
        day = lower
        while day <= end:
            if day.weekday() in selected:
                yield day
            if day == date.max:
                break
            day += timedelta(days=1)
    else:
        first_month = _month_index(lower)
        last_month = _month_index(end)
        for month_index in range(first_month, last_month + 1):
            year, zero_month = divmod(month_index, 12)
            year += 1
            month = zero_month + 1
            if kind == "monthly_dates":
                candidates = {_clamped(month_index, requested) for requested in rule["days"]}
            elif kind == "selected_months":
                candidates = {_clamped(month_index, rule["day"])} if month in rule["months"] else set()
            else:
                candidate = _ordinal_day(year, month, rule["weekday"], rule["ordinal"])
                candidates = {candidate} if candidate is not None else set()
            for candidate in sorted(candidates):
                if lower <= candidate <= end:
                    yield candidate


def occurrences(anchor: date, rule: dict, start: date, end: date) -> list[date]:
    """Return sorted, unique occurrence dates within [start, end] and on/after anchor."""
    _check_date(anchor, "anchor")
    _check_date(start, "start")
    _check_date(end, "end")
    validate_rule(rule)
    return list(_iter_occurrences(anchor, rule, start, end))


def bucket_bounds(anchor: date, rule: dict, today: date) -> tuple[date | None, date | None]:
    """Return (latest payday on/before today, earliest payday after today).

    A missing payday is ``None``. In particular, the current payday is ``None``
    before the first occurrence, and a one-time schedule has no next payday
    after it occurs. These are schedule boundaries, not bank processing dates.
    """
    _check_date(anchor, "anchor")
    _check_date(today, "today")
    validate_rule(rule)
    current = None
    if today >= anchor:
        for current in _iter_occurrences(anchor, rule, anchor, today):
            pass
    next_payday = None
    if today < date.max:
        tomorrow = today + timedelta(days=1)
        next_payday = next(_iter_occurrences(anchor, rule, tomorrow, date.max), None)
    return current, next_payday
