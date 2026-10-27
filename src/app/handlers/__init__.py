"""Роутеры с обработчиками сообщений и callback-кнопок."""

from __future__ import annotations

from aiogram import Router

from app.handlers import callbacks, chat, commands, errors, generation

__all__ = ["setup_routers"]


def setup_routers() -> Router:
    """Собирает корневой роутер.

    Порядок подключения важен: сначала узкие хендлеры (команды, генерация),
    в конце — catch-all обработчик обычного текста.

    Роутеры модулей живут на уровне модулей (декораторы регистрируют хендлеры
    при импорте), поэтому повторный вызов просто не прицепляет их второй раз.
    """
    root = Router(name="root")
    errors.register(root)
    for module in (commands, generation, callbacks, chat):
        if module.router.parent_router is None:
            root.include_router(module.router)
    return root
