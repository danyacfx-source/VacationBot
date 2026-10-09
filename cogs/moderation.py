"""Модерация: предупреждения, кик/бан/мьют, розыгрыши и AFK."""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from core.timeutil import humanize_delta, msk_utcnow, parse_duration
from services.notify import send_moderation_log
from ui import style

log = logging.getLogger(__name__)

MAX_MUTE = timedelta(days=28)


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.scheduler.register_interval("giveaways", self.check_giveaways, seconds=30)

    def cog_unload(self) -> None:
        self.bot.scheduler.unregister("giveaways")

    async def _mod_log(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        color: discord.Color,
    ) -> None:
        """Единая отправка в мод-лог (канал берётся из config)."""
        if interaction.guild is None:
            return
        await send_moderation_log(self.bot, interaction.guild, title, description, color)

    # ═══════════════════════════════════════
    #  WARNINGS
    # ═══════════════════════════════════════

    @app_commands.command(name="warn", description="Выдать предупреждение участнику")
    @app_commands.describe(user="Участник", reason="Причина")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(
        self, interaction: discord.Interaction, user: discord.Member, reason: str = "Не указана"
    ) -> None:
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя предупредить себя."), ephemeral=True
            )
            return
        if user.top_role >= interaction.user.top_role:
            await interaction.response.send_message(
                embed=style.error(
                    "Ошибка", "Нельзя предупредить участника с равной или высшей ролью."
                ),
                ephemeral=True,
            )
            return
        if user.bot:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя предупредить бота."), ephemeral=True
            )
            return

        db = self.bot.db
        await db.execute(
            "INSERT INTO warnings (user_id, reason, moderator_id, date) VALUES (?, ?, ?, ?)",
            (user.id, reason, interaction.user.id, msk_utcnow().isoformat()),
        )
        count = int(
            await db.scalar(
                "SELECT COUNT(*) FROM warnings WHERE user_id = ?", (user.id,), default=0
            )
        )
        warn_id = count

        embed = style.warning(
            "⚠️ Предупреждение",
            f"{user.mention} — предупреждение **#{warn_id}**",
            footer=f"Выдал: {interaction.user.display_name}",
        )
        style.field(embed, "Причина", reason, inline=True)
        style.field(embed, "Всего", str(count), inline=True)

        await interaction.response.send_message(embed=embed)

        await self._mod_log(
            interaction,
            "⚠️ Предупреждение",
            f"{user.mention} — предупреждение **#{warn_id}**\n"
            f"**Причина:** {reason}\n"
            f"**Всего:** {count}\n"
            f"**Выдал:** {interaction.user.display_name}",
            discord.Color.orange(),
        )

        if count >= 3:
            try:
                await user.timeout(
                    timedelta(days=7), reason=f"3 предупреждения. Последняя: {reason}"
                )
            except discord.Forbidden:
                log.warning("Нет прав для авто-таймаута %s (3 предупреждения)", user)
                return

            auto_embed = style.error(
                "🔇 Автомьют",
                f"{user.mention} замьючен на **7 дней** (3 предупреждения)",
            )
            await interaction.followup.send(embed=auto_embed)
            await self._mod_log(
                interaction,
                "🔇 Автомьют",
                f"{user.mention} замьючен на **7 дней** (3 предупреждения)",
                discord.Color.red(),
            )

    @app_commands.command(name="warnings", description="Показать предупреждения участника")
    @app_commands.describe(user="Участник")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings_cmd(self, interaction: discord.Interaction, user: discord.Member) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id, reason, moderator_id, date FROM warnings WHERE user_id = ? ORDER BY id",
            (user.id,),
        )

        if not rows:
            await interaction.response.send_message(
                embed=style.success("✅ Нет предупреждений", f"У {user.mention} нет предупреждений."),
                ephemeral=True,
            )
            return

        lines = []
        for i, row in enumerate(rows, 1):
            mod = interaction.guild.get_member(row["moderator_id"]) if interaction.guild else None
            mod_name = mod.display_name if mod else "Unknown"
            date_str = "—"
            if row["date"]:
                try:
                    date_str = datetime.fromisoformat(row["date"]).strftime("%d.%m.%Y %H:%M")
                except (TypeError, ValueError):
                    date_str = "—"
            lines.append(f"**#{i}** — {row['reason']}\n  └ {mod_name}, {date_str}")

        embed = style.warning(
            f"⚠️ Предупреждения: {user.display_name} ({len(rows)})",
            style.truncate("\n".join(lines)),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clearwarnings", description="Очистить все предупреждения участника")
    @app_commands.describe(user="Участник")
    @app_commands.default_permissions(administrator=True)
    async def clearwarnings(self, interaction: discord.Interaction, user: discord.Member) -> None:
        db = self.bot.db
        count = int(
            await db.scalar(
                "SELECT COUNT(*) FROM warnings WHERE user_id = ?", (user.id,), default=0
            )
        )
        await db.execute("DELETE FROM warnings WHERE user_id = ?", (user.id,))
        await interaction.response.send_message(
            embed=style.success(
                "✅ Очищено", f"Очищено **{count}** предупреждений у {user.mention}."
            )
        )

    # ═══════════════════════════════════════
    #  KICK / BAN
    # ═══════════════════════════════════════

    @app_commands.command(name="kick", description="Кикнуть участника с сервера")
    @app_commands.describe(user="Участник", reason="Причина")
    @app_commands.default_permissions(kick_members=True)
    async def kick(
        self, interaction: discord.Interaction, user: discord.Member, reason: str = "Не указана"
    ) -> None:
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя кикнуть себя."), ephemeral=True
            )
            return
        if user.top_role >= interaction.user.top_role:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя кикнуть участника с равной или высшей ролью."),
                ephemeral=True,
            )
            return
        if user.bot:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя кикнуть бота."), ephemeral=True
            )
            return

        try:
            await user.send(
                f"👢 Вас кикнули с сервера **{interaction.guild.name}**\nПричина: {reason}"
            )
        except discord.Forbidden:
            log.debug("Не удалось отправить ЛС о кике %s", user)

        await user.kick(reason=f"Кикнут {interaction.user}: {reason}")

        embed = style.error(
            "👢 Кик",
            f"**{user.display_name}** кикнут",
            footer=f"Кикнул: {interaction.user.display_name}",
        )
        style.field(embed, "Причина", reason, inline=True)

        await interaction.response.send_message(embed=embed)
        await self._mod_log(
            interaction,
            "👢 Кик",
            f"**{user.display_name}** кикнут\n"
            f"**Причина:** {reason}\n"
            f"**Кикнул:** {interaction.user.display_name}",
            discord.Color.red(),
        )

    @app_commands.command(name="ban", description="Забанить участника")
    @app_commands.describe(user="Участник", reason="Причина")
    @app_commands.default_permissions(ban_members=True)
    async def ban(
        self, interaction: discord.Interaction, user: discord.Member, reason: str = "Не указана"
    ) -> None:
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя забанить себя."), ephemeral=True
            )
            return
        if user.top_role >= interaction.user.top_role:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя забанить участника с равной или высшей ролью."),
                ephemeral=True,
            )
            return
        if user.bot:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя забанить бота."), ephemeral=True
            )
            return

        try:
            await user.send(
                f"🔨 Вы забанены на сервере **{interaction.guild.name}**\nПричина: {reason}"
            )
        except discord.Forbidden:
            log.debug("Не удалось отправить ЛС о бане %s", user)

        await user.ban(
            reason=f"Забанен {interaction.user}: {reason}", delete_message_seconds=0
        )

        embed = style.error(
            "🔨 Бан",
            f"**{user.display_name}** забанен",
            footer=f"Забанил: {interaction.user.display_name}",
        )
        style.field(embed, "Причина", reason, inline=True)

        await interaction.response.send_message(embed=embed)
        await self._mod_log(
            interaction,
            "🔨 Бан",
            f"**{user.display_name}** забанен\n"
            f"**Причина:** {reason}\n"
            f"**Забанил:** {interaction.user.display_name}",
            discord.Color.dark_red(),
        )

    @app_commands.command(name="unban", description="Разбанить пользователя по ID")
    @app_commands.describe(user_id="ID пользователя")
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str) -> None:
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Некорректный ID."), ephemeral=True
            )
            return

        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"Разбанен {interaction.user}")
        except discord.NotFound:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Пользователь не найден или не забанен."),
                ephemeral=True,
            )
            return

        embed = style.success(
            "✅ Разбан",
            f"**{user.display_name}**#{user.discriminator} разбанен",
            footer=f"Разбанил: {interaction.user.display_name}",
        )
        await interaction.response.send_message(embed=embed)

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
    ) -> None:
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя замьютить себя."), ephemeral=True
            )
            return
        if user.top_role >= interaction.user.top_role:
            await interaction.response.send_message(
                embed=style.error(
                    "Ошибка", "Нельзя замьютить участника с равной или высшей ролью."
                ),
                ephemeral=True,
            )
            return

        delta = parse_duration(duration)
        if delta is None:
            await interaction.response.send_message(
                embed=style.error(
                    "Ошибка", "Некорректная длительность. Примеры: `10м`, `1ч`, `1д`, `2ч30м`"
                ),
                ephemeral=True,
            )
            return
        if delta > MAX_MUTE:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Максимальная длительность — 28 дней."),
                ephemeral=True,
            )
            return

        until = msk_utcnow() + delta
        try:
            await user.timeout(until, reason=f"Мьют от {interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нет прав для мьюта этого участника."),
                ephemeral=True,
            )
            return

        human = humanize_delta(delta)
        embed = style.warning(
            "🔇 Мьют",
            f"{user.mention} замьючен на **{human}**",
            footer=f"Замьютил: {interaction.user.display_name}",
        )
        style.field(embed, "Причина", reason, inline=True)

        await interaction.response.send_message(embed=embed)
        await self._mod_log(
            interaction,
            "🔇 Мьют",
            f"{user.mention} замьючен на **{human}**\n"
            f"**Причина:** {reason}\n"
            f"**Замьютил:** {interaction.user.display_name}",
            discord.Color.orange(),
        )

    @app_commands.command(name="unmute", description="Размьютить участника")
    @app_commands.describe(user="Участник")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not user.is_timed_out():
            await interaction.response.send_message(
                embed=style.warning("🔇 Не в мьюте", f"{user.mention} не замьючен."),
                ephemeral=True,
            )
            return

        try:
            await user.timeout(None, reason=f"Размьют {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нет прав."), ephemeral=True
            )
            return

        embed = style.success(
            "🔊 unmute",
            f"{user.mention} размьючен",
            footer=f"Размутил: {interaction.user.display_name}",
        )
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
    ) -> None:
        delta = parse_duration(duration)
        if delta is None:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Некорректная длительность."), ephemeral=True
            )
            return

        end_time = msk_utcnow() + delta

        embed = style.base(
            "🎉 РОЗЫГРЫШ!",
            (
                f"**Приз:** {prize}\n\n"
                f"Нажмите ✅ чтобы участвовать!\n"
                f"Окончание: <t:{int(end_time.timestamp())}:R>\n"
                f"Победителей: **{winners}**"
            ),
            color=style.ACCENT,
            footer=f"Создал: {interaction.user.display_name}",
        )

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        await msg.add_reaction("✅")

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO giveaways (message_id, prize, host_id, channel_id, end_time, winners_count, ended) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (msg.id, prize, interaction.user.id, interaction.channel_id, end_time.isoformat(), winners),
        )

    async def check_giveaways(self) -> None:
        """Завершает розыгрыши с истёкшим сроком и выбирает победителей."""
        db = self.bot.db
        now = msk_utcnow()
        rows = await db.fetchall(
            "SELECT message_id, prize, host_id, channel_id, end_time, winners_count "
            "FROM giveaways WHERE ended = 0"
        )

        for row in rows:
            mid = row["message_id"]
            prize = row["prize"]
            ch_id = row["channel_id"]
            winners_count = row["winners_count"] or 1

            try:
                end_time = datetime.fromisoformat(row["end_time"])
            except (TypeError, ValueError):
                log.warning("Некорректное end_time у розыгрыша %s", mid)
                continue
            if now < end_time:
                continue

            await db.execute("UPDATE giveaways SET ended = 1 WHERE message_id = ?", (mid,))

            channel = self.bot.channel_of(ch_id)
            if channel is None:
                continue
            try:
                msg = await channel.fetch_message(mid)
            except (discord.NotFound, discord.Forbidden) as exc:
                log.debug("Не удалось получить сообщение розыгрыша %s: %s", mid, exc)
                continue

            reaction = None
            for r in msg.reactions:
                if str(r.emoji) == "✅":
                    reaction = r
                    break

            users: list[discord.User] = []
            if reaction is not None:
                try:
                    users = [u async for u in reaction.users() if not u.bot]
                except discord.HTTPException as exc:
                    log.debug("Не удалось получить реакции розыгрыша %s: %s", mid, exc)

            if not users:
                await self._edit_giveaway(
                    msg,
                    style.base(
                        "🎉 Розыгрыш завершён!",
                        f"**Приз:** {prize}\n\nУчастников не было.",
                        color=style.NEUTRAL,
                        footer=None,
                    ),
                )
                continue

            count = min(winners_count, len(users))
            winners_list = random.sample(users, count)
            winners_text = ", ".join(w.mention for w in winners_list)

            await self._edit_giveaway(
                msg,
                style.base(
                    "🎉 Розыгрыш завершён!",
                    (
                        f"**Приз:** {prize}\n\n"
                        f"**Победители:** {winners_text}\n"
                        f"Участников: **{len(users)}**"
                    ),
                    color=style.ACCENT,
                    footer=None,
                ),
            )
            try:
                await channel.send(
                    f"🎉 Поздравляем {winners_text}! Вы выиграли **{prize}**!"
                )
            except discord.HTTPException as exc:
                log.debug("Не удалось отправить поздравление в %s: %s", channel, exc)

    async def _edit_giveaway(self, message: discord.Message, embed: discord.Embed) -> None:
        try:
            await message.edit(embed=embed)
        except discord.HTTPException as exc:
            log.debug("Не удалось обновить розыгрыш %s: %s", message.id, exc)

    # ═══════════════════════════════════════
    #  AFK
    # ═══════════════════════════════════════

    @app_commands.command(name="afk", description="Пометить себя как AFK")
    @app_commands.describe(reason="Причина")
    async def afk_cmd(self, interaction: discord.Interaction, reason: str = "AFK") -> None:
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO afk (user_id, reason, since, display_name) VALUES (?, ?, ?, ?)",
            (
                interaction.user.id,
                reason,
                msk_utcnow().isoformat(),
                interaction.user.display_name,
            ),
        )
        await interaction.response.send_message(
            embed=style.info(
                "😴 AFK", f"{interaction.user.mention} теперь AFK: **{reason}**"
            ),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        db = self.bot.db

        row = await db.fetchone(
            "SELECT reason FROM afk WHERE user_id = ?", (message.author.id,)
        )
        if row:
            await db.execute("DELETE FROM afk WHERE user_id = ?", (message.author.id,))
            try:
                await message.channel.send(
                    f"👋 {message.author.mention} вернулся!", delete_after=5
                )
            except discord.HTTPException as exc:
                log.debug("Не удалось сообщить о возвращении из AFK: %s", exc)

        for user in message.mentions:
            if user.bot or user.id == message.author.id:
                continue
            afk_row = await db.fetchone(
                "SELECT reason, since FROM afk WHERE user_id = ?", (user.id,)
            )
            if not afk_row:
                continue
            try:
                since = datetime.fromisoformat(afk_row["since"])
            except (TypeError, ValueError):
                since = msk_utcnow()
            ago = msk_utcnow() - since
            mins = int(ago.total_seconds() / 60)
            time_text = f"{mins} мин." if mins < 60 else f"{mins // 60} ч. {mins % 60} мин."
            try:
                await message.channel.send(
                    f"😴 **{user.display_name}** AFK: {afk_row['reason']} ({time_text})",
                    delete_after=8,
                )
            except discord.HTTPException as exc:
                log.debug("Не удалось ответить на упоминание AFK: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
