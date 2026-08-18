import discord
from discord.ext import commands

class ExampleCog(commands.Cog):
    """Простой пример расширения (cog)."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="hi")
    async def hi(self, ctx: commands.Context):
        """Отправляет приветственное сообщение."""
        await ctx.send("👋 Привет! Я пример cog.")

async def setup(bot: commands.Bot):
    await bot.add_cog(ExampleCog(bot))
