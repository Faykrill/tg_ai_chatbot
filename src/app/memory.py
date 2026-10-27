"""Память диалогов в оперативной памяти.

Хранит историю по ключу ``(user_id, chat_id, thread_id)``, ограничивает её
сверху по числу пар «вопрос-ответ» и по количеству диалогов (LRU), чтобы бот
не разрастался в бесконечный словарь.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from aiogram.types import Message as TelegramMessage

__all__ = ["ChatMessage", "DialogueKey", "DialogueMemory"]

Role = Literal["system", "user", "assistant"]


class ChatMessage(TypedDict):
    """Сообщение в формате chat.completions."""

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class DialogueKey:
    """Ключ диалога: кто, где и в какой теме написал."""

    user_id: int
    chat_id: int
    thread_id: int | None

    @classmethod
    def from_message(cls, message: TelegramMessage) -> DialogueKey:
        """Строит ключ из сообщения Telegram.

        В каналах и группах с анонимными постами ``from_user`` может быть None,
        тогда используем ``sender_chat``, а при его отсутствии — сам чат.
        """
        if message.from_user is not None:
            user_id = message.from_user.id
        elif message.sender_chat is not None:
            user_id = message.sender_chat.id
        else:
            user_id = message.chat.id
        return cls(
            user_id=user_id,
            chat_id=message.chat.id,
            thread_id=message.message_thread_id,
        )


class DialogueMemory:
    """LRU-хранилище истории диалогов."""

    def __init__(self, max_pairs: int = 10, max_dialogs: int = 500) -> None:
        if max_pairs <= 0:
            raise ValueError("max_pairs должен быть больше нуля")
        if max_dialogs <= 0:
            raise ValueError("max_dialogs должен быть больше нуля")
        self._max_pairs = max_pairs
        self._max_dialogs = max_dialogs
        self._dialogs: OrderedDict[DialogueKey, list[ChatMessage]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def max_pairs(self) -> int:
        return self._max_pairs

    @property
    def max_messages(self) -> int:
        return self._max_pairs * 2

    @property
    def dialog_count(self) -> int:
        """Сколько диалогов сейчас в памяти."""
        with self._lock:
            return len(self._dialogs)

    def history(self, key: DialogueKey) -> list[ChatMessage]:
        """Копия истории диалога (пустой список, если диалога нет)."""
        with self._lock:
            messages = self._dialogs.get(key)
            if messages is None:
                return []
            self._dialogs.move_to_end(key)
            return list(messages)

    def pairs_count(self, key: DialogueKey) -> int:
        """Число полных пар сообщений в диалоге."""
        with self._lock:
            return len(self._dialogs.get(key, ())) // 2

    def record_turn(self, key: DialogueKey, prompt: str, answer: str) -> None:
        """Добавляет пару «вопрос-ответ» и обрезает историю по лимиту."""
        with self._lock:
            messages = self._dialogs.setdefault(key, [])
            messages.append({"role": "user", "content": prompt})
            messages.append({"role": "assistant", "content": answer})
            self._dialogs[key] = self._trim(messages)
            self._dialogs.move_to_end(key)
            while len(self._dialogs) > self._max_dialogs:
                self._dialogs.popitem(last=False)

    def clear(self, key: DialogueKey) -> bool:
        """Очищает диалог. Возвращает True, если в памяти что-то было."""
        with self._lock:
            return self._dialogs.pop(key, None) is not None

    def _trim(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """Оставляет последние ``max_pairs`` пар, начиная с сообщения пользователя."""
        trimmed = messages[-self.max_messages :]
        while trimmed and trimmed[0]["role"] != "user":
            trimmed.pop(0)
        return trimmed
