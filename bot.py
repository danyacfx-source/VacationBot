"""Точка входа VacationBot.

Порядок старта: логирование -> БД -> миграция старых данных -> коги ->
планировщик/HTTP -> вход в Discord -> синхронизация команд.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import sys
import time

_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)
os.chdir(_BOT_DIR)

import discord
from discord import app_commands

import config
from core import errors as core_errors
from core.app import VacationBot
from core.log import install_discord_handler, setup_logging
from db import Database, init_schema
from db.migrate import migrate_legacy
from services.http import http
from services.notify import send_log, send_startup_log, send_vacation_log
from services.vacation import refresh_panels

setup_logging()
log = logging.getLogger("bot")

BOT_STATE_FILE = "bot_state.json"
# Путь относительный: config.DATA_DIR меняет cwd — данные должны ехать за ним.
DB_PATH = "bot_data.db"

COGS = [
    "cogs.tickets",
    "cogs.clan_tickets",
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
    "cogs.welcome",
    "cogs.direction_roles",
    "handlers",
]


# --------------------------------------------------------------------- состояние


def _load_bot_state() -> dict | None:
    try:
        with open(BOT_STATE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_bot_state(graceful: bool) -> None:
    data = {
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "graceful": bool(graceful),
    }
    try:
        with open(BOT_STATE_FILE, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
    except Exception as exc:
        log.error("Не удалось сохранить состояние бота: %s", exc)


def _log_tail(lines: int = 30) -> str:
    try:
        with open("bot.log", "r", encoding="utf-8", errors="replace") as handle:
            return "".join(handle.readlines()[-lines:])
    except Exception:
        return ""


async def _notify_abnormal_restart(bot: VacationBot) -> None:
    try:
        tail = _log_tail()
        description = (
            "Бот перезапущен после нештатной остановки (сбой/принудительное завершение).\n"
        )
        if tail:
            description += f"```\n{tail[-1800:]}\n```"
        await send_log(bot, "⚠️ Бот перезапущен после сбоя", description)
    except Exception as exc:
        log.error("Ошибка уведомления о перезапуске: %s", exc)


# --------------------------------------------------------------------- команды


@app_commands.command(name="ping", description="Проверка, что бот работает")
async def ping_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Pong!")


@app_commands.context_menu(name="Снять отпуск")
@app_commands.default_permissions(administrator=True)
async def context_remove_vacation(interaction: discord.Interaction, user: discord.Member) -> None:
    bot: VacationBot = interaction.client  # type: ignore[assignment]

    entry = await bot.vacations.get_user(user.id)
    if not entry:
        await interaction.response.send_message(
            f"❌ У {user.mention} нет активного отпуска.", ephemeral=True
        )
        return

    periods = entry.get("periods") or []
    period_lines = [
        f"📅 {p.get('start_date', '—')} — {p.get('end_date', '—')}\n"
        f"📝 {p.get('reason') or '—'}"
        for p in periods
    ]
    vacation_info = "\n\n".join(period_lines) or "—"
    reasons = "; ".join(str(p.get("reason") or "") for p in periods if p.get("reason")) or "—"
    dates = "; ".join(
        f"{p.get('start_date', '—')} — {p.get('end_date', '—')}" for p in periods
    ) or "—"

    removed = await bot.vacations.remove_user(user.id)
    if not removed:
        await interaction.response.send_message(
            f"❌ Не удалось снять отпуск у {user.mention}.", ephemeral=True
        )
        return

    role = interaction.guild.get_role(config.VACATION_ROLE_ID) if interaction.guild else None
    if role and role in user.roles:
        try:
            await user.remove_roles(role, reason="Отпуск снят администратором")
        except discord.HTTPException as exc:
            log.warning("Не удалось снять роль отпуска у %s: %s", user.id, exc)

    await interaction.response.send_message(
        f"✅ Отпуск у {user.mention} снят.\n{vacation_info}",
        ephemeral=True,
    )

    await send_vacation_log(
        bot,
        "🗑️ Отпуск снят (контекстное меню)",
        f"**Пользователь:** {user.mention}\n"
        f"**Снял:** {interaction.user.mention}\n"
        f"**Причина отпуска:** {reasons}\n"
        f"**Даты:** {dates}",
        color=discord.Color.red(),
    )

    await refresh_panels(bot)


# --------------------------------------------------------------------- сборка бота


def build_bot(db: Database) -> VacationBot:
    bot = VacationBot(db=db)

    bot.tree.add_command(ping_cmd)
    bot.tree.add_command(context_remove_vacation)

    core_errors.install(bot)
    install_discord_handler(
        lambda text: send_log(bot, "⚠️ Ошибки бота", text)
    )

    @bot.event
    async def on_disconnect() -> None:
        log.warning("Бот отключён от Discord")

    @bot.event
    async def on_resumed() -> None:
        log.info("Бот переподключён к Discord")

    @bot.event
    async def on_ready() -> None:
        log.info("Бот запущен: %s", bot.user)
        if bot._ready_done:
            log.info("Повторный on_ready (реконнект) — пропускаю инициализацию")
            return
        bot._ready_done = True
        bot.launch_time = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        state = _load_bot_state()
        abnormal = state is not None and not state.get("graceful", False)
        _save_bot_state(False)
        if abnormal:
            await _notify_abnormal_restart(bot)

        if bot._load_errors:
            try:
                error_text = "\n".join(f"**{ext}:** {err}" for ext, err in bot._load_errors)
                await send_log(bot, "⚠️ Ошибки загрузки расширений", error_text[:1900])
            except Exception as exc:
                log.error("Не удалось сообщить об ошибках загрузки: %s", exc)
            bot._load_errors.clear()

        # Шаги независимы: сбой одного не должен убить остальные.
        await _guard(bot, "планировщик и HTTP", _start_services(bot))
        synced = await _guard(bot, "синхронизация команд", _sync_commands(bot)) or []
        await _guard(bot, "глобальный /ping", _ensure_global_ping(bot))
        await _guard(
            bot,
            "лог запуска",
            send_startup_log(
                bot,
                "✅ Бот запущен",
                f"**{bot.user}** подключён\n"
                f"Синхронизировано команд: **{len(synced)}**\n"
                + "\n".join(f"`/{c.name}` — {c.description}" for c in synced),
            ),
        )
        await _guard(bot, "API-сервер", _start_api(bot))

    return bot


async def _guard(bot: VacationBot, label: str, coro) -> object | None:
    """Ловит сбой шага: логирует, докладывает в канал и не роняет on_ready."""
    try:
        return await coro
    except Exception as exc:
        log.error("Ошибка шага «%s»: %s", label, exc, exc_info=True)
        try:
            await send_log(bot, "❌ Ошибка запуска", f"**{label}**\n```{exc}```")
        except Exception:
            pass
        return None


async def _with_retries(label: str, factory, attempts: int = 3):
    """Повторяет корутину с растущей паузой — сетевые сбои не фатальны."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except Exception as exc:
            last = exc
            log.error("%s: попытка %d/%d не удалась: %s", label, attempt, attempts, exc)
            if attempt < attempts:
                await asyncio.sleep(3 * attempt)
    assert last is not None
    raise last


