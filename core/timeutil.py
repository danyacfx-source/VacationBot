"""Работа со временем: единый часовой пояс и форматирование."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import config

try:
    from zoneinfo import ZoneInfo

    _MSK: timezone | ZoneInfo = ZoneInfo(config.SCHEDULE_TZ)
except Exception:
    # На Windows нет IANA-базы, а у Москвы с 2014 года нет перевода
    # часов — фиксированный UTC+3 даёт тот же результат.
    _MSK = timezone(timedelta(hours=3), name="MSK")


def msk_now() -> datetime:
    """Текущие время в часовом поясе бота (МСК)."""
    return datetime.now(_MSK)


def msk_utcnow() -> datetime:
    """Текущий момент в UTC (для отметок в БД)."""
    return datetime.now(timezone.utc)


def to_msk(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(_MSK)
    return dt.astimezone(_MSK)


def msk_stamp(dt: datetime | None = None) -> str:
    """Строка вида «Сегодня, в 14:05» / «03.09.2026, в 14:05»."""
    target = to_msk(dt or msk_now())
    today = msk_now().date()
    prefix = "Сегодня" if target.date() == today else target.strftime("%d.%m.%Y")
    return f"{prefix}, в {target.strftime('%H:%M')}"


def msk_short(dt: datetime | None = None) -> str:
    return to_msk(dt or msk_now()).strftime("%d.%m.%Y %H:%M")


def parse_date(value: str) -> datetime | None:
    """Парсинг ДД.ММ.ГГГГ. Возвращает None вместо исключения."""
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y")
    except (ValueError, AttributeError):
        return None


def parse_duration(value: str) -> timedelta | None:
    """Парсинг длительности: «10м», «1ч», «2ч30м», «3d», «1w2d»."""
    text = (value or "").strip().lower().replace(" ", "")
    if not text:
        return None

    units = {
        "w": 7 * 24 * 60,
        "d": 24 * 60,
        "h": 60,
        "m": 1,
        "s": 0,
        "н": 7 * 24 * 60,
        "д": 24 * 60,
        "ч": 60,
        "м": 1,
        "с": 0,
    }
    digits = ""
    total = 0
    seen = False
    for char in text:
        if char.isdigit():
            digits += char
            continue
        if not digits or char not in units:
            return None
        total += int(digits) * units[char]
        digits = ""
        seen = True
    if digits:
        if not seen:
            return None
        total += int(digits) * units.get("m", 1)
    if total <= 0:
        return None
    return timedelta(minutes=total)


def humanize_delta(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 60:
        return f"{total} сек"
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts: list[str] = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if not parts:
        parts.append(f"{seconds} сек")
    return " ".join(parts)


def at_time(hour: int, minute: int = 0, day: date | None = None) -> datetime:
    base = day or msk_now().date()
    return datetime.combine(base, time(hour=hour, minute=minute), tzinfo=_MSK)


__all__ = [
    "msk_now",
    "msk_utcnow",
    "to_msk",
    "msk_stamp",
    "msk_short",
    "parse_date",
    "parse_duration",
    "humanize_delta",
    "at_time",
]
