"""
Точка входа: загружает конфиг, регистрирует хендлеры и запускает бота.

Запуск:
    python main.py
"""

from __future__ import annotations

import logging
import sys

from telegram import BotCommand, Update
from telegram.ext import Application

from bot import __version__
from bot.config import load_settings
from bot.handlers import register
from bot.services import init_cache


def _setup_logging(level: int) -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=level,
    )
    # Снижаем шум от httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def _set_commands(app: Application) -> None:
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Запустить бота"),
            BotCommand("rates", "Курсы популярных валют"),
            BotCommand("convert", "Конвертировать сумму"),
            BotCommand("cancel", "Отменить диалог"),
            BotCommand("help", "Помощь"),
        ]
    )


def main() -> None:
    try:
        settings = load_settings()
    except RuntimeError as e:
        print(f"[config] {e}", file=sys.stderr)
        sys.exit(1)

    _setup_logging(settings.log_level)
    log = logging.getLogger("main")
    log.info("Currency bot v%s starting…", __version__)

    init_cache(settings.cache_ttl)

    builder = (
        Application.builder()
        .token(settings.token)
        .post_init(_set_commands)
        # Щедрые таймауты — особенно важно при работе через SOCKS-прокси.
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(10.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_read_timeout(60.0)
        .get_updates_write_timeout(30.0)
        .get_updates_pool_timeout(10.0)
    )
    if settings.proxy_url:
        log.info("Используется прокси для Telegram API: %s", settings.proxy_url)
        builder = builder.proxy(settings.proxy_url).get_updates_proxy(settings.proxy_url)
    app = builder.build()
    app.bot_data["settings"] = settings

    register(app)

    log.info("Бот запущен. Нажми Ctrl+C, чтобы остановить.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
