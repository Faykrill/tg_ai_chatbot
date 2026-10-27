"""
ИИ-Telegram-бот: рецепты, анекдоты и диалог с памятью.
Логические секции: конфиг -> хранилище -> ИИ -> Telegram-хелперы -> обработчики -> запуск.
"""

import asyncio
import functools
import json
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

from aiogram import Bot, Dispatcher, Router, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand
from aiogram.dispatcher.middlewares.base import BaseMiddleware

# ======================================================================
# 1. КОНФИГУРАЦИЯ
# ======================================================================

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
AI_PROVIDER = os.getenv("AI_PROVIDER", "deepseek").lower()
AI_API_KEY = os.getenv("AI_API_KEY")
AI_MODEL = os.getenv("AI_MODEL")

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Добавь его в .env")
if not AI_API_KEY:
    raise RuntimeError("Не задан AI_API_KEY. Добавь его в .env")

PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "default_model": "llama-3.3-70b-versatile"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "default_model": "meta-llama/llama-3.3-70b-instruct:free"},
}

if AI_PROVIDER not in PROVIDERS:
    raise RuntimeError("AI_PROVIDER должен быть: deepseek, qwen, groq или openrouter")

AI_MODEL = AI_MODEL or PROVIDERS[AI_PROVIDER]["default_model"]

# Параметры генерации для каждого режима (температура, лимит токенов)
MODE_PARAMS = {
    "chat": {"temperature": 0.7, "max_tokens": 8000},
    "recipe": {"temperature": 0.2, "max_tokens": 5000},
    "joke": {"temperature": 0.1, "max_tokens": 1500},
}
DEFAULT_PARAMS = {"temperature": 0.7, "max_tokens": 8000}

# Лимиты Telegram и настройки памяти
TG_MESSAGE_LIMIT = 4096
CHUNK_LIMIT = 3800
MAX_HISTORY_PAIRS = 10
MAX_HISTORY_MESSAGES = MAX_HISTORY_PAIRS * 2

SYSTEM_PROMPTS = {
    "chat": (
        "Ты полезный русскоязычный ассистент в Telegram. "
        "Отвечай дружелюбно, понятно и по делу. "
        "Не используй форматирование с помощью '*'. "
        "Эмодзи используй только при сильной необходимости."
    ),
    "recipe": (
        "Ты опытный шеф-повар. Пользователь просит рецепт. "
        "Дай рецепт в удобном формате: название, ингредиенты, шаги приготовления. "
        "Если тема не указана, придумай интересный случайный рецепт. "
        "Пиши на русском языке. "
        "Используй форматирование знаками только для списков. "
        "Пиши только по делу, без лишних вступлений."
    ),
    "joke": (
        "Ты генерируешь анекдоты. Пользователь просит анекдот. "
        "Выдай один анекдот без объяснений. "
        "Если тема указана, постарайся сделать анекдот на эту тему. "
        "Пиши на русском языке."
    ),
}

client = AsyncOpenAI(
    api_key=AI_API_KEY,
    base_url=PROVIDERS[AI_PROVIDER]["base_url"],
)

router = Router()

# ======================================================================
# ОГРАНИЧЕНИЕ ДОСТУПА: белые списки пользователей и чатов
# ======================================================================

def _parse_ids(raw: str) -> set:
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip()}


ALLOWED_USER_IDS = _parse_ids(os.getenv("ALLOWED_USER_IDS", ""))
ALLOWED_CHAT_IDS = _parse_ids(os.getenv("ALLOWED_CHAT_IDS", ""))

if not ALLOWED_USER_IDS and not ALLOWED_CHAT_IDS:
    logging.warning(
        "Списки доступа пусты: бот ОТКРЫТ для всех! "
        "Задай ALLOWED_USER_IDS в .env, чтобы закрыть доступ."
    )


def _event_user_and_chat(event):
    user = getattr(event, "from_user", None)
    chat = getattr(event, "chat", None) or getattr(getattr(event, "message", None), "chat", None)
    return user, chat


