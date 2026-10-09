"""Погода и курсы валют — полностью асинхронно."""

from __future__ import annotations

import logging
from typing import Any

import config
from services.http import http

log = logging.getLogger(__name__)

_WMO_DESC_RU = {
    0: "Ясно",
    1: "Преимущественно ясно",
    2: "Переменная облачность",
    3: "Пасмурно",
    45: "Туман",
    48: "Изморозь",
    51: "Лёгкая морось",
    53: "Морось",
    55: "Сильная морось",
    56: "Ледяная морось",
    57: "Сильная ледяная морось",
    61: "Лёгкий дождь",
    63: "Умеренный дождь",
    65: "Сильный дождь",
    66: "Ледяной дождь",
    67: "Сильный ледяной дождь",
    71: "Лёгкий снег",
    73: "Умеренный снег",
    75: "Сильный снег",
    77: "Снежная крупа",
    80: "Лёгкий ливень",
    81: "Умеренный ливень",
    82: "Сильный ливень",
    85: "Лёгкий снежный ливень",
    86: "Сильный снежный ливень",
    95: "Гроза",
    96: "Гроза с градом",
    99: "Сильная гроза с градом",
}

_coords_cache: dict[str, tuple[float, float]] = {}


async def _geocode(city: str) -> tuple[float, float] | None:
    cached = _coords_cache.get(city)
    if cached:
        return cached
    try:
        data = await http.get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
        )
        results = data.get("results") or []
        if not results:
            return None
        coords = (float(results[0]["latitude"]), float(results[0]["longitude"]))
        _coords_cache[city] = coords
        return coords
    except Exception as exc:
        log.warning("Геокодинг %s: %s", city, exc)
        return None


async def _from_openmeteo(city: str) -> dict[str, str] | None:
    coords = await _geocode(city)
    if coords is None:
        return None
    try:
        data = await http.get_json(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": coords[0],
                "longitude": coords[1],
                "current": (
                    "temperature_2m,relative_humidity_2m,apparent_temperature,"
                    "weather_code,wind_speed_10m"
                ),
                "timezone": "auto",
            },
        )
        current = data.get("current")
        if not current:
            return None
        code = current.get("weather_code")
        return {
            "temp": str(round(current["temperature_2m"])),
            "feels": str(round(current["apparent_temperature"])),
            "desc": _WMO_DESC_RU.get(code, f"Код погоды {code}"),
            "humidity": str(current["relative_humidity_2m"]),
            "wind": str(round(current["wind_speed_10m"])),
        }
    except Exception as exc:
        log.warning("Open-Meteo %s: %s", city, exc)
        return None


async def _from_wttr(city: str) -> dict[str, str] | None:
    for attempt in range(2):
        try:
            data = await http.get_json(
                f"https://wttr.in/{city}",
                params={"format": "j1", "lang": "ru"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            current = data["current_condition"][0]
            desc_en = current["weatherDesc"][0]["value"]
            desc = (current.get("lang_ru") or [{"value": ""}])[0].get("value") or (
                config.WEATHER_DESC_RU.get(desc_en, desc_en)
            )
            return {
                "temp": current["temp_C"],
                "feels": current["FeelsLikeC"],
                "desc": desc,
                "humidity": current["humidity"],
                "wind": current["windspeedKmph"],
            }
        except Exception as exc:
            log.warning("wttr.in %s (попытка %d): %s", city, attempt + 1, exc)
    return None


async def fetch_weather() -> dict[str, dict[str, str] | None]:
    """Погода по всем городам из config.DAILY_CITIES."""
    result: dict[str, dict[str, str] | None] = {}
    for english, russian in config.DAILY_CITIES.items():
        data = await _from_wttr(english)
        if data is None:
            data = await _from_openmeteo(english)
            if data:
                log.info("Погода %s — fallback Open-Meteo", english)
        result[russian] = data
    return result


_CURRENCIES = {
    "USD": "🇺🇸 USD",
    "EUR": "🇪🇺 EUR",
    "GBP": "🇬🇧 GBP",
    "BYN": "🇧🇾 BYN",
    "KZT": "🇰🇿 KZT",
}


async def fetch_currency() -> dict[str, float]:
    try:
        data = await http.get_json("https://api.exchangerate-api.com/v4/latest/RUB")
    except Exception as exc:
        log.warning("Курсы валют: %s", exc)
        return {}
    rates = data.get("rates", {})
    result: dict[str, float] = {}
    for code, label in _CURRENCIES.items():
        rate = rates.get(code)
        if rate:
            result[label] = round(1 / rate, 2)
    return result


async def fetch_daily_report() -> tuple[dict[str, dict[str, str] | None], dict[str, float]]:
    weather, currency = await fetch_weather(), await fetch_currency()
    return weather, currency


__all__ = ["fetch_weather", "fetch_currency", "fetch_daily_report"]