async def _start_services(bot: VacationBot) -> None:
    await _with_retries("Планировщик", lambda: bot.scheduler.start())
    await _with_retries("HTTP-клиент", lambda: http.start())


async def _sync_commands(bot: VacationBot):
    async def do_sync():
        if config.GUILD_ID:
            bot.tree.copy_global_to(guild=config.GUILD_ID)
            return await bot.tree.sync(guild=config.GUILD_ID)
        return await bot.tree.sync()

    synced = await _with_retries("Синхронизация команд", do_sync)
    log.info("Синхронизировано %d команд", len(synced))
    for command in synced:
        log.info("  /%s — %s", command.name, command.description)
    return synced


async def _start_api(bot: VacationBot) -> None:
    from api_server import start_api

    await start_api(bot)
    log.info("API сервер запущен на порту %s", config.API_PORT)


async def _register_persistent_views(bot: VacationBot) -> None:
    """Регистрирует все persistent view (дедуп — по custom_id)."""
    try:
        from cogs.clan_tickets import (
            ClanTicketClosedView,
            ClanTicketCloseView,
            ClanTicketPanelView,
        )
        from cogs.events import EventRSVPSelectView
        from cogs.roles import RolePanelView
        from cogs.temp_voice import TempChannelView
        from cogs.tickets import (
            ArmaPanelView,
            PromotionPanelView,
            TicketCloseView,
            TicketClosedView,
            TicketCreateView,
        )
        from cogs.vacations import LegacyVacationPanelView, RequestPanelView
    except Exception as exc:
        log.error("Не удалось импортировать view: %s", exc, exc_info=True)
        return

    bot.add_persistent_views(
        [
            RequestPanelView(),
            LegacyVacationPanelView(),
            ClanTicketPanelView(),
            ClanTicketCloseView(),
            ClanTicketClosedView(),
            TicketCreateView(),
            TicketCloseView(),
            PromotionPanelView(),
            ArmaPanelView(),
            RolePanelView(),
            TempChannelView(),
            EventRSVPSelectView(),
            TicketClosedView(),
        ]
    )


