import os
import sys
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_conn

MAX_VOICE_SESSIONS = 100


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} сек."
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours == 0:
        return f"{minutes} мин."
    return f"{hours} ч. {minutes} мин."


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._voice_sessions: dict[int, dict] = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        conn = get_conn()
        now = discord.utils.utcnow()
        now_iso = now.isoformat()

        before_channel = before.channel
        after_channel = after.channel

        if before_channel is None and after_channel is not None:
            conn.execute(
                "INSERT INTO member_stats (user_id, messages, voice_seconds, voice_joins) "
                "VALUES (?, 0, 0, 1) "
                "ON CONFLICT(user_id) DO UPDATE SET voice_joins = voice_joins + 1",
                (member.id,),
            )
            self._voice_sessions[member.id] = {"start": now, "channel": after_channel.name}

        elif before_channel is not None and after_channel is None:
            if member.id in self._voice_sessions:
                session = self._voice_sessions.pop(member.id)
                elapsed = (now - session["start"]).total_seconds()
                if elapsed > 5:
                    secs = int(elapsed)
                    conn.execute(
                        "UPDATE member_stats SET voice_seconds = voice_seconds + ? WHERE user_id = ?",
                        (secs, member.id),
                    )
                    conn.execute(
                        "INSERT INTO voice_sessions (user_id, channel, start, end, seconds) VALUES (?, ?, ?, ?, ?)",
                        (member.id, session["channel"], session["start"].isoformat(), now_iso, secs),
                    )
                    count = conn.execute(
                        "SELECT COUNT(*) FROM voice_sessions WHERE user_id = ?", (member.id,)
                    ).fetchone()[0]
                    if count > MAX_VOICE_SESSIONS:
                        conn.execute(
                            "DELETE FROM voice_sessions WHERE user_id = ? AND id NOT IN "
                            "(SELECT id FROM voice_sessions WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
                            (member.id, member.id, MAX_VOICE_SESSIONS),
                        )

        elif before_channel is not None and after_channel is not None and before_channel.id != after_channel.id:
            if member.id in self._voice_sessions:
                session = self._voice_sessions.pop(member.id)
                elapsed = (now - session["start"]).total_seconds()
                if elapsed > 5:
                    secs = int(elapsed)
                    conn.execute(
                        "UPDATE member_stats SET voice_seconds = voice_seconds + ? WHERE user_id = ?",
                        (secs, member.id),
                    )
                    conn.execute(
                        "INSERT INTO voice_sessions (user_id, channel, start, end, seconds) VALUES (?, ?, ?, ?, ?)",
                        (member.id, session["channel"], session["start"].isoformat(), now_iso, secs),
                    )
                    count = conn.execute(
                        "SELECT COUNT(*) FROM voice_sessions WHERE user_id = ?", (member.id,)
                    ).fetchone()[0]
                    if count > MAX_VOICE_SESSIONS:
                        conn.execute(
                            "DELETE FROM voice_sessions WHERE user_id = ? AND id NOT IN "
                            "(SELECT id FROM voice_sessions WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
                            (member.id, member.id, MAX_VOICE_SESSIONS),
                        )

            self._voice_sessions[member.id] = {"start": now, "channel": after_channel.name}

        conn.commit()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        conn = get_conn()
        conn.execute(
            "INSERT INTO member_stats (user_id, messages, voice_seconds, voice_joins) "
            "VALUES (?, 1, 0, 0) "
            "ON CONFLICT(user_id) DO UPDATE SET messages = messages + 1",
            (message.author.id,),
        )
        conn.commit()

    def _get_user_stats(self, user_id: int) -> dict:
        conn = get_conn()
        row = conn.execute(
            "SELECT messages, voice_seconds, voice_joins FROM member_stats WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return {"messages": row[0], "voice_seconds": row[1], "voice_joins": row[2]}
        return {"messages": 0, "voice_seconds": 0, "voice_joins": 0}

    def _get_voice_sessions(self, user_id: int) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT channel, start, end, seconds FROM voice_sessions WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
        return [{"channel": r[0], "start": r[1], "end": r[2], "seconds": r[3]} for r in rows]

    def _get_total_stats(self) -> tuple[int, int]:
        conn = get_conn()
        row = conn.execute(
            "SELECT COALESCE(SUM(messages), 0), COALESCE(SUM(voice_seconds), 0), COUNT(*) FROM member_stats"
        ).fetchone()
        return row[0], row[1], row[2]

    def _get_top(self, column: str, limit: int = 15) -> list[tuple[int, int]]:
        conn = get_conn()
        rows = conn.execute(
            f"SELECT user_id, {column} FROM member_stats WHERE {column} > 0 ORDER BY {column} DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

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

        total_msgs, total_voice, db_users = self._get_total_stats()

        embed = discord.Embed(
            title=f"📋 {guild.name}",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(
            name="👥 Участники",
            value=f"Всего: **{total}**\nОнлайн: **{online}**\nБотов: **{bots}**",
            inline=True,
        )
        embed.add_field(
            name="📂 Каналы",
            value=f"Текстовых: **{text_channels}**\nГолосовых: **{voice_channels}**\nКатегорий: **{categories}**",
            inline=True,
        )
        embed.add_field(
            name="🎯 Прочее",
            value=f"Ролей: **{roles}**\nБусты: **{boost_count}** (Ур. {boost_tier})\nСоздан: **{created.strftime('%d.%m.%Y')}** ({age_days} дн.)",
            inline=True,
        )
        embed.add_field(
            name="📊 Статистика бота",
            value=f"Сообщений: **{total_msgs}**\nВ голосе: **{format_duration(total_voice)}**\nПользователей в базе: **{db_users}**",
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
        stats = self._get_user_stats(member.id)
        sessions = self._get_voice_sessions(member.id)

        embed = discord.Embed(
            title=f"👤 {member.display_name}",
            color=member.color if member.color != discord.Color.default() else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="💬 Сообщения", value=f"**{stats['messages']}**", inline=True)
        embed.add_field(name="🔊 В голосе", value=f"**{format_duration(stats['voice_seconds'])}**", inline=True)
        embed.add_field(name="🚪 Заходов в войс", value=f"**{stats['voice_joins']}**", inline=True)

        if sessions:
            top_channels: dict[str, int] = {}
            for s in sessions:
                top_channels[s["channel"]] = top_channels.get(s["channel"], 0) + s["seconds"]
            sorted_ch = sorted(top_channels.items(), key=lambda x: x[1], reverse=True)[:5]
            if sorted_ch:
                lines = [f"`{ch}` — {format_duration(secs)}" for ch, secs in sorted_ch]
                embed.add_field(name="🏆 Топ каналы", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="мойпрофиль", description="Показать твою статистику")
    async def my_profile(self, interaction: discord.Interaction):
        member = interaction.user
        stats = self._get_user_stats(member.id)
        sessions = self._get_voice_sessions(member.id)

        embed = discord.Embed(
            title=f"🃏 {member.display_name}",
            color=member.color if member.color != discord.Color.default() else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="💬 Сообщения", value=f"**{stats['messages']}**", inline=True)
        embed.add_field(name="🔊 В голосе", value=f"**{format_duration(stats['voice_seconds'])}**", inline=True)
        embed.add_field(name="🚪 Заходов в войс", value=f"**{stats['voice_joins']}**", inline=True)

        if sessions:
            top_channels: dict[str, int] = {}
            for s in sessions:
                top_channels[s["channel"]] = top_channels.get(s["channel"], 0) + s["seconds"]
            sorted_ch = sorted(top_channels.items(), key=lambda x: x[1], reverse=True)[:5]
            if sorted_ch:
                lines = [f"`{ch}` — {format_duration(secs)}" for ch, secs in sorted_ch]
                embed.add_field(name="🏆 Топ каналы", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="мойстатистика", description="Подробная статистика твоей активности")
    @app_commands.describe(user="Участник (по умолчанию ты)")
    async def my_stats(self, interaction: discord.Interaction, user: discord.Member = None):
        member = user or interaction.user
        stats = self._get_user_stats(member.id)
        sessions = self._get_voice_sessions(member.id)

        voice_secs = stats["voice_seconds"]
        messages = stats["messages"]
        joins = stats["voice_joins"]

        embed = discord.Embed(
            title=f"📊 Статистика: {member.display_name}",
            color=member.color if member.color != discord.Color.default() else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="💬 Сообщения", value=f"**{messages}** сообщений", inline=True)
        embed.add_field(
            name="🔊 Голосовые каналы",
            value=f"Общее время: **{format_duration(voice_secs)}**\nЗаходов: **{joins}**",
            inline=True,
        )

        if sessions:
            today_start = discord.utils.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_secs = sum(s["seconds"] for s in sessions if s["end"] >= today_start.isoformat())
            embed.add_field(name="📅 Сегодня", value=format_duration(today_secs), inline=True)

            top_channels: dict[str, int] = {}
            for s in sessions:
                top_channels[s["channel"]] = top_channels.get(s["channel"], 0) + s["seconds"]
            sorted_ch = sorted(top_channels.items(), key=lambda x: x[1], reverse=True)[:5]
            if sorted_ch:
                lines = [f"`{ch}` — {format_duration(secs)}" for ch, secs in sorted_ch]
                embed.add_field(name="🏆 Топ каналы", value="\n".join(lines), inline=False)

        if member.joined_at:
            days = (discord.utils.utcnow() - member.joined_at).days
            avg_msgs = round(messages / days, 1) if days > 0 else 0
            avg_voice = round(voice_secs / days, 1) if days > 0 else 0
            embed.add_field(
                name="📈 Среднее за день",
                value=f"Сообщений: **{avg_msgs}**\nВ голосе: **{format_duration(int(avg_voice))}**",
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
        top = self._get_top(col, 15)

        if not top:
            return await interaction.followup.send("Статистика пока пуста.")

        def val_fmt(uid, v):
            if metric.value == "voice":
                return format_duration(v)
            return f"{v} сообщ." if metric.value == "messages" else str(v)

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, v) in enumerate(top):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            medal = medals[i] if i < 3 else f"**{i+1}.**"
            lines.append(f"{medal} {name} — {val_fmt(uid, v)}")

        embed = discord.Embed(
            title=title,
            description="\n".join(lines),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="аватар", description="Показать аватар участника")
    @app_commands.describe(user="Участник")
    async def avatar(self, interaction: discord.Interaction, user: discord.Member = None):
        member = user or interaction.user
        embed = discord.Embed(
            title=f"🖼️ Аватар: {member.display_name}",
            color=member.color if member.color != discord.Color.default() else discord.Color.blurple(),
        )
        embed.set_image(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="список_ролей", description="Показать все роли сервера с ID")
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
            return await interaction.response.send_message("Нет ролей.", ephemeral=True)

        embed = discord.Embed(
            title=f"🎯 Роли сервера ({len(lines)})",
            description="\n".join(lines[:50]),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
