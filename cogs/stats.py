"""Статистика сервера и участников: сообщения, голосовые сессии, топы."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
from ui import style

log = logging.getLogger(__name__)

MIN_SESSION_SECONDS = 5
# Максимальная длительность, которую мы записываем закрытой сессии,
# восстановленной после рестарта (участник ушёл, пока бота не было).
RESTORE_CAP_SECONDS = 6 * 3600
TOP_COLUMNS = frozenset({"messages", "voice_seconds", "voice_joins"})


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} сек."
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours == 0:
        return f"{minutes} мин."
    return f"{hours} ч. {minutes} мин."


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _member_color(member: discord.Member) -> discord.Color:
    return member.color if member.color != discord.Color.default() else discord.Color.blurple()


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        await self._restore_voice_sessions()

    # ------------------------------------------------------------ голосовые сессии

    async def _restore_voice_sessions(self) -> None:
        """Восстанавливает незакрытые войс-сессии после рестарта.

        Кто остался в канале — начало сессии берётся из started_at, время простоя
        бота не теряется. Кто ушёл, пока бота не было — сессия закрывается
        с разумной (ограниченной) длительностью.
        """
        open_sessions = await self.bot.voice_open.all_open()
        if not open_sessions:
            return

        now = discord.utils.utcnow()
        in_voice = self._voice_members()

        for user_id, (channel, started_at) in open_sessions.items():
            start = _parse_iso(started_at)
            if user_id in in_voice:
                restored = start if start is not None and start <= now else now
                await self.bot.db.execute(
                    "UPDATE voice_open SET started_at = ? WHERE user_id = ?",
                    (restored.isoformat(timespec="seconds"), user_id),
                )
                log.info(
                    "Войс-сессия %s восстановлена: канал %s, начало %s",
                    user_id,
                    channel,
                    restored.isoformat(timespec="seconds"),
                )
                continue

            await self.bot.voice_open.close(user_id)
            if start is None:
                log.warning("Войс-сессия %s без времени начала — закрыта без записи", user_id)
                continue

            await self._record_voice_session(
                user_id, channel, start, now, cap=RESTORE_CAP_SECONDS
            )
            log.info(
                "Войс-сессия %s закрыта после рестарта: канал %s, %s сек.",
                user_id,
                channel,
                int(min((now - start).total_seconds(), RESTORE_CAP_SECONDS)),
            )

    def _voice_members(self) -> dict[int, str]:
        """Участники, которые сейчас в голосовом канале: user_id -> имя канала."""
        found: dict[int, str] = {}
        for guild in self.bot.guilds:
            for member in guild.members:
                state = member.voice
                if state is not None and state.channel is not None:
                    found[member.id] = state.channel.name
        return found

    async def _finish_voice_session(self, user_id: int, now: datetime) -> None:
        """Закрывает открытую сессию и записывает её в историю.

        Общий блок завершения для LEAVE и для SWITCH.
        """
        row = await self.bot.db.fetchone(
            "SELECT channel, started_at FROM voice_open WHERE user_id = ?", (user_id,)
        )
        channel = await self.bot.voice_open.close(user_id)
        if not channel:
            return
        if row is None:
            log.warning("У %s нет записи voice_open — сессия закрыта без истории", user_id)
            return

        start = _parse_iso(row.get("started_at"))
        if start is None:
            log.warning("У %s битое started_at — сессия закрыта без истории", user_id)
            return

        await self._record_voice_session(user_id, channel, start, now)

    async def _record_voice_session(
        self,
        user_id: int,
        channel: str,
        start: datetime,
        now: datetime,
        *,
        cap: int | None = None,
    ) -> None:
        elapsed = (now - start).total_seconds()
        if elapsed <= MIN_SESSION_SECONDS:
            return
        if cap is not None:
            elapsed = min(elapsed, cap)
        secs = int(elapsed)

        db = self.bot.db
        await db.execute(
            "INSERT INTO member_stats (user_id, messages, voice_seconds, voice_joins) "
            "VALUES (?, 0, ?, 0) "
            "ON CONFLICT(user_id) DO UPDATE SET voice_seconds = voice_seconds + ?",
            (user_id, secs, secs),
        )
        await db.execute(
            'INSERT INTO voice_sessions (user_id, channel, start, "end", seconds) '
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, channel, start.isoformat(), now.isoformat(), secs),
        )

        count = int(
            await db.scalar(
                "SELECT COUNT(*) FROM voice_sessions WHERE user_id = ?", (user_id,), 0
            )
            or 0
        )
        if count > config.MAX_VOICE_SESSIONS:
            await db.execute(
                "DELETE FROM voice_sessions WHERE user_id = ? AND id NOT IN "
                "(SELECT id FROM voice_sessions WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
                (user_id, user_id, config.MAX_VOICE_SESSIONS),
            )

    # ------------------------------------------------------------ слушатели

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        now = discord.utils.utcnow()
        before_channel = before.channel
        after_channel = after.channel

        try:
            if before_channel is None and after_channel is not None:
                await self.bot.db.execute(
                    "INSERT INTO member_stats (user_id, messages, voice_seconds, voice_joins) "
                    "VALUES (?, 0, 0, 1) "
                    "ON CONFLICT(user_id) DO UPDATE SET voice_joins = voice_joins + 1",
                    (member.id,),
                )
                await self.bot.voice_open.open(member.id, after_channel.name)

            elif before_channel is not None and after_channel is None:
                await self._finish_voice_session(member.id, now)

            elif (
                before_channel is not None
                and after_channel is not None
                and before_channel.id != after_channel.id
            ):
                await self._finish_voice_session(member.id, now)
                await self.bot.voice_open.open(member.id, after_channel.name)
        except Exception:
            log.exception("Ошибка учёта голосовой сессии %s", member)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        try:
            await self.bot.db.execute(
                "INSERT INTO member_stats (user_id, messages, voice_seconds, voice_joins) "
                "VALUES (?, 1, 0, 0) "
                "ON CONFLICT(user_id) DO UPDATE SET messages = messages + 1",
                (message.author.id,),
            )
        except Exception:
            log.exception("Не удалось обновить статистику сообщений %s", message.author)

    # ------------------------------------------------------------ запросы

    async def _get_user_stats(self, user_id: int) -> dict:
        row = await self.bot.db.fetchone(
            "SELECT messages, voice_seconds, voice_joins FROM member_stats WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            return {"messages": 0, "voice_seconds": 0, "voice_joins": 0}
        return {
            "messages": int(row.get("messages") or 0),
            "voice_seconds": int(row.get("voice_seconds") or 0),
            "voice_joins": int(row.get("voice_joins") or 0),
        }

    async def _get_voice_sessions(self, user_id: int) -> list[dict]:
        rows = await self.bot.db.fetchall(
            "SELECT channel, start, \"end\", seconds FROM voice_sessions "
            "WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        return [
            {
                "channel": r["channel"],
                "start": r["start"],
                "end": r["end"],
                "seconds": int(r["seconds"] or 0),
            }
            for r in rows
        ]

    async def _get_total_stats(self) -> tuple[int, int, int]:
        row = await self.bot.db.fetchone(
            "SELECT COALESCE(SUM(messages), 0) AS messages, "
            "COALESCE(SUM(voice_seconds), 0) AS voice, COUNT(*) AS users "
            "FROM member_stats"
        )
        row = row or {}
        return int(row.get("messages") or 0), int(row.get("voice") or 0), int(row.get("users") or 0)

    async def _get_top(self, column: str, limit: int = 15) -> list[tuple[int, int]]:
        if column not in TOP_COLUMNS:
            log.warning("Запрос топа по неизвестной колонке: %s", column)
            return []
        rows = await self.bot.db.fetchall(
            f"SELECT user_id, {column} FROM member_stats WHERE {column} > 0 "
            f"ORDER BY {column} DESC LIMIT ?",
            (limit,),
        )
        return [(int(r["user_id"]), int(r[column] or 0)) for r in rows]

    @staticmethod
    def _top_channels(sessions: list[dict]) -> list[tuple[str, int]]:
        totals: dict[str, int] = {}
        for s in sessions:
            channel = s["channel"] or "—"
            totals[channel] = totals.get(channel, 0) + s["seconds"]
        return sorted(totals.items(), key=lambda x: x[1], reverse=True)[:5]

    def _add_top_channels(self, embed: discord.Embed, sessions: list[dict]) -> None:
        if not sessions:
            return
        sorted_ch = self._top_channels(sessions)
        if sorted_ch:
            lines = [f"`{ch}` — {format_duration(secs)}" for ch, secs in sorted_ch]
            style.field(embed, "🏆 Топ каналы", "\n".join(lines), inline=False)

    async def _profile_embed(self, member: discord.Member, title: str) -> discord.Embed:
        stats = await self._get_user_stats(member.id)
        sessions = await self._get_voice_sessions(member.id)

        embed = style.base(title, color=_member_color(member), footer=None, timestamp=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        style.field(embed, "💬 Сообщения", f"**{stats['messages']}**", inline=True)
        style.field(
            embed,
            "🔊 В голосе",
            f"**{format_duration(stats['voice_seconds'])}**",
            inline=True,
        )
        style.field(embed, "🚪 Заходов в войс", f"**{stats['voice_joins']}**", inline=True)
        self._add_top_channels(embed, sessions)
        return embed

    # ------------------------------------------------------------ команды

    @app_commands.command(name="сервер", description="Информация о сервере")
    async def server_info(self, interaction: discord.Interaction):
        guild = interaction.guild

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        roles = len(guild.roles) - 1
        online = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)
        bots = sum(1 for m in guild.members if m.bot)
        total = guild.member_count

        boost_tier = guild.premium_tier
        boost_count = guild.premium_subscription_count or 0

        created = guild.created_at
        age_days = (discord.utils.utcnow() - created).days

        total_msgs, total_voice, db_users = await self._get_total_stats()

        embed = style.base(
            f"📋 {guild.name}",
            color=discord.Color.blurple(),
            footer=None,
            timestamp=True,
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        style.field(
            embed,
            "👥 Участники",
            f"Всего: **{total}**\nОнлайн: **{online}**\nБотов: **{bots}**",
            inline=True,
        )
        style.field(
            embed,
            "📂 Каналы",
            f"Текстовых: **{text_channels}**\nГолосовых: **{voice_channels}**\n"
            f"Категорий: **{categories}**",
            inline=True,
        )
        style.field(
            embed,
            "🎯 Прочее",
            f"Ролей: **{roles}**\nБусты: **{boost_count}** (Ур. {boost_tier})\n"
            f"Создан: **{created.strftime('%d.%m.%Y')}** ({age_days} дн.)",
            inline=True,
        )
        style.field(
            embed,
            "📊 Статистика бота",
            f"Сообщений: **{total_msgs}**\nВ голосе: **{format_duration(total_voice)}**\n"
            f"Пользователей в базе: **{db_users}**",
            inline=False,
        )

        owner = guild.owner
        if owner:
            embed.set_footer(text=f"Владелец: {owner.display_name}", icon_url=owner.display_avatar.url)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="участник", description="Статистика участника")
    @app_commands.describe(user="Участник (по умолчанию ты)")
    async def user_info(self, interaction: discord.Interaction, user: discord.Member = None):
        member = user or interaction.user
        embed = await self._profile_embed(member, f"👤 {member.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="мойпрофиль", description="Показать твою статистику")
    async def my_profile(self, interaction: discord.Interaction):
        member = interaction.user
        embed = await self._profile_embed(member, f"🃏 {member.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="мойстатистика", description="Подробная статистика твоей активности"
    )
    @app_commands.describe(user="Участник (по умолчанию ты)")
    async def my_stats(self, interaction: discord.Interaction, user: discord.Member = None):
        member = user or interaction.user
        stats = await self._get_user_stats(member.id)
        sessions = await self._get_voice_sessions(member.id)

        voice_secs = stats["voice_seconds"]
        messages = stats["messages"]
        joins = stats["voice_joins"]

        embed = style.base(
            f"📊 Статистика: {member.display_name}",
            color=_member_color(member),
            footer=None,
            timestamp=True,
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        style.field(embed, "💬 Сообщения", f"**{messages}** сообщений", inline=True)
        style.field(
            embed,
            "🔊 Голосовые каналы",
            f"Общее время: **{format_duration(voice_secs)}**\nЗаходов: **{joins}**",
            inline=True,
        )

        if sessions:
            today_start = discord.utils.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_secs = 0
            for s in sessions:
                end = _parse_iso(s["end"])
                if end is not None and end >= today_start:
                    today_secs += s["seconds"]
            style.field(embed, "📅 Сегодня", format_duration(today_secs), inline=True)

            self._add_top_channels(embed, sessions)

        if member.joined_at:
            days = (discord.utils.utcnow() - member.joined_at).days
            avg_msgs = round(messages / days, 1) if days > 0 else 0
            avg_voice = round(voice_secs / days, 1) if days > 0 else 0
            style.field(
                embed,
                "📈 Среднее за день",
                f"Сообщений: **{avg_msgs}**\nВ голосе: **{format_duration(int(avg_voice))}**",
                inline=True,
            )

        if not sessions and messages == 0:
            embed.description = "_Статистика пока пуста. Начни общаться!_"

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="топ_актив", description="Топ участников по активности")
    @app_commands.describe(metric="Что сравнивать")
    @app_commands.choices(metric=[
        app_commands.Choice(name="Сообщения", value="messages"),
        app_commands.Choice(name="Голосовое время", value="voice"),
        app_commands.Choice(name="Заходы в войс", value="joins"),
    ])
    async def top_active(self, interaction: discord.Interaction, metric: app_commands.Choice[str]):
        await interaction.response.defer()

        col_map = {"messages": "messages", "voice": "voice_seconds", "joins": "voice_joins"}
        col = col_map[metric.value]
        title_map = {
            "messages": "🏆 Топ по сообщениям",
            "voice": "🏆 Топ по голосовому времени",
            "joins": "🏆 Топ по заходам в войс",
        }
        title = title_map[metric.value]
        top = await self._get_top(col, 15)

        if not top:
            return await interaction.followup.send(embed=style.info("Статистика пока пуста."))

        def val_fmt(uid, v):
            if metric.value == "voice":
                return format_duration(v)
            return f"{v} сообщ." if metric.value == "messages" else str(v)

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, v) in enumerate(top):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            medal = medals[i] if i < 3 else f"**{i + 1}.**"
            lines.append(f"{medal} {name} — {val_fmt(uid, v)}")

        embed = style.base(
            title,
            "\n".join(lines),
            color=discord.Color.gold(),
            footer=None,
            timestamp=True,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="аватар", description="Показать аватар участника")
    @app_commands.describe(user="Участник")
    async def avatar(self, interaction: discord.Interaction, user: discord.Member = None):
        member = user or interaction.user
        embed = style.base(
            f"🖼️ Аватар: {member.display_name}",
            color=_member_color(member),
            footer=f"ID: {member.id}",
        )
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="список_ролей", description="Показать все роли сервера с ID"
    )
    @app_commands.default_permissions(administrator=True)
    async def roles_list_admin(self, interaction: discord.Interaction):
        roles = sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)
        lines = []
        for role in roles:
            if role == interaction.guild.default_role:
                continue
            members = len(role.members)
            lines.append(f"{role.mention} — `{role.id}` ({members} чел.)")

        if not lines:
            return await interaction.response.send_message(
                embed=style.info("Нет ролей."), ephemeral=True
            )

        embed = style.base(
            f"🎯 Роли сервера ({len(lines)})",
            "\n".join(lines[:50]),
            color=discord.Color.blurple(),
            footer=None,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
