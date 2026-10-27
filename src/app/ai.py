"""Клиент OpenAI-совместимого API с единой обработкой ошибок."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from openai import AsyncOpenAI

from app import texts
from app.config import Settings
from app.logging_setup import get_logger
from app.memory import ChatMessage
from app.prompts import DEFAULT_MODE, GenerationParams, params_for

__all__ = ["AIClient", "AIError", "GenerationResult"]

LOGGER = get_logger(__name__)

#: Роли, которые приходят в историю из Telegram — system добавляем сами.
SYSTEM_ROLE: Final[str] = "system"
USER_ROLE: Final[str] = "user"
ASSISTANT_ROLE: Final[str] = "assistant"


class AIError(RuntimeError):
    """ИИ не ответил. ``message`` можно показать пользователю."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Ответ модели плюс служебная информация о генерации."""

    text: str
    mode: str
    truncated: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AIClient:
    """Обёртка над ``AsyncOpenAI``: промпты, параметры режима, разбор ответа."""

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        self._settings = settings
        self._client = client or AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.provider.base_url,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,
        )

    @property
    def model(self) -> str:
        return self._settings.model

    @property
    def provider_name(self) -> str:
        return self._settings.provider.name

    def build_messages(
        self,
        prompt: str,
        *,
        mode: str = DEFAULT_MODE,
        history: Sequence[ChatMessage] = (),
    ) -> list[ChatMessage]:
        """Собирает список сообщений: system → история → новый запрос."""
        params: GenerationParams = params_for(mode)
        messages: list[ChatMessage] = [
            {"role": SYSTEM_ROLE, "content": params.system_prompt}  # type: ignore[typeddict-item]
        ]
        messages.extend(history)
        messages.append({"role": USER_ROLE, "content": prompt})
        return messages

    async def generate(
        self,
        prompt: str,
        *,
        mode: str = DEFAULT_MODE,
        history: Sequence[ChatMessage] = (),
    ) -> GenerationResult:
        """Запрашивает ответ у модели.

        :raises AIError: при сетевой ошибке, проблемах с ключом/квотой
            или пустом ответе модели.
        """
        params = params_for(mode)
        messages = self.build_messages(prompt, mode=mode, history=history)

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                temperature=params.temperature,
                max_tokens=params.max_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - SDK бросает разные типы ошибок
            LOGGER.exception("Ошибка запроса к ИИ (%s)", type(exc).__name__)
            raise AIError(texts.AI_UNAVAILABLE, cause=exc) from exc

        return self._parse_response(response, mode=mode)

    async def aclose(self) -> None:
        """Закрывает HTTP-сессию SDK."""
        await self._client.close()

    def _parse_response(self, response: Any, *, mode: str) -> GenerationResult:
        """Достаёт текст из ответа SDK, не падая на странных ответах провайдера."""
        usage = getattr(response, "usage", None)
        if usage is not None:
            LOGGER.info(
                "Токены: вход=%s, выход=%s",
                getattr(usage, "prompt_tokens", "?"),
                getattr(usage, "completion_tokens", "?"),
            )

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise AIError(texts.EMPTY_ANSWER)

        choice = choices[0]
        message = getattr(choice, "message", None)
        content = (getattr(message, "content", None) or "").strip()
        if not content:
            raise AIError(texts.EMPTY_ANSWER)

        truncated = getattr(choice, "finish_reason", None) == "length"
        if truncated:
            content += texts.TRUNCATED_NOTE

        return GenerationResult(
            text=content,
            mode=mode,
            truncated=truncated,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