async def _ensure_global_ping(bot: VacationBot) -> None:
    """Глобальный /ping — для бейджа «Supports Commands»."""
    try:
        from discord.http import Route

        app_id = bot.application_id or (bot.user.id if bot.user else None)
        if not app_id:
            return
        get_route = Route("GET", "/applications/{application_id}/commands", application_id=app_id)
        existing = await bot.http.request(get_route)
        if any(cmd.get("name") == "ping" for cmd in existing):
            return
        put_route = Route("PUT", "/applications/{application_id}/commands", application_id=app_id)
        await bot.http.request(
            put_route,
            json=existing
            + [{"name": "ping", "description": "Проверка, что бот работает", "type": 1}],
        )
        log.info("Зарегистрирован глобальный /ping")
    except Exception as exc:
        log.error("Не удалось зарегистрировать глобальный /ping: %s", exc)


# --------------------------------------------------------------------- запуск


async def _bootstrap(bot: VacationBot) -> None:
    db = bot.db
    db.connect()
    await init_schema(db)
    migrated = await migrate_legacy(db)
    if migrated:
        log.info("Миграция старых данных: %d записей", migrated)
    log.info("База данных готова: %s", DB_PATH)

    try:
        async with bot:
            bot._load_errors = []
            for extension in COGS:
                try:
                    await bot.load_extension(extension)
                    log.info("Загружен: %s", extension)
                except Exception as exc:
                    log.error("Ошибка загрузки %s: %s", extension, exc, exc_info=True)
                    bot._load_errors.append((extension, str(exc)))

            await _register_persistent_views(bot)

            if not config.TOKEN:
                log.error("DISCORD_BOT_TOKEN не найден в .env")
                raise SystemExit(1)

            await bot.start(config.TOKEN)
            # start() вернулся — сессия закрылась штатно (рестарт по API).
            # Флаг ставим только здесь: исключение ниже не должно
            # выглядеть как «честная остановка».
            _save_bot_state(True)
    finally:
        # Чистим ресурсы при любом выходе — иначе следующая попытка
        # упёртся в открытую сессию/заблокированную БД.
        await _cleanup(bot)

    if bot._shutdown_requested:
        log.info("Остановка по запросу API")
        os._exit(0)


async def _cleanup(bot: VacationBot) -> None:
    for label, awaitable in (
        ("планировщик", bot.scheduler.stop()),
        ("HTTP-клиент", http.close()),
    ):
        try:
            await awaitable
        except Exception as exc:
            log.error("Ошибка остановки (%s): %s", label, exc)
    try:
        bot.db.close()
    except Exception as exc:
        log.error("Ошибка закрытия БД: %s", exc)


def main() -> None:
    """Крутит бота до победного: сбой -> пауза с бэкоффом -> новая попытка.

    Внешнего супервизора больше нет, поэтому процесс не умирает
    из-за транзиентной ошибки — он пересобирается сам.
    """
    delay = 5
    failures = 0

    while True:
        had_error = False
        try:
            asyncio.run(_bootstrap(build_bot(Database(DB_PATH))))
        except KeyboardInterrupt:
            _save_bot_state(True)
            break
        except SystemExit:
            raise
        except Exception as exc:
            had_error = True
            failures += 1
            log.error("Сбой запуска №%d: %s", failures, exc, exc_info=True)

        if had_error:
            log.info("Перезапуск через %d с (сбоев подряд: %d)", delay, failures)
            time.sleep(delay)
            delay = min(delay * 2, 60)
        else:
            failures = 0
            delay = 5


def _handle_exception(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    log.error("Необработанное исключение:", exc_info=(exc_type, exc_value, exc_tb))


sys.excepthook = _handle_exception


if __name__ == "__main__":
    main()
