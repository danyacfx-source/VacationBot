"""Поиск автора действия в журнале аудита Discord.

Один общий хелпер вместо восьми копий «пробежать audit_logs и найти
модератора» в handlers.py.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import discord

log = logging.getLogger(__name__)


async def find_audit_author(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target: discord.abc.Snowflake | int,
    *,
    limit: int = 10,
    delay: float = 0.6,
    predicate: Callable[[discord.AuditLogEntry], bool] | None = None,
) -> tuple[discord.Member | discord.User | None, discord.AuditLogEntry | None]:
    """Возвращает (автор, запись) для последнего действия по target.

    Discord пишет журнал аудита асинхронно, поэтому перед первым
    запросом даём небольшую паузу.
    """
    target_id = target if isinstance(target, int) else target.id
    if delay:
        import asyncio

        await asyncio.sleep(delay)

    try:
        async for entry in guild.audit_logs(limit=limit, action=action):
            obj = getattr(entry.target, "id", entry.target)
            if obj != target_id:
                continue
            if predicate and not predicate(entry):
                continue
            return entry.user, entry
    except discord.Forbidden:
        log.debug("Нет прав на журнал аудита в %s", guild)
    except Exception as exc:
        log.debug("Ошибка чтения журнала аудита: %s", exc)
    return None, None


async def find_last_action(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    *,
    limit: int = 10,
    predicate: Callable[[discord.AuditLogEntry], bool] | None = None,
) -> tuple[discord.Member | discord.User | None, discord.AuditLogEntry | None]:
    """Последняя запись указанного типа (для событий без target)."""
    import asyncio

    await asyncio.sleep(0.6)
    try:
        async for entry in guild.audit_logs(limit=limit, action=action):
            if predicate and not predicate(entry):
                continue
            return entry.user, entry
    except Exception as exc:
        log.debug("Ошибка чтения журнала аудита: %s", exc)
    return None, None


__all__ = ["find_audit_author", "find_last_action"]
