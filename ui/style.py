"""Единый стиль эмбедов: цвета, футеры, штампы времени."""

from __future__ import annotations

from datetime import datetime

import discord

import config
from core.timeutil import msk_now

FOOTER_DEFAULT = "Сделано с ❤️ от Денди"

# Семантические цвета — один источник правды для всех когов.
SUCCESS = discord.Color.green()
ERROR = discord.Color.red()
WARNING = discord.Color.orange()
INFO = discord.Color.blurple()
NEUTRAL = discord.Color.greyple()
ACCENT = discord.Color.gold()
VACATION = discord.Color.orange()
TICKET = discord.Color.blue()
EVENT = discord.Color.purple()
AI = discord.Color.dark_purple()


def base(
    title: str,
    description: str | None = None,
    *,
    color: discord.Color | None = None,
    footer: str | None = FOOTER_DEFAULT,
    timestamp: bool = False,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color or INFO)
    if footer:
        embed.set_footer(text=footer)
    if timestamp:
        embed.timestamp = datetime.now()
    return embed


def success(title: str, description: str | None = None, **kwargs) -> discord.Embed:
    return base(title, description, color=SUCCESS, **kwargs)


def error(title: str, description: str | None = None, **kwargs) -> discord.Embed:
    return base(title, description, color=ERROR, **kwargs)


def warning(title: str, description: str | None = None, **kwargs) -> discord.Embed:
    return base(title, description, color=WARNING, **kwargs)


def info(title: str, description: str | None = None, **kwargs) -> discord.Embed:
    return base(title, description, color=INFO, **kwargs)


def field(
    embed: discord.Embed, name: str, value: str, *, inline: bool = False
) -> discord.Embed:
    """Поле с защитой от пустых значений (Discord отклоняет пустую строку)."""
    embed.add_field(name=name, value=value or "—", inline=inline)
    return embed


def bullet_list(items: list[str], empty: str = "—", limit: int = 1024) -> str:
    if not items:
        return empty
    text = "\n".join(items)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def truncate(text: str, limit: int = 4000) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def respond_ok(interaction: discord.Interaction, text: str, *, ephemeral: bool = True):
    return await interaction.response.send_message(
        embed=success("✅ Готово", text), ephemeral=ephemeral
    )


async def respond_err(interaction: discord.Interaction, text: str, *, ephemeral: bool = True):
    return await interaction.response.send_message(embed=error("Ошибка", text), ephemeral=ephemeral)


def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False
    return bool(interaction.user.guild_permissions.administrator)


def now_msk() -> datetime:
    return msk_now()


__all__ = [
    "SUCCESS",
    "ERROR",
    "WARNING",
    "INFO",
    "NEUTRAL",
    "ACCENT",
    "VACATION",
    "TICKET",
    "EVENT",
    "AI",
    "base",
    "success",
    "error",
    "warning",
    "info",
    "field",
    "bullet_list",
    "truncate",
    "respond_ok",
    "respond_err",
    "is_admin",
    "FOOTER_DEFAULT",
    "config",
]
