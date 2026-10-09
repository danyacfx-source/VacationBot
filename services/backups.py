"""Ежедневный бэкап: SQLite + JSON в ZIP, отправка в Discord.

Архивация выполняется в отдельном потоке — event loop не замирает.
"""

from __future__ import annotations

import asyncio
import logging
import os
import zipfile
from datetime import date
from pathlib import Path

import discord

import config
from db import Database

log = logging.getLogger(__name__)


def _pack(zip_path: Path, db_backup: Path) -> list[str]:
    """Синхронная упаковка файлов (вызывается в executor'е)."""
    packed: list[str] = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if db_backup.exists():
            archive.write(db_backup, "bot_data.db")
            packed.append("bot_data.db")
        for filename in config.BACKUP_FILES:
            path = Path(filename)
            if path.exists():
                archive.write(path, filename)
                packed.append(filename)
    return packed


async def run_backup(db: Database) -> tuple[Path | None, list[str]]:
    """Создаёт ZIP-архив без отправки. Возвращает (путь, содержимое)."""
    return await _run_backup_inner(db, date.today().strftime("%d.%m.%Y"))


async def _run_backup_inner(db: Database, date_str: str) -> tuple[Path | None, list[str]]:
    zip_path = Path(f"backup_{date_str}.zip")
    db_backup = Path("bot_data_backup.db")

    loop = asyncio.get_running_loop()
    try:
        await db.backup(db_backup)
        packed = await loop.run_in_executor(None, _pack, zip_path, db_backup)
    except Exception as exc:
        log.error("Ошибка бэкапа: %s", exc, exc_info=True)
        return None, []

    for temp in (db_backup,):
        try:
            if temp.exists():
                os.remove(temp)
        except OSError:
            pass
    return zip_path, packed


async def send_backup(bot, db: Database) -> bool:
    """Полный цикл: собрать архив, отправить в канал, удалить файл."""
    channel = bot.channel_of(config.BACKUP_CHANNEL)
    if channel is None:
        log.warning("Канал бэкапов не найден")
        return False

    date_str = date.today().strftime("%d.%m.%Y")
    zip_path, packed = await _run_backup_inner(db, date_str)
    if zip_path is None:
        return False

    try:
        file = discord.File(str(zip_path), filename=zip_path.name)
        await channel.send(content=f"📦 Бэкап от {date_str}", file=file)
        log.info("Бэкап отправлен (%d файлов)", len(packed))
        return True
    except Exception as exc:
        log.error("Не удалось отправить бэкап: %s", exc)
        return False
    finally:
        try:
            if zip_path.exists():
                os.remove(zip_path)
        except OSError:
            pass


__all__ = ["send_backup", "run_backup"]
