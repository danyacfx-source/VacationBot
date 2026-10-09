"""Класс бота: доступ к БД, сторам и планировщику — из любого кога."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

import config
from core.scheduler import Scheduler
from db import (
    Database,
    EventDraftStore,
    MusicStore,
    ReminderStore,
    StateStore,
    TempChannelStore,
    VacationStore,
    VoiceOpenStore,
)

log = logging.getLogger(__name__)


class VacationBot(commands.Bot):
    def __init__(self, db: Database, **kwargs: Any):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=config.intents,
            reconnect=True,
            max_messages=None,
            **kwargs,
        )
        self.db = db
        self.state = StateStore(db)
        self.vacations = VacationStore(db)
        self.temp_channels = TempChannelStore(db)
        self.reminders = ReminderStore(db)
        self.voice_open = VoiceOpenStore(db)
        self.event_drafts = EventDraftStore(db)
        self.music_store = MusicStore(db)
        self.scheduler = Scheduler(db)

        self.launch_time: discord.utils.datetime.datetime | None = None
        self._ready_done = False
        self._shutdown_requested = False
        self._load_errors: list[tuple[str, str]] = []
        self._persistent_view_ids: set[int] = set()
        self._persistent_view_keys: set[str] = set()

    # ------------------------------------------------------------ реестры

    def add_persistent_view(self, view: discord.ui.View) -> None:
        """Регистрирует view один раз — без дублей по id и по custom_id."""
        if id(view) in self._persistent_view_ids:
            return

        custom_ids = {
            getattr(item, "custom_id", None)
            for item in view.walk_children()
            if getattr(item, "custom_id", None)
        }
        if custom_ids and custom_ids & self._persistent_view_keys:
            self._persistent_view_ids.add(id(view))
            return

        self.add_view(view)
        self._persistent_view_ids.add(id(view))
        self._persistent_view_keys |= custom_ids

    def add_persistent_views(self, views: list[discord.ui.View]) -> None:
        for view in views:
            self.add_persistent_view(view)

    # ------------------------------------------------------------ удобный доступ

    def channel_of(self, channel_id: int) -> discord.abc.GuildChannel | None:
        if not channel_id:
            return None
        return self.get_channel(channel_id)

    async def notify_error(self, title: str, description: str) -> None:
        from services.notify import send_log

        await send_log(self, title, description)


__all__ = ["VacationBot"]
