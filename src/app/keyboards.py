"""Inline-клавиатуры и список команд меню бота."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from aiogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup

__all__ = [
    "CALLBACK_PREFIXES",
    "JOKE_NEW",
    "ORIGINAL_KEYBOARDS",
    "RECIPE_INGREDIENTS",
    "RECIPE_NEW",
    "RECIPE_SCALE_2",
    "WAIT",
    "bot_commands",
    "joke_kb",
    "original_kb_for",
    "processing_kb",
    "recipe_kb",
]

# === Данные callback-кнопок ===
JOKE_NEW: Final[str] = "joke:new"
RECIPE_NEW: Final[str] = "rec:new"
RECIPE_INGREDIENTS: Final[str] = "rec:ing"
RECIPE_SCALE_2: Final[str] = "rec:port2"
WAIT: Final[str] = "sys:wait"

#: Префиксы callback-данных, которые обрабатывает наш роутер кнопок.
CALLBACK_PREFIXES: Final[tuple[str, ...]] = ("joke:", "rec:")


def joke_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Ещё", callback_data=JOKE_NEW)],
        ]
    )


def recipe_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Другой рецепт", callback_data=RECIPE_NEW)],
            [
                InlineKeyboardButton(
                    text="🛒 Ингредиенты", callback_data=RECIPE_INGREDIENTS
                ),
                InlineKeyboardButton(
                    text="📏 Порции на 2", callback_data=RECIPE_SCALE_2
                ),
            ],
        ]
    )


def processing_kb() -> InlineKeyboardMarkup:
    """Клавиатура на время обработки: одна кнопка-индикатор."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏳ ИИ думает...", callback_data=WAIT)],
        ]
    )


#: callback_data -> «родная» клавиатура сообщения с такой кнопкой.
ORIGINAL_KEYBOARDS: Final[dict[str, Callable[[], InlineKeyboardMarkup]]] = {
    JOKE_NEW: joke_kb,
    RECIPE_NEW: recipe_kb,
    RECIPE_INGREDIENTS: recipe_kb,
    RECIPE_SCALE_2: recipe_kb,
}


def original_kb_for(data: str) -> InlineKeyboardMarkup:
    """Какая клавиатура должна быть под сообщением с таким callback-префиксом."""
    factory = ORIGINAL_KEYBOARDS.get(data)
    if factory is not None:
        return factory()
    return joke_kb() if data.startswith("joke:") else recipe_kb()


def bot_commands() -> list[BotCommand]:
    """Команды, которые показываются в меню Telegram."""
    return [
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="recipe", description="Рецепт"),
        BotCommand(command="joke", description="Анекдот"),
        BotCommand(command="chatmode", description="Режим работы в группе"),
        BotCommand(command="settopic", description="Привязать бота к теме"),
        BotCommand(command="unsettopic", description="Отвязать бота от темы"),
        BotCommand(command="clear", description="Очистить память диалога"),
        BotCommand(command="memory", description="Размер памяти диалога"),
    ]
