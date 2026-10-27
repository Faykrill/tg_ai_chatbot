import asyncio
import logging
import os
import re

import json
from pathlib import Path

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand
from aiogram.enums import ChatAction

from openai import AsyncOpenAI

# Загружаем переменные из .env
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
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
    },
}

if AI_PROVIDER not in PROVIDERS:
    raise RuntimeError("AI_PROVIDER должен быть: deepseek, qwen, groq или openrouter")

AI_MODEL = AI_MODEL or PROVIDERS[AI_PROVIDER]["default_model"]

client = AsyncOpenAI(
    api_key=AI_API_KEY,
    base_url=PROVIDERS[AI_PROVIDER]["base_url"],
)

router = Router()

# Данные бота (заполняются при запуске), нужны для поиска упоминаний в группах
BOT_USERNAME = ""
BOT_ID = 0

# Режимы работы в группах:
# "mention" (по умолчанию) - отвечает на команды, @упоминания и reply на свои сообщения
# "all" - отвечает на ВСЕ сообщения группы (нужно отключить privacy mode в BotFather)
GROUP_MODES: dict = {}

# Память диалогов: (user_id, chat_id, thread_id) -> список сообщений
DIALOGUES: dict = {}
MAX_HISTORY_PAIRS = 10
MAX_HISTORY_MESSAGES = MAX_HISTORY_PAIRS * 2  # 10 пар = 20 сообщений


def get_history_key(message: types.Message) -> tuple:
    """Формирует уникальный ключ для памяти."""
    user_id = message.from_user.id if message.from_user else message.sender_chat.id
    return (user_id, message.chat.id, message.message_thread_id)


def get_history(message: types.Message) -> list:
    key = get_history_key(message)
    return DIALOGUES.get(key, [])


def save_history(message: types.Message, history: list):
    key = get_history_key(message)
    # Обрезаем историю, если она стала слишком длинной
    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]
    DIALOGUES[key] = history

# Привязка к темам в форум-группах: chat_id -> message_thread_id.
# Если группа есть в этом словаре, бот отвечает ТОЛЬКО в этой теме.
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
        BINDS_FILE.write_text(
            json.dumps(TOPIC_BINDS, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        logging.exception("Не удалось сохранить topics.json")


TOPIC_BINDS: dict = load_binds()


def is_topic_blocked(message: types.Message) -> bool:
    """True, если группа привязана к теме, а сообщение пришло из другой темы."""
    bind = TOPIC_BINDS.get(message.chat.id)
    if bind is None:
        return False  # привязки нет - работаем как раньше
    return message.message_thread_id != bind

SYSTEM_PROMPTS = {
    "chat": (
        "Ты полезный русскоязычный ассистент в Telegram. "
        "Отвечай дружелюбно, понятно и по делу."
        "Не используй форматирование с помощью '*'."
        "Эмодзи используй только при сильной необходимости."
    ),
    "recipe": (
        "Ты опытный шеф-повар. "
        "Пользователь просит рецепт. "
        "Дай рецепт в удобном формате: название, ингредиенты, шаги приготовления. "
        "Если тема не указана, придумай интересный случайный рецепт. "
        "Пиши на русском языке."
        "Используй форматирование знаками только для списков."
        "Пиши только по делу, без лишних вступлений."
    ),
    "joke": (
        "Ты генерируешь анекдоты. "
        "Пользователь просит анекдот. "
        "Выдай один анекдот без объяснений. "
        "Если тема указана, постарайся сделать анекдот на эту тему. "
        "Пиши на русском языке."
    ),
}

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
    """Клавиатура на время обработки: одна кнопка-индикатор."""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⏳ ИИ думает...", callback_data="sys:wait")],
    ])


def original_kb_for(data: str) -> types.InlineKeyboardMarkup:
    """Какая клавиатура должна быть под сообщением с таким callback-префиксом."""
    return joke_kb() if data.startswith("joke:") else recipe_kb()


