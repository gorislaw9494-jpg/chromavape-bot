from __future__ import annotations

import html
import math
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

from config import config
from database import OrderError, db
from keyboards import (
    back_to_main_kb,
    cart_clear_confirm_kb,
    cart_kb,
    categories_kb,
    chat_end_kb,
    checkout_confirm_kb,
    delivery_kb,
    main_menu_kb,
    phone_request_kb,
    product_card_kb,
    products_kb,
    skip_comment_kb,
    skip_name_kb,
    user_orders_kb,
)
from states import ChatWithManager, Checkout
from utils import (
    fmt_price,
    is_admin,
    notify_admins,
    notify_admins_photo,
    order_items_text,
    replace_with_photo_or_text,
    safe_delete,
    safe_edit,
    status_label,
)

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
async def cmd_start(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await state.clear()
    await db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer("Главное меню 👇", reply_markup=ReplyKeyboardRemove())
    await _show_main_menu(message, message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    text = (
        "ℹ️ <b>Помощь</b>\n\n"
        "/start — главное меню\n"
        "/help — эта справка\n"
        "/cancel — отменить оформление или чат\n\n"
        "🛍 В каталоге выберите категорию и товар.\n"
        "🧺 В корзине можно изменить количество, очистить её и оформить заказ.\n"
        "🧾 При оформлении бот по шагам спросит телефон, способ получения, "
        "адрес (для доставки) и комментарий."
    )
    await message.answer(text, reply_markup=back_to_main_kb())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())
    await _show_main_menu(message, message.from_user.id)


@router.message(Command("admin"))
async def admin_denied(message: Message) -> None:
    await message.answer("⛔ У вас нет доступа к админ-панели.")


@router.callback_query(F.data == "menu:main")
async def menu_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id = callback.from_user.id
    await db.add_user(user_id, callback.from_user.username, callback.from_user.first_name)
    await safe_edit(
        callback,
        await _main_menu_text(user_id),
        main_menu_kb(is_admin(user_id), await db.get_cart_count(user_id)),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:help")
async def menu_help(callback: CallbackQuery) -> None:
    text = (
        "❓ <b>Помощь</b>\n\n"
        "🛍 <b>Каталог</b> — выберите категорию и товар.\n"
        "🧺 <b>Корзина</b> — измените количество, удалите товар или очистите корзину.\n"
        "🧾 <b>Оформить заказ</b> — бот пошагово спросит телефон, "
        "способ получения, адрес и комментарий.\n"
        "📦 <b>Мои заказы</b> — статусы ваших заказов.\n"
        "💬 <b>Связаться с менеджером</b> — переписка с администратором.\n\n"
        "Команда /cancel отменяет текущее оформление или чат."
    )
    await safe_edit(callback, text, back_to_main_kb())
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
        total = sum(int(item["price"]) * int(item["qty"]) for item in items)
        text = (
            "🧺 <b>Корзина</b>\n\n"
            f"{order_items_text(items)}\n\n"
            f"💰 <b>Итого: {fmt_price(total)}</b>"
        )

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


@router.callback_query(F.data == "cart:clear")
async def cart_clear_ask(callback: CallbackQuery) -> None:
    await safe_edit(
        callback,
        "🧹 <b>Очистить корзину?</b>\n\nВсе товары будут удалены.",
        cart_clear_confirm_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "cart:clear_confirm")
async def cart_clear(callback: CallbackQuery) -> None:
    await db.clear_cart(callback.from_user.id)
    await _render_cart(callback)
    await callback.answer("🧹 Корзина очищена")


# ------------------------------------------------------------------- checkout
def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if 10 <= len(digits) <= 15:
        return "+" + digits
    return None


async def _start_checkout(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    items = [item for item in await db.get_cart_items(user_id) if int(item["is_active"])]
    if not items:
        await callback.answer("Корзина пуста", show_alert=True)
        await _render_cart(callback)
        return

    await state.clear()
    await state.set_state(Checkout.phone)
    await state.update_data(phone=None, name=None, delivery_method=None, address=None, comment=None)

    await safe_edit(
        callback,
        "📞 <b>Шаг 1 из 6.</b> Отправьте контактный телефон.\n\n"
        "Нажмите «Поделиться контактом» или введите номер вручную.",
        InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="checkout:cancel")]]
        ),
    )
    if callback.message is not None:
        await callback.message.answer(
            "Телефон нужен менеджеру для связи по заказу:",
            reply_markup=phone_request_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.in_({"menu:checkout", "cart:checkout"}))
