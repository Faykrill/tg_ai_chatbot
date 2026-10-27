"""JSON-хранилища настроек бота: привязки к темам и режимы групп.

Файлы пишутся атомарно (во временный файл + ``os.replace``), чтобы при
внезапной остановке контейнера не получить обрезанный JSON.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Final

from app.logging_setup import get_logger

__all__ = ["GroupMode", "GroupModeStore", "JsonDictStore", "TopicStore"]

LOGGER = get_logger(__name__)

#: Маркер «ключа нет в словаре» (нужен, чтобы отличать None от отсутствия).
_MISSING: Final[object] = object()


def _normalize_thread(thread_id: int | None) -> int | None:
    """Приводит General-тему к одному виду.

    В форум-группах сообщения в General приходят либо без ``message_thread_id``
    (None), либо с id=1 — для бота это одна и та же тема.
    """
    return None if thread_id is None or thread_id == 1 else thread_id


class JsonDictStore:
    """Простейшее хранилище словаря в JSON-файле."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> dict[str, Any]:
        """Читает файл; при любой ошибке возвращает пустой словарь."""
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            LOGGER.exception("Не удалось прочитать %s", self._path.name)
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, data: Mapping[str, Any]) -> bool:
        """Атомарно записывает словарь. Возвращает True при успехе."""
        try:
            with self._lock:
                tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
                tmp_path.write_text(
                    json.dumps(dict(data), ensure_ascii=False), encoding="utf-8"
                )
                os.replace(tmp_path, self._path)
        except OSError:
            LOGGER.exception("Не удалось сохранить %s", self._path.name)
            return False
        return True


class TopicStore:
    """Привязка форум-групп к темам: ``chat_id -> message_thread_id``.

    Если группа есть в словаре, бот отвечает ТОЛЬКО в этой теме.
    Значение ``None`` означает тему General, поэтому «привязано» и
    «нет привязки» различаются наличием ключа, а не его значением.
    """

    def __init__(self, storage: JsonDictStore) -> None:
        self._storage = storage
        self._binds: dict[int, int | None] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        binds: dict[int, int | None] = {}
        for raw_chat_id, raw_thread in self._storage.read().items():
            try:
                chat_id = int(raw_chat_id)
            except (TypeError, ValueError):
                LOGGER.warning("Пропущена запись о теме с ключом %r", raw_chat_id)
                continue
            binds[chat_id] = _normalize_thread(None if raw_thread is None else int(raw_thread))
        self._binds = binds

    def is_bound(self, chat_id: int) -> bool:
        with self._lock:
            return chat_id in self._binds

    def thread_of(self, chat_id: int) -> int | None:
        """Id темы-привязки (None — General); None, если привязки нет, тоже None."""
        with self._lock:
            return self._binds[chat_id] if chat_id in self._binds else None

    def is_blocked(self, chat_id: int, thread_id: int | None) -> bool:
        """True, если группа привязана к теме, а сообщение пришло из другой темы."""
        with self._lock:
            if chat_id not in self._binds:
                return False  # привязки нет - работаем как раньше
            return self._binds[chat_id] != _normalize_thread(thread_id)

    def bind(self, chat_id: int, thread_id: int | None) -> bool:
        """Ставит привязку и сохраняет её на диск."""
        with self._lock:
            self._binds[chat_id] = _normalize_thread(thread_id)
        return self.save()

    def unbind(self, chat_id: int) -> bool:
        """Снимает привязку (False — если её и не было) и сохраняет файл."""
        with self._lock:
            existed = self._binds.pop(chat_id, _MISSING) is not _MISSING
        if existed:
            self.save()
        return existed

    def save(self) -> bool:
        with self._lock:
            snapshot = {str(chat_id): thread for chat_id, thread in self._binds.items()}
        return self._storage.write(snapshot)


class GroupMode(str, Enum):
    """Режимы работы бота в группах."""

    MENTION = "mention"  # команды, @упоминания и reply на сообщения бота
    ALL = "all"  # отвечать на все сообщения (нужен выключенный privacy mode)

    @classmethod
    def parse(cls, value: str | None) -> "GroupMode | None":
        """Разбирает аргумент команды, возвращая None при неизвестном значении."""
        if not value:
            return None
        try:
            return cls(value.strip().lower())
        except ValueError:
            return None


class GroupModeStore:
    """Режимы работы бота в группах: ``chat_id -> GroupMode``."""

    def __init__(self, storage: JsonDictStore) -> None:
        self._storage = storage
        self._modes: dict[int, GroupMode] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        modes: dict[int, GroupMode] = {}
        for raw_chat_id, raw_mode in self._storage.read().items():
            try:
                chat_id = int(raw_chat_id)
            except (TypeError, ValueError):
                LOGGER.warning("Пропущена запись о режиме с ключом %r", raw_chat_id)
                continue
            mode = GroupMode.parse(str(raw_mode))
            if mode is None:
                LOGGER.warning("Неизвестный режим группы %r: %r", chat_id, raw_mode)
                continue
            modes[chat_id] = mode
        self._modes = modes

    def get(self, chat_id: int) -> GroupMode:
        """Текущий режим группы (по умолчанию — MENTION)."""
        with self._lock:
            return self._modes.get(chat_id, GroupMode.MENTION)

    def set(self, chat_id: int, mode: GroupMode) -> bool:
        """Меняет режим группы и сохраняет его на диск."""
        with self._lock:
            self._modes[chat_id] = mode
        return self.save()

    def reset(self, chat_id: int) -> bool:
        """Забывает режим группы (например, когда бота удалили из чата)."""
        with self._lock:
            existed = self._modes.pop(chat_id, _MISSING) is not _MISSING
        if existed:
            self.save()
        return existed

    def save(self) -> bool:
        with self._lock:
            snapshot = {
                str(chat_id): mode.value for chat_id, mode in self._modes.items()
            }
        return self._storage.write(snapshot)

