import sys
import os
import logging

import discord
from discord import app_commands
from discord.ext import commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class RolePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for role_id, label, style in config.ROLE_PANEL_ROLES:
            btn = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"role_toggle_{role_id}"
            )
            btn.callback = self.make_callback(role_id, label)
            self.add_item(btn)

    def make_callback(self, role_id: int, label: str):
        async def callback(interaction: discord.Interaction):
            member = interaction.guild.get_member(interaction.user.id)
            if not member:
                return await interaction.response.send_message("Ошибка.", ephemeral=True)

            role = interaction.guild.get_role(role_id)
            if not role:
                return await interaction.response.send_message("Роль не найдена.", ephemeral=True)

            if role in member.roles:
                await member.remove_roles(role, reason="Роль снята через панель")
                await interaction.response.send_message(
                    f"Роль **{label}** снята.", ephemeral=True
                )
            else:
                await member.add_roles(role, reason="Роль выдана через панель")
                await interaction.response.send_message(
                    f"Роль **{label}** выдана.", ephemeral=True
                )
        return callback

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        logging.error("Ошибка в RolePanelView: %s", error, exc_info=True)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("Произошла ошибка.", ephemeral=True)
            else:
                await interaction.response.send_message("Произошла ошибка.", ephemeral=True)
        except Exception:
            pass


class RoleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="role_panel", description="[Админ] Отправить панель ролей в канал")
    @app_commands.describe(channel="Канал для панели")
    async def role_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        embed = discord.Embed(
            title="🎭 Автовыдача ролей",
            description=(
                "👉 **Автовыдача ролей** 👈\n"
                "Нажмите на соответствующую реакцию под сообщением, чтобы получить желаемую роль. "
                "Перед этим внимательно прочитайте описание ролей.\n\n"
                "P.s. по данным ролям Вас будут пинговать в каналах, учтите это.\n\n"
                "**Arma**\n"
                "Для игроков в Arma Reforger - тут ебут и высокие требования к игрокам\n\n"
                "**Radmir**\n"
                "Для игроков на RP серверах RADMIR - чилл, расслабон\n\n"
                "**VR**\n"
                "Для игроков в VR игры (хентай игры)\n\n"
                "**Сидер**\n"
                "Для тех кто помогает поднимать сервера (за это есть плюшки)"
            ),
            color=discord.Color.blurple()
        )

        await interaction.response.defer(ephemeral=True)

        await channel.send(embed=embed, view=RolePanelView())

        await interaction.followup.send(
            f"✅ Панель ролей отправлена в {channel.mention}",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleCog(bot))
