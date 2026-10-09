"""Система тикетов: панели заявок, создание, закрытие, транскрипт, approve/reject."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.timeutil import msk_utcnow
from services.notify import send_ticket_log
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


class TicketCreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Подать заявку",
        style=discord.ButtonStyle.green,
        custom_id="ticket_create",
    )
    async def ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "clan")

    @discord.ui.button(
        label="Подать заявку в академию",
        style=discord.ButtonStyle.blurple,
        custom_id="ticket_create_academy",
    )
    async def academy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "academy")

    async def _create_ticket(self, interaction: discord.Interaction, ticket_type: str):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client

        if await find_open_ticket(bot, interaction.user.id, ticket_type):
            await interaction.followup.send(
                embed=style.warning(
                    "⏳ Тикет уже открыт",
                    "У вас уже есть открытый тикет этого типа.",
                ),
                ephemeral=True,
            )
            return

        user = interaction.user
        guild = interaction.guild

        type_config = {
            "clan": {
                "prefix": "тикет",
                "color": discord.Color.dark_red(),
                "category": config.TICKET_CATEGORY,
                "title": "Заявка в клан",
                "question": (
                    "**Пожалуйста, ответьте на вопросы:**\n\n"
                    "**1.** Сколько часов в игре?\n"
                    "**2.** Для чего вы хотите вступить в клан?\n"
                    "**3.** Откуда вы узнали о GMS?\n"
                    "**4.** Сколько вам лет?\n"
                    "**5.** Какой у вас часовой пояс?\n"
                    "**6.** Какой у вас средний онлайн в неделю?"
                ),
            },
            "academy": {
                "prefix": "академка",
                "color": discord.Color.gold(),
                "category": config.TICKET_ACADEMY_CATEGORY,
                "title": "Заявка в академию",
                "question": (
                    "**Пожалуйста, ответьте на вопросы:**\n\n"
                    "**1.** Готовы ли вы пройти курс молодого бойца?\n"
                    "**2.** Сколько вам лет?\n"
                    "**3.** Откуда вы узнали о GMS?\n"
                    "**4.** Сколько времени в неделю вы сможете уделять игре?\n"
                    "**5.** Чему вы хотите научиться?\n"
                    "**6.** Планируете ли вы повышаться до старшего состава?\n"
                    "**7.** Что вы ожидаете увидеть в клане?\n"
                    "**8.** Что вы хотите от клана?\n"
                    "**9.** Сколько у вас часов в Squad?"
                ),
            },
            "promotion": {
                "prefix": "повышение",
                "color": discord.Color.green(),
                "category": config.TICKET_CATEGORY,
                "title": "Заявка на повышение",
                "question": (
                    "Пожалуйста, ответьте на следующие вопросы:\n\n"
                    "1. Ваш никнейм в игре?\n"
                    "2. Какую должность вы занимаете сейчас?\n"
                    "3. На какую должность хотите повыситься?\n"
                    "4. Что вы сделали для клана за последнее время?\n"
                    "5. Почему вы заслуживаете повышения?"
                ),
            },
            "arma": {
                "prefix": "арма",
                "color": discord.Color.blue(),
                "category": config.TICKET_CATEGORY,
                "title": "Заявка на армач",
                "question": (
                    "Пожалуйста, ответьте на следующие вопросы:\n\n"
                    "1. Ваш никнейм в игре?\n"
                    "2. Как давно играете?\n"
                    "3. Почему хотите стать армачом?\n"
                    "4. Какие классы/роли вы хорошо освоили?\n"
                    "5. Есть ли у вас опыт ведения армачей?"
                ),
            },
        }

        cfg = type_config[ticket_type]
        category = guild.get_channel(cfg["category"])

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }
        staff_role = guild.get_role(config.TICKET_STAFF_ROLE)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        channel_name = f"{cfg['prefix']}-{user.name}"
        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Тикет от {user} ({user.id}) | Тип: {ticket_type}",
            )
        except discord.HTTPException as exc:
            log.error("Не удалось создать тикет %s для %s: %s", ticket_type, user, exc)
            await interaction.followup.send(
                embed=style.error("Ошибка", "Не удалось создать тикет (ошибка Discord)."),
                ephemeral=True,
            )
            return
        except Exception:
            log.exception("Непредвиденная ошибка создания тикета %s", ticket_type)
            await interaction.followup.send(
                embed=style.error("Ошибка", "Не удалось создать тикет."),
                ephemeral=True,
            )
            return

        embed = style.base(
            cfg["title"],
            cfg["question"],
            color=cfg["color"],
            footer=f"ID: {user.id}",
            timestamp=True,
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

        pings = " ".join(f"<@&{role_id}>" for role_id in config.TICKET_NOTIFY_ROLES)
        try:
            await channel.send(
                content=f"{pings} {user.mention}".strip(),
                embed=embed,
                view=TicketCloseView(),
            )
        except discord.HTTPException as exc:
            log.error("Не удалось отправить сообщение в тикет %s: %s", channel.name, exc)

        await save_ticket(
            bot,
            {
                "user_id": user.id,
                "channel_id": channel.id,
                "type": ticket_type,
                "status": "open",
                "created_at": msk_utcnow().isoformat(timespec="seconds"),
                "guild_id": guild.id,
            },
        )

        await send_ticket_log(
            bot,
            "🎫 Тикет создан",
            f"**Тикет:** {channel.mention}\n**Тип:** {ticket_type}\n**Пользователь:** {user}",
        )

        await interaction.followup.send(
            embed=style.success("🎫 Тикет создан", f"Тикет создан: {channel.mention}"),
            ephemeral=True,
        )


class TicketCloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Да", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm_close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
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
                        log.error("Не удалось снять права %s в тикете: %s", member, exc)

            staff_role = channel.guild.get_role(config.TICKET_STAFF_ROLE)
            try:
                await channel.set_permissions(channel.guild.default_role, overwrite=None)
                if staff_role:
                    await channel.set_permissions(
                        staff_role,
                        view_channel=True,
                        read_message_history=True,
                    )
            except discord.HTTPException as exc:
                log.error("Не удалось обновить права тикета %s: %s", channel.name, exc)

        embed = style.base(
            "Тикет закрыт",
            f"Тикет закрыт модератором {interaction.user.mention}.\n\n"
            "Вы можете сохранить транскрипт или удалить канал.",
            color=style.NEUTRAL,
            footer=None,
        )

        await interaction.edit_original_response(embed=embed, view=TicketClosedView())

        await send_ticket_log(
            bot,
            "🎫 Тикет закрыт",
            f"**Тикет:** {channel.mention}\n**Закрыл:** {interaction.user}",
        )

    @discord.ui.button(label="Нет", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel_close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.edit_message(
            embed=style.info("Отменено", "Закрытие отменено."),
            view=None,
        )


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Закрыть тикет",
        style=discord.ButtonStyle.red,
        custom_id="ticket_close",
        emoji="🔒",
    )
    async def close_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            embed=style.warning(
                "🔒 Закрытие тикета",
                "Вы уверены, что хотите закрыть тикет?",
            ),
            view=TicketCloseConfirmView(),
        )


class TicketClosedView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Удалить канал",
        style=discord.ButtonStyle.danger,
        custom_id="closed_delete",
        emoji="🗑️",
    )
    async def delete_channel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()

        bot = interaction.client
        ticket_data = await fetch_ticket(bot, interaction.channel.id)

        if ticket_data:
            is_owner = interaction.user.id == ticket_data.get("user_id")
            is_staff = interaction.user.guild_permissions.manage_channels
            if not is_owner and not is_staff:
                await interaction.followup.send(
                    embed=style.error("Нет доступа", "❌ Вы не можете удалить этот тикет."),
                    ephemeral=True,
                )
                return

        await send_ticket_log(
            bot,
            "🗑️ Канал тикета удалён",
            f"**Канал:** {interaction.channel.name}\n**Удалил:** {interaction.user}",
        )

        await delete_ticket(bot, interaction.channel.id)

        try:
            await interaction.channel.delete()
        except discord.HTTPException as exc:
            log.error("Не удалось удалить канал тикета %s: %s", interaction.channel.name, exc)
            await interaction.followup.send(
                embed=style.error("Ошибка", "Не удалось удалить канал."),
                ephemeral=True,
            )

    @discord.ui.button(
        label="Сохранить транскрипт",
        style=discord.ButtonStyle.blurple,
        custom_id="closed_transcript",
        emoji="📄",
    )
    async def save_transcript(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()

        await send_transcript(
            interaction,
            prefix="transcript",
            transcript_channel_id=config.TICKET_TRANSCRIPT_CHANNEL,
            message_fields=True,
            meta_fields=True,
            ephemeral=False,
        )

    @discord.ui.button(
        label="Одобрить",
        style=discord.ButtonStyle.green,
        custom_id="closed_approve",
        emoji="✅",
    )
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()

        bot = interaction.client
        ticket_data = await fetch_ticket(bot, interaction.channel.id)

        if not ticket_data:
            await interaction.followup.send(
                embed=style.error("Ошибка", "Данные тикета не найдены.")
            )
            return

        user_id = ticket_data.get("user_id")
        ticket_type = ticket_data.get("type")
        guild = interaction.guild
        member = guild.get_member(int(user_id)) if user_id else None

        role_map = {
            "academy": getattr(config, "ACADEMY_ROLES", []),
            "clan": getattr(config, "CLAN_ROLES", []),
            "arma": getattr(config, "ARMA_ROLES", []),
        }

        roles_to_add = role_map.get(ticket_type, [])

        if member and roles_to_add:
            for role_id in roles_to_add:
                role = guild.get_role(role_id)
                if role:
                    try:
                        await member.add_roles(
                            role,
                            reason=f"Тикет одобрен: {interaction.channel.name}",
                        )
                    except discord.HTTPException as exc:
                        log.error(
                            "Не удалось выдать роль %s пользователю %s: %s",
                            role,
                            member,
                            exc,
                        )

        await update_ticket(
            bot,
            interaction.channel.id,
            status="approved",
            approved_by=interaction.user.id,
            approved_at=msk_utcnow().isoformat(timespec="seconds"),
        )

        if member:
            try:
                await member.send(
                    f"✅ Ваша заявка в **{ticket_type}** была одобрена! Добро пожаловать!"
                )
            except discord.HTTPException as exc:
                log.warning("Не удалось отправить ЛС %s: %s", member, exc)

        embed = style.success(
            "Заявка одобрена",
            f"Заявка одобрена модератором {interaction.user.mention}.",
            footer=None,
        )
        await interaction.edit_original_response(embed=embed)

        await send_ticket_log(
            bot,
            "✅ Тикет одобрен",
            f"**Тикет:** {interaction.channel.mention}\n"
            f"**Пользователь:** <@{user_id}>\n"
            f"**Одобрил:** {interaction.user}",
        )

    @discord.ui.button(
        label="Отклонить",
        style=discord.ButtonStyle.red,
        custom_id="closed_reject",
        emoji="❌",
    )
    async def reject(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()

        bot = interaction.client
        ticket_data = await fetch_ticket(bot, interaction.channel.id)

        if not ticket_data:
            await interaction.followup.send(
                embed=style.error("Ошибка", "Данные тикета не найдены.")
            )
            return

        user_id = ticket_data.get("user_id")
        ticket_type = ticket_data.get("type")
        guild = interaction.guild
        member = guild.get_member(int(user_id)) if user_id else None

        await update_ticket(
            bot,
            interaction.channel.id,
            status="rejected",
            rejected_by=interaction.user.id,
            rejected_at=msk_utcnow().isoformat(timespec="seconds"),
        )

        if member:
            try:
                await member.send(
                    f"❌ Ваша заявка в **{ticket_type}** была отклонена."
                )
            except discord.HTTPException as exc:
                log.warning("Не удалось отправить ЛС %s: %s", member, exc)

        embed = style.error(
            "Заявка отклонена",
            f"Заявка отклонена модератором {interaction.user.mention}.",
            footer=None,
        )
        await interaction.edit_original_response(embed=embed)

        await send_ticket_log(
            bot,
            "❌ Тикет отклонён",
            f"**Тикет:** {interaction.channel.mention}\n"
            f"**Пользователь:** <@{user_id}>\n"
            f"**Отклонил:** {interaction.user}",
        )


class PromotionPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Подать заявку на повышение",
        style=discord.ButtonStyle.green,
        custom_id="ticket_create_promotion",
        emoji="📈",
    )
    async def promotion_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await TicketCreateView()._create_ticket(interaction, "promotion")


class ArmaPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Подать заявку на армача",
        style=discord.ButtonStyle.blurple,
        custom_id="ticket_create_arma",
        emoji="⚔️",
    )
    async def arma_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await TicketCreateView()._create_ticket(interaction, "arma")


class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    ticket_group = app_commands.Group(name="tickets", description="Управление тикетами")

    @ticket_group.command(name="ticket_panel", description="Отправить панель создания тикетов")
    @app_commands.describe(channel="Канал для панели")
    async def ticket_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        if not style.is_admin(interaction):
            await interaction.response.send_message(
                embed=style.error("Нет прав", "У вас нет прав для использования этой команды."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        target = channel or interaction.channel

        embed = style.base(
            "ПОДАЧА ЗАЯВКИ В КЛАН Group Military Slavic",
            (
                "При подаче заявки, важно понимать, что есть условия вступления!\n\n"
                "**Условия:**\n"
                "🔹 Возраст от 16 лет (есть исключения)\n"
                "🔹 Адекватность\n"
                "🔹 Более 100 часов в Squad\n"
                "🔹 Желание учиться и совершенствовать свои навыки в команде\n"
                "🔹 Если у вас менее 100 часов нажмите \"Подать заявку в академию\"\n\n"
                "**В свою очередь мы предоставим вам:**\n"
                "🔶 Взаимный опыт\n"
                "🔶 Приятная атмосфера\n"
                "🔶 VIP пропуск на все сервера Пятый Мотострелковый\n"
                "🔶 Обучение тактикам и ведению боя в различных условиях\n"
                "🔶 У нас нет глупых правил, чтобы сдерживать ваш потенциал\n"
                "🔶 Клановые мероприятия. Эвенты, тренировки, Воскрески\n\n"
                "Если тебя всё устраивает, нажимай кнопку **\"Подать заявку\"**\n"
                "Если же у вас есть вопрос, можете воспользоваться общим чатом"
            ),
            color=discord.Color.dark_red(),
            footer="Нажмите на кнопку ниже, чтобы подать заявку.",
        )

        await target.send(embed=embed, view=TicketCreateView())

        if channel:
            text = f"Панель тикетов отправлена в {channel.mention}."
        else:
            text = "Панель тикетов отправлена."
        await interaction.followup.send(
            embed=style.success("🎫 Панель тикетов", text), ephemeral=True
        )

    @ticket_group.command(name="promote_panel", description="Отправить панель заявок на повышение")
    @app_commands.describe(channel="Канал для панели")
    async def promote_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        if not style.is_admin(interaction):
            await interaction.response.send_message(
                embed=style.error("Нет прав", "У вас нет прав для использования этой команды."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        target = channel or interaction.channel

        embed = style.base(
            "📈 Заявка на повышение",
            (
                "Нажмите на кнопку ниже, чтобы подать заявку на повышение.\n\n"
                "Убедитесь, что вы соответствуете требованиям должности, на которую претендуете."
            ),
            color=discord.Color.green(),
            footer="Нажмите на кнопку ниже, чтобы создать заявку.",
        )

        await target.send(embed=embed, view=PromotionPanelView())

        if channel:
            text = f"Панель повышений отправлена в {channel.mention}."
        else:
            text = "Панель повышений отправлена."
        await interaction.followup.send(
            embed=style.success("📈 Панель повышений", text), ephemeral=True
        )

    @ticket_group.command(name="arma_panel", description="Отправить панель заявок на армача")
    @app_commands.describe(channel="Канал для панели")
    async def arma_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        if not style.is_admin(interaction):
            await interaction.response.send_message(
                embed=style.error("Нет прав", "У вас нет прав для использования этой команды."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        target = channel or interaction.channel

        embed = style.base(
            "⚔️ Заявка на армача",
            (
                "Нажмите на кнопку ниже, чтобы подать заявку на армача.\n\n"
                "Убедитесь, что вы хорошо освоили классы и имеете опыт."
            ),
            color=discord.Color.blue(),
            footer="Нажмите на кнопку ниже, чтобы создать заявку.",
        )

        await target.send(embed=embed, view=ArmaPanelView())

        if channel:
            text = f"Панель армачей отправлена в {channel.mention}."
        else:
            text = "Панель армачей отправлена."
        await interaction.followup.send(
            embed=style.success("⚔️ Панель армачей", text), ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCog(bot))
