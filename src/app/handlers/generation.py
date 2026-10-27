"""Команды генерации контента: /recipe и /joke."""

from __future__ import annotations

from collections.abc import Callable

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, Message

from app import prompts
from app.ai import AIError
from app.chat_rules import get_command_args
from app.filters import TopicAllowed
from app.keyboards import joke_kb, recipe_kb
from app.messaging import (
    finalize_placeholder,
    send_long_text,
    send_thinking,
    send_typing,
)
from app.prompts import Mode
from app.services import Services

__all__ = ["router"]

router = Router(name="generation")


async def generate_with_keyboard(
    message: Message,
    services: Services,
    *,
    prompt: str,
    mode: str,
    keyboard: Callable[[], InlineKeyboardMarkup],
) -> None:
    """Общий сценарий: статус «печатает», заглушка, ответ модели с кнопками."""
    await send_typing(message)
    placeholder = await send_thinking(message)

    try:
        result = await services.ai.generate(prompt, mode=mode)
    except AIError as exc:
        await finalize_placeholder(placeholder, message, exc.message)
        return

    await send_long_text(
        message,
        result.text,
        reply_markup=keyboard(),
        placeholder=placeholder,
    )


@router.message(Command("recipe"), TopicAllowed())
async def command_recipe(message: Message, services: Services) -> None:
    """Рецепт по запросу или случайный, если тема не указана."""
    await generate_with_keyboard(
        message,
        services,
        prompt=prompts.recipe_prompt(get_command_args(message)),
        mode=Mode.RECIPE,
        keyboard=recipe_kb,
    )


@router.message(Command("joke"), TopicAllowed())
async def command_joke(message: Message, services: Services) -> None:
    """Анекдот по теме или обычный, если тема не указана."""
    await generate_with_keyboard(
        message,
        services,
        prompt=prompts.joke_prompt(get_command_args(message)),
        mode=Mode.JOKE,
        keyboard=joke_kb,
    )
