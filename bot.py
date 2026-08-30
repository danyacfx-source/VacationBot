import asyncio
import datetime
import json
import logging
import os
import sys

import psutil


_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(_BOT_DIR)
sys.path.insert(0, _BOT_DIR)

import discord
from discord import app_commands
from discord.ext import commands
import config
from helpers import send_log, send_startup_log, send_vacation_log, load_vacations, save_vacations, update_vacation_panel
from database import init_db, migrate_json_to_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Прокси для соединения с Discord (если задан в конфиге), передаётся в session discord.py.
_proxy_url = getattr(config, "PROXY_URL", "") or ""
if _proxy_url.lower() in ("", "none", "system", "off", "0"):
    _proxy_url = ""

_bot_options = {}
if _proxy_url:
    _bot_options["proxy"] = _proxy_url

bot = commands.Bot(command_prefix="!", intents=config.intents, reconnect=True, max_messages=None,
                   **_bot_options)

@app_commands.command(name="ping", description="Проверка, что бот работает")
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


bot.tree.add_command(ping_cmd)


class DiscordLogHandler(logging.Handler):
    def __init__(self, bot):
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self._pending = []
        self._flush_task = None
        self.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            if record.name.startswith("discord"):
                return
            self._pending.append(self.format(record))
            self.bot.loop.call_soon_threadsafe(self._schedule_flush)
        except Exception:
            pass

    def _schedule_flush(self):
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush())

    async def _flush(self):
        try:
            await asyncio.sleep(5)
            pending, self._pending = self._pending, []
            if not pending:
                return
            text = "\n".join(pending)
            if len(text) > 1900:
                text = text[-1900:]
            await send_log(self.bot, title="⚠️ Ошибки бота", description=f"```\n{text}\n```")
        except Exception:
            pass


logging.getLogger().addHandler(DiscordLogHandler(bot))

VACATION_ROLE_ID = 1479161484897423433

BOT_STATE_FILE = "bot_state.json"


