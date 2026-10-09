"""Музыкальный плеер: очередь, повторы и потоковое воспроизведение."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from services.http import http
from ui import style

log = logging.getLogger(__name__)

YDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

FFMPEG_PATH = None
for _path in ("ffmpeg.exe", "ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe", "/usr/bin/ffmpeg"):
    if os.path.isfile(_path):
        FFMPEG_PATH = _path
        break
if FFMPEG_PATH is None:
    FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"


class MusicTrack:
    __slots__ = ("url", "title", "duration", "requester", "requester_id", "webpage_url")

    def __init__(
        self,
        url: str,
        title: str,
        duration: int = 0,
        requester: discord.abc.User | None = None,
        webpage_url: str | None = None,
        requester_id: int | None = None,
    ):
        self.url = url
        self.title = title
        self.duration = duration
        self.requester = requester
        self.requester_id = requester_id if requester_id is not None else getattr(requester, "id", None)
        self.webpage_url = webpage_url or url

    def __str__(self) -> str:
        return f"{self.title} [{self.format_duration(self.duration)}]"

    @staticmethod
    def format_duration(seconds: int) -> str:
        if not seconds:
            return "0:00"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


def _track_to_dict(track: MusicTrack) -> dict:
    requester_id = track.requester_id
    if requester_id is None and track.requester is not None:
        requester_id = getattr(track.requester, "id", None)
    return {
        "title": track.title,
        "url": track.url,
        "webpage_url": track.webpage_url,
        "duration": int(track.duration or 0),
        "requester_id": requester_id,
    }


def _track_from_dict(data) -> MusicTrack | None:
    if not isinstance(data, dict):
        return None
    url = data.get("url")
    if not url:
        return None
    return MusicTrack(
        url=str(url),
        title=str(data.get("title") or "Unknown"),
        duration=int(data.get("duration") or 0),
        webpage_url=str(data.get("webpage_url") or url),
        requester_id=data.get("requester_id"),
    )


class GuildMusicPlayer:
    def __init__(self, guild_id: int, bot: commands.Bot):
        self.guild_id = guild_id
        self.bot = bot
        self.queue: list[MusicTrack] = []
        self.current: MusicTrack | None = None
        self.voice_client: discord.VoiceClient | None = None
        self.loop_one: bool = False
        self.loop_all: bool = False
        self.playing: bool = False

    # ------------------------------------------------------------ повтор

    @property
    def loop_mode(self) -> str:
        if self.loop_one:
            return "one"
        if self.loop_all:
            return "all"
        return "off"

    def set_loop_mode(self, mode: str) -> None:
        self.loop_one = mode == "one"
        self.loop_all = mode == "all"

    # ------------------------------------------------------------ персистентность

    def to_payload(self) -> dict:
        return {
            "queue": [_track_to_dict(track) for track in self.queue],
            "current": _track_to_dict(self.current) if self.current else None,
            "loop": self.loop_mode,
        }

    def load_payload(self, payload: dict) -> None:
        """Восстановление очереди из bot.music_store (голос не возвращаем)."""
        self.set_loop_mode(str(payload.get("loop") or "off"))
        queue = payload.get("queue")
        if isinstance(queue, list):
            for item in queue:
                track = _track_from_dict(item)
                if track is not None:
                    self.queue.append(track)
        current = _track_from_dict(payload.get("current"))
        if current is not None:
            self.queue.insert(0, current)

    async def persist(self) -> None:
        """Сохраняет очередь в bot.music_store (пустое состояние — удаляет)."""
        try:
            if self.queue or self.current:
                await self.bot.music_store.save(self.guild_id, self.to_payload())
            else:
                await self.bot.music_store.drop(self.guild_id)
        except Exception as exc:
            log.error("Не удалось сохранить очередь сервера %s: %s", self.guild_id, exc)

    def persist_soon(self) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self.persist(), self.bot.loop)
        except Exception as exc:
            log.error("Не удалось сохранить очередь сервера %s: %s", self.guild_id, exc)

    # ------------------------------------------------------------ воспроизведение

    def play_next(self) -> None:
        self.playing = True

        if self.loop_one and self.current:
            next_track = self.current
        elif self.loop_all and self.current:
            self.queue.append(self.current)
            next_track = self.queue.pop(0) if self.queue else None
        else:
            next_track = self.queue.pop(0) if self.queue else None
            if next_track is None:
                self.current = None
                self.playing = False

        if next_track is None:
            self.current = None
            self.playing = False
            self.persist_soon()
            asyncio.run_coroutine_threadsafe(self._disconnect(), self.bot.loop)
            return

        self.current = next_track
        self.persist_soon()

        def _after_play(error):
            if error:
                log.error("Music playback error in guild %s: %s", self.guild_id, error)
            asyncio.run_coroutine_threadsafe(self._safe_play_next(), self.bot.loop)

        try:
            source = discord.FFmpegPCMAudio(
                next_track.url,
                executable=FFMPEG_PATH,
                **FFMPEG_OPTIONS,
            )
            if self.voice_client and self.voice_client.is_connected():
                self.voice_client.play(source, after=_after_play)
            else:
                self.playing = False
                self.current = None
                self.persist_soon()
        except Exception as exc:
            log.error("Failed to play track in guild %s: %s", self.guild_id, exc)
            self.playing = False
            self.current = None
            self.persist_soon()
            asyncio.run_coroutine_threadsafe(self._safe_play_next(), self.bot.loop)

    async def _safe_play_next(self) -> None:
        try:
            self.play_next()
        except Exception as exc:
            log.error("Error in play_next for guild %s: %s", self.guild_id, exc)
            self.playing = False
            self.current = None

    async def _disconnect(self) -> None:
        try:
            if self.voice_client and self.voice_client.is_connected():
                await self.voice_client.disconnect()
        except Exception as exc:
            log.debug("Не удалось отключиться от голоса на сервере %s: %s", self.guild_id, exc)
        self.voice_client = None

    def stop(self) -> None:
        self.queue.clear()
        self.current = None
        self.loop_one = False
        self.loop_all = False
        self.playing = False
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
        asyncio.run_coroutine_threadsafe(self._disconnect(), self.bot.loop)


# ------------------------------------------------------------ разрешение ссылок

def _resolve_ytdlp(search_url: str) -> list[MusicTrack]:
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        try:
            info = ydl.extract_info(search_url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            log.error("yt_dlp extraction failed: %s", exc)
            return []

    tracks: list[MusicTrack] = []
    entries = info.get("entries") or []
    if not entries:
        entries = [info]

    for entry in entries:
        url = entry.get("url") or entry.get("webpage_url") or ""
        title = entry.get("title", "Unknown")
        duration = entry.get("duration") or 0
        webpage = entry.get("webpage_url") or entry.get("url") or ""
        tracks.append(
            MusicTrack(url=url, title=title, duration=duration, webpage_url=webpage)
        )

    return tracks


async def _spotify_oembed(url: str) -> dict | None:
    try:
        await http.start()
        data = await http.get_json(url)
    except Exception as exc:
        log.debug("Spotify oembed не ответил: %s", exc)
        return None
    return data if isinstance(data, dict) else None


async def _resolve_spotify(query: str) -> list[MusicTrack]:
    track_match = re.search(r"spotify:track:([a-zA-Z0-9]+)", query)
    url_match = re.search(r"open\.spotify\.com/track/([a-zA-Z0-9]+)", query)
    playlist_match = re.search(r"spotify:playlist:([a-zA-Z0-9]+)", query)
    playlist_url_match = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]+)", query)

    if track_match or url_match:
        track_id = track_match.group(1) if track_match else url_match.group(1)
        info_url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track_id}"
        search_query = f"spotify track {track_id}"

        data = await _spotify_oembed(info_url)
        if data is not None:
            track_name = data.get("title", "")
            description = data.get("description", track_name)
            search_query = description if description else (track_name or search_query)

        return await asyncio.to_thread(_resolve_ytdlp, f"ytsearch:{search_query}")

    if playlist_match or playlist_url_match:
        pl_id = playlist_match.group(1) if playlist_match else playlist_url_match.group(1)
        info_url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/playlist/{pl_id}"
        tracks: list[MusicTrack] = []

        data = await _spotify_oembed(info_url)
        if data is not None:
            description = str(data.get("description") or "")
            parts = [p.strip() for p in description.split("|") if p.strip()]
            if parts:
                search_query = " ".join(parts[:3])
                tracks = await asyncio.to_thread(_resolve_ytdlp, f"ytsearch5:{search_query}")

        if not tracks:
            tracks = await asyncio.to_thread(_resolve_ytdlp, f"ytsearch5:spotify playlist {pl_id}")
        return tracks

    return await asyncio.to_thread(_resolve_ytdlp, f"ytsearch:{query}")


async def resolve_music_url(query: str) -> list[MusicTrack]:
    query = query.strip()

    if re.search(r"(open\.spotify\.com|spotify:)", query):
        return await _resolve_spotify(query)

    if re.search(r"(music\.yandex\.ru|music\.yandex\.com)", query):
        return await asyncio.to_thread(_resolve_ytdlp, query)

    if re.match(r"https?://", query):
        return await asyncio.to_thread(_resolve_ytdlp, query)

    return await asyncio.to_thread(_resolve_ytdlp, f"ytsearch:{query}")


def _loop_status(player: GuildMusicPlayer) -> str:
    if player.loop_one:
        return "Один"
    if player.loop_all:
        return "Все"
    return "Выкл"


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildMusicPlayer] = {}

    async def cog_load(self) -> None:
        try:
            rows = await self.bot.db.fetchall("SELECT guild_id FROM music_state")
        except Exception as exc:
            log.error("Не удалось прочитать сохранённые музыкальные очереди: %s", exc)
            return
        for row in rows:
            try:
                await self._restore(int(row["guild_id"]))
            except Exception as exc:
                log.error("Не удалось восстановить очередь %s: %s", row.get("guild_id"), exc)

    async def _restore(self, guild_id: int) -> GuildMusicPlayer | None:
        if guild_id in self.players:
            return self.players[guild_id]
        try:
            payload = await self.bot.music_store.load(guild_id)
        except Exception as exc:
            log.error("Не удалось прочитать очередь сервера %s: %s", guild_id, exc)
            return None
        if not payload:
            return None
        player = GuildMusicPlayer(guild_id, self.bot)
        player.load_payload(payload)
        self.players[guild_id] = player
        log.info(
            "Очередь сервера %s восстановлена после рестарта: %d трек(ов)",
            guild_id,
            len(player.queue),
        )
        return player

    async def _get_player(self, guild_id: int | None) -> GuildMusicPlayer | None:
        return self.players.get(guild_id) or await self._restore(guild_id)

    async def _ensure_player(self, interaction: discord.Interaction) -> GuildMusicPlayer:
        guild_id = interaction.guild_id
        player = await self._get_player(guild_id)
        if player is None:
            player = GuildMusicPlayer(guild_id, self.bot)
            self.players[guild_id] = player
        return player

    async def _join_vc(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        member = interaction.user
        if not member.voice or not member.voice.channel:
            await interaction.followup.send(
                embed=style.error("Зайди в голосовой канал."), ephemeral=True
            )
            return None

        channel = member.voice.channel
        player = await self._ensure_player(interaction)

        if player.voice_client and player.voice_client.is_connected():
            if player.voice_client.channel.id != channel.id:
                await player.voice_client.move_to(channel)
            return player.voice_client

        vc = await channel.connect()
        player.voice_client = vc
        return vc

    # ------------------------------------------------------------ команды

    @app_commands.command(name="play", description="Включить музыку (YouTube, Яндекс Музыка, Spotify, поиск)")
    @app_commands.describe(query="Ссылка или название песни")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        player = await self._ensure_player(interaction)
        vc = await self._join_vc(interaction)
        if not vc:
            return

        tracks = await resolve_music_url(query)
        if not tracks:
            await interaction.followup.send(
                embed=style.error("Ничего не найдено."), ephemeral=True
            )
            return

        track = tracks[0]
        track.requester = interaction.user

        if player.playing or player.current:
            player.queue.append(track)
            embed = style.success(
                "Добавлено в очередь",
                f"[{track.title}]({track.webpage_url}) [{MusicTrack.format_duration(track.duration)}]",
                footer=f"Позиция в очереди: {len(player.queue)}",
            )
            await player.persist()
            await interaction.followup.send(embed=embed)
        else:
            player.queue.insert(0, track)
            player.play_next()
            embed = style.base(
                "Сейчас играет",
                f"[{track.title}]({track.webpage_url}) [{MusicTrack.format_duration(track.duration)}]",
                color=discord.Color.blue(),
            )
            await player.persist()
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="stop", description="Остановить музыку и выйти из канала")
    async def stop(self, interaction: discord.Interaction):
        player = await self._get_player(interaction.guild_id)
        if not player:
            await interaction.response.send_message(
                embed=style.error("Ничего не играет."), ephemeral=True
            )
            return

        player.stop()
        await player.persist()
        await interaction.response.send_message(embed=style.info("Остановлено и отключено."))

    @app_commands.command(name="skip", description="Пропустить текущий трек")
    async def skip(self, interaction: discord.Interaction):
        player = await self._get_player(interaction.guild_id)
        if not player or not player.current:
            await interaction.response.send_message(
                embed=style.error("Ничего не играет."), ephemeral=True
            )
            return

        if player.voice_client and player.voice_client.is_playing():
            title = player.current.title
            player.voice_client.stop()
            await interaction.response.send_message(embed=style.info(f"Пропущено: {title}"))
        else:
            await interaction.response.send_message(
                embed=style.error("Ничего не играет."), ephemeral=True
            )

    @app_commands.command(name="queue", description="Показать очередь воспроизведения")
    async def queue(self, interaction: discord.Interaction):
        player = await self._get_player(interaction.guild_id)
        if not player:
            await interaction.response.send_message(
                embed=style.error("Нет музыкального плеера для этого сервера."),
                ephemeral=True,
            )
            return

        embed = style.base("Очередь", color=discord.Color.orange(), footer=None)

        if player.current:
            embed.add_field(
                name="Сейчас играет",
                value=(
                    f"[{player.current.title}]({player.current.webpage_url}) "
                    f"[{MusicTrack.format_duration(player.current.duration)}]"
                ),
                inline=False,
            )

        if player.queue:
            lines = []
            for i, track in enumerate(player.queue[:15], 1):
                lines.append(
                    f"**{i}.** [{track.title}]({track.webpage_url}) "
                    f"[{MusicTrack.format_duration(track.duration)}]"
                )
            embed.add_field(name="Далее", value="\n".join(lines), inline=False)

            if len(player.queue) > 15:
                embed.set_footer(text=f"...и ещё {len(player.queue) - 15}")

        if not player.current and not player.queue:
            embed.description = "Очередь пуста."

        embed.set_footer(text=f"Повтор: {_loop_status(player)}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="Показать текущий трек")
    async def nowplaying(self, interaction: discord.Interaction):
        player = await self._get_player(interaction.guild_id)
        if not player or not player.current:
            await interaction.response.send_message(
                embed=style.error("Ничего не играет."), ephemeral=True
            )
            return

        track = player.current
        embed = style.base(
            "Сейчас играет",
            f"[{track.title}]({track.webpage_url})",
            color=discord.Color.blue(),
            footer=None,
        )
        embed.add_field(name="Длительность", value=MusicTrack.format_duration(track.duration))

        requester = track.requester
        if requester is None and track.requester_id and interaction.guild is not None:
            requester = interaction.guild.get_member(track.requester_id)
        if requester is not None:
            embed.set_footer(
                text=f"Запросил {requester.display_name}",
                icon_url=requester.display_avatar.url,
            )

        embed.add_field(name="Повтор", value=_loop_status(player))
        embed.add_field(name="Очередь", value=f"{len(player.queue)} трек(ов)")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="loop", description="Режим повтора (выкл / один / все)")
    async def loop(self, interaction: discord.Interaction):
        player = await self._get_player(interaction.guild_id)
        if not player:
            await interaction.response.send_message(
                embed=style.error("Нет музыкального плеера для этого сервера."),
                ephemeral=True,
            )
            return

        if not player.loop_one and not player.loop_all:
            player.loop_one = True
            mode = "Один (повтор трека)"
        elif player.loop_one:
            player.loop_one = False
            player.loop_all = True
            mode = "Все (повтор очереди)"
        else:
            player.loop_all = False
            mode = "Выкл"

        await player.persist()
        await interaction.response.send_message(embed=style.info(f"Режим повтора: {mode}"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
