"""Приветствия, прощания и тест welcome-сообщения."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from ui import style

log = logging.getLogger(__name__)


def _notice(text: str, *, ok: bool = True) -> discord.Embed:
    """Короткий ответ на команду: тот же текст, но в эмбеде."""
    return style.base(None, text, color=style.SUCCESS if ok else style.ERROR, footer=None)


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        await self._grant_join_roles(member)
        await self._post_public(member, left=False)
        if config.WELCOME_DM_ENABLED:
            try:
                embed = self._build_embed(member)
                await member.send(embed=embed)
                log.info("Welcome: приветствие отправлено %s", member)
            except discord.Forbidden:
                log.warning("Welcome: нельзя отправить ЛС %s", member)
            except discord.HTTPException:
                log.warning("Welcome: не удалось отправить ЛС %s", member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        await self._post_public(member, left=True)

    # ------------------------------------------------------------ служебное

    async def _grant_join_roles(self, member: discord.Member) -> None:
        """Автовыдача ролей при вступлении (config.JOIN_ROLES)."""
        if member.bot or not config.JOIN_ROLES:
            return
        for role_id in config.JOIN_ROLES:
            role = member.guild.get_role(role_id)
            if role is None or role in member.roles:
                continue
            try:
                await member.add_roles(
                    role, reason="Автовыдача роли при вступлении на сервер"
                )
                log.info(
                    "Выдана роль %s участнику %s (%s)", role.name, member, member.id
                )
            except discord.Forbidden:
                log.error(
                    "Нет прав выдать роль %s участнику %s (%s)",
                    role.name,
                    member,
                    member.id,
                )
            except Exception as exc:
                log.error("Ошибка выдачи роли %s участнику %s: %s", role.name, member, exc)

    async def _post_public(self, member: discord.Member, left: bool) -> None:
        cid = config.WELCOME_LEAVE_CHANNEL if left else config.WELCOME_CHANNEL
        if not cid:
            return
        channel = self.bot.get_channel(cid)
        if channel is None:
            return
        try:
            if left:
                embed = style.base(
                    None,
                    f"**{member.display_name}** покинул сервер. До встречи! 👋",
                    color=discord.Color.dark_grey(),
                    footer=f"ID: {member.id}",
                )
                if member.display_avatar:
                    embed.set_author(
                        name="Участник вышел", icon_url=member.display_avatar.url
                    )
            else:
                embed = style.base(
                    None,
                    f"**{member.display_name}** зашёл на сервер! Поздороваемся вместе? 👋",
                    color=style.SUCCESS,
                    footer=f"ID: {member.id}",
                )
                if member.display_avatar:
                    embed.set_author(
                        name="Новый участник", icon_url=member.display_avatar.url
                    )
                style.field(
                    embed,
                    "Участников на сервере",
                    str(member.guild.member_count),
                    inline=True,
                )
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.warning(
                "Welcome: нет прав писать в канал %s", getattr(channel, "name", cid)
            )
        except discord.HTTPException:
            log.warning(
                "Welcome: ошибка отправки в канал %s", getattr(channel, "name", cid)
            )

    def _build_embed(self, member: discord.Member) -> discord.Embed:
        guild = member.guild
        lines = []
        for cat in guild.categories:
            text_channels = [
                c
                for c in cat.text_channels
                if c.permissions_for(guild.default_role).read_messages
            ]
            if text_channels:
                cat_lines = [f"• **<#{c.id}>**" for c in text_channels]
                lines.append(f"**{cat.name}**")
                lines.extend(cat_lines)
                lines.append("")

        voice_lines = [
            f"• **{vc.name}**"
            for vc in guild.voice_channels
            if vc.permissions_for(guild.default_role).connect
        ]
        if voice_lines:
            lines.append("**Голосовые каналы**")
            lines.extend(voice_lines)

        title = config.WELCOME_TITLE
        if config.WELCOME_CLAN_NAME:
            title = f"Добро пожаловать в {config.WELCOME_CLAN_NAME}! 🎖️"
        embed = style.base(
            title,
            config.WELCOME_INTRO,
            color=style.EVENT,
            footer=config.WELCOME_FOOTER,
        )
        if lines:
            channel_text = "\n".join(lines).strip()
            if len(channel_text) > 1024:
                channel_text = channel_text[:1020] + "\n…"
            style.field(embed, "📂 Наши каналы", channel_text)
        if guild.rules_channel:
            style.field(
                embed,
                "📜 Правила",
                f"Ознакомься с правилами сервера: {guild.rules_channel.mention}",
            )
        return embed

    # ------------------------------------------------------------ команды

    @app_commands.command(
        name="welcome_test", description="[Админ] Отправить тестовое welcome-сообщение в ЛС"
    )
    @app_commands.describe(user="Кому отправить в ЛС")
    async def welcome_test(self, interaction: discord.Interaction, user: discord.Member):
        if not style.is_admin(interaction):
            return await interaction.response.send_message(
                embed=_notice("Нет прав.", ok=False), ephemeral=True
            )
        embed = self._build_embed(user)
        try:
            await user.send(embed=embed)
            await interaction.response.send_message(
                embed=_notice(
                    f"✅ Тестовое welcome-сообщение отправлено в ЛС {user.mention}"
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=_notice(
                    f"❌ Не удалось отправить ЛС {user.mention} (у пользователя закрыты ЛС)",
                    ok=False,
                ),
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                embed=_notice(f"❌ Ошибка отправки ЛС {user.mention}", ok=False),
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
