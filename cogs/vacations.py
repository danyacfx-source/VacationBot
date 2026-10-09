"""Система отпусков: заявки, продление, снятие, панель и напоминания."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.timeutil import msk_now, parse_date
from services.notify import send_vacation_log
from services.vacation import (
    build_info_panel_embed,
    build_request_panel_embed,
    refresh_panels,
)
from ui import style

log = logging.getLogger(__name__)

NOTIFIED_KEY = "vacation_return_notified"


def _has_panel_role(member: discord.Member) -> bool:
    return any(role.id == config.VACATION_PANEL_ROLE for role in member.roles)


async def _require_panel_role(interaction: discord.Interaction) -> bool:
    if _has_panel_role(interaction.user):
        return True
    await interaction.response.send_message(
        embed=style.error("Нет доступа", "У вас нет роли для этой кнопки."),
        ephemeral=True,
    )
    return False


async def _apply_vacation_role(member: discord.Member, guild: discord.Guild, *, grant: bool) -> None:
    role = guild.get_role(config.VACATION_ROLE)
    if role is None:
        return
    try:
        if grant and role not in member.roles:
            await member.add_roles(role, reason="Одобрена заявка на отпуск")
        elif not grant and role in member.roles:
            await member.remove_roles(role, reason="Отпуск снят")
    except discord.HTTPException as exc:
        log.warning("Не удалось изменить роль отпуска у %s: %s", member, exc)


class VacationModal(discord.ui.Modal, title="Заявка на отпуск"):
    start_date = discord.ui.TextInput(
        label="Дата начала (ДД.ММ.ГГГГ)",
        placeholder="25.07.2026",
        required=True,
        max_length=10,
    )
    end_date = discord.ui.TextInput(
        label="Дата окончания (ДД.ММ.ГГГГ)",
        placeholder="10.08.2026",
        required=True,
        max_length=10,
    )
    reason = discord.ui.TextInput(
        label="Причина",
        placeholder="Укажите причину отпуска",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        start = parse_date(self.start_date.value)
        if start is None:
            await interaction.response.send_message(
                embed=style.error("Неверная дата", "Формат даты начала: ДД.ММ.ГГГГ."),
                ephemeral=True,
            )
            return

        end = parse_date(self.end_date.value)
        if end is None:
            await interaction.response.send_message(
                embed=style.error("Неверная дата", "Формат даты окончания: ДД.ММ.ГГГГ."),
                ephemeral=True,
            )
            return

        if end < start:
            await interaction.response.send_message(
                embed=style.error("Неверные даты", "Окончание не может быть раньше начала."),
                ephemeral=True,
            )
            return

        reason = self.reason.value.strip()
        bot = interaction.client
        await bot.vacations.add_period(
            user_id=interaction.user.id,
            user_name=str(interaction.user),
            start_date=start.strftime("%d.%m.%Y"),
            end_date=end.strftime("%d.%m.%Y"),
            reason=reason,
        )

        if interaction.guild is not None:
            await _apply_vacation_role(interaction.user, interaction.guild, grant=True)

        days = (end - start).days + 1
        await interaction.response.send_message(
            embed=style.success(
                "✅ Отпуск одобрен",
                f"📅 С **{start.strftime('%d.%m.%Y')}** по **{end.strftime('%d.%m.%Y')}** ({days} дн.)",
            ),
            ephemeral=True,
        )

        await send_vacation_log(
            bot,
            "🏖️ Отпуск одобрен",
            f"**Пользователь:** {interaction.user.mention}\n"
            f"**Период:** {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')} ({days} дн.)\n"
            f"**Причина:** {reason}",
        )
        await refresh_panels(bot)


class VacationExtendModal(discord.ui.Modal, title="Продление отпуска"):
    extra_days = discord.ui.TextInput(
        label="Дополнительные дни",
        placeholder="3",
        required=True,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            extra = int(self.extra_days.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Количество дней должно быть числом."),
                ephemeral=True,
            )
            return

        if extra <= 0:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Количество дней должно быть больше нуля."),
                ephemeral=True,
            )
            return

        bot = interaction.client
        record = await bot.vacations.get_user(interaction.user.id)
        if not record:
            await interaction.response.send_message(
                embed=style.error("Нет отпуска", "У вас нет активного отпуска."),
                ephemeral=True,
            )
            return

        now = msk_now()
        target = None
        for period in record["periods"]:
            end = parse_date(period.get("end_date", ""))
            if end is not None and end.date() >= now.date():
                target = period
                break

        if target is None:
            await interaction.response.send_message(
                embed=style.error("Нет текущего отпуска", "Продлить нечего."),
                ephemeral=True,
            )
            return

        old_end = parse_date(target["end_date"])
        if old_end is None:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Не удалось прочитать дату окончания."),
                ephemeral=True,
            )
            return

        new_end = old_end + timedelta(days=extra)
        await bot.vacations.extend_period(
            interaction.user.id, target.get("start_date", ""), new_end.strftime("%d.%m.%Y")
        )

        await interaction.response.send_message(
            embed=style.success(
                "🔄 Отпуск продлён",
                f"Продление на **{extra}** дн.\n"
                f"📅 Новая дата окончания: **{new_end.strftime('%d.%m.%Y')}**",
            ),
            ephemeral=True,
        )

        await send_vacation_log(
            bot,
            "🔄 Отпуск продлён",
            f"**Пользователь:** {interaction.user.mention}\n"
            f"**Продление:** {extra} дн.\n"
            f"**Новая дата окончания:** {new_end.strftime('%d.%m.%Y')}",
        )
        await refresh_panels(bot)


async def _show_status(bot, user: discord.abc.User, record: dict | None) -> discord.Embed:
    embed = style.base("🏖️ Ваши отпуска", color=discord.Color.blue())
    if not record:
        embed.description = "У вас нет отпусков."
        return embed
    for index, period in enumerate(record.get("periods", []), start=1):
        embed.add_field(
            name=f"Период {index}",
            value=(
                f"📅 {period.get('start_date', '—')} — {period.get('end_date', '—')}\n"
                f"📝 {period.get('reason', '—')}"
            ),
            inline=False,
        )
    return embed


async def _cancel_all(bot, user: discord.Member, guild: discord.Guild | None) -> int:
    removed = await bot.vacations.remove_user(user.id)
    if guild is not None:
        await _apply_vacation_role(user, guild, grant=False)
    return removed


class LegacyVacationPanelView(discord.ui.View):
    """Старая панель из трёх кнопок — сообщения на сервере продолжают работать."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Заявка на отпуск",
        style=discord.ButtonStyle.green,
        custom_id="vacation_panel_request",
    )
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _require_panel_role(interaction):
            return
        await interaction.response.send_modal(VacationModal())

    @discord.ui.button(
        label="Статус отпуска",
        style=discord.ButtonStyle.blurple,
        custom_id="vacation_panel_status",
    )
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _require_panel_role(interaction):
            return
        record = await interaction.client.vacations.get_user(interaction.user.id)
        if not record:
            await interaction.response.send_message(
                embed=style.error("Нет отпусков", "У вас нет отпусков."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=await _show_status(interaction.client, interaction.user, record), ephemeral=True
        )

    @discord.ui.button(
        label="Отменить отпуск",
        style=discord.ButtonStyle.red,
        custom_id="vacation_panel_cancel",
    )
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _require_panel_role(interaction):
            return
        bot = interaction.client
        if not await bot.vacations.get_user(interaction.user.id):
            await interaction.response.send_message(
                embed=style.error("Нет отпусков", "У вас нет отпусков."), ephemeral=True
            )
            return
        removed = await _cancel_all(bot, interaction.user, interaction.guild)
        await interaction.response.send_message(
            embed=style.success("✅ Отменено", f"Снято период(ов): **{removed}**."), ephemeral=True
        )
        await refresh_panels(bot)


class RequestPanelView(discord.ui.View):
    """Основная панель отпусков: заявка, статус, продление, снятие."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📝 Взять отпуск",
        style=discord.ButtonStyle.green,
        custom_id="vacation_request_btn",
    )
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _require_panel_role(interaction):
            return
        await interaction.response.send_modal(VacationModal())

    @discord.ui.button(
        label="📋 Статус",
        style=discord.ButtonStyle.blurple,
        custom_id="vacation_my_status",
    )
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _require_panel_role(interaction):
            return
        record = await interaction.client.vacations.get_user(interaction.user.id)
        if not record:
            await interaction.response.send_message(
                embed=style.error("Нет отпусков", "У вас нет отпусков."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=await _show_status(interaction.client, interaction.user, record), ephemeral=True
        )

    @discord.ui.button(
        label="🔄 Продлить отпуск",
        style=discord.ButtonStyle.success,
        custom_id="vacation_extend_btn",
    )
    async def extend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _require_panel_role(interaction):
            return
        await interaction.response.send_modal(VacationExtendModal())

    @discord.ui.button(
        label="❌ Снять отпуск",
        style=discord.ButtonStyle.red,
        custom_id="vacation_cancel_btn",
    )
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _require_panel_role(interaction):
            return
        bot = interaction.client
        if not await bot.vacations.get_user(interaction.user.id):
            await interaction.response.send_message(
                embed=style.error("Нет отпусков", "У вас нет отпусков."), ephemeral=True
            )
            return

        removed = await _cancel_all(bot, interaction.user, interaction.guild)
        await interaction.response.send_message(
            embed=style.success("✅ Снято", f"Периодов отпуска снято: **{removed}**."),
            ephemeral=True,
        )
        await send_vacation_log(
            bot,
            "❌ Отпуск снят",
            f"**Пользователь:** {interaction.user.mention} снял {removed} период(ов) отпуска.",
        )
        await refresh_panels(bot)


class VacationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.scheduler.register_daily(
            "vacation_return",
            self.check_overdue_vacations,
            hour=config.VACATION_RETURN_HOUR,
            minute=0,
            catch_up=True,
            window_minutes=10,
        )

    # ------------------------------------------------------------ команды

    @app_commands.command(name="vacation_panel", description="Отправить панель отпусков")
    @app_commands.default_permissions(administrator=True)
    async def vacation_panel(self, interaction: discord.Interaction) -> None:
        data = await self.bot.vacations.list_all()
        info_embed = build_info_panel_embed(data)
        await interaction.response.send_message(embed=info_embed)
        info_message = await interaction.original_response()

        request_message = await interaction.followup.send(
            embed=build_request_panel_embed(), view=RequestPanelView(), wait=True
        )

        await self.bot.vacations.set_panel(
            channel_id=interaction.channel_id,
            info_message_id=info_message.id,
            request_message_id=request_message.id,
        )
        await interaction.followup.send(
            embed=style.success("✅ Панель развёрнута"), ephemeral=True
        )

    @app_commands.command(name="vacation_list", description="Показать все отпуска")
    @app_commands.default_permissions(administrator=True)
    async def vacation_list(self, interaction: discord.Interaction) -> None:
        data = await self.bot.vacations.list_all()
        if not data:
            await interaction.response.send_message(
                embed=style.info("📋 Отпусков нет"), ephemeral=True
            )
            return

        embed = style.base("📋 Все отпуска", color=discord.Color.blue())
        for uid, record in data.items():
            name = record.get("user_name") or f"ID: {uid}"
            periods = record.get("periods", [])
            lines = [
                f"📅 {p.get('start_date', '—')} — {p.get('end_date', '—')}\n"
                f"📝 {p.get('reason', '—')}"
                for p in periods
            ]
            style.field(embed, name, "\n\n".join(lines) if lines else "Нет периодов")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="vacation_remove", description="Снять отпуск у участника")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user="Участник, у которого снять отпуск")
    async def vacation_remove(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not await self.bot.vacations.get_user(user.id):
            await interaction.response.send_message(
                embed=style.error("Нет отпусков", f"У {user.mention} нет отпусков."),
                ephemeral=True,
            )
            return

        removed = await _cancel_all(self.bot, user, interaction.guild)
        await interaction.response.send_message(
            embed=style.success(
                "✅ Отпуск снят", f"Все отпуски ({removed} период(ов)) у {user.mention} сняты."
            ),
            ephemeral=True,
        )
        await send_vacation_log(
            self.bot,
            "🗑️ Отпуск снят (вручную)",
            f"**Пользователь:** {user.mention}\n"
            f"**Снял:** {interaction.user.mention}\n"
            f"**Количество периодов:** {removed}",
            color=discord.Color.red(),
        )
        await refresh_panels(self.bot)

    # ------------------------------------------------------------ фоновое задание

    async def check_overdue_vacations(self) -> None:
        """Пингует роли о просроченных отпусках (≥5 дней), один раз за период."""
        now = msk_now()
        data = await self.bot.vacations.list_all()
        notified: list[str] = await self.bot.state.get(NOTIFIED_KEY, [])
        if not isinstance(notified, list):
            notified = []
        notified_set = set(notified)

        channel = self.bot.channel_of(config.VACATION_RETURN_CHANNEL)
        if channel is None:
            return

        changed = False
        for uid, record in data.items():
            user_name = record.get("user_name") or f"<@{uid}>"
            for period in record.get("periods", []):
                end = parse_date(period.get("end_date", ""))
                if end is None:
                    continue
                overdue = (now.date() - end.date()).days
                if overdue < 5:
                    continue

                key = f"{uid}_{period.get('end_date', '')}"
                if key in notified_set:
                    continue

                try:
                    pings = " ".join(f"<@&{role_id}>" for role_id in config.VACATION_PING_ROLES)
                    await channel.send(
                        f"{pings}\n"
                        f"⚠️ **{user_name}** — отпуск истёк **{overdue}** дн. назад "
                        f"(дата окончания: {period.get('end_date', '')})."
                    )
                except discord.HTTPException as exc:
                    log.warning("Не удалось отправить напоминание об отпуске: %s", exc)
                    continue

                notified_set.add(key)
                changed = True

        if changed:
            await self.bot.state.set(NOTIFIED_KEY, sorted(notified_set))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VacationCog(bot))