def _load_bot_state():
    try:
        with open(BOT_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_bot_state(graceful: bool):
    data = {
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "graceful": bool(graceful),
    }
    try:
        with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logging.error("Не удалось сохранить состояние бота: %s", e)


async def _notify_abnormal_restart(bot):
    try:
        tail = ""
        try:
            with open("bot.log", "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                tail = "".join(lines[-30:])
        except Exception:
            pass
        desc = (
            "Бот перезапущен после нештатной остановки "
            "(сбой/принудительное завершение/вотчер).\n"
        )
        if tail:
            desc += f"```\n{tail[-1800:]}\n```"
        await send_log(bot, "⚠️ Бот перезапущен после сбоя", desc)
    except Exception as e:
        logging.error("Ошибка уведомления о перезапуске: %s", e)


async def _watchdog_monitor(bot):
    await asyncio.sleep(60)
    alerted = False
    while True:
        try:
            alive = False
            for p in psutil.process_iter(["name", "cmdline"]):
                try:
                    name = (p.info["name"] or "").lower()
                    if name in ("wscript.exe", "cscript.exe"):
                        cmd = " ".join(p.info["cmdline"] or []).lower()
                        if "watchdog.vbs" in cmd:
                            alive = True
                            break
                except Exception:
                    continue
            if not alive and not alerted:
                alerted = True
                await send_log(
                    bot,
                    "🚨 Вотчер не запущен!",
                    "Процесс watchdog.vbs не обнаружен. "
                    "Если бот упадёт, его никто не перезапустит. "
                    "Запустите watchdog.vbs вручную.",
                    color=discord.Color.orange(),
                )
            elif alive:
                alerted = False
        except Exception as e:
            logging.error("Ошибка проверки вотчера: %s", e)
        await asyncio.sleep(300)


@app_commands.context_menu(name="Снять отпуск")
@app_commands.default_permissions(administrator=True)
async def context_remove_vacation(interaction: discord.Interaction, user: discord.Member):
    vacations = load_vacations()
    user_id_str = str(user.id)

    if user_id_str not in vacations:
        await interaction.response.send_message(
            f"❌ У {user.mention} нет активного отпуска.", ephemeral=True
        )
        return

    v = vacations[user_id_str]
    periods = v.get("periods", [])
    period_lines = []
    for p in periods:
        period_lines.append(
            f"📅 {p.get('start_date', '—')} — {p.get('end_date', '—')}\n"
            f"📝 {p.get('reason', '—')}"
        )
    vacation_info = "\n\n".join(period_lines) if period_lines else (
        f"**Причина:** {v.get('reason', '—')}\n"
        f"**Даты:** {v.get('start_date', '—')} — {v.get('end_date', '—')}"
    )

    del vacations[user_id_str]
    save_vacations(vacations)

    role = interaction.guild.get_role(VACATION_ROLE_ID)
    if role and role in user.roles:
        await user.remove_roles(role, reason="Отпуск снят администратором")

    await interaction.response.send_message(
        f"✅ Отпуск у {user.mention} снят.\n"
        f"{vacation_info}",
        ephemeral=True
    )

    await send_vacation_log(
        interaction.client,
        "🗑️ Отпуск снят (контекстное меню)",
        f"**Пользователь:** {user.mention}\n"
        f"**Снял:** {interaction.user.mention}\n"
        f"**Причина отпуска:** {vacation_reason}\n"
        f"**Даты:** {vacation_dates}",
        color=discord.Color.red(),
    )

    await update_vacation_panel(interaction.client)


bot.tree.add_command(context_remove_vacation)

COGS = [
    "cogs.tickets",
    "cogs.vacations",
    "cogs.events",
    "cogs.music",
    "cogs.misc",
    "cogs.embeds",
    "cogs.temp_voice",
    "cogs.voice_cleanup",
    "cogs.roles",
    "cogs.fun",
    "cogs.stats",
    "cogs.moderation",
    "handlers",
]


@bot.event
async def on_disconnect():
    logging.warning("Бот отключён от Discord")


@bot.event
async def on_resumed():
    logging.info("Бот переподключён к Discord")


@bot.event
async def on_ready():
    logging.info("Бот запущен: %s", bot.user)

    if getattr(bot, "_ready_done", False):
        logging.info("Повторный on_ready (реконнект) — пропускаю инициализацию")
        return
    bot._ready_done = True

    state = _load_bot_state()
    abnormal = state is not None and not state.get("graceful", False)
    _save_bot_state(False)
    if abnormal:
        await _notify_abnormal_restart(bot)

    if not hasattr(bot, "_watchdog_task"):
        bot._watchdog_task = asyncio.create_task(_watchdog_monitor(bot))

    try:
        if os.path.exists("bot.paused"):
            os.remove("bot.paused")
            logging.info("Бот запущен вручную, маркер bot.paused снят")
    except Exception as e:
        logging.error("Ошибка удаления bot.paused: %s", e)

    load_errors = getattr(bot, '_load_errors', [])
    if load_errors:
        error_text = "\n".join(f"**{ext}:** {err}" for ext, err in load_errors)
        await send_log(bot, "⚠️ Ошибки загрузки расширений", error_text[:1900])
        load_errors.clear()

    try:
        # Init database
        init_db()
        migrate_json_to_db()
        logging.info("База данных инициализирована")
        # Register persistent views
        from cogs.tickets import (TicketCreateView, TicketCloseView,
                                   PromotionPanelView, ArmaPanelView, TicketClosedView)
        from cogs.vacations import RequestPanelView, LegacyVacationPanelView
        from cogs.roles import RolePanelView
        from cogs.temp_voice import TempChannelView
        from cogs.events import EventRSVPView

        bot.add_view(RequestPanelView())
        bot.add_view(LegacyVacationPanelView())
        bot.add_view(TicketCreateView())
        bot.add_view(TicketCloseView())
        bot.add_view(PromotionPanelView())
        bot.add_view(ArmaPanelView())
        bot.add_view(RolePanelView())
        bot.add_view(TempChannelView())
        bot.add_view(EventRSVPView("0"))
        bot.add_view(TicketClosedView())

        # Sync commands
        if config.GUILD_ID:
            bot.tree.copy_global_to(guild=config.GUILD_ID)
            synced = await bot.tree.sync(guild=config.GUILD_ID)
        else:
            synced = await bot.tree.sync()

        # Register global /ping to enable the "Supports Commands" badge
        try:
            from discord.http import Route
            app_id = bot.application_id or bot.user.id
            get_route = Route("GET", "/applications/{application_id}/commands", application_id=app_id)
            existing = await bot.http.request(get_route)
            if not any(cmd.get("name") == "ping" for cmd in existing):
                put_route = Route("PUT", "/applications/{application_id}/commands", application_id=app_id)
                await bot.http.request(put_route, json=existing + [{
                    "name": "ping",
                    "description": "Проверка, что бот работает",
                    "type": 1,
                }])
                logging.info("Registered global /ping for the 'Supports Commands' badge")
        except Exception as e:
            logging.error("Failed to register global /ping: %s", e)

        logging.info("Синхронизировано %d команд", len(synced))
        for cmd in synced:
            logging.info("  /%s — %s", cmd.name, cmd.description)

        await send_startup_log(
            bot,
            "✅ Бот запущен",
            f"**{bot.user}** подключён\n"
            f"Синхронизировано команд: **{len(synced)}**\n"
            + "\n".join(f"`/{c.name}` — {c.description}" for c in synced)
        )

        # Start API server
        try:
            from api_server import start_api
            await start_api(bot)
            logging.info("API сервер запущен на порту %s", config.API_PORT)
        except Exception as e:
            logging.error("Ошибка запуска API: %s", e)

        bot.launch_time = datetime.datetime.utcnow()

    except Exception as e:
        logging.error("Ошибка on_ready: %s", e, exc_info=True)
        await send_log(bot, "❌ Ошибка запуска", f"```{e}```")


async def main():
    async with bot:
        load_errors = []
        for ext in COGS:
            try:
                await bot.load_extension(ext)
                logging.info("Загружен: %s", ext)
            except Exception as e:
                logging.error("Ошибка загрузки %s: %s", ext, e, exc_info=True)
                load_errors.append((ext, str(e)))
        bot._load_errors = load_errors

        if not config.TOKEN:
            logging.error("DISCORD_BOT_TOKEN не найден в .env")
            raise SystemExit(1)

        await bot.start(config.TOKEN)
        _save_bot_state(True)
        if getattr(bot, "_shutdown_requested", False):
            logging.info("Остановка по запросу API")
            try:
                with open("bot.paused", "w", encoding="utf-8") as f:
                    f.write("stopped")
            except Exception as e:
                logging.error("Не удалось создать bot.paused: %s", e)
            os._exit(0)


def _handle_exception(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logging.error("Необработанное исключение:", exc_info=(exc_type, exc_value, exc_tb))


sys.excepthook = _handle_exception


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            _save_bot_state(True)
            break
        except Exception as e:
            logging.error("Критическая ошибка: %s", e, exc_info=True)
        # Повторное использование модульного bot после завершения asyncio.run ненадёжно:
        # event loop закрыт, коги уже загружены, aiohttp-сессия закрыта ("Session is closed").
        # Поэтому завершаем процесс, а вотчер поднимет бота заново с чистым состоянием.
        os._exit(1)
