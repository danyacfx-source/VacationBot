"""Ежедневный утренний пост: погода + курсы валют.

Одна функция вместо двух копий кода (`daily_morning` и `test_morning`).
"""

from __future__ import annotations

import logging

import discord

import config
from core.timeutil import msk_now
from services.weather import fetch_currency, fetch_weather
from ui import style

log = logging.getLogger(__name__)


async def build_morning_embed() -> discord.Embed:
    now = msk_now()
    weather = await fetch_weather()
    currency = await fetch_currency()

    weather_lines: list[str] = []
    for city in config.DAILY_CITIES.values():
        data = weather.get(city)
        if data:
            weather_lines.append(
                f"**{city}** — {data['desc']}, {data['temp']}°C "
                f"(ощущается {data['feels']}°C)\n"
                f"💨 Ветер: {data['wind']} км/ч | 💧 Влажность: {data['humidity']}%"
            )
        else:
            weather_lines.append(f"**{city}** — недоступно")

    currency_lines = [f"{label}: **{rate} ₽**" for label, rate in currency.items()]

    embed = discord.Embed(
        title=f"☀️ Доброе утро! {now.strftime('%d.%m.%Y')}",
        color=style.ACCENT,
    )
    embed.add_field(name="🌡️ Погода", value="\n\n".join(weather_lines) or "—", inline=False)
    embed.add_field(
        name="💱 Курс валют (ЦБ)",
        value="\n".join(currency_lines) or "Не удалось загрузить",
        inline=False,
    )
    embed.set_footer(text=style.FOOTER_DEFAULT)
    embed.timestamp = now
    return embed


async def send_morning(bot) -> bool:
    """Публикует утренний пост. Возвращает True, если отправлено."""
    channel = bot.channel_of(config.DAILY_CHANNEL)
    if channel is None:
        log.warning("Канал утреннего поста не найден")
        return False
    embed = await build_morning_embed()
    await channel.send(embed=embed)
    return True


__all__ = ["build_morning_embed", "send_morning"]
