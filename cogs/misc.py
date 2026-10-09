"""Разное: тест утреннего поста, дни рождения, память, артиллерия, вебхуки, роли, ИИ."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import random
import tracemalloc
from datetime import datetime
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config
from core.timeutil import msk_now
from services.ai import ask, detect_provider
from services.backups import send_backup
from services.daily import build_morning_embed, send_morning
from services.ram import build_ram_embed
from ui import style

log = logging.getLogger(__name__)

# Тексты промаха для /чугуний (варианты из старого ARTILLERY_RESULTS["miss"]).
_MISS_TEXTS = [
    "Снаряд пролетел мимо! {target} цел.",
    "Промах! {target} укрылся вовремя.",
    "Ветер унёс снаряд мимо! {target} не пострадал.",
    "{target} уклонился! Снаряд ушёл в песок.",
    "Снаряд застрял в стене. {target} не пострадал.",
]


@functools.lru_cache(maxsize=1)
def _load_artillery() -> dict:
    """Ленивая загрузка справочника орудий (181 позиция) из data/artillery.json."""
    path = Path(config.BASE_DIR) / "data" / "artillery.json"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _tracemalloc_lines(top_stats: list) -> list[str]:
    total = sum(stat.size for stat in top_stats)
    lines = [f"**Всего отслежено: {total / (1024 * 1024):.2f} MB**\n"]
    lines.append("```")
    lines.append(f"{'File and line':<70}{'Memory':>10}  {'Blocks':>8}")
    lines.append("-" * 91)
    for stat in top_stats[:20]:
        frame = stat.traceback[0]
        filepath = f"{frame.filename}:{frame.lineno}"
        if len(filepath) > 68:
            filepath = "..." + filepath[-65:]
        size_mb = stat.size / (1024 * 1024)
        lines.append(f"{filepath:<70}{size_mb:>8.2f}MB  {stat.count:>8}")
    lines.append("```")
    return lines


class MiscCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.scheduler.register_daily(
            "birthdays",
            self.birthday_check,
            hour=config.BIRTHDAY_HOUR,
            minute=0,
            catch_up=True,
        )
        self.bot.scheduler.register_daily(
            "backup",
            self.daily_backup,
            hour=config.BACKUP_HOUR,
            minute=0,
            catch_up=True,
            window_minutes=10,
        )
        self.bot.scheduler.register_daily(
            "morning",
            self.daily_morning,
            hour=config.MORNING_HOUR,
            minute=0,
            catch_up=False,
        )
        self.bot.scheduler.register_interval(
            "ram_monitor",
            self.ram_monitor,
            seconds=config.RAM_REPORT_INTERVAL_MINUTES * 60,
        )
        # tracemalloc_monitor объявлен ниже, но НЕ регистрируется в планировщике —
        # в оригинале он тоже не запускался в cog_load. Оставлен мёртвым намеренно.

    def cog_unload(self) -> None:
        for job in ("birthdays", "backup", "morning", "ram_monitor"):
            self.bot.scheduler.unregister(job)

    # ═══════════════════════════════════════
    #  КОМАНДЫ
    # ═══════════════════════════════════════

    @app_commands.command(name="test_morning", description="Тест ежедневного сообщения (только для админов)")
    async def test_morning(self, interaction: discord.Interaction) -> None:
        if not style.is_admin(interaction):
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нет прав."), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        channel = self.bot.channel_of(config.DAILY_CHANNEL)
        if not channel:
            await interaction.followup.send(
                embed=style.error("Ошибка", "❌ Канал не найден."), ephemeral=True
            )
            return

        embed = await build_morning_embed()
        await channel.send(embed=embed)
        await interaction.followup.send(
            embed=style.success("✅ Отправлено!"), ephemeral=True
        )

    @app_commands.command(name="добавить_день_рождения", description="Добавить день рождения участника")
    @app_commands.describe(user="Участник", date="Дата (ДД.ММ.ГГГГ)")
    async def add_birthday(
        self, interaction: discord.Interaction, user: discord.Member, date: str
    ) -> None:
        if not config.DATE_PATTERN.match(date):
            await interaction.response.send_message(
                embed=style.error(
                    "Ошибка", "❌ Неверный формат даты. Используй ДД.ММ.ГГГГ"
                ),
                ephemeral=True,
            )
            return

        try:
            datetime.strptime(date, "%d.%m.%Y")
        except ValueError:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "❌ Такой даты не существует."),
                ephemeral=True,
            )
            return

        await self.bot.db.execute(
            "INSERT INTO birthdays (user_id, date, notified, name) VALUES (?, ?, 0, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET date = excluded.date, name = excluded.name",
            (user.id, date, user.display_name),
        )

        await interaction.response.send_message(
            embed=style.success(
                "🎂 День рождения сохранён",
                f"✅ День рождения **{user.display_name}** установлен на **{date}**.",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="ближайшие_дни_рождения", description="Показать ближайшие дни рождения")
    async def upcoming_birthdays(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall("SELECT user_id, date, name FROM birthdays")
        if not rows:
            await interaction.response.send_message(
                embed=style.info("🎂 Дней рождения пока нет."), ephemeral=True
            )
            return

        now = msk_now()
        this_year = now.year

        upcoming: list[tuple[int, str, str]] = []
        for row in rows:
            try:
                bd = datetime.strptime(row["date"], "%d.%m.%Y")
            except (ValueError, TypeError):
                continue
            name = row.get("name") or f"<@{int(row['user_id'])}>"

            bd_this = bd.replace(year=this_year)
            if bd_this < now:
                bd_this = bd.replace(year=this_year + 1)

            days_until = (bd_this - now).days
            upcoming.append((days_until, name, row["date"]))

        upcoming.sort(key=lambda x: x[0])

        lines = []
        for days, name, bd_date in upcoming[:10]:
            if days == 0:
                lines.append(f"🎉 **{name}** — **СЕГОДНЯ!**")
            elif days == 1:
                lines.append(f"🔔 **{name}** — **ЗАВТРА!** ({bd_date})")
            else:
                lines.append(f"📅 **{name}** — через **{days}** дн. ({bd_date})")

        embed = style.base(
            "🎂 Ближайшие дни рождения",
            "\n".join(lines) if lines else "Нет данных.",
            color=discord.Color.pink(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ram", description="Показать потребление оперативной памяти")
    async def ram_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_ram_embed())

    @app_commands.command(name="ram_test", description="Отчёт tracemalloc по памяти (топ-20 строк)")
    async def ram_test_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if not tracemalloc.is_tracing():
            tracemalloc.start()

        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics("lineno")

        embed = style.base(
            "Отчёт tracemalloc",
            "\n".join(_tracemalloc_lines(top_stats)),
            color=style.SUCCESS,
            footer=f"Запросил {interaction.user.display_name}",
            timestamp=True,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="чугуний", description="Выстрелить артиллерией по участнику")
    @app_commands.describe(target="Цель для обстрела (если не указана — случайный)")
    async def artillery(
        self, interaction: discord.Interaction, target: discord.Member = None
    ) -> None:
        if not any(r.id == config.ARTY_ROLE for r in interaction.user.roles):
            await interaction.response.send_message(
                embed=style.error("Ошибка", "❌ Нет прав."), ephemeral=True
            )
            return

        if target is None:
            members = [
                m
                for m in interaction.guild.members
                if not m.bot and m.id != interaction.user.id
            ]
            if not members:
                await interaction.response.send_message(
                    embed=style.error("Ошибка", "Нет целей."), ephemeral=True
                )
                return
            target = random.choice(members)

        if target.id == interaction.user.id:
            await interaction.response.send_message(
                embed=style.warning(
                    "Ошибка", "Стрелять по себе — плохая идея."
                ),
                ephemeral=True,
            )
            return

        if target.bot:
            await interaction.response.send_message(
                embed=style.warning("Ошибка", "Боты неуязвимы для артиллерии."),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        types = _load_artillery()
        art = types[random.choice(list(types.keys()))]

        roll = random.random()
        dmg = 0

        if roll < art["chance_miss"]:
            result_type = "miss"
        elif roll < art["chance_miss"] + art["chance_crit"]:
            result_type = "destroy"
            dmg = random.randint(art["crit_min"], art["crit_max"])
        elif roll < art["chance_miss"] + art["chance_crit"] + art.get("chance_dud", 0):
            result_type = "dud"
        else:
            result_type = "hit"
            dmg = random.randint(art["dmg_min"], art["dmg_max"])

        flavor_text = random.choice(art["flavor"])

        result_icons = {
            "hit": "💥",
            "destroy": "💀",
            "miss": "💨",
            "dud": "🔩",
        }
        result_icon = result_icons[result_type]

        # result_text определяется ДО сборки сообщения — в старом коде ветка miss
        # обращалась к неопределённой переменной и падала с NameError.
        if result_type == "miss":
            result_text = random.choice(_MISS_TEXTS).format(target=target.mention)
        elif result_type == "destroy":
            result_text = (
                f"{target.mention} ликвидирован взрывом {art['emoji']} {art['name']}. "
                "Полное уничтожение!"
            )
        elif result_type == "dud":
            result_text = f"Снаряд не разорвался! {target.mention} повезло."
        else:
            result_text = (
                f"{target.mention} получил **{dmg}** урона! {flavor_text}"
            )

        text = (
            f"{interaction.user.mention} сбросил {art['emoji']} {art['name']} "
            f"на {target.mention}!\n"
            f"{result_icon} Результат: {result_text}"
        )

        await interaction.followup.send(text)

    @app_commands.command(name="webhook_create", description="Создать вебхук в канале")
    @app_commands.describe(channel="Канал для создания вебхука", name="Имя вебхука")
    async def webhook_create(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        name: str = "Webhook",
    ) -> None:
        if not interaction.user.guild_permissions.manage_webhooks:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нет прав."), ephemeral=True
            )
            return

        try:
            webhook = await channel.create_webhook(
                name=name, reason=f"Создал {interaction.user}"
            )
            embed = style.success(
                "✅ Вебхук создан",
                f"**Имя:** {webhook.name}\n"
                f"**Канал:** {channel.mention}\n"
                f"**URL:** {webhook.url}",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as exc:
            log.error("Не удалось создать вебхук: %s", exc, exc_info=True)
            await interaction.response.send_message(
                embed=style.error("Ошибка", f"❌ Ошибка: {exc}"), ephemeral=True
            )

    @app_commands.command(name="webhook_send", description="Отправить сообщение через вебхук")
    @app_commands.describe(
        url="URL вебхука",
        message="Текст сообщения",
        name="Имя (переопределить)",
        avatar_url="Аватар (переопределить)",
    )
    async def webhook_send(
        self,
        interaction: discord.Interaction,
        url: str,
        message: str,
        name: str = None,
        avatar_url: str = None,
    ) -> None:
        if not interaction.user.guild_permissions.manage_webhooks:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нет прав."), ephemeral=True
            )
            return

        try:
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(url, session=session)
                avatar = avatar_url if avatar_url else None
                await webhook.send(content=message, username=name, avatar_url=avatar)
            await interaction.response.send_message(
                embed=style.success("✅ Сообщение отправлено."), ephemeral=True
            )
        except Exception as exc:
            log.error("Не удалось отправить сообщение вебхука: %s", exc, exc_info=True)
            await interaction.response.send_message(
                embed=style.error("Ошибка", f"❌ Ошибка: {exc}"), ephemeral=True
            )

    @app_commands.command(name="webhook_list", description="Показать вебхуки в канале")
    @app_commands.describe(channel="Канал")
    async def webhook_list(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        if not interaction.user.guild_permissions.manage_webhooks:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нет прав."), ephemeral=True
            )
            return

        webhooks = await channel.webhooks()
        if not webhooks:
            await interaction.response.send_message(
                embed=style.info("Вебхуков нет."), ephemeral=True
            )
            return

        embed = style.base(f"🔗 Вебхуки — {channel.name}", color=style.INFO)
        for wh in webhooks:
            style.field(
                embed,
                wh.name,
                f"ID: `{wh.id}`\n"
                f"Создан: {wh.created_at.strftime('%d.%m.%Y') if wh.created_at else '—'}\n"
                f"URL: {wh.url}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="webhook_delete", description="Удалить вебхук")
    @app_commands.describe(url="URL вебхука")
    async def webhook_delete(
        self, interaction: discord.Interaction, url: str
    ) -> None:
        if not interaction.user.guild_permissions.manage_webhooks:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нет прав."), ephemeral=True
            )
            return

        try:
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(url, session=session)
                wh_name = webhook.name
                await webhook.delete(reason=f"Удалил {interaction.user}")
            await interaction.response.send_message(
                embed=style.success(f"✅ Вебхук **{wh_name}** удалён."), ephemeral=True
            )
        except Exception as exc:
            log.error("Не удалось удалить вебхук: %s", exc, exc_info=True)
            await interaction.response.send_message(
                embed=style.error("Ошибка", f"❌ Ошибка: {exc}"), ephemeral=True
            )

    @app_commands.command(name="roles_list", description="Вывести список всех ролей с ID")
    async def roles_list(self, interaction: discord.Interaction) -> None:
        if not style.is_admin(interaction):
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Нет прав."), ephemeral=True
            )
            return

        # Осознанно канал бэкапов (config.BACKUP_CHANNEL), а не канал вызова —
        # поведение старого кода сохранено.
        channel = self.bot.channel_of(config.BACKUP_CHANNEL)
        if not channel:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Канал не найден."), ephemeral=True
            )
            return

        roles = sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)

        lines = []
        for role in roles:
            if role == interaction.guild.default_role:
                continue
            lines.append(f"`{role.id}` — {role.mention} ({role.members.count} чел.)")

        chunks = [lines[i : i + 30] for i in range(0, len(lines), 30)]

        for idx, chunk in enumerate(chunks):
            title = "📋 Роли сервера"
            if len(chunks) > 1:
                title += f" (часть {idx + 1}/{len(chunks)})"
            embed = style.base(title, "\n".join(chunk), color=style.INFO)
            await channel.send(embed=embed)

        await interaction.response.send_message(
            embed=style.success("✅ Список ролей отправлен."), ephemeral=True
        )

    @app_commands.command(name="ai", description="ИИ без цензуры — дерзкие ответы на каждый день")
    @app_commands.describe(message="Что спросить (или оставь пустым для рандома)")
    async def ai_cmd(self, interaction: discord.Interaction, message: str = "") -> None:
        if interaction.channel_id != config.AI_CHANNEL:
            await interaction.response.send_message(
                embed=style.error(
                    "Ошибка", "🤖 Эта команда доступна только в канале ИИ."
                ),
                ephemeral=True,
            )
            return

        provider = config.AI_PROVIDER or detect_provider()
        if not provider:
            await interaction.response.send_message(
                embed=style.error(
                    "Ошибка",
                    "❌ Не настроен ни один ИИ-провайдер.\n"
                    "Добавь бесплатный ключ в `.env` и перезапусти бота:\n"
                    "- `OPENROUTER_API_KEY=` — бесплатные модели на openrouter.ai\n"
                    "- `GEMINI_API_KEY=` — бесплатный тариф на aistudio.google.com",
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        if not message:
            message = random.choice(config.AI_USER_TRIGGERS)

        system_prompt = random.choice(config.AI_SYSTEM_PROMPTS)

        try:
            reply, provider_name, status = await ask(provider, system_prompt, message)

            if reply is None:
                if status == 402:
                    await interaction.followup.send(
                        embed=style.error(
                            "Ошибка",
                            f"❌ У провайдера **{provider_name}** закончился баланс/лимит. "
                            "Попробуй позже или смени провайдера.",
                        )
                    )
                    return
                if status == 0:
                    await interaction.followup.send(
                        embed=style.error(
                            "Ошибка", "❌ ИИ не отвечает (таймаут). Попробуй позже."
                        )
                    )
                    return
                await interaction.followup.send(
                    embed=style.error(
                        "Ошибка",
                        f"❌ Ошибка API (код {status}) у провайдера **{provider_name}**. "
                        "Попробуй позже.",
                    )
                )
                return

            if len(reply) > 1900:
                reply = reply[:1900] + "..."

            embed = style.base(
                f"🤖 ИИ ({provider_name})",
                reply,
                color=style.AI,
                footer=f"Запрос: {message[:100]}",
            )
            await interaction.followup.send(embed=embed)

        except asyncio.TimeoutError:
            await interaction.followup.send(
                embed=style.error(
                    "Ошибка", "❌ ИИ не отвечает (таймаут). Попробуй позже."
                )
            )
        except Exception as exc:
            log.error("Ошибка AI: %s", exc, exc_info=True)
            await interaction.followup.send(
                embed=style.error("Ошибка", "❌ Произошла ошибка при обращении к ИИ.")
            )

    # ═══════════════════════════════════════
    #  ФОНОВЫЕ ЗАДАНИЯ (через bot.scheduler)
    # ═══════════════════════════════════════

    async def birthday_check(self) -> None:
        """Поздравляет именинников в config.BIRTHDAY_CHANNEL (job: birthdays)."""
        now = msk_now()
        today_str = now.strftime("%d.%m")

        rows = await self.bot.db.fetchall("SELECT user_id, date, name FROM birthdays")

        today_users = []
        for row in rows:
            try:
                bd = datetime.strptime(row["date"], "%d.%m.%Y")
            except (ValueError, TypeError):
                continue
            if bd.strftime("%d.%m") == today_str:
                today_users.append(row)

        if not today_users:
            return

        channel = self.bot.channel_of(config.BIRTHDAY_CHANNEL)
        if not channel:
            return

        for info in today_users:
            user_id = int(info["user_id"])
            name = info.get("name") or f"<@{user_id}>"

            embed = style.base(
                "🎂 С Днём Рождения!",
                (
                    f"Сегодня **{name}** празднует день рождения!\n\n"
                    "Поздравляем! Желаем здоровья, счастья и удачи! 🎉🥳"
                ),
                color=discord.Color.pink(),
            )
            try:
                guild = (
                    self.bot.get_guild(config.GUILD_ID.id)
                    if config.GUILD_ID
                    else (self.bot.guilds[0] if self.bot.guilds else None)
                )
                member = await guild.fetch_member(user_id) if guild else None
                if member:
                    embed.set_thumbnail(url=member.display_avatar.url)
                    await channel.send(content=member.mention, embed=embed)
                else:
                    await channel.send(embed=embed)
            except Exception as exc:
                log.warning("Не удалось поздравить %s: %s", user_id, exc)
                await channel.send(embed=embed)

    async def daily_backup(self) -> None:
        """Ежедневный ZIP-бэкап в config.BACKUP_CHANNEL (job: backup)."""
        await send_backup(self.bot, self.bot.db)

    async def daily_morning(self) -> None:
        """Утренний пост в config.DAILY_CHANNEL (job: morning)."""
        try:
            sent = await send_morning(self.bot)
            if sent:
                log.info("Ежедневное сообщение отправлено")
        except Exception as exc:
            log.error("Ошибка отправки ежедневного сообщения: %s", exc, exc_info=True)

    async def ram_monitor(self) -> None:
        """Отчёт о памяти в config.RAM_LOG_CHANNEL (job: ram_monitor)."""
        try:
            ch = self.bot.channel_of(config.RAM_LOG_CHANNEL)
            if not ch:
                return
            await ch.send(embed=build_ram_embed())
        except Exception as exc:
            log.error("Ошибка ram_monitor: %s", exc, exc_info=True)

    async def tracemalloc_monitor(self) -> None:
        """Мёртвое задание: в оригинале объявлено, но не запускалось.

        Намеренно НЕ регистрируется в планировщике — поведение не меняем.
        """
        try:
            ch = self.bot.channel_of(config.RAM_LOG_CHANNEL)
            if not ch:
                return

            if not tracemalloc.is_tracing():
                return

            snapshot = tracemalloc.take_snapshot()
            top_stats = snapshot.statistics("lineno")

            embed = style.base(
                "Отчёт tracemalloc",
                "\n".join(_tracemalloc_lines(top_stats)),
                color=style.SUCCESS,
                timestamp=True,
            )
            await ch.send(embed=embed)
        except Exception as exc:
            log.error("Ошибка tracemalloc_monitor: %s", exc, exc_info=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MiscCog(bot))
