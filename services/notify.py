"""Отправка служебных сообщений в лог-каналы."""

from __future__ import annotations

import logging

import discord

import config

log = logging.getLogger(__name__)


async def _send(
    bot,
    channel_id: int,
    title: str,
    description: str,
    color: discord.Color,
    ping: bool = False,
    ping_role: int | None = None,
) -> None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        return
    embed = discord.Embed(title=title, description=description, color=color)
    content = None
    if ping and ping_role:
        content = f"<@&{ping_role}>"
    try:
        await channel.send(content=content, embed=embed)
    except Exception as exc:
        log.debug("Не удалось отправить в канал %s: %s", channel_id, exc)


async def send_log(
    bot,
    title: str,
    description: str,
    color: discord.Color | None = None,
    ping: bool = True,
) -> None:
    await _send(
        bot,
        config.LOG_CHANNEL,
        title,
        description,
        color or discord.Color.red(),
        ping=ping,
        ping_role=config.ERROR_ROLE if ping else None,
    )


async def send_startup_log(
    bot, title: str, description: str, color: discord.Color | None = None
) -> None:
    await _send(bot, config.STARTUP_LOG_CHANNEL, title, description, color or discord.Color.green())


async def send_ticket_log(
    bot, title: str, description: str, color: discord.Color | None = None
) -> None:
    await _send(bot, config.TICKET_LOG_CHANNEL, title, description, color or discord.Color.blue())


async def send_vacation_log(
    bot, title: str, description: str, color: discord.Color | None = None
) -> None:
    await _send(
        bot, config.VACATION_LOG_CHANNEL, title, description, color or discord.Color.orange()
    )


async def send_moderation_log(
    bot, guild: discord.Guild, title: str, description: str, color: discord.Color | None = None
) -> None:
    """Мод-лог берётся из guild — не требует глобального bot.get_channel."""
    channel = guild.get_channel(config.MODERATION_LOG_CHANNEL) or bot.get_channel(
        config.MODERATION_LOG_CHANNEL
    )
    if channel is None:
        return
    embed = discord.Embed(title=title, description=description, color=color or discord.Color.red())
    try:
        await channel.send(embed=embed)
    except Exception as exc:
        log.debug("Мод-лог недоступен: %s", exc)


__all__ = [
    "send_log",
    "send_startup_log",
    "send_ticket_log",
    "send_vacation_log",
    "send_moderation_log",
]
