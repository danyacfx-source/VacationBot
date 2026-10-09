"""Заявки в клан: панель, создание, закрытие, транскрипт (без approve/reject)."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.timeutil import msk_utcnow
from services.notify import _send as _notify_send
from services.transcripts import (
    delete_ticket,
    fetch_ticket,
    find_open_ticket,
    save_ticket,
    send_transcript,
    update_ticket,
)
from ui import style

log = logging.getLogger(__name__)

CLAN_APPLICATION_FORM = (
    "**Пожалуйста, ответьте на вопросы:**\n\n"
    "**1.** Сколько часов в игре?\n"
    "**2.** Для чего вы хотите вступить в клан?\n"
    "**3.** Откуда вы узнали о GMS?\n"
    "**4.** Сколько вам лет?\n"
    "**5.** Какой у вас часовой пояс?\n"
    "**6.** Какой у вас средний онлайн в неделю?"
)

CLAN_PANEL_DESCRIPTION = (
    "🗓️ Возраст - от 16 лет\n"
    "🧘 Адекватность, стрессоустойчивость, спокойствие в критических ситуациях\n"
    "🎙️ Наличие микрофона - обязательно.\n\n"
    "🤝 Взаимный опыт\n"
    "😊 Приятная атмосфера\n"
    "🎮 Помощь в освоении механик игры\n\n"
    "💎 P.S. В будущем будет VIP на сервера, которые приглядутся"
)

CLAN_TICKET_TYPE = "clan"


async def _clan_log(bot, title: str, description: str, color: discord.Color | None = None) -> None:
    """Клановый тикет-лог идёт в свой канал (см. config.CLAN_TICKET_LOG_CHANNEL)."""
    await _notify_send(
        bot,
        config.CLAN_TICKET_LOG_CHANNEL,
        title,
        description,
        color or discord.Color.blue(),
    )


class ClanTicketPanelView(discord.ui.View):
    """Persistent-панель регистрации клана."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Подать заявку в клан", style=discord.ButtonStyle.primary, custom_id="ck_create", emoji="📝")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction)

    async def _create_ticket(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client

        if await find_open_ticket(bot, interaction.user.id, CLAN_TICKET_TYPE):
            return await interaction.followup.send(
                embed=style.warning(
                    "⏳ Заявка уже открыта",
                    "У вас уже есть открытая заявка в клан.",
                ),
                ephemeral=True,
            )

        guild = interaction.guild
        user = interaction.user
        category = guild.get_channel(config.TICKET_CATEGORY)
        if not category:
            return await interaction.followup.send(
                embed=style.error("Ошибка", "❌ Категория тикетов не настроена."),
                ephemeral=True,
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True,
            ),
        }
        staff_role = guild.get_role(config.TICKET_STAFF_ROLE)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        try:
            channel = await guild.create_text_channel(
                name=f"клан-{user.name}",
                category=category,
                overwrites=overwrites,
                topic=f"Заявка в клан от {user} ({user.id})",
            )
        except discord.HTTPException as e:
            log.warning("Ошибка создания кланового тикета для %s: %s", user, e)
            return await interaction.followup.send(
                embed=style.error("Ошибка", "❌ Не удалось создать заявку (ошибка Discord)."),
                ephemeral=True,
            )
        except Exception as e:
            log.exception("Непредвиденная ошибка создания кланового тикета: %s", e)
            return await interaction.followup.send(
                embed=style.error("Ошибка", "❌ Не удалось создать заявку."),
                ephemeral=True,
            )

        embed = style.base(
            "📝 ЗАЯВКА В КЛАН",
            CLAN_APPLICATION_FORM,
            color=discord.Color.gold(),
            footer=f"ID: {user.id}",
            timestamp=True,
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

        staff_mention = f"<@&{config.TICKET_STAFF_ROLE}>"
        try:
            await channel.send(
                content=f"{staff_mention} {user.mention}",
                embed=embed,
                view=ClanTicketCloseView(),
            )
        except discord.HTTPException as exc:
            log.error("Не удалось отправить сообщение в заявку %s: %s", channel.name, exc)

        await save_ticket(
            bot,
            {
                "user_id": user.id,
                "channel_id": channel.id,
                "type": CLAN_TICKET_TYPE,
                "status": "open",
                "created_at": msk_utcnow().isoformat(timespec="seconds"),
                "guild_id": guild.id,
            },
        )

        await interaction.followup.send(
            embed=style.success("📝 Заявка в клан", f"Заявка в клан создана: {channel.mention}"),
            ephemeral=True,
        )

        await _clan_log(
            bot,
            "📝 Заявка в клан",
            f"**Тикет:** {channel.mention}\n**Пользователь:** {user}",
        )


class ClanTicketCloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Да", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        channel = interaction.channel
        bot = interaction.client
        ticket_data = await fetch_ticket(bot, channel.id)

        if ticket_data:
            await update_ticket(
                bot,
                channel.id,
                status="closed",
                closed_at=msk_utcnow().isoformat(timespec="seconds"),
                closed_by=interaction.user.id,
            )

            creator_id = ticket_data.get("user_id")
            if creator_id:
                member = channel.guild.get_member(int(creator_id))
                if member:
                    try:
                        await channel.set_permissions(member, overwrite=None)
                    except discord.HTTPException as exc:
                        log.error("Не удалось снять права %s в заявке: %s", member, exc)

            staff_role = channel.guild.get_role(config.TICKET_STAFF_ROLE)
            try:
                await channel.set_permissions(
                    channel.guild.default_role, view_channel=False
                )
                if staff_role:
                    await channel.set_permissions(
                        staff_role,
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True,
                    )
            except discord.HTTPException as exc:
                log.error("Не удалось обновить права заявки %s: %s", channel.name, exc)

        embed = style.base(
            "Заявка закрыта",
            f"Закрыл: {interaction.user.mention}\nСохраните транскрипт или удалите канал.",
            color=style.NEUTRAL,
            footer=None,
        )
        await interaction.message.edit(embed=embed, view=ClanTicketClosedView())

        await _clan_log(
            bot,
            "📝 Заявка в клан закрыта",
            f"**Тикет:** {channel.mention}\n**Закрыл:** {interaction.user}",
        )

    @discord.ui.button(label="Нет", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=style.info("Отменено", "Закрытие отменено."),
            view=None,
        )


class ClanTicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Закрыть заявку", style=discord.ButtonStyle.red, custom_id="ck_close", emoji="🔒")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=style.warning("🔒 Закрытие заявки", "Вы уверены?"),
            view=ClanTicketCloseConfirmView(),
        )


