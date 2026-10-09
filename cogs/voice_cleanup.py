"""Удаление войс-каналов в запрещённых категориях (config.BLOCKED_VOICE_CATEGORIES)."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

import config

log = logging.getLogger(__name__)

VOICE_TYPES = (discord.ChannelType.voice, discord.ChannelType.stage_voice)


def is_blocked_voice(channel):
    return (
        channel.category_id in config.BLOCKED_VOICE_CATEGORIES
        and channel.type in VOICE_TYPES
    )


class VoiceCleanupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.scheduler.register_interval("voice_cleanup", self.cleanup_loop, seconds=120)

    async def _cleanup_guild(self, guild):
        for cat_id in config.BLOCKED_VOICE_CATEGORIES:
            category = guild.get_channel(cat_id)
            if not category:
                continue
            for ch in list(category.channels):
                if not is_blocked_voice(ch):
                    continue
                try:
                    await ch.delete(reason="Войс-каналы в этой категории запрещены")
                    log.info("Удалён войс-канал %s в категории %s", ch.name, category.name)
                except discord.NotFound:
                    pass
                except Exception as e:
                    log.error("Ошибка удаления войс-канала %s: %s", ch.name, e)

    async def cleanup_loop(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self._cleanup_guild(guild)
            except Exception as e:
                log.error("Ошибка в periodic cleanup войс-каналов: %s", e)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                await self._cleanup_guild(guild)
            except Exception as e:
                log.error("Ошибка очистки войс-каналов при старте: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if not is_blocked_voice(channel):
            return
        try:
            await channel.delete(reason="Войс-каналы в этой категории запрещены")
            log.info(
                "Удалён новый войс-канал %s в категории %s",
                channel.name, channel.category.name if channel.category else "?"
            )
        except discord.NotFound:
            pass
        except Exception as e:
            log.error("Ошибка удаления нового войс-канала %s: %s", channel.name, e)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if is_blocked_voice(after):
            try:
                await after.delete(reason="Войс-каналы в этой категории запрещены")
                log.info(
                    "Удалён перемещённый войс-канал %s в категорию %s",
                    after.name, after.category.name if after.category else "?"
                )
            except discord.NotFound:
                pass
            except Exception as e:
                log.error("Ошибка удаления перемещённого войс-канала %s: %s", after.name, e)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceCleanupCog(bot))
