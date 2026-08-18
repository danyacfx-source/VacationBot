import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import config

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

GUILD = config.GUILD_ID

@bot.tree.command(name="find_member", description="Поиск участника по нику")
@app_commands.describe(query="Часть ника")
async def find_member(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True)
    results = []
    q = query.lower()
    for member in interaction.guild.members:
        if q in member.name.lower() or q in member.display_name.lower():
            results.append(f"`{member.id}` — {member.name} ({member.display_name})")
    if not results:
        await interaction.followup.send(f"Не найдено по запросу: `{query}`", ephemeral=True)
    else:
        await interaction.followup.send("\n".join(results[:25]), ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.tree.sync(guild=GUILD)
    print("Synced")
    await bot.close()

bot.run(config.TOKEN)
