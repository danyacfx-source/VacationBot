"""Эмбеды памяти процесса."""

from __future__ import annotations

import discord

import psutil

from core.timeutil import msk_utcnow


def build_ram_embed() -> discord.Embed:
    proc = psutil.Process()
    memory = proc.memory_info()

    current_mb = memory.rss / (1024**2)
    peak_mb = memory.peak_wset / (1024**2) if hasattr(memory, "peak_wset") else None

    if current_mb >= 500:
        color = discord.Color.red()
    elif current_mb >= 200:
        color = discord.Color.orange()
    else:
        color = discord.Color.green()

    embed = discord.Embed(title="📊 Память бота", color=color)
    embed.add_field(name="Текущее потребление", value=f"**{current_mb:.1f}** МБ", inline=True)
    if peak_mb:
        embed.add_field(name="Пик", value=f"**{peak_mb:.1f}** МБ", inline=True)
    embed.set_footer(text=f"PID: {proc.pid}")
    embed.timestamp = msk_utcnow()
    return embed


__all__ = ["build_ram_embed"]