async def cart_checkout(callback: CallbackQuery, state: FSMContext) -> None:
    await _start_checkout(callback, state)


@router.message(Checkout.phone)
async def checkout_phone(message: Message, state: FSMContext) -> None:
    phone = None
    if message.contact and message.contact.phone_number:
        phone = _normalize_phone(message.contact.phone_number)
    elif message.text:
        phone = _normalize_phone(message.text)

    if not phone:
        await message.answer(
            "Введите номер телефона цифрами (например, +7 999 123-45-67) "
            "или нажмите «Поделиться контактом».",
            reply_markup=phone_request_kb(),
        )
        return

    await state.update_data(phone=phone)
    await message.answer("✅ Телефон сохранён.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Checkout.name)
    await message.answer(
        "👤 <b>Шаг 2 из 6.</b> Как к вам обращаться?\n\n"
        "Можно пропустить — тогда используем ваше имя из Telegram.",
        reply_markup=skip_name_kb(),
    )


@router.message(Checkout.name)
async def checkout_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()[:80] or None
    await state.update_data(name=name)
    await state.set_state(Checkout.delivery)
    await message.answer("📦 <b>Шаг 3 из 6.</b> Выберите способ получения:", reply_markup=delivery_kb())


@router.callback_query(Checkout.name, F.data == "checkout:skip_name")
async def checkout_skip_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(name=None)
    await state.set_state(Checkout.delivery)
    await safe_edit(
        callback,
        "📦 <b>Шаг 3 из 6.</b> Выберите способ получения:",
        delivery_kb(),
    )
    await callback.answer()


@router.callback_query(Checkout.delivery, F.data.startswith("checkout:delivery:"))
async def checkout_delivery(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":")[-1]
    if method not in {"delivery", "pickup"}:
        await callback.answer("Неизвестный способ получения", show_alert=True)
        return
    await state.update_data(delivery_method=method)
    if method == "delivery":
        await state.set_state(Checkout.address)
        await safe_edit(
            callback,
            "📍 <b>Шаг 4 из 6.</b> Введите адрес доставки:\n\n"
            "Укажите город, улицу, дом и квартиру.",
        )
    else:
        await state.update_data(address=None)
        await state.set_state(Checkout.comment)
        await safe_edit(
            callback,
            "💬 <b>Шаг 5 из 6.</b> Добавьте комментарий к заказу.\n\n"
            "Это необязательно.",
            skip_comment_kb(),
        )
    await callback.answer()


@router.message(Checkout.address)
async def checkout_address(message: Message, state: FSMContext) -> None:
    address = (message.text or "").strip()
    if len(address) < 5:
        await message.answer("Введите адрес подробнее (город, улица, дом, квартира).")
        return
    await state.update_data(address=address[:300])
    await state.set_state(Checkout.comment)
    await message.answer(
        "💬 <b>Шаг 5 из 6.</b> Добавьте комментарий к заказу.\n\n"
        "Это необязательно.",
        reply_markup=skip_comment_kb(),
    )


async def _checkout_summary(user_id: int, data: dict) -> str:
    items = [item for item in await db.get_cart_items(user_id) if int(item["is_active"])]
    total = sum(int(item["price"]) * int(item["qty"]) for item in items)
    method = "🚚 Доставка" if data.get("delivery_method") == "delivery" else "🏪 Самовывоз"
    name = data.get("name") or "не указано"
    address = data.get("address") or ("—" if data.get("delivery_method") == "delivery" else "самовывоз")
    comment = data.get("comment") or "—"
    return (
        "🧾 <b>Проверьте заказ</b>\n\n"
        f"{order_items_text(items)}\n\n"
        f"👤 Имя: {html.escape(str(name))}\n"
        f"📞 Телефон: {html.escape(str(data.get('phone') or '—'))}\n"
        f"📦 Получение: {method}\n"
        f"📍 Адрес: {html.escape(str(address))}\n"
        f"💬 Комментарий: {html.escape(str(comment))}\n\n"
        f"💰 <b>Итого: {fmt_price(total)}</b>\n\n"
        "Всё верно? Нажмите «Подтвердить заказ»."
    )


async def _show_summary(message: Message, state: FSMContext, edit_callback: CallbackQuery | None = None) -> None:
    data = await state.get_data()
    text = await _checkout_summary(message.chat.id, data)
    await state.set_state(Checkout.confirm)
    if edit_callback is not None:
        await safe_edit(edit_callback, text, checkout_confirm_kb())
        await edit_callback.answer()
    else:
        await message.answer(text, reply_markup=checkout_confirm_kb())


@router.message(Checkout.comment)
async def checkout_comment(message: Message, state: FSMContext) -> None:
    comment = (message.text or "").strip()[:500] or None
    await state.update_data(comment=comment)
    await _show_summary(message, state)


@router.callback_query(Checkout.comment, F.data == "checkout:skip_comment")
async def checkout_skip_comment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(comment=None)
    if callback.message is None:
        await callback.answer()
        return
    await _show_summary(callback.message, state, edit_callback=callback)


@router.callback_query(Checkout.confirm, F.data == "order:confirm")
async def order_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    data = await state.get_data()
    phone = data.get("phone")
    if not phone:
        await callback.answer("Сессия оформления устарела. Начните заново.", show_alert=True)
        await state.clear()
        return

    try:
        order_id = await db.create_order(
            user_id=user_id,
            phone=phone,
            delivery_method=data.get("delivery_method") or "pickup",
            address=data.get("address"),
            comment=data.get("comment"),
            full_name=data.get("name"),
        )
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
        await state.clear()
        await _render_cart(callback)
        return

    await state.clear()
    order = await db.get_order(order_id)
    items = await db.get_order_items(order_id)
    if order is None:
        await callback.answer("Заказ создан, но данные не найдены", show_alert=True)
        return

    method = "🚚 Доставка" if order["delivery_method"] == "delivery" else "🏪 Самовывоз"
    user_text = (
        f"✅ <b>Заказ №{order_id} принят!</b>\n\n"
        f"{order_items_text(items)}\n\n"
        f"📞 Телефон: {html.escape(order['phone'] or '—')}\n"
        f"📦 Получение: {method}\n"
        f"📍 Адрес: {html.escape(order['address'] or '—')}\n"
        f"💬 Комментарий: {html.escape(order['comment'] or '—')}\n\n"
        f"💰 <b>Итого: {fmt_price(order['total'])}</b>\n"
        f"Статус: {status_label(order['status'])}\n\n"
        "Администратор получил уведомление и скоро свяжется с вами."
    )
    await safe_edit(callback, user_text, main_menu_kb(is_admin(user_id), 0))

    username = f"@{order['username']}" if order["username"] else "—"
    full_name = order["full_name"] or "не указано"
    admin_text = (
        f"🔔 <b>НОВЫЙ ЗАКАЗ №{order_id}</b>\n\n"
        f"👤 Покупатель: {html.escape(str(full_name))}\n"
        f"🔗 Username: {html.escape(username)}\n"
        f"🆔 Telegram ID: <code>{order['user_id']}</code>\n"
        f"📞 Телефон: {html.escape(order['phone'] or '—')}\n"
        f"🕒 {order['created_at']}\n\n"
        f"📦 Получение: {method}\n"
        f"📍 Адрес: {html.escape(order['address'] or '—')}\n"
        f"💬 Комментарий: {html.escape(order['comment'] or '—')}\n\n"
        f"{order_items_text(items)}\n\n"
        f"💰 <b>Итого: {fmt_price(order['total'])}</b>\n"
        f"Статус: {status_label(order['status'])}"
    )
    from keyboards import admin_order_kb

    if callback.bot is not None:
        await notify_admins(callback.bot, admin_text, admin_order_kb(order_id, order["status"]))
    await callback.answer("Заказ оформлен")


@router.callback_query(F.data == "checkout:cancel")
async def checkout_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(
        callback,
        "❌ Оформление заказа отменено.",
        main_menu_kb(is_admin(callback.from_user.id), await db.get_cart_count(callback.from_user.id)),
    )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer("Клавиатура сброшена.", reply_markup=ReplyKeyboardRemove())


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
    method = "🚚 Доставка" if order["delivery_method"] == "delivery" else "🏪 Самовывоз"
    text = (
        f"📦 <b>Заказ №{order_id}</b>\n"
        f"🕒 {order['created_at']}\n"
        f"Статус: {status_label(order['status'])}\n\n"
        f"{order_items_text(items)}\n\n"
        f"📞 Телефон: {html.escape(order['phone'] or '—')}\n"
        f"📦 Получение: {method}\n"
        f"📍 Адрес: {html.escape(order['address'] or '—')}\n"
        f"💬 Комментарий: {html.escape(order['comment'] or '—')}\n\n"
        f"💰 <b>Итого: {fmt_price(order['total'])}</b>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать менеджеру", callback_data=f"chat:order:{order_id}")],
            [InlineKeyboardButton(text="⬅️ Мои заказы", callback_data="menu:orders")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )
    await safe_edit(callback, text, kb)
    await callback.answer()