def is_access_allowed(event) -> bool:
    if not ALLOWED_USER_IDS and not ALLOWED_CHAT_IDS:
        return True  # открытый режим
    user, chat = _event_user_and_chat(event)
    if user is not None and user.id in ALLOWED_USER_IDS:
        return True
    if chat is not None and chat.id in ALLOWED_CHAT_IDS:
        return True
    return False


class AccessMiddleware(BaseMiddleware):
    """Не пропускает события от посторонних ни в один обработчик."""

    async def __call__(self, handler, event, data):
        if is_access_allowed(event):
            return await handler(event, data)

        user, chat = _event_user_and_chat(event)
        logging.warning(
            f"Доступ запрещён: user={user.id if user else '?'} ({user.full_name if user else '?'}), "
            f"chat={chat.id if chat else '?'}"
        )

        # В личке вежливо отказываем, в группах молчим, кнопки гасим тостом
        try:
            if isinstance(event, types.CallbackQuery):
                await event.answer("🔒 Нет доступа", show_alert=True)
            elif chat is not None and chat.type == "private":
                await event.answer("🔒 Это приватный бот. Доступ только по белому списку владельца.")
        except Exception:
            pass
        return  # обработчик не вызывается


router.message.middleware(AccessMiddleware())
router.callback_query.middleware(AccessMiddleware())

# Данные, заполняемые при запуске
BOT_USERNAME = ""
BOT_ID = 0

# Режимы работы в группах: "mention" (по умолчанию) или "all"
GROUP_MODES: dict = {}

# Память диалогов: (user_id, chat_id, thread_id) -> список сообщений
DIALOGUES: dict = {}

# Сообщения, которые прямо сейчас обрабатываются кнопками: (chat_id, message_id)
CALLBACK_LOCKS: set = set()


# ======================================================================
# 2. ХРАНИЛИЩЕ: привязка к темам и память диалогов
# ======================================================================

BINDS_FILE = Path(__file__).with_name("topics.json")


def load_binds() -> dict:
    if BINDS_FILE.exists():
        try:
            data = json.loads(BINDS_FILE.read_text(encoding="utf-8"))
            return {int(k): v for k, v in data.items()}
        except Exception:
            logging.exception("Не удалось прочитать topics.json")
    return {}


def save_binds() -> None:
    try:
        BINDS_FILE.write_text(json.dumps(TOPIC_BINDS, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logging.exception("Не удалось сохранить topics.json")


TOPIC_BINDS: dict = load_binds()


def is_topic_blocked(message: types.Message) -> bool:
    """True, если группа привязана к теме, а сообщение пришло из другой темы."""
    bind = TOPIC_BINDS.get(message.chat.id)
    if bind is None:
        return False
    return message.message_thread_id != bind


def get_history_key(message: types.Message) -> tuple:
    """Уникальный ключ памяти: пользователь + чат + тема."""
    if message.from_user is not None:
        user_id = message.from_user.id
    elif message.sender_chat is not None:
        user_id = message.sender_chat.id
    else:
        user_id = 0
    return (user_id, message.chat.id, message.message_thread_id)


def get_history(message: types.Message) -> list:
    return DIALOGUES.get(get_history_key(message), [])


def save_history(message: types.Message, history: list) -> None:
    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]
    DIALOGUES[get_history_key(message)] = history


def clear_history(message: types.Message) -> bool:
    key = get_history_key(message)
    if key in DIALOGUES:
        del DIALOGUES[key]
        return True
    return False


# ======================================================================
# 3. ЗАПРОСЫ К ИИ
# ======================================================================

async def ask_ai(user_prompt: str, mode: str = "chat", history: list | None = None) -> str:
    params = MODE_PARAMS.get(mode, DEFAULT_PARAMS)
    messages = [{"role": "system", "content": SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["chat"])}]
    if history and mode == "chat":
        messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})

    try:
        response = await client.chat.completions.create(model=AI_MODEL, messages=messages, **params)
        if response.usage:
            logging.info(
                "[%s] Токены: вход=%s, выход=%s",
                AI_MODEL, response.usage.prompt_tokens, response.usage.completion_tokens,
            )
        choice = response.choices[0]
        answer = choice.message.content or ""
        if choice.finish_reason == "length":
            answer += '\n\n⚠️ (Ответ оборвался из-за лимита длины — напиши "продолжи")'
        return answer.strip() or "ИИ вернул пустой ответ."
    except Exception:
        logging.exception("Ошибка запроса к ИИ")
        return "Не получилось получить ответ от ИИ. Проверь ключ и доступ в интернет."


