"""Панель отпусков: сборка эмбедов и обновление развёрнутых сообщений."""

from __future__ import annotations

import logging

import discord

from ui import style

log = logging.getLogger(__name__)


def build_info_panel_embed(data: dict[str, dict]) -> discord.Embed:
    embed = style.base("Система отпусков | Информация", color=style.VACATION)

    entries: list[str] = []
    for uid, entry in data.items():
        if not isinstance(entry, dict):
            continue
        periods = entry.get("periods", [])
        if not periods:
            continue

        lines = [f"<@{uid}>"]
        for period in periods:
            start = period.get("start_date", "")
            end = period.get("end_date", "")
            reason = period.get("reason", "")
            lines.append(f"от {start} до {end}" if start else f"до {end}")
            if reason:
                lines.append(reason)
        entries.append("\n".join(lines))

    embed.description = "\n\n".join(entries) if entries else "Нет активных отпусков"
    return embed


def build_request_panel_embed() -> discord.Embed:
    return style.base(
        "Система отпусков | Панель",
        (
            "Нажмите кнопку ниже, чтобы подать заявку на отпуск.\n\n"
            "🔹 **Взять отпуск** — подать заявку\n"
            "🔹 **Статус** — посмотреть свои отпуска\n"
            "🔹 **Продлить отпуск** — продлить текущий отпуск\n"
            "🔹 **Снять отпуск** — отменить текущий отпуск"
        ),
        color=discord.Color.blurple(),
    )


async def refresh_panels(bot) -> int:
    """Обновляет обе сообщения панели. Возвращает число обновлений."""
    store = getattr(bot, "vacations", None)
    if store is None:
        return 0

    panel = await store.get_panel()
    if not panel:
        return 0

    channel = bot.channel_of(int(panel.get("channel_id") or 0))
    if channel is None:
        return 0

    updated = 0
    data = await store.list_all()

    info_id = int(panel.get("info_message_id") or 0)
    if info_id:
        try:
            message = await channel.fetch_message(info_id)
            await message.edit(embed=build_info_panel_embed(data))
            updated += 1
        except Exception as exc:
            log.debug("Не удалось обновить инфо-панель: %s", exc)

    request_id = int(panel.get("request_message_id") or 0)
    if request_id:
        try:
            message = await channel.fetch_message(request_id)
            await message.edit(embed=build_request_panel_embed())
            updated += 1
        except Exception as exc:
            log.debug("Не удалось обновить панель заявок: %s", exc)

    return updated


__all__ = ["build_info_panel_embed", "build_request_panel_embed", "refresh_panels"]
