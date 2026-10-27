"""Отправка ответов: нарезка длинного текста, заглушка, редактирование сообщений.

Все ошибки Telegram API гасятся внутри модуля (пишутся в лог), чтобы сбой
отправки одного куска не ронял обработку всего апдейта.
"""

from __future__ import annotations

from typing import Final

from aiogram.enums import ChatAction
from aiogram.exceptions import AiogramError
from aiogram.types import InlineKeyboardMarkup, Message

from app.chat_rules import is_group_chat
from app.logging_setup import get_logger
from app.texts import EMPTY_ANSWER

__all__ = [
    "answer_text",
    "finalize_placeholder",
    "replace_message",
    "send_long_text",
    "send_thinking",
    "send_typing",
    "set_keyboard",
    "split_text",
]

LOGGER = get_logger(__name__)

#: Лимит текста сообщения в Telegram.
MESSAGE_LIMIT: Final[int] = 4096
#: Запас под служебные символы при редактировании.
EDIT_LIMIT: Final[int] = 4000
#: Размер куска при нарезке длинного ответа.
CHUNK_LIMIT: Final[int] = 3800


def split_text(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Режет текст на куски по абзацам, чтобы не рвать предложения."""
    if not text:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(paragraph) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(
                paragraph[start : start + limit]
                for start in range(0, len(paragraph), limit)
            )
            continue
        if len(current) + len(paragraph) + 2 > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


async def answer_text(
    message: Message,
    text: str,
    *,
    reply: bool | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Отправляет одно сообщение, не падая при ошибках Telegram API.

    ``reply=None`` — в группах отвечать с цитатой, в личке писать рядом.
    При отказе сервера пробует отправить то же сообщение без клавиатуры,
    а затем — без цитаты.
    """
    if reply is None:
        reply = is_group_chat(message)

    attempts: list[tuple[bool, InlineKeyboardMarkup | None]] = [(reply, reply_markup)]
    if reply_markup is not None:
        attempts.append((reply, None))
    if reply:
        attempts.append((False, None))

    for use_reply, markup in attempts:
        try:
            if use_reply:
                return await message.reply(text, reply_markup=markup, parse_mode=None)
            return await message.answer(text, reply_markup=markup, parse_mode=None)
        except AiogramError as exc:
            LOGGER.warning("Не удалось отправить сообщение: %s — пробую иначе", exc)

    LOGGER.error("Сообщение так и не отправлено: %.80s", text)
    return None


async def send_typing(message: Message) -> None:
    """Показывает статус «печатает…» (в нужной теме форум-группы)."""
    try:
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
            message_thread_id=message.message_thread_id,
        )
    except AiogramError as exc:
        LOGGER.debug("Не удалось показать статус «печатает»: %s", exc)


async def send_thinking(message: Message) -> Message | None:
    """Отправляет заглушку «Думаю...» и возвращает её для последующего редактирования."""
    try:
        return await message.answer("⏳ Думаю...")
    except AiogramError as exc:
        LOGGER.warning("Не удалось отправить сообщение-заглушку: %s", exc)
        return None


async def set_keyboard(
    message: Message,
    keyboard: InlineKeyboardMarkup | None,
) -> None:
    """Меняет клавиатуру под сообщением, игнорируя ошибки (например, если оно удалено)."""
    try:
        await message.edit_reply_markup(reply_markup=keyboard)
    except AiogramError as exc:
        LOGGER.warning("Не удалось поменять клавиатуру: %s", exc)


def _markup_for_index(
    index: int,
    last_index: int,
    attach_to: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> InlineKeyboardMarkup | None:
    """Определяет, к какому куску длинного сообщения крепить клавиатуру."""
    if reply_markup is None:
        return None
    if attach_to == "first":
        return reply_markup if index == 0 else None
    return reply_markup if index == last_index else None


async def send_long_text(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    attach_to: str = "last",
    placeholder: Message | None = None,
) -> None:
    """Отправляет длинный ответ кусками.

    Первый кусок пытается заменить собой заглушку «Думаю...»; если не влезло
    или редактирование не удалось — заглушка удаляется, а кусок отправляется
    заново.
    """
    chunks = split_text(text) or [EMPTY_ANSWER]
    last_index = len(chunks) - 1

    for index, chunk in enumerate(chunks):
        markup = _markup_for_index(index, last_index, attach_to, reply_markup)

        if index == 0 and placeholder is not None:
            if len(chunk) <= EDIT_LIMIT:
                try:
                    await placeholder.edit_text(chunk, reply_markup=markup)
                    continue
                except AiogramError as exc:
                    LOGGER.warning("Не удалось отредактировать заглушку: %s", exc)
            try:
                await placeholder.delete()
            except AiogramError as exc:
                LOGGER.debug("Не удалось удалить заглушку: %s", exc)

        await answer_text(
            message,
            chunk,
            reply=index == 0 and is_group_chat(message),
            reply_markup=markup,
        )


async def finalize_placeholder(
    placeholder: Message | None,
    message: Message,
    text: str,
) -> None:
    """Показывает короткое сообщение (обычно ошибку) вместо заглушки «Думаю...»."""
    if placeholder is not None:
        try:
            await placeholder.edit_text(text)
            return
        except AiogramError as exc:
            LOGGER.warning("Не удалось обновить заглушку: %s", exc)
    await answer_text(message, text)


async def replace_message(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Заменяет текст сообщения на месте.

    Если текст не влезает в лимит — удаляет сообщение и шлёт новое по кусочкам
    в той же теме, а клавиатура оказывается на последнем куске.
    """
    if len(text) <= EDIT_LIMIT:
        try:
            await message.edit_text(text, reply_markup=reply_markup)
            return
        except AiogramError as exc:
            LOGGER.warning("Не удалось отредактировать сообщение: %s", exc)

    thread = message.message_thread_id
    kwargs = {"message_thread_id": thread} if thread is not None else {}
    try:
        await message.delete()
    except AiogramError as exc:
        LOGGER.debug("Не удалось удалить сообщение: %s", exc)

    chunks = split_text(text) or [EMPTY_ANSWER]
    last_index = len(chunks) - 1
    for index, chunk in enumerate(chunks):
        try:
            await message.bot.send_message(
                chat_id=message.chat.id,
                text=chunk,
                reply_markup=_markup_for_index(index, last_index, "last", reply_markup),
                parse_mode=None,
                **kwargs,
            )
        except AiogramError as exc:
            LOGGER.error("Не удалось отправить кусок сообщения: %s", exc)
            return

