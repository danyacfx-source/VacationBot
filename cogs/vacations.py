import sys
import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import config

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import send_vacation_log, load_vacations, save_vacations, build_info_panel_embed, build_request_panel_embed, update_vacation_panel

VACATION_ROLE_ID = 1479161484897423433
PANEL_ROLE_ID = 1459877837388513494
PING_ROLE_1 = 1509699660149821601
PING_ROLE_2 = 1484506106897109125
VACATION_RETURN_NOTIFIED = set()


class VacationModal(discord.ui.Modal, title="Заявка на отпуск"):
    start_date = discord.ui.TextInput(
        label="Дата начала (ДД.ММ.ГГГГ)",
        placeholder="25.07.2026",
        required=True,
        max_length=10,
    )
    end_date = discord.ui.TextInput(
        label="Дата окончания (ДД.ММ.ГГГГ)",
        placeholder="10.08.2026",
        required=True,
        max_length=10,
    )
    reason = discord.ui.TextInput(
        label="Причина",
        placeholder="Укажите причину отпуска",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            start = datetime.strptime(self.start_date.value.strip(), "%d.%m.%Y")
        except ValueError:
            await interaction.response.send_message(
                "❌ Неверный формат даты начала. Используйте ДД.ММ.ГГГГ.", ephemeral=True
            )
            return

        try:
            end = datetime.strptime(self.end_date.value.strip(), "%d.%m.%Y")
        except ValueError:
            await interaction.response.send_message(
                "❌ Неверный формат даты окончания. Используйте ДД.ММ.ГГГГ.", ephemeral=True
            )
            return

        if end < start:
            await interaction.response.send_message(
                "❌ Дата окончания не может быть раньше даты начала.", ephemeral=True
            )
            return

        reason = self.reason.value.strip()

        vacations = load_vacations()
        user_id_str = str(interaction.user.id)

        if user_id_str not in vacations:
            vacations[user_id_str] = {
                "user_name": str(interaction.user),
                "periods": [],
            }

        vacation = vacations[user_id_str]
        vacation["user_name"] = str(interaction.user)
        vacation["periods"].append({
            "start_date": start.strftime("%d.%m.%Y"),
            "end_date": end.strftime("%d.%m.%Y"),
            "reason": reason,
        })

        save_vacations(vacations)

        role = interaction.guild.get_role(VACATION_ROLE_ID)
        if role:
            await interaction.user.add_roles(role, reason="Одобрена заявка на отпуск")

        days = (end - start).days + 1
        await interaction.response.send_message(
            f"✅ Ваш отпуск одобрен!\n"
            f"📅 С **{start.strftime('%d.%m.%Y')}** по **{end.strftime('%d.%m.%Y')}** ({days} дн.)",
            ephemeral=True,
        )

        await send_vacation_log(
            interaction.client,
            "🏖️ Отпуск одобрен",
            f"**Пользователь:** {interaction.user.mention}\n"
            f"**Период:** {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')} ({days} дн.)\n"
            f"**Причина:** {reason}",
        )

        await update_vacation_panel(interaction.client)


class LegacyVacationPanelView(discord.ui.View):
    VACATION_ROLE = 1459877837388513494

    def __init__(self):
        super().__init__(timeout=None)

    def _has_vacation_role(self, member: discord.Member) -> bool:
        return any(r.id == self.VACATION_ROLE for r in member.roles)

    @discord.ui.button(label="Заявка на отпуск", style=discord.ButtonStyle.green, custom_id="vacation_panel_request")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._has_vacation_role(interaction.user):
            await interaction.response.send_message("❌ У вас нет роли для подачи заявок на отпуск.", ephemeral=True)
            return
        await interaction.response.send_modal(VacationModal())

    @discord.ui.button(label="Статус отпуска", style=discord.ButtonStyle.blurple, custom_id="vacation_panel_status")
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._has_vacation_role(interaction.user):
            await interaction.response.send_message("❌ У вас нет роли для просмотра статуса.", ephemeral=True)
            return
        vacations = load_vacations()
        user_id_str = str(interaction.user.id)
        if user_id_str not in vacations:
            await interaction.response.send_message("❌ У вас нет отпусков.", ephemeral=True)
            return
        v = vacations[user_id_str]
        embed = discord.Embed(title="🏖️ Ваши отпуска", color=discord.Color.blue())
        for i, p in enumerate(v.get("periods", []), 1):
            embed.add_field(
                name=f"Период {i}",
                value=f"📅 {p['start_date']} — {p['end_date']}\n📝 {p['reason']}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Отменить отпуск", style=discord.ButtonStyle.red, custom_id="vacation_panel_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._has_vacation_role(interaction.user):
            await interaction.response.send_message("❌ У вас нет роли для отмены отпуска.", ephemeral=True)
            return
        vacations = load_vacations()
        user_id_str = str(interaction.user.id)
        if user_id_str not in vacations:
            await interaction.response.send_message("❌ У вас нет отпусков.", ephemeral=True)
            return
        del vacations[user_id_str]
        save_vacations(vacations)
        role = interaction.guild.get_role(VACATION_ROLE_ID)
        if role:
            await interaction.user.remove_roles(role, reason="Отмена отпуска")
        await interaction.response.send_message("✅ Все ваши отпуски отменены.", ephemeral=True)


class VacationExtendModal(discord.ui.Modal, title="Продление отпуска"):
    extra_days = discord.ui.TextInput(
        label="Дополнительные дни",
        placeholder="3",
        required=True,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            extra = int(self.extra_days.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Количество дней должно быть числом.", ephemeral=True
            )
            return
        if extra <= 0:
            await interaction.response.send_message(
                "❌ Количество дней должно быть больше нуля.", ephemeral=True
            )
            return

        vacations = load_vacations()
        user_id_str = str(interaction.user.id)
        if user_id_str not in vacations:
            await interaction.response.send_message(
                "❌ У вас нет активного отпуска.", ephemeral=True
            )
            return

        v = vacations[user_id_str]
        periods = v.get("periods", [])
        now = datetime.now()

        target = None
        for p in periods:
            try:
                end = datetime.strptime(p["end_date"], "%d.%m.%Y")
                if end >= now:
                    target = p
                    break
            except (KeyError, ValueError):
                continue

        if not target:
            await interaction.response.send_message(
                "❌ У вас нет текущего отпуска для продления.", ephemeral=True
            )
            return

        old_end = datetime.strptime(target["end_date"], "%d.%m.%Y")
        new_end = old_end + timedelta(days=extra)
        target["end_date"] = new_end.strftime("%d.%m.%Y")
        save_vacations(vacations)

        await interaction.response.send_message(
            f"✅ Отпуск продлён на **{extra}** дн.\n"
            f"📅 Новая дата окончания: **{new_end.strftime('%d.%m.%Y')}**",
            ephemeral=True,
        )

        await send_vacation_log(
            interaction.client,
            "🔄 Отпуск продлён",
            f"**Пользователь:** {interaction.user.mention}\n"
            f"**Продление:** {extra} дн.\n"
            f"**Новая дата окончания:** {new_end.strftime('%d.%m.%Y')}",
        )

        await update_vacation_panel(interaction.client)


class RequestPanelView(discord.ui.View):
    VACATION_ROLE = 1459877837388513494

    def __init__(self):
        super().__init__(timeout=None)

    def _has_vacation_role(self, member: discord.Member) -> bool:
        return any(r.id == self.VACATION_ROLE for r in member.roles)

    @discord.ui.button(
        label="📝 Взять отпуск",
        style=discord.ButtonStyle.green,
        custom_id="vacation_request_btn",
    )
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._has_vacation_role(interaction.user):
            await interaction.response.send_message(
                "❌ У вас нет роли для подачи заявок на отпуск.", ephemeral=True
            )
            return
        await interaction.response.send_modal(VacationModal())

    @discord.ui.button(
        label="📋 Статус",
        style=discord.ButtonStyle.blurple,
        custom_id="vacation_my_status",
    )
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._has_vacation_role(interaction.user):
            await interaction.response.send_message(
                "❌ У вас нет роли для просмотра статуса.", ephemeral=True
            )
            return
        vacations = load_vacations()
        user_id_str = str(interaction.user.id)
        if user_id_str not in vacations:
            await interaction.response.send_message("❌ У вас нет отпусков.", ephemeral=True)
            return
        v = vacations[user_id_str]
        embed = discord.Embed(title="🏖️ Ваши отпуска", color=discord.Color.blue())
        for i, p in enumerate(v.get("periods", []), 1):
            embed.add_field(
                name=f"Период {i}",
                value=f"📅 {p['start_date']} — {p['end_date']}\n📝 {p['reason']}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="🔄 Продлить отпуск",
        style=discord.ButtonStyle.success,
        custom_id="vacation_extend_btn",
    )
    async def extend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._has_vacation_role(interaction.user):
            await interaction.response.send_message(
                "❌ У вас нет роли для продления отпуска.", ephemeral=True
            )
            return
        await interaction.response.send_modal(VacationExtendModal())

    @discord.ui.button(
        label="❌ Снять отпуск",
        style=discord.ButtonStyle.red,
        custom_id="vacation_cancel_btn",
    )
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._has_vacation_role(interaction.user):
            await interaction.response.send_message(
                "❌ У вас нет роли для отмены отпуска.", ephemeral=True
            )
            return
        vacations = load_vacations()
        user_id_str = str(interaction.user.id)
        if user_id_str not in vacations:
            await interaction.response.send_message("❌ У вас нет отпусков.", ephemeral=True)
            return

        count = len(vacations[user_id_str].get("periods", []))
        del vacations[user_id_str]
        save_vacations(vacations)

        role = interaction.guild.get_role(VACATION_ROLE_ID)
        if role:
            await interaction.user.remove_roles(role, reason="Отпуск снят")

        await interaction.response.send_message(
            f"✅ Снято {count} период(ов) отпуска.", ephemeral=True
        )

        await send_vacation_log(
            interaction.client,
            "❌ Отпуск снят",
            f"**Пользователь:** {interaction.user.mention} снял {count} период(ов) отпуска.",
        )

        await update_vacation_panel(interaction.client)


class VacationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.vacation_return_check.start()

    @app_commands.command(
        name="vacation_panel",
        description="Отправить панель отпусков",
    )
    @app_commands.default_permissions(administrator=True)
    async def vacation_panel(self, interaction: discord.Interaction):
        info_embed = build_info_panel_embed(load_vacations())
        await interaction.response.send_message(embed=info_embed)

        info_msg = await interaction.original_response()

        request_embed = build_request_panel_embed()
        request_view = RequestPanelView()
        request_msg = await interaction.followup.send(embed=request_embed, view=request_view)

        vacations = load_vacations()
        vacations["__panel__"] = {
            "channel_id": interaction.channel.id,
            "info_message_id": info_msg.id,
            "request_message_id": request_msg.id,
        }
        save_vacations(vacations)

    @app_commands.command(
        name="vacation_list",
        description="Показать все отпуска",
    )
    @app_commands.default_permissions(administrator=True)
    async def vacation_list(self, interaction: discord.Interaction):
        vacations = load_vacations()
        real_vacations = {
            k: v for k, v in vacations.items() if k != "__panel__" and isinstance(v, dict)
        }

        if not real_vacations:
            await interaction.response.send_message("📋 Отпусков нет.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📋 Все отпуска",
            color=discord.Color.blue(),
        )

        for user_id_str, v in real_vacations.items():
            name = v.get("user_name", f"ID: {user_id_str}")
            periods = v.get("periods", [])
            lines = []
            for p in periods:
                lines.append(f"📅 {p.get('start_date', '—')} — {p.get('end_date', '—')}\n📝 {p.get('reason', '—')}")
            embed.add_field(
                name=name,
                value="\n\n".join(lines) if lines else "Нет периодов",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="vacation_remove",
        description="Снять отпуск у участника",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user="Участник, у которого снять отпуск")
    async def vacation_remove(self, interaction: discord.Interaction, user: discord.Member):
        vacations = load_vacations()
        user_id_str = str(user.id)

        if user_id_str not in vacations:
            await interaction.response.send_message(
                f"❌ У {user.mention} нет отпусков.", ephemeral=True
            )
            return

        v = vacations[user_id_str]
        periods = v.get("periods", [])
        count = len(periods)
        del vacations[user_id_str]
        save_vacations(vacations)

        role = interaction.guild.get_role(VACATION_ROLE_ID)
        if role and role in user.roles:
            await user.remove_roles(role, reason="Отпуск снят администратором")

        await interaction.response.send_message(
            f"✅ Все отпуски ({count} период(ов)) у {user.mention} сняты.",
            ephemeral=True,
        )

        await send_vacation_log(
            interaction.client,
            "🗑️ Отпуск снят (вручную)",
            f"**Пользователь:** {user.mention}\n"
            f"**Снял:** {interaction.user.mention}\n"
            f"**Количество периодов:** {count}",
            color=discord.Color.red(),
        )

        await update_vacation_panel(self.bot)

    @tasks.loop(minutes=1)
    async def vacation_return_check(self):
        now = datetime.now()

        if now.hour != 10 or now.minute > 2:
            return

        global VACATION_RETURN_NOTIFIED
        vacations = load_vacations()

        for user_id_str, v in vacations.items():
            if user_id_str == "__panel__":
                continue
            if not isinstance(v, dict):
                continue

            user_name = v.get("user_name", f"<@{user_id_str}>")
            for p in v.get("periods", []):
                try:
                    end_date = datetime.strptime(p["end_date"], "%d.%m.%Y")
                except (KeyError, ValueError):
                    continue

                days_overdue = (now.date() - end_date.date()).days
                key = f"{user_id_str}_{p['end_date']}"

                if days_overdue >= 5 and key not in VACATION_RETURN_NOTIFIED:
                    channel = self.bot.get_channel(config.VACATION_RETURN_CHANNEL)
                    if channel:
                        try:
                            await channel.send(
                                f"<@&{PING_ROLE_1}> <@&{PING_ROLE_2}>\n"
                                f"⚠️ **{user_name}** — "
                                f"отпуск истёк **{days_overdue}** дн. назад "
                                f"(дата окончания: {p['end_date']})."
                            )
                            VACATION_RETURN_NOTIFIED.add(key)
                        except Exception:
                            pass

    @vacation_return_check.before_loop
    async def before_vacation_return_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(VacationCog(bot))
