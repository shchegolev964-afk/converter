"""Inline-клавиатуры."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .config import QUICK_PICK


def _grid(buttons: list[InlineKeyboardButton], cols: int = 4) -> list[list[InlineKeyboardButton]]:
    return [buttons[i : i + cols] for i in range(0, len(buttons), cols)]


def currencies_kb(prefix: str, recent: list[str] | None = None) -> InlineKeyboardMarkup:
    """Кнопки с популярными валютами + последние использованные."""
    seen: set[str] = set()
    items: list[str] = []
    for code in (recent or []) + QUICK_PICK:
        c = code.upper()
        if c not in seen:
            seen.add(c)
            items.append(c)

    rows = _grid(
        [InlineKeyboardButton(c, callback_data=f"{prefix}:{c}") for c in items],
        cols=4,
    )
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💱 Курсы", callback_data="menu:rates"),
                InlineKeyboardButton("🔁 Конвертация", callback_data="menu:convert"),
            ],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="menu:help")],
        ]
    )


def after_convert_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔁 Ещё конвертация", callback_data="menu:convert"),
                InlineKeyboardButton("💱 Курсы", callback_data="menu:rates"),
            ]
        ]
    )