async def set_keyboard(message: types.Message, kb: types.InlineKeyboardMarkup):
    """Меняет клавиатуру под сообщением, игнорируя ошибки (например, если сообщение удалено)."""
    try:
        await message.edit_reply_markup(reply_markup=kb)
    except Exception as e:
        logging.warning(f"Не удалось поменять клавиатуру: {e}")

def is_group_chat(message: types.Message) -> bool:
    return message.chat.type in ("group", "supergroup")


def get_command_args(message: types.Message) -> str:
    if not message.text:
        return ""
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        return parts[1].strip()
    return ""


def bot_is_mentioned(message: types.Message) -> bool:
    text = message.text or ""
    
    # 1. Самый надёжный способ: через сущности (entities) Telegram
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                # В aiogram 3 у MessageEntity нет .text, вырезаем срезом по offset и length
                mention_text = text[entity.offset : entity.offset + entity.length]
                if mention_text.lower() == "@" + (BOT_USERNAME or "").lower():
                    return True
            elif entity.type == "text_mention":
                # Если упомянули по имени (без @, но с ссылкой на профиль бота)
                if entity.user and entity.user.id == BOT_ID:
                    return True

    # 2. Резервный способ: поиск по тексту (на случай, если entities не сработали)
    if BOT_USERNAME and ("@" + BOT_USERNAME).lower() in text.lower():
        return True
        
    return False


def is_reply_to_bot(message: types.Message) -> bool:
    reply = message.reply_to_message
    if reply is None or reply.from_user is None:
        return False
    return reply.from_user.id == BOT_ID


def strip_mention(text: str) -> str:
    """Убирает @упоминание бота из текста, чтобы не мешало нейросети."""
    if BOT_USERNAME:
        pattern = re.compile(re.escape("@" + BOT_USERNAME), re.IGNORECASE)
        text = pattern.sub("", text)
    return text.strip()


async def ask_ai(user_prompt: str, mode: str = "chat", history: list = None, temperature = 0.7, max_tokens = 8000) -> str:
    system_prompt = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["chat"])
    
    messages = [{"role": "system", "content": system_prompt}]

    # Если есть история и это обычный чат — добавляем её
    if history and mode == "chat":
        messages.extend(history)

    messages.append({"role": "user", "content": user_prompt})

    try:
        response = await client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            temperature= temperature,
            max_tokens=max_tokens, # Увеличенный лимит, как мы делали раньше
        )

        logging.info(f"Токены: вход={response.usage.prompt_tokens}, выход={response.usage.completion_tokens}")

        choice = response.choices[0]
        answer = choice.message.content
        if choice.finish_reason == "length":
            answer += '\n\n⚠️ (Ответ оборвался из-за лимита длины — напиши "продолжи")'
        return answer.strip() if answer else "ИИ вернул пустой ответ."
    except Exception:
        logging.exception("Ошибка запроса к ИИ")
        return (
            "Не получилось получить ответ от ИИ. "
            "Проверь AI_API_KEY, AI_PROVIDER, AI_MODEL и доступ в интернет."
        )


def split_text(text: str, limit: int = 3800) -> list:
    """Режет текст на куски по абзацам, чтобы не рвать предложения."""
    chunks = []
    current = ""
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


