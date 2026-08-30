import os
import re
import discord
from dotenv import load_dotenv

load_dotenv(override=True)

DATA_DIR = os.getenv("DATA_DIR", "")
if DATA_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.chdir(DATA_DIR)

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_ID = discord.Object(id=int(os.getenv("GUILD_ID", "0"))) if os.getenv("GUILD_ID") else None

# Прокси для соединения с Discord (например, встроенный VPN SOCKS/HTTP-прокси).
# Если пусто или "system" — используется прокси из переменных окружения (HTTP_PROXY/HTTPS_PROXY),
# иначе строкой вида "http://127.0.0.1:10809" или "socks5://127.0.0.1:10808".
PROXY_URL = os.getenv("DISCORD_PROXY", "")
VACATION_CHANNEL = int(os.getenv("VACATION_CHANNEL", "0"))
LOG_CHANNEL = 1532771198642028807
STARTUP_LOG_CHANNEL = 1526326063020638288
TICKET_CATEGORY = int(os.getenv("TICKET_CATEGORY", "0"))
TICKET_ACADEMY_CATEGORY = int(os.getenv("TICKET_ACADEMY_CATEGORY", "0"))
TICKET_TRANSCRIPT_CHANNEL = int(os.getenv("TICKET_TRANSCRIPT_CHANNEL", "0"))
DATA_FILE = "vacations.json"
MESSAGE_LOG_CHANNEL = 1500578204329705493
JOIN_LOG_CHANNEL = 1500577590040203274
JOIN_ROLES = [
    int(x) for x in os.getenv("JOIN_ROLES", "").replace(" ", "").split(",") if x.strip().isdigit()
]
ROLE_LOG_CHANNEL = 1500578653631807560
MODERATION_LOG_CHANNEL = 1500582616867536966
CHANNEL_LOG_CHANNEL = 1500578793197273329
VOICE_LOG_CHANNEL = 1527463186859823235
VC_TRIGGER_CHANNEL = 1532767473139454103
VC_CATEGORY = 1484514321181708300
BLOCKED_VOICE_CATEGORIES = [1524102656040370308, 1509568337825501365, 1530371838927044759, 1484497475791486987]
VC_CONTROL_CHANNEL = 1484514324457197578
DAILY_CHANNEL = 1484508720783429694
BIRTHDAY_FILE = "birthdays.json"
BIRTHDAY_CHANNEL = 1484508720783429694
TICKET_LOG_CHANNEL = 1527108109301186561
VACATION_LOG_CHANNEL = 1530378959353679993
TICKET_STAFF_ROLE = 1484506106897109125
VACATION_RETURN_CHANNEL = 1484507345210970112
BACKUP_CHANNEL = 1527121761345474740
BACKUP_FILES = ["vacations.json", "events.json", "birthdays.json", "tickets.json", "member_stats.json", "warnings.json", "giveaways.json", "afk.json"]
AI_CHANNEL = 1527470663567413378
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CUSTOM_API_BASE = os.getenv("CUSTOM_API_BASE", "").rstrip("/")
CUSTOM_API_KEY = os.getenv("CUSTOM_API_KEY", "")
CUSTOM_API_MODEL = os.getenv("CUSTOM_API_MODEL", "")
AI_PROVIDER = os.getenv("AI_PROVIDER", "").lower()
AI_MODEL = os.getenv("AI_MODEL", "")
API_TOKEN = os.getenv("API_TOKEN", "")
API_PORT = 8080
RAM_LOG_CHANNEL = 1527792637971664978
BLOCKED_USERS = [1194273351921844237]
ERROR_ROLE = 1529077925071028224
TICKETS_DATA_FILE = "tickets.json"
EVENTS_FILE = "events.json"
VACATION_STAFF_ROLE = 1474807356117356827
VACATION_ROLE = 1479161484897423433
ARTY_ROLE = 1484493092471050240
ACADEMY_ROLES = [1524116315403452578, 1459877837388513494]
CLAN_ROLES = [1454769218305261578, 1459877837388513494]
ARMA_ROLES = [1484493092471050240, 1459877837388513494]

ROLE_PANEL_ROLES = [
    (1509567886509871226, "Radmir", discord.ButtonStyle.primary),
    (1491136489134751804, "Arma", discord.ButtonStyle.danger),
    (1508914132454215721, "VR", discord.ButtonStyle.success),
    (1484608030950559896, "Сидер", discord.ButtonStyle.secondary),
]

EMBED_COLORS = {
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

DAILY_CITIES = {
    "Moscow": "Москва",
    "Penza": "Пенза",
    "Yekaterinburg": "Екатеринбург",
    "Karaganda": "Караганда, Казахстан",
    "Belgorod": "Белгород",
}

WEATHER_DESC_RU = {
    "Sunny": "Ясно", "Clear": "Ясно",
    "Partly cloudy": "Переменная облачность", "Partly Cloudy": "Переменная облачность",
    "Cloudy": "Облачно", "Overcast": "Пасмурно",
    "Mist": "Туман", "Fog": "Туман",
    "Light rain": "Небольшой дождь", "Moderate rain": "Умеренный дождь",
    "Heavy rain": "Сильный дождь", "Light drizzle": "Моросящий дождь",
    "Moderate or heavy drizzle": "Сильный моросящий дождь",
    "Patchy rain possible": "Возможен небольшой дождь",
    "Patchy rain nearby": "Рядом небольшой дождь",
    "Light rain shower": "Небольшой ливень",
    "Moderate or heavy rain shower": "Умеренный или сильный ливень",
    "Torrential rain shower": "Ливень",
    "Light snow": "Небольшой снег", "Moderate snow": "Умеренный снег",
    "Heavy snow": "Сильный снег", "Blizzard": "Метель",
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
    "Moderate or heavy sleet": "Сильный мокрый снег",
    "Patchy sleet possible": "Возможен мокрый снег",
    "Patchy freezing drizzle possible": "Возможна лёгкая морось",
    "Patchy light freezing drizzle": "Лёгкая морось",
    "Moderate or heavy freezing drizzle": "Сильная морось",
    "Patchy light sleet": "Лёгкий мокрый снег",
    "Moderate or heavy sleet showers": "Сильные ливни с мокрым снегом",
    "Light rain and snow": "Дождь со снегом",
    "Moderate or heavy rain and snow": "Сильный дождь со снегом",
    "Patchy light rain and snow": "Небольшой дождь со снегом",
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
    "Moderate or heavy sleet": "Сильный мокрый снег",
}

DATE_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.moderation = True
intents.messages = True
intents.voice_states = True

AI_SYSTEM_PROMPTS = [
    "Ты дерзкий ИИ-ассистент. Отвечай максимально дерзко, саркастично и без цензуры. Будь как гопник-философ.",
    "Ты — ИИ без фильтров. Говори как хочешь, будь откровенным, используй мемы и сленг.",
    "Ты — алкаш-философ из подворотни. Давай мудрые цитаты, но в упоротом стиле.",
    "Ты — токсичный геймер. Отвечай на вопросы как токсик в чате, с матами и оскорблениями.",
    "Ты — грубый повар-алкоголик. Отвечай на вопросы связанные с едой и жизнью, добавляя маты.",
]

AI_USER_TRIGGERS = [
    "Сгенерируй рандомное сообщение", "Скажи что-нибудь",
    "Расскажи что-нибудь интересное", "Подкинь мудрость",
    "Порадуй меня",     "Сгенерируй цитату", "Сделай мне день",
]
