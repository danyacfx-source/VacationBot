import logging

import discord
from discord.ext import commands

import config


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        await self._post_public(member, left=False)
        if config.WELCOME_DM_ENABLED:
            try:
                embed = self._build_embed(member)
                await member.send(embed=embed)
                logging.info("Welcome: приветствие отправлено %s", member)
            except discord.Forbidden:
                logging.warning("Welcome: нельзя отправить ЛС %s", member)
            except discord.HTTPException:
                logging.warning("Welcome: не удалось отправить ЛС %s", member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        await self._post_public(member, left=True)

    async def _post_public(self, member: discord.Member, left: bool):
        cid = config.WELCOME_LEAVE_CHANNEL if left else config.WELCOME_CHANNEL
        if not cid:
            return
        channel = self.bot.get_channel(cid)
        if channel is None:
            return
        try:
            if left:
                embed = discord.Embed(
                    description=f"**{member.display_name}** покинул сервер. До встречи! 👋",
                    color=discord.Color.dark_grey(),
                )
                if member.display_avatar:
                    embed.set_author(name="Участник вышел", icon_url=member.display_avatar.url)
                embed.set_footer(text=f"ID: {member.id}")
            else:
                embed = discord.Embed(
                    description=f"**{member.display_name}** зашёл на сервер! Поздороваемся вместе? 👋",
                    color=discord.Color.green(),
                )
                if member.display_avatar:
                    embed.set_author(name="Новый участник", icon_url=member.display_avatar.url)
                embed.add_field(name="Участников на сервере", value=str(member.guild.member_count), inline=True)
                embed.set_footer(text=f"ID: {member.id}")
            await channel.send(embed=embed)
        except discord.Forbidden:
            logging.warning("Welcome: нет прав писать в канал %s", getattr(channel, "name", cid))
        except discord.HTTPException:
            logging.warning("Welcome: ошибка отправки в канал %s", getattr(channel, "name", cid))

    def _build_embed(self, member: discord.Member) -> discord.Embed:
        guild = member.guild
        lines = []
        for cat in guild.categories:
            text_channels = [c for c in cat.text_channels if c.permissions_for(guild.default_role).read_messages]
            if text_channels:
                cat_lines = []
                for c in text_channels:
                    cat_lines.append(f"• **<#{c.id}>**")
                if cat_lines:
                    lines.append(f"**{cat.name}**")
                    lines.extend(cat_lines)
                    lines.append("")

        voice_lines = []
        for vc in guild.voice_channels:
            if vc.permissions_for(guild.default_role).connect:
                voice_lines.append(f"• **{vc.name}**")
        if voice_lines:
            lines.append("**Голосовые каналы**")
            lines.extend(voice_lines)

        title = config.WELCOME_TITLE
        if config.WELCOME_CLAN_NAME:
            title = f"Добро пожаловать в {config.WELCOME_CLAN_NAME}! 🎖️"
        embed = discord.Embed(
            title=title,
            description=config.WELCOME_INTRO,
            color=discord.Color.purple(),
        )
        if lines:
            channel_text = "\n".join(lines).strip()
            if len(channel_text) > 1024:
                channel_text = channel_text[:1020] + "\n…"
            embed.add_field(name="📂 Наши каналы", value=channel_text, inline=False)
        if guild.rules_channel:
            embed.add_field(
                name="📜 Правила",
                value=f"Ознакомься с правилами сервера: {guild.rules_channel.mention}",
                inline=False,
            )
        embed.set_footer(text=config.WELCOME_FOOTER)
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
