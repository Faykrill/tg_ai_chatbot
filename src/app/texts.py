"""Тексты, которые видит пользователь, и ответы на ошибки."""

from __future__ import annotations

from typing import Final

__all__ = [
    "AI_UNAVAILABLE",
    "ALREADY_EMPTY",
    "BUTTON_ERROR",
    "CHATMODE_ALL",
    "CHATMODE_GROUP_ONLY",
    "CHATMODE_INVALID",
    "CHATMODE_MENTION",
    "CLEARED",
    "EMPTY_ANSWER",
    "GENERAL_TOPIC_NAME",
    "HELP_TEXT",
    "MEMORY_FORMAT",
    "NOT_TEXT",
    "SETTOPIC_FORUM_ONLY",
    "SETTOPIC_GROUP_ONLY",
    "SETTOPIC_OK",
    "START_TEXT",
    "TOPIC_NOT_BOUND",
    "TOPIC_UNBOUND",
    "TRUNCATED_NOTE",
    "UNKNOWN_BUTTON",
]

START_TEXT: Final[str] = (
    "Привет! Я ИИ-бот.\n\n"
    "Команды:\n"
    "/recipe — рецепт\n"
    "/joke — анекдот\n"
    "/help — помощь\n\n"
    "Или просто напиши мне сообщение, и я отвечу через нейросеть.\n"
    "В группах я отвечаю на команды, @упоминания и ответы на мои сообщения."
)

HELP_TEXT: Final[str] = (
    "Что я умею:\n"
    "/recipe — придумать рецепт\n"
    "/recipe курица и рис — рецепт по запросу\n"
    "/joke — рассказать анекдот\n"
    "/joke про программистов — анекдот на тему\n"
    "Просто текст — обычный чат с ИИ.\n\n"
    "В группах:\n"
    "— отвечу, если написать команду или упомянуть меня через @\n"
    "— отвечу, если ответить (reply) на моё сообщение\n"
    "/chatmode all — отвечать на все сообщения (нужен отключённый privacy mode)\n"
    "/chatmode mention — отвечать только на команды, @упоминания и reply\n\n"
    "В группах с темами:\n"
    "/settopic — привязать бота к текущей теме\n"
    "/unsettopic — отвязать бота от темы\n\n"
    "Память диалога:\n"
    "/clear — очистить память диалога\n"
    "/memory — узнать размер памяти"
)

# === Ошибки и служебные ответы ===
AI_UNAVAILABLE: Final[str] = (
    "Не получилось получить ответ от ИИ. "
    "Проверь AI_API_KEY, AI_PROVIDER, AI_MODEL и доступ в интернет."
)
EMPTY_ANSWER: Final[str] = "ИИ вернул пустой ответ."
BUTTON_ERROR: Final[str] = "😕 Не получилось обработать кнопку. Попробуй ещё раз."
UNKNOWN_BUTTON: Final[str] = "Неизвестная кнопка"
NOT_TEXT: Final[str] = "Пока я понимаю только текстовые сообщения."
TRUNCATED_NOTE: Final[str] = (
    "\n\n⚠️ (Ответ оборвался из-за лимита длины — напиши \"продолжи\")"
)

# === Режимы работы в группах ===
CHATMODE_GROUP_ONLY: Final[str] = (
    "Эта команда работает только в группах. В личке я всегда отвечаю на всё."
)
CHATMODE_INVALID: Final[str] = (
    "Использование: /chatmode all или /chatmode mention\nТекущий режим: {current}"
)
CHATMODE_ALL: Final[str] = (
    "Режим «all»: теперь я отвечаю на каждое сообщение в группе.\n"
    "Важно: в BotFather должен быть отключён privacy mode, "
    "иначе я не увижу обычные сообщения."
)
CHATMODE_MENTION: Final[str] = (
    "Режим «mention»: отвечаю на команды, @упоминания и reply на мои сообщения."
)

# === Темы форум-групп ===
SETTOPIC_GROUP_ONLY: Final[str] = "Эта команда работает только в группах."
SETTOPIC_FORUM_ONLY: Final[str] = (
    "В этой группе не включены темы. Включи форум-режим в настройках группы."
)
SETTOPIC_OK: Final[str] = (
    "Готово! В этой группе я теперь работаю только в этой теме ({topic}). "
    "В остальных темах буду молчать."
)
TOPIC_UNBOUND: Final[str] = "Привязка снята: снова отвечаю во всех темах этой группы."
TOPIC_NOT_BOUND: Final[str] = "В этой группе я и так не привязан к конкретной теме."
GENERAL_TOPIC_NAME: Final[str] = "General"

# === Память диалога ===
CLEARED: Final[str] = "🗑 Память очищена. Начнём с чистого листа!"
ALREADY_EMPTY: Final[str] = "Память и так пуста."
MEMORY_FORMAT: Final[str] = (
    " В памяти сейчас {pairs} пар сообщений (максимум {max_pairs})."
)