async def send_safe_message(message: types.Message, text: str, reply: bool = False, reply_markup=None):
    try:
        if reply:
            await message.reply(text, reply_markup=reply_markup)
        else:
            await message.answer(text, reply_markup=reply_markup)
    except Exception:
        try:
            if reply:
                await message.reply(text, parse_mode=None, reply_markup=reply_markup)
            else:
                await message.answer(text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение: {e}")

async def send_thinking(message: types.Message) -> types.Message:
    """Отправляет сообщение-заглушку 'Думаю...' и возвращает его объект для последующего редактирования."""
    try:
        return await message.answer("⏳ Думаю...")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение-заглушку: {e}")
        return None

async def send_long_message(
    message: types.Message,
    text: str,
    reply_markup=None,
    attach_to: str = "last",
    placeholder: types.Message | None = None,
):
    chunks = split_text(text if text else "Пустой ответ.")
    last = len(chunks) - 1

    # Если есть заглушка — пробуем заменить её первым куском
    if placeholder is not None and chunks:
        first = chunks[0]
        # Кнопки крепим к первому куску, только если он же и последний,
        # либо если явно просили attach_to="first"
        kb_first = None
        if reply_markup is not None and (
            (attach_to == "first") or (attach_to == "last" and last == 0)
        ):
            kb_first = reply_markup

        replaced = False
        if len(first) <= 4000:
            try:
                await placeholder.edit_text(first, reply_markup=kb_first)
                replaced = True
            except Exception as e:
                logging.warning(f"Не удалось отредактировать заглушку: {e}")

        if not replaced:
            # Не влезло или редактирование не удалось — удаляем и шлём заново
            try:
                await placeholder.delete()
            except Exception:
                pass
            await send_safe_message(
                message,
                first,
                reply=(is_group_chat(message)),
                reply_markup=kb_first,
            )

        # Остальные куски — как обычно
        for idx in range(1, len(chunks)):
            kb = None
            if reply_markup is not None and attach_to == "last" and idx == last:
                kb = reply_markup
            await send_safe_message(message, chunks[idx], reply=False, reply_markup=kb)
        return

    # Старое поведение (без заглушки)
    for idx, chunk in enumerate(chunks):
        kb = None
        if reply_markup is not None and (
            (attach_to == "last" and idx == last) or (attach_to == "first" and idx == 0)
        ):
            kb = reply_markup
        await send_safe_message(message, chunk, reply=(idx == 0 and is_group_chat(message)), reply_markup=kb)


async def answer_message(message: types.Message, text: str):
    await send_safe_message(message, text, reply=is_group_chat(message))


@router.message(CommandStart())
async def command_start(message: types.Message):
    if is_topic_blocked(message):
        return
    text = (
        "Привет! Я ИИ-бот.\n\n"
        "Команды:\n"
        "/recipe — рецепт\n"
        "/joke — анекдот\n"
        "/help — помощь\n\n"
        "Или просто напиши мне сообщение, и я отвечу через нейросеть.\n"
        "В группах я отвечаю на команды, @упоминания и ответы на мои сообщения."
    )
    await answer_message(message, text)


@router.message(Command("help"))
async def command_help(message: types.Message):
    if is_topic_blocked(message):
            return
    text = (
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
    )
    await answer_message(message, text)


@router.message(Command("chatmode"))
async def command_chatmode(message: types.Message):
    if is_topic_blocked(message):
            return
    if not is_group_chat(message):
        await answer_message(
            message,
            "Эта команда работает только в группах. В личке я всегда отвечаю на всё.",
        )
        return

    args = get_command_args(message).lower()
    if args not in ("all", "mention"):
        current = GROUP_MODES.get(message.chat.id, "mention")
        await answer_message(
            message,
            f"Использование: /chatmode all или /chatmode mention\nТекущий режим: {current}",
        )
        return

    GROUP_MODES[message.chat.id] = args
    if args == "all":
        await answer_message(
            message,
            "Режим «all»: теперь я отвечаю на каждое сообщение в группе.\n"
            "Важно: в BotFather должен быть отключён privacy mode, иначе я не увижу обычные сообщения.",
        )
    else:
        await answer_message(
            message,
            "Режим «mention»: отвечаю на команды, @упоминания и reply на мои сообщения.",
        )

@router.message(Command("clear"))
async def command_clear(message: types.Message):
    key = get_history_key(message)
    if key in DIALOGUES:
        del DIALOGUES[key]
        await answer_message(message, "🗑 Память очищена. Начнём с чистого листа!")
    else:
        await answer_message(message, "Память и так пуста.")


@router.message(Command("memory"))
async def command_memory(message: types.Message):
    history = get_history(message)
    pairs = len(history) // 2
    await answer_message(
        message, 
        f" В памяти сейчас {pairs} пар сообщений (максимум {MAX_HISTORY_PAIRS})."
    )

@router.message(Command("settopic"))
async def command_settopic(message: types.Message):
    if not is_group_chat(message):
        await answer_message(message, "Эта команда работает только в группах.")
        return
    if not message.chat.is_forum:
        await answer_message(
            message,
            "В этой группе не включены темы. Включи форум-режим в настройках группы.",
        )
        return
    TOPIC_BINDS[message.chat.id] = message.message_thread_id
    save_binds()
    topic_name = message.message_thread_id if message.message_thread_id is not None else "Общая"
    await answer_message(
        message,
        f"Готово! В этой группе я теперь работаю только в этой теме (id={topic_name}). "
        "В остальных темах буду молчать.",
    )


@router.message(Command("unsettopic"))
async def command_unsettopic(message: types.Message):
    if message.chat.id in TOPIC_BINDS:
        del TOPIC_BINDS[message.chat.id]
        save_binds()
        await answer_message(
            message, "Привязка снята: снова отвечаю во всех темах этой группы."
        )
    else:
        await answer_message(
            message, "В этой группе я и так не привязан к конкретной теме."
        )

@router.message(Command("recipe"))
async def command_recipe(message: types.Message):
    if is_topic_blocked(message):
        return
    args = get_command_args(message)
    if args:
        user_prompt = f"Придумай рецепт. Тема или продукты: {args}"
    else:
        user_prompt = "Придумай интересный случайный рецепт."

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    placeholder = await send_thinking(message)

    answer = await ask_ai(user_prompt, mode="recipe", temperature=0.2, max_tokens=5000)
    await send_long_message(message, answer, reply_markup=recipe_kb(), placeholder=placeholder)


@router.message(Command("joke"))
async def command_joke(message: types.Message):
    if is_topic_blocked(message):
        return
    args = get_command_args(message)
    if args:
        user_prompt = f"Расскажи анекдот. Тема: {args}"
    else:
        user_prompt = "Расскажи хороший анекдот."

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    placeholder = await send_thinking(message)

    answer = await ask_ai(user_prompt, mode="joke", temperature=0.1, max_tokens=1500)
    await send_long_message(message, answer, reply_markup=joke_kb(), placeholder=placeholder)

async def replace_message(message: types.Message, text: str, keyboard):
    """Заменяет текст сообщения на месте. Если текст не влезает в лимит — пересоздаёт сообщение."""
    if len(text) <= 4000:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception as e:
            logging.warning(f"Не удалось отредактировать сообщение: {e}")

    # Фолбэк: удаляем старое и шлём заново по кусочкам, кнопки — на последнем
    bot = message.bot
    chat_id = message.chat.id
    thread = message.message_thread_id
    try:
        await message.delete()
    except Exception:
        pass

    chunks = split_text(text)
    last = len(chunks) - 1
    for idx, chunk in enumerate(chunks):
        kwargs = {}
        if thread is not None:
            kwargs["message_thread_id"] = thread
        await bot.send_message(
            chat_id=chat_id,
            text=chunk,
            reply_markup=(keyboard if idx == last else None),
            **kwargs,
        )


# Сообщения, которые прямо сейчас обрабатываются кнопками: (chat_id, message_id).
# Защищает от повторных нажатий, пока ИИ думает.
CALLBACK_LOCKS: set = set()

KNOWN_CALLBACKS = {"joke:new", "rec:new", "rec:ing", "rec:port2"}


@router.callback_query(lambda c: c.data.startswith(("joke:", "rec:")))
async def handle_callback(callback: types.CallbackQuery):
    message = callback.message
    data = callback.data
    lock_key = (message.chat.id, message.message_id)

    # 1) Это сообщение уже обрабатывается - не запускаем второе выполнение
    if lock_key in CALLBACK_LOCKS:
        await callback.answer(
            "⏳ Уже думаю! Дождись результата, не нажимай повторно.",
            show_alert=True,
        )
        return

    # 2) Неизвестная кнопка
    if data not in KNOWN_CALLBACKS:
        await callback.answer("Неизвестная кнопка", show_alert=True)
        return

    # 3) Тост: нажатие принято
    await callback.answer("🤔 Принято, ИИ думает...", show_alert=False)

    CALLBACK_LOCKS.add(lock_key)
    done = False

    # 4) Визуально блокируем кнопки на время обработки
    await set_keyboard(message, processing_kb())

    try:
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
            message_thread_id=message.message_thread_id,
        )

        if data == "joke:new":
            answer = await ask_ai("Расскажи хороший анекдот.", mode="joke")
            await replace_message(message, answer, joke_kb())

        elif data == "rec:new":
            prompt = (
                "Придумай ДРУГОЙ рецепт на ту же тему, что и текст ниже, но не повторяй его:\n"
                f"{message.text[:1500]}"
            )
            answer = await ask_ai(prompt, mode="recipe")
            await replace_message(message, answer, recipe_kb())

        elif data == "rec:ing":
            prompt = (
                f"Вот рецепт:\n{message.text[:3000]}\n\n"
                "Выдели из него только список ингредиентов, без шагов и пояснений."
            )
            answer = await ask_ai(prompt, mode="chat")
            await replace_message(message, answer, recipe_kb())

        elif data == "rec:port2":
            prompt = (
                f"Вот рецепт:\n{message.text[:3000]}\n\n"
                "Пересчитай количества ингредиентов на 2 порции и выдай полный рецепт с новыми количествами."
            )
            answer = await ask_ai(prompt, mode="chat")
            await replace_message(message, answer, recipe_kb())

        done = True

    except Exception:
        logging.exception("Ошибка при обработке кнопки")
        try:
            await message.answer("😕 Не получилось обработать кнопку. Попробуй ещё раз.")
        except Exception:
            pass

    finally:
        # Если что-то пошло не так - возвращаем исходные кнопки
        if not done:
            await set_keyboard(message, original_kb_for(data))
        CALLBACK_LOCKS.discard(lock_key)

