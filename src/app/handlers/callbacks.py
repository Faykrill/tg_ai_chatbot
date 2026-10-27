"""Обработка inline-кнопок (анекдоты и рецепты)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from app import prompts, texts
from app.ai import AIError
from app.keyboards import (
    CALLBACK_PREFIXES,
    JOKE_NEW,
    RECIPE_INGREDIENTS,
    RECIPE_NEW,
    RECIPE_SCALE_2,
    WAIT,
    joke_kb,
    original_kb_for,
    processing_kb,
    recipe_kb,
)
from app.logging_setup import get_logger
from app.messaging import (
    answer_text,
    replace_message,
    send_typing,
    set_keyboard,
)
from app.prompts import Mode
from app.services import Services

__all__ = ["router"]

LOGGER = get_logger(__name__)

router = Router(name="callbacks")


@dataclass(frozen=True, slots=True)
class ButtonAction:
    """Что делаем по нажатию кнопки: какой промпт, режим и клава результата."""

    mode: str
    keyboard: Callable[[], InlineKeyboardMarkup]
    build_prompt: Callable[[str], str]


ACTIONS: Final[dict[str, ButtonAction]] = {
    JOKE_NEW: ButtonAction(
        mode=Mode.JOKE,
        keyboard=joke_kb,
        build_prompt=lambda _text: prompts.joke_prompt(""),
    ),
    RECIPE_NEW: ButtonAction(
        mode=Mode.RECIPE,
        keyboard=recipe_kb,
        build_prompt=prompts.another_recipe_prompt,
    ),
    RECIPE_INGREDIENTS: ButtonAction(
        mode=Mode.CHAT,
        keyboard=recipe_kb,
        build_prompt=prompts.ingredients_prompt,
    ),
    RECIPE_SCALE_2: ButtonAction(
        mode=Mode.CHAT,
        keyboard=recipe_kb,
        build_prompt=prompts.scale_recipe_prompt,
    ),
}


class InflightGuard:
    """Не даёт дважды запустить обработку одного сообщения (защита от дабл-кликов).

    Все проверки происходят внутри event loop без await между проверкой и
    добавлением, поэтому обычное ``set`` здесь потокобезопасен.
    """

    def __init__(self) -> None:
        self._keys: set[tuple[int, int]] = set()

    def acquire(self, key: tuple[int, int]) -> bool:
        if key in self._keys:
            return False
        self._keys.add(key)
        return True

    def release(self, key: tuple[int, int]) -> None:
        self._keys.discard(key)


_GUARD = InflightGuard()


@router.callback_query(F.data.startswith(CALLBACK_PREFIXES))
async def handle_action_button(callback: CallbackQuery, services: Services) -> None:
    """Перегенерирует текст под кнопкой, пока ИИ думает — блокирует кнопки."""
    message = callback.message
    data = callback.data or ""

    # InaccessibleMessage (старое или удалённое сообщение) текстом не обладает.
    if message is None or not hasattr(message, "text"):
        await callback.answer(texts.BUTTON_ERROR, show_alert=True)
        return

    lock_key = (message.chat.id, message.message_id)

    # 1) Это сообщение уже обрабатывается — не запускаем второе выполнение
    if not _GUARD.acquire(lock_key):
        await callback.answer(
            "⏳ Уже думаю! Дождись результата, не нажимай повторно.",
            show_alert=True,
        )
        return

    try:
        action = ACTIONS.get(data)

        # 2) Неизвестная кнопка
        if action is None:
            await callback.answer(texts.UNKNOWN_BUTTON, show_alert=True)
            return

        # 3) Тост: нажатие принято
        await callback.answer("🤔 Принято, ИИ думает...", show_alert=False)

        # 4) Визуально блокируем кнопки на время обработки
        await set_keyboard(message, processing_kb())
        await send_typing(message)

        done = False
        try:
            source = message.text or ""
            result = await services.ai.generate(
                action.build_prompt(source),
                mode=action.mode,
            )
            await replace_message(message, result.text, action.keyboard())
            done = True
        except AIError as exc:
            await answer_text(message, exc.message)
        except Exception:  # noqa: BLE001 - хендлер не должен ронять бота
            LOGGER.exception("Ошибка при обработке кнопки")
            await answer_text(message, texts.BUTTON_ERROR)
        finally:
            # Если что-то пошло не так — возвращаем исходные кнопки
            if not done:
                await set_keyboard(message, original_kb_for(data))
    finally:
        _GUARD.release(lock_key)


@router.callback_query(F.data == WAIT)
async def callback_wait(callback: CallbackQuery) -> None:
    """Кнопка-индикатор «ИИ думает...» — просто напоминаем о терпении."""
    await callback.answer(
        "⏳ Ещё думаю! Как закончу — кнопки вернутся.",
        show_alert=True,
    )