# ======================================================================
# 4. TELEGRAM-ХЕЛПЕРЫ: проверки, клавиатуры, отправка
# ======================================================================

def is_group_chat(message: types.Message) -> bool:
    return message.chat.type in ("group", "supergroup")


def get_command_args(message: types.Message) -> str:
    if not message.text:
        return ""
    parts = message.text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def bot_is_mentioned(message: types.Message) -> bool:
    text = message.text or ""
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mention_text = text[entity.offset : entity.offset + entity.length]
                if mention_text.lower() == "@" + (BOT_USERNAME or "").lower():
                    return True
            elif entity.type == "text_mention":
                if entity.user and entity.user.id == BOT_ID:
                    return True
    return bool(BOT_USERNAME) and ("@" + BOT_USERNAME).lower() in text.lower()


def is_reply_to_bot(message: types.Message) -> bool:
    reply = message.reply_to_message
    return bool(reply and reply.from_user and reply.from_user.id == BOT_ID)


def strip_mention(text: str) -> str:
    if BOT_USERNAME:
        pattern = re.compile(re.escape("@" + BOT_USERNAME), re.IGNORECASE)
        text = pattern.sub("", text)
    return text.strip()


def joke_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎲 Ещё", callback_data="joke:new")],
    ])


def recipe_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔄 Другой рецепт", callback_data="rec:new")],
        [
            types.InlineKeyboardButton(text="🛒 Ингредиенты", callback_data="rec:ing"),
            types.InlineKeyboardButton(text="📏 Порции на 2", callback_data="rec:port2"),
        ],
    ])


def processing_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⏳ ИИ думает...", callback_data="sys:wait")],
    ])


def kb_for_mode(mode: str) -> types.InlineKeyboardMarkup:
    return joke_kb() if mode == "joke" else recipe_kb()


async def set_keyboard(message: types.Message, kb: types.InlineKeyboardMarkup) -> None:
    try:
        await message.edit_reply_markup(reply_markup=kb)
    except Exception as e:
        logging.warning(f"Не удалось поменять клавиатуру: {e}")


def split_text(text: str, limit: int = CHUNK_LIMIT) -> list:
    """Режет текст на куски по абзацам, чтобы не рвать предложения."""
    chunks, current = [], ""
    for paragraph in text.split("\n\n"):
        if len(paragraph) > limit:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(paragraph), limit):
                chunks.append(paragraph[i : i + limit])
            continue
        if len(current) + len(paragraph) + 2 > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


