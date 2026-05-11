"""Конфигурация бота: читает .env и валидирует значения."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня проекта (на уровень выше пакета bot/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    token: str
    base_currency: str
    cache_ttl: int
    log_level: int
    proxy_url: str | None  # http(s):// или socks5:// URL, None — без прокси


def _get_log_level(name: str) -> int:
    return getattr(logging, name.upper(), logging.INFO)


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token.startswith("PASTE_") or "replace-me" in token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. Скопируй .env.example в .env и вставь "
            "токен, полученный у @BotFather."
        )

    proxy = os.getenv("TELEGRAM_PROXY", "").strip() or None

    return Settings(
        token=token,
        base_currency=os.getenv("BASE_CURRENCY", "USD").upper(),
        cache_ttl=int(os.getenv("CACHE_TTL_SECONDS", "60")),
        log_level=_get_log_level(os.getenv("LOG_LEVEL", "INFO")),
        proxy_url=proxy,
    )


# ----------------------------- Списки валют ----------------------------------

# Криптовалюты, которые умеем конвертировать. Ключ — тикер, значение — id в CoinGecko.
CRYPTO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether",
    "USDC": "usd-coin",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TON": "the-open-network",
    "TRX": "tron",
    "DOT": "polkadot",
}

# Что показываем в /rates
POPULAR_FIAT = ["EUR", "GBP", "JPY", "CNY", "RUB", "CHF", "AUD", "CAD"]
POPULAR_CRYPTO = ["BTC", "ETH", "TON", "SOL", "USDT"]

# Кнопки быстрого выбора в /convert
QUICK_PICK = ["USD", "EUR", "RUB", "GBP", "BTC", "ETH", "USDT", "TON"]
