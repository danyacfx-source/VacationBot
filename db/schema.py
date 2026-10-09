"""Схема БД и миграции.

Старые таблицы сохраняют исходную структуру — существующий bot_data.db
подхватывается без потери данных. Новые таблицы добавляются сюда.
"""

from __future__ import annotations

import logging

from .database import Database

log = logging.getLogger(__name__)

SCHEMA = """
-- статистика и голосовые сессии
CREATE TABLE IF NOT EXISTS member_stats (
    user_id INTEGER PRIMARY KEY,
    messages INTEGER DEFAULT 0,
    voice_seconds INTEGER DEFAULT 0,
    voice_joins INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS voice_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel TEXT,
    start TEXT,
    end TEXT,
    seconds INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_voice_sessions_user ON voice_sessions(user_id);

-- открытые голосовые сессии (переживают рестарт)
CREATE TABLE IF NOT EXISTS voice_open (
    user_id INTEGER PRIMARY KEY,
    channel TEXT,
    started_at TEXT
);

-- модерация
CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    reason TEXT DEFAULT 'Не указана',
    moderator_id INTEGER,
    date TEXT
);

CREATE INDEX IF NOT EXISTS idx_warnings_user ON warnings(user_id);

CREATE TABLE IF NOT EXISTS afk (
    user_id INTEGER PRIMARY KEY,
    reason TEXT DEFAULT 'AFK',
    since TEXT,
    display_name TEXT
);

CREATE TABLE IF NOT EXISTS giveaways (
    message_id INTEGER PRIMARY KEY,
    prize TEXT,
    host_id INTEGER,
    channel_id INTEGER,
    end_time TEXT,
    winners_count INTEGER DEFAULT 1,
    ended INTEGER DEFAULT 0
);

-- тикеты
CREATE TABLE IF NOT EXISTS tickets (
    number INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    channel_id INTEGER,
    ticket_type TEXT DEFAULT '',
    status TEXT DEFAULT 'open',
    created_at TEXT,
    closed_at TEXT,
    closed_by INTEGER,
    transcript TEXT DEFAULT '',
    guild_id INTEGER DEFAULT 0,
    approved_by INTEGER DEFAULT 0,
    approved_at TEXT DEFAULT '',
    rejected_by INTEGER DEFAULT 0,
    rejected_at TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

-- ивенты
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT,
    time TEXT,
    description TEXT DEFAULT '',
    host_id INTEGER,
    going_inf TEXT DEFAULT '[]',
    going_tech TEXT DEFAULT '[]',
    going TEXT DEFAULT '[]',
    sl TEXT DEFAULT '[]',
    start TEXT,
    briefing TEXT,
    maybe TEXT DEFAULT '[]',
    camera TEXT DEFAULT '[]',
    not_going TEXT DEFAULT '[]',
    show_not_going INTEGER DEFAULT 0,
    required INTEGER DEFAULT 0,
    channel_id INTEGER DEFAULT 0,
    creator_id INTEGER DEFAULT 0,
    image_url TEXT DEFAULT '',
    event_type TEXT DEFAULT 'freeform',
    location TEXT DEFAULT '',
    reminded_briefing_minus15 INTEGER DEFAULT 0,
    reminded_briefing INTEGER DEFAULT 0,
    reminded_start_minus15 INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS birthdays (
    user_id INTEGER PRIMARY KEY,
    date TEXT,
    notified INTEGER DEFAULT 0,
    name TEXT DEFAULT ''
);

-- отпуска: периоды строками, панель отдельно
CREATE TABLE IF NOT EXISTS vacation_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_name TEXT DEFAULT '',
    start_date TEXT DEFAULT '',
    end_date TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_vacation_periods_user ON vacation_periods(user_id);

CREATE TABLE IF NOT EXISTS vacation_panels (
    slot INTEGER PRIMARY KEY CHECK (slot = 1),
    channel_id INTEGER DEFAULT 0,
    info_message_id INTEGER DEFAULT 0,
    request_message_id INTEGER DEFAULT 0
);

-- персистентное состояние
CREATE TABLE IF NOT EXISTS state_store (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- единый планировщик
CREATE TABLE IF NOT EXISTS scheduler_state (
    job TEXT PRIMARY KEY,
    last_run TEXT
);

-- напоминания (переживают рестарт)
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER DEFAULT 0,
    fire_at TEXT NOT NULL,
    message TEXT DEFAULT '',
    delivered INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(delivered, fire_at);

-- владельцы временных войс-каналов
CREATE TABLE IF NOT EXISTS temp_channels (
    channel_id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    created_at TEXT DEFAULT ''
);

-- незавершённые диалоги создания ивентов (FSM)
CREATE TABLE IF NOT EXISTS event_drafts (
    user_id INTEGER PRIMARY KEY,
    flow TEXT DEFAULT '',
    payload TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT ''
);

-- музыкальные очереди
CREATE TABLE IF NOT EXISTS music_state (
    guild_id INTEGER PRIMARY KEY,
    payload TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT ''
);
"""

# Колонки, появившиеся в старых версиях: добавляем, если таблица уже существует.
EVENT_COLUMNS: list[tuple[str, str]] = [
    ("start", "TEXT"),
    ("briefing", "TEXT"),
    ("maybe", "TEXT DEFAULT '[]'"),
    ("camera", "TEXT DEFAULT '[]'"),
    ("not_going", "TEXT DEFAULT '[]'"),
    ("show_not_going", "INTEGER DEFAULT 0"),
    ("required", "INTEGER DEFAULT 0"),
    ("channel_id", "INTEGER DEFAULT 0"),
    ("creator_id", "INTEGER DEFAULT 0"),
    ("image_url", "TEXT DEFAULT ''"),
    ("event_type", "TEXT DEFAULT 'freeform'"),
    ("location", "TEXT DEFAULT ''"),
    ("reminded_briefing_minus15", "INTEGER DEFAULT 0"),
    ("reminded_briefing", "INTEGER DEFAULT 0"),
    ("reminded_start_minus15", "INTEGER DEFAULT 0"),
]

TICKET_COLUMNS: list[tuple[str, str]] = [
    ("ticket_type", "TEXT DEFAULT ''"),
    ("guild_id", "INTEGER DEFAULT 0"),
    ("approved_by", "INTEGER DEFAULT 0"),
    ("approved_at", "TEXT DEFAULT ''"),
    ("rejected_by", "INTEGER DEFAULT 0"),
    ("rejected_at", "TEXT DEFAULT ''"),
]

BIRTHDAY_COLUMNS: list[tuple[str, str]] = [
    ("name", "TEXT DEFAULT ''"),
]


async def init_schema(db: Database) -> None:
    await db.executescript(SCHEMA)
    await _ensure_columns(db, "events", EVENT_COLUMNS)
    await _ensure_columns(db, "tickets", TICKET_COLUMNS)
    await _ensure_columns(db, "birthdays", BIRTHDAY_COLUMNS)
    log.info("Схема БД готова")


async def _ensure_columns(db: Database, table: str, columns: list[tuple[str, str]]) -> None:
    existing = await db.fetchall(f"PRAGMA table_info({table})")
    names = {c["name"] for c in existing}
    for name, ddl in columns:
        if name not in names:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                log.info("Схема: добавлена колонка %s.%s", table, name)
            except Exception as exc:
                log.error("Не удалось добавить %s.%s: %s", table, name, exc)