async def send_safe_message(message: types.Message, text: str, reply: bool = False, reply_markup=None) -> None:
    """Отправка с автоматическим учётом темы (aiogram сам подставит message_thread_id)."""
    try:
        if reply:
            await message.reply(text, reply_markup=reply_markup)
        else:
            await message.answer(text, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение: {e}")


async def send_thinking(message: types.Message) -> types.Message | None:
    """Заглушка 'Думаю...'. В группах отправляется reply, чтобы сохранить связь с вопросом."""
    try:
        if is_group_chat(message):
            return await message.reply("⏳ Думаю...")
        return await message.answer("⏳ Думаю...")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение-заглушку: {e}")
        return None


async def send_long_message(
    message: types.Message,
    text: str,
    reply_markup=None,
    placeholder: types.Message | None = None,
) -> None:
    chunks = split_text(text or "Пустой ответ.")
    last = len(chunks) - 1

    # Если есть заглушка — заменяем её первым куском
    if placeholder is not None:
        kb_first = reply_markup if (last == 0) else None
        replaced = False
        if len(chunks[0]) <= TG_MESSAGE_LIMIT:
            try:
                await placeholder.edit_text(chunks[0], reply_markup=kb_first)
                replaced = True
            except Exception as e:
                logging.warning(f"Не удалось отредактировать заглушку: {e}")
        if not replaced:
            try:
                await placeholder.delete()
            except Exception:
                pass
            await send_safe_message(message, chunks[0], reply=is_group_chat(message), reply_markup=kb_first)
        for idx in range(1, len(chunks)):
            kb = reply_markup if idx == last else None
            await send_safe_message(message, chunks[idx], reply_markup=kb)
        return

    # Обычный режим без заглушки
    for idx, chunk in enumerate(chunks):
        kb = reply_markup if idx == last else None
        await send_safe_message(message, chunk, reply=(idx == 0 and is_group_chat(message)), reply_markup=kb)


async def answer_message(message: types.Message, text: str) -> None:
    await send_safe_message(message, text, reply=is_group_chat(message))


async def replace_message(message: types.Message, text: str, keyboard) -> None:
    """Заменяет текст сообщения на месте; если не влезает — пересоздаёт по кускам."""
    if len(text) <= TG_MESSAGE_LIMIT:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception as e:
            logging.warning(f"Не удалось отредактировать сообщение: {e}")

    try:
        await message.delete()
    except Exception:
        pass

    chunks = split_text(text)
    last = len(chunks) - 1
    for idx, chunk in enumerate(chunks):
        kwargs = {}
        if message.message_thread_id is not None:
            kwargs["message_thread_id"] = message.message_thread_id
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=chunk,
            reply_markup=(keyboard if idx == last else None),
            **kwargs,
        )


async def run_generation(message: types.Message, mode: str, user_prompt: str, keyboard=None) -> None:
    """Общий пайплайн: typing -> заглушка -> запрос к ИИ -> отправка ответа."""
    await message.bot.send_chat_action(
        chat_id=message.chat.id,
        action=ChatAction.TYPING,
        message_thread_id=message.message_thread_id,
    )
    placeholder = await send_thinking(message)
    answer = await ask_ai(user_prompt, mode=mode)
    await send_long_message(message, answer, reply_markup=keyboard, placeholder=placeholder)


def topic_guard(func):
    """Декоратор: игнорирует сообщения из непривязанных тем форума."""
    @functools.wraps(func)
    async def wrapper(message: types.Message, *args, **kwargs):
        if is_topic_blocked(message):
            return None
        return await func(message, *args, **kwargs)
    return wrapper


# ======================================================================
# 5. ОБРАБОТЧИКИ: команды
# ======================================================================

@router.message(CommandStart())
@topic_guard
async def command_start(message: types.Message):
    await answer_message(message, (
        "Привет! Я ИИ-бот.\n\n"
        "Команды:\n"
        "/recipe — рецепт\n"
        "/joke — анекдот\n"
        "/help — помощь\n\n"
        "Или просто напиши мне сообщение, и я отвечу через нейросеть.\n"
        "В группах я отвечаю на команды, @упоминания и ответы на мои сообщения."
    ))


