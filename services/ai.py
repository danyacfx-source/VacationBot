"""AI-провайдеры: DeepSeek, OpenRouter, Gemini и свой endpoint.

Полностью асинхронно на aiohttp — никаких `requests` в потоке на 60 секунд.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

import config
from services.http import http

log = logging.getLogger(__name__)

TIMEOUT = 65
MAX_TOKENS = 500
TEMPERATURE = 1.2

Reply = tuple[str | None, str, int]


def detect_provider() -> str:
    if config.CUSTOM_API_BASE and config.CUSTOM_API_KEY:
        return "custom"
    if config.OPENROUTER_API_KEY:
        return "openrouter"
    if config.GEMINI_API_KEY:
        return "gemini"
    if config.DEEPSEEK_API_KEY:
        return "deepseek"
    return ""


async def _chat_completion(
    url: str,
    provider: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    params: dict[str, Any] | None = None,
) -> Reply:
    try:
        status, data = await http.post_json(
            url, headers=headers, json=payload, params=params, timeout=TIMEOUT
        )
    except asyncio.TimeoutError:
        return None, provider, 0
    except aiohttp.ClientError as exc:
        log.error("%s HTTP-ошибка: %s", provider, exc)
        return None, provider, 0

    if status != 200:
        log.error("%s API error %s: %s", provider, status, str(data)[:500])
        return None, provider, status

    try:
        content = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return None, provider, 0
    return content, provider, 200


async def _ask_custom(system_prompt: str, message: str) -> Reply:
    if not config.CUSTOM_API_BASE or not config.CUSTOM_API_KEY:
        return None, "custom", 0
    url = config.CUSTOM_API_BASE
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    return await _chat_completion(
        url,
        "custom",
        {
            "Authorization": f"Bearer {config.CUSTOM_API_KEY}",
            "Content-Type": "application/json",
        },
        {
            "model": config.AI_MODEL or config.CUSTOM_API_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
        },
    )


async def _ask_deepseek(system_prompt: str, message: str) -> Reply:
    if not config.DEEPSEEK_API_KEY:
        return None, "deepseek", 0
    return await _chat_completion(
        "https://api.deepseek.com/chat/completions",
        "deepseek",
        {
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
        },
    )


async def _ask_openrouter(system_prompt: str, message: str) -> Reply:
    if not config.OPENROUTER_API_KEY:
        return None, "openrouter", 0
    return await _chat_completion(
        "https://openrouter.ai/api/v1/chat/completions",
        "openrouter",
        {
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        {
            "model": config.AI_MODEL or "deepseek/deepseek-chat-v3-0324:free",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
        },
    )


async def _ask_gemini(system_prompt: str, message: str) -> Reply:
    if not config.GEMINI_API_KEY:
        return None, "gemini", 0
    model = config.AI_MODEL or "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    status, data = await http.post_json(
        url,
        params={"key": config.GEMINI_API_KEY},
        json={
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": message}]}],
            "generationConfig": {"maxOutputTokens": MAX_TOKENS, "temperature": TEMPERATURE},
        },
        timeout=TIMEOUT,
    )
    if status != 200:
        log.error("Gemini API error %s: %s", status, str(data)[:500])
        return None, "gemini", status
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        return None, "gemini", 0
    return text, "gemini", 200


async def ask(
    provider: str,
    system_prompt: str,
    message: str,
    *,
    timeout: float = TIMEOUT + 5,
) -> Reply:
    """Запрос к указанному провайдеру с таймаутом."""
    coro: Any
    if provider == "custom":
        coro = _ask_custom(system_prompt, message)
    elif provider == "openrouter":
        coro = _ask_openrouter(system_prompt, message)
    elif provider == "gemini":
        coro = _ask_gemini(system_prompt, message)
    else:
        coro = _ask_deepseek(system_prompt, message)
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return None, provider, 0


__all__ = ["ask", "detect_provider"]
