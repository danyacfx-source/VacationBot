"""Временные голосовые каналы: создание по входу в триггер, управление, очистка."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

import config
from ui import style

log = logging.getLogger(__name__)

_channel_locks: dict[int, asyncio.Lock] = {}


def _is_trigger_channel(vc) -> bool:
    return vc.id in (config.VC_TRIGGER_CHANNEL, config.VC_WARDogs_TRIGGER_CHANNEL)


def _is_managed_category(category_id) -> bool:
    return category_id in (config.VC_CATEGORY, config.VC_WARDogs_CATEGORY)


def _channel_lock(channel_id: int) -> asyncio.Lock:
    lock = _channel_locks.get(channel_id)
    if lock is None:
        lock = asyncio.Lock()
        _channel_locks[channel_id] = lock
    return lock


async def _get_owner(bot, channel_id: int) -> int | None:
    return await bot.temp_channels.get_owner(channel_id)


class TempChannelKickModal(discord.ui.Modal, title="Выгнать участника"):

    target = discord.ui.TextInput(
        label="ID или упоминание участника",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Вы не в голосовом канале."), ephemeral=True
            )

        vc = interaction.user.voice.channel

        if _is_trigger_channel(vc) or not _is_managed_category(vc.category_id):
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя управлять этим каналом."), ephemeral=True
            )

        owner_id = await _get_owner(interaction.client, vc.id)
        if owner_id != interaction.user.id:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Только владелец канала может выгонять."), ephemeral=True
            )

        raw = self.target.value.strip()
        uid = raw.strip("<@!>")
        try:
            uid = int(uid)
        except ValueError:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Укажите ID участника."), ephemeral=True
            )

        member = interaction.guild.get_member(uid)
        if not member:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Участник не найден."), ephemeral=True
            )

        if member.voice and member.voice.channel and member.voice.channel.id == vc.id:
            try:
                await member.move_to(None, reason="Выгнан из временного канала")
            except Exception as e:
                log.error("Ошибка выгна участника %s из канала %s: %s", member, vc.name, e)
                return await interaction.response.send_message(
                    embed=style.error("Ошибка", "Не удалось выгнать участника."), ephemeral=True
                )
            await interaction.response.send_message(
                embed=style.success("Участник выгнан", f"✅ {member.mention} выгнан."), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=style.error("Ошибка", "Участник не в вашем канале."), ephemeral=True
            )


class TempChannelRenameModal(discord.ui.Modal, title="Переименовать канал"):

    new_name = discord.ui.TextInput(
        label="Новое название",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Вы не в голосовом канале."), ephemeral=True
            )

        vc = interaction.user.voice.channel

        if _is_trigger_channel(vc) or not _is_managed_category(vc.category_id):
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя управлять этим каналом."), ephemeral=True
            )

        owner_id = await _get_owner(interaction.client, vc.id)
        if owner_id != interaction.user.id:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Только владелец канала может переименовывать."), ephemeral=True
            )

        old_name = vc.name
        try:
            await vc.edit(name=self.new_name.value, reason="Переименован владельцем")
        except Exception as e:
            log.error("Ошибка переименования канала %s: %s", vc.name, e)
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Не удалось переименовать канал."), ephemeral=True
            )
        await interaction.response.send_message(
            embed=style.success(
                "Канал переименован",
                f"✅ Канал переименован: `{old_name}` → `{self.new_name.value}`"
            ),
            ephemeral=True
        )


class TempChannelLimitModal(discord.ui.Modal, title="Лимит участников"):

    limit = discord.ui.TextInput(
        label="Лимит (0 = без лимита, макс. 99)",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Вы не в голосовом канале."), ephemeral=True
            )

        vc = interaction.user.voice.channel

        if _is_trigger_channel(vc) or not _is_managed_category(vc.category_id):
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя управлять этим каналом."), ephemeral=True
            )

        owner_id = await _get_owner(interaction.client, vc.id)
        if owner_id != interaction.user.id:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Только владелец канала может менять лимит."), ephemeral=True
            )

        try:
            n = int(self.limit.value)
        except ValueError:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Введите число."), ephemeral=True
            )

        if n < 0 or n > 99:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Лимит должен быть от 0 до 99."), ephemeral=True
            )

        try:
            await vc.edit(user_limit=n, reason="Лимит изменён владельцем")
        except Exception as e:
            log.error("Ошибка изменения лимита канала %s: %s", vc.name, e)
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Не удалось изменить лимит."), ephemeral=True
            )
        if n == 0:
            text = "✅ Лимит снят."
        else:
            text = f"✅ Лимит установлен: **{n}** участников."
        await interaction.response.send_message(
            embed=style.success("Лимит изменён", text), ephemeral=True
        )


class TempChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔒 Закрыть",
        style=discord.ButtonStyle.danger,
        custom_id="temp_vc_lock"
    )
    async def lock_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Вы не в голосовом канале."), ephemeral=True
            )

        vc = interaction.user.voice.channel
        if _is_trigger_channel(vc) or not _is_managed_category(vc.category_id):
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Нельзя управлять этим каналом."), ephemeral=True
            )

        owner_id = await _get_owner(interaction.client, vc.id)
        if owner_id != interaction.user.id:
            return await interaction.response.send_message(
                embed=style.error("Ошибка", "Только владелец канала может закрывать/открывать."), ephemeral=True
            )

        everyone = interaction.guild.default_role
        current = vc.overwrites_for(everyone)
        is_locked = current.connect is False

        try:
            if is_locked:
                current.connect = None
                await vc.set_overwrite(everyone, overwrite=current, reason="Канал открыт")
                button.label = "🔒 Закрыть"
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(
                    embed=style.success("Канал открыт", "✅ Канал открыт."), ephemeral=True
                )
            else:
                current.connect = False
                await vc.set_overwrite(everyone, overwrite=current, reason="Канал закрыт")
                button.label = "🔓 Открыть"
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(
                    embed=style.success("Канал закрыт", "✅ Канал закрыт."), ephemeral=True
                )
        except Exception as e:
            log.error("Ошибка переключения блокировки канала %s: %s", vc.name, e)
            if interaction.response.is_done():
                await interaction.followup.send(
                    embed=style.error("Ошибка", "Не удалось изменить блокировку."), ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    embed=style.error("Ошибка", "Не удалось изменить блокировку."), ephemeral=True
                )

    @discord.ui.button(
        label="👢 Выгнать",
        style=discord.ButtonStyle.secondary,
        custom_id="temp_vc_kick"
    )
    async def kick_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempChannelKickModal())

    @discord.ui.button(
        label="✏️ Название",
        style=discord.ButtonStyle.primary,
        custom_id="temp_vc_rename"
    )
    async def rename_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempChannelRenameModal())

    @discord.ui.button(
        label="👥 Лимит",
        style=discord.ButtonStyle.success,
        custom_id="temp_vc_limit"
    )
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempChannelLimitModal())

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        log.error("Ошибка в TempChannelView: %s", error, exc_info=True)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("Произошла ошибка.", ephemeral=True)
            else:
                await interaction.response.send_message("Произошла ошибка.", ephemeral=True)
        except Exception:
            pass


class TempVoiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.scheduler.register_interval(
            "temp_voice_cleanup", self.cleanup_empty_channels, seconds=60
        )
        self.bot.add_persistent_view(TempChannelView())

    # ------------------------------------------------------------ фоновое задание

    async def cleanup_empty_channels(self) -> None:
        for guild in self.bot.guilds:
            for cat_id in (config.VC_CATEGORY, config.VC_WARDogs_CATEGORY):
                category = guild.get_channel(cat_id)
                if not category:
                    continue
                for ch in list(category.voice_channels):
                    if _is_trigger_channel(ch):
                        continue
                    humans = [m for m in ch.members if not m.bot]
                    if not humans:
                        async with _channel_lock(ch.id):
                            try:
                                await self.bot.temp_channels.remove(ch.id)
                                await ch.delete(reason="Периодическая очистка временных каналов")
                                log.info("Очищен пустой временный канал %s (периодическая уборка)", ch.name)
                            except discord.NotFound:
                                await self.bot.temp_channels.remove(ch.id)
                            except Exception as e:
                                log.error("Ошибка периодической очистки канала %s: %s", ch.name, e)

    # ------------------------------------------------------------ слушатели

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            owners = await self.bot.temp_channels.all()
            live_ids: set[int] = set()

            for guild in self.bot.guilds:
                for cat_id in (config.VC_CATEGORY, config.VC_WARDogs_CATEGORY):
                    category = guild.get_channel(cat_id)
                    if not category:
                        continue
                    for ch in list(category.voice_channels):
                        if _is_trigger_channel(ch):
                            continue
                        live_ids.add(ch.id)
                        humans = [m for m in ch.members if not m.bot]
                        if not humans:
                            async with _channel_lock(ch.id):
                                try:
                                    await self.bot.temp_channels.remove(ch.id)
                                    await ch.delete(reason="Очистка пустого временного канала")
                                    log.info("Очищен пустой временный канал %s", ch.name)
                                except discord.NotFound:
                                    await self.bot.temp_channels.remove(ch.id)
                                except Exception as e:
                                    log.error("Ошибка очистки временного канала %s: %s", ch.name, e)
                        elif ch.id not in owners:
                            await self.bot.temp_channels.set_owner(ch.id, humans[0].id)
                            log.info("Восстановлен владелец канала %s теперь %s", ch.name, humans[0])

                for trigger_id in (config.VC_TRIGGER_CHANNEL, config.VC_WARDogs_TRIGGER_CHANNEL):
                    trigger = guild.get_channel(trigger_id)
                    if trigger and any(not m.bot for m in trigger.members):
                        first = next(m for m in trigger.members if not m.bot)
                        await self._create_temp_channel(first, trigger)

            for ch_id in list(owners.keys()):
                if ch_id not in live_ids:
                    await self.bot.temp_channels.remove(ch_id)
        except Exception as e:
            log.error("Ошибка очистки временных каналов: %s", e)

    async def _create_temp_channel(self, member: discord.Member, trigger_channel):
        if trigger_channel.id == config.VC_WARDogs_TRIGGER_CHANNEL:
            cat_id = config.VC_WARDogs_CATEGORY
            name = "Wardogs"
        else:
            cat_id = config.VC_CATEGORY
            name = "Клановый"
        category = member.guild.get_channel(cat_id)
        try:
            vc = await member.guild.create_voice_channel(
                name=name,
                category=category,
                reason="Временный канал"
            )
            await self.bot.temp_channels.set_owner(vc.id, member.id)
            moved = False
            for m in list(trigger_channel.members):
                if m.bot:
                    continue
                try:
                    await m.move_to(vc, reason="Перемещение в временный канал")
                    moved = True
                except Exception as e:
                    log.error("Ошибка перемещения %s во временный канал: %s", m, e)
            if not moved:
                await self.bot.temp_channels.remove(vc.id)
                await vc.delete(reason="Временный канал: никто не перемещён")
                log.info("Удалён пустой временный канал (не удалось переместить участников)")
        except Exception as e:
            log.error("Ошибка создания временного канала: %s", e)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        if before.channel and _is_trigger_channel(before.channel):
            return

        if after.channel and _is_trigger_channel(after.channel):
            await self._create_temp_channel(member, after.channel)

        if before.channel and not _is_trigger_channel(before.channel) and _is_managed_category(before.channel.category_id):
            vc = before.channel

            if after.channel and after.channel.id == vc.id:
                return

            owner_id = await self.bot.temp_channels.get_owner(vc.id)
            leaving_owner = owner_id is not None and owner_id == member.id
            async with _channel_lock(vc.id):
                remaining = [m for m in vc.members if not m.bot]
                if not remaining:
                    try:
                        await self.bot.temp_channels.remove(vc.id)
                        await vc.delete(reason="Временный канал: все вышли")
                        log.info("Удалён пустой временный канал %s", vc.name)
                    except discord.NotFound:
                        await self.bot.temp_channels.remove(vc.id)
                    except Exception as e:
                        log.error("Ошибка удаления временного канала: %s", e)
                elif leaving_owner:
                    new_owner = None
                    for m in remaining:
                        if owner_id != m.id:
                            new_owner = m
                            break
                    if new_owner is None:
                        new_owner = remaining[0]
                    await self.bot.temp_channels.set_owner(vc.id, new_owner.id)
                    log.info("Владелец канала %s теперь %s", vc.name, new_owner)
                    embed = style.base(
                        "👑 Права канала переданы",
                        description=(
                            f"Предыдущий владелец **{member.display_name}** покинул канал.\n"
                            f"Новый владелец: **{new_owner.mention}**"
                        ),
                        color=discord.Color.gold()
                    )
                    try:
                        await vc.send(embed=embed)
                    except discord.NotFound:
                        log.info("Канал %s уже удалён, уведомление о передаче прав пропущено", vc.name)
                    except Exception as e:
                        log.error("Ошибка уведомления о передаче прав: %s", e)


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVoiceCog(bot))
