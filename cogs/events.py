"""Ивенты: создание через ЛС (7 шагов), RSVP, редактирование, отмена, напоминания.

Состояние диалогов персистентно (bot.event_drafts — таблица event_drafts),
поэтому рестарт не прерывает создание/редактирование ивента.
Гроссбух load_events/save_events заменён точечными INSERT/UPDATE/DELETE через bot.db.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from core.timeutil import msk_now
from ui import style

log = logging.getLogger(__name__)


# ------------------------------------------------------------ работа с БД

_EVENT_COLUMNS = (
    "id, name, start, briefing, description, creator_id, host_id, "
    "going_inf, going_tech, going, maybe, sl, camera, not_going, show_not_going, "
    "required, channel_id, image_url, event_type, location, date, time, "
    "reminded_briefing_minus15, reminded_briefing, reminded_start_minus15"
)

_INSERT_EVENT = (
    "INSERT INTO events (name, start, briefing, description, host_id, creator_id, "
    "going_inf, going_tech, going, maybe, sl, camera, not_going, show_not_going, "
    "required, channel_id, image_url, event_type, location, "
    "reminded_briefing_minus15, reminded_briefing, reminded_start_minus15) "
    "VALUES (?, ?, ?, ?, 0, ?, '[]', '[]', '[]', '[]', '[]', '[]', '[]', ?, 0, ?, ?, ?, '', 0, 0, 0) "
    "RETURNING id"
)

_RSVP_KEYS = ("going_inf", "going_tech", "maybe", "sl", "camera", "not_going")

_EDITABLE_FIELDS = {"name", "description", "briefing", "start", "image_url"}


def _jlist(value) -> list:
    try:
        parsed = json.loads(value) if value else []
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _row_to_event(row: dict) -> dict:
    going_inf = _jlist(row.get("going_inf"))
    for u in _jlist(row.get("going")):
        if u not in going_inf:
            going_inf.append(u)
    creator = row.get("creator_id") or row.get("host_id")
    start = row.get("start") or (
        f"{row.get('date', '')} {row.get('time', '')}".strip() if row.get("date") else ""
    )
    return {
        "name": row.get("name") or "",
        "start": start,
        "briefing": row.get("briefing") or "",
        "description": row.get("description") or "",
        "creator_id": str(creator) if creator else "",
        "going_inf": going_inf,
        "going_tech": _jlist(row.get("going_tech")),
        "maybe": _jlist(row.get("maybe")),
        "sl": _jlist(row.get("sl")),
        "camera": _jlist(row.get("camera")),
        "not_going": _jlist(row.get("not_going")),
        "show_not_going": bool(row.get("show_not_going")) if row.get("show_not_going") is not None else True,
        "required": row.get("required") or 0,
        "channel_id": row.get("channel_id") or 0,
        "image_url": row.get("image_url") or "",
        "event_type": row.get("event_type") or "freeform",
        "location": row.get("location") or "",
        "reminded_briefing_minus15": bool(row.get("reminded_briefing_minus15")),
        "reminded_briefing": bool(row.get("reminded_briefing")),
        "reminded_start_minus15": bool(row.get("reminded_start_minus15")),
    }


async def _fetch_event(db, event_id) -> dict | None:
    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        return None
    row = await db.fetchone(f"SELECT {_EVENT_COLUMNS} FROM events WHERE id = ?", (eid,))
    return _row_to_event(row) if row else None


async def _save_rsvp(db, event_id, event: dict) -> None:
    sets = ", ".join(f"{key} = ?" for key in _RSVP_KEYS)
    params = [json.dumps(event.get(key, [])) for key in _RSVP_KEYS]
    params.append(int(event_id))
    await db.execute(f"UPDATE events SET {sets} WHERE id = ?", params)


async def _update_event_field(db, event_id, field: str, value: str) -> None:
    if field not in _EDITABLE_FIELDS:
        raise ValueError(f"Недопустимое поле: {field}")
    await db.execute(f"UPDATE events SET {field} = ? WHERE id = ?", (value, int(event_id)))


def _parse_dt(text: str | None) -> datetime | None:
    """Парсинг «ДД.ММ.ГГГГ ЧЧ:ММ» (МСК). None вместо исключения."""
    try:
        return datetime.strptime((text or "").strip(), "%d.%m.%Y %H:%M")
    except (ValueError, AttributeError):
        return None


def _build_event_embed(event_id, data: dict) -> discord.Embed:
    embed = discord.Embed(
        title=data["name"],
        color=discord.Color.blurple()
    )

    if data.get("description"):
        embed.add_field(name="Описание / Description", value=data["description"], inline=False)

    start_display = (data.get("start") or f"{data.get('date', '')} {data.get('time', '')}") + " (МСК)"
    briefing_display = (data.get("briefing") or start_display) + " (МСК)" if data.get("briefing") else start_display

    embed.add_field(
        name="Сбор / Briefing",
        value=briefing_display,
        inline=False
    )

    embed.add_field(
        name="Начало / Start",
        value=start_display,
        inline=False
    )

    required = data.get("required", 0)
    going_count = len(data.get("going_inf", [])) + len(data.get("going_tech", []))
    if required > 0:
        embed.add_field(
            name="Нужно людей",
            value=f"**{going_count}** / {required}",
            inline=False
        )

    for key, label in [
        ("going_inf", "🪖 Иду (пех)"),
        ("going_tech", "🚜 Иду (тех)"),
        ("maybe", "🤔 Возможно"),
        ("sl", "🟠 SL"),
        ("camera", "📷 Камера"),
    ]:
        users = data.get(key, [])
        count = len(users)
        if users:
            value = "\n".join(f"<@{uid}>" for uid in users)
        else:
            value = "—"
        embed.add_field(name=f"{label} ({count})", value=value, inline=True)

    if data.get("show_not_going") or data.get("not_going"):
        users = data.get("not_going", [])
        count = len(users)
        value = "\n".join(f"<@{uid}>" for uid in users) if users else "—"
        embed.add_field(name=f"❌ Не иду ({count})", value=value, inline=True)

    creator_id = data.get("creator_id")
    if creator_id:
        embed.add_field(
            name="Создал / Created by",
            value=f"<@{creator_id}>",
            inline=False
        )

    if data.get("image_url"):
        embed.set_image(url=data["image_url"])

    embed.set_footer(text=f"ID: {event_id}")
    return embed


# ------------------------------------------------------------ view'ы диалога создания

class EventTypeView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def _state(self, interaction: discord.Interaction) -> dict | None:
        draft = await interaction.client.event_drafts.get(self.user_id)
        if draft and draft[0] == "create" and isinstance(draft[1], dict):
            return draft[1]
        return None

    @discord.ui.button(label="1 — Компетитив", style=discord.ButtonStyle.primary, custom_id="ev_type_comp")
    async def competitive(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(embed=style.error("Не для тебя."), ephemeral=True)
        state = await self._state(interaction)
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)
        state["event_type"] = "competitive"
        state["step"] = "description"
        await interaction.client.event_drafts.set(self.user_id, "create", state)
        await interaction.response.edit_message(content="✅ Тип: **Компетитив**\n\n📝 Шаг 3/7 — Описание события\nВведите описание:", view=None)

    @discord.ui.button(label="2 — Свободная форма", style=discord.ButtonStyle.secondary, custom_id="ev_type_free")
    async def freeform(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(embed=style.error("Не для тебя."), ephemeral=True)
        state = await self._state(interaction)
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)
        state["event_type"] = "freeform"
        state["step"] = "description"
        await interaction.client.event_drafts.set(self.user_id, "create", state)
        await interaction.response.edit_message(content="✅ Тип: **Свободная форма**\n\n📝 Шаг 3/7 — Описание события\nВведите описание:", view=None)


class NotGoingickerView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def _state(self, interaction: discord.Interaction) -> dict | None:
        draft = await interaction.client.event_drafts.get(self.user_id)
        if draft and draft[0] == "create" and isinstance(draft[1], dict):
            return draft[1]
        return None

    @discord.ui.button(label="1 — Да", style=discord.ButtonStyle.success, custom_id="ev_notgoing_yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(embed=style.error("Не для тебя."), ephemeral=True)
        state = await self._state(interaction)
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)
        state["show_not_going"] = True
        await interaction.client.event_drafts.set(self.user_id, "create", state)
        await self._finish_preview(interaction, state)

    @discord.ui.button(label="2 — Нет", style=discord.ButtonStyle.danger, custom_id="ev_notgoing_no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(embed=style.error("Не для тебя."), ephemeral=True)
        state = await self._state(interaction)
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)
        state["show_not_going"] = False
        await interaction.client.event_drafts.set(self.user_id, "create", state)
        await self._finish_preview(interaction, state)

    async def _finish_preview(self, interaction: discord.Interaction, state: dict):
        embed = self._build_preview(state)
        await interaction.response.edit_message(content="📋 **Превью события:**", embed=embed, view=PublishConfirmView(self.user_id))

    def _build_preview(self, state: dict) -> discord.Embed:
        embed = discord.Embed(title=state["name"], color=discord.Color.blurple())
        if state.get("description"):
            embed.add_field(name="Описание / Description", value=state["description"], inline=False)
        embed.add_field(name="Сбор / Briefing", value=state["briefing"] + " (МСК)", inline=False)
        embed.add_field(name="Начало / Start", value=state["start"] + " (МСК)", inline=False)
        embed.add_field(name="🪖 Иду (пех) (0)", value="—", inline=True)
        embed.add_field(name="🚜 Иду (тех) (0)", value="—", inline=True)
        embed.add_field(name="🤔 Возможно (0)", value="—", inline=True)
        embed.add_field(name="🟠 SL (0)", value="—", inline=True)
        embed.add_field(name="📷 Камера (0)", value="—", inline=True)
        if state.get("show_not_going"):
            embed.add_field(name="❌ Не иду (0)", value="—", inline=True)
        embed.add_field(name="Создал / Created by", value=f"<@{self.user_id}>", inline=False)
        if state.get("image_url"):
            embed.set_image(url=state["image_url"])
        return embed


class PublishConfirmView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="1 — Да, опубликовать", style=discord.ButtonStyle.success, custom_id="ev_publish_yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(embed=style.error("Не для тебя."), ephemeral=True)
        db = interaction.client.db
        draft = await interaction.client.event_drafts.get(self.user_id)
        if not draft or draft[0] != "create" or not isinstance(draft[1], dict):
            await interaction.client.event_drafts.clear(self.user_id)
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)
        state = draft[1]
        await interaction.client.event_drafts.clear(self.user_id)

        channel = interaction.client.channel_of(int(state.get("channel_id") or 0))
        if channel is None:
            return await interaction.response.edit_message(content="❌ Канал не найден.", embed=None, view=None)

        try:
            row = await db.fetchone(
                _INSERT_EVENT,
                (
                    state.get("name", ""),
                    state.get("start", ""),
                    state.get("briefing", ""),
                    state.get("description", ""),
                    self.user_id,
                    int(bool(state.get("show_not_going", False))),
                    int(state.get("channel_id") or 0),
                    state.get("image_url", ""),
                    state.get("event_type", "freeform"),
                ),
            )
        except Exception:
            log.exception("Ошибка вставки ивента")
            return await interaction.response.edit_message(content="❌ Не удалось опубликовать ивент.", embed=None, view=None)
        if not row:
            return await interaction.response.edit_message(content="❌ Не удалось опубликовать ивент.", embed=None, view=None)

        event_id = str(row["id"])
        event = await _fetch_event(db, event_id)
        if event is None:
            return await interaction.response.edit_message(content="❌ Не удалось опубликовать ивент.", embed=None, view=None)

        embed = _build_event_embed(event_id, event)
        view = EventRSVPSelectView(event_id, creator_id=self.user_id)
        await channel.send(embed=embed, view=view)
        await interaction.response.edit_message(content="✅ **Ивент опубликован!**", embed=None, view=None)

    @discord.ui.button(label="2 — Нет, отменить", style=discord.ButtonStyle.danger, custom_id="ev_publish_no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(embed=style.error("Не для тебя."), ephemeral=True)
        await interaction.client.event_drafts.clear(self.user_id)
        await interaction.response.edit_message(content="❌ Создание ивента отменено.", embed=None, view=None)


# ------------------------------------------------------------ view'ы редактирования

class EventEditSelectView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def _state(self, interaction: discord.Interaction) -> dict | None:
        draft = await interaction.client.event_drafts.get(self.user_id)
        if draft and draft[0] == "edit" and isinstance(draft[1], dict):
            return draft[1]
        return None

    @discord.ui.select(
        placeholder="Выбери поле для редактирования...",
        options=[
            discord.SelectOption(label="Название", value="name", emoji="📝"),
            discord.SelectOption(label="Описание", value="description", emoji="📋"),
            discord.SelectOption(label="Время сбора (Briefing)", value="briefing", emoji="📢"),
            discord.SelectOption(label="Время начала (Start)", value="start", emoji="⏰"),
            discord.SelectOption(label="Изображение", value="image_url", emoji="🖼"),
        ],
        custom_id="ev_edit_select",
    )
    async def select_field(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(embed=style.error("Не для тебя."), ephemeral=True)
        state = await self._state(interaction)
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)

        field = select.values[0]
        state["field"] = field
        state["step"] = "awaiting_value"
        await interaction.client.event_drafts.set(self.user_id, "edit", state)

        event = await _fetch_event(interaction.client.db, state.get("event_id"))
        if not event:
            return await interaction.response.edit_message(content="❌ Ивент не найден.", embed=None, view=None)

        field_labels = {
            "name": "Название",
            "description": "Описание",
            "briefing": "Время сбора (ДД.ММ.ГГГГ ЧЧ:ММ)",
            "start": "Время начала (ДД.ММ.ГГГГ ЧЧ:ММ)",
            "image_url": "Изображение",
        }
        current = event.get(field, "") or "(пусто)"
        label = field_labels.get(field, field)

        if field == "image_url":
            msg = (
                f"✅ Поле: **{label}**\n"
                f"Текущее значение: {current if current else '(нет изображения)'}\n\n"
                "🖼 Прикрепи новое изображение или отправь `-` чтобы удалить."
            )
        else:
            msg = (
                f"✅ Поле: **{label}**\n"
                f"Текущее значение: {current}\n\n"
                "✏️ Введи новое значение:"
            )
        await interaction.response.edit_message(content=msg, view=None)


class EventEditConfirmView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def _state(self, interaction: discord.Interaction) -> dict | None:
        draft = await interaction.client.event_drafts.get(self.user_id)
        if draft and draft[0] == "edit" and isinstance(draft[1], dict):
            return draft[1]
        return None

    @discord.ui.button(label="✅ Сохранить", style=discord.ButtonStyle.success, custom_id="ev_edit_save")
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(embed=style.error("Не для тебя."), ephemeral=True)
        state = await self._state(interaction)
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)

        db = interaction.client.db
        event = await _fetch_event(db, state.get("event_id"))
        if not event:
            await interaction.client.event_drafts.clear(self.user_id)
            return await interaction.response.edit_message(content="❌ Ивент не найден.", embed=None, view=None)

        field = state.get("field")
        new_value = state.get("new_value", "")
        try:
            await _update_event_field(db, state["event_id"], field, new_value)
        except ValueError:
            log.error("Edit: недопустимое поле %r", field)
            return await interaction.response.edit_message(content="❌ Ивент не найден.", embed=None, view=None)

        event[field] = new_value
        embed = _build_event_embed(state["event_id"], event)
        channel = interaction.client.channel_of(int(state.get("channel_id") or 0))
        if channel:
            try:
                msg = await channel.fetch_message(state["message_id"])
                await msg.edit(embed=embed)
            except (discord.NotFound, discord.HTTPException) as e:
                log.info("Edit: не удалось обновить эмбед (%s): %s", type(e).__name__, e)

        await interaction.client.event_drafts.clear(self.user_id)
        await interaction.response.edit_message(content="✅ Ивент обновлён!", embed=None, view=None)

    @discord.ui.button(label="❌ Отмена", style=discord.ButtonStyle.danger, custom_id="ev_edit_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(embed=style.error("Не для тебя."), ephemeral=True)
        await interaction.client.event_drafts.clear(self.user_id)
        await interaction.response.edit_message(content="❌ Редактирование отменено.", embed=None, view=None)


# ------------------------------------------------------------ persistent view ивента

class EventRSVPSelectView(discord.ui.View):
    """RSVP-панель ивента. Регистрируется в bot.py как persistent (event_id="0")."""

    def __init__(self, event_id: str = "0", creator_id: int = 0):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.creator_id = creator_id

    async def _get_event_id(self, interaction: discord.Interaction) -> str | None:
        if self.event_id and self.event_id != "0":
            return self.event_id
        msg = interaction.message
        if msg and msg.embeds:
            footer = msg.embeds[0].footer.text or ""
            log.info("_get_event_id: footer=%r, embed title=%r", footer, msg.embeds[0].title)
            if footer.startswith("ID: "):
                return footer[4:]
            title = msg.embeds[0].title or ""
            if title:
                row = await interaction.client.db.fetchone(
                    "SELECT id FROM events WHERE name = ? LIMIT 1", (title,)
                )
                if row:
                    return str(row["id"])
        else:
            log.warning("_get_event_id: no embeds on message. msg=%s", msg)
        return None

    @discord.ui.select(
        placeholder="Выбери действие...",
        options=[
            discord.SelectOption(label="🪖 Иду (пех)", value="going_inf", emoji="🪖"),
            discord.SelectOption(label="🚜 Иду (тех)", value="going_tech", emoji="🚜"),
            discord.SelectOption(label="🤔 Возможно", value="maybe", emoji="🤔"),
            discord.SelectOption(label="🟠 SL", value="sl", emoji="🟠"),
            discord.SelectOption(label="📷 Камера", value="camera", emoji="📷"),
            discord.SelectOption(label="❌ Не иду", value="not_going", emoji="❌"),
        ],
        custom_id="event_rsvp_select",
    )
    async def rsvp_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        log.info("RSVP select: value=%s, user=%s (%s)", select.values[0], interaction.user, interaction.user.id)
        eid = await self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message(embed=style.error("Ивент не найден."), ephemeral=True)
        await self.rsvp(interaction, select.values[0], eid)

    @discord.ui.button(label="✏️ Редактировать", style=discord.ButtonStyle.secondary, custom_id="event_edit")
    async def edit_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        eid = await self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message(embed=style.error("Ивент не найден."), ephemeral=True)

        event = await _fetch_event(interaction.client.db, eid)
        if not event:
            return await interaction.response.send_message(embed=style.error("Ивент не найден."), ephemeral=True)

        creator_id = str(event.get("creator_id") or "")
        if str(interaction.user.id) != creator_id:
            return await interaction.response.send_message(
                embed=style.error("Только создатель ивента может его редактировать."), ephemeral=True
            )

        try:
            await interaction.user.send(
                "📝 **Редактирование ивента**\n\n"
                f"Ивент: **{event.get('name', '')}**"
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=style.error("❌ Не могу отправить ЛС. Открой личные сообщения."), ephemeral=True
            )

        await interaction.client.event_drafts.set(interaction.user.id, "edit", {
            "event_id": eid,
            "channel_id": interaction.message.channel.id,
            "message_id": interaction.message.id,
            "step": "choose_field",
        })
        await interaction.user.send(
            "Выбери поле для редактирования:",
            view=EventEditSelectView(interaction.user.id),
        )
        await interaction.response.send_message(embed=style.success("✅ Проверь ЛС!"), ephemeral=True)

    @discord.ui.button(label="🚫 Отменить ивент", style=discord.ButtonStyle.danger, custom_id="event_cancel")
    async def cancel_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        eid = await self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message(embed=style.error("Ивент не найден."), ephemeral=True)

        event = await _fetch_event(interaction.client.db, eid)
        if not event:
            return await interaction.response.send_message(
                embed=style.error("Ивент не найден."), ephemeral=True
            )

        creator_id = str(event.get("creator_id") or "")
        if str(interaction.user.id) != creator_id:
            return await interaction.response.send_message(
                embed=style.error("Только создатель ивента может его отменить."), ephemeral=True
            )

        await interaction.response.send_message(
            embed=style.warning("Вы уверены, что хотите отменить ивент?"),
            view=EventCancelConfirmView(
                eid,
                channel_id=interaction.message.channel.id,
                message_id=interaction.message.id,
            ),
            ephemeral=True
        )

    async def rsvp(self, interaction: discord.Interaction, key: str, eid: str):
        uid = str(interaction.user.id)
        db = interaction.client.db
        event = await _fetch_event(db, eid)
        log.info(
            "RSVP rsvp: event_id=%r, key=%s, user=%s, event_found=%s",
            eid, key, uid, event is not None
        )
        if not event:
            log.warning("RSVP rsvp: event not found! event_id=%r", eid)
            return await interaction.response.send_message(
                embed=style.error("Ивент не найден."), ephemeral=True
            )

        already_in = uid in event.get(key, [])

        for k in _RSVP_KEYS:
            if uid in event.get(k, []):
                event[k].remove(uid)

        if not already_in:
            event.setdefault(key, []).append(uid)

        await _save_rsvp(db, eid, event)

        embed = _build_event_embed(eid, event)
        try:
            await interaction.response.edit_message(embed=embed)
        except (discord.NotFound, discord.HTTPException) as e:
            log.info("RSVP edit_message пропущен (%s): %s", type(e).__name__, e)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        log.error("Ошибка в EventRSVPSelectView: %s", error, exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Произошла ошибка.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Произошла ошибка.", ephemeral=True)
        except Exception:
            log.warning("Не удалось ответить на ошибку EventRSVPSelectView", exc_info=True)


class EventCancelConfirmView(discord.ui.View):
    def __init__(self, event_id: str, channel_id: int = 0, message_id: int = 0):
        super().__init__(timeout=60)
        self.event_id = event_id
        self.channel_id = channel_id
        self.message_id = message_id

    @discord.ui.button(label="Да, отменить", style=discord.ButtonStyle.danger, custom_id="event_cancel_confirm2")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = interaction.client.db
        event = await _fetch_event(db, self.event_id)
        if not event:
            await interaction.response.edit_message(content="Ивент уже удалён.", view=None)
            return

        await db.execute("DELETE FROM events WHERE id = ?", (int(self.event_id),))

        if self.channel_id and self.message_id:
            channel = interaction.client.channel_of(self.channel_id)
            if channel:
                try:
                    msg = await channel.fetch_message(self.message_id)
                    if msg and msg.embeds:
                        embed = msg.embeds[0]
                        embed.title = f"{embed.title} — Отменён"
                        embed.color = discord.Color.red()
                        creator = event.get("creator_id") or 0
                        view = EventRSVPSelectView(
                            self.event_id, creator_id=int(creator) if str(creator).isdigit() else 0
                        )
                        for child in view.children:
                            child.disabled = True
                        await msg.edit(embed=embed, view=view)
                except discord.NotFound:
                    log.info("Отмена: сообщение ивента не найдено (удалено?)")
                except (discord.HTTPException, discord.Forbidden) as e:
                    log.info("Отмена: не удалось обновить эмбед (%s): %s", type(e).__name__, e)

        await interaction.response.edit_message(content="Ивент отменён.", view=None)

    @discord.ui.button(label="Нет, оставить", style=discord.ButtonStyle.secondary, custom_id="event_cancel_keep2")
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Ивент не отменён.", view=None)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        log.error("Ошибка в EventCancelConfirmView: %s", error, exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Произошла ошибка.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Произошла ошибка.", ephemeral=True)
        except Exception:
            log.warning("Не удалось ответить на ошибку EventCancelConfirmView", exc_info=True)


# ------------------------------------------------------------ напоминания

def _plural(n, one, few, many):
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


def _relative_str(dt, now):
    secs = (dt - now).total_seconds()
    mins = int(round(secs / 60))
    if mins >= 0:
        if mins == 0:
            return "прямо сейчас"
        if mins < 60:
            unit = _plural(mins, "минуту", "минуты", "минут")
            return f"через {mins} {unit}"
        hours = mins // 60
        if hours < 24:
            unit = _plural(hours, "час", "часа", "часов")
            return f"через {hours} {unit}"
        days = hours // 24
        unit = _plural(days, "день", "дня", "дней")
        return f"через {days} {unit}"
    if mins > -1:
        return "только что"
    mins = -mins
    if mins < 60:
        unit = _plural(mins, "минуту", "минуты", "минут")
        return f"{mins} {unit} назад"
    hours = mins // 60
    if hours < 24:
        unit = _plural(hours, "час", "часа", "часов")
        return f"{hours} {unit} назад"
    days = hours // 24
    unit = _plural(days, "день", "дня", "дней")
    return f"{days} {unit} назад"


# ------------------------------------------------------------ ког

class EventCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _reminder_text(self, name, label, dt, now):
        return f"🔔 {name} — {label} {_relative_str(dt, now)}!"

    async def cog_load(self) -> None:
        self.bot.scheduler.register_interval("event_reminder", self.event_reminder, seconds=60)

    @app_commands.command(name="event", description="Создать ивент через ЛС")
    async def event_cmd(self, interaction: discord.Interaction):
        try:
            await interaction.user.send(
                "📝 **Шаг 1/7 — Название события**\n"
                "Введите название:"
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=style.error("❌ Не могу отправить ЛС. Открой личные сообщения."), ephemeral=True
            )

        await self.bot.event_drafts.set(interaction.user.id, "create", {
            "channel_id": interaction.channel_id,
            "step": "name",
        })
        await interaction.response.send_message(embed=style.success("✅ Проверь ЛС!"), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return

        uid = message.author.id
        draft = await self.bot.event_drafts.get(uid)
        if not draft or not isinstance(draft[1], dict):
            return
        flow, payload = draft

        if flow == "edit":
            if payload.get("step") == "awaiting_value":
                await self._handle_edit_message(message, payload)
            return

        if flow == "create":
            await self._handle_create_message(message, payload)

    async def _handle_create_message(self, message: discord.Message, state: dict):
        uid = message.author.id
        text = message.content.strip()
        step = state.get("step")

        if step == "name":
            if not text:
                return await message.channel.send("❌ Название не может быть пустым. Попробуй ещё раз:")
            state["name"] = text
            state["step"] = "type"
            await self.bot.event_drafts.set(uid, "create", state)
            await message.channel.send(
                f"✅ Название: **{text}**\n\n"
                "📝 **Шаг 2/7 — Тип события**",
                view=EventTypeView(uid),
            )

        elif step == "description":
            state["description"] = text if text != "-" else ""
            state["step"] = "briefing"
            await self.bot.event_drafts.set(uid, "create", state)
            await message.channel.send(
                "✅ Описание сохранено.\n\n"
                "📢 **Шаг 4/7 — Время сбора / Briefing**\n"
                "Введите время сбора по МСК:\n\n"
                "Формат: ДД.ММ.ГГГГ ЧЧ:ММ (время МСК)\n"
                "Пример: 25.04.2026 19:00"
            )

        elif step == "briefing":
            if _parse_dt(text) is None:
                return await message.channel.send(
                    "❌ Неверный формат. Используй ДД.ММ.ГГГГ ЧЧ:ММ\n"
                    "Пример: 25.04.2026 19:00"
                )
            state["briefing"] = text
            state["step"] = "start"
            await self.bot.event_drafts.set(uid, "create", state)
            await message.channel.send(
                f"✅ Сбор: **{text} (МСК)**\n\n"
                "⏰ **Шаг 5/7 — Время начала / Start**\n"
                "Введите время начала по МСК:\n\n"
                "Формат: ДД.ММ.ГГГГ ЧЧ:ММ (время МСК)\n"
                "Пример: 25.04.2026 20:00"
            )

        elif step == "start":
            if _parse_dt(text) is None:
                return await message.channel.send(
                    "❌ Неверный формат. Используй ДД.ММ.ГГГГ ЧЧ:ММ\n"
                    "Пример: 25.04.2026 20:00"
                )
            state["start"] = text
            state["step"] = "image"
            await self.bot.event_drafts.set(uid, "create", state)
            await message.channel.send(
                f"✅ Начало: **{text} (МСК)**\n\n"
                "🖼 **Шаг 6/7 — Изображение**\n"
                "Прикрепите изображение или отправьте `-` чтобы пропустить."
            )

        elif step == "image":
            if text == "-":
                state["image_url"] = ""
            elif message.attachments:
                state["image_url"] = message.attachments[0].url
            else:
                return await message.channel.send(
                    "❌ Прикрепи изображение или отправь `-` чтобы пропустить."
                )
            state["step"] = "not_going"
            await self.bot.event_drafts.set(uid, "create", state)
            await message.channel.send(
                "✅ Изображение обработано.\n\n"
                "❌ **Шаг 7/7 — Кнопка 'Не иду'**\n"
                "Включить кнопку отказа?",
                view=NotGoingickerView(uid),
            )

    async def _handle_edit_message(self, message: discord.Message, state: dict):
        uid = message.author.id
        field = state.get("field")
        if field == "briefing" or field == "start":
            if _parse_dt(message.content.strip()) is None:
                return await message.channel.send(
                    "❌ Неверный формат. Используй ДД.ММ.ГГГГ ЧЧ:ММ\n"
                    "Пример: 25.04.2026 19:00"
                )
            state["new_value"] = message.content.strip()
        elif field == "image_url":
            if message.content.strip() == "-":
                state["new_value"] = ""
            elif message.attachments:
                state["new_value"] = message.attachments[0].url
            else:
                return await message.channel.send(
                    "❌ Прикрепи изображение или отправь `-` чтобы удалить."
                )
        else:
            value = message.content.strip()
            if field == "name" and not value:
                return await message.channel.send("❌ Название не может быть пустым.")
            state["new_value"] = value

        event = await _fetch_event(self.bot.db, state.get("event_id"))
        if not event:
            await message.channel.send("❌ Ивент не найден.")
            await self.bot.event_drafts.clear(uid)
            return

        await self.bot.event_drafts.set(uid, "edit", state)

        preview = discord.Embed(
            title="📋 Превью изменений",
            description=f"**{event['name']}**",
            color=discord.Color.blurple(),
        )
        field_labels = {
            "name": "Название",
            "description": "Описание",
            "briefing": "Время сбора",
            "start": "Время начала",
            "image_url": "Изображение",
        }
        display = state["new_value"] if state["new_value"] else "(пусто)"
        preview.add_field(name=field_labels.get(field, field), value=display, inline=False)
        await message.channel.send(
            embed=preview,
            view=EventEditConfirmView(uid),
        )

    async def event_reminder(self) -> None:
        try:
            rows = await self.bot.db.fetchall(f"SELECT {_EVENT_COLUMNS} FROM events")
            now = msk_now().replace(tzinfo=None)

            for row in rows:
                data = _row_to_event(row)
                event_id = row["id"]

                start_dt = _parse_dt(data.get("start"))
                if start_dt is None:
                    continue
                briefing_dt = _parse_dt(data.get("briefing")) or start_dt

                users = (
                    data.get("going_inf", [])
                    + data.get("going_tech", [])
                    + data.get("sl", [])
                    + data.get("camera", [])
                )
                mentions = " ".join(f"<@{uid}>" for uid in users)
                channel_id = data.get("channel_id")
                channel = self.bot.channel_of(channel_id) if channel_id else None

                briefing_diff = (briefing_dt - now).total_seconds() / 60
                start_diff = (start_dt - now).total_seconds() / 60

                if -1 <= briefing_diff <= 14 and not data["reminded_briefing_minus15"]:
                    if not users:
                        await self.bot.db.execute(
                            "UPDATE events SET reminded_briefing_minus15 = 1 WHERE id = ?",
                            (event_id,),
                        )
                    elif channel:
                        try:
                            text = self._reminder_text(
                                data["name"], "📢 Сбор / Briefing", briefing_dt, now
                            )
                            await channel.send(content=f"{mentions} {text}")
                            await self.bot.db.execute(
                                "UPDATE events SET reminded_briefing_minus15 = 1 WHERE id = ?",
                                (event_id,),
                            )
                        except Exception as e:
                            log.error("Ошибка напоминания (briefing -15): %s", e)

                if -1 <= briefing_diff <= 0 and not data["reminded_briefing"]:
                    if not users:
                        await self.bot.db.execute(
                            "UPDATE events SET reminded_briefing = 1 WHERE id = ?",
                            (event_id,),
                        )
                    elif channel:
                        try:
                            text = self._reminder_text(
                                data["name"], "📢 Сбор / Briefing", briefing_dt, now
                            )
                            await channel.send(content=f"{mentions} {text}")
                            await self.bot.db.execute(
                                "UPDATE events SET reminded_briefing = 1 WHERE id = ?",
                                (event_id,),
                            )
                        except Exception as e:
                            log.error("Ошибка напоминания (briefing): %s", e)

                if -1 <= start_diff <= 14 and not data["reminded_start_minus15"]:
                    if not users:
                        await self.bot.db.execute(
                            "UPDATE events SET reminded_start_minus15 = 1 WHERE id = ?",
                            (event_id,),
                        )
                    elif channel:
                        try:
                            text = self._reminder_text(
                                data["name"], "⏰ Начало / Start", start_dt, now
                            )
                            await channel.send(content=f"{mentions} {text}")
                            await self.bot.db.execute(
                                "UPDATE events SET reminded_start_minus15 = 1 WHERE id = ?",
                                (event_id,),
                            )
                        except Exception as e:
                            log.error("Ошибка напоминания (start -15): %s", e)

        except Exception:
            log.exception("Ошибка event_reminder")


async def setup(bot: commands.Bot):
    await bot.add_cog(EventCog(bot))
