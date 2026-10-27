"""Системные промпты, параметры генерации и конструкторы запросов к ИИ."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "DEFAULT_MODE",
    "MODES",
    "Mode",
    "another_recipe_prompt",
    "chat_prompt",
    "ingredients_prompt",
    "joke_prompt",
    "params_for",
    "recipe_prompt",
    "scale_recipe_prompt",
]


class Mode:
    """Названия режимов генерации (каждый со своим системным промптом)."""

    CHAT: Final[str] = "chat"
    RECIPE: Final[str] = "recipe"
    JOKE: Final[str] = "joke"


DEFAULT_MODE: Final[str] = Mode.CHAT


@dataclass(frozen=True, slots=True)
class GenerationParams:
    """Системный промпт + параметры запроса для конкретного режима."""

    system_prompt: str
    temperature: float
    max_tokens: int


MODES: Final[dict[str, GenerationParams]] = {
    Mode.CHAT: GenerationParams(
        system_prompt=(
            "Ты полезный русскоязычный ассистент в Telegram. "
            "Отвечай дружелюбно, понятно и по делу."
            "Не используй форматирование с помощью '*'."
            "Эмодзи используй только при сильной необходимости."
        ),
        temperature=0.7,
        max_tokens=8000,
    ),
    Mode.RECIPE: GenerationParams(
        system_prompt=(
            "Ты опытный шеф-повар. "
            "Пользователь просит рецепт. "
            "Дай рецепт в удобном формате: название, ингредиенты, шаги приготовления. "
            "Если тема не указана, придумай интересный случайный рецепт. "
            "Пиши на русском языке."
            "Используй форматирование знаками только для списков."
            "Пиши только по делу, без лишних вступлений."
        ),
        temperature=0.2,
        max_tokens=5000,
    ),
    Mode.JOKE: GenerationParams(
        system_prompt=(
            "Ты генерируешь анекдоты. "
            "Пользователь просит анекдот. "
            "Выдай один анекдот без объяснений. "
            "Если тема указана, постарайся сделать анекдот на эту тему. "
            "Пиши на русском языке."
        ),
        temperature=0.1,
        max_tokens=1500,
    ),
}


def params_for(mode: str) -> GenerationParams:
    """Возвращает параметры режима, падая на обычный чат при неизвестном режиме."""
    return MODES.get(mode, MODES[DEFAULT_MODE])


def clip(text: str, limit: int) -> str:
    """Обрезает исходный текст сообщения, чтобы не раздувать промпт."""
    return (text or "").strip()[:limit]


def chat_prompt(text: str) -> str:
    """Запрос для обычного чата (без обёрток — как в старой версии)."""
    return text


def recipe_prompt(topic: str) -> str:
    if topic:
        return f"Придумай рецепт. Тема или продукты: {topic}"
    return "Придумай интересный случайный рецепт."


def joke_prompt(topic: str) -> str:
    if topic:
        return f"Расскажи анекдот. Тема: {topic}"
    return "Расскажи хороший анекдот."


def another_recipe_prompt(current_text: str, limit: int = 1500) -> str:
    return (
        "Придумай ДРУГОЙ рецепт на ту же тему, что и текст ниже, но не повторяй его:\n"
        f"{clip(current_text, limit)}"
    )


def ingredients_prompt(current_text: str, limit: int = 3000) -> str:
    return (
        f"Вот рецепт:\n{clip(current_text, limit)}\n\n"
        "Выдели из него только список ингредиентов, без шагов и пояснений."
    )


def scale_recipe_prompt(current_text: str, portions: int = 2, limit: int = 3000) -> str:
    return (
        f"Вот рецепт:\n{clip(current_text, limit)}\n\n"
        f"Пересчитай количества ингредиентов на {portions} порции "
        "и выдай полный рецепт с новыми количествами."
    )
