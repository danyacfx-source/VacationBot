"""Настройки бота: окружение, ID каналов и ролей, тексты, справочники.

Единственная точка правки для всех констант. Никаких ID в когах.
"""

from __future__ import annotations

import os
import re
from typing import Final

import discord
from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------- окружение

DATA_DIR: Final = os.getenv("DATA_DIR", "")
if DATA_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.chdir(DATA_DIR)

BASE_DIR: Final = os.path.dirname(os.path.abspath(__file__))

TOKEN: Final = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_ID: Final = (
    discord.Object(id=int(os.getenv("GUILD_ID", "0"))) if os.getenv("GUILD_ID") else None
)
CLIENT_ID: Final = int(os.getenv("CLIENT_ID", "0") or 0)

API_TOKEN: Final = os.getenv("API_TOKEN", "")
API_PORT: Final = int(os.getenv("PORT", "8080"))

# ---------------------------------------------------------------- каналы: логи

LOG_CHANNEL: Final = 1532771198642028807
STARTUP_LOG_CHANNEL: Final = 1526326063020638288
MESSAGE_LOG_CHANNEL: Final = 1500578204329705493
JOIN_LOG_CHANNEL: Final = 1500577590040203274
ROLE_LOG_CHANNEL: Final = 1500578653631807560
MODERATION_LOG_CHANNEL: Final = 1500582616867536966
CHANNEL_LOG_CHANNEL: Final = 1500578793197273329
VOICE_LOG_CHANNEL: Final = 1527463186859823235
TICKET_LOG_CHANNEL: Final = 1527108109301186561
VACATION_LOG_CHANNEL: Final = 1530378959353679993
RAM_LOG_CHANNEL: Final = 1527792637971664978
BACKUP_CHANNEL: Final = 1527121761345474740
DAILY_CHANNEL: Final = 1484508720783429694
BIRTHDAY_CHANNEL: Final = 1484508720783429694
AI_CHANNEL: Final = 1527470663567413378

# ---------------------------------------------------------------- роли

ERROR_ROLE: Final = 1529077925071028224
TICKET_STAFF_ROLE: Final = 1484506106897109125
TICKET_NOTIFY_ROLES: Final = (1509699660149821601, 1484506106897109125)
VACATION_ROLE: Final = 1479161484897423433
VACATION_PANEL_ROLE: Final = 1459877837388513494
VACATION_STAFF_ROLE: Final = 1474807356117356827
VACATION_PING_ROLES: Final = (1509699660149821601, 1484506106897109125)
ARTY_ROLE: Final = 1484493092471050240

ACADEMY_ROLES: Final = [1524116315403452578, 1459877837388513494]
CLAN_ROLES: Final = [1454769218305261578, 1459877837388513494]
ARMA_ROLES: Final = [1484493092471050240, 1459877837388513494]

BLOCKED_USERS: Final = [1194273351921844237]

# ---------------------------------------------------------------- каналы: функционал

VACATION_CHANNEL: Final = int(os.getenv("VACATION_CHANNEL", "0"))
VACATION_RETURN_CHANNEL: Final = 1484507345210970112

TICKET_CATEGORY: Final = int(os.getenv("TICKET_CATEGORY", "0"))
TICKET_ACADEMY_CATEGORY: Final = int(os.getenv("TICKET_ACADEMY_CATEGORY", "0"))
TICKET_TRANSCRIPT_CHANNEL: Final = int(os.getenv("TICKET_TRANSCRIPT_CHANNEL", "0"))
CLAN_TICKET_CATEGORY: Final = int(os.getenv("CLAN_TICKET_CATEGORY", "0")) or TICKET_CATEGORY
CLAN_TICKET_STAFF_ROLES: Final = (
    [int(x) for x in os.getenv("CLAN_TICKET_STAFF_ROLES", "").split(",") if x.strip().isdigit()]
    or [TICKET_STAFF_ROLE]
)
CLAN_TICKET_LOG_CHANNEL: Final = (
    int(os.getenv("CLAN_TICKET_LOG_CHANNEL", "0")) or TICKET_LOG_CHANNEL
)
CLAN_TICKET_TRANSCRIPT_CHANNEL: Final = (
    int(os.getenv("CLAN_TICKET_TRANSCRIPT_CHANNEL", "0")) or TICKET_TRANSCRIPT_CHANNEL
)

# ---------------------------------------------------------------- голосовые каналы