@router.callback_query(lambda c: c.data == "sys:wait")
async def callback_wait(callback: types.CallbackQuery):
    await callback.answer(
        "⏳ Ещё думаю! Как закончу — кнопки вернутся.",
        show_alert=True,
    )

@router.message()
async def handle_text(message: types.Message):
    # Блокировка для тем (если есть)
    if is_topic_blocked(message):
        return

    if not message.text:
        if not is_group_chat(message):
            await message.answer("Пока я понимаю только текстовые сообщения.")
        return

    # В группах проверяем, адресовано ли сообщение боту
    if is_group_chat(message):
        mode = GROUP_MODES.get(message.chat.id, "mention")
        mentioned = bot_is_mentioned(message)
        replied = is_reply_to_bot(message)
        
        if mode == "mention" and not (mentioned or replied):
            return

        prompt = strip_mention(message.text) or message.text
    else:
        prompt = message.text

    # === ЛОГИКА ПАМЯТИ ===
    history = get_history(message)
    history.append({"role": "user", "content": prompt})

    await message.bot.send_chat_action(
        chat_id=message.chat.id,
        action=ChatAction.TYPING,
        message_thread_id=message.message_thread_id,
    )

    placeholder = await send_thinking(message)

    answer = await ask_ai(prompt, mode="chat", history=history)

    # Сохраняем ответ бота в историю
    history.append({"role": "assistant", "content": answer})
    save_history(message, history)
    # ====================

    await send_long_message(message, answer, placeholder=placeholder)


async def main():
    global BOT_USERNAME, BOT_ID

    bot = Bot(token=BOT_TOKEN)
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    BOT_ID = me.id
    logging.info(f"Бот запущен: @{BOT_USERNAME} (id={BOT_ID})")

    dp = Dispatcher()
    dp.include_router(router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запуск бота"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="recipe", description="Рецепт"),
            BotCommand(command="joke", description="Анекдот"),
            BotCommand(command="chatmode", description="Режим работы в группе"),
        ]
    )

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())