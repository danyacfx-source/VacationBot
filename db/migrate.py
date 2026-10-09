"""Перенос данных из старого формата (JSON) в новый.

Запускается один раз при старте, идемпотентно: повторный вызов ничего
не ломает и не дублирует. Возвращает суммарное число перенесённых записей.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Sequence

from .database import Database

log = logging.getLogger(__name__)

Row = Sequence[Any]


def _load_json(filename: str) -> dict[str, Any] | None:
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.error("Не удалось прочитать %s: %s", filename, exc)
        return None


def _retire(filename: str) -> None:
    """Переименовывает исходный JSON после успешного переноса."""
    try:
        target = f"{filename}.bak"
        if os.path.exists(target):
            os.remove(target)
        os.rename(filename, target)
        log.info("Миграция: %s -> %s", filename, target)
    except OSError as exc:
        log.warning("Не удалось переименовать %s: %s", filename, exc)


async def _migrate_simple(
    db: Database,
    filename: str,
    table: str,
    columns: list[str],
    build_rows: Callable[[dict[str, Any]], list[Row]],
) -> int:
    data = _load_json(filename)
    if not data:
        return 0
    rows = build_rows(data)
    if not rows:
        _retire(filename)
        return 0
    await db.insert_replace(table, columns, rows)
    _retire(filename)
    log.info("Миграция: %s -> %s (%d записей)", filename, table, len(rows))
    return len(rows)


async def migrate_vacations(db: Database) -> int:
    """vacations.json -> vacation_periods + vacation_panels."""
    existing = int(await db.scalar("SELECT COUNT(*) FROM vacation_periods", default=0) or 0)
    if existing:
        return 0

    data = _load_json("vacations.json")
    if data is None:
        return 0

    periods: list[Row] = []
    panel: tuple | None = None

    for key, value in data.items():
        if key == "__panel__":
            if isinstance(value, dict):
                panel = (
                    int(value.get("channel_id") or 0),
                    int(value.get("info_message_id") or 0),
                    int(value.get("request_message_id") or 0),
                )
            continue
        if not isinstance(value, dict) or not key.isdigit():
            continue

        user_id = int(key)
        user_name = str(value.get("user_name") or "")
        raw_periods = value.get("periods")

        if not isinstance(raw_periods, list) or not raw_periods:
            # Старый плоский формат: start_date/end_date/reason прямо в записи.
            raw_periods = [
                {
                    "start_date": value.get("start_date", ""),
                    "end_date": value.get("end_date", ""),
                    "reason": value.get("reason", ""),
                }
            ]

        for period in raw_periods:
            if not isinstance(period, dict):
                continue
            periods.append(
                (
                    user_id,
                    user_name,
                    str(period.get("start_date") or ""),
                    str(period.get("end_date") or ""),
                    str(period.get("reason") or ""),
                )
            )

    if periods:
        await db.executemany(
            "INSERT INTO vacation_periods "
            "(user_id, user_name, start_date, end_date, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, '')",
            periods,
        )
        log.info("Миграция: vacations.json -> vacation_periods (%d периодов)", len(periods))

    if panel:
        await db.execute(
            "INSERT INTO vacation_panels "
            "(slot, channel_id, info_message_id, request_message_id) "
            "VALUES (1, ?, ?, ?) ON CONFLICT(slot) DO UPDATE SET "
            "channel_id = excluded.channel_id, "
            "info_message_id = excluded.info_message_id, "
            "request_message_id = excluded.request_message_id",
            panel,
        )
        log.info("Миграция: панель отпусков восстановлена")

    if os.path.exists("vacations.json"):
        _retire("vacations.json")
    return len(periods)


async def _migrate_member_stats(db: Database) -> int:
    data = _load_json("member_stats.json")
    if not data:
        return 0

    stats_rows: list[Row] = []
    session_rows: list[Row] = []
    for uid, stats in data.items():
        if not str(uid).isdigit() or not isinstance(stats, dict):
            continue
        stats_rows.append(
            (
                int(uid),
                int(stats.get("messages", 0)),
                int(stats.get("voice_seconds", 0)),
                int(stats.get("voice_joins", 0)),
            )
        )
        for session in stats.get("voice_sessions", []) or []:
            if not isinstance(session, dict):
                continue
            session_rows.append(
                (
                    int(uid),
                    str(session.get("channel", "")),
                    str(session.get("start", "")),
                    str(session.get("end", "")),
                    int(session.get("seconds", 0)),
                )
            )

    count = 0
    if stats_rows:
        await db.insert_replace(
            "member_stats",
            ["user_id", "messages", "voice_seconds", "voice_joins"],
            stats_rows,
        )
        count += len(stats_rows)
    if session_rows:
        await db.executemany(
            'INSERT INTO voice_sessions (user_id, channel, start, "end", seconds) '
            "VALUES (?, ?, ?, ?, ?)",
            session_rows,
        )
        count += len(session_rows)

    _retire("member_stats.json")
    log.info("Миграция: member_stats.json -> member_stats (%d записей)", count)
    return count


async def _migrate_events(db: Database) -> int:
    data = _load_json("events.json")
    if not data:
        return 0

    event_columns = [
        "id",
        "name",
        "start",
        "briefing",
        "description",
        "host_id",
        "creator_id",
        "going_inf",
        "going_tech",
        "maybe",
        "sl",
        "camera",
        "not_going",
        "show_not_going",
        "required",
        "channel_id",
        "image_url",
        "event_type",
        "location",
    ]
    rows: list[Row] = []
    for event_id, event in data.items():
        if event_id.startswith("_") or not str(event_id).isdigit() or not isinstance(event, dict):
            continue

        going_inf = list(event.get("going_inf") or [])
        for user in event.get("going") or []:
            if user not in going_inf:
                going_inf.append(user)
        start = event.get("start") or (
            f"{event.get('date', '')} {event.get('time', '')}".strip()
        )

        rows.append(
            (
                int(event_id),
                str(event.get("name", "")),
                str(start or ""),
                str(event.get("briefing", "") or ""),
                str(event.get("description", "") or ""),
                int(event.get("host_id", 0) or 0),
                int(event.get("creator_id", 0) or 0),
                json.dumps(going_inf, ensure_ascii=False),
                json.dumps(event.get("going_tech") or [], ensure_ascii=False),
                json.dumps(event.get("maybe") or [], ensure_ascii=False),
                json.dumps(event.get("sl") or [], ensure_ascii=False),
                json.dumps(event.get("camera") or [], ensure_ascii=False),
                json.dumps(event.get("not_going") or [], ensure_ascii=False),
                int(bool(event.get("show_not_going", True))),
                int(event.get("required", 0) or 0),
                int(event.get("channel_id", 0) or 0),
                str(event.get("image_url", "") or ""),
                str(event.get("event_type", "freeform") or "freeform"),
                str(event.get("location", "") or ""),
            )
        )

    count = 0
    if rows:
        count = await db.insert_replace("events", event_columns, rows)

    _retire("events.json")
    log.info("Миграция: events.json -> events (%d записей)", count)
    return count


async def migrate_legacy(db: Database) -> int:
    """Переносит неснятые старые JSON-хранилища. Идемпотентно."""
    total = 0
    total += await migrate_vacations(db)
    total += await _migrate_member_stats(db)
    total += await _migrate_events(db)

    total += await _migrate_simple(
        db,
        "warnings.json",
        "warnings",
        ["user_id", "reason", "moderator_id", "date"],
        lambda data: [
            (int(uid), str(w.get("reason", "")), int(w.get("moderator", 0) or 0), str(w.get("date", "")))
            for uid, warns in data.items()
            if isinstance(warns, list)
            for w in warns
            if isinstance(w, dict)
        ],
    )

    total += await _migrate_simple(
        db,
        "tickets.json",
        "tickets",
        [
            "number",
            "user_id",
            "channel_id",
            "ticket_type",
            "status",
            "created_at",
            "closed_at",
            "closed_by",
            "transcript",
            "guild_id",
        ],
        lambda data: [
            (
                int(num),
                int(t.get("user_id", 0) or 0),
                int(t.get("channel_id", 0) or 0),
                str(t.get("type", "") or t.get("category", "") or ""),
                str(t.get("status", "open") or "open"),
                str(t.get("created_at", "") or ""),
                str(t.get("closed_at", "") or ""),
                int(t.get("closed_by", 0) or 0),
                str(t.get("transcript", "") or ""),
                int(t.get("guild_id", 0) or 0),
            )
            for num, t in data.items()
            if str(num).isdigit() and isinstance(t, dict)
        ],
    )

    total += await _migrate_simple(
        db,
        "birthdays.json",
        "birthdays",
        ["user_id", "date", "notified", "name"],
        lambda data: [
            (
                int(uid),
                str(info.get("date", "") or ""),
                int(bool(info.get("notified", False))),
                str(info.get("name", "") or ""),
            )
            for uid, info in data.items()
            if str(uid).isdigit() and isinstance(info, dict)
        ],
    )

    total += await _migrate_simple(
        db,
        "giveaways.json",
        "giveaways",
        ["message_id", "prize", "host_id", "channel_id", "end_time", "winners_count", "ended"],
        lambda data: [
            (
                int(mid),
                str(info.get("prize", "") or ""),
                int(info.get("host", 0) or 0),
                int(info.get("channel_id", 0) or 0),
                str(info.get("end_time", "") or ""),
                int(info.get("winners_count", 1) or 1),
                int(bool(info.get("ended", False))),
            )
            for mid, info in data.items()
            if str(mid).isdigit() and isinstance(info, dict)
        ],
    )

    total += await _migrate_simple(
        db,
        "afk.json",
        "afk",
        ["user_id", "reason", "since", "display_name"],
        lambda data: [
            (
                int(uid),
                str(info.get("reason", "AFK") or "AFK"),
                str(info.get("since", "") or ""),
                str(info.get("display_name", "") or ""),
            )
            for uid, info in data.items()
            if str(uid).isdigit() and isinstance(info, dict)
        ],
    )

    return total


def import_from_sqlite(dsn: str, sqlite_path: str) -> dict[str, int]:
    """Перенос данных из старого bot_data.db в PostgreSQL (один раз).

    Идемпотентно: переносятся только таблицы с полным совпадением названия,
    которые в PostgreSQL пока пусты. Исходный файл остаётся архивом.
    Возвращает {таблица: перенесено строк}; отрицательное значение — ошибка.
    """
    if not os.path.exists(sqlite_path):
        return {}

    import sqlite3

    import psycopg
    from psycopg.rows import dict_row

    from .database import mask_dsn

    counts: dict[str, int] = {}
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    dst = psycopg.connect(dsn, autocommit=True, connect_timeout=15, row_factory=dict_row)
    try:
        src_tables = {
            row[0]
            for row in src.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        dst_tables = {
            row["tablename"]
            for row in dst.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }

        for table in sorted(src_tables & dst_tables):
            has_data = dst.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone() is not None
            if has_data:
                continue

            src_cols = [row[1] for row in src.execute(f'PRAGMA table_info("{table}")').fetchall()]
            dst_rows = dst.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                (table,),
            ).fetchall()
            dst_cols = [row["column_name"] for row in dst_rows]
            columns = [c for c in dst_cols if c in set(src_cols)]
            if not columns:
                continue

            rows = src.execute(
                f'SELECT {", ".join(chr(34) + c + chr(34) for c in columns)} FROM "{table}"'
            ).fetchall()
            if not rows:
                continue

            query = (
                f'INSERT INTO "{table}" ({", ".join(chr(34) + c + chr(34) for c in columns)}) '
                f"VALUES ({', '.join(['%s'] * len(columns))}) ON CONFLICT DO NOTHING"
            )
            try:
                with dst.transaction():
                    with dst.cursor() as cur:
                        cur.executemany(query, rows)
            except Exception as exc:
                log.error("Перенос %s не удался: %s", table, exc)
                counts[table] = -1
                continue

            counts[table] = len(rows)
            _bump_sequences(dst, table, dst_cols)
            log.info("Перенос SQLite: %s -> %s (%d строк)", sqlite_path, table, len(rows))

        if counts:
            log.info("SQLite: файл %s сохранён как архив", sqlite_path)
    finally:
        src.close()
        dst.close()
    return counts


def _bump_sequences(dst, table: str, columns: list[str]) -> None:
    """Подгоняет identity-последовательности под уже вставленные id."""
    identity = dst.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND is_identity = 'YES'",
        (table,),
    ).fetchall()
    for row in identity:
        column = row["column_name"]
        if column not in columns:
            continue
        peak = dst.execute(
            f'SELECT COALESCE(MAX("{column}"), 0) FROM "{table}"'
        ).fetchone()
        value = int(next(iter(peak.values())) or 0)
        dst.execute(
            "SELECT setval(pg_get_serial_sequence(%s, %s), %s, %s)",
            (table, column, max(value, 1), value > 0),
        )


__all__ = ["migrate_legacy", "migrate_vacations", "import_from_sqlite"]
