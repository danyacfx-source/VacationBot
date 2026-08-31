import sys
import os
import asyncio
import logging
import time
import traceback
from datetime import timedelta

import discord
from discord.ext import commands
import aiohttp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import send_log
import config


class LoggingHandlers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Анти-дубль голосовых логов: Discord иногда шлёт один и тот же
        # voice_state_update несколько раз подряд.
        self._voice_log_dedup = {}
        self._VOICE_DEDUP_SECONDS = 6

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
                        logging.info(
                            "Выдана роль %s участнику %s (%s)", role.name, member, member.id
                        )
                    except discord.Forbidden:
                        logging.error(
                            "Нет прав выдать роль %s участнику %s (%s)",
                            role.name, member, member.id,
                        )
                    except Exception as e:
                        logging.error(
                            "Ошибка выдачи роли %s участнику %s: %s",
                            role.name, member, e,
                        )

            channel = guild.get_channel(config.JOIN_LOG_CHANNEL)
            if not channel:
                return

            embed = discord.Embed(
                title="👋 Участник присоединился",
                description=f"{member.mention} ({member})",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="ID", value=str(member.id), inline=True)
            embed.add_field(
                name="Аккаунт создан",
                value=f"<t:{int(member.created_at.timestamp())}:R>",
                inline=True
            )
            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)
            embed.set_footer(text=f"Участников: {guild.member_count}")

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_member_join error: %s", e)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        try:
            guild = member.guild
            if not guild:
                return

            channel = guild.get_channel(config.MODERATION_LOG_CHANNEL)
            if not channel:
                return

            moderator = None
            reason = "Не указана"

            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                    if entry.target and entry.target.id == member.id:
                        moderator = entry.user
                        reason = entry.reason or "Не указана"
                        break
            except discord.Forbidden:
                pass

            now = discord.utils.utcnow()
            moscow_ts = now.timestamp() + 3 * 3600
            import datetime as _dt
            time_str = _dt.datetime.utcfromtimestamp(moscow_ts).strftime("%d.%m.%Y в %H:%M")
            is_today = _dt.datetime.utcfromtimestamp(moscow_ts).date() == _dt.datetime.utcfromtimestamp(now.timestamp()).date()
            time_display = f"Сегодня, в {_dt.datetime.utcfromtimestamp(moscow_ts).strftime('%H:%M')}" if is_today else time_str

            if moderator:
                mod_text = f"{moderator.mention} ({moderator})"
                title = "Кик выдан"
                desc = f"{mod_text} выписывает путёвку на банановый остров пользователю {member.mention} ({member})"
            else:
                title = "Участник покинул сервер"
                desc = f"{member.mention} ({member})"

            embed = discord.Embed(
                title=title,
                description=desc,
                color=discord.Color.orange(),
                timestamp=now,
            )

            embed.add_field(name="Причина", value=reason, inline=False)

            roles = [r.mention for r in member.roles if r != guild.default_role]
            if roles:
                embed.add_field(name="Роли", value=", ".join(roles), inline=False)
            else:
                embed.add_field(name="Роли", value="@everyone", inline=False)

            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"id участника: {member.id}•{time_display}")

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_member_remove error: %s", e)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        try:
            channel = guild.get_channel(config.MODERATION_LOG_CHANNEL)
            if not channel:
                return

            moderator = None
            reason = "Не указана"

            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                    if entry.target and entry.target.id == user.id:
                        moderator = entry.user
                        reason = entry.reason or "Не указана"
                        break
            except discord.Forbidden:
                pass

            now = discord.utils.utcnow()
            moscow_ts = now.timestamp() + 3 * 3600
            import datetime as _dt
            time_str = _dt.datetime.utcfromtimestamp(moscow_ts).strftime("%d.%m.%Y в %H:%M")
            is_today = _dt.datetime.utcfromtimestamp(moscow_ts).date() == _dt.datetime.utcfromtimestamp(now.timestamp()).date()
            time_display = f"Сегодня, в {_dt.datetime.utcfromtimestamp(moscow_ts).strftime('%H:%M')}" if is_today else time_str

            if moderator:
                mod_text = f"{moderator.mention} ({moderator})"
            else:
                mod_text = "Система"

            embed = discord.Embed(
                title="Блокировка выдана",
                description=(
                    f"{mod_text} выписывает путёвку на банановый остров "
                    f"пользователю {user.mention} ({user})"
                ),
                color=discord.Color.dark_red(),
                timestamp=now,
            )

            embed.add_field(name="Причина", value=reason, inline=False)

            member = guild.get_member(user.id)
            if member:
                roles = [r.mention for r in member.roles if r != guild.default_role]
            else:
                roles = []
            if roles:
                embed.add_field(name="Роли", value=", ".join(roles), inline=False)
            else:
                embed.add_field(name="Роли", value="@everyone", inline=False)

            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"id участника: {user.id}•{time_display}")

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_member_ban error: %s", e)

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
                    moderator = None
                    try:
                        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                            if entry.target and entry.target.id == after.id:
                                moderator = entry.user
                                break
                    except discord.Forbidden:
                        pass

                    if after.timed_out_until and (not before.timed_out_until or after.timed_out_until > before.timed_out_until):
                        duration = after.timed_out_until - discord.utils.utcnow()
                        embed = discord.Embed(
                            title="🔇 Участник заглушен",
                            description=f"{after.mention} ({after.id})",
                            color=discord.Color.orange(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="Длительность", value=str(duration).split(".")[0], inline=True)
                        if moderator:
                            embed.add_field(name="Модератор", value=f"{moderator} ({moderator.id})", inline=True)
                        await channel.send(embed=embed)
                    elif not after.timed_out_until and before.timed_out_until:
                        embed = discord.Embed(
                            title="🔊 Участник разглушен",
                            description=f"{after.mention} ({after.id})",
                            color=discord.Color.green(),
                            timestamp=discord.utils.utcnow()
                        )
                        if moderator:
                            embed.add_field(name="Модератор", value=f"{moderator} ({moderator.id})", inline=True)
                        await channel.send(embed=embed)

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
                moscow_ts = now.timestamp() + 3 * 3600
                import datetime as _dt
                time_str = _dt.datetime.utcfromtimestamp(moscow_ts).strftime("%d.%m.%Y в %H:%M")

                moderator = None
                try:
                    async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.member_role_update):
                        if entry.target and entry.target.id == after.id:
                            moderator = entry.user
                            break
                except discord.Forbidden:
                    pass

                desc_parts = []
                if added_roles:
                    desc_parts.append("Добавлены роли")
                if removed_roles:
                    desc_parts.append("Удалены роли")

                embed = discord.Embed(
                    title=f"Роли участника {after.display_name} (@{after.name}) были изменены",
                    description="\n".join(desc_parts),
                    color=discord.Color.blurple(),
                    timestamp=now,
                )

                if added_roles:
                    role_names = [f"<@&{rid}>" for rid in added_roles]
                    embed.add_field(name="Добавлены роли", value=", ".join(role_names), inline=False)

                if removed_roles:
                    role_names = [f"<@&{rid}>" for rid in removed_roles]
                    embed.add_field(name="Удалены роли", value=", ".join(role_names), inline=False)

                embed.add_field(
                    name="Кто изменил",
                    value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                    inline=True,
                )

                embed.set_thumbnail(url=after.display_avatar.url)
                embed.set_footer(text=f"id участника: {after.id}•{time_str}")

                await role_channel.send(embed=embed)
        except Exception as e:
            logging.error("on_member_update error: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        try:
            guild = role.guild
            channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not channel:
                return

            embed = discord.Embed(
                title="🔵 Роль создана",
                description=f"{role.mention} ({role.name})",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="ID", value=str(role.id), inline=True)
            embed.add_field(name="Цвет", value=str(role.color), inline=True)
            embed.add_field(name="Отображаемая отдельно", value="Да" if role.hoist else "Нет", inline=True)

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_role_create error: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        try:
            guild = after.guild
            channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not channel:
                return

            changes = []
            if before.name != after.name:
                changes.append(f"**Имя роли изменено:** `{before.name}` → `{after.name}`")
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
            moscow_ts = now.timestamp() + 3 * 3600
            import datetime as _dt
            time_str = _dt.datetime.utcfromtimestamp(moscow_ts).strftime("%d.%m.%Y в %H:%M")

            moderator = None
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.role_update):
                    if entry.target and entry.target.id == after.id:
                        moderator = entry.user
                        break
            except discord.Forbidden:
                pass

            embed = discord.Embed(
                title=f"Роль {after.mention} была изменена",
                description="\n".join(changes),
                color=discord.Color.purple(),
                timestamp=now,
            )
            embed.add_field(
                name="Кто изменил",
                value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                inline=True,
            )

            if moderator:
                embed.set_footer(text=f"id участника: {moderator.id}•{time_str}")
            else:
                embed.set_footer(text=time_str)

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_role_update error: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        try:
            guild = role.guild
            channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not channel:
                return

            embed = discord.Embed(
                title="⚫ Роль удалена",
                description=f"**{role.name}**",
                color=discord.Color.dark_grey(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="ID", value=str(role.id), inline=True)
            embed.add_field(name="Цвет", value=str(role.color), inline=True)
            embed.add_field(name="Участников с ролью", value=str(len(role.members)), inline=True)

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_role_delete error: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        try:
            guild = channel.guild
            log_channel = guild.get_channel(config.CHANNEL_LOG_CHANNEL)
            if not log_channel:
                return

            now = discord.utils.utcnow()
            moscow_ts = now.timestamp() + 3 * 3600
            import datetime as _dt
            time_str = _dt.datetime.utcfromtimestamp(moscow_ts).strftime("%d.%m.%Y в %H:%M")

            moderator = None
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_create):
                    if entry.target and entry.target.id == channel.id:
                        moderator = entry.user
                        break
            except discord.Forbidden:
                pass

            channel_type = "text" if isinstance(channel, discord.TextChannel) else \
                           "voice" if isinstance(channel, discord.VoiceChannel) else \
                           "category" if isinstance(channel, discord.CategoryChannel) else \
                           "announcement" if isinstance(channel, discord.ForumChannel) else str(channel.type)

            embed = discord.Embed(
                title=f"Канал {channel.name} ({channel.id}) был создан",
                color=discord.Color.green(),
                timestamp=now,
            )
            embed.add_field(
                name="Кто создал",
                value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                inline=True,
            )
            embed.add_field(name="Тип канала", value=channel_type, inline=True)

            if moderator:
                embed.set_footer(text=f"ID модератора: {moderator.id}•{time_str}")
            else:
                embed.set_footer(text=time_str)

            await log_channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_channel_create error: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        try:
            guild = channel.guild
            log_channel = guild.get_channel(config.CHANNEL_LOG_CHANNEL)
            if not log_channel:
                return

            now = discord.utils.utcnow()
            moscow_ts = now.timestamp() + 3 * 3600
            import datetime as _dt
            time_str = _dt.datetime.utcfromtimestamp(moscow_ts).strftime("%d.%m.%Y в %H:%M")

            moderator = None
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
                    if entry.target and entry.target.id == channel.id:
                        moderator = entry.user
                        break
            except discord.Forbidden:
                pass

            channel_type = "text" if isinstance(channel, discord.TextChannel) else \
                           "voice" if isinstance(channel, discord.VoiceChannel) else \
                           "category" if isinstance(channel, discord.CategoryChannel) else \
                           "announcement" if isinstance(channel, discord.ForumChannel) else str(channel.type)

            embed = discord.Embed(
                title=f"Канал {channel.name} ({channel.id}) был удалён",
                color=discord.Color.red(),
                timestamp=now,
            )
            embed.add_field(
                name="Кто удалил",
                value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                inline=True,
            )
            embed.add_field(name="Тип канала", value=channel_type, inline=True)

            if moderator:
                embed.set_footer(text=f"ID модератора: {moderator.id}•{time_str}")
            else:
                embed.set_footer(text=time_str)

            await log_channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_channel_delete error: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        try:
            guild = after.guild
            log_channel = guild.get_channel(config.CHANNEL_LOG_CHANNEL)

            if isinstance(after, discord.VoiceChannel) and before.name != after.name:
                vc_log = guild.get_channel(config.VOICE_LOG_CHANNEL)
                if vc_log:
                    now = discord.utils.utcnow()
                    moscow_ts = now.timestamp() + 3 * 3600
                    import datetime as _dt
                    time_str = _dt.datetime.utcfromtimestamp(moscow_ts).strftime("%d.%m.%Y в %H:%M")
                    embed = discord.Embed(
                        title=f"Канал {after.name} ({after.id}) был обновлён",
                        description=f"`{before.name}` → `{after.name}`",
                        color=discord.Color.blurple(),
                        timestamp=now,
                    )
                    embed.set_footer(text=time_str)
                    await vc_log.send(embed=embed)

            if not log_channel:
                return

            now = discord.utils.utcnow()
            moscow_ts = now.timestamp() + 3 * 3600
            import datetime as _dt
            time_str = _dt.datetime.utcfromtimestamp(moscow_ts).strftime("%d.%m.%Y в %H:%M")

            moderator = None
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_update):
                    if entry.target and entry.target.id == after.id:
                        moderator = entry.user
                        break
            except discord.Forbidden:
                pass

            changes = []
            if before.name != after.name:
                changes.append(f"**Название:** `{before.name}` → `{after.name}`")
            if before.category != after.category:
                old_cat = before.category.name if before.category else "Нет"
                new_cat = after.category.name if after.category else "Нет"
                changes.append(f"**Категория:** `{old_cat}` → `{new_cat}`")
            if hasattr(before, 'topic') and before.topic != after.topic:
                old_topic = before.topic or "Нет"
                new_topic = after.topic or "Нет"
                changes.append(f"**Топик:** `{old_topic[:50]}` → `{new_topic[:50]}`")
            if hasattr(before, 'nsfw') and before.nsfw != after.nsfw:
                changes.append(f"**NSFW:** `{before.nsfw}` → `{after.nsfw}`")
            if hasattr(before, 'slowmode_delay') and before.slowmode_delay != after.slowmode_delay:
                changes.append(f"**Слоумод:** `{before.slowmode_delay}с` → `{after.slowmode_delay}с`")
            if hasattr(before, 'overwrites') and dict(before.overwrites) != dict(after.overwrites):
                changes.append("**Разрешения изменены**")

            if not changes:
                return

            embed = discord.Embed(
                title=f"Канал {after.name} ({after.id}) был обновлён",
                color=discord.Color.gold(),
                timestamp=now,
            )
            embed.add_field(
                name="Кто обновил",
                value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                inline=True,
            )
            embed.add_field(name="Изменения", value="\n".join(changes), inline=False)

            if moderator:
                embed.set_footer(text=f"ID модератора: {moderator.id}•{time_str}")
            else:
                embed.set_footer(text=time_str)

            await log_channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_channel_update error: %s", e)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            guild = member.guild
            if not guild:
                return

            log_channel = guild.get_channel(config.VOICE_LOG_CHANNEL)
            if not log_channel:
                return

            # Подавление дублей: одинаковое событие от того же участника
            # в течение короткого окна не отправляем повторно.
            async def dedup(embed: discord.Embed) -> bool:
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
                    logging.info(
                        "voice log подавлен (дубль) для %s", member
                    )
                    return False
                self._voice_log_dedup[key] = now
                if len(self._voice_log_dedup) > 500:
                    cutoff = now - self._VOICE_DEDUP_SECONDS
                    stale = [k for k, v in self._voice_log_dedup.items() if v < cutoff]
                    for k in stale:
                        del self._voice_log_dedup[k]
                return True

            async def send_safe(embed):
                if not await dedup(embed):
                    return
                for attempt in range(3):
                    try:
                        await log_channel.send(embed=embed)
                        return
                    except (aiohttp.ClientError, discord.HTTPException) as e:
                        if attempt < 2:
                            await asyncio.sleep(5)
                        else:
                            logging.error("voice log не отправлен (3 попытки): %s", e)

            before_channel = before.channel
            after_channel = after.channel

            now = discord.utils.utcnow()
            moscow_ts = now.timestamp() + 3 * 3600
            import datetime as _dt
            time_str = _dt.datetime.utcfromtimestamp(moscow_ts).strftime("%d.%m.%Y в %H:%M")

            def get_user_status(member):
                states = []
                if member.bot:
                    states.append("бот")
                if member.guild_permissions.administrator:
                    states.append("админ")
                return ", ".join(states) if states else "неизвестно"

            if not before_channel and after_channel:
                status = get_user_status(member)
                embed = discord.Embed(
                    title=f"Участник {member.display_name} (@{member.name}) зашёл в канал",
                    description=f"**{after_channel.name}** ({status})",
                    color=discord.Color.green(),
                    timestamp=now,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"id участника: {member.id}•{time_str}")
                await send_safe(embed)

            elif before_channel and not after_channel:
                status = get_user_status(member)
                embed = discord.Embed(
                    title=f"Участник {member.display_name} (@{member.name}) покинул канал",
                    description=f"**{before_channel.name}** ({status})",
                    color=discord.Color.red(),
                    timestamp=now,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"id участника: {member.id}•{time_str}")
                await send_safe(embed)

            elif before_channel and after_channel and before_channel.id != after_channel.id:
                status = get_user_status(member)
                embed = discord.Embed(
                    title=f"Участник {member.display_name} (@{member.name}) переместился",
                    description=(
                        f"**{before_channel.name}** → **{after_channel.name}** ({status})"
                    ),
                    color=discord.Color.blurple(),
                    timestamp=now,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"id участника: {member.id}•{time_str}")
                await send_safe(embed)

            elif before_channel and after_channel and before_channel.id == after_channel.id:
                changes = []
                if before.self_mute != after.self_mute:
                    changes.append(f"Self-Mute: {'Да' if after.self_mute else 'Нет'}")
                if before.self_deaf != after.self_deaf:
                    changes.append(f"Self-Deaf: {'Да' if after.self_deaf else 'Нет'}")
                if before.mute != after.mute:
                    changes.append(f"Мьют: {'Да' if after.mute else 'Нет'}")
                if before.deaf != after.deaf:
                    changes.append(f"Глух: {'Да' if after.deaf else 'Нет'}")
                if getattr(before, 'stream', False) != getattr(after, 'stream', False):
                    changes.append(f"Стрим: {'Да' if getattr(after, 'stream', False) else 'Нет'}")
                if getattr(before, 'video', False) != getattr(after, 'video', False):
                    changes.append(f"Видео: {'Да' if getattr(after, 'video', False) else 'Нет'}")

                if changes:
                    status = get_user_status(member)
                    embed = discord.Embed(
                        title=f"Участник {member.display_name} (@{member.name}) изменил состояние",
                        description=(
                            f"**{after_channel.name}** ({status})\n"
                            + "\n".join(changes)
                        ),
                        color=discord.Color.greyple(),
                        timestamp=now,
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text=f"id участника: {member.id}•{time_str}")
                    await send_safe(embed)

        except Exception as e:
            logging.error("on_voice_state_update error: %s", e)

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author.bot:
                return
            if message.author.id in config.BLOCKED_USERS:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                except Exception:
                    pass
        except Exception as e:
            logging.error("on_message error: %s", e)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        try:
            if message.author.bot:
                return

            channel = self.bot.get_channel(config.MESSAGE_LOG_CHANNEL)
            if not channel:
                return

            now = discord.utils.utcnow()
            moscow_ts = now.timestamp() + 3 * 3600
            import datetime as _dt
            moscow_dt = _dt.datetime.utcfromtimestamp(moscow_ts)
            is_today = moscow_dt.date() == _dt.datetime.utcfromtimestamp(now.timestamp()).date()
            time_display = f"Сегодня, в {moscow_dt.strftime('%H:%M')}" if is_today else moscow_dt.strftime("%d.%m.%Y в %H:%M")

            content = message.content[:1900] if message.content else "_Пусто_"
            if message.attachments:
                attachments = "\n".join(f"• {a.filename}" for a in message.attachments[:5])
                content += f"\n\n**Вложения:**\n{attachments}"

            embed = discord.Embed(
                title="Сообщение было удалено",
                description=f"**Содержание:**\n{content}",
                color=discord.Color.red(),
                timestamp=now,
            )
            embed.add_field(
                name="Автор",
                value=f"{message.author.display_name} ({message.author})",
                inline=True,
            )
            embed.add_field(
                name="Канал",
                value=f"{message.channel.mention} ({message.channel})",
                inline=True,
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.set_footer(text=f"id сообщения: {message.id}•{time_display}")

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_message_delete error: %s", e)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        try:
            if before.author.bot:
                return
            if before.content == after.content:
                return

            channel = self.bot.get_channel(config.MESSAGE_LOG_CHANNEL)
            if not channel:
                return

            embed = discord.Embed(
                title="✏️ Сообщение изменено",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Автор", value=f"{before.author} ({before.author.id})", inline=True)
            embed.add_field(name="Канал", value=before.channel.mention, inline=True)

            old_content = before.content[:1024] if before.content else "*Пусто*"
            new_content = after.content[:1024] if after.content else "*Пусто*"
            embed.add_field(name="Было", value=old_content, inline=False)
            embed.add_field(name="Стало", value=new_content, inline=False)

            embed.set_thumbnail(url=before.author.display_avatar.url)
            embed.set_footer(text=f"ID сообщения: {before.id}")
            embed.add_field(
                name="Ссылка",
                value=f"[Перейти]({before.jump_url})",
                inline=True
            )

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_message_edit error: %s", e)

    @commands.Cog.listener()
    async def on_error(self, event, *args, **kwargs):
        try:
            error_trace = traceback.format_exc()
            await send_log(
                self.bot,
                title=f"❌ Ошибка: {event}",
                description=f"```\n{error_trace[:1900]}\n```",
                color=discord.Color.dark_red()
            )
        except Exception as e:
            logging.error("on_error handler failed: %s", e)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        try:
            error_trace = traceback.format_exception(type(error), error, error.__traceback__)
            error_text = "".join(error_trace)[:1900]
            await send_log(
                self.bot,
                title=f"❌ Ошибка команды: {ctx.command}",
                description=(
                    f"**Команда:** `{ctx.command}`\n"
                    f"**Автор:** {ctx.author} ({ctx.author.id})\n"
                    f"**Канал:** {ctx.channel.mention}\n"
                    f"```\n{error_text}\n```"
                ),
                color=discord.Color.dark_red()
            )
        except Exception as e:
            logging.error("on_command_error handler failed: %s", e)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction, error):
        try:
            logging.error("Slash command error: %s — %s", interaction.command, error)

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Произошла ошибка при выполнении команды.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "Произошла ошибка при выполнении команды.",
                        ephemeral=True
                    )
            except Exception:
                pass

            error_trace = traceback.format_exception(type(error), error, error.__traceback__)
            error_text = "".join(error_trace)[:1900]

            await send_log(
                self.bot,
                title=f"❌ Ошибка slash-команды: {interaction.command}",
                description=(
                    f"**Команда:** `/{interaction.command}`\n"
                    f"**Автор:** {interaction.user} ({interaction.user.id})\n"
                    f"**Канал:** {interaction.channel.mention}\n"
                    f"```\n{error_text}\n```"
                ),
                color=discord.Color.dark_red()
            )
        except Exception as e:
            logging.error("on_app_command_error handler failed: %s", e)


async def setup(bot):
    await bot.add_cog(LoggingHandlers(bot))
