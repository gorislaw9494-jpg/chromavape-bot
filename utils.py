from __future__ import annotations

import html
from typing import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from config import config

STATUS_LABELS = {
    "new": "🆕 Новый",
    "accepted": "✅ Принят",
    "processing": "🛠 В работе",
    "shipped": "🚚 Отправлен",
    "completed": "🏁 Выполнен",
    "cancelled": "❌ Отменён",
}

STATUS_EMOJI = {
    "new": "🆕",
    "accepted": "✅",
    "processing": "🛠",
    "shipped": "🚚",
    "completed": "🏁",
    "cancelled": "❌",
}


def fmt_price(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₽"


def truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids


def order_items_text(items: Iterable) -> str:
    """Render order items list. Supports both 'product_name' (orders) and 'name' (cart)."""
    lines = []
    for item in items:
        # Support both 'product_name' (from orders) and 'name' (from cart)
        product_name = item.get('product_name') or item.get('name', 'Неизвестный товар')
        lines.append(
            f"• {html.escape(str(product_name))} — "
            f"{item['qty']} шт. × {fmt_price(item['price'])} = "
            f"{fmt_price(int(item['price']) * int(item['qty']))}"
        )
    return "\n".join(lines)


async def safe_delete(message: Message | None) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def safe_edit(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Edit a bot message, falling back to delete + send for photo messages."""
    message = callback.message
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        error = str(exc).lower()
        if "message is not modified" in error:
            return
        await safe_delete(message)
        await message.answer(text, reply_markup=reply_markup)


async def send_photo_or_text(
    message: Message,
    photo: str | None,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if photo:
        await message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup)
    else:
        await message.answer(caption, reply_markup=reply_markup)


async def replace_with_photo_or_text(
    callback: CallbackQuery,
    photo: str | None,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Replace the current bot message with a fresh product/menu message."""
    message = callback.message
    if message is None:
        return
    await safe_delete(message)
    await send_photo_or_text(message, photo, caption, reply_markup)


async def notify_admins(bot: Bot, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except (TelegramForbiddenError, TelegramBadRequest):
            continue


async def notify_admins_photo(
    bot: Bot,
    photo: str,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_photo(
                admin_id, photo=photo, caption=caption, reply_markup=reply_markup
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            continue
