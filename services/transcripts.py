"""Транскрипты тикетов и точечные SQL-записи таблицы tickets.

Оба тикет-кога (cogs.tickets, cogs.clan_tickets) зовут эти функции:
генерация текста транскрипта и SQL по таблице tickets существуют
в одном экземпляре и не дублируются.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import discord

from db.schema import TICKET_COLUMNS as _TICKET_DDL
from db.schema import ensure_columns as _ensure_columns
from ui import style

log = logging.getLogger(__name__)

# ------------------------------------------------------------ таблица tickets

# ключ словаря тикета -> (колонка БД, тип)
_TICKET_COLUMNS: dict[str, tuple[str, type]] = {
    "user_id": ("user_id", int),
    "channel_id": ("channel_id", int),
    "type": ("ticket_type", str),
    "status": ("status", str),
    "created_at": ("created_at", str),
    "closed_at": ("closed_at", str),
    "closed_by": ("closed_by", int),
    "transcript": ("transcript", str),
    "guild_id": ("guild_id", int),
    "approved_by": ("approved_by", int),
    "approved_at": ("approved_at", str),
    "rejected_by": ("rejected_by", int),
    "rejected_at": ("rejected_at", str),
}

_DEFAULTS: dict[str, Any] = {"status": "open", "transcript": ""}

_COLUMNS = [column for column, _ in _TICKET_COLUMNS.values()]
_SELECT_LIST = ", ".join(["number", *_COLUMNS])


def _coerce(cast: type, value: Any) -> Any:
    if cast is int:
        try:
            return int(value) if value else 0
        except (TypeError, ValueError):
            return 0
    return str(value) if value is not None else ""


def _row_to_ticket(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(column) for key, (column, _) in _TICKET_COLUMNS.items()}


async def ensure_ticket_schema(db) -> None:
    """Добавляет недостающие колонки таблицы tickets (идемпотентно).

    Проверка одна — дальше флаг на самом объекте БД (глобального состояния нет).
    """
    if getattr(db, "_tickets_schema_ready", False):
        return

    try:
        await _ensure_columns(db, "tickets", _TICKET_DDL)
    except Exception as exc:
        log.error("Не удалось сверить схему tickets: %s", exc)

    setattr(db, "_tickets_schema_ready", True)


async def fetch_ticket(bot, channel_id: int) -> dict[str, Any] | None:
    """Тикет по ID канала (номер тикета = channel_id)."""
    await ensure_ticket_schema(bot.db)
    row = await bot.db.fetchone(
        f"SELECT {_SELECT_LIST} FROM tickets WHERE number = ?",
        (int(channel_id),),
    )
    return _row_to_ticket(row) if row else None


async def find_open_ticket(bot, user_id: int, ticket_type: str) -> dict[str, Any] | None:
    """Первый открытый тикет пользователя заданного типа."""
    await ensure_ticket_schema(bot.db)
    row = await bot.db.fetchone(
        f"SELECT {_SELECT_LIST} FROM tickets "
        "WHERE user_id = ? AND ticket_type = ? AND status = ? LIMIT 1",
        (int(user_id), ticket_type, "open"),
    )
    return _row_to_ticket(row) if row else None


async def save_ticket(bot, ticket: dict[str, Any]) -> None:
    """Upsert одной записи — без перезаписи всей таблицы."""
    number = int(ticket.get("channel_id") or ticket.get("number") or 0)
    if not number:
        raise ValueError("save_ticket: у тикета не указан channel_id")

    await ensure_ticket_schema(bot.db)
    columns = ["number", *_COLUMNS]
    params: list[Any] = [number]
    for key, (column, cast) in _TICKET_COLUMNS.items():
        value = ticket.get(key)
        if value in (None, "") and key in _DEFAULTS:
            value = _DEFAULTS[key]
        params.append(_coerce(cast, value))

    await bot.db.insert_replace("tickets", columns, [params])


async def update_ticket(bot, channel_id: int, **fields: Any) -> None:
    """Точечный UPDATE указанных полей одного тикета."""
    if not fields:
        return

    assignments: list[str] = []
    params: list[Any] = []
    await ensure_ticket_schema(bot.db)
    for key, value in fields.items():
        entry = _TICKET_COLUMNS.get(key)
        if entry is None:
            raise ValueError(f"update_ticket: неизвестное поле {key!r}")
        column, cast = entry
        assignments.append(f"{column} = ?")
        params.append(_coerce(cast, value))

    params.append(int(channel_id))
    await bot.db.execute(
        f"UPDATE tickets SET {', '.join(assignments)} WHERE number = ?",
        params,
    )


async def delete_ticket(bot, channel_id: int) -> int:
    """Удаляет одну запись по номеру тикета. Возвращает число затронутых строк."""
    await ensure_ticket_schema(bot.db)
    return await bot.db.execute("DELETE FROM tickets WHERE number = ?", (int(channel_id),))


# ------------------------------------------------------------ транскрипт

async def build_transcript_text(channel, *, message_fields: bool = True) -> str:
    """Текстовый транскрипт истории канала (хронологически)."""
    try:
        messages = [message async for message in channel.history(oldest_first=True)]
    except discord.HTTPException as exc:
        log.error("Не удалось прочитать историю канала %s: %s", channel.name, exc)
        return ""

    lines: list[str] = []
    for msg in messages:
        timestamp = msg.created_at.strftime("%d.%m.%Y %H:%M:%S")
        content = msg.content or ""
        if msg.embeds:
            for embed in msg.embeds:
                if embed.description:
                    content += f" {embed.description}"
                if message_fields and embed.fields:
                    for field in embed.fields:
                        content += f"\n**{field.name}**: {field.value}"
        lines.append(f"[{timestamp}] {msg.author}: {content}")

    return "\n".join(lines)


async def _transcript_meta(interaction: discord.Interaction, channel) -> discord.Embed:
    embed = style.base(
        f"Транскрипт: {channel.name}",
        color=style.NEUTRAL,
        footer=f"Канал: {channel.name} | Сохранил: {interaction.user}",
        timestamp=True,
    )
    ticket = await fetch_ticket(interaction.client, channel.id)
    if ticket:
        style.field(embed, "Пользователь", f"<@{ticket.get('user_id')}>", inline=True)
        style.field(embed, "Тип", str(ticket.get("type") or "unknown"), inline=True)
        style.field(embed, "Статус", str(ticket.get("status") or "unknown"), inline=True)
    return embed


async def send_transcript(
    interaction: discord.Interaction,
    *,
    prefix: str,
    transcript_channel_id: int,
    message_fields: bool = True,
    meta_fields: bool = False,
    fallback_file: bool = False,
    confirm_text: str = "Транскрипт сохранён.",
    ephemeral: bool = True,
) -> None:
    """Единая точка входа для обоих когов: файл + загрузка в канал транскриптов.

    prefix         — имя файла: ``{prefix}-{канал}.txt``
    message_fields — включать ли поля эмбедов сообщений в текст
    meta_fields    — эмбед с данными тикета рядом с файлом
    fallback_file  — если канал транскриптов не найден, отдать файл в ответ
    """
    channel = interaction.channel
    text = await build_transcript_text(channel, message_fields=message_fields)
    file = discord.File(
        fp=BytesIO(text.encode("utf-8")),
        filename=f"{prefix}-{channel.name}.txt",
    )

    guild = interaction.guild
    target = guild.get_channel(transcript_channel_id) if (guild and transcript_channel_id) else None

    if target is None:
        if fallback_file:
            await interaction.followup.send(file=file, ephemeral=ephemeral)
        else:
            await interaction.followup.send(
                embed=style.success("📄 Транскрипт", confirm_text),
                ephemeral=ephemeral,
            )
        return

    try:
        if meta_fields:
            await target.send(embed=await _transcript_meta(interaction, channel), file=file)
        else:
            await target.send(file=file)
    except discord.HTTPException as exc:
        log.error("Не удалось сохранить транскрипт канала %s: %s", channel.name, exc)
        await interaction.followup.send(
            embed=style.error("Ошибка", "Не удалось сохранить транскрипт."),
            ephemeral=ephemeral,
        )
        return

    await interaction.followup.send(
        embed=style.success("📄 Транскрипт", confirm_text),
        ephemeral=ephemeral,
    )


__all__ = [
    "ensure_ticket_schema",
    "fetch_ticket",
    "find_open_ticket",
    "save_ticket",
    "update_ticket",
    "delete_ticket",
    "build_transcript_text",
    "send_transcript",
]
