"""Единый планировщик фоновых задач.

Заменяет одиннадцать `tasks.loop(minutes=1)` с ручной проверкой часа
и флагами в памяти. Последний запуск каждого задания хранится в БД,
поэтому рестарт не приводит ни к двойной отправке, ни к пропуску.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Awaitable, Callable

import config
from db import Database

log = logging.getLogger(__name__)

JobFunc = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class Job:
    name: str
    func: JobFunc
    kind: str = "daily"  # daily | interval
    at: time | None = None
    interval_seconds: int = 0
    catch_up: bool = False
    window_minutes: int = config.DAILY_WINDOW_MINUTES
    enabled: bool = True
    last_run: datetime | None = None
    _ran_date: date | None = field(default=None, repr=False)

    def is_due(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        if self.kind == "interval":
            if self.last_run is None:
                return True
            return (now - self.last_run).total_seconds() >= self.interval_seconds

        assert self.at is not None
        last_day = self.last_run.date() if self.last_run else None
        if last_day == now.date():
            return False
        if now.timetz().replace(tzinfo=None) < self.at:
            return False
        if self.catch_up:
            return True
        window_end = (
            datetime.combine(now.date(), self.at) + timedelta(minutes=self.window_minutes)
        ).time()
        return now.timetz().replace(tzinfo=None) <= window_end

    def mark(self, now: datetime) -> None:
        self.last_run = now
        if self.kind == "daily":
            self._ran_date = now.date()


def _msk_now() -> datetime:
    from core.timeutil import msk_now

    return msk_now()


class Scheduler:
    def __init__(self, db: Database):
        self._db = db
        self._jobs: dict[str, Job] = {}
        self._task: asyncio.Task | None = None
        self._ready = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ регистрация

    def daily(
        self,
        name: str,
        hour: int,
        minute: int = 0,
        *,
        catch_up: bool = False,
        window_minutes: int | None = None,
    ) -> Callable[[JobFunc], JobFunc]:
        """Декоратор: ежедневное задание в указанные часы и минуты (МСК)."""

        def wrapper(func: JobFunc) -> JobFunc:
            self.register_daily(
                name,
                func,
                hour=hour,
                minute=minute,
                catch_up=catch_up,
                window_minutes=window_minutes,
            )
            return func

        return wrapper

    def every(
        self, name: str, seconds: int
    ) -> Callable[[JobFunc], JobFunc]:
        """Декоратор: интервальное задание."""

        def wrapper(func: JobFunc) -> JobFunc:
            self.register_interval(name, func, seconds)
            return func

        return wrapper

    def register_daily(
        self,
        name: str,
        func: JobFunc,
        *,
        hour: int,
        minute: int = 0,
        catch_up: bool = False,
        window_minutes: int | None = None,
    ) -> None:
        self._jobs[name] = Job(
            name=name,
            func=func,
            kind="daily",
            at=time(hour=hour, minute=minute),
            catch_up=catch_up,
            window_minutes=(
                window_minutes if window_minutes is not None else config.DAILY_WINDOW_MINUTES
            ),
        )

    def register_interval(self, name: str, func: JobFunc, seconds: int) -> None:
        self._jobs[name] = Job(
            name=name, func=func, kind="interval", interval_seconds=max(1, int(seconds))
        )

    def unregister(self, name: str) -> None:
        self._jobs.pop(name, None)

    @property
    def jobs(self) -> list[str]:
        return sorted(self._jobs)

    # ------------------------------------------------------------ жизненный цикл

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._load_state()
        self._ready = True
        self._task = asyncio.create_task(self._loop(), name="scheduler")
        log.info("Планировщик запущен: %d заданий", len(self._jobs))

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _load_state(self) -> None:
        try:
            rows = await self._db.fetchall("SELECT job, last_run FROM scheduler_state")
        except Exception as exc:
            log.error("Не удалось прочитать состояние планировщика: %s", exc)
            return
        for row in rows:
            job = self._jobs.get(row["job"])
            if job is None:
                continue
            try:
                job.last_run = datetime.fromisoformat(row["last_run"])
            except (TypeError, ValueError):
                job.last_run = None

    async def _save_state(self, job: Job) -> None:
        if job.last_run is None:
            return
        try:
            await self._db.execute(
                "INSERT INTO scheduler_state (job, last_run) VALUES (?, ?) "
                "ON CONFLICT(job) DO UPDATE SET last_run = excluded.last_run",
                (job.name, job.last_run.isoformat(timespec="seconds")),
            )
        except Exception as exc:
            log.error("Не удалось сохранить состояние задания %s: %s", job.name, exc)

    # ------------------------------------------------------------ цикл

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(20)
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Ошибка цикла планировщика")

    async def tick(self, now: datetime | None = None) -> list[str]:
        """Один проход. Возвращает имена запущенных заданий (для тестов)."""
        now = now or _msk_now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        ran: list[str] = []
        for job in list(self._jobs.values()):
            if not job.is_due(now):
                continue
            job.mark(now)
            await self._save_state(job)
            ran.append(job.name)
            asyncio.create_task(self._run(job), name=f"job:{job.name}")
        return ran

    async def _run(self, job: Job) -> None:
        try:
            await job.func()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Задание %s завершилось с ошибкой", job.name)


__all__ = ["Scheduler", "Job", "_msk_now"]
