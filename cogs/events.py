import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import send_log, load_events, save_events, build_event_embed
import config

import datetime
import logging
import uuid

import discord
from discord import app_commands
from discord.ext import commands, tasks


dm_event_states = {}
user_active_flow = {}


class EventTypeView(discord.ui.View):
    def __init__(self, user_id: int, flow_id: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.flow_id = flow_id

    def _state(self):
        state = dm_event_states.get(self.flow_id)
        if state and state.get("user_id") == self.user_id:
            return state
        return None

    @discord.ui.button(label="1 — Компетитив", style=discord.ButtonStyle.primary, custom_id="ev_type_comp")
    async def competitive(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Не для тебя.", ephemeral=True)
        state = self._state()
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)
        state["event_type"] = "competitive"
        state["step"] = "description"
        await interaction.response.edit_message(content="✅ Тип: **Компетитив**\n\n📝 Шаг 3/7 — Описание события\nВведите описание:", view=None)

    @discord.ui.button(label="2 — Свободная форма", style=discord.ButtonStyle.secondary, custom_id="ev_type_free")
    async def freeform(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Не для тебя.", ephemeral=True)
        state = self._state()
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)
        state["event_type"] = "freeform"
        state["step"] = "description"
        await interaction.response.edit_message(content="✅ Тип: **Свободная форма**\n\n📝 Шаг 3/7 — Описание события\nВведите описание:", view=None)


class NotGoingickerView(discord.ui.View):
    def __init__(self, user_id: int, flow_id: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.flow_id = flow_id

    def _state(self):
        state = dm_event_states.get(self.flow_id)
        if state and state.get("user_id") == self.user_id:
            return state
        return None

    @discord.ui.button(label="1 — Да", style=discord.ButtonStyle.success, custom_id="ev_notgoing_yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Не для тебя.", ephemeral=True)
        state = self._state()
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)
        state["show_not_going"] = True
        await self._finish_preview(interaction, state)

    @discord.ui.button(label="2 — Нет", style=discord.ButtonStyle.danger, custom_id="ev_notgoing_no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Не для тебя.", ephemeral=True)
        state = self._state()
        if not state:
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)
        state["show_not_going"] = False
        await self._finish_preview(interaction, state)

    async def _finish_preview(self, interaction: discord.Interaction, state):
        embed = self._build_preview(state)
        await interaction.response.edit_message(content="📋 **Превью события:**", embed=embed, view=PublishConfirmView(self.user_id, self.flow_id))

    def _build_preview(self, state):
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
    def __init__(self, user_id: int, flow_id: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.flow_id = flow_id

    def _clear_active(self):
        if user_active_flow.get(self.user_id) == self.flow_id:
            user_active_flow.pop(self.user_id, None)

    @discord.ui.button(label="1 — Да, опубликовать", style=discord.ButtonStyle.success, custom_id="ev_publish_yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Не для тебя.", ephemeral=True)
        state = dm_event_states.pop(self.flow_id, None)
        if not state or state.get("user_id") != self.user_id:
            self._clear_active()
            return await interaction.response.edit_message(content="❌ Состояние утеряно.", embed=None, view=None)

        channel = interaction.client.get_channel(state["channel_id"])
        if not channel:
            return await interaction.response.edit_message(content="❌ Канал не найден.", embed=None, view=None)

        event_id = str(interaction.id)
        events = load_events()
        events[event_id] = {
            "name": state["name"],
            "description": state.get("description", ""),
            "start": state["start"],
            "briefing": state["briefing"],
            "location": "",
            "going_inf": [],
            "going_tech": [],
            "maybe": [],
            "sl": [],
            "camera": [],
            "not_going": [],
            "show_not_going": state.get("show_not_going", False),
            "required": 0,
            "channel_id": state["channel_id"],
            "creator_id": self.user_id,
            "image_url": state.get("image_url", ""),
            "event_type": state.get("event_type", "freeform"),
        }
        save_events(events)

        embed = build_event_embed(event_id, events[event_id])
        view = EventRSVPView(event_id, creator_id=self.user_id)
        await channel.send(embed=embed, view=view)
        self._clear_active()
        await interaction.response.edit_message(content="✅ **Ивент опубликован!**", embed=None, view=None)

    @discord.ui.button(label="2 — Нет, отменить", style=discord.ButtonStyle.danger, custom_id="ev_publish_no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Не для тебя.", ephemeral=True)
        dm_event_states.pop(self.flow_id, None)
        self._clear_active()
        await interaction.response.edit_message(content="❌ Создание ивента отменено.", embed=None, view=None)


class EventRSVPView(discord.ui.View):
    def __init__(self, event_id: str, creator_id: int = 0):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.creator_id = creator_id

    def _get_event_id(self, interaction: discord.Interaction) -> str | None:
        msg = interaction.message
        if msg and msg.embeds:
            footer = msg.embeds[0].footer.text or ""
            logging.info("_get_event_id: footer=%r, embed title=%r", footer, msg.embeds[0].title)
            if footer.startswith("ID: "):
                return footer[4:]
            title = msg.embeds[0].title or ""
            if title:
                events = load_events()
                for eid, data in events.items():
                    if data.get("name") == title:
                        return eid
        else:
            logging.warning("_get_event_id: no embeds on message. msg=%s", msg)
        return None

    @discord.ui.button(label="🪖 Иду (пех)", style=discord.ButtonStyle.success, custom_id="event_going_inf")
    async def going_inf(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info("RSVP button: going_inf, user=%s (%s)", interaction.user, interaction.user.id)
        eid = self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message("Ивент не найден.", ephemeral=True)
        await self.rsvp(interaction, "going_inf", eid)

    @discord.ui.button(label="🚜 Иду (тех)", style=discord.ButtonStyle.success, custom_id="event_going_tech")
    async def going_tech(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info("RSVP button: going_tech, user=%s (%s)", interaction.user, interaction.user.id)
        eid = self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message("Ивент не найден.", ephemeral=True)
        await self.rsvp(interaction, "going_tech", eid)

    @discord.ui.button(label="🤔 Возможно", style=discord.ButtonStyle.primary, custom_id="event_maybe")
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        eid = self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message("Ивент не найден.", ephemeral=True)
        await self.rsvp(interaction, "maybe", eid)

    @discord.ui.button(label="🟠 SL", style=discord.ButtonStyle.secondary, custom_id="event_sl")
    async def sl(self, interaction: discord.Interaction, button: discord.ui.Button):
        eid = self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message("Ивент не найден.", ephemeral=True)
        await self.rsvp(interaction, "sl", eid)

    @discord.ui.button(label="📷 Камера", style=discord.ButtonStyle.secondary, custom_id="event_camera")
    async def camera(self, interaction: discord.Interaction, button: discord.ui.Button):
        eid = self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message("Ивент не найден.", ephemeral=True)
        await self.rsvp(interaction, "camera", eid)

    @discord.ui.button(label="❌ Не иду", style=discord.ButtonStyle.danger, custom_id="event_not_going")
    async def not_going(self, interaction: discord.Interaction, button: discord.ui.Button):
        eid = self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message("Ивент не найден.", ephemeral=True)
        await self.rsvp(interaction, "not_going", eid)

    @discord.ui.button(label="🚫 Отменить ивент", style=discord.ButtonStyle.danger, custom_id="event_cancel")
    async def cancel_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        eid = self._get_event_id(interaction)
        if not eid:
            return await interaction.response.send_message("Ивент не найден.", ephemeral=True)

        events = load_events()
        event = events.get(eid)
        if not event:
            return await interaction.response.send_message(
                "Ивент не найден.", ephemeral=True
            )

        creator_id = str(event.get("creator_id") or "")
        if str(interaction.user.id) != creator_id:
            return await interaction.response.send_message(
                "Только создатель ивента может его отменить.", ephemeral=True
            )

        await interaction.response.send_message(
            "Вы уверены, что хотите отменить ивент?",
            view=EventCancelConfirmView(
                eid,
                channel_id=interaction.message.channel.id,
                message_id=interaction.message.id,
            ),
            ephemeral=True
        )

    async def rsvp(self, interaction: discord.Interaction, key: str, eid: str):
        uid = str(interaction.user.id)
        events = load_events()
        event = events.get(eid)
        logging.info(
            "RSVP rsvp: event_id=%r, key=%s, user=%s, event_found=%s",
            eid, key, uid, event is not None
        )
        if not event:
            logging.warning(
                "RSVP rsvp: event not found! event_id=%r, available=%s",
                eid, list(events.keys())
            )
            return await interaction.response.send_message(
                "Ивент не найден.", ephemeral=True
            )

        already_in = uid in event.get(key, [])

        for k in ("going_inf", "going_tech", "maybe", "sl", "camera", "not_going"):
            if uid in event.get(k, []):
                event[k].remove(uid)

        if not already_in:
            event.setdefault(key, []).append(uid)

        save_events(events)

        embed = build_event_embed(eid, event)
        try:
            await interaction.response.edit_message(embed=embed)
        except (discord.NotFound, discord.HTTPException) as e:
            logging.info("RSVP edit_message пропущен (%s): %s", type(e).__name__, e)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        logging.error("Ошибка в EventRSVPView: %s", error, exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Произошла ошибка.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Произошла ошибка.", ephemeral=True)
        except Exception:
            pass


class EventCancelConfirmView(discord.ui.View):
    def __init__(self, event_id: str, channel_id: int = 0, message_id: int = 0):
        super().__init__(timeout=60)
        self.event_id = event_id
        self.channel_id = channel_id
        self.message_id = message_id

    @discord.ui.button(label="Да, отменить", style=discord.ButtonStyle.danger, custom_id="event_cancel_confirm2")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        events = load_events()
        event = events.pop(self.event_id, None)
        if not event:
            await interaction.response.edit_message(content="Ивент уже удалён.", view=None)
            return

        save_events(events)

        if self.channel_id and self.message_id:
            channel = interaction.client.get_channel(self.channel_id)
            if channel:
                try:
                    msg = await channel.fetch_message(self.message_id)
                    if msg and msg.embeds:
                        embed = msg.embeds[0]
                        embed.title = f"{embed.title} — Отменён"
                        embed.color = discord.Color.red()
                        view = EventRSVPView(self.event_id, creator_id=event.get("creator_id") or 0)
                        for child in view.children:
                            child.disabled = True
                        await msg.edit(embed=embed, view=view)
                except discord.NotFound:
                    logging.info("Отмена: сообщение ивента не найдено (удалено?)")
                except (discord.HTTPException, discord.Forbidden) as e:
                    logging.info("Отмена: не удалось обновить эмбед (%s): %s", type(e).__name__, e)

        await interaction.response.edit_message(content="Ивент отменён.", view=None)

    @discord.ui.button(label="Нет, оставить", style=discord.ButtonStyle.secondary, custom_id="event_cancel_keep2")
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Ивент не отменён.", view=None)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        logging.error("Ошибка в EventCancelConfirmView: %s", error, exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Произошла ошибка.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Произошла ошибка.", ephemeral=True)
        except Exception:
            pass


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


class EventCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _reminder_text(self, name, label, dt, now):
        return f"🔔 {name} — {label} {_relative_str(dt, now)}!"

    async def cog_load(self):
        self.event_reminder.start()

    @app_commands.command(name="event", description="Создать ивент через ЛС")
    async def event_cmd(self, interaction: discord.Interaction):
        try:
            await interaction.user.send(
                "📝 **Шаг 1/7 — Название события**\n"
                "Введите название:"
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ Не могу отправить ЛС. Открой личные сообщения.", ephemeral=True
            )

        flow_id = uuid.uuid4().hex
        dm_event_states[flow_id] = {
            "user_id": interaction.user.id,
            "channel_id": interaction.channel.id,
            "step": "name",
        }
        user_active_flow[interaction.user.id] = flow_id
        await interaction.response.send_message("✅ Проверь ЛС!", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return

        uid = message.author.id
        flow_id = user_active_flow.get(uid)
        state = dm_event_states.get(flow_id) if flow_id else None
        if not state or state.get("user_id") != uid:
            return

        step = state["step"]
        text = message.content.strip()

        if step == "name":
            if not text:
                return await message.channel.send("❌ Название не может быть пустым. Попробуй ещё раз:")
            state["name"] = text
            state["step"] = "type"
            await message.channel.send(
                f"✅ Название: **{text}**\n\n"
                "📝 **Шаг 2/7 — Тип события**",
                view=EventTypeView(uid, flow_id),
            )

        elif step == "description":
            state["description"] = text if text != "-" else ""
            state["step"] = "briefing"
            await message.channel.send(
                "✅ Описание сохранено.\n\n"
                "📢 **Шаг 4/7 — Время сбора / Briefing**\n"
                "Введите время сбора по МСК:\n\n"
                "Формат: ДД.ММ.ГГГГ ЧЧ:ММ (время МСК)\n"
                "Пример: 25.04.2026 19:00"
            )

        elif step == "briefing":
            try:
                datetime.datetime.strptime(text, "%d.%m.%Y %H:%M")
            except ValueError:
                return await message.channel.send(
                    "❌ Неверный формат. Используй ДД.ММ.ГГГГ ЧЧ:ММ\n"
                    "Пример: 25.04.2026 19:00"
                )
            state["briefing"] = text
            state["step"] = "start"
            await message.channel.send(
                f"✅ Сбор: **{text} (МСК)**\n\n"
                "⏰ **Шаг 5/7 — Время начала / Start**\n"
                "Введите время начала по МСК:\n\n"
                "Формат: ДД.ММ.ГГГГ ЧЧ:ММ (время МСК)\n"
                "Пример: 25.04.2026 20:00"
            )

        elif step == "start":
            try:
                datetime.datetime.strptime(text, "%d.%m.%Y %H:%M")
            except ValueError:
                return await message.channel.send(
                    "❌ Неверный формат. Используй ДД.ММ.ГГГГ ЧЧ:ММ\n"
                    "Пример: 25.04.2026 20:00"
                )
            state["start"] = text
            state["step"] = "image"
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
            await message.channel.send(
                "✅ Изображение обработано.\n\n"
                "❌ **Шаг 7/7 — Кнопка 'Не иду'**\n"
                "Включить кнопку отказа?",
                view=NotGoingickerView(uid, flow_id),
            )

    @tasks.loop(minutes=1)
    async def event_reminder(self):
        try:
            events = load_events()
            now = datetime.datetime.now()
            changed = False

            for event_id, data in events.items():
                try:
                    start_str = data.get("start") or f"{data.get('date', '')} {data.get('time', '')}"
                    start_dt = datetime.datetime.strptime(
                        start_str, "%d.%m.%Y %H:%M"
                    )
                except ValueError:
                    continue

                briefing_str = data.get("briefing") or start_str
                try:
                    briefing_dt = datetime.datetime.strptime(
                        briefing_str, "%d.%m.%Y %H:%M"
                    )
                except ValueError:
                    briefing_dt = start_dt

                users = (
                    data.get("going_inf", [])
                    + data.get("going_tech", [])
                    + data.get("going", [])
                    + data.get("sl", [])
                    + data.get("camera", [])
                )
                mentions = " ".join(f"<@{uid}>" for uid in users)
                channel_id = data.get("channel_id")
                channel = self.bot.get_channel(channel_id) if channel_id else None

                briefing_diff = (briefing_dt - now).total_seconds() / 60
                start_diff = (start_dt - now).total_seconds() / 60

                if -1 <= briefing_diff <= 14 and not data.get("reminded_briefing_minus15"):
                    if not users:
                        data["reminded_briefing_minus15"] = True
                        changed = True
                    elif channel:
                        try:
                            text = self._reminder_text(
                                data["name"], "📢 Сбор / Briefing", briefing_dt, now
                            )
                            await channel.send(content=f"{mentions} {text}")
                            data["reminded_briefing_minus15"] = True
                            changed = True
                        except Exception as e:
                            logging.error("Ошибка напоминания (briefing -15): %s", e)

                if -1 <= briefing_diff <= 0 and not data.get("reminded_briefing"):
                    if not users:
                        data["reminded_briefing"] = True
                        changed = True
                    elif channel:
                        try:
                            text = self._reminder_text(
                                data["name"], "📢 Сбор / Briefing", briefing_dt, now
                            )
                            await channel.send(content=f"{mentions} {text}")
                            data["reminded_briefing"] = True
                            changed = True
                        except Exception as e:
                            logging.error("Ошибка напоминания (briefing): %s", e)

                if -1 <= start_diff <= 14 and not data.get("reminded_start_minus15"):
                    if not users:
                        data["reminded_start_minus15"] = True
                        changed = True
                    elif channel:
                        try:
                            text = self._reminder_text(
                                data["name"], "⏰ Начало / Start", start_dt, now
                            )
                            await channel.send(content=f"{mentions} {text}")
                            data["reminded_start_minus15"] = True
                            changed = True
                        except Exception as e:
                            logging.error("Ошибка напоминания (start -15): %s", e)

            if changed:
                save_events(events)

        except Exception as e:
            logging.error("Ошибка event_reminder: %s", e, exc_info=True)

    @event_reminder.before_loop
    async def before_event_reminder(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(EventCog(bot))
