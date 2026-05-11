"""Работа с внешними API (Frankfurter, CoinGecko) + кэш."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from .config import CRYPTO_IDS
from .formatting import is_crypto

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
OPEN_ERAPI_URL = "https://open.er-api.com/v6/latest/{base}"
ERAPI_CDN_URL = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{base}.json"
)
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

_HTTP_TIMEOUT = httpx.Timeout(10.0)


class RateError(Exception):
    """Понятная ошибка для пользователя (неверная валюта, нет данных и т.п.)."""


class _TTLCache:
    """Минималистичный async-safe TTL-кэш."""

    def __init__(self, ttl: int) -> None:
        self.ttl = ttl
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_or_set(self, key: str, factory):
        async with self._lock:
            hit = self._data.get(key)
            if hit and time.monotonic() - hit[0] < self.ttl:
                return hit[1]
        # снаружи лока, чтобы запросы шли параллельно
        value = await factory()
        async with self._lock:
            self._data[key] = (time.monotonic(), value)
        return value


_cache: _TTLCache | None = None


def init_cache(ttl: int) -> None:
    global _cache
    _cache = _TTLCache(ttl)


def _cache_or_run(key: str, factory):
    if _cache is None:
        return factory()
    return _cache.get_or_set(key, factory)


# --------------------------- HTTP helpers ------------------------------------

async def _http_get_json(url: str, params: dict[str, str]) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %s for %s %s", e.response.status_code, url, params)
        raise RateError(
            f"API ответил {e.response.status_code}. Проверь коды валют."
        ) from e
    except httpx.HTTPError as e:
        logger.warning("HTTP error %s for %s", e, url)
        raise RateError("API недоступен. Попробуй чуть позже.") from e


# --------------------------- Public API --------------------------------------

async def _from_open_erapi(base: str) -> dict[str, float]:
    """open.er-api.com: бесплатный, без ключа, поддерживает RUB/UAH/BYN и т. п."""
    data = await _http_get_json(OPEN_ERAPI_URL.format(base=base), {})
    if data.get("result") != "success":
        raise RateError(f"open.er-api: {data.get('error-type', 'unknown')}")
    rates = data.get("rates") or {}
    if not rates:
        raise RateError("open.er-api вернул пустой ответ.")
    rates[base.upper()] = 1.0
    return {k.upper(): float(v) for k, v in rates.items()}


async def _from_erapi_cdn(base: str) -> dict[str, float]:
    """fawazahmed0/currency-api (jsdelivr CDN) — резерв."""
    data = await _http_get_json(ERAPI_CDN_URL.format(base=base.lower()), {})
    rates = data.get(base.lower()) or {}
    if not rates:
        raise RateError("currency-api CDN вернул пустой ответ.")
    out = {k.upper(): float(v) for k, v in rates.items()}
    out[base.upper()] = 1.0
    return out


async def _from_frankfurter(base: str) -> dict[str, float]:
    """Frankfurter (ЕЦБ) — резерв; RUB не поддерживает."""
    data = await _http_get_json(FRANKFURTER_URL, {"from": base})
    rates = data.get("rates") or {}
    if not rates:
        raise RateError("Frankfurter вернул пустой ответ.")
    rates[base.upper()] = 1.0
    return {k.upper(): float(v) for k, v in rates.items()}


async def fiat_rates(base: str) -> dict[str, float]:
    """
    Все доступные курсы относительно базовой фиатной валюты.
    Источники пробуются по очереди — первый успешный выигрывает.
    """
    base = base.upper()

    async def factory():
        last_err: Exception | None = None
        for name, fn in (
            ("open.er-api", _from_open_erapi),
            ("currency-api CDN", _from_erapi_cdn),
            ("frankfurter", _from_frankfurter),
        ):
            try:
                return await fn(base)
            except RateError as e:
                logger.warning("Источник %s упал для base=%s: %s", name, base, e)
                last_err = e
        raise RateError(
            f"Все фиатные источники недоступны для {base}: {last_err}"
        )

    return await _cache_or_run(f"fiat:{base}", factory)


async def fiat_rate(base: str, target: str) -> float:
    if base == target:
        return 1.0
    try:
        rates = await fiat_rates(base)
    except RateError:
        raise
    rate = rates.get(target)
    if rate is None:
        raise RateError(f"Неизвестная фиатная валюта: {target}.")
    return rate


async def crypto_prices(symbols: list[str], vs: list[str]) -> dict[str, dict[str, float]]:
    """Возвращает {SYMBOL: {vs_code: price}} для каждого тикера."""
    ids = []
    sym_to_id = {}
    for s in symbols:
        cid = CRYPTO_IDS.get(s.upper())
        if cid:
            ids.append(cid)
            sym_to_id[s.upper()] = cid
    if not ids:
        return {}

    key = f"crypto:{','.join(sorted(ids))}|{','.join(sorted(v.lower() for v in vs))}"

    async def factory():
        return await _http_get_json(
            COINGECKO_URL,
            {"ids": ",".join(ids), "vs_currencies": ",".join(v.lower() for v in vs)},
        )

    raw = await _cache_or_run(key, factory)
    out: dict[str, dict[str, float]] = {}
    for sym, cid in sym_to_id.items():
        entry = raw.get(cid) or {}
        out[sym] = {k.upper(): v for k, v in entry.items()}
    return out


async def crypto_price(symbol: str, vs: str) -> float:
    data = await crypto_prices([symbol], [vs])
    price = data.get(symbol.upper(), {}).get(vs.upper())
    if price is None:
        raise RateError(f"Не удалось получить цену {symbol} в {vs}.")
    return float(price)


# --------------------------- Convert -----------------------------------------

async def convert(from_cur: str, to_cur: str, amount: float) -> float:
    """Универсальная конвертация любой пары (фиат/крипта)."""
    from_cur = from_cur.upper()
    to_cur = to_cur.upper()
    if from_cur == to_cur:
        return amount

    f_crypto, t_crypto = is_crypto(from_cur), is_crypto(to_cur)

    # фиат -> фиат
    if not f_crypto and not t_crypto:
        return amount * await fiat_rate(from_cur, to_cur)

    # крипта -> фиат
    if f_crypto and not t_crypto:
        try:
            return amount * await crypto_price(from_cur, to_cur)
        except RateError:
            # fallback через USD
            in_usd = amount * await crypto_price(from_cur, "USD")
            return in_usd * await fiat_rate("USD", to_cur)

    # фиат -> крипта
    if not f_crypto and t_crypto:
        try:
            price_in_from = await crypto_price(to_cur, from_cur)
            return amount / price_in_from
        except RateError:
            usd_amount = amount * await fiat_rate(from_cur, "USD")
            price_usd = await crypto_price(to_cur, "USD")
            return usd_amount / price_usd

    # крипта -> крипта (через USD)
    prices = await crypto_prices([from_cur, to_cur], ["USD"])
    p_from = prices.get(from_cur, {}).get("USD")
    p_to = prices.get(to_cur, {}).get("USD")
    if not p_from or not p_to:
        raise RateError("Не удалось получить цены крипты.")
    return amount * p_from / p_to


def validate_currency(code: str) -> None:
    """Быстрая проверка формата кода. Доступность валюты проверится при запросе."""
    if not code:
        raise RateError("Пустой код валюты.")
    if not code.isalpha() or not (2 <= len(code) <= 6):
        raise RateError(f"«{code}» не похоже на код валюты (нужно 2–6 букв).")
