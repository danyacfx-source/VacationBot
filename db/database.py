"""Асинхронный фасад над PostgreSQL.

API прежний (execute/fetchone/fetchall/scalar/executemany/backup), сменён
только бэкенд: psycopg3 работает синхронно в отдельном потоке под RLock —
event loop не блокируется, а политика event loop не важна (на Windows
async-драйверы требуют Selector-луп, что конфликтует с discord.py).

SQL пишется в привычном стиле с '?': convert() переводит плейсхолдеры
на '%s', обходя строковые литералы, идентификаторы и комментарии.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Callable

import psycopg
from psycopg import sql as pg_sql
from psycopg.rows import dict_row

log = logging.getLogger(__name__)

Row = dict[str, Any]

_CONNECT_OPTIONS: dict[str, Any] = {
    "autocommit": True,
    "connect_timeout": 15,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "application_name": "vacationbot",
    "row_factory": dict_row,
}


def convert(query: str) -> str:
    """`?` -> `%s` вне строк, идентификаторов и комментариев."""
    out: list[str] = []
    i, n = 0, len(query)
    while i < n:
        ch = query[i]

        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                c = query[i]
                out.append(c)
                i += 1
                if c == quote:
                    if i < n and query[i] == quote:  # удвоенная кавычка
                        out.append(query[i])
                        i += 1
                        continue
                    break
            continue

        if ch == "-" and i + 1 < n and query[i + 1] == "-":
            end = query.find("\n", i)
            end = n if end == -1 else end
            out.append(query[i:end])
            i = end
            continue

        if ch == "/" and i + 1 < n and query[i + 1] == "*":
            end = query.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append(query[i:end])
            i = end
            continue

        out.append("%s" if ch == "?" else ch)
        i += 1

    return "".join(out)


def mask_dsn(dsn: str) -> str:
    """DSN без пароля — для логов."""
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    creds, hostpart = rest.rsplit("@", 1)
    login = creds.split(":", 1)[0]
    return f"{scheme}://{login}:***@{hostpart}"


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._conn: psycopg.Connection | None = None
        self._lock = threading.RLock()
        self._pk_cache: dict[str, list[str]] = {}

    # ------------------------------------------------------------ жизненный цикл

    def connect(self) -> None:
        """Открывает соединение (синхронно, до запуска основных задач)."""
        if self._conn is not None and not self._conn.closed:
            return
        self._conn = psycopg.connect(self.dsn, **_CONNECT_OPTIONS)
        log.info("PostgreSQL подключён: %s", mask_dsn(self.dsn))

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    @property
    def connection(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self.connect()
        assert self._conn is not None
        return self._conn

    # ------------------------------------------------------------ низкоуровневый прогон

    def _run(self, fn: Callable[[], Any]):
        """Выполняет fn под замком в отдельном потоке; при обрыве связи — один ретрай."""
        loop = asyncio.get_running_loop()

        def runner():
            with self._lock:
                try:
                    return fn()
                except psycopg.OperationalError as exc:
                    log.warning("PostgreSQL: связь потеряна (%s), переподключаюсь", exc)
                    self.close()
                    self.connect()
                    return fn()

        return loop.run_in_executor(None, runner)

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        def _do():
            return self.connection.execute(convert(sql), params).rowcount

        return await self._run(_do)

    async def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> int:
        items = list(seq)
        if not items:
            return 0
        query = convert(sql)

        def _do():
            with self.connection.cursor() as cur:
                cur.executemany(query, items)
                return cur.rowcount

        return await self._run(_do)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Row | None:
        def _do():
            return self.connection.execute(convert(sql), params).fetchone()

        return await self._run(_do)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        def _do():
            return self.connection.execute(convert(sql), params).fetchall()

        return await self._run(_do)

    async def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        def _do():
            row = self.connection.execute(convert(sql), params).fetchone()
            if row is None:
                return default
            return next(iter(row.values()))

        return await self._run(_do)

    async def executescript(self, script: str) -> None:
        """Несколько операторов за раз (DDL-схема)."""

        def _do():
            self.connection.execute(script)

        await self._run(_do)

    # ------------------------------------------------------------ upsert

    async def insert_replace(
        self,
        table: str,
        columns: Sequence[str],
        rows: Iterable[Sequence[Any]],
    ) -> int:
        """INSERT OR REPLACE: конфликт решается по первичному ключу таблицы."""
        items = list(rows)
        if not items:
            return 0

        def _do():
            return self._upsert(table, list(columns), items)

        return await self._run(_do)

    def _upsert(self, table: str, columns: list[str], items: list[Sequence[Any]]) -> int:
        conn = self.connection
        pk = self._pk_cache.get(table)
        if pk is None:
            cur = conn.execute(
                "SELECT kcu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON kcu.constraint_name = tc.constraint_name "
                " AND kcu.table_schema = tc.table_schema "
                "WHERE tc.table_schema = 'public' "
                "  AND tc.table_name = %s "
                "  AND tc.constraint_type = 'PRIMARY KEY' "
                "ORDER BY kcu.ordinal_position",
                (table,),
            )
            pk = [row["column_name"] for row in cur.fetchall()]
            self._pk_cache[table] = pk

        head = pg_sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            pg_sql.Identifier(table),
            pg_sql.SQL(", ").join(pg_sql.Identifier(c) for c in columns),
            pg_sql.SQL(", ").join(pg_sql.Placeholder() for _ in columns),
        )
        if pk:
            conflict = pg_sql.SQL(" ON CONFLICT ({}) ").format(
                pg_sql.SQL(", ").join(pg_sql.Identifier(c) for c in pk)
            )
            updates = [c for c in columns if c not in pk]
            if updates:
                action = pg_sql.SQL("DO UPDATE SET {}").format(
                    pg_sql.SQL(", ").join(
                        pg_sql.SQL("{} = EXCLUDED.{}").format(
                            pg_sql.Identifier(c), pg_sql.Identifier(c)
                        )
                        for c in updates
                    )
                )
            else:
                action = pg_sql.SQL("DO NOTHING")
            query = head + conflict + action
        else:
            query = head + pg_sql.SQL(" ON CONFLICT DO NOTHING")

        with conn.cursor() as cur:
            cur.executemany(query, items)
            return cur.rowcount

    # ------------------------------------------------------------ бэкап

    async def backup(self, target: str | Path) -> None:
        """Дамп данных всех таблиц в восстановимый COPY-скрипт."""

        def _do():
            self._dump(Path(target))

        await self._run(_do)
        log.info("Бэкап PostgreSQL: %s", target)

    def _dump(self, path: Path) -> None:
        conn = self.connection
        cur = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        tables = [row["tablename"] for row in cur.fetchall()]

        with open(path, "wb") as handle:
            handle.write(b"-- VacationBot PostgreSQL dump\n")
            for table in tables:
                header = pg_sql.SQL('COPY public.{} FROM stdin WITH (FORMAT csv, HEADER true);\n').format(
                    pg_sql.Identifier(table)
                )
                handle.write(header.as_string(conn).encode("utf-8"))
                with conn.cursor().copy(
                    f'COPY public."{table}" TO STDOUT WITH (FORMAT csv, HEADER true)'
                ) as copy:
                    for chunk in copy:
                        handle.write(
                            chunk if isinstance(chunk, (bytes, bytearray, memoryview))
                            else chunk.encode("utf-8")
                        )
                handle.write(b"\\.\n")


__all__ = ["Database", "Row", "convert", "mask_dsn"]
