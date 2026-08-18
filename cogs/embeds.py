import sys
import os

import discord
from discord import app_commands
from discord.ext import commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class EmbedModal(discord.ui.Modal, title="Генератор эмбедов"):

    embed_title = discord.ui.TextInput(
        label="Заголовок",
        required=True,
        max_length=256
    )

    embed_description = discord.ui.TextInput(
        label="Описание",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=4000
    )

    embed_color = discord.ui.TextInput(
        label="Цвет (red, blue, green, gold...)",
        required=False,
        placeholder="red"
    )

    embed_footer = discord.ui.TextInput(
        label="Подвал (необязательно)",
        required=False,
        max_length=2048
    )

    async def on_submit(self, interaction: discord.Interaction):
        color_str = (self.embed_color.value or "red").lower().strip()
        color = config.EMBED_COLORS.get(color_str, discord.Color.red())

        embed = discord.Embed(
            title=self.embed_title.value,
            description=self.embed_description.value,
            color=color
        )

        if self.embed_footer.value:
            embed.set_footer(text=self.embed_footer.value)

        await interaction.response.send_message(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none()
        )


class EmbedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="embed", description="[Админ] Создать эмбед через модалку")
    async def embed_cmd(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)
        await interaction.response.send_modal(EmbedModal())

    @app_commands.command(name="embed_send", description="[Админ] Отправить эмбед в канал")
    @app_commands.describe(
        channel="Канал для отправки",
        title="Заголовок",
        description="Описание",
        color="Цвет (red, blue, green, gold...)",
        footer="Подвал (необязательно)"
    )
    async def embed_send(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        description: str,
        color: str = "red",
        footer: str = "",
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        color_obj = config.EMBED_COLORS.get(color.lower().strip(), discord.Color.red())

        embed = discord.Embed(
            title=title,
            description=description,
            color=color_obj
        )

        if footer:
            embed.set_footer(text=footer)

        await channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none()
        )

        await interaction.response.send_message(
            f"✅ Эмбед отправлен в {channel.mention}",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedCog(bot))
