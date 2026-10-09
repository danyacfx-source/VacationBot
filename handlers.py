"""Логирующие слушатели событий сервера.

14 чисто логирующих обработчиков, команд нет. Служебные обработчики ошибок
(on_error / on_command_error / on_app_command_error) установлены в
core.errors.install(bot) и здесь не дублируются.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

import aiohttp
import discord
from discord.ext import commands

import config
from core.timeutil import msk_stamp
from services.audit import find_audit_author
from ui import style

log = logging.getLogger(__name__)


def _embed(
    title: str | None,
    description: str | None = None,
    *,
    color: discord.Color,
    footer: str | None = None,
    now: datetime | None = None,
) -> discord.Embed:
    """style.base + корректная отметка времени (UTC, как в оригинале)."""
    embed = style.base(title, description, color=color, footer=footer)
    embed.timestamp = now or discord.utils.utcnow()
    return embed


def _who(user) -> str:
    """Значение поля «Кто изменил/создал/удалил»."""
    return f"{user.mention} {user}" if user else "Неизвестно"


def _id_stamp(prefix: str, user, time_str: str) -> str:
    """Футер вида «id участника: 123•Сегодня, в 14:05» / просто время."""
    return f"{prefix}: {user.id}•{time_str}" if user else time_str


def _channel_type(channel) -> str:
    if isinstance(channel, discord.TextChannel):
        return "text"
    if isinstance(channel, discord.VoiceChannel):
        return "voice"
    if isinstance(channel, discord.CategoryChannel):
        return "category"
    if isinstance(channel, discord.ForumChannel):
        return "announcement"
    return str(channel.type)


class LoggingHandlers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Анти-дубль голосовых логов: Discord иногда шлёт один и тот же
        # voice_state_update несколько раз подряд.
        self._voice_log_dedup: dict[tuple, float] = {}
        self._VOICE_DEDUP_SECONDS = 6
        self._VOICE_DEDUP_MAX = 500

    # ------------------------------------------------------------ служебное

    async def _send_to(
        self, channel, embed: discord.Embed, *, retries: int = 1, delay: float = 5.0
    ) -> None:
        """Отправка лог-эмбеда: один общий try/except вместо копипасты."""
        if isinstance(channel, int):
            channel = self.bot.get_channel(channel)
        if channel is None:
            return
        for attempt in range(1, retries + 1):
            try:
                await channel.send(embed=embed)
                return
            except discord.Forbidden:
                log.error("Нет прав писать в канал %s", getattr(channel, "id", channel))
                return
            except (aiohttp.ClientError, discord.HTTPException) as exc:
                if attempt >= retries:
                    log.error(
                        "Лог не отправлен в канал %s (%d попыток): %s",
                        getattr(channel, "id", channel),
                        attempt,
                        exc,
                    )
                    return
                await asyncio.sleep(delay)

    def _is_voice_duplicate(self, member, before, after) -> bool:
        key = (
            member.id,
            before.channel.id if before.channel else 0,
            after.channel.id if after.channel else 0,
            bool(after.self_mute),
            bool(after.self_deaf),
            bool(after.mute),
            bool(after.deaf),
            getattr(after, "stream", False),
            getattr(after, "video", False),
        )
        now = time.monotonic()
        last = self._voice_log_dedup.get(key)
        if last is not None and (now - last) < self._VOICE_DEDUP_SECONDS:
            log.info("voice log подавлен (дубль) для %s", member)
            return True

        self._voice_log_dedup[key] = now
        if len(self._voice_log_dedup) > self._VOICE_DEDUP_MAX:
            cutoff = now - self._VOICE_DEDUP_SECONDS
            for stale in [k for k, v in self._voice_log_dedup.items() if v < cutoff]:
                del self._voice_log_dedup[stale]
        if len(self._voice_log_dedup) > self._VOICE_DEDUP_MAX:
            overflow = len(self._voice_log_dedup) - self._VOICE_DEDUP_MAX
            oldest = sorted(self._voice_log_dedup.items(), key=lambda kv: kv[1])
            for key_stale, _ in oldest[:overflow]:
                del self._voice_log_dedup[key_stale]
        return False

    async def _log_voice(self, channel, member, before, after, embed) -> None:
        if self._is_voice_duplicate(member, before, after):
            return
        await self._send_to(channel, embed, retries=3, delay=5)

    # ------------------------------------------------------------ участники

    @commands.Cog.listener()
    async def on_member_join(self, member):
        try:
            guild = member.guild
            if not guild:
                return

            if not member.bot and config.JOIN_ROLES:
                for role_id in config.JOIN_ROLES:
                    role = guild.get_role(role_id)
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
                    except Exception as e:
                        log.error(
                            "Ошибка выдачи роли %s участнику %s: %s", role.name, member, e
                        )

            embed = _embed(
                "👋 Участник присоединился",
                f"{member.mention} ({member})",
                color=style.SUCCESS,
                footer=f"Участников: {guild.member_count}",
            )
            style.field(embed, "ID", str(member.id), inline=True)
            style.field(
                embed,
                "Аккаунт создан",
                f"<t:{int(member.created_at.timestamp())}:R>",
                inline=True,
            )
            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)

            await self._send_to(guild.get_channel(config.JOIN_LOG_CHANNEL), embed)
        except Exception as e:
            log.error("on_member_join error: %s", e)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        try:
            guild = member.guild
            if not guild:
                return

            channel = guild.get_channel(config.MODERATION_LOG_CHANNEL)
            if not channel:
                return

            moderator, entry = await find_audit_author(
                guild, discord.AuditLogAction.kick, member, limit=5
            )
            reason = (entry.reason or "Не указана") if entry else "Не указана"

            now = discord.utils.utcnow()
            time_display = msk_stamp(now)

            if moderator:
                mod_text = f"{moderator.mention} ({moderator})"
                title = "Кик выдан"
                desc = (
                    f"{mod_text} выписывает путёвку на банановый остров "
                    f"пользователю {member.mention} ({member})"
                )
            else:
                title = "Участник покинул сервер"
                desc = f"{member.mention} ({member})"

            embed = _embed(
                title,
                desc,
                color=style.WARNING,
                footer=f"id участника: {member.id}•{time_display}",
                now=now,
            )

            style.field(embed, "Причина", reason)

            roles = [r.mention for r in member.roles if r != guild.default_role]
            style.field(embed, "Роли", ", ".join(roles) if roles else "@everyone")

            embed.set_thumbnail(url=member.display_avatar.url)
            await self._send_to(channel, embed)
        except Exception as e:
            log.error("on_member_remove error: %s", e)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        try:
            channel = guild.get_channel(config.MODERATION_LOG_CHANNEL)
            if not channel:
                return

            moderator, entry = await find_audit_author(
                guild, discord.AuditLogAction.ban, user, limit=5
            )
            reason = (entry.reason or "Не указана") if entry else "Не указана"

            now = discord.utils.utcnow()
            time_display = msk_stamp(now)

            mod_text = f"{moderator.mention} ({moderator})" if moderator else "Система"

            embed = _embed(
                "Блокировка выдана",
                (
                    f"{mod_text} выписывает путёвку на банановый остров "
                    f"пользователю {user.mention} ({user})"
                ),
                color=discord.Color.dark_red(),
                footer=f"id участника: {user.id}•{time_display}",
                now=now,
            )

            style.field(embed, "Причина", reason)

            member = guild.get_member(user.id)
            roles = (
                [r.mention for r in member.roles if r != guild.default_role]
                if member
                else []
            )
            style.field(embed, "Роли", ", ".join(roles) if roles else "@everyone")

            embed.set_thumbnail(url=user.display_avatar.url)
            await self._send_to(channel, embed)
        except Exception as e:
            log.error("on_member_ban error: %s", e)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
            if before.guild is None:
                return

            guild = before.guild

            # Timeout logging
            if before.timed_out_until != after.timed_out_until:
                channel = guild.get_channel(config.MODERATION_LOG_CHANNEL)
                if channel:
                    moderator, _ = await find_audit_author(
                        guild, discord.AuditLogAction.member_update, after, limit=5
                    )

                    if after.timed_out_until and (
                        not before.timed_out_until
                        or after.timed_out_until > before.timed_out_until
                    ):
                        duration = after.timed_out_until - discord.utils.utcnow()
                        embed = _embed(
                            "🔇 Участник заглушен",
                            f"{after.mention} ({after.id})",
                            color=style.WARNING,
                        )
                        style.field(
                            embed,
                            "Длительность",
                            str(duration).split(".")[0],
                            inline=True,
                        )
                        if moderator:
                            style.field(
                                embed,
                                "Модератор",
                                f"{moderator} ({moderator.id})",
                                inline=True,
                            )
                        await self._send_to(channel, embed)
                    elif not after.timed_out_until and before.timed_out_until:
                        embed = _embed(
                            "🔊 Участник разглушен",
                            f"{after.mention} ({after.id})",
                            color=style.SUCCESS,
                        )
                        if moderator:
                            style.field(
                                embed,
                                "Модератор",
                                f"{moderator} ({moderator.id})",
                                inline=True,
                            )
                        await self._send_to(channel, embed)

            # Role add/remove logging
            old_roles = set(r.id for r in before.roles)
            new_roles = set(r.id for r in after.roles)
            added_roles = new_roles - old_roles
            removed_roles = old_roles - new_roles

            if added_roles or removed_roles:
                role_channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
                if not role_channel:
                    return

                now = discord.utils.utcnow()
                time_str = msk_stamp(now)

                moderator, _ = await find_audit_author(
                    guild,
                    discord.AuditLogAction.member_role_update,
                    after,
                    limit=10,
                )

                desc_parts = []
                if added_roles:
                    desc_parts.append("Добавлены роли")
                if removed_roles:
                    desc_parts.append("Удалены роли")

                embed = _embed(
                    f"Роли участника {after.display_name} (@{after.name}) были изменены",
                    "\n".join(desc_parts),
                    color=style.INFO,
                    footer=f"id участника: {after.id}•{time_str}",
                    now=now,
                )

                if added_roles:
                    style.field(
                        embed,
                        "Добавлены роли",
                        ", ".join(f"<@&{rid}>" for rid in added_roles),
                    )

                if removed_roles:
                    style.field(
                        embed,
                        "Удалены роли",
                        ", ".join(f"<@&{rid}>" for rid in removed_roles),
                    )

                style.field(embed, "Кто изменил", _who(moderator), inline=True)
                embed.set_thumbnail(url=after.display_avatar.url)

                await self._send_to(role_channel, embed)
        except Exception as e:
            log.error("on_member_update error: %s", e)

    # ------------------------------------------------------------ роли

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        try:
            guild = role.guild
            channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not channel:
                return

            embed = _embed(
                "🔵 Роль создана",
                f"{role.mention} ({role.name})",
                color=discord.Color.blue(),
            )
            style.field(embed, "ID", str(role.id), inline=True)
            style.field(embed, "Цвет", str(role.color), inline=True)
            style.field(
                embed,
                "Отображаемая отдельно",
                "Да" if role.hoist else "Нет",
                inline=True,
            )

            await self._send_to(channel, embed)
        except Exception as e:
            log.error("on_guild_role_create error: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        try:
            guild = after.guild
            channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not channel:
                return

            changes = []
            if before.name != after.name:
                changes.append(
                    f"**Имя роли изменено:** `{before.name}` → `{after.name}`"
                )
            if before.icon != after.icon:
                changes.append("**Иконка роли изменена**")
            if before.color != after.color:
                changes.append(f"**Цвет изменён:** `{before.color}` → `{after.color}`")
            if before.hoist != after.hoist:
                val = "Да" if after.hoist else "Нет"
                changes.append(f"**Отображаемая отдельно:** {val}")
            if before.mentionable != after.mentionable:
                val = "Да" if after.mentionable else "Нет"
                changes.append(f"**Упоминаемая:** {val}")

            if not changes:
                return

            now = discord.utils.utcnow()
            time_str = msk_stamp(now)

            moderator, _ = await find_audit_author(
                guild, discord.AuditLogAction.role_update, after, limit=5
            )

            embed = _embed(
                f"Роль {after.mention} была изменена",
                "\n".join(changes),
                color=style.EVENT,
                footer=_id_stamp("id участника", moderator, time_str),
                now=now,
            )
            style.field(embed, "Кто изменил", _who(moderator), inline=True)

            await self._send_to(channel, embed)
        except Exception as e:
            log.error("on_guild_role_update error: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        try:
            guild = role.guild
            channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not channel:
                return

            embed = _embed(
                "⚫ Роль удалена", f"**{role.name}**", color=discord.Color.dark_grey()
            )
            style.field(embed, "ID", str(role.id), inline=True)
            style.field(embed, "Цвет", str(role.color), inline=True)
            style.field(embed, "Участников с ролью", str(len(role.members)), inline=True)

            await self._send_to(channel, embed)
        except Exception as e:
            log.error("on_guild_role_delete error: %s", e)

    # ------------------------------------------------------------ каналы

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        try:
            guild = channel.guild
            log_channel = guild.get_channel(config.CHANNEL_LOG_CHANNEL)
            if not log_channel:
                return

            now = discord.utils.utcnow()
            time_str = msk_stamp(now)

            moderator, _ = await find_audit_author(
                guild, discord.AuditLogAction.channel_create, channel, limit=5
            )

            embed = _embed(
                f"Канал {channel.name} ({channel.id}) был создан",
                color=style.SUCCESS,
                footer=_id_stamp("ID модератора", moderator, time_str),
                now=now,
            )
            style.field(embed, "Кто создал", _who(moderator), inline=True)
            style.field(embed, "Тип канала", _channel_type(channel), inline=True)

            await self._send_to(log_channel, embed)
        except Exception as e:
            log.error("on_guild_channel_create error: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        try:
            guild = channel.guild
            log_channel = guild.get_channel(config.CHANNEL_LOG_CHANNEL)
            if not log_channel:
                return

            now = discord.utils.utcnow()
            time_str = msk_stamp(now)

            moderator, _ = await find_audit_author(
                guild, discord.AuditLogAction.channel_delete, channel, limit=5
            )

            embed = _embed(
                f"Канал {channel.name} ({channel.id}) был удалён",
                color=style.ERROR,
                footer=_id_stamp("ID модератора", moderator, time_str),
                now=now,
            )
            style.field(embed, "Кто удалил", _who(moderator), inline=True)
            style.field(embed, "Тип канала", _channel_type(channel), inline=True)

            await self._send_to(log_channel, embed)
        except Exception as e:
            log.error("on_guild_channel_delete error: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        try:
            guild = after.guild
            log_channel = guild.get_channel(config.CHANNEL_LOG_CHANNEL)

            if isinstance(after, discord.VoiceChannel) and before.name != after.name:
                vc_log = guild.get_channel(config.VOICE_LOG_CHANNEL)
                if vc_log:
                    now = discord.utils.utcnow()
                    embed = _embed(
                        f"Канал {after.name} ({after.id}) был обновлён",
                        f"`{before.name}` → `{after.name}`",
                        color=style.INFO,
                        footer=msk_stamp(now),
                        now=now,
                    )
                    await self._send_to(vc_log, embed)

            if not log_channel:
                return

            now = discord.utils.utcnow()
            time_str = msk_stamp(now)

            moderator, _ = await find_audit_author(
                guild, discord.AuditLogAction.channel_update, after, limit=5
            )

            changes = []
            if before.name != after.name:
                changes.append(f"**Название:** `{before.name}` → `{after.name}`")
            if before.category != after.category:
                old_cat = before.category.name if before.category else "Нет"
                new_cat = after.category.name if after.category else "Нет"
                changes.append(f"**Категория:** `{old_cat}` → `{new_cat}`")
            if hasattr(before, "topic") and before.topic != after.topic:
                old_topic = before.topic or "Нет"
                new_topic = after.topic or "Нет"
                changes.append(f"**Топик:** `{old_topic[:50]}` → `{new_topic[:50]}`")
            if hasattr(before, "nsfw") and before.nsfw != after.nsfw:
                changes.append(f"**NSFW:** `{before.nsfw}` → `{after.nsfw}`")
            if (
                hasattr(before, "slowmode_delay")
                and before.slowmode_delay != after.slowmode_delay
            ):
                changes.append(
                    f"**Слоумод:** `{before.slowmode_delay}с` → `{after.slowmode_delay}с`"
                )
            if hasattr(before, "overwrites") and dict(before.overwrites) != dict(
                after.overwrites
            ):
                changes.append("**Разрешения изменены**")

            if not changes:
                return

            embed = _embed(
                f"Канал {after.name} ({after.id}) был обновлён",
                color=style.ACCENT,
                footer=_id_stamp("ID модератора", moderator, time_str),
                now=now,
            )
            style.field(embed, "Кто обновил", _who(moderator), inline=True)
            style.field(embed, "Изменения", "\n".join(changes))

            await self._send_to(log_channel, embed)
        except Exception as e:
            log.error("on_guild_channel_update error: %s", e)

    # ------------------------------------------------------------ голосовые

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            guild = member.guild
            if not guild:
                return

            log_channel = guild.get_channel(config.VOICE_LOG_CHANNEL)
            if not log_channel:
                return

            before_channel = before.channel
            after_channel = after.channel

            now = discord.utils.utcnow()
            time_str = msk_stamp(now)

            def get_user_status(member):
                states = []
                if member.bot:
                    states.append("бот")
                if member.guild_permissions.administrator:
                    states.append("админ")
                return ", ".join(states) if states else "неизвестно"

            if not before_channel and after_channel:
                status = get_user_status(member)
                embed = _embed(
                    f"Участник {member.display_name} (@{member.name}) зашёл в канал",
                    f"**{after_channel.name}** ({status})",
                    color=style.SUCCESS,
                    footer=f"id участника: {member.id}•{time_str}",
                    now=now,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                await self._log_voice(log_channel, member, before, after, embed)

            elif before_channel and not after_channel:
                status = get_user_status(member)
                embed = _embed(
                    f"Участник {member.display_name} (@{member.name}) покинул канал",
                    f"**{before_channel.name}** ({status})",
                    color=style.ERROR,
                    footer=f"id участника: {member.id}•{time_str}",
                    now=now,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                await self._log_voice(log_channel, member, before, after, embed)

            elif before_channel and after_channel and before_channel.id != after_channel.id:
                status = get_user_status(member)
                embed = _embed(
                    f"Участник {member.display_name} (@{member.name}) переместился",
                    f"**{before_channel.name}** → **{after_channel.name}** ({status})",
                    color=style.INFO,
                    footer=f"id участника: {member.id}•{time_str}",
                    now=now,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                await self._log_voice(log_channel, member, before, after, embed)

            elif before_channel and after_channel and before_channel.id == after_channel.id:
                changes = []
                if before.self_mute != after.self_mute:
                    changes.append(
                        f"Self-Mute: {'Да' if after.self_mute else 'Нет'}"
                    )
                if before.self_deaf != after.self_deaf:
                    changes.append(
                        f"Self-Deaf: {'Да' if after.self_deaf else 'Нет'}"
                    )
                if before.mute != after.mute:
                    changes.append(f"Мьют: {'Да' if after.mute else 'Нет'}")
                if before.deaf != after.deaf:
                    changes.append(f"Глух: {'Да' if after.deaf else 'Нет'}")
                if getattr(before, "stream", False) != getattr(after, "stream", False):
                    changes.append(
                        f"Стрим: {'Да' if getattr(after, 'stream', False) else 'Нет'}"
                    )
                if getattr(before, "video", False) != getattr(after, "video", False):
                    changes.append(
                        f"Видео: {'Да' if getattr(after, 'video', False) else 'Нет'}"
                    )

                if changes:
                    status = get_user_status(member)
                    embed = _embed(
                        f"Участник {member.display_name} (@{member.name}) изменил состояние",
                        f"**{after_channel.name}** ({status})\n" + "\n".join(changes),
                        color=style.NEUTRAL,
                        footer=f"id участника: {member.id}•{time_str}",
                        now=now,
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    await self._log_voice(log_channel, member, before, after, embed)

        except Exception as e:
            log.error("on_voice_state_update error: %s", e)

    # ------------------------------------------------------------ сообщения

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author.bot:
                return
            if message.author.id in config.BLOCKED_USERS:
                try:
                    await message.delete()
                except discord.Forbidden:
                    log.debug("Нет прав удалить сообщение %s", message.id)
                except Exception as e:
                    log.debug("Не удалось удалить сообщение %s: %s", message.id, e)
        except Exception as e:
            log.error("on_message error: %s", e)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        try:
            if message.author.bot:
                return

            now = discord.utils.utcnow()
            time_display = msk_stamp(now)

            content = message.content[:1900] if message.content else "_Пусто_"
            if message.attachments:
                attachments = "\n".join(
                    f"• {a.filename}" for a in message.attachments[:5]
                )
                content += f"\n\n**Вложения:**\n{attachments}"

            embed = _embed(
                "Сообщение было удалено",
                f"**Содержание:**\n{content}",
                color=style.ERROR,
                footer=f"id сообщения: {message.id}•{time_display}",
                now=now,
            )
            style.field(
                embed,
                "Автор",
                f"{message.author.display_name} ({message.author})",
                inline=True,
            )
            style.field(
                embed,
                "Канал",
                f"{message.channel.mention} ({message.channel})",
                inline=True,
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)

            await self._send_to(self.bot.get_channel(config.MESSAGE_LOG_CHANNEL), embed)
        except Exception as e:
            log.error("on_message_delete error: %s", e)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        try:
            if before.author.bot:
                return
            if before.content == after.content:
                return

            embed = _embed(
                "✏️ Сообщение изменено", color=style.ACCENT, footer=None
            )
            style.field(embed, "Автор", f"{before.author} ({before.author.id})", inline=True)
            style.field(embed, "Канал", before.channel.mention, inline=True)

            old_content = before.content[:1024] if before.content else "*Пусто*"
            new_content = after.content[:1024] if after.content else "*Пусто*"
            style.field(embed, "Было", old_content)
            style.field(embed, "Стало", new_content)

            embed.set_thumbnail(url=before.author.display_avatar.url)
            embed.set_footer(text=f"ID сообщения: {before.id}")
            style.field(embed, "Ссылка", f"[Перейти]({before.jump_url})", inline=True)

            await self._send_to(self.bot.get_channel(config.MESSAGE_LOG_CHANNEL), embed)
        except Exception as e:
            log.error("on_message_edit error: %s", e)


async def setup(bot):
    await bot.add_cog(LoggingHandlers(bot))
