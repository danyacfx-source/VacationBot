import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from io import BytesIO

from helpers import send_ticket_log, load_tickets, save_tickets
import config

log = logging.getLogger("clan_tickets")

CLAN_APPLICATION_FORM = (
    "**Пожалуйста, ответьте на вопросы:**\n\n"
    "**1.** Сколько часов в игре?\n"
    "**2.** Для чего вы хотите вступить в клан?\n"
    "**3.** Откуда вы узнали о направлении WARDOGS GMS?\n"
    "**4.** Сколько вам лет?\n"
    "**5.** Какой у вас часовой пояс?\n"
    "**6.** Какой у вас средний онлайн в неделю?"
)

CLAN_TICKET_TYPE = "clan"


class ClanTicketPanelView(discord.ui.View):
    """Persistent-панель регистрации клана."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Подать заявку в клан", style=discord.ButtonStyle.primary, custom_id="ck_create", emoji="📝")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction)

    async def _create_ticket(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        tickets = load_tickets()
        for t in tickets.values():
            if (
                t.get("user_id") == interaction.user.id
                and t.get("status") == "open"
                and t.get("type") == CLAN_TICKET_TYPE
            ):
                return await interaction.followup.send(
                    "У вас уже есть открытая заявка в клан.", ephemeral=True
                )

        guild = interaction.guild
        user = interaction.user
        category = guild.get_channel(config.TICKET_CATEGORY)
        if not category:
            return await interaction.followup.send("❌ Категория тикетов не настроена.", ephemeral=True)

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
                "❌ Не удалось создать заявку (ошибка Discord).", ephemeral=True
            )
        except Exception as e:
            log.exception("Непредвиденная ошибка создания кланового тикета: %s", e)
            return await interaction.followup.send(
                "❌ Не удалось создать заявку.", ephemeral=True
            )

        embed = discord.Embed(
            title="📝 ЗАЯВКА В КЛАН",
            description=CLAN_APPLICATION_FORM,
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.set_footer(text=f"ID: {user.id}")

        staff_mention = f"<@&{config.TICKET_STAFF_ROLE}>"
        await channel.send(content=f"{staff_mention} {user.mention}", embed=embed, view=ClanTicketCloseView())

        ticket_id = str(channel.id)
        tickets[ticket_id] = {
            "user_id": user.id,
            "channel_id": channel.id,
            "type": CLAN_TICKET_TYPE,
            "status": "open",
            "created_at": datetime.utcnow().isoformat(),
            "guild_id": guild.id,
        }
        save_tickets(tickets)

        await interaction.followup.send(f"Заявка в клан создана: {channel.mention}", ephemeral=True)

        await send_ticket_log(
            interaction.client,
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
            await channel.set_permissions(channel.guild.default_role, view_channel=False)
            staff_role = channel.guild.get_role(config.TICKET_STAFF_ROLE)
            if staff_role:
                await channel.set_permissions(
                    staff_role, view_channel=True, send_messages=False, read_message_history=True
                )

        embed = discord.Embed(
            title="Заявка закрыта",
            description=f"Закрыл: {interaction.user.mention}\nСохраните транскрипт или удалите канал.",
            color=discord.Color.greyple(),
        )
        await interaction.message.edit(embed=embed, view=ClanTicketClosedView())

        await send_ticket_log(
            interaction.client,
            "📝 Заявка в клан закрыта",
            f"**Тикет:** {channel.mention}\n**Закрыл:** {interaction.user}",
        )

    @discord.ui.button(label="Нет", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Закрытие отменено.", view=None)


class ClanTicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Закрыть заявку", style=discord.ButtonStyle.red, custom_id="ck_close", emoji="🔒")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Вы уверены?", view=ClanTicketCloseConfirmView()
        )


class ClanTicketClosedView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Удалить канал", style=discord.ButtonStyle.danger, custom_id="ck_delete", emoji="🗑️")
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        tickets = load_tickets()
        ticket_data = tickets.get(str(interaction.channel.id))

        if ticket_data:
            is_owner = interaction.user.id == ticket_data.get("user_id")
            is_staff = interaction.user.guild_permissions.manage_channels
            if not is_owner and not is_staff:
                return await interaction.followup.send(
                    "❌ Вы не можете удалить этот тикет.", ephemeral=True
                )

        tickets.pop(str(interaction.channel.id), None)
        save_tickets(tickets)

        await send_ticket_log(
            interaction.client,
            "🗑️ Клановый тикет удалён",
            f"**Канал:** {interaction.channel.name}\n**Удалил:** {interaction.user}",
        )

        await interaction.channel.delete()

    @discord.ui.button(label="Сохранить транскрипт", style=discord.ButtonStyle.blurple, custom_id="ck_transcript", emoji="📄")
    async def save_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        channel = interaction.channel
        messages = [message async for message in channel.history(oldest_first=True)]

        lines = []
        for msg in messages:
            ts = msg.created_at.strftime("%d.%m.%Y %H:%M:%S")
            content = msg.content or ""
            if msg.embeds:
                for e in msg.embeds:
                    if e.description:
                        content += f" {e.description}"
            lines.append(f"[{ts}] {msg.author}: {content}")

        transcript = "\n".join(lines)
        file = discord.File(
            fp=BytesIO(transcript.encode("utf-8")),
            filename=f"clan-{channel.name}.txt",
        )

        if config.TICKET_TRANSCRIPT_CHANNEL:
            tr_ch = interaction.guild.get_channel(config.TICKET_TRANSCRIPT_CHANNEL)
            if tr_ch:
                await tr_ch.send(file=file)
                return await interaction.followup.send("Транскрипт сохранён.", ephemeral=True)
        await interaction.followup.send(file=file, ephemeral=True)


class ClanTicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    clan_group = app_commands.Group(name="clan", description="Управление заявками в клан")

    @clan_group.command(name="panel", description="Отправить панель заявок в клан")
    @app_commands.describe(channel="Канал для панели")
    @app_commands.guild_only()
    async def clan_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel

        embed = discord.Embed(
            title="⚔️ ЗАЯВКА В КЛАН",
            description=CLAN_APPLICATION_FORM,
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Нажмите кнопку ниже, чтобы подать заявку.")
        await target.send(embed=embed, view=ClanTicketPanelView())
        await interaction.followup.send(f"Панель отправлена в {target.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ClanTicketCog(bot))