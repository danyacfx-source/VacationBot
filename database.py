import sqlite3
import json
import os
import threading
import logging

DB_FILE = "bot_data.db"
_local = threading.local()


def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_FILE, check_same_thread=False, isolation_level=None)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn


_EVENTS_EXTRA_COLUMNS = [
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


def _ensure_events_columns(conn):
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(events)").fetchall()}
        for name, ddl in _EVENTS_EXTRA_COLUMNS:
            if name not in cols:
                conn.execute(f"ALTER TABLE events ADD COLUMN {name} {ddl}")
        conn.commit()
    except Exception as e:
        logging.error("Ошибка расширения схемы events: %s", e)


def init_db():
    conn = get_conn()
    conn.executescript("""
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

        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reason TEXT DEFAULT 'Не указана',
            moderator_id INTEGER,
            date TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_warnings_user ON warnings(user_id);

        CREATE TABLE IF NOT EXISTS tickets (
            number INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            channel_id INTEGER,
            category TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            created_at TEXT,
            closed_at TEXT,
            closed_by INTEGER,
            transcript TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
        CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

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
            location TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS birthdays (
            user_id INTEGER PRIMARY KEY,
            date TEXT,
            notified INTEGER DEFAULT 0
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

        CREATE TABLE IF NOT EXISTS afk (
            user_id INTEGER PRIMARY KEY,
            reason TEXT DEFAULT 'AFK',
            since TEXT,
            display_name TEXT
        );
    """)
    _ensure_events_columns(conn)
    conn.commit()


def backup_database(backup_path: str = "bot_data_backup.db"):
    src = get_conn()
    dst = sqlite3.connect(backup_path)
    src.backup(dst)
    dst.close()
    logging.info("SQLite backup created: %s", backup_path)


def migrate_json_to_db():
    conn = get_conn()

    # member_stats
    if os.path.exists("member_stats.json"):
        with open("member_stats.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for uid, stats in data.items():
            conn.execute(
                "INSERT OR REPLACE INTO member_stats (user_id, messages, voice_seconds, voice_joins) VALUES (?, ?, ?, ?)",
                (int(uid), stats.get("messages", 0), stats.get("voice_seconds", 0), stats.get("voice_joins", 0)),
            )
            for s in stats.get("voice_sessions", []):
                conn.execute(
                    "INSERT INTO voice_sessions (user_id, channel, start, end, seconds) VALUES (?, ?, ?, ?, ?)",
                    (int(uid), s.get("channel", ""), s.get("start", ""), s.get("end", ""), s.get("seconds", 0)),
                )
        conn.commit()
        os.rename("member_stats.json", "member_stats.json.bak")
        logging.info("Migrated member_stats.json to SQLite (%d users)", len(data))

    # warnings
    if os.path.exists("warnings.json"):
        with open("warnings.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for uid, warns in data.items():
            for w in warns:
                conn.execute(
                    "INSERT INTO warnings (user_id, reason, moderator_id, date) VALUES (?, ?, ?, ?)",
                    (int(uid), w.get("reason", ""), int(w.get("moderator", 0)), w.get("date", "")),
                )
        conn.commit()
        os.rename("warnings.json", "warnings.json.bak")
        logging.info("Migrated warnings.json to SQLite")

    # tickets
    if os.path.exists("tickets.json"):
        with open("tickets.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for num_str, t in data.items():
            if num_str.startswith("_"):
                continue
            conn.execute(
                """INSERT OR REPLACE INTO tickets
                   (number, user_id, channel_id, category, status, created_at, closed_at, closed_by, transcript)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(num_str),
                    int(t.get("user_id", 0)),
                    int(t.get("channel_id", 0)),
                    t.get("category", ""),
                    t.get("status", "open"),
                    t.get("created_at", ""),
                    t.get("closed_at", ""),
                    int(t.get("closed_by", 0)) if t.get("closed_by") else 0,
                    t.get("transcript", ""),
                ),
            )
        conn.commit()
        os.rename("tickets.json", "tickets.json.bak")
        logging.info("Migrated tickets.json to SQLite")

    # events
    if os.path.exists("events.json"):
        with open("events.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for eid, ev in data.items():
            if eid.startswith("_"):
                continue
            going_inf = list(ev.get("going_inf", []))
            for u in ev.get("going", []):
                if u not in going_inf:
                    going_inf.append(u)
            start = ev.get("start") or (f"{ev.get('date', '')} {ev.get('time', '')}".strip())
            conn.execute(
                """INSERT OR REPLACE INTO events
                   (id, name, start, briefing, description, host_id, creator_id,
                    going_inf, going_tech, maybe, sl, camera, not_going,
                    show_not_going, required, channel_id, image_url, event_type, location)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(eid),
                    ev.get("name", ""),
                    start,
                    ev.get("briefing", ""),
                    ev.get("description", ""),
                    int(ev.get("host_id", 0) or 0),
                    int(ev.get("creator_id", 0) or 0),
                    json.dumps(going_inf),
                    json.dumps(ev.get("going_tech", [])),
                    json.dumps(ev.get("maybe", [])),
                    json.dumps(ev.get("sl", [])),
                    json.dumps(ev.get("camera", [])),
                    json.dumps(ev.get("not_going", [])),
                    int(bool(ev.get("show_not_going", True))),
                    int(ev.get("required", 0) or 0),
                    int(ev.get("channel_id", 0) or 0),
                    ev.get("image_url", ""),
                    ev.get("event_type", "freeform"),
                    ev.get("location", ""),
                ),
            )
        conn.commit()
        os.rename("events.json", "events.json.bak")
        logging.info("Migrated events.json to SQLite")

    # birthdays
    if os.path.exists("birthdays.json"):
        with open("birthdays.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for uid, info in data.items():
            conn.execute(
                "INSERT OR REPLACE INTO birthdays (user_id, date, notified) VALUES (?, ?, ?)",
                (int(uid), info.get("date", ""), int(info.get("notified", False))),
            )
        conn.commit()
        os.rename("birthdays.json", "birthdays.json.bak")
        logging.info("Migrated birthdays.json to SQLite")

    # giveaways
    if os.path.exists("giveaways.json"):
        with open("giveaways.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for mid, info in data.items():
            conn.execute(
                """INSERT OR REPLACE INTO giveaways
                   (message_id, prize, host_id, channel_id, end_time, winners_count, ended)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(mid),
                    info.get("prize", ""),
                    int(info.get("host", 0)),
                    int(info.get("channel_id", 0)),
                    info.get("end_time", ""),
                    info.get("winners_count", 1),
                    int(info.get("ended", False)),
                ),
            )
        conn.commit()
        os.rename("giveaways.json", "giveaways.json.bak")
        logging.info("Migrated giveaways.json to SQLite")

    # afk
    if os.path.exists("afk.json"):
        with open("afk.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for uid, info in data.items():
            conn.execute(
                "INSERT OR REPLACE INTO afk (user_id, reason, since, display_name) VALUES (?, ?, ?, ?)",
                (int(uid), info.get("reason", ""), info.get("since", ""), info.get("display_name", "")),
            )
        conn.commit()
        os.rename("afk.json", "afk.json.bak")
        logging.info("Migrated afk.json to SQLite")
