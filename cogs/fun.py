"""Развлекательные команды: дуэли, КНБ, кубик, шар, голосования, напоминания."""

from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.timeutil import msk_now
from ui import style

log = logging.getLogger(__name__)

DUELS_KEY = "active_duels"
DUEL_TTL = timedelta(minutes=3)

POLL_REACTIONS = (
    "1️⃣",
    "2️⃣",
    "3️⃣",
    "4️⃣",
    "5️⃣",
    "6️⃣",
    "7️⃣",
    "8️⃣",
    "9️⃣",
    "🔟",
)


def _pair_key(user_a: int, user_b: int) -> str:
    first, second = sorted((user_a, user_b))
    return f"{first}_{second}"


async def _active_duels(bot: commands.Bot) -> dict[str, str]:
    data = await bot.state.get(DUELS_KEY, {})
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def _duel_is_fresh(expires_at: str, now: datetime) -> bool:
    try:
        deadline = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=now.tzinfo)
    return deadline >= now


async def _duel_reserve(bot: commands.Bot, pair_key: str) -> bool:
    """True — вызов записан в bot.state, False — пара уже занята."""
    now = msk_now()
    duels = {
        key: expires
        for key, expires in (await _active_duels(bot)).items()
        if _duel_is_fresh(expires, now)
    }
    if pair_key in duels:
        return False
    duels[pair_key] = (now + DUEL_TTL).isoformat(timespec="seconds")
    await bot.state.set(DUELS_KEY, duels)
    return True


async def _duel_release(bot: commands.Bot, pair_key: str) -> None:
    duels = await _active_duels(bot)
    if pair_key in duels:
        duels.pop(pair_key)
        await bot.state.set(DUELS_KEY, duels)


class FunCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.scheduler.register_interval(
            "reminders", self.deliver_reminders, seconds=15
        )

    # ------------------------------------------------------------ команды

    @app_commands.command(name="дуэль", description="Вызвать участника на дуэль")
    @app_commands.describe(opponent="Участник для дуэли")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member):
        if opponent.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=style.error("❌ Нельзя дуэлиться с самим собой."), ephemeral=True
            )
        if opponent.bot:
            return await interaction.response.send_message(
                embed=style.error("❌ Боты не участвуют в дуэлях."), ephemeral=True
            )

        pair_key = _pair_key(interaction.user.id, opponent.id)
        if not await _duel_reserve(self.bot, pair_key):
            return await interaction.response.send_message(
                embed=style.error("❌ Дуэль уже запланирована между этими игроками."),
                ephemeral=True,
            )

        embed = style.base(
            "⚔️ Дуэль!",
            (
                f"**{interaction.user.mention}** вызывает **{opponent.mention}** на дуэль!\n\n"
                f"{opponent.mention}, нажми кнопку ниже чтобы принять вызов!"
            ),
            color=discord.Color.red(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        view = DuelAcceptView(
            challenger=interaction.user,
            opponent=opponent,
            bot=self.bot,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="рпс", description="Камень-ножницы-бумага")
    @app_commands.describe(choice="Твой выбор")
    @app_commands.choices(choice=[
        app_commands.Choice(name="🪨 Камень", value="rock"),
        app_commands.Choice(name="✂️ Ножницы", value="scissors"),
        app_commands.Choice(name="📄 Бумага", value="paper"),
    ])
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        choices = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}
        bot_choice = random.choice(list(choices.keys()))
        user_val = choice.value

        if user_val == bot_choice:
            result = "Ничья!"
            color = discord.Color.gold()
        elif (
            (user_val == "rock" and bot_choice == "scissors")
            or (user_val == "scissors" and bot_choice == "paper")
            or (user_val == "paper" and bot_choice == "rock")
        ):
            result = "Ты победил!"
            color = discord.Color.green()
        else:
            result = "Ты проиграл!"
            color = discord.Color.red()

        embed = style.base(
            "🪨✂️📄 Камень-Ножницы-Бумага",
            (
                f"**Ты:** {choices[user_val]}\n"
                f"**Бот:** {choices[bot_choice]}\n\n"
                f"**{result}**"
            ),
            color=color,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dice", description="Бросить кубик (1-100)")
    @app_commands.describe(sides="Количество граней (по умолчанию 6)")
    async def dice(self, interaction: discord.Interaction, sides: int = 6):
        if sides < 2 or sides > 100:
            return await interaction.response.send_message(
                embed=style.error("❌ Кубик должен иметь от 2 до 100 граней."),
                ephemeral=True,
            )
        result = random.randint(1, sides)
        await interaction.response.send_message(
            embed=style.base("🎲 Кубик", f"**{result}** (из {sides})")
        )

    @app_commands.command(name="8ball", description="Магический шар ответов")
    @app_commands.describe(question="Задай вопрос шару")
    async def eight_ball(self, interaction: discord.Interaction, question: str):
        answers_positive = [
            "Безусловно да.", "Определённо да.", "Можешь рассчитывать на это.",
            "Да, конечно.", "Да, если постараешься.",
        ]
        answers_neutral = [
            "Спроси позже.", "Лучше не отвечать сейчас.",
            "Не могу предсказать.", "Сконцентрируйся и спроси снова.",
            "Магический шар колеблется...",
        ]
        answers_negative = [
            "Мой ответ — нет.", "Не стоит на это надеяться.",
            "Сомневаюсь.", "Вряд ли.", "Однозначно нет.",
        ]
        roll = random.random()
        if roll < 0.35:
            answer = random.choice(answers_positive)
            color = discord.Color.green()
        elif roll < 0.65:
            answer = random.choice(answers_neutral)
            color = discord.Color.gold()
        else:
            answer = random.choice(answers_negative)
            color = discord.Color.red()

        embed = style.base("🎱 Магический шар", color=color)
        embed.add_field(name="Вопрос", value=question, inline=False)
        embed.add_field(name="Ответ", value=f"*{answer}*", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="poll", description="Создать голосование")
    @app_commands.describe(
        question="Вопрос голосования",
        option1="Вариант 1",
        option2="Вариант 2",
        option3="Вариант 3 (необязательно)",
        option4="Вариант 4 (необязательно)",
    )
    async def poll(
        self, interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str = None,
        option4: str = None,
    ):
        options = [opt for opt in [option1, option2, option3, option4] if opt]
        if len(options) < 2:
            return await interaction.response.send_message(
                embed=style.error("❌ Нужно минимум 2 варианта."), ephemeral=True
            )
        if len(options) > 10:
            return await interaction.response.send_message(
                embed=style.error("❌ Максимум 10 вариантов."), ephemeral=True
            )

        lines = [f"{POLL_REACTIONS[i]} {opt}" for i, opt in enumerate(options)]

        embed = style.base(
            f"📊 {question}",
            "\n".join(lines),
            color=discord.Color.blurple(),
            footer=f"Голосование от {interaction.user.display_name}",
        )
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        for i in range(len(options)):
            await msg.add_reaction(POLL_REACTIONS[i])

    @app_commands.command(name="remind", description="Напомнить через указанное время")
    @app_commands.describe(
        time="Время (например: 10м, 2ч, 1д)",
        message="Текст напоминания",
    )
    async def remind(self, interaction: discord.Interaction, time: str, message: str):
        match = re.match(r"(\d+)\s*(м|мин|ч|чч|д|дн)", time.lower())
        if not match:
            return await interaction.response.send_message(
                embed=style.error("❌ Формат времени: `10м`, `2ч`, `1д`"), ephemeral=True
            )

        amount = int(match.group(1))
        unit = match.group(2)

        if unit in ("м", "мин"):
            delta = timedelta(minutes=amount)
        elif unit in ("ч", "чч"):
            delta = timedelta(hours=amount)
        elif unit in ("д", "дн"):
            delta = timedelta(days=amount)
        else:
            return await interaction.response.send_message(
                embed=style.error("❌ Неизвестная единица времени."), ephemeral=True
            )

        if delta > timedelta(days=config.REMINDER_MAX_DAYS):
            return await interaction.response.send_message(
                embed=style.error(
                    f"❌ Максимальное время — {config.REMINDER_MAX_DAYS} дней."
                ),
                ephemeral=True,
            )

        fire_at = msk_now() + delta
        await self.bot.reminders.add(
            interaction.user.id,
            interaction.channel_id or 0,
            fire_at,
            message,
        )

        embed = style.success(
            "⏰ Напоминание установлено",
            f"**Через:** {time}\n**Напоминание:** {message}",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------ доставка напоминаний

    async def deliver_reminders(self) -> None:
        """Фоновое задание: забирает созревшие напоминания из bot.reminders."""
        now = msk_now()
        try:
            rows = await self.bot.reminders.due(now)
        except Exception as exc:
            log.error("Не удалось получить напоминания: %s", exc)
            return

        for row in rows:
            reminder_id = int(row["id"])
            try:
                await self._send_reminder(row)
            except Exception as exc:
                log.warning("Не удалось доставить напоминание %s: %s", reminder_id, exc)
            await self.bot.reminders.mark_delivered(reminder_id)

    async def _send_reminder(self, row: dict) -> None:
        user_id = int(row["user_id"])
        channel_id = int(row.get("channel_id") or 0)
        text = str(row.get("message") or "")
        mention = f"<@{user_id}>"
        dm_embed = style.base(
            "⏰ Напоминание", text, color=discord.Color.gold(), footer=None
        )
        dm_embed.timestamp = discord.utils.utcnow()

        try:
            user = await self.bot.fetch_user(user_id)
            dm = await user.create_dm()
            await dm.send(content=mention, embed=dm_embed)
            return
        except discord.Forbidden:
            pass
        except discord.HTTPException as exc:
            log.warning("Не удалось отправить напоминание в ЛС %s: %s", user_id, exc)
            return

        channel = self.bot.channel_of(channel_id)
        if channel is None:
            log.warning(
                "Напоминание для %s не доставлено: канал %s недоступен",
                user_id,
                channel_id,
            )
            return
        try:
            await channel.send(
                content=mention,
                embed=style.base(
                    "⏰ Напоминание", text, color=discord.Color.gold(), footer=None
                ),
            )
        except discord.HTTPException as exc:
            log.warning(
                "Не удалось отправить напоминание в канал %s: %s", channel_id, exc
            )


class DuelAcceptView(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member, bot: commands.Bot):
        super().__init__(timeout=30)
        self.challenger = challenger
        self.opponent = opponent
        self.bot = bot
        self.pair_key = _pair_key(challenger.id, opponent.id)

    @discord.ui.button(label="Принять вызов", style=discord.ButtonStyle.red, emoji="⚔️")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            return await interaction.response.send_message(
                embed=style.error("❌ Этот вызов не для тебя."), ephemeral=True
            )

        await _duel_release(self.bot, self.pair_key)
        self.stop()

        a_hp = 100
        b_hp = 100
        a_name = self.challenger.mention
        b_name = self.opponent.mention
        rounds_log = []

        turn = 0
        while a_hp > 0 and b_hp > 0:
            turn += 1
            a_dmg = random.randint(10, 30)
            b_dmg = random.randint(10, 30)

            a_crit = random.random() < 0.15
            b_crit = random.random() < 0.15
            if a_crit:
                a_dmg = int(a_dmg * 2)
            if b_crit:
                b_dmg = int(b_dmg * 2)

            b_hp -= a_dmg
            a_hp -= b_dmg

            crit_a = " 💥 КРИТ!" if a_crit else ""
            crit_b = " 💥 КРИТ!" if b_crit else ""
            rounds_log.append(
                f"**Раунд {turn}:** {a_name} → **{a_dmg}**{crit_a} | "
                f"{b_name} → **{b_dmg}**{crit_b}"
            )

        if a_hp <= 0 and b_hp <= 0:
            winner_text = "Ничья! Оба полегли!"
            color = discord.Color.gold()
        elif a_hp <= 0:
            winner_text = f"🏆 **{self.opponent.display_name}** победил!"
            color = discord.Color.green()
        else:
            winner_text = f"🏆 **{self.challenger.display_name}** победил!"
            color = discord.Color.green()

        embed = style.base(
            "⚔️ Результаты дуэли",
            "\n".join(rounds_log[-5:]) + f"\n\n{winner_text}",
            color=color,
            footer=(
                f"{self.challenger.display_name} {max(0, a_hp)} HP | "
                f"{self.opponent.display_name} {max(0, b_hp)} HP"
            ),
        )

        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        await _duel_release(self.bot, self.pair_key)
        for item in self.children:
            item.disabled = True


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunCog(bot))
