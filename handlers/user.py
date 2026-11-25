from __future__ import annotations

import html
import math

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from config import config
from database import OrderError, db
from keyboards import (
    back_to_main_kb,
    cart_kb,
    categories_kb,
    checkout_confirm_kb,
    main_menu_kb,
    product_card_kb,
    products_kb,
    user_orders_kb,
)
from utils import fmt_price, is_admin, order_items_text, replace_with_photo_or_text, safe_edit, status_label

router = Router(name="user")

PAGE_SIZE = 8


async def _main_menu_text(user_id: int) -> str:
    cart_count = await db.get_cart_count(user_id)
    cart_line = f"\n🧺 В корзине: {cart_count} шт." if cart_count else ""
    return (
        f"👋 <b>Добро пожаловать в {html.escape(config.shop_name)}!</b>\n\n"
        "Здесь вы можете выбрать товары и оформить заказ в пару кликов.\n"
        "Выберите раздел ниже:"
        f"{cart_line}"
    )


async def _show_main_menu(message: Message, user_id: int) -> None:
    await message.answer(
        await _main_menu_text(user_id),
        reply_markup=main_menu_kb(is_admin(user_id), await db.get_cart_count(user_id)),
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return
    await db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _show_main_menu(message, message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    text = (
        "ℹ️ <b>Помощь</b>\n\n"
        "/start — главное меню\n"
        "/help — эта справка\n\n"
        "🛍 В каталоге выберите категорию и товар.\n"
        "🧺 В корзине можно изменить количество и оформить заказ одним нажатием."
    )
    await message.answer(text, reply_markup=back_to_main_kb())


@router.message(Command("admin"))
async def admin_denied(message: Message) -> None:
    await message.answer("⛔ У вас нет доступа к админ-панели.")


@router.callback_query(F.data == "menu:main")
async def menu_main(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    await db.add_user(user_id, callback.from_user.username, callback.from_user.first_name)
    await safe_edit(
        callback,
        await _main_menu_text(user_id),
        main_menu_kb(is_admin(user_id), await db.get_cart_count(user_id)),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:catalog")
async def menu_catalog(callback: CallbackQuery) -> None:
    categories = await db.get_categories()
    text = "🛍 <b>Каталог</b>\n\nВыберите категорию:"
    await safe_edit(callback, text, categories_kb(categories))
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def show_category(callback: CallbackQuery) -> None:
    _, category_id_raw, page_raw = callback.data.split(":")
    category_id = int(category_id_raw)
    page = max(0, int(page_raw))

    category = await db.get_category(category_id)
    if category is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    total = await db.count_products(category_id, only_active=True)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, total_pages - 1)
    products = await db.get_products_page(category_id, page, PAGE_SIZE, only_active=True)

    if not products:
        text = f"{category['emoji']} <b>{html.escape(category['title'])}</b>\n\nВ этой категории пока нет товаров."
        await safe_edit(callback, text, categories_kb(await db.get_categories()))
        await callback.answer()
        return

    text = f"{category['emoji']} <b>{html.escape(category['title'])}</b>\n\nВыберите товар:"
    await safe_edit(callback, text, products_kb(products, category_id, page, total_pages))
    await callback.answer()


@router.callback_query(F.data.startswith("product:"))
async def show_product(callback: CallbackQuery) -> None:
    _, product_id_raw, category_id_raw, page_raw = callback.data.split(":")
    product = await db.get_product(int(product_id_raw))
    if product is None or not int(product["is_active"]):
        await callback.answer("Товар больше недоступен", show_alert=True)
        return

    category = await db.get_category(int(category_id_raw))
    category_title = category["title"] if category else "—"
    stock = int(product["stock"])
    description = html.escape(product["description"]) if product["description"] else "Без описания"
    stock_line = f"📦 В наличии: <b>{stock} шт.</b>" if stock > 0 else "📦 <b>Нет в наличии</b>"

    caption = (
        f"<b>{html.escape(product['name'])}</b>\n\n"
        f"{description}\n\n"
        f"🏷 Категория: {html.escape(category_title)}\n"
        f"💰 Цена: <b>{fmt_price(product['price'])}</b>\n"
        f"{stock_line}"
    )
    await replace_with_photo_or_text(
        callback,
        product["photo_file_id"],
        caption,
        product_card_kb(product["id"], int(category_id_raw), int(page_raw), stock > 0),
    )
    await callback.answer()


# ----------------------------------------------------------------------- cart
async def _render_cart(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    items = [item for item in await db.get_cart_items(user_id) if int(item["is_active"])]

    if not items:
        text = "🧺 <b>Корзина</b>\n\nВаша корзина пуста."
    else:
        lines = [order_items_text(items)]
        total = sum(int(item["price"]) * int(item["qty"]) for item in items)
        text = f"🧺 <b>Корзина</b>\n\n{lines[0]}\n\n💰 <b>Итого: {fmt_price(total)}</b>"

    await safe_edit(callback, text, cart_kb(items))


@router.callback_query(F.data == "menu:cart")
async def menu_cart(callback: CallbackQuery) -> None:
    await _render_cart(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("cart:add:"))
async def cart_add(callback: CallbackQuery) -> None:
    product_id = int(callback.data.split(":")[2])
    result = await db.add_to_cart(callback.from_user.id, product_id)
    if result == "ok":
        await callback.answer("✅ Товар добавлен в корзину")
    elif result == "limit":
        await callback.answer("⚠️ В корзине уже максимальное количество", show_alert=True)
    else:
        await callback.answer("😔 Товар закончился", show_alert=True)


@router.callback_query(F.data.startswith("cart:inc:"))
async def cart_inc(callback: CallbackQuery) -> None:
    product_id = int(callback.data.split(":")[2])
    result = await db.change_cart_qty(callback.from_user.id, product_id, 1)
    if result == "limit":
        await callback.answer("⚠️ Больше нет в наличии", show_alert=True)
        return
    if result == "unavailable":
        await callback.answer("😔 Товар больше недоступен", show_alert=True)
        return
    await _render_cart(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("cart:dec:"))
async def cart_dec(callback: CallbackQuery) -> None:
    product_id = int(callback.data.split(":")[2])
    await db.change_cart_qty(callback.from_user.id, product_id, -1)
    await _render_cart(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("cart:del:"))
async def cart_del(callback: CallbackQuery) -> None:
    product_id = int(callback.data.split(":")[2])
    await db.remove_cart_item(callback.from_user.id, product_id)
    await _render_cart(callback)
    await callback.answer("🗑 Товар удалён из корзины")


# ------------------------------------------------------------------- checkout
@router.callback_query(F.data == "cart:checkout")
async def cart_checkout(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    items = [item for item in await db.get_cart_items(user_id) if int(item["is_active"])]
    if not items:
        await callback.answer("Корзина пуста", show_alert=True)
        await _render_cart(callback)
        return

    total = sum(int(item["price"]) * int(item["qty"]) for item in items)
    text = (
        "🧾 <b>Подтверждение заказа</b>\n\n"
        f"{order_items_text(items)}\n\n"
        f"💰 <b>Итого: {fmt_price(total)}</b>\n\n"
        "После подтверждения администратор получит ваш заказ "
        "и свяжется с вами в Telegram."
    )
    await safe_edit(callback, text, checkout_confirm_kb())
    await callback.answer()


@router.callback_query(F.data == "order:confirm")
async def order_confirm(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    try:
        order_id = await db.create_order(user_id)
    except OrderError as exc:
        code = str(exc)
        if code == "empty_cart":
            await callback.answer("Корзина пуста", show_alert=True)
        elif code.startswith("stock:"):
            await callback.answer(
                f"Товара «{code.split(':', 1)[1]}» не хватает на складе. Уменьшите количество.",
                show_alert=True,
            )
        else:
            await callback.answer("Не удалось оформить заказ", show_alert=True)
        await _render_cart(callback)
        return

    order = await db.get_order(order_id)
    items = await db.get_order_items(order_id)

    user_text = (
        f"✅ <b>Заказ №{order_id} оформлен!</b>\n\n"
        f"{order_items_text(items)}\n\n"
        f"💰 <b>Итого: {fmt_price(order['total'])}</b>\n"
        f"Статус: {status_label(order['status'])}\n\n"
        "Администратор уже получил уведомление и скоро свяжется с вами."
    )
    await safe_edit(callback, user_text, back_to_main_kb())

    username = f" (@{order['username']})" if order["username"] else ""
    full_name = order["full_name"] or "Покупатель"
    admin_text = (
        f"🔔 <b>Новый заказ №{order_id}</b>\n\n"
        f"👤 Покупатель: {html.escape(str(full_name))}{html.escape(username)}\n"
        f"🆔 Telegram ID: <code>{order['user_id']}</code>\n"
        f"🕒 {order['created_at']}\n\n"
        f"{order_items_text(items)}\n\n"
        f"💰 <b>Итого: {fmt_price(order['total'])}</b>\n"
        f"Статус: {status_label(order['status'])}"
    )
    from keyboards import admin_order_kb

    await notify_admins_safe(callback, admin_text, admin_order_kb(order_id, order["status"]))
    await callback.answer("Заказ оформлен")


async def notify_admins_safe(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    from utils import notify_admins

    if callback.bot is not None:
        await notify_admins(callback.bot, text, reply_markup)


# -------------------------------------------------------------------- my orders
@router.callback_query(F.data == "menu:orders")
async def menu_orders(callback: CallbackQuery) -> None:
    orders = await db.get_user_orders(callback.from_user.id, limit=10)
    if not orders:
        text = "📦 <b>Мои заказы</b>\n\nУ вас пока нет заказов."
        await safe_edit(callback, text, back_to_main_kb())
    else:
        text = "📦 <b>Мои заказы</b>\n\nВыберите заказ, чтобы посмотреть подробности:"
        await safe_edit(callback, text, user_orders_kb(orders))
    await callback.answer()


@router.callback_query(F.data.startswith("myorder:"))
async def my_order(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if order is None or int(order["user_id"]) != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    items = await db.get_order_items(order_id)
    text = (
        f"📦 <b>Заказ №{order_id}</b>\n"
        f"🕒 {order['created_at']}\n"
        f"Статус: {status_label(order['status'])}\n\n"
        f"{order_items_text(items)}\n\n"
        f"💰 <b>Итого: {fmt_price(order['total'])}</b>"
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Мои заказы", callback_data="menu:orders")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )
    await safe_edit(callback, text, kb)
    await callback.answer()


# -------------------------------------------------------------------- contacts
@router.callback_query(F.data == "menu:contacts")
async def menu_contacts(callback: CallbackQuery) -> None:
    support = config.support_contact or "Напишите администратору в Telegram."
    text = (
        "ℹ️ <b>Контакты</b>\n\n"
        f"🏪 Магазин: <b>{html.escape(config.shop_name)}</b>\n"
        f"💬 Поддержка: {html.escape(support)}"
    )
    await safe_edit(callback, text, back_to_main_kb())
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
