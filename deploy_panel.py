import asyncio
import discord
from dotenv import load_dotenv
import os
import json

load_dotenv(override=True)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = 1484548234230894722

VACATION_ROLE = 1459877837388513494


def load_vacations():
    if os.path.exists("vacations.json"):
        with open("vacations.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        data.pop("__panel__", None)
        return data
    return {}


def build_info_embed(data):
    embed = discord.Embed(
        title="Система отпусков | Информация",
        color=discord.Color.orange(),
    )
    entries = []
    for uid, v in data.items():
        if uid == "__panel__" or not isinstance(v, dict):
            continue
        periods = v.get("periods", [])
        if not periods:
            continue
        lines = [f"<@{uid}>"]
        for p in periods:
            start_d = p.get("start_date", "")
            end_d = p.get("end_date", "")
            reason = p.get("reason", "")
            if start_d:
                lines.append(f"от {start_d} до {end_d}")
            else:
                lines.append(f"до {end_d}")
            if reason:
                lines.append(reason)
        entries.append("\n".join(lines))
    embed.description = "\n\n".join(entries) if entries else "Нет активных отпусков"
    embed.set_footer(text="Сделано с ❤️ от Денди")
    return embed


def build_request_embed():
    embed = discord.Embed(
        title="Система отпусков | Панель",
        description=(
            "Нажмите кнопку ниже, чтобы подать заявку на отпуск.\n\n"
            "🔹 **Взять отпуск** — подать заявку\n"
            "🔹 **Мои отпуска** — посмотреть свои отпуска\n"
            "🔹 **Отменить отпуск** — отменить текущий отпуск"
        ),
        color=discord.Color.blurple(),
    )
    return embed


class RequestPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Взять отпуск", style=discord.ButtonStyle.green, custom_id="vacation_request_btn")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VacationModal())

    @discord.ui.button(label="📋 Мои отпуска", style=discord.ButtonStyle.blurple, custom_id="vacation_my_status")
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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

    @discord.ui.button(label="❌ Отменить отпуск", style=discord.ButtonStyle.red, custom_id="vacation_cancel_btn")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Функция отмены временно недоступна.", ephemeral=True)


class VacationModal(discord.ui.Modal, title="Заявка на отпуск"):
    start_date = discord.ui.TextInput(label="Дата начала (ДД.ММ.ГГГГ)", placeholder="25.07.2026", required=True, max_length=10)
    end_date = discord.ui.TextInput(label="Дата окончания (ДД.ММ.ГГГГ)", placeholder="10.08.2026", required=True, max_length=10)
    reason = discord.ui.TextInput(label="Причина", placeholder="Укажите причину отпуска", style=discord.TextStyle.paragraph, required=True, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        from datetime import datetime, timedelta
        try:
            start = datetime.strptime(self.start_date.value.strip(), "%d.%m.%Y")
        except ValueError:
            await interaction.response.send_message("❌ Неверный формат даты начала.", ephemeral=True)
            return
        try:
            end = datetime.strptime(self.end_date.value.strip(), "%d.%m.%Y")
        except ValueError:
            await interaction.response.send_message("❌ Неверный формат даты окончания.", ephemeral=True)
            return
        if end < start:
            await interaction.response.send_message("❌ Дата окончания не может быть раньше даты начала.", ephemeral=True)
            return
        reason = self.reason.value.strip()
        vacations = load_vacations()
        user_id_str = str(interaction.user.id)
        if user_id_str not in vacations:
            vacations[user_id_str] = {"user_name": str(interaction.user), "periods": []}
        vacations[user_id_str]["user_name"] = str(interaction.user)
        vacations[user_id_str]["periods"].append({
            "start_date": start.strftime("%d.%m.%Y"),
            "end_date": end.strftime("%d.%m.%Y"),
            "reason": reason,
        })
        with open("vacations.json", "w", encoding="utf-8") as f:
            raw = {}
            if os.path.exists("vacations.json"):
                with open("vacations.json", "r", encoding="utf-8") as rf:
                    raw = json.load(rf)
            panel = raw.get("__panel__")
            raw = {k: v for k, v in vacations.items() if k != "__panel__"}
            if panel:
                raw["__panel__"] = panel
            json.dump(raw, f, ensure_ascii=False, indent=4)

        role = interaction.guild.get_role(1479161484897423433)
        if role:
            await interaction.user.add_roles(role)
        days = (end - start).days + 1
        await interaction.response.send_message(
            f"✅ Ваш отпуск одобрен!\n📅 С **{start.strftime('%d.%m.%Y')}** по **{end.strftime('%d.%m.%Y')}** ({days} дн.)",
            ephemeral=True,
        )


async def main():
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            print(f"Channel {CHANNEL_ID} not found!")
            await client.close()
            return

        print(f"Channel: {channel.name}")

        info_embed = build_info_embed(load_vacations())
        info_msg = await channel.send(embed=info_embed)
        print(f"Info panel sent: {info_msg.id}")

        request_embed = build_request_embed()
        view = RequestPanelView()
        request_msg = await channel.send(embed=request_embed, view=view)
        print(f"Request panel sent: {request_msg.id}")

        panel_data = {
            "channel_id": CHANNEL_ID,
            "info_message_id": info_msg.id,
            "request_message_id": request_msg.id,
        }
        raw = {}
        if os.path.exists("vacations.json"):
            with open("vacations.json", "r", encoding="utf-8") as f:
                raw = json.load(f)
        raw["__panel__"] = panel_data
        with open("vacations.json", "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=4)
        print("Panel data saved to vacations.json")

        await client.close()

    await client.start(TOKEN)

asyncio.run(main())
