"""Глобальные обработчики ошибок: slash-команды, prefix-команды, события."""

from __future__ import annotations

import logging
import traceback
from typing import Any

import discord
from discord.ext import commands

from services.notify import send_log

log = logging.getLogger(__name__)


def fmt_exception(exc: BaseException, limit: int = 1800) -> str:
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if len(text) > limit:
        text = text[-limit:]
    return f"```{text}```"


def friendly_message(error: Exception) -> str:
    original = getattr(error, "original", error)
    if isinstance(original, discord.app_commands.MissingPermissions):
        return "Недостаточно прав для выполнения команды."
    if isinstance(original, discord.app_commands.BotMissingPermissions):
        missing = ", ".join(p.replace("_", " ") for p in getattr(original, "missing_permissions", []))
        return f"Боту не хватает прав: **{missing}**" if missing else "Боту не хватает прав."
    if isinstance(original, discord.app_commands.CommandOnCooldown):
        return f"Подождите **{original.retry_after:.0f} сек.** перед повторным вызовом."
    if isinstance(original, discord.app_commands.CheckFailure):
        return "Условия выполнения команды не выполнены."
    return "Произошла ошибка при выполнении команды."


def install(bot: commands.Bot) -> None:
    """Вешает все обработчики на экземпляр бота."""

    @bot.tree.error
    async def tree_error(interaction: discord.Interaction, error: Exception) -> None:
        original = getattr(error, "original", error)
        log.error("Ошибка slash-команды /%s", getattr(interaction.command, "name", "?"), exc_info=original)
        message = friendly_message(error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass
        await send_log(
            bot,
            "⚠️ Ошибка команды",
            f"Команда: `/{getattr(interaction.command, 'name', '?')}`\n"
            f"Автор: {interaction.user}\n\n{fmt_exception(original)}",
            ping=False,
        )

    @bot.event
    async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        original = getattr(error, "original", error)
        log.error("Ошибка prefix-команды", exc_info=original)
        await send_log(
            bot,
            "⚠️ Ошибка команды",
            f"Команда: `{ctx.command}`\nАвтор: {ctx.author}\nКанал: {ctx.channel}\n\n"
            f"{fmt_exception(original)}",
            ping=False,
        )

    @bot.event
    async def on_error(event_method: str, *args: Any, **kwargs: Any) -> None:
        log.error("Ошибка события %s", event_method, exc_info=True)
        await send_log(
            bot, "⚠️ Ошибка события", f"Событие: `{event_method}`", ping=False
        )


__all__ = ["install", "fmt_exception", "friendly_message"]
