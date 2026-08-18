import sys
import os
import discord
from discord.ext import commands
from discord import app_commands
from io import BytesIO
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import send_ticket_log, load_tickets, save_tickets
import config


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

        tickets = load_tickets()

        for t in tickets.values():
            if (
                t.get("user_id") == interaction.user.id
                and t.get("status") == "open"
                and t.get("type") == ticket_type
            ):
                await interaction.followup.send(
                    "У вас уже есть открытый тикет этого типа.", ephemeral=True
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
            guild.get_role(config.TICKET_STAFF_ROLE): discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            ),
        }

        channel_name = f"{cfg['prefix']}-{user.name}"
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Тикет от {user} ({user.id}) | Тип: {ticket_type}",
        )

        embed = discord.Embed(
            title=cfg["title"],
            description=cfg["question"],
            color=cfg["color"],
            timestamp=datetime.utcnow(),
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.set_footer(text=f"ID: {user.id}")

        await channel.send(
            content=f"<@&1509699660149821601> <@&1484506106897109125> {user.mention}",
            embed=embed,
            view=TicketCloseView(),
        )

        ticket_id = str(channel.id)
        tickets[ticket_id] = {
            "user_id": user.id,
            "channel_id": channel.id,
            "type": ticket_type,
            "status": "open",
            "created_at": datetime.utcnow().isoformat(),
            "guild_id": guild.id,
        }
        save_tickets(tickets)

        await send_ticket_log(
            interaction.client,
            "🎫 Тикет создан",
            f"**Тикет:** {channel.mention}\n**Тип:** {ticket_type}\n**Пользователь:** {user}",
        )

        await interaction.followup.send(
            f"Тикет создан: {channel.mention}", ephemeral=True
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
        tickets = load_tickets()
        ticket_data = tickets.get(str(channel.id))

        if ticket_data:
            ticket_data["status"] = "closed"
            ticket_data["closed_at"] = datetime.utcnow().isoformat()
            ticket_data["closed_by"] = interaction.user.id
            save_tickets(tickets)

            creator_id = ticket_data.get("user_id")
            if creator_id:
                member = channel.guild.get_member(int(creator_id))
                if member:
                    await channel.set_permissions(member, overwrite=None)
            staff_role = channel.guild.get_role(config.TICKET_STAFF_ROLE)
            if staff_role:
                await channel.set_permissions(
                    channel.guild.default_role, overwrite=None,
                )
                await channel.set_permissions(
                    staff_role,
                    view_channel=True,
                    read_message_history=True,
                )

        embed = discord.Embed(
            title="Тикет закрыт",
            description=f"Тикет закрыт модератором {interaction.user.mention}.\n\nВы можете сохранить транскрипт или удалить канал.",
            color=discord.Color.greyple(),
        )

        await interaction.edit_original_response(embed=embed, view=TicketClosedView())

        await send_ticket_log(
            interaction.client,
            "🎫 Тикет закрыт",
            f"**Тикет:** {channel.mention}\n**Закрыл:** {interaction.user}",
        )

    @discord.ui.button(label="Нет", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel_close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.edit_message(
            content="Закрытие отменено.", view=None
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
            "Вы уверены, что хотите закрыть тикет?",
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

        tickets = load_tickets()
        ticket_data = tickets.get(str(interaction.channel.id))

        if ticket_data and interaction.user.id == ticket_data.get("user_id"):
            await interaction.followup.send(
                "❌ Вы не можете управлять этим тикетом."
            )
            return

        await send_ticket_log(
            interaction.client,
            "🗑️ Канал тикета удалён",
            f"**Канал:** {interaction.channel.name}\n**Удалил:** {interaction.user}",
        )

        tickets.pop(str(interaction.channel.id), None)
        save_tickets(tickets)

        await interaction.channel.delete()

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

        channel = interaction.channel
        messages = [message async for message in channel.history(oldest_first=True)]

        lines = []
        for msg in messages:
            timestamp = msg.created_at.strftime("%d.%m.%Y %H:%M:%S")
            content = msg.content or ""
            if msg.embeds:
                for embed in msg.embeds:
                    if embed.description:
                        content += f" {embed.description}"
                    if embed.fields:
                        for field in embed.fields:
                            content += f"\n**{field.name}**: {field.value}"
            lines.append(f"[{timestamp}] {msg.author}: {content}")

        transcript_text = "\n".join(lines)
        file = discord.File(
            fp=BytesIO(transcript_text.encode("utf-8")),
            filename=f"transcript-{channel.name}.txt",
        )

        transcript_channel = interaction.guild.get_channel(
            config.TICKET_TRANSCRIPT_CHANNEL
        )
        if transcript_channel:
            embed = discord.Embed(
                title=f"Транскрипт: {channel.name}",
                color=discord.Color.greyple(),
                timestamp=datetime.utcnow(),
            )
            embed.set_footer(text=f"Канал: {channel.name} | Сохранил: {interaction.user}")

            tickets = load_tickets()
            ticket_data = tickets.get(str(channel.id))
            if ticket_data:
                user_id = ticket_data.get("user_id")
                embed.add_field(name="Пользователь", value=f"<@{user_id}>", inline=True)
                embed.add_field(name="Тип", value=ticket_data.get("type", "unknown"), inline=True)
                embed.add_field(name="Статус", value=ticket_data.get("status", "unknown"), inline=True)

            await transcript_channel.send(embed=embed, file=file)

        await interaction.followup.send("Транскрипт сохранён.")

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

        tickets = load_tickets()
        ticket_data = tickets.get(str(interaction.channel.id))

        if not ticket_data:
            await interaction.followup.send("Данные тикета не найдены.")
            return

        user_id = ticket_data.get("user_id")
        ticket_type = ticket_data.get("type")
        guild = interaction.guild
        member = guild.get_member(user_id)

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
                    await member.add_roles(role, reason=f"Тикет одобрен: {interaction.channel.name}")

        ticket_data["status"] = "approved"
        ticket_data["approved_by"] = interaction.user.id
        ticket_data["approved_at"] = datetime.utcnow().isoformat()
        save_tickets(tickets)

        if member:
            try:
                await member.send(
                    f"✅ Ваша заявка в **{ticket_type}** была одобрена! Добро пожаловать!"
                )
            except discord.Forbidden:
                pass

        embed = discord.Embed(
            title="Заявка одобрена",
            description=f"Заявка одобрена модератором {interaction.user.mention}.",
            color=discord.Color.green(),
        )
        await interaction.edit_original_response(embed=embed)

        await send_ticket_log(
            interaction.client,
            "✅ Тикет одобрен",
            f"**Тикет:** {interaction.channel.mention}\n**Пользователь:** <@{user_id}>\n**Одобрил:** {interaction.user}",
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

        tickets = load_tickets()
        ticket_data = tickets.get(str(interaction.channel.id))

        if not ticket_data:
            await interaction.followup.send("Данные тикета не найдены.")
            return

        user_id = ticket_data.get("user_id")
        ticket_type = ticket_data.get("type")
        guild = interaction.guild
        member = guild.get_member(user_id)

        ticket_data["status"] = "rejected"
        ticket_data["rejected_by"] = interaction.user.id
        ticket_data["rejected_at"] = datetime.utcnow().isoformat()
        save_tickets(tickets)

        if member:
            try:
                await member.send(
                    f"❌ Ваша заявка в **{ticket_type}** была отклонена."
                )
            except discord.Forbidden:
                pass

        embed = discord.Embed(
            title="Заявка отклонена",
            description=f"Заявка отклонена модератором {interaction.user.mention}.",
            color=discord.Color.red(),
        )
        await interaction.edit_original_response(embed=embed)

        await send_ticket_log(
            interaction.client,
            "❌ Тикет отклонён",
            f"**Тикет:** {interaction.channel.mention}\n**Пользователь:** <@{user_id}>\n**Отклонил:** {interaction.user}",
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
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "У вас нет прав для использования этой команды.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        target = channel or interaction.channel

        embed = discord.Embed(
            title="ПОДАЧА ЗАЯВКИ В КЛАН Group Military Slavic",
            description=(
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
        )
        embed.set_footer(text="Нажмите на кнопку ниже, чтобы подать заявку.")

        await target.send(embed=embed, view=TicketCreateView())

        if channel:
            await interaction.followup.send(
                f"Панель тикетов отправлена в {channel.mention}.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "Панель тикетов отправлена.", ephemeral=True
            )

    @ticket_group.command(name="promote_panel", description="Отправить панель заявок на повышение")
    @app_commands.describe(channel="Канал для панели")
    async def promote_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "У вас нет прав для использования этой команды.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        target = channel or interaction.channel

        embed = discord.Embed(
            title="📈 Заявка на повышение",
            description=(
                "Нажмите на кнопку ниже, чтобы подать заявку на повышение.\n\n"
                "Убедитесь, что вы соответствуете требованиям должности, на которую претендуете."
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="Нажмите на кнопку ниже, чтобы создать заявку.")

        await target.send(embed=embed, view=PromotionPanelView())

        if channel:
            await interaction.followup.send(
                f"Панель повышений отправлена в {channel.mention}.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "Панель повышений отправлена.", ephemeral=True
            )

    @ticket_group.command(name="arma_panel", description="Отправить панель заявок на армача")
    @app_commands.describe(channel="Канал для панели")
    async def arma_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "У вас нет прав для использования этой команды.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        target = channel or interaction.channel

        embed = discord.Embed(
            title="⚔️ Заявка на армача",
            description=(
                "Нажмите на кнопку ниже, чтобы подать заявку на армача.\n\n"
                "Убедитесь, что вы хорошо освоили классы и имеете опыт."
            ),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Нажмите на кнопку ниже, чтобы создать заявку.")

        await target.send(embed=embed, view=ArmaPanelView())

        if channel:
            await interaction.followup.send(
                f"Панель армачей отправлена в {channel.mention}.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "Панель армачей отправлена.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCog(bot))