@router.message(Command("help"))
@topic_guard
async def command_help(message: types.Message):
    await answer_message(message, (
        "Что я умею:\n"
        "/recipe — придумать рецепт\n"
        "/recipe курица и рис — рецепт по запросу\n"
        "/joke — рассказать анекдот\n"
        "/joke про программистов — анекдот на тему\n"
        "Просто текст — обычный чат с ИИ.\n\n"
        "В группах:\n"
        "— отвечу, если написать команду или упомянуть меня через @\n"
        "— отвечу, если ответить (reply) на моё сообщение\n"
        "В группах с темами:\n"
        "/settopic — привязать бота к текущей теме\n"
        "/unsettopic — отвязать бота от темы\n"
        "/clear — очистить память диалога\n"
        "/memory — узнать размер памяти\n"
    ))

@router.message(Command("myid"))
async def command_myid(message: types.Message):
    await answer_message(
        message,
        f"Твой ID: {message.from_user.id}\nID этого чата: {message.chat.id}",
    )

@router.message(Command("chatmode"))
async def command_chatmode(message: types.Message):
    if not is_group_chat(message):
        await answer_message(message, "Эта команда работает только в группах. В личке я всегда отвечаю на всё.")
        return

    args = get_command_args(message).lower()
    if args not in ("all", "mention"):
        current = GROUP_MODES.get(message.chat.id, "mention")
        await answer_message(message, f"Использование: /chatmode all или /chatmode mention\nТекущий режим: {current}")
        return

    GROUP_MODES[message.chat.id] = args
    if args == "all":
        await answer_message(message, (
            "Режим «all»: теперь я отвечаю на каждое сообщение в группе.\n"
            "Важно: в BotFather должен быть отключён privacy mode, иначе я не увижу обычные сообщения."
        ))
    else:
        await answer_message(message, "Режим «mention»: отвечаю на команды, @упоминания и reply на мои сообщения.")


@router.message(Command("clear"))
@topic_guard
async def command_clear(message: types.Message):
    if clear_history(message):
        await answer_message(message, "🗑 Память очищена. Начнём с чистого листа!")
    else:
        await answer_message(message, "Память и так пуста.")


@router.message(Command("memory"))
@topic_guard
async def command_memory(message: types.Message):
    pairs = len(get_history(message)) // 2
    await answer_message(message, f"🧠 В памяти сейчас {pairs} пар сообщений (максимум {MAX_HISTORY_PAIRS}).")


@router.message(Command("settopic"))
async def command_settopic(message: types.Message):
    if not is_group_chat(message):
        await answer_message(message, "Эта команда работает только в группах.")
        return
    if not message.chat.is_forum:
        await answer_message(message, "В этой группе не включены темы. Включи форум-режим в настройках группы.")
        return
    TOPIC_BINDS[message.chat.id] = message.message_thread_id
    save_binds()
    topic_name = message.message_thread_id if message.message_thread_id is not None else "Общая"
    await answer_message(message, (
        f"Готово! В этой группе я теперь работаю только в этой теме (id={topic_name}). "
        "В остальных темах буду молчать."
    ))


@router.message(Command("unsettopic"))
async def command_unsettopic(message: types.Message):
    if message.chat.id in TOPIC_BINDS:
        del TOPIC_BINDS[message.chat.id]
        save_binds()
        await answer_message(message, "Привязка снята: снова отвечаю во всех темах этой группы.")
    else:
        await answer_message(message, "В этой группе я и так не привязан к конкретной теме.")


@router.message(Command("recipe"))
@topic_guard
async def command_recipe(message: types.Message):
    args = get_command_args(message)
    prompt = f"Придумай рецепт. Тема или продукты: {args}" if args else "Придумай интересный случайный рецепт."
    await run_generation(message, "recipe", prompt, keyboard=recipe_kb())


@router.message(Command("joke"))
@topic_guard
async def command_joke(message: types.Message):
    args = get_command_args(message)
    prompt = f"Расскажи анекдот. Тема: {args}" if args else "Расскажи хороший анекдот."
    await run_generation(message, "joke", prompt, keyboard=joke_kb())


# ======================================================================
# 6. ОБРАБОТЧИКИ: кнопки (callback)
# ======================================================================

def _prompt_joke_new(text: str) -> tuple:
    return "Расскажи хороший анекдот.", "joke"


