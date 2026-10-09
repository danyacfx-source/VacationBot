"""Самовосстанавливающаяся панель «Выбери направление»: реакции выдают роли."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

import config
from ui import style

log = logging.getLogger(__name__)

PANEL_KEY = "direction_panel_message_id"
PANEL_FOOTER = "Нажми на реакцию под этим сообщением, чтобы выбрать направление"


class DirectionRolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._started_panel = False
        self._footer = PANEL_FOOTER

    # ------------------------------------------------------------ состояние

    async def _panel_message_id(self) -> int | None:
        value = await self.bot.state.get(PANEL_KEY)
        return value if isinstance(value, int) else None

    async def _remember_panel(self, message_id: int) -> None:
        await self.bot.state.set(PANEL_KEY, message_id)

    # ------------------------------------------------------------ панель

    async def _ensure_panel(self) -> None:
        channel = self.bot.get_channel(config.DIRECTION_CHANNEL)
        if channel is None:
            log.warning("DirectionRoles: канал выбора направления не найден (%s)", config.DIRECTION_CHANNEL)
            return
        roles = config.DIRECTION_ROLES
        if not roles:
            return
        desc = "\n".join(f"{emoji} — **{name}**" for emoji, name in roles) + "\n\nМожно выбрать несколько направлений."
        embed = style.base(
            "🎯 Выбери направление",
            desc,
            color=discord.Color.blurple(),
            footer=self._footer,
        )

        panel_id = await self._panel_message_id()
        if panel_id:
            try:
                msg = await channel.fetch_message(panel_id)
            except discord.HTTPException:
                msg = None
            if msg is not None:
                await self._refresh_panel(msg, embed, roles)
                return

        async for old in channel.history(limit=20):
            if old.author.id != self.bot.user.id or not old.embeds:
                continue
            footer = (old.embeds[0].footer.text or "").strip()
            if footer != self._footer:
                continue
            await self._refresh_panel(old, embed, roles)
            await self._remember_panel(old.id)
            return

        try:
            msg = await channel.send(embed=embed)
        except discord.HTTPException as exc:
            log.warning("DirectionRoles: не удалось отправить панель: %s", exc)
            return
        await self._sync_reactions(msg, roles)
        await self._remember_panel(msg.id)

    async def _refresh_panel(self, msg: discord.Message, embed: discord.Embed, roles) -> None:
        try:
            await msg.edit(embed=embed)
        except discord.HTTPException as exc:
            log.warning("DirectionRoles: не удалось обновить панель: %s", exc)
        await self._sync_reactions(msg, roles)

    @staticmethod
    async def _sync_reactions(msg: discord.Message, roles) -> None:
        wanted = {emoji for emoji, _ in roles}
        current = {r.emoji for r in msg.reactions if isinstance(r.emoji, str)}
        for emoji in wanted - current:
            try:
                await msg.add_reaction(emoji)
            except discord.HTTPException as exc:
                log.warning("DirectionRoles: не удалось поставить реакцию %s: %s", emoji, exc)

    # ------------------------------------------------------------ слушатели

    @commands.Cog.listener()
    async def on_ready(self):
        if self._started_panel:
            return
        self._started_panel = True
        asyncio.create_task(self._ensure_panel(), name="direction_roles:ensure_panel")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != await self._panel_message_id():
            return
        await self._toggle_role(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != await self._panel_message_id():
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
            log.warning("DirectionRoles: роль %r не найдена на сервере", name)
            return
        try:
            if add and role not in member.roles:
                await member.add_roles(role, reason="Выбор направления по реакции")
            elif not add and role in member.roles:
                await member.remove_roles(role, reason="Снятие направления по реакции")
        except discord.Forbidden:
            log.warning("DirectionRoles: нет прав менять роль %s", name)
        except discord.HTTPException:
            log.warning("DirectionRoles: ошибка смены роли %s", name)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DirectionRolesCog(bot))