# ------------------------------------------------------------- contacts & chat
@router.callback_query(F.data == "menu:contacts")
async def menu_contacts(callback: CallbackQuery) -> None:
    support = config.support_contact or "менеджер магазина"
    text = (
        "💬 <b>Связаться с менеджером</b>\n\n"
        f"🏪 Магазин: <b>{html.escape(config.shop_name)}</b>\n"
        f"👤 Поддержка: {html.escape(support)}\n\n"
        "Нажмите кнопку ниже, чтобы написать менеджеру прямо в боте. "
        "Сообщение будет привязано к вашему последнему заказу."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать менеджеру", callback_data="chat:manager")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )
    await safe_edit(callback, text, kb)
    await callback.answer()


async def _start_chat(callback: CallbackQuery, state: FSMContext, order_id: int) -> None:
    order = await db.get_order(order_id)
    if order is None or int(order["user_id"]) != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await state.set_state(ChatWithManager.active)
    await state.update_data(order_id=order_id)
    if callback.message is not None:
        await callback.message.answer(
            f"💬 <b>Чат с менеджером по заказу №{order_id}</b>\n\n"
            "Напишите сообщение или отправьте фото. "
            "Менеджер ответит вам в этом боте.",
            reply_markup=chat_end_kb(),
        )
    await callback.answer("Чат открыт")


@router.callback_query(F.data == "chat:manager")
async def chat_manager(callback: CallbackQuery, state: FSMContext) -> None:
    order = await db.get_last_user_order(callback.from_user.id)
    if order is None:
        await callback.answer("Сначала оформите заказ", show_alert=True)
        return
    await _start_chat(callback, state, int(order["id"]))


@router.callback_query(F.data.startswith("chat:order:"))
async def chat_order(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[2])
    await _start_chat(callback, state, order_id)


@router.callback_query(F.data == "chat:end")
async def chat_end(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback, "✅ Чат завершён. Чтобы написать снова, откройте «Связаться с менеджером».")
    await callback.answer()


@router.message(ChatWithManager.active)
async def user_chat_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    if message.from_user is None:
        return
    if not message.text and not message.photo:
        await message.answer("Отправьте текст или фото.")
        return

    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    header = (
        f"💬 <b>Сообщение от покупателя</b>\n"
        f"Заказ №{order_id or '—'}\n"
        f"👤 {html.escape(message.from_user.full_name)}\n"
        f"🔗 {html.escape(username)}\n"
        f"🆔 <code>{message.from_user.id}</code>\n\n"
    )
    from keyboards import admin_reply_kb

    reply_kb = admin_reply_kb(int(order_id)) if order_id else None
    if message.photo:
        caption = header + html.escape(message.caption or "📷 Фото")
        if message.bot is not None:
            await notify_admins_photo(message.bot, message.photo[-1].file_id, caption, reply_kb)
        await db.add_chat_message(
            user_id=message.from_user.id,
            sender="user",
            order_id=int(order_id) if order_id else None,
            message_type="photo",
            file_id=message.photo[-1].file_id,
            text=message.caption,
        )
    else:
        if message.bot is not None:
            await notify_admins(message.bot, header + html.escape(message.text or ""), reply_kb)
        await db.add_chat_message(
            user_id=message.from_user.id,
            sender="user",
            order_id=int(order_id) if order_id else None,
            message_type="text",
            text=message.text,
        )
    await message.answer("✅ Сообщение отправлено менеджеру. Можно отправить ещё одно.")


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()