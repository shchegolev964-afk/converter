"""Хендлеры команд и состояний ConversationHandler."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import services
from .config import POPULAR_CRYPTO, POPULAR_FIAT, Settings
from .formatting import fmt_pair, format_amount, is_crypto, normalize_code
from .keyboards import after_convert_kb, currencies_kb, main_menu_kb
from .services import RateError

logger = logging.getLogger(__name__)

# Состояния ConversationHandler
FROM_CUR, TO_CUR, AMOUNT = range(3)

RECENT_MAX = 6


# --------------------------- Утилиты -----------------------------------------

def _push_recent(context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    recent: list[str] = context.user_data.setdefault("recent", [])
    code = code.upper()
    if code in recent:
        recent.remove(code)
    recent.insert(0, code)
    del recent[RECENT_MAX:]


def _recent(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    return list(context.user_data.get("recent", []))


async def _reply(update: Update, text: str, **kwargs):
    """Унифицированный ответ для message/callback_query."""
    if update.callback_query:
        await update.callback_query.answer()
        return await update.callback_query.message.reply_text(text, **kwargs)
    return await update.message.reply_text(text, **kwargs)


# --------------------------- /start, /help -----------------------------------

HELP_TEXT = (
    "👋 *Я — бот курсов валют и криптовалют.*\n\n"
    "*Команды:*\n"
    "• /rates — текущие курсы популярных валют\n"
    "• /convert — конвертация суммы\n"
    "• /cancel — отменить диалог\n"
    "• /help — это сообщение\n\n"
    "Поддержка фиата (USD, EUR, RUB, GBP, JPY, …) и крипты "
    "(BTC, ETH, USDT, TON, SOL, XRP, ADA, DOGE, …).\n\n"
    "Источники: [Frankfurter](https://frankfurter.app) + "
    "[CoinGecko](https://www.coingecko.com)."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(),
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(
        update,
        HELP_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(),
        disable_web_page_preview=True,
    )


# --------------------------- /rates ------------------------------------------

async def cmd_rates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    base = settings.base_currency

    try:
        fiat = await services.fiat_rates(base)
        crypto = await services.crypto_prices(POPULAR_CRYPTO, ["USD", "RUB"])
    except RateError as e:
        await _reply(update, f"⚠️ {e}")
        return

    lines = [f"💱 *Текущие курсы* (база: {base})", ""]
    lines.append(f"*Фиат — 1 {base} →*")
    for code in POPULAR_FIAT:
        v = fiat.get(code)
        if v is not None:
            lines.append(f"  • {code}: {format_amount(code, v)}")

    if crypto:
        lines.append("")
        lines.append("*Криптовалюты:*")
        for sym in POPULAR_CRYPTO:
            entry = crypto.get(sym, {})
            usd = entry.get("USD")
            rub = entry.get("RUB")
            if usd is None:
                continue
            chunk = f"  • {sym}: {format_amount('USD', usd)} USD"
            if rub is not None:
                chunk += f" / {format_amount('RUB', rub)} RUB"
            lines.append(chunk)

    await _reply(
        update,
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(),
    )


# --------------------------- /convert ----------------------------------------

async def convert_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("from", None)
    context.user_data.pop("to", None)
    await _reply(
        update,
        "🔁 *Конвертация валют*\n\n"
        "Шаг 1/3. Из какой валюты конвертируем?\n"
        "Введи код (например, `USD`, `EUR`, `BTC`) или выбери ниже:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=currencies_kb("from", _recent(context)),
    )
    return FROM_CUR


async def _pick(update: Update, prefix: str) -> str | None:
    """Достаёт код валюты из callback_query или из текста."""
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data
        if data == "cancel":
            return "__CANCEL__"
        if data.startswith(prefix + ":"):
            return data.split(":", 1)[1].upper()
        return None
    if update.message and update.message.text:
        return normalize_code(update.message.text)
    return None


async def convert_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = await _pick(update, "from")
    if code == "__CANCEL__":
        return await cancel(update, context)
    if not code:
        await _reply(update, "Не понял. Введи код валюты, например `USD`.",
                     parse_mode=ParseMode.MARKDOWN)
        return FROM_CUR

    try:
        services.validate_currency(code)
    except RateError as e:
        await _reply(update, f"⚠️ {e} Попробуй ещё раз.")
        return FROM_CUR

    context.user_data["from"] = code
    _push_recent(context, code)
    await _reply(
        update,
        f"✅ Из: *{code}*\n\nШаг 2/3. В какую валюту конвертируем?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=currencies_kb("to", _recent(context)),
    )
    return TO_CUR


async def convert_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = await _pick(update, "to")
    if code == "__CANCEL__":
        return await cancel(update, context)
    if not code:
        await _reply(update, "Не понял. Введи код валюты, например `EUR`.",
                     parse_mode=ParseMode.MARKDOWN)
        return TO_CUR

    try:
        services.validate_currency(code)
    except RateError as e:
        await _reply(update, f"⚠️ {e} Попробуй ещё раз.")
        return TO_CUR

    if code == context.user_data.get("from"):
        await _reply(update, "Целевая валюта совпадает с исходной — выбери другую.")
        return TO_CUR

    context.user_data["to"] = code
    _push_recent(context, code)
    hint = "до 8 знаков после запятой" if is_crypto(context.user_data["from"]) else "число"
    await _reply(
        update,
        f"✅ В: *{code}*\n\nШаг 3/3. Введи сумму ({hint}):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AMOUNT


async def convert_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").replace(",", ".").replace(" ", "").strip()
    try:
        amount = float(raw)
        if amount <= 0 or amount != amount:  # NaN check
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Сумма должна быть положительным числом. Попробуй ещё раз."
        )
        return AMOUNT

    from_cur = context.user_data.get("from")
    to_cur = context.user_data.get("to")
    if not from_cur or not to_cur:
        await update.message.reply_text("Что-то пошло не так. Начни заново: /convert")
        return ConversationHandler.END

    try:
        result = await services.convert(from_cur, to_cur, amount)
    except RateError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ConversationHandler.END
    except Exception:  # noqa: BLE001
        logger.exception("convert failed")
        await update.message.reply_text("⚠️ Внутренняя ошибка при конвертации.")
        return ConversationHandler.END

    await update.message.reply_text(
        fmt_pair(from_cur, amount, to_cur, result),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=after_convert_kb(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("from", None)
    context.user_data.pop("to", None)
    await _reply(update, "Операция отменена. Чтобы начать заново — /convert.")
    return ConversationHandler.END


# --------------------------- Главное меню (callbacks) ------------------------

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Кнопки из main_menu_kb / after_convert_kb."""
    query = update.callback_query
    if not query:
        return None
    await query.answer()
    data = query.data or ""

    if data == "menu:rates":
        await cmd_rates(update, context)
        return None
    if data == "menu:help":
        await cmd_help(update, context)
        return None
    if data == "menu:convert":
        # Запустим диалог конвертации вручную, имитируя entry_point.
        return await convert_start(update, context)
    return None


# --------------------------- Ошибки ------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Что-то пошло не так. Попробуй ещё раз чуть позже."
            )
        except Exception:  # noqa: BLE001
            pass


# --------------------------- Регистрация -------------------------------------

def register(app: Application) -> None:
    convert_handler = ConversationHandler(
        entry_points=[
            CommandHandler("convert", convert_start),
            CallbackQueryHandler(convert_start, pattern=r"^menu:convert$"),
        ],
        states={
            FROM_CUR: [
                CallbackQueryHandler(convert_from, pattern=r"^(from:|cancel$)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, convert_from),
            ],
            TO_CUR: [
                CallbackQueryHandler(convert_to, pattern=r"^(to:|cancel$)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, convert_to),
            ],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, convert_amount)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
        ],
        name="convert",
        persistent=False,
        per_message=False,
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("rates", cmd_rates))
    app.add_handler(convert_handler)
    # router для кнопок главного меню (после convert_handler, чтобы не перехватывать его)
    app.add_handler(CallbackQueryHandler(menu_router, pattern=r"^menu:"))
    app.add_error_handler(error_handler)
