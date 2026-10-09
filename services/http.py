"""Общий HTTP-клиент на aiohttp для всех внешних вызовов."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)


class HttpClient:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": "VacationBot/2.0"},
            )
            log.info("HTTP-клиент запущен")

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise RuntimeError("HTTP-клиент не запущен")
        return self._session

    async def get_json(self, url: str, *, params: dict[str, Any] | None = None, **kwargs: Any):
        await self.start()
        async with self.session.get(url, params=params, **kwargs) as resp:
            if resp.status >= 400:
                raise aiohttp.ClientResponseError(
                    resp.request_info, resp.history, status=resp.status, message=str(resp.reason)
                )
            return await resp.json(content_type=None)

    async def post_json(self, url: str, *, timeout: float | None = None, **kwargs: Any):
        await self.start()
        client_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else DEFAULT_TIMEOUT
        async with self.session.post(url, timeout=client_timeout, **kwargs) as resp:
            data = await resp.json(content_type=None)
            return resp.status, data


http = HttpClient()

__all__ = ["http", "HttpClient"]
