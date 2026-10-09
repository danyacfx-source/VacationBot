"""Переиспользуемые компоненты: подтверждения, пагинация, индикаторы."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import discord

from ui import style

ConfirmCallback = Callable[[], Awaitable[None]]
CancelCallback = Callable[[], Awaitable[None]]


class ConfirmView(discord.ui.View):
    """Кнопки «Да»/«Нет» с произвольным обработчиком."""

    def __init__(
        self,
        on_confirm: ConfirmCallback,
        *,
        on_cancel: CancelCallback | None = None,
        timeout: float = 60,
        confirm_label: str = "Да",
        cancel_label: str = "Нет",
        confirm_style: discord.ButtonStyle = discord.ButtonStyle.danger,
        author_id: int | None = None,
    ):
        super().__init__(timeout=timeout)
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._author_id = author_id
        self.message: discord.Message | None = None
        self.answered = False

        self.confirm_button.label = confirm_label
        self.cancel_button.label = cancel_label
        self.confirm_button.style = confirm_style

    async def _check(self, interaction: discord.Interaction) -> bool:
        if self._author_id is not None and interaction.user.id != self._author_id:
            await interaction.response.send_message(
                embed=style.error("Это не ваше подтверждение."), ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Да", style=discord.ButtonStyle.danger, row=0)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.answered or not await self._check(interaction):
            return
        self.answered = True
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            pass
        await self._on_confirm()
        self.stop()

    @discord.ui.button(label="Нет", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.answered or not await self._check(interaction):
            return
        self.answered = True
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            pass
        if self._on_cancel is not None:
            await self._on_cancel()
        self.stop()

    async def on_timeout(self) -> None:
        if self.answered or self.message is None:
            return
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


class Paginator(discord.ui.View):
    """Постраничный просмотр списка эмбедов."""

    def __init__(self, pages: list[discord.Embed], *, timeout: float = 180, author_id: int | None = None):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.index = 0
        self._author_id = author_id
        self.message: discord.Message | None = None
        self._update()

    def _update(self) -> None:
        last = len(self.pages) <= 1
        self.first.disabled = self.prev.disabled = last or self.index == 0
        self.last.disabled = self.next.disabled = last or self.index == len(self.pages) - 1
        for page_no, page in enumerate(self.pages, start=1):
            footer = page.footer.text or ""
            counter = f"Страница {page_no}/{len(self.pages)}"
            page.set_footer(text=f"{counter} • {footer}" if footer else counter)

    async def _edit(self, interaction: discord.Interaction) -> None:
        self._update()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    def _allowed(self, interaction: discord.Interaction) -> bool:
        if self._author_id is None or interaction.user.id == self._author_id:
            return True
        return False

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def first(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._allowed(interaction):
            return
        self.index = 0
        await self._edit(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._allowed(interaction):
            return
        self.index = max(0, self.index - 1)
        await self._edit(interaction)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._allowed(interaction):
            return
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self._edit(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def last(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._allowed(interaction):
            return
        self.index = len(self.pages) - 1
        await self._edit(interaction)

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


def chunk_pages(items: list[str], per_page: int) -> list[list[str]]:
    return [items[i : i + per_page] for i in range(0, len(items), per_page)]


__all__ = ["ConfirmView", "Paginator", "chunk_pages"]
