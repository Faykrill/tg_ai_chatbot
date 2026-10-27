"""Контейнер зависимостей бота.

Один объект ``Services`` создаётся при старте и передаётся всем хендлерам,
фильтрам и middleware через ``Dispatcher.start_polling(bot, services=...)``,
поэтому в коде не приходится работать с глобальными переменными.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aiogram.types import User

from app.ai import AIClient
from app.config import Settings
from app.logging_setup import get_logger
from app.memory import DialogueMemory
from app.stores import GroupModeStore, JsonDictStore, TopicStore

__all__ = ["BotIdentity", "Services"]

LOGGER = get_logger(__name__)


@dataclass(slots=True)
class BotIdentity:
    """Данные самого бота: нужны для поиска упоминаний и ответов себе."""

    username: str = ""
    user_id: int = 0

    @property
    def mention(self) -> str:
        """Строка вида ``@username`` (пустая, если username не задан)."""
        return f"@{self.username}" if self.username else ""

    def update(self, user: User) -> None:
        """Заполняет данные бота ответом ``getMe``."""
        self.username = user.username or ""
        self.user_id = user.id

    def is_same_user(self, user: User | None) -> bool:
        return bool(self.user_id) and user is not None and user.id == self.user_id


@dataclass(slots=True)
class Services:
    """Всё, что нужно хендлерам: настройки, ИИ, память и хранилища."""

    settings: Settings
    ai: AIClient
    memory: DialogueMemory
    topics: TopicStore
    group_modes: GroupModeStore
    identity: BotIdentity = field(default_factory=BotIdentity)

    @classmethod
    def build(cls, settings: Settings) -> "Services":
        """Создаёт все зависимости из настроек (файлы читаются сразу)."""
        return cls(
            settings=settings,
            ai=AIClient(settings),
            memory=DialogueMemory(
                max_pairs=settings.max_history_pairs,
                max_dialogs=settings.max_dialogs,
            ),
            topics=TopicStore(JsonDictStore(settings.topics_file)),
            group_modes=GroupModeStore(JsonDictStore(settings.group_modes_file)),
        )

    async def aclose(self) -> None:
        """Освобождает ресурсы при остановке бота."""
        await self.ai.aclose()
