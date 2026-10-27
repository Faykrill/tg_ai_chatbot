"""Глобальный обработчик ошибок хендлеров."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import ErrorEvent

from app.logging_setup import get_logger

__all__ = ["register"]

LOGGER = get_logger(__name__)


def register(root: Router) -> None:
    """Пишем в лог полный traceback и не даём ошибке уронить polling."""

    @root.errors()
    async def handle_error(event: ErrorEvent) -> bool:
        LOGGER.exception(
            "Необработанная ошибка при обработке апдейта %s",
            getattr(event.update, "update_type", "?"),
            exc_info=event.exception,
        )
        return True