def _prompt_rec_new(text: str) -> tuple:
    return ("Придумай ДРУГОЙ рецепт на ту же тему, что и текст ниже, но не повторяй его:\n" + text[:1500]), "recipe"


def _prompt_rec_ing(text: str) -> tuple:
    return (f"Вот рецепт:\n{text[:3000]}\n\nВыдели из него только список ингредиентов, без шагов и пояснений."), "chat"


def _prompt_rec_port2(text: str) -> tuple:
    return (f"Вот рецепт:\n{text[:3000]}\n\nПересчитай количества ингредиентов на 2 порции и выдай полный рецепт с новыми количествами."), "chat"


CALLBACK_ROUTES = {
    "joke:new": _prompt_joke_new,
    "rec:new": _prompt_rec_new,
    "rec:ing": _prompt_rec_ing,
    "rec:port2": _prompt_rec_port2,
}


@router.callback_query(lambda c: c.data in CALLBACK_ROUTES)
async def handle_callback(callback: types.CallbackQuery):
    message = callback.message
    data = callback.data
    lock_key = (message.chat.id, message.message_id)

    if lock_key in CALLBACK_LOCKS:
        await callback.answer("⏳ Уже думаю! Дождись результата, не нажимай повторно.", show_alert=True)
        return

    await callback.answer("🤔 Принято, ИИ думает...", show_alert=False)
    CALLBACK_LOCKS.add(lock_key)
    done = False
    await set_keyboard(message, processing_kb())

    try:
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
            message_thread_id=message.message_thread_id,
        )
        prompt, mode = CALLBACK_ROUTES[data](message.text or "")
        answer = await ask_ai(prompt, mode=mode)
        await replace_message(message, answer, kb_for_mode(mode))
        done = True
    except Exception:
        logging.exception("Ошибка при обработке кнопки")
        try:
            await message.answer("😕 Не получилось обработать кнопку. Попробуй ещё раз.")
        except Exception:
            pass
    finally:
        if not done:
            await set_keyboard(message, kb_for_mode(_mode_of(data)))
        CALLBACK_LOCKS.discard(lock_key)


def _mode_of(data: str) -> str:
    return "joke" if data.startswith("joke:") else "recipe"


@router.callback_query(lambda c: c.data == "sys:wait")
async def callback_wait(callback: types.CallbackQuery):
    await callback.answer("⏳ Ещё думаю! Как закончу — кнопки вернутся.", show_alert=True)


# ======================================================================
# 7. ОБРАБОТЧИКИ: обычный текст с памятью
# ======================================================================

@router.message()
@topic_guard
async def handle_text(message: types.Message):
    if not message.text:
        if not is_group_chat(message):
            await message.answer("Пока я понимаю только текстовые сообщения.")
        return

    if is_group_chat(message):
        mode = GROUP_MODES.get(message.chat.id, "mention")
        if mode == "mention" and not (bot_is_mentioned(message) or is_reply_to_bot(message)):
            return
        prompt = strip_mention(message.text) or message.text
    else:
        prompt = message.text

    history = get_history(message)
    history.append({"role": "user", "content": prompt})

    placeholder = await send_thinking(message)
    answer = await ask_ai(prompt, mode="chat", history=history)

    history.append({"role": "assistant", "content": answer})
    save_history(message, history)

    await send_long_message(message, answer, placeholder=placeholder)


# ======================================================================
# 8. ЗАПУСК
# ======================================================================

async def main():
    global BOT_USERNAME, BOT_ID

    bot = Bot(token=BOT_TOKEN)
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    BOT_ID = me.id
    logging.info(f"Бот запущен: @{BOT_USERNAME} (id={BOT_ID})")

    dp = Dispatcher()
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="recipe", description="Рецепт"),
        BotCommand(command="joke", description="Анекдот"),
        BotCommand(command="chatmode", description="Режим работы в группе"),
    ])

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())