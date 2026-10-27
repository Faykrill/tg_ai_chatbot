"""Настройки бота: чтение ``.env``, реестр провайдеров и валидация."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

__all__ = [
    "ConfigError",
    "PROVIDERS",
    "SRC_DIR",
    "Settings",
    "load_settings",
]

#: Каталог ``src`` — рядом с ним лежат data-файлы бота (topics.json и т. п.).
SRC_DIR: Final[Path] = Path(__file__).resolve().parents[1]

#: Где ищем ``.env``: сначала в корне проекта, затем в ``src``.
ENV_CANDIDATES: Final[tuple[Path, ...]] = (SRC_DIR.parent / ".env", SRC_DIR / ".env")

DEFAULT_PROVIDER: Final[str] = "deepseek"
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
DEFAULT_MAX_HISTORY_PAIRS: Final[int] = 10
DEFAULT_MAX_DIALOGS: Final[int] = 500
DEFAULT_REQUEST_TIMEOUT: Final[float] = 120.0
DEFAULT_MAX_RETRIES: Final[int] = 2


class ConfigError(RuntimeError):
    """Некорректная конфигурация — бот не может стартовать."""


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """OpenAI-совместимый провайдер."""

    name: str
    base_url: str
    default_model: str


PROVIDERS: Final[dict[str, ProviderConfig]] = {
    config.name: config
    for config in (
        ProviderConfig("deepseek", "https://api.deepseek.com/v1", "deepseek-chat"),
        ProviderConfig(
            "qwen",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "qwen-plus",
        ),
        ProviderConfig(
            "groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"
        ),
        ProviderConfig(
            "openrouter",
            "https://openrouter.ai/api/v1",
            "meta-llama/llama-3.3-70b-instruct:free",
        ),
    )
}


@dataclass(frozen=True, slots=True)
class Settings:
    """Все настройки бота в одном immutable-объекте."""

    bot_token: str
    provider: ProviderConfig
    api_key: str
    model: str
    data_dir: Path
    log_level: str
    max_history_pairs: int
    max_dialogs: int
    request_timeout: float
    max_retries: int

    @property
    def topics_file(self) -> Path:
        """Файл с привязками групп к темам (обратная совместимость)."""
        return self.data_dir / "topics.json"

    @property
    def group_modes_file(self) -> Path:
        """Файл с режимами работы бота в группах."""
        return self.data_dir / "group_modes.json"

    @staticmethod
    def available_providers() -> tuple[str, ...]:
        return tuple(PROVIDERS)


def _clean(value: str | None) -> str | None:
    """Убирает пробелы и кавычки, которые могут остаться в ``.env``."""
    if value is None:
        return None
    return value.strip().strip("'\"").strip() or None


def _env_str(name: str, default: str | None = None) -> str | None:
    return _clean(os.getenv(name)) or default


def _env_int(name: str, default: int, settings_hint: str) -> int:
    raw = _env_str(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{settings_hint} должен быть целым числом, а не {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{settings_hint} должен быть больше нуля (сейчас {value})")
    return value


def _env_float(name: str, default: float, settings_hint: str) -> float:
    raw = _env_str(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{settings_hint} должен быть числом, а не {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{settings_hint} должен быть больше нуля (сейчас {value})")
    return value


def _load_dotenv_file(env_file: Path | None) -> Path | None:
    """Загружает переданный ``.env`` либо первый найденный из ``ENV_CANDIDATES``."""
    candidates: Sequence[Path] = (
        (env_file,) if env_file is not None else ENV_CANDIDATES
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            load_dotenv(path, override=True)
            return path
    load_dotenv(override=True)  # как раньше: полагаемся на поиск python-dotenv
    return None


def load_settings(env_file: Path | None = None) -> Settings:
    """Читает переменные окружения и возвращает проверенные настройки.

    :raises ConfigError: если обязательные переменные не заданы или невалидны.
    """
    _load_dotenv_file(env_file)

    bot_token = _env_str("BOT_TOKEN")
    if not bot_token:
        raise ConfigError("Не задан BOT_TOKEN. Добавь его в .env")

    api_key = _env_str("AI_API_KEY")
    if not api_key:
        raise ConfigError("Не задан AI_API_KEY. Добавь его в .env")

    provider_name = (_env_str("AI_PROVIDER", DEFAULT_PROVIDER) or DEFAULT_PROVIDER).lower()
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise ConfigError(
            f"Неизвестный AI_PROVIDER={provider_name!r}. "
            f"Должен быть один из: {', '.join(Settings.available_providers())}"
        )

    return Settings(
        bot_token=bot_token,
        provider=provider,
        api_key=api_key,
        model=_env_str("AI_MODEL") or provider.default_model,
        data_dir=SRC_DIR,
        log_level=(_env_str("LOG_LEVEL", DEFAULT_LOG_LEVEL) or DEFAULT_LOG_LEVEL).upper(),
        max_history_pairs=_env_int(
            "MAX_HISTORY_PAIRS", DEFAULT_MAX_HISTORY_PAIRS, "MAX_HISTORY_PAIRS"
        ),
        max_dialogs=_env_int("MAX_DIALOGS", DEFAULT_MAX_DIALOGS, "MAX_DIALOGS"),
        request_timeout=_env_float(
            "AI_TIMEOUT", DEFAULT_REQUEST_TIMEOUT, "AI_TIMEOUT"
        ),
        max_retries=_env_int("AI_MAX_RETRIES", DEFAULT_MAX_RETRIES, "AI_MAX_RETRIES"),
    )