class ClanTicketClosedView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Удалить канал", style=discord.ButtonStyle.danger, custom_id="ck_delete", emoji="🗑️")
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        bot = interaction.client
        ticket_data = await fetch_ticket(bot, interaction.channel.id)

        if ticket_data:
            is_owner = interaction.user.id == ticket_data.get("user_id")
            is_staff = interaction.user.guild_permissions.manage_channels
            if not is_owner and not is_staff:
                return await interaction.followup.send(
                    embed=style.error("Нет доступа", "❌ Вы не можете удалить этот тикет."),
                    ephemeral=True,
                )

        await delete_ticket(bot, interaction.channel.id)

        await _clan_log(
            bot,
            "🗑️ Клановый тикет удалён",
            f"**Канал:** {interaction.channel.name}\n**Удалил:** {interaction.user}",
        )

        try:
            await interaction.channel.delete()
        except discord.HTTPException as exc:
            log.error(
                "Не удалось удалить канал кланового тикета %s: %s",
                interaction.channel.name,
                exc,
            )
            await interaction.followup.send(
                embed=style.error("Ошибка", "Не удалось удалить канал."),
                ephemeral=True,
            )

    @discord.ui.button(label="Сохранить транскрипт", style=discord.ButtonStyle.blurple, custom_id="ck_transcript", emoji="📄")
    async def save_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        await send_transcript(
            interaction,
            prefix="clan",
            transcript_channel_id=config.TICKET_TRANSCRIPT_CHANNEL,
            message_fields=False,
            fallback_file=True,
            ephemeral=True,
        )


class ClanTicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    clan_group = app_commands.Group(name="clan", description="Управление заявками в клан")

    @clan_group.command(name="panel", description="Отправить панель заявок в клан")
    @app_commands.describe(channel="Канал для панели")
    @app_commands.guild_only()
    async def clan_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not style.is_admin(interaction):
            return await interaction.response.send_message(
                embed=style.error("Нет прав", "❌ Нет прав."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel

        embed = style.base(
            "⚔️ ЗАЯВКА В КЛАН",
            CLAN_PANEL_DESCRIPTION,
            color=discord.Color.gold(),
            footer="Нажмите кнопку ниже, чтобы подать заявку.",
        )
        await target.send(embed=embed, view=ClanTicketPanelView())
        await interaction.followup.send(
            embed=style.success("✅ Панель", f"Панель отправлена в {target.mention}."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ClanTicketCog(bot))
