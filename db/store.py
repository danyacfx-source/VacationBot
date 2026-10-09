"""Типизированные хранилища поверх SQLite.

Каждый стор инкапсулирует SQL для одной предметной области — коги
работают с объектами, а не с запросами.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .database import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateStore:
    """Ключ-значение с JSON-сериализацией. Замена глобальных dict'ов."""

    def __init__(self, db: Database):
        self._db = db

    async def get(self, key: str, default: Any = None) -> Any:
        row = await self._db.fetchone("SELECT value FROM state_store WHERE key = ?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return default

    async def set(self, key: str, value: Any) -> None:
        await self._db.execute(
            "INSERT INTO state_store (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    async def delete(self, key: str) -> None:
        await self._db.execute("DELETE FROM state_store WHERE key = ?", (key,))

    async def get_str(self, key: str, default: str = "") -> str:
        value = await self.get(key, default)
        return value if isinstance(value, str) else default


class VacationStore:
    """Отпуска: периоды + метаданные панели."""

    def __init__(self, db: Database):
        self._db = db

    async def list_all(self) -> dict[str, dict[str, Any]]:
        rows = await self._db.fetchall(
            "SELECT id, user_id, user_name, start_date, end_date, reason "
            "FROM vacation_periods ORDER BY id"
        )
        result: dict[str, dict[str, Any]] = {}
        for r in rows:
            uid = str(r["user_id"])
            entry = result.setdefault(uid, {"user_name": r["user_name"], "periods": []})
            if r["user_name"]:
                entry["user_name"] = r["user_name"]
            entry["periods"].append(
                {
                    "start_date": r["start_date"],
                    "end_date": r["end_date"],
                    "reason": r["reason"],
                }
            )
        return result

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        all_vacations = await self.list_all()
        return all_vacations.get(str(user_id))

    async def add_period(
        self,
        user_id: int,
        user_name: str,
        start_date: str,
        end_date: str,
        reason: str,
    ) -> None:
        await self._db.execute(
            "INSERT INTO vacation_periods "
            "(user_id, user_name, start_date, end_date, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, user_name, start_date, end_date, reason, _now()),
        )

    async def extend_period(self, user_id: int, target_start: str, new_end: str) -> bool:
        changed = await self._db.execute(
            "UPDATE vacation_periods SET end_date = ? "
            "WHERE user_id = ? AND start_date = ?",
            (new_end, user_id, target_start),
        )
        return changed > 0

    async def remove_user(self, user_id: int) -> int:
        return await self._db.execute(
            "DELETE FROM vacation_periods WHERE user_id = ?", (user_id,)
        )

    async def count_user(self, user_id: int) -> int:
        return int(
            await self._db.scalar(
                "SELECT COUNT(*) FROM vacation_periods WHERE user_id = ?", (user_id,), 0
            )
        )

    # ------------------------------------------------------------ панель

    async def get_panel(self) -> dict[str, int] | None:
        row = await self._db.fetchone(
            "SELECT channel_id, info_message_id, request_message_id "
            "FROM vacation_panels WHERE slot = 1"
        )
        return dict(row) if row else None

    async def set_panel(self, channel_id: int, info_message_id: int, request_message_id: int) -> None:
        await self._db.execute(
            "INSERT INTO vacation_panels (slot, channel_id, info_message_id, request_message_id) "
            "VALUES (1, ?, ?, ?) ON CONFLICT(slot) DO UPDATE SET "
            "channel_id = excluded.channel_id, "
            "info_message_id = excluded.info_message_id, "
            "request_message_id = excluded.request_message_id",
            (channel_id, info_message_id, request_message_id),
        )


class TempChannelStore:
    """Владельцы временных войс-каналов — больше не теряются при рестарте."""

    def __init__(self, db: Database):
        self._db = db

    async def set_owner(self, channel_id: int, owner_id: int) -> None:
        await self._db.execute(
            "INSERT INTO temp_channels (channel_id, owner_id, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(channel_id) DO UPDATE SET owner_id = excluded.owner_id",
            (channel_id, owner_id, _now()),
        )

    async def get_owner(self, channel_id: int) -> int | None:
        row = await self._db.fetchone(
            "SELECT owner_id FROM temp_channels WHERE channel_id = ?", (channel_id,)
        )
        return int(row["owner_id"]) if row else None

    async def remove(self, channel_id: int) -> None:
        await self._db.execute("DELETE FROM temp_channels WHERE channel_id = ?", (channel_id,))

    async def all(self) -> dict[int, int]:
        rows = await self._db.fetchall("SELECT channel_id, owner_id FROM temp_channels")
        return {int(r["channel_id"]): int(r["owner_id"]) for r in rows}

    async def clear(self) -> None:
        await self._db.execute("DELETE FROM temp_channels")


class ReminderStore:
    """Отложенные напоминания: расписание в БД, а не asyncio.sleep."""

    def __init__(self, db: Database):
        self._db = db

    async def add(self, user_id: int, channel_id: int, fire_at: datetime, message: str) -> int:
        await self._db.execute(
            "INSERT INTO reminders (user_id, channel_id, fire_at, message, delivered) "
            "VALUES (?, ?, ?, ?, 0)",
            (user_id, channel_id, fire_at.isoformat(timespec="seconds"), message),
        )
        return int(
            await self._db.scalar("SELECT last_insert_rowid()", default=0) or 0
        )

    async def due(self, now: datetime, limit: int = 20) -> list[dict[str, Any]]:
        return await self._db.fetchall(
            "SELECT id, user_id, channel_id, fire_at, message FROM reminders "
            "WHERE delivered = 0 AND fire_at <= ? ORDER BY fire_at LIMIT ?",
            (now.isoformat(timespec="seconds"), limit),
        )

    async def mark_delivered(self, reminder_id: int) -> None:
        await self._db.execute("UPDATE reminders SET delivered = 1 WHERE id = ?", (reminder_id,))

    async def pending_count(self, user_id: int) -> int:
        return int(
            await self._db.scalar(
                "SELECT COUNT(*) FROM reminders WHERE delivered = 0 AND user_id = ?",
                (user_id,),
                0,
            )
        )


class VoiceOpenStore:
    """Открытые голосовые сессии — продолжаются после рестарта."""

    def __init__(self, db: Database):
        self._db = db

    async def open(self, user_id: int, channel: str) -> None:
        await self._db.execute(
            "INSERT INTO voice_open (user_id, channel, started_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET channel = excluded.channel, "
            "started_at = excluded.started_at",
            (user_id, channel, _now()),
        )

    async def close(self, user_id: int) -> str | None:
        row = await self._db.fetchone(
            "SELECT channel FROM voice_open WHERE user_id = ?", (user_id,)
        )
        if row is None:
            return None
        await self._db.execute("DELETE FROM voice_open WHERE user_id = ?", (user_id,))
        return str(row["channel"])

    async def all_open(self) -> dict[int, tuple[str, str]]:
        rows = await self._db.fetchall("SELECT user_id, channel, started_at FROM voice_open")
        return {int(r["user_id"]): (str(r["channel"]), str(r["started_at"])) for r in rows}


class EventDraftStore:
    """Незавершённые диалоги создания/редактирования ивентов (FSM)."""

    def __init__(self, db: Database):
        self._db = db

    async def get(self, user_id: int) -> tuple[str, dict[str, Any]] | None:
        row = await self._db.fetchone(
            "SELECT flow, payload FROM event_drafts WHERE user_id = ?", (user_id,)
        )
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        return str(row["flow"]), payload

    async def set(self, user_id: int, flow: str, payload: dict[str, Any]) -> None:
        await self._db.execute(
            "INSERT INTO event_drafts (user_id, flow, payload, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET flow = excluded.flow, "
            "payload = excluded.payload, updated_at = excluded.updated_at",
            (user_id, flow, json.dumps(payload, ensure_ascii=False), _now()),
        )

    async def clear(self, user_id: int) -> None:
        await self._db.execute("DELETE FROM event_drafts WHERE user_id = ?", (user_id,))


class MusicStore:
    """Очереди музыки — восстанавливаются после рестарта."""

    def __init__(self, db: Database):
        self._db = db

    async def save(self, guild_id: int, payload: dict[str, Any]) -> None:
        await self._db.execute(
            "INSERT INTO music_state (guild_id, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET payload = excluded.payload, "
            "updated_at = excluded.updated_at",
            (guild_id, json.dumps(payload, ensure_ascii=False), _now()),
        )

    async def load(self, guild_id: int) -> dict[str, Any] | None:
        row = await self._db.fetchone(
            "SELECT payload FROM music_state WHERE guild_id = ?", (guild_id,)
        )
        if row is None:
            return None
        try:
            data = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    async def drop(self, guild_id: int) -> None:
        await self._db.execute("DELETE FROM music_state WHERE guild_id = ?", (guild_id,))
