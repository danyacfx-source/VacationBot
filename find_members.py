import asyncio
import discord
from dotenv import load_dotenv
import os

load_dotenv(override=True)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

MEMBERS_TO_FIND = [
    "diska2k19",
    "рикс",
    "rixulkin",
    "кибер",
    "турист",
    "slavyan",
    "славян",
    "delorang",
    "пяточк",
    "aloves",
    "alove",
    "илюх",
    "нот_фаунд",
    "нот фаунд",
    "not_found",
    "jesus",
    "guushka",
    "лиiiii",
    "gushk",
    "mixail",
    "миша",
    "микс",
    "789478346202415124",
]

async def main():
    intents = discord.Intents.default()
    intents.members = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        guild = client.get_guild(GUILD_ID)
        if not guild:
            print("Guild not found")
            await client.close()
            return

        print(f"Guild: {guild.name} ({guild.member_count} members)")
        found = set()
        for member in guild.members:
            name_lower = member.name.lower()
            display_lower = member.display_name.lower()
            for search in MEMBERS_TO_FIND:
                if search.lower() in name_lower or search.lower() in display_lower:
                    if member.id not in found:
                        found.add(member.id)
                        print(f"  {member.name} ({member.display_name}) -> {member.id}")
                    break

        # Also dump all members for manual search
        print("\n=== ALL MEMBERS ===")
        for member in guild.members:
            print(f"  {member.name} | {member.display_name} | {member.id}")

        await client.close()

    await client.start(TOKEN)

asyncio.run(main())
