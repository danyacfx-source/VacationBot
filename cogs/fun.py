import sys
import os
import asyncio
import random
import re
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord import app_commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class FunCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_duels = {}

    @app_commands.command(name="дуэль", description="Вызвать участника на дуэль")
    @app_commands.describe(opponent="Участник для дуэли")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member):
        if opponent.id == interaction.user.id:
            return await interaction.response.send_message(
                "❌ Нельзя дуэлиться с самим собой.", ephemeral=True
            )
        if opponent.bot:
            return await interaction.response.send_message(
                "❌ Боты не участвуют в дуэлях.", ephemeral=True
            )
        pair_key = tuple(sorted([interaction.user.id, opponent.id]))
        if pair_key in self.active_duels:
            return await interaction.response.send_message(
                "❌ Дуэль уже запланирована между этими игроками.", ephemeral=True
            )

        self.active_duels[pair_key] = True

        embed = discord.Embed(
            title="⚔️ Дуэль!",
            description=(
                f"**{interaction.user.mention}** вызывает **{opponent.mention}** на дуэль!\n\n"
                f"{opponent.mention}, нажми кнопку ниже чтобы принять вызов!"
            ),
            color=discord.Color.red(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        view = DuelAcceptView(
            challenger=interaction.user,
            opponent=opponent,
            active_duels=self.active_duels,
            pair_key=pair_key,
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

        embed = discord.Embed(
            title="🪨✂️📄 Камень-Ножницы-Бумага",
            description=(
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
                "❌ Кубик должен иметь от 2 до 100 граней.", ephemeral=True
            )
        result = random.randint(1, sides)
        await interaction.response.send_message(
            f"🎲 **{result}** (из {sides})"
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

        embed = discord.Embed(
            title="🎱 Магический шар",
            color=color,
        )
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
                "❌ Нужно минимум 2 варианта.", ephemeral=True
            )
        if len(options) > 10:
            return await interaction.response.send_message(
                "❌ Максимум 10 вариантов.", ephemeral=True
            )

        reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

        lines = []
        for i, opt in enumerate(options):
            lines.append(f"{reactions[i]} {opt}")

        embed = discord.Embed(
            title=f"📊 {question}",
            description="\n".join(lines),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Голосование от {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        for i in range(len(options)):
            await msg.add_reaction(reactions[i])

    @app_commands.command(name="remind", description="Напомнить через указанное время")
    @app_commands.describe(
        time="Время (например: 10м, 2ч, 1д)",
        message="Текст напоминания",
    )
    async def remind(self, interaction: discord.Interaction, time: str, message: str):
        match = re.match(r"(\d+)\s*(м|мин|ч|чч|д|дн)", time.lower())
        if not match:
            return await interaction.response.send_message(
                "❌ Формат времени: `10м`, `2ч`, `1д`", ephemeral=True
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
                "❌ Неизвестная единица времени.", ephemeral=True
            )

        if delta.total_seconds() > 86400 * 7:
            return await interaction.response.send_message(
                "❌ Максимальное время — 7 дней.", ephemeral=True
            )

        embed = discord.Embed(
            title="⏰ Напоминание установлено",
            description=(
                f"**Через:** {time}\n"
                f"**Напоминание:** {message}"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        await asyncio.sleep(delta.total_seconds())

        try:
            user = await self.bot.fetch_user(interaction.user.id)
            dm = await user.create_dm()
            await dm.send(
                content=interaction.user.mention,
                embed=discord.Embed(
                    title="⏰ Напоминание",
                    description=message,
                    color=discord.Color.gold(),
                    timestamp=discord.utils.utcnow(),
                ),
            )
        except discord.Forbidden:
            try:
                channel = interaction.channel
                await channel.send(
                    content=interaction.user.mention,
                    embed=discord.Embed(
                        title="⏰ Напоминание",
                        description=message,
                        color=discord.Color.gold(),
                    ),
                )
            except Exception:
                pass


class DuelAcceptView(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member, active_duels: dict, pair_key: tuple):
        super().__init__(timeout=30)
        self.challenger = challenger
        self.opponent = opponent
        self.active_duels = active_duels
        self.pair_key = pair_key

    @discord.ui.button(label="Принять вызов", style=discord.ButtonStyle.red, emoji="⚔️")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            return await interaction.response.send_message(
                "❌ Этот вызов не для тебя.", ephemeral=True
            )

        self.active_duels.pop(self.pair_key, None)
        self.stop()

        a_hp = 100
        b_hp = 100
        a_name = self.challenger.mention
        b_name = self.opponent.mention
        log = []

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
            log.append(
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

        embed = discord.Embed(
            title="⚔️ Результаты дуэли",
            description="\n".join(log[-5:]) + f"\n\n{winner_text}",
            color=color,
        )
        embed.set_footer(
            text=f"{self.challenger.display_name} {max(0, a_hp)} HP | {self.opponent.display_name} {max(0, b_hp)} HP"
        )

        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        self.active_duels.pop(self.pair_key, None)
        for item in self.children:
            item.disabled = True


async def setup(bot: commands.Bot):
    await bot.add_cog(FunCog(bot))
