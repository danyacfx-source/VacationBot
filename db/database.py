"""Асинхронный фасад над SQLite.

Одно соединение, все операции сериализованы замком и выполняются
в executor'е — event loop никогда не блокируется на диске.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

Row = dict[str, Any]


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._ready = False

    # ------------------------------------------------------------ жизненный цикл

    def connect(self) -> None:
        """Создаёт соединение (синхронно, до запуска event loop)."""
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._ready = True
        log.info("SQLite подключён: %s", self.path)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
                self._ready = False

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    # ------------------------------------------------------------ низкоуровневый прогон

    def _run(self, fn):
        """Выполняет fn под замком в отдельном потоке."""
        loop = asyncio.get_running_loop()

        def runner():
            with self._lock:
                return fn()

        return loop.run_in_executor(None, runner)

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        def _do():
            cur = self.connection.execute(sql, params)
            return cur.rowcount

        return await self._run(_do)

    async def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> int:
        items = list(seq)

        def _do():
            cur = self.connection.executemany(sql, items)
            return cur.rowcount

        return await self._run(_do)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Row | None:
        def _do():
            row = self.connection.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

        return await self._run(_do)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        def _do():
            return [dict(r) for r in self.connection.execute(sql, params).fetchall()]

        return await self._run(_do)

    async def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        def _do():
            row = self.connection.execute(sql, params).fetchone()
            if row is None:
                return default
            return row[0]

        return await self._run(_do)

    # ------------------------------------------------------------ транзакции

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Явная транзакция: блокирует запись до завершения блока."""

        def _begin():
            self.connection.execute("BEGIN IMMEDIATE")

        await self._run(_begin)
        try:
            yield
        except BaseException:
            def _rollback():
                try:
                    self.connection.execute("ROLLBACK")
                except Exception:
                    pass

            await self._run(_rollback)
            raise
        else:
            def _commit():
                self.connection.execute("COMMIT")

            await self._run(_commit)

    # ------------------------------------------------------------ служебное

    async def backup(self, target: str | Path) -> None:
        def _do():
            dst = sqlite3.connect(str(target))
            try:
                self.connection.backup(dst)
            finally:
                dst.close()

        await self._run(_do)
        log.info("Бэкап SQLite: %s", target)

    async def executescript(self, script: str) -> None:
        await self._run(lambda: self.connection.executescript(script))

    async def vacuum(self) -> None:
        await self._run(lambda: self.connection.execute("VACUUM"))
