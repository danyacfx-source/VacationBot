import json
import os
import logging
from datetime import datetime

import discord
import psutil
import requests

from config import (
    LOG_CHANNEL,
    STARTUP_LOG_CHANNEL,
    TICKET_LOG_CHANNEL,
    VACATION_LOG_CHANNEL,
    DATA_FILE,
    TICKETS_DATA_FILE,
    BIRTHDAY_FILE,
    EVENTS_FILE,
    ERROR_ROLE,
    DAILY_CITIES,
    WEATHER_DESC_RU,
)


async def send_log(bot, title, description, color=discord.Color.red(), ping=True):
    channel = bot.get_channel(LOG_CHANNEL)
    if channel:
        embed = discord.Embed(title=title, description=description, color=color)
        try:
            content = f"<@&{ERROR_ROLE}>" if ping else None
            await channel.send(content=content, embed=embed)
        except Exception:
            pass


async def send_startup_log(bot, title, description, color=discord.Color.green()):
    channel = bot.get_channel(STARTUP_LOG_CHANNEL)
    if channel:
        embed = discord.Embed(title=title, description=description, color=color)
        try:
            await channel.send(embed=embed)
        except Exception:
            pass


async def send_ticket_log(bot, title, description, color=discord.Color.blue()):
    channel = bot.get_channel(TICKET_LOG_CHANNEL)
    if channel:
        embed = discord.Embed(title=title, description=description, color=color)
        try:
            await channel.send(embed=embed)
        except Exception:
            pass


async def send_vacation_log(bot, title, description, color=discord.Color.orange()):
    channel = bot.get_channel(VACATION_LOG_CHANNEL)
    if channel:
        embed = discord.Embed(title=title, description=description, color=color)
        try:
            await channel.send(embed=embed)
        except Exception:
            pass


async def update_vacation_panel(bot):
    raw = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    panel_data = raw.get("__panel__")
    if not panel_data:
        return
    channel = bot.get_channel(panel_data.get("channel_id"))
    if not channel:
        return
    try:
        info_msg = await channel.fetch_message(panel_data.get("info_message_id"))
        embed_data = {k: v for k, v in raw.items() if k != "__panel__"}
        embed = build_info_panel_embed(embed_data)
        await info_msg.edit(embed=embed)
    except Exception:
        pass
    try:
        request_msg = await channel.fetch_message(panel_data.get("request_message_id"))
        embed = build_request_panel_embed()
        await request_msg.edit(embed=embed)
    except Exception:
        pass


def load_vacations():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.pop("__panel__", None)
        return data
    return {}


def save_vacations(data):
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = {}
    panel_info = raw.get("__panel__")
    out = dict(data)
    if panel_info:
        out["__panel__"] = panel_info
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=4)


def build_info_panel_embed(data):
    now = datetime.now()

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

        user_name = v.get("user_name", f"<@{uid}>")
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

    if entries:
        embed.description = "\n\n".join(entries)
    else:
        embed.description = "Нет активных отпусков"

    embed.set_footer(text="Сделано с ❤️ от Денди")
    return embed


def build_request_panel_embed():
    embed = discord.Embed(
        title="Система отпусков | Панель",
        description=(
            "Нажмите кнопку ниже, чтобы подать заявку на отпуск.\n\n"
            "🔹 **Взять отпуск** — подать заявку\n"
            "🔹 **Статус** — посмотреть свои отпуска\n"
            "🔹 **Продлить отпуск** — продлить текущий отпуск\n"
            "🔹 **Снять отпуск** — отменить текущий отпуск"
        ),
        color=discord.Color.blurple(),
    )
    return embed


def load_tickets():
    from database import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT number, user_id, channel_id, category, status, created_at, closed_at, closed_by, transcript FROM tickets"
    ).fetchall()
    result = {}
    for r in rows:
        result[str(r[0])] = {
            "user_id": str(r[1]),
            "channel_id": str(r[2]),
            "category": r[3],
            "status": r[4],
            "created_at": r[5],
            "closed_at": r[6],
            "closed_by": str(r[7]) if r[7] else "",
            "transcript": r[8],
        }
    return result


