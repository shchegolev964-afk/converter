"""Форматирование чисел и тикеров для вывода пользователю."""

from __future__ import annotations

from .config import CRYPTO_IDS


def is_crypto(code: str) -> bool:
    return code.upper() in CRYPTO_IDS


def format_amount(code: str, value: float) -> str:
    """2 знака для фиата, до 8 знаков для крипты (с обрезкой нулей)."""
    if is_crypto(code):
        s = f"{value:.8f}".rstrip("0").rstrip(".")
        return s or "0"
    # тонкий неразрывный пробел как разделитель тысяч
    return f"{value:,.2f}".replace(",", " ")


def fmt_pair(from_code: str, from_amount: float, to_code: str, to_amount: float) -> str:
    return (
        f"💸 *{format_amount(from_code, from_amount)} {from_code}* = "
        f"*{format_amount(to_code, to_amount)} {to_code}*"
    )


def normalize_code(raw: str) -> str:
    return raw.strip().upper().replace(" ", "")
