"""Команды управления ботом: старт, помощь, режимы, темы, память."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app import texts
from app.chat_rules import get_command_args
from app.chat_rules import is_group_chat
from app.filters import TopicAllowed
from app.messaging import answer_text
from app.memory import DialogueKey
from app.services import Services
from app.stores import GroupMode

__all__ = ["router"]

router = Router(name="commands")


@router.message(CommandStart(), TopicAllowed())
async def command_start(message: Message, services: Services) -> None:
    await answer_text(message, texts.START_TEXT)


@router.message(Command("help"), TopicAllowed())
async def command_help(message: Message, services: Services) -> None:
    await answer_text(message, texts.HELP_TEXT)


@router.message(Command("chatmode"), TopicAllowed())
async def command_chatmode(message: Message, services: Services) -> None:
    """Включает режим «отвечать на всё» либо возвращает режим по упоминаниям."""
    if not is_group_chat(message):
        await answer_text(message, texts.CHATMODE_GROUP_ONLY)
        return

    mode = GroupMode.parse(get_command_args(message))
    if mode is None:
        current = services.group_modes.get(message.chat.id)
        await answer_text(
            message,
            texts.CHATMODE_INVALID.format(current=current.value),
        )
        return

    services.group_modes.set(message.chat.id, mode)
    await answer_text(
        message,
        texts.CHATMODE_ALL if mode is GroupMode.ALL else texts.CHATMODE_MENTION,
    )


@router.message(Command("clear"))
async def command_clear(message: Message, services: Services) -> None:
    """Забывает историю диалога в этом чате/теме."""
    key = DialogueKey.from_message(message)
    cleared = services.memory.clear(key)
    await answer_text(
        message,
        texts.CLEARED if cleared else texts.ALREADY_EMPTY,
    )


@router.message(Command("memory"))
async def command_memory(message: Message, services: Services) -> None:
    """Показывает, сколько пар сообщений хранится в памяти."""
    key = DialogueKey.from_message(message)
    await answer_text(
        message,
        texts.MEMORY_FORMAT.format(
            pairs=services.memory.pairs_count(key),
            max_pairs=services.memory.max_pairs,
        ),
    )


@router.message(Command("settopic"))
async def command_settopic(message: Message, services: Services) -> None:
    """Привязывает бота к текущей теме форум-группы."""
    if not is_group_chat(message):
        await answer_text(message, texts.SETTOPIC_GROUP_ONLY)
        return
    if not message.chat.is_forum:
        await answer_text(message, texts.SETTOPIC_FORUM_ONLY)
        return

    services.topics.bind(message.chat.id, message.message_thread_id)
    topic = (
        f"id={message.message_thread_id}"
        if message.message_thread_id is not None
        else texts.GENERAL_TOPIC_NAME
    )
    await answer_text(message, texts.SETTOPIC_OK.format(topic=topic))


@router.message(Command("unsettopic"))
async def command_unsettopic(message: Message, services: Services) -> None:
    """Снимает привязку к теме: бот снова отвечает во всех темах группы."""
    result = texts.TOPIC_UNBOUND if services.topics.unbind(message.chat.id) else texts.TOPIC_NOT_BOUND
    await answer_text(message, result)
