"""Настройка логирования + отправка ERROR-логов в Discord с батчингом."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import discord

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(log_file: str = "bot.log") -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


class DiscordLogHandler(logging.Handler):
    """Пакетирует ERROR-записи и шлёт их в канал логов раз в 5 секунд.

    Не заспамит при циклических ошибках и не держит event loop.
    """

    FLUSH_DELAY = 5.0
    MAX_LEN = 1900

    def __init__(self, send: Callable[[str], object]):
        super().__init__(level=logging.ERROR)
        self._send = send
        self._pending: list[str] = []
        self._task: asyncio.Task | None = None
        self.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name.startswith("discord"):
                return
            self._pending.append(self.format(record))
            self._schedule()
        except Exception:
            pass

    def _schedule(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._flush(), name="discord-log-flush")

    async def _flush(self) -> None:
        try:
            await asyncio.sleep(self.FLUSH_DELAY)
            if not self._pending:
                return
            pending, self._pending = self._pending, []
            text = "\n".join(pending)
            if len(text) > self.MAX_LEN:
                text = text[-self.MAX_LEN:]
            await self._send(f"```\n{text}\n```")
        except Exception:
            pass


def install_discord_handler(send: Callable[[str], object]) -> DiscordLogHandler:
    handler = DiscordLogHandler(send)
    logging.getLogger().addHandler(handler)
    return handler
