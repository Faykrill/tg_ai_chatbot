"""Точка входа Telegram ИИ-бота.

Весь код вынесен в пакет :mod:`app`, здесь только сборка зависимостей и запуск
long polling-а.

Запуск:
    python src/main.py              # локально, из корня проекта
    docker compose up --build       # в контейнере
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Позволяет запускать файл и как скрипт (python src/main.py), и как модуль
# (python -m src.main) — каталог src/ должен быть в sys.path.
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.bootstrap import create_bot, create_dispatcher  # noqa: E402
from app.config import ConfigError, load_settings  # noqa: E402
from app.logging_setup import get_logger, setup_logging  # noqa: E402
from app.services import Services  # noqa: E402

# Код возврата по sysexits.h — удобно отличать проблемы конфигурации в логах хоста.
EXIT_CONFIG_ERROR = 78
EXIT_INTERRUPTED = 130

LOGGER = get_logger(__name__)


async def run() -> None:
    """Собирает бота и крутит polling до остановки."""
    settings = load_settings()
    setup_logging(settings.log_level)

    services = Services.build(settings)
    bot = create_bot(settings)
    dispatcher = create_dispatcher(services)

    # Опрос через polling: всё, что накопилось за время простоя, не нужно.
    await bot.delete_webhook(drop_pending_updates=True)

    # services попадает в kwargs каждого хендлера, фильтра и middleware.
    await dispatcher.start_polling(bot, services=services)


def main() -> int:
    try:
        asyncio.run(run())
    except ConfigError as exc:
        # Логгер на этом этапе ещё не настроен — пишем напрямую в stderr.
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except KeyboardInterrupt:
        print("Бот остановлен пользователем", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception:  # noqa: BLE001 - фиксируем падение и выходим с кодом 1
        LOGGER.exception("Бот аварийно остановлен")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