def save_tickets(data):
    from database import get_conn
    conn = get_conn()
    for num_str, t in data.items():
        if num_str.startswith("_"):
            continue
        conn.execute(
            """INSERT OR REPLACE INTO tickets
               (number, user_id, channel_id, category, status, created_at, closed_at, closed_by, transcript)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(num_str),
                int(t.get("user_id", 0)),
                int(t.get("channel_id", 0)),
                t.get("category", ""),
                t.get("status", "open"),
                t.get("created_at", ""),
                t.get("closed_at", ""),
                int(t.get("closed_by", 0)) if t.get("closed_by") else 0,
                t.get("transcript", ""),
            ),
        )
    conn.commit()


def load_birthdays():
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT user_id, date, notified FROM birthdays").fetchall()
    return {str(r[0]): {"date": r[1], "notified": bool(r[2])} for r in rows}


def save_birthdays(data):
    from database import get_conn
    conn = get_conn()
    for uid, info in data.items():
        conn.execute(
            "INSERT OR REPLACE INTO birthdays (user_id, date, notified) VALUES (?, ?, ?)",
            (int(uid), info.get("date", ""), int(info.get("notified", False))),
        )
    conn.commit()


def load_events():
    from database import get_conn
    import json as _json
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, start, briefing, description, creator_id, host_id, "
        "going_inf, going_tech, going, maybe, sl, camera, not_going, show_not_going, "
        "required, channel_id, image_url, event_type, location, date, time, "
        "reminded_briefing_minus15, reminded_briefing, reminded_start_minus15 "
        "FROM events"
    ).fetchall()
    result = {}
    for r in rows:
        going_inf = _json.loads(r[7]) if r[7] else []
        legacy_going = _json.loads(r[9]) if r[9] else []
        for u in legacy_going:
            if u not in going_inf:
                going_inf.append(u)
        creator = r[5] if r[5] else r[6]
        result[str(r[0])] = {
            "name": r[1],
            "start": r[2] or (f"{r[20]} {r[21]}".strip() if r[20] else ""),
            "briefing": r[3] or "",
            "description": r[4] or "",
            "creator_id": str(creator) if creator else "",
            "going_inf": going_inf,
            "going_tech": _json.loads(r[8]) if r[8] else [],
            "maybe": _json.loads(r[10]) if r[10] else [],
            "sl": _json.loads(r[11]) if r[11] else [],
            "camera": _json.loads(r[12]) if r[12] else [],
            "not_going": _json.loads(r[13]) if r[13] else [],
            "show_not_going": bool(r[14]) if r[14] is not None else True,
            "required": r[15] or 0,
            "channel_id": r[16] or 0,
            "image_url": r[17] or "",
            "event_type": r[18] or "freeform",
            "location": r[19] or "",
            "reminded_briefing_minus15": bool(r[22]) if r[22] is not None else False,
            "reminded_briefing": bool(r[23]) if r[23] is not None else False,
            "reminded_start_minus15": bool(r[24]) if r[24] is not None else False,
        }
    return result


def save_events(data):
    from database import get_conn
    import json as _json
    conn = get_conn()
    valid_ids = []
    for eid, ev in data.items():
        if eid.startswith("_"):
            continue
        valid_ids.append(int(eid))
        going_inf = list(ev.get("going_inf", []))
        for u in ev.get("going", []):
            if u not in going_inf:
                going_inf.append(u)
        start = ev.get("start") or (f"{ev.get('date', '')} {ev.get('time', '')}".strip())
        conn.execute(
            """INSERT OR REPLACE INTO events
               (id, name, start, briefing, description, host_id, creator_id,
                going_inf, going_tech, going, maybe, sl, camera, not_going,
                show_not_going, required, channel_id, image_url, event_type, location,
                reminded_briefing_minus15, reminded_briefing, reminded_start_minus15)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(eid),
                ev.get("name", ""),
                start,
                ev.get("briefing", ""),
                ev.get("description", ""),
                int(ev.get("host_id", 0) or 0),
                int(ev.get("creator_id", 0) or 0),
                _json.dumps(going_inf),
                _json.dumps(ev.get("going_tech", [])),
                _json.dumps([]),
                _json.dumps(ev.get("maybe", [])),
                _json.dumps(ev.get("sl", [])),
                _json.dumps(ev.get("camera", [])),
                _json.dumps(ev.get("not_going", [])),
                int(bool(ev.get("show_not_going", True))),
                int(ev.get("required", 0) or 0),
                int(ev.get("channel_id", 0) or 0),
                ev.get("image_url", ""),
                ev.get("event_type", "freeform"),
                ev.get("location", ""),
                int(bool(ev.get("reminded_briefing_minus15", False))),
                int(bool(ev.get("reminded_briefing", False))),
                int(bool(ev.get("reminded_start_minus15", False))),
            ),
        )
    if valid_ids:
        placeholders = ",".join("?" * len(valid_ids))
        conn.execute(f"DELETE FROM events WHERE id NOT IN ({placeholders})", valid_ids)
    else:
        conn.execute("DELETE FROM events")
    conn.commit()


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

_OM_COORDS_CACHE = {}


def _om_coords(eng):
    coords = _OM_COORDS_CACHE.get(eng)
    if coords:
        return coords
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": eng, "count": 1},
            timeout=10,
        )
        results = (r.json().get("results") or [])
        if not results:
            return None
        coords = (results[0]["latitude"], results[0]["longitude"])
        _OM_COORDS_CACHE[eng] = coords
        return coords
    except Exception as e:
        logging.warning("Open-Meteo geocoding error for %s: %s", eng, e)
        return None


def _fetch_weather_openmeteo(eng):
    try:
        coords = _om_coords(eng)
        if coords is None:
            return None
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": coords[0],
                "longitude": coords[1],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=10,
        )
        cur = r.json().get("current")
        if not cur:
            return None
        code = cur.get("weather_code")
        return {
            "temp": str(round(cur["temperature_2m"])),
            "feels": str(round(cur["apparent_temperature"])),
            "desc": _WMO_DESC_RU.get(code, f"Код погоды {code}"),
            "humidity": str(cur["relative_humidity_2m"]),
            "wind": str(round(cur["wind_speed_10m"])),
        }
    except Exception as e:
        logging.warning("Open-Meteo fetch error for %s: %s", eng, e)
        return None


def fetch_weather():
    result = {}
    for eng, rus in DAILY_CITIES.items():
        data = None
        for attempt in range(2):
            try:
                r = requests.get(
                    f"https://wttr.in/{eng}?format=j1&lang=ru",
                    timeout=15,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                data = r.json()
                break
            except Exception as e:
                logging.warning("Weather fetch error for %s (попытка %d): %s", eng, attempt + 1, e)
        if data is None:
            result[rus] = None
        else:
            try:
                cur = data["current_condition"][0]
                temp = cur["temp_C"]
                feels = cur["FeelsLikeC"]
                desc_en = cur["weatherDesc"][0]["value"]
                desc = (
                    cur.get("lang_ru") or [{"value": ""}]
                )[0].get("value") or WEATHER_DESC_RU.get(desc_en, desc_en)
                humidity = cur["humidity"]
                wind = cur["windspeedKmph"]
                result[rus] = {
                    "temp": temp,
                    "feels": feels,
                    "desc": desc,
                    "humidity": humidity,
                    "wind": wind,
                }
            except Exception as e:
                logging.warning("Weather parse error for %s: %s", eng, e)
                result[rus] = None
        if result[rus] is None:
            fallback = _fetch_weather_openmeteo(eng)
            if fallback:
                result[rus] = fallback
                logging.info("Weather fallback (Open-Meteo) for %s", eng)
    return result


def fetch_currency():
    result = {}
    try:
        r = requests.get(
            "https://api.exchangerate-api.com/v4/latest/RUB",
            timeout=10
        )
        data = r.json()
        rates = data.get("rates", {})
        currencies = {
            "USD": "🇺🇸 USD",
            "EUR": "🇪🇺 EUR",
            "GBP": "🇬🇧 GBP",
            "BYN": "🇧🇾 BYN",
            "KZT": "🇰🇿 KZT",
        }
        for code, label in currencies.items():
            rate = rates.get(code)
            if rate:
                rub_per_unit = round(1 / rate, 2)
                result[label] = rub_per_unit
    except Exception as e:
        logging.warning("Currency fetch error: %s", e)
    return result


def get_ram_embed():
    proc = psutil.Process()
    proc_mem = proc.memory_info()

    proc_mb = proc_mem.rss / (1024 ** 2)
    peak_mb = proc_mem.peak_wset / (1024 ** 2) if hasattr(proc_mem, 'peak_wset') else None

    if proc_mb >= 500:
        color = discord.Color.red()
    elif proc_mb >= 200:
        color = discord.Color.orange()
    else:
        color = discord.Color.green()

    embed = discord.Embed(
        title="📊 Память бота",
        color=color
    )
    embed.add_field(name="Текущее потребление", value=f"**{proc_mb:.1f}** МБ", inline=True)
    if peak_mb:
        embed.add_field(name="Пик", value=f"**{peak_mb:.1f}** МБ", inline=True)
    embed.set_footer(text=f"PID: {proc.pid}")
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_event_embed(event_id, data):
    embed = discord.Embed(
        title=data["name"],
        color=discord.Color.blurple()
    )

    if data.get("description"):
        embed.add_field(name="Описание / Description", value=data["description"], inline=False)

    start_display = (data.get("start") or f"{data.get('date', '')} {data.get('time', '')}") + " (МСК)"
    briefing_display = (data.get("briefing") or start_display) + " (МСК)" if data.get("briefing") else start_display

    embed.add_field(
        name="Сбор / Briefing",
        value=briefing_display,
        inline=False
    )

    embed.add_field(
        name="Начало / Start",
        value=start_display,
        inline=False
    )

    required = data.get("required", 0)
    going_count = len(data.get("going_inf", [])) + len(data.get("going_tech", []))
    if required > 0:
        embed.add_field(
            name="Нужно людей",
            value=f"**{going_count}** / {required}",
            inline=False
        )

    for key, label in [
        ("going_inf", "🪖 Иду (пех)"),
        ("going_tech", "🚜 Иду (тех)"),
        ("maybe", "🤔 Возможно"),
        ("sl", "🟠 SL"),
        ("camera", "📷 Камера"),
    ]:
        users = data.get(key, [])
        count = len(users)
        if users:
            value = "\n".join(f"<@{uid}>" for uid in users)
        else:
            value = "—"
        embed.add_field(name=f"{label} ({count})", value=value, inline=True)

    if data.get("show_not_going") or data.get("not_going"):
        users = data.get("not_going", [])
        count = len(users)
        value = "\n".join(f"<@{uid}>" for uid in users) if users else "—"
        embed.add_field(name=f"❌ Не иду ({count})", value=value, inline=True)

    creator_id = data.get("creator_id")
    if creator_id:
        embed.add_field(
            name="Создал / Created by",
            value=f"<@{creator_id}>",
            inline=False
        )

    if data.get("image_url"):
        embed.set_image(url=data["image_url"])

    embed.set_footer(text=f"ID: {event_id}")
    return embed
