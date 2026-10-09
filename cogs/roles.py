"""Панель автовыдачи ролей: /role_panel и персистентные кнопки-тогглы."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from ui import style

log = logging.getLogger(__name__)

PANEL_TITLE = "🎭 Автовыдача ролей"
PANEL_DESCRIPTION = (
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
)


class RolePanelView(discord.ui.View):
    """Кнопки строятся из config.ROLE_PANEL_ROLES, custom_id: role_toggle_{role_id}."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        for role_id, label, button_style in config.ROLE_PANEL_ROLES:
            button = discord.ui.Button(
                label=label,
                style=button_style,
                custom_id=f"role_toggle_{role_id}",
            )
            button.callback = self.make_callback(role_id, label)
            self.add_item(button)

    def make_callback(self, role_id: int, label: str):
        async def callback(interaction: discord.Interaction):
            guild = interaction.guild
            if guild is None:
                return await interaction.response.send_message(
                    embed=style.error("Ошибка."), ephemeral=True
                )

            member = guild.get_member(interaction.user.id)
            if not member:
                return await interaction.response.send_message(
                    embed=style.error("Ошибка."), ephemeral=True
                )

            role = guild.get_role(role_id)
            if not role:
                return await interaction.response.send_message(
                    embed=style.error("Роль не найдена."), ephemeral=True
                )

            if role in member.roles:
                await member.remove_roles(role, reason="Роль снята через панель")
                await interaction.response.send_message(
                    embed=style.info(PANEL_TITLE, f"Роль **{label}** снята."),
                    ephemeral=True,
                )
            else:
                await member.add_roles(role, reason="Роль выдана через панель")
                await interaction.response.send_message(
                    embed=style.success(PANEL_TITLE, f"Роль **{label}** выдана."),
                    ephemeral=True,
                )
        return callback

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        log.error("Ошибка в RolePanelView: %s", error, exc_info=True)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    embed=style.error("Произошла ошибка."), ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    embed=style.error("Произошла ошибка."), ephemeral=True
                )
        except Exception:
            log.warning("Не удалось ответить на ошибку RolePanelView")


class RoleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_persistent_view(RolePanelView())

    @app_commands.command(name="role_panel", description="[Админ] Отправить панель ролей в канал")
    @app_commands.describe(channel="Канал для панели")
    async def role_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not style.is_admin(interaction):
            return await interaction.response.send_message(
                embed=style.error("Нет прав."), ephemeral=True
            )

        embed = style.base(
            PANEL_TITLE,
            PANEL_DESCRIPTION,
            color=discord.Color.blurple(),
            footer=None,
        )

        await interaction.response.defer(ephemeral=True)

        await channel.send(embed=embed, view=RolePanelView())

        await interaction.followup.send(
            embed=style.success(
                "✅ Готово", f"Панель ролей отправлена в {channel.mention}"
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleCog(bot))
