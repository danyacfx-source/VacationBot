import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
import config

import asyncio
import tempfile
import re
import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp

MUSIC_TEMP_DIR = tempfile.mkdtemp(prefix="bot_music_")

YDL_OPTS = {
    'format': 'bestaudio/best',
    'outtmpl': os.path.join(MUSIC_TEMP_DIR, '%(id)s.%(ext)s'),
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'extract_flat': False,
    'cookiefile': None,
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

FFMPEG_PATH = None
for p in ['ffmpeg.exe', 'ffmpeg', r'C:\ffmpeg\bin\ffmpeg.exe', '/usr/bin/ffmpeg']:
    if os.path.isfile(p):
        FFMPEG_PATH = p
        break
if FFMPEG_PATH is None:
    import shutil
    FFMPEG_PATH = shutil.which('ffmpeg') or 'ffmpeg'


class MusicTrack:
    __slots__ = ('url', 'title', 'duration', 'requester', 'webpage_url')

    def __init__(self, url: str, title: str, duration: int = 0, requester: discord.Member = None, webpage_url: str = None):
        self.url = url
        self.title = title
        self.duration = duration
        self.requester = requester
        self.webpage_url = webpage_url or url

    def __str__(self):
        return f'{self.title} [{self.format_duration(self.duration)}]'

    @staticmethod
    def format_duration(seconds: int) -> str:
        if not seconds:
            return '0:00'
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f'{h}:{m:02d}:{s:02d}'
        return f'{m}:{s:02d}'


class GuildMusicPlayer:
    def __init__(self, guild_id: int, bot: commands.Bot):
        self.guild_id = guild_id
        self.bot = bot
        self.queue: list[MusicTrack] = []
        self.current: MusicTrack = None
        self.voice_client: discord.VoiceClient = None
        self.loop_one: bool = False
        self.loop_all: bool = False
        self.playing: bool = False

    def play_next(self):
        self.playing = True

        if self.loop_one and self.current:
            next_track = self.current
        elif self.loop_all and self.current:
            self.queue.append(self.current)
            next_track = self.queue.pop(0) if self.queue else None
        else:
            if self.queue:
                next_track = self.queue.pop(0)
            else:
                next_track = None
                self.current = None
                self.playing = False

        if next_track is None:
            self.current = None
            self.playing = False
            asyncio.run_coroutine_threadsafe(self._disconnect(), self.bot.loop)
            return

        self.current = next_track

        def _after_play(error):
            if error:
                logging.error('Music playback error in guild %s: %s', self.guild_id, error)
            asyncio.run_coroutine_threadsafe(self._safe_play_next(), self.bot.loop)

        try:
            source = discord.FFmpegPCMAudio(
                next_track.url,
                executable=FFMPEG_PATH,
                **FFMPEG_OPTIONS
            )
            if self.voice_client and self.voice_client.is_connected():
                self.voice_client.play(source, after=_after_play)
            else:
                self.playing = False
                self.current = None
        except Exception as e:
            logging.error('Failed to play track in guild %s: %s', self.guild_id, e)
            self.playing = False
            self.current = None
            asyncio.run_coroutine_threadsafe(self._safe_play_next(), self.bot.loop)

    async def _safe_play_next(self):
        try:
            self.play_next()
        except Exception as e:
            logging.error('Error in play_next for guild %s: %s', self.guild_id, e)
            self.playing = False
            self.current = None

    async def _disconnect(self):
        try:
            if self.voice_client and self.voice_client.is_connected():
                await self.voice_client.disconnect()
        except Exception:
            pass
        self.voice_client = None

    @staticmethod
    def _extract_url(url: str) -> dict:
        opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'source_address': '0.0.0.0',
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info

    def stop(self):
        self.queue.clear()
        self.current = None
        self.loop_one = False
        self.loop_all = False
        self.playing = False
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
        asyncio.run_coroutine_threadsafe(self._disconnect(), self.bot.loop)


music_players: dict[int, GuildMusicPlayer] = {}


def get_music_player(guild_id: int) -> GuildMusicPlayer:
    if guild_id not in music_players:
        return None
    return music_players[guild_id]


async def resolve_music_url(query: str) -> list[MusicTrack]:
    query = query.strip()

    if re.search(r'(open\.spotify\.com|spotify:)', query):
        return await _resolve_spotify(query)

    if re.search(r'(music\.yandex\.ru|music\.yandex\.com)', query):
        return _resolve_ytdlp(query)

    if re.match(r'https?://', query):
        return _resolve_ytdlp(query)

    return _resolve_ytdlp(f'ytsearch:{query}')


def _resolve_ytdlp(search_url: str) -> list[MusicTrack]:
    opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'source_address': '0.0.0.0',
        'extract_flat': False,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(search_url, download=False)
        except yt_dlp.utils.DownloadError as e:
            logging.error('yt_dlp extraction failed: %s', e)
            return []

    tracks = []
    entries = info.get('entries', [])
    if not entries:
        entries = [info]

    for entry in entries:
        url = entry.get('url') or entry.get('webpage_url') or entry.get('webpage_url', '')
        title = entry.get('title', 'Unknown')
        duration = entry.get('duration') or 0
        webpage = entry.get('webpage_url') or entry.get('url', '')
        tracks.append(MusicTrack(
            url=url,
            title=title,
            duration=duration,
            webpage_url=webpage,
        ))

    return tracks


async def _resolve_spotify(query: str) -> list[MusicTrack]:
    track_match = re.search(r'spotify:track:([a-zA-Z0-9]+)', query)
    url_match = re.search(r'open\.spotify\.com/track/([a-zA-Z0-9]+)', query)
    playlist_match = re.search(r'spotify:playlist:([a-zA-Z0-9]+)', query)
    playlist_url_match = re.search(r'open\.spotify\.com/playlist/([a-zA-Z0-9]+)', query)

    if track_match or url_match:
        track_id = track_match.group(1) if track_match else url_match.group(1)
        info_url = f'https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track_id}'
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(info_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        artist = data.get('thumbnail_url', '')
                        track_name = data.get('title', '')
                        description = data.get('description', track_name)
                        search_query = description if description else track_name
                    else:
                        search_query = f'spotify track {track_id}'
        except Exception:
            search_query = f'spotify track {track_id}'

        results = _resolve_ytdlp(f'ytsearch:{search_query}')
        return results

    if playlist_match or playlist_url_match:
        pl_id = playlist_match.group(1) if playlist_match else playlist_url_match.group(1)
        info_url = f'https://open.spotify.com/oembed?url=https://open.spotify.com/playlist/{pl_id}'
        tracks = []
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(info_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        description = data.get('description', '')
                        parts = [p.strip() for p in description.split('|') if p.strip()]
                        if parts:
                            search_query = ' '.join(parts[:3])
                            tracks = _resolve_ytdlp(f'ytsearch5:{search_query}')
        except Exception:
            pass

        if not tracks:
            tracks = _resolve_ytdlp(f'ytsearch5:spotify playlist {pl_id}')
        return tracks

    return _resolve_ytdlp(f'ytsearch:{query}')


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _ensure_player(self, interaction: discord.Interaction) -> GuildMusicPlayer:
        gid = interaction.guild_id
        if gid not in music_players:
            music_players[gid] = GuildMusicPlayer(gid, self.bot)
        return music_players[gid]

    async def _join_vc(self, interaction: discord.Interaction) -> discord.VoiceClient:
        member = interaction.user
        if not member.voice or not member.voice.channel:
            await interaction.followup.send('Зайди в голосовой канал.', ephemeral=True)
            return None

        channel = member.voice.channel
        player = await self._ensure_player(interaction)

        if player.voice_client and player.voice_client.is_connected():
            if player.voice_client.channel.id != channel.id:
                await player.voice_client.move_to(channel)
            return player.voice_client
        else:
            vc = await channel.connect()
            player.voice_client = vc
            return vc

    @app_commands.command(name='play', description='Включить музыку (YouTube, Яндекс Музыка, Spotify, поиск)')
    @app_commands.describe(query='Ссылка или название песни')
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        player = await self._ensure_player(interaction)
        vc = await self._join_vc(interaction)
        if not vc:
            return

        tracks = await resolve_music_url(query)
        if not tracks:
            await interaction.followup.send('Ничего не найдено.', ephemeral=True)
            return

        track = tracks[0]
        track.requester = interaction.user

        if player.playing or player.current:
            player.queue.append(track)
            embed = discord.Embed(
                title='Добавлено в очередь',
                description=f'[{track.title}]({track.webpage_url}) [{MusicTrack.format_duration(track.duration)}]',
                color=discord.Color.green()
            )
            embed.set_footer(text=f'Позиция в очереди: {len(player.queue)}')
            await interaction.followup.send(embed=embed)
        else:
            player.queue.append(track)
            player.play_next()
            embed = discord.Embed(
                title='Сейчас играет',
                description=f'[{track.title}]({track.webpage_url}) [{MusicTrack.format_duration(track.duration)}]',
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed)

    @app_commands.command(name='stop', description='Остановить музыку и выйти из канала')
    async def stop(self, interaction: discord.Interaction):
        player = get_music_player(interaction.guild_id)
        if not player:
            await interaction.response.send_message('Ничего не играет.', ephemeral=True)
            return

        player.stop()
        await interaction.response.send_message('Остановлено и отключено.')

    @app_commands.command(name='skip', description='Пропустить текущий трек')
    async def skip(self, interaction: discord.Interaction):
        player = get_music_player(interaction.guild_id)
        if not player or not player.current:
            await interaction.response.send_message('Ничего не играет.', ephemeral=True)
            return

        if player.voice_client and player.voice_client.is_playing():
            player.voice_client.stop()
            await interaction.response.send_message(f'Пропущено: {player.current.title}')
        else:
            await interaction.response.send_message('Ничего не играет.', ephemeral=True)

    @app_commands.command(name='queue', description='Показать очередь воспроизведения')
    async def queue(self, interaction: discord.Interaction):
        player = get_music_player(interaction.guild_id)
        if not player:
            await interaction.response.send_message('Нет музыкального плеера для этого сервера.', ephemeral=True)
            return

        embed = discord.Embed(title='Очередь', color=discord.Color.orange())

        if player.current:
            embed.add_field(
                name='Сейчас играет',
                value=f'[{player.current.title}]({player.current.webpage_url}) [{MusicTrack.format_duration(player.current.duration)}]',
                inline=False
            )

        if player.queue:
            lines = []
            for i, t in enumerate(player.queue[:15], 1):
                lines.append(f'**{i}.** [{t.title}]({t.webpage_url}) [{MusicTrack.format_duration(t.duration)}]')
            embed.add_field(
                name='Далее',
                value='\n'.join(lines),
                inline=False
            )

            if len(player.queue) > 15:
                embed.set_footer(text=f'...и ещё {len(player.queue) - 15}')

        if not player.current and not player.queue:
            embed.description = 'Очередь пуста.'

        loop_status = 'Выкл'
        if player.loop_one:
            loop_status = 'Один'
        elif player.loop_all:
            loop_status = 'Все'
        embed.set_footer(text=f'Повтор: {loop_status}')

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='nowplaying', description='Показать текущий трек')
    async def nowplaying(self, interaction: discord.Interaction):
        player = get_music_player(interaction.guild_id)
        if not player or not player.current:
            await interaction.response.send_message('Ничего не играет.', ephemeral=True)
            return

        track = player.current
        embed = discord.Embed(
            title='Сейчас играет',
            description=f'[{track.title}]({track.webpage_url})',
            color=discord.Color.blue()
        )
        embed.add_field(name='Длительность', value=MusicTrack.format_duration(track.duration))
        if track.requester:
            embed.set_footer(text=f'Запросил {track.requester.display_name}', icon_url=track.requester.display_avatar.url)

        loop_status = 'Выкл'
        if player.loop_one:
            loop_status = 'Один'
        elif player.loop_all:
            loop_status = 'Все'
        embed.add_field(name='Повтор', value=loop_status)

        queue_len = len(player.queue)
        embed.add_field(name='Очередь', value=f'{queue_len} трек(ов)')

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='loop', description='Режим повтора (выкл / один / все)')
    async def loop(self, interaction: discord.Interaction):
        player = get_music_player(interaction.guild_id)
        if not player:
            await interaction.response.send_message('Нет музыкального плеера для этого сервера.', ephemeral=True)
            return

        if not player.loop_one and not player.loop_all:
            player.loop_one = True
            mode = 'Один (повтор трека)'
        elif player.loop_one:
            player.loop_one = False
            player.loop_all = True
            mode = 'Все (повтор очереди)'
        else:
            player.loop_all = False
            mode = 'Выкл'

        await interaction.response.send_message(f'Режим повтора: {mode}')


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
