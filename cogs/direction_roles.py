import logging

import discord
from discord.ext import commands

import config


class DirectionRolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._panel_message_id = None
        self._started_panel = False
        self._footer = "Нажми на реакцию под этим сообщением, чтобы выбрать направление"

    async def _ensure_panel(self):
        channel = self.bot.get_channel(config.DIRECTION_CHANNEL)
        if channel is None:
            logging.warning("DirectionRoles: канал выбора направления не найден (%s)", config.DIRECTION_CHANNEL)
            return
        roles = config.DIRECTION_ROLES
        if not roles:
            return
        desc = "\n".join(f"{emoji} — **{name}**" for emoji, name in roles) + "\n\nМожно выбрать несколько направлений."
        embed = discord.Embed(
            title="🎯 Выбери направление",
            description=desc,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=self._footer)

        if self._panel_message_id:
            try:
                msg = await channel.fetch_message(self._panel_message_id)
            except discord.HTTPException:
                msg = None
            if msg is not None:
                try:
                    await msg.edit(embed=embed)
                except discord.HTTPException:
                    pass
                await self._sync_reactions(msg, roles)
                return

        async for old in channel.history(limit=20):
            if old.author.id == self.bot.user.id and old.embeds:
                footer = (old.embeds[0].footer.text or "").strip()
                if footer != self._footer:
                    continue
                msg = old
                try:
                    await msg.edit(embed=embed)
                except discord.HTTPException:
                    pass
                await self._sync_reactions(msg, roles)
                self._panel_message_id = msg.id
                return
        msg = await channel.send(embed=embed)
        await self._sync_reactions(msg, roles)
        self._panel_message_id = msg.id

    @staticmethod
    async def _sync_reactions(msg, roles):
        wanted = {emoji for emoji, _ in roles}
        current = {r.emoji for r in msg.reactions if isinstance(r.emoji, str)}
        for emoji in wanted - current:
            try:
                await msg.add_reaction(emoji)
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._started_panel:
            self._started_panel = True
            self.bot.loop.create_task(self._ensure_panel())

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != self._panel_message_id:
            return
        await self._toggle_role(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != self._panel_message_id:
            return
        await self._toggle_role(payload, add=False)

    async def _toggle_role(self, payload: discord.RawReactionActionEvent, add: bool):
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return
        emoji = payload.emoji.name
        name = None
        for e, n in config.DIRECTION_ROLES:
            if e == emoji:
                name = n
                break
        if name is None:
            return
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            logging.warning("DirectionRoles: роль %r не найдена на сервере", name)
            return
        try:
            if add and role not in member.roles:
                await member.add_roles(role, reason="Выбор направления по реакции")
            elif not add and role in member.roles:
                await member.remove_roles(role, reason="Снятие направления по реакции")
        except discord.Forbidden:
            logging.warning("DirectionRoles: нет прав менять роль %s", name)
        except discord.HTTPException:
            logging.warning("DirectionRoles: ошибка смены роли %s", name)


async def setup(bot: commands.Bot):
    await bot.add_cog(DirectionRolesCog(bot))
