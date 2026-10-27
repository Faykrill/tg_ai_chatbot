"""Сборка Bot и Dispatcher: здесь настраиваются все компоненты бота."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.config import Settings
from app.handlers import setup_routers
from app.keyboards import bot_commands
from app.logging_setup import get_logger
from app.services import Services

__all__ = ["create_bot", "create_dispatcher", "on_shutdown", "on_startup"]

LOGGER = get_logger(__name__)


def create_bot(settings: Settings) -> Bot:
    """Telegram-бот.

    ``parse_mode=None`` — ответы модели отправляются как обычный текст, иначе
    случайные звёздочки и скобки в тексте модели ломали бы отправку.
    """
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=None),
    )


def create_dispatcher(services: Services) -> Dispatcher:
    """Диспетчер со всеми роутерами и хендлерами старта/остановки."""
    dispatcher = Dispatcher()
    dispatcher.include_router(setup_routers())
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    return dispatcher


async def on_startup(bot: Bot, services: Services) -> None:
    """Заполняет данные бота и меню команд."""
    me = await bot.get_me()
    services.identity.update(me)
    await bot.set_my_commands(bot_commands())

    settings = services.settings
    LOGGER.info(
        "Бот запущен: @%s (id=%s)",
        services.identity.username or "-",
        services.identity.user_id,
    )
    LOGGER.info(
        "ИИ: провайдер=%s модель=%s история=%s пар",
        settings.provider.name,
        settings.model,
        services.memory.max_pairs,
    )


async def on_shutdown(services: Services) -> None:
    """Закрывает HTTP-сессию клиента ИИ."""
    await services.aclose()
    LOGGER.info("Бот остановлен")
