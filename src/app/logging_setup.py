"""Настройка логирования: единый формат для консоли и Docker-логов."""

from __future__ import annotations

import logging
import sys
from typing import Final

__all__ = ["get_logger", "setup_logging"]

LOG_FORMAT: Final[str] = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

#: Библиотеки, которые пишут слишком много на уровне INFO.
QUIET_LOGGERS: Final[tuple[str, ...]] = ("httpx", "httpcore", "openai", "aiogram.event")


def setup_logging(level: str | int = "INFO") -> logging.Logger:
    """Настраивает root-логгер и возвращает его."""
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        stream=sys.stdout,
        force=True,
    )
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    return logging.getLogger()


def get_logger(name: str | None = None) -> logging.Logger:
    """Короткая обёртка, чтобы логгеры создавались в одном месте."""
    return logging.getLogger(name)
