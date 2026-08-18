import json
import os
import random
import re
import sys
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_conn


def parse_duration(text: str) -> int | None:
    total = 0
    parts = re.findall(r'(\d+)\s*(д|ч|м|с|d|h|m|s)', text.lower())
    if not parts:
        return None
    mult = {'д': 86400, 'd': 86400, 'ч': 3600, 'h': 3600, 'м': 60, 'm': 60, 'с': 1, 's': 1}
    for val, unit in parts:
        total += int(val) * mult.get(unit, 0)
    return total if total > 0 else None


def format_duration_short(seconds: int) -> str:
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    parts = []
    if d:
        parts.append(f"{d}д")
    if h:
        parts.append(f"{h}ч")
    if m:
        parts.append(f"{m}м")
    return " ".join(parts) if parts else f"{seconds}с"


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    # ═══════════════════════════════════════
    #  WARNINGS
    # ═══════════════════════════════════════

    @app_commands.command(name="warn", description="Выдать предупреждение участнику")
    @app_commands.describe(user="Участник", reason="Причина")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Не указана"):
        if user.id == interaction.user.id:
            return await interaction.response.send_message("Нельзя предупредить себя.", ephemeral=True)
        if user.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("Нельзя предупредить участника с равной или высшей ролью.", ephemeral=True)
        if user.bot:
            return await interaction.response.send_message("Нельзя предупредить бота.", ephemeral=True)

        conn = get_conn()
        conn.execute(
            "INSERT INTO warnings (user_id, reason, moderator_id, date) VALUES (?, ?, ?, ?)",
            (user.id, reason, interaction.user.id, discord.utils.utcnow().isoformat()),
        )
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) FROM warnings WHERE user_id = ?", (user.id,)
        ).fetchone()[0]

        warn_id = count
        embed = discord.Embed(
            title="⚠️ Предупреждение",
            description=f"{user.mention} — предупреждение **#{warn_id}**",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Причина", value=reason, inline=True)
        embed.add_field(name="Всего", value=str(count), inline=True)
        embed.set_footer(text=f"Выдал: {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)

        log_ch = interaction.guild.get_channel(1500582616867536966)
        if log_ch:
            await log_ch.send(embed=embed)

        if count >= 3:
            try:
                await user.timeout(timedelta(days=7), reason=f"3 предупреждения. Последняя: {reason}")
                auto_embed = discord.Embed(
                    title="🔇 Автомьют",
                    description=f"{user.mention} замьючен на **7 дней** (3 предупреждения)",
                    color=discord.Color.red(),
                )
                await interaction.followup.send(embed=auto_embed)
                if log_ch:
                    await log_ch.send(embed=auto_embed)
            except discord.Forbidden:
                pass

    @app_commands.command(name="warnings", description="Показать предупреждения участника")
    @app_commands.describe(user="Участник")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings_cmd(self, interaction: discord.Interaction, user: discord.Member):
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, reason, moderator_id, date FROM warnings WHERE user_id = ? ORDER BY id",
            (user.id,),
        ).fetchall()

        if not rows:
            return await interaction.response.send_message(
                f"✅ У {user.mention} нет предупреждений.", ephemeral=True
            )

        lines = []
        for i, (wid, reason, mod_id, date) in enumerate(rows, 1):
            mod = interaction.guild.get_member(mod_id)
            mod_name = mod.display_name if mod else "Unknown"
            date_str = datetime.fromisoformat(date).strftime("%d.%m.%Y %H:%M") if date else "—"
            lines.append(f"**#{i}** — {reason}\n  └ {mod_name}, {date_str}")

        embed = discord.Embed(
            title=f"⚠️ Предупреждения: {user.display_name} ({len(rows)})",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clearwarnings", description="Очистить все предупреждения участника")
    @app_commands.describe(user="Участник")
    @app_commands.default_permissions(administrator=True)
    async def clearwarnings(self, interaction: discord.Interaction, user: discord.Member):
        conn = get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM warnings WHERE user_id = ?", (user.id,)
        ).fetchone()[0]
        conn.execute("DELETE FROM warnings WHERE user_id = ?", (user.id,))
        conn.commit()
        await interaction.response.send_message(f"✅ Очищено **{count}** предупреждений у {user.mention}.")

    # ═══════════════════════════════════════
    #  KICK / BAN
    # ═══════════════════════════════════════

    @app_commands.command(name="kick", description="Кикнуть участника с сервера")
    @app_commands.describe(user="Участник", reason="Причина")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Не указана"):
        if user.id == interaction.user.id:
            return await interaction.response.send_message("Нельзя кикнуть себя.", ephemeral=True)
        if user.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("Нельзя кикнуть участника с равной или высшей ролью.", ephemeral=True)
        if user.bot:
            return await interaction.response.send_message("Нельзя кикнуть бота.", ephemeral=True)

        try:
            await user.send(f"👢 Вас кикнули с сервера **{interaction.guild.name}**\nПричина: {reason}")
        except discord.Forbidden:
            pass

        await user.kick(reason=f"Кикнут {interaction.user}: {reason}")

        embed = discord.Embed(
            title="👢 Кик",
            description=f"**{user.display_name}** кикнут",
            color=discord.Color.red(),
        )
        embed.add_field(name="Причина", value=reason, inline=True)
        embed.set_footer(text=f"Кикнул: {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)
        log_ch = interaction.guild.get_channel(1500582616867536966)
        if log_ch:
            await log_ch.send(embed=embed)

    @app_commands.command(name="ban", description="Забанить участника")
    @app_commands.describe(user="Участник", reason="Причина")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Не указана"):
        if user.id == interaction.user.id:
            return await interaction.response.send_message("Нельзя забанить себя.", ephemeral=True)
        if user.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("Нельзя забанить участника с равной или высшей ролью.", ephemeral=True)
        if user.bot:
            return await interaction.response.send_message("Нельзя забанить бота.", ephemeral=True)

        try:
            await user.send(f"🔨 Вы забанены на сервере **{interaction.guild.name}**\nПричина: {reason}")
        except discord.Forbidden:
            pass

        await user.ban(reason=f"Забанен {interaction.user}: {reason}", delete_message_days=0)

        embed = discord.Embed(
            title="🔨 Бан",
            description=f"**{user.display_name}** забанен",
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Причина", value=reason, inline=True)
        embed.set_footer(text=f"Забанил: {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)
        log_ch = interaction.guild.get_channel(1500582616867536966)
        if log_ch:
            await log_ch.send(embed=embed)

    @app_commands.command(name="unban", description="Разбанить пользователя по ID")
    @app_commands.describe(user_id="ID пользователя")
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str):
        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.response.send_message("Некорректный ID.", ephemeral=True)

        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"Разбанен {interaction.user}")
            embed = discord.Embed(
                title="✅ Разбан",
                description=f"**{user.display_name}**#{user.discriminator} разбанен",
                color=discord.Color.green(),
            )
            embed.set_footer(text=f"Разбанил: {interaction.user.display_name}")
            await interaction.response.send_message(embed=embed)
        except discord.NotFound:
            await interaction.response.send_message(
                "Пользователь не найден или не забанен.", ephemeral=True
            )

    # ═══════════════════════════════════════
    #  MUTE / UNMUTE
    # ═══════════════════════════════════════

    @app_commands.command(name="mute", description="Замьютить участника")
    @app_commands.describe(
        user="Участник",
        duration="Длительность (10м, 1ч, 1д)",
        reason="Причина",
    )
    @app_commands.default_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: str = "10м",
        reason: str = "Не указана",
    ):
        if user.id == interaction.user.id:
            return await interaction.response.send_message("Нельзя замьютить себя.", ephemeral=True)
        if user.top_role >= interaction.user.top_role:
            return await interaction.response.send_message(
                "Нельзя замьютить участника с равной или высшей ролью.", ephemeral=True
            )

        seconds = parse_duration(duration)
        if seconds is None or seconds <= 0:
            return await interaction.response.send_message(
                "Некорректная длительность. Примеры: `10м`, `1ч`, `1д`, `2ч30м`", ephemeral=True
            )
        if seconds > 2419200:
            return await interaction.response.send_message(
                "Максимальная длительность — 28 дней.", ephemeral=True
            )

        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        try:
            await user.timeout(until, reason=f"Мьют от {interaction.user}: {reason}")
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Нет прав для мьюта этого участника.", ephemeral=True
            )

        embed = discord.Embed(
            title="🔇 Мьют",
            description=f"{user.mention} замьючен на **{format_duration_short(seconds)}**",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Причина", value=reason, inline=True)
        embed.set_footer(text=f"Замьютил: {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)
        log_ch = interaction.guild.get_channel(1500582616867536966)
        if log_ch:
            await log_ch.send(embed=embed)

    @app_commands.command(name="unmute", description="Размьютить участника")
    @app_commands.describe(user="Участник")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, user: discord.Member):
        if not user.is_timed_out():
            return await interaction.response.send_message(
                f"{user.mention} не замьючен.", ephemeral=True
            )

        try:
            await user.timeout(None, reason=f"Размьют {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        embed = discord.Embed(
            title="🔊 unmute",
            description=f"{user.mention} размьючен",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Размутил: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    # ═══════════════════════════════════════
    #  GIVEAWAY
    # ═══════════════════════════════════════

    @app_commands.command(name="giveaway", description="Создать розыгрыш")
    @app_commands.describe(
        prize="Приз",
        duration="Длительность (1ч, 1д, 3д)",
        winners="Количество победителей",
    )
    async def giveaway_cmd(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str = "1ч",
        winners: int = 1,
    ):
        seconds = parse_duration(duration)
        if seconds is None or seconds <= 0:
            return await interaction.response.send_message("Некорректная длительность.", ephemeral=True)

        end_time = discord.utils.utcnow() + timedelta(seconds=seconds)

        embed = discord.Embed(
            title="🎉 РОЗЫГРЫШ!",
            description=(
                f"**Приз:** {prize}\n\n"
                f"Нажмите ✅ чтобы участвовать!\n"
                f"Окончание: <t:{int(end_time.timestamp())}:R>\n"
                f"Победителей: **{winners}**"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Создал: {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        await msg.add_reaction("✅")

        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO giveaways (message_id, prize, host_id, channel_id, end_time, winners_count, ended) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (msg.id, prize, interaction.user.id, interaction.channel_id, end_time.isoformat(), winners),
        )
        conn.commit()

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        conn = get_conn()
        now = discord.utils.utcnow()
        rows = conn.execute(
            "SELECT message_id, prize, host_id, channel_id, end_time, winners_count FROM giveaways WHERE ended = 0"
        ).fetchall()

        for mid, prize, host_id, ch_id, end_time_str, winners_count in rows:
            end_time = datetime.fromisoformat(end_time_str)
            if now < end_time:
                continue

            conn.execute("UPDATE giveaways SET ended = 1 WHERE message_id = ?", (mid,))
            conn.commit()

            try:
                channel = self.bot.get_channel(ch_id)
                if not channel:
                    continue
                msg = await channel.fetch_message(mid)
            except (discord.NotFound, discord.Forbidden):
                continue

            reaction = None
            for r in msg.reactions:
                if str(r.emoji) == "✅":
                    reaction = r
                    break

            if not reaction:
                embed = discord.Embed(
                    title="🎉 Розыгрыш завершён!",
                    description=f"**Приз:** {prize}\n\nУчастников не было.",
                    color=discord.Color.greyple(),
                )
                await msg.edit(embed=embed)
                continue

            users = [u async for u in reaction.users() if not u.bot]

            if not users:
                embed = discord.Embed(
                    title="🎉 Розыгрыш завершён!",
                    description=f"**Приз:** {prize}\n\nУчастников не было.",
                    color=discord.Color.greyple(),
                )
                await msg.edit(embed=embed)
                continue

            count = min(winners_count, len(users))
            winners_list = random.sample(users, count)
            winners_text = ", ".join(w.mention for w in winners_list)

            embed = discord.Embed(
                title="🎉 Розыгрыш завершён!",
                description=(
                    f"**Приз:** {prize}\n\n"
                    f"**Победители:** {winners_text}\n"
                    f"Участников: **{len(users)}**"
                ),
                color=discord.Color.gold(),
            )
            await msg.edit(embed=embed)
            await channel.send(
                f"🎉 Поздравляем {winners_text}! Вы выиграли **{prize}**!"
            )

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()

    # ═══════════════════════════════════════
    #  AFK
    # ═══════════════════════════════════════

    @app_commands.command(name="afk", description="Пометить себя как AFK")
    @app_commands.describe(reason="Причина")
    async def afk_cmd(self, interaction: discord.Interaction, reason: str = "AFK"):
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO afk (user_id, reason, since, display_name) VALUES (?, ?, ?, ?)",
            (interaction.user.id, reason, discord.utils.utcnow().isoformat(), interaction.user.display_name),
        )
        conn.commit()
        await interaction.response.send_message(
            f"😴 {interaction.user.mention} теперь AFK: **{reason}**", ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        conn = get_conn()

        row = conn.execute("SELECT reason FROM afk WHERE user_id = ?", (message.author.id,)).fetchone()
        if row:
            conn.execute("DELETE FROM afk WHERE user_id = ?", (message.author.id,))
            conn.commit()
            try:
                await message.channel.send(
                    f"👋 {message.author.mention} вернулся!", delete_after=5
                )
            except discord.Forbidden:
                pass

        for user in message.mentions:
            if user.bot or user.id == message.author.id:
                continue
            afk_row = conn.execute(
                "SELECT reason, since FROM afk WHERE user_id = ?", (user.id,)
            ).fetchone()
            if afk_row:
                reason, since_str = afk_row
                since = datetime.fromisoformat(since_str)
                ago = discord.utils.utcnow() - since
                mins = int(ago.total_seconds() / 60)
                time_text = f"{mins} мин." if mins < 60 else f"{mins // 60} ч. {mins % 60} мин."
                try:
                    await message.channel.send(
                        f"😴 **{user.display_name}** AFK: {reason} ({time_text})",
                        delete_after=8,
                    )
                except discord.Forbidden:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))