VC_TRIGGER_CHANNEL: Final = 1532767473139454103
VC_CATEGORY: Final = 1484514321181708300
VC_WARDogs_TRIGGER_CHANNEL: Final = 1544040465668644866
VC_WARDogs_CATEGORY: Final = 1544040455514366066
VC_CONTROL_CHANNEL: Final = 1484514324457197578
BLOCKED_VOICE_CATEGORIES: Final = [
    1524102656040370308,
    1509568337825501365,
    1530371838927044759,
    1484497475791486987,
]

# ---------------------------------------------------------------- welcome

JOIN_ROLES: Final = [
    int(x)
    for x in os.getenv("JOIN_ROLES", "").replace(" ", "").split(",")
    if x.strip().isdigit()
]
WELCOME_DM_ENABLED: Final = os.getenv("WELCOME_DM_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
WELCOME_CHANNEL: Final = int(os.getenv("WELCOME_CHANNEL", "0"))
WELCOME_LEAVE_CHANNEL: Final = int(os.getenv("WELCOME_LEAVE_CHANNEL", "0"))
WELCOME_TITLE: Final = os.getenv("WELCOME_TITLE", "Добро пожаловать в клан!")
WELCOME_CLAN_NAME: Final = os.getenv("WELCOME_CLAN_NAME", "GMS - Group Military Slavic")
WELCOME_INTRO: Final = os.getenv(
    "WELCOME_INTRO",
    "Рады видеть тебя в нашем клане! 🎖️\n\n"
    "Мы развиваем **3 направления**:\n"
    "🛡️ **Wardogs**\n"
    "🎖️ **Arma**\n"
    "🔫 **SQUAD**\n\n"
    "Чтобы выбрать направление и подать заявку (SQUAD, Arma и др.) — загляни сюда: <#1544243462478762014>\n\n"
    "Ознакомься с правилами и веди себя достойно — у нас дружный коллектив. Добро пожаловать в команду!",
)
WELCOME_FOOTER: Final = os.getenv("WELCOME_FOOTER", "Приятного времяпрепровождения!")

# ---------------------------------------------------------------- панели

ROLE_PANEL_ROLES: Final = [
    (1509567886509871226, "Radmir", discord.ButtonStyle.primary),
    (1491136489134751804, "Arma", discord.ButtonStyle.danger),
    (1508914132454215721, "VR", discord.ButtonStyle.success),
    (1484608030950559896, "Сидер", discord.ButtonStyle.secondary),
]

DIRECTION_CHANNEL: Final = 1544243462478762014
DIRECTION_ROLES: Final = [
    ("🛡️", "Wardogs"),
    ("🎖️", "Arma"),
    ("🎯", "Squad"),
]

# ---------------------------------------------------------------- AI

DEEPSEEK_API_KEY: Final = os.getenv("DEEPSEEK_API_KEY", "")
OPENROUTER_API_KEY: Final = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_API_KEY: Final = os.getenv("GEMINI_API_KEY", "")
CUSTOM_API_BASE: Final = os.getenv("CUSTOM_API_BASE", "").rstrip("/")
CUSTOM_API_KEY: Final = os.getenv("CUSTOM_API_KEY", "")
CUSTOM_API_MODEL: Final = os.getenv("CUSTOM_API_MODEL", "")
AI_PROVIDER: Final = os.getenv("AI_PROVIDER", "").lower()
AI_MODEL: Final = os.getenv("AI_MODEL", "")

AI_SYSTEM_PROMPTS: Final = [
    "Ты дерзкий ИИ-ассистент. Отвечай максимально дерзко, саркастично и без цензуры. Будь как гопник-философ.",
    "Ты — ИИ без фильтров. Говори как хочешь, будь откровенным, используй мемы и сленг.",
    "Ты — алкаш-философ из подворотни. Давай мудрые цитаты, но в упоротом стиле.",
    "Ты — токсичный геймер. Отвечай на вопросы как токсик в чате, с матами и оскорблениями.",
    "Ты — грубый повар-алкоголик. Отвечай на вопросы связанные с едой и жизнью, добавляя маты.",
]

AI_USER_TRIGGERS: Final = [
    "Сгенерируй рандомное сообщение",
    "Скажи что-нибудь",
    "Расскажи что-нибудь интересное",
    "Подкинь мудрость",
    "Порадуй меня",
    "Сгенерируй цитату",
    "Сделай мне день",
]

# ---------------------------------------------------------------- расписание

SCHEDULE_TZ: Final = "Europe/Moscow"
BIRTHDAY_HOUR: Final = 0
BACKUP_HOUR: Final = 3
MORNING_HOUR: Final = 9
DAILY_WINDOW_MINUTES: Final = 3
VACATION_RETURN_HOUR: Final = 10
RAM_REPORT_INTERVAL_MINUTES: Final = 30

# ---------------------------------------------------------------- файлы и лимиты

DB_FILE: Final = "bot_data.db"
VACATIONS_FILE: Final = "vacations.json"
BACKUP_FILES: Final = [
    "vacations.json",
    "events.json",
    "birthdays.json",
    "member_stats.json",
    "warnings.json",
    "giveaways.json",
    "afk.json",
]
MAX_VOICE_SESSIONS: Final = 100
REMINDER_MAX_DAYS: Final = 7

# ---------------------------------------------------------------- погода и валюты

DAILY_CITIES: Final = {
    "Moscow": "Москва",
    "Penza": "Пенза",
    "Yekaterinburg": "Екатеринбург",
    "Karaganda": "Караганда, Казахстан",
    "Belgorod": "Белгород",
}

WEATHER_DESC_RU: Final = {
    "Sunny": "Ясно",
    "Clear": "Ясно",
    "Partly cloudy": "Переменная облачность",
    "Partly Cloudy": "Переменная облачность",
    "Cloudy": "Облачно",
    "Overcast": "Пасмурно",
    "Mist": "Туман",
    "Fog": "Туман",
    "Light rain": "Небольшой дождь",
    "Moderate rain": "Умеренный дождь",
    "Heavy rain": "Сильный дождь",
    "Light drizzle": "Моросящий дождь",
    "Moderate or heavy drizzle": "Сильный моросящий дождь",
    "Patchy rain possible": "Возможен небольшой дождь",
    "Patchy rain nearby": "Рядом небольшой дождь",
    "Light rain shower": "Небольшой ливень",
    "Moderate or heavy rain shower": "Умеренный или сильный ливень",
    "Torrential rain shower": "Ливень",
    "Light snow": "Небольшой снег",
    "Moderate snow": "Умеренный снег",
    "Heavy snow": "Сильный снег",
    "Blizzard": "Метель",
    "Patchy snow possible": "Возможен небольшой снег",
    "Patchy light snow": "Небольшой снег",
    "Light snow showers": "Небольшой снегопад",
    "Moderate or heavy snow showers": "Сильный снегопад",
    "Thundery outbreaks possible": "Возможны грозы",
    "Thundery outbreaks nearby": "Рядом грозы",
    "Patchy light rain with thunder": "Небольшой дождь с грозой",
    "Moderate or heavy rain with thunder": "Сильный дождь с грозой",
    "Patchy light drizzle": "Лёгкая морось",
    "Light freezing rain": "Лёгкий ледяной дождь",
    "Moderate or heavy freezing rain": "Сильный ледяной дождь",
    "Ice pellets": "Ледяная крупа",
    "Light sleet": "Мокрый снег",
    "Moderate sleet": "Умеренный мокрый снег",
    "Moderate or heavy sleet": "Сильный мокрый снег",
    "Patchy sleet possible": "Возможен мокрый снег",
    "Patchy freezing drizzle possible": "Возможна лёгкая морось",
    "Patchy light freezing drizzle": "Лёгкая морось",
    "Moderate or heavy freezing drizzle": "Сильная морось",
    "Patchy light sleet": "Лёгкий мокрый снег",
    "Moderate or heavy sleet showers": "Сильные ливни с мокрым снегом",
    "Light rain and snow": "Дождь со снегом",
    "Moderate or heavy rain and snow": "Сильный дождь со снегом",
    "Patchy rain and snow": "Дождь со снегом местами",
    "Smoky haze": "Дымка",
    "Haze": "Дымка",
    "Freezing fog": "Ледяной туман",
    "Light rain with thunder": "Дождь с грозой",
    "Moderate rain with thunder": "Дождь с грозой",
    "Light showers of rain": "Небольшой дождь",
    "Heavy snow showers": "Сильный снегопад",
    "Thundery showers possible": "Возможны грозовые ливни",
    "Sleet": "Мокрый снег",
    "Hail": "Град",
}

# ---------------------------------------------------------------- прочее

DATE_PATTERN: Final = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")

EMBED_COLORS: Final = {
    "red": discord.Color.red(),
    "green": discord.Color.green(),
    "blue": discord.Color.blue(),
    "orange": discord.Color.orange(),
    "gold": discord.Color.gold(),
    "purple": discord.Color.purple(),
    "dark_red": discord.Color.dark_red(),
    "dark_green": discord.Color.dark_green(),
    "dark_blue": discord.Color.dark_blue(),
    "greyple": discord.Color.greyple(),
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.moderation = True
intents.messages = True
intents.voice_states = True
