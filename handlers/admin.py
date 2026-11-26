from __future__ import annotations

import html
import math

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import config
from database import db
from filters import IsAdmin
from keyboards import (
    add_product_confirm_kb,
    admin_categories_kb,
    admin_delete_confirm_kb,
    admin_menu_kb,
    admin_order_kb,
    admin_orders_kb,
    admin_product_kb,
    admin_products_kb,
    buyer_reply_kb,
)
from states import AddProduct, EditProduct, ReplyToBuyer
from utils import (
    fmt_price,
    notify_admins,
    order_items_text,
    replace_with_photo_or_text,
    safe_delete,
    safe_edit,
    status_label,
)

router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PAGE_SIZE = 8
EDIT_PROMPTS = {
    "name": "Введите новое название товара:",
    "price": "Введите новую цену в рублях (целое число):",
    "description": "Введите новое описание товара:",
    "stock": "Введите новый остаток на складе (целое число):",
    "photo": "Отправьте новое фото товара или напишите «-», чтобы удалить фото:",
}


def _order_admin_text(order, items) -> str:
    username = f"@{order['username']}" if order["username"] else "—"
    full_name = order["full_name"] or "не указано"
    method = "🚚 Доставка" if order["delivery_method"] == "delivery" else "🏪 Самовывоз"
    return (
        f"🧾 <b>Заказ №{order['id']}</b>\n\n"
        f"👤 Покупатель: {html.escape(str(full_name))}\n"
        f"🔗 Username: {html.escape(username)}\n"
        f"🆔 Telegram ID: <code>{order['user_id']}</code>\n"
        f"📞 Телефон: {html.escape(order['phone'] or '—')}\n"
        f"🕒 {order['created_at']}\n"
        f"Статус: {status_label(order['status'])}\n\n"
        f"📦 Получение: {method}\n"
        f"📍 Адрес: {html.escape(order['address'] or '—')}\n"
        f"💬 Комментарий: {html.escape(order['comment'] or '—')}\n\n"
        f"{order_items_text(items)}\n\n"
        f"💰 <b>Итого: {fmt_price(order['total'])}</b>"
    )


# ------------------------------------------------------------------ admin menu
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    stats = await db.get_stats()
    text = (
        "⚙️ <b>Админ-панель</b>\n\n"
        f"📦 Товаров: {stats['products_active']} активных из {stats['products_total']}\n"
        f"🧾 Заказов: {stats['orders_total']} (новых: {stats['orders_new']})\n"
        f"👥 Пользователей: {stats['users']}"
    )
    await message.answer(text, reply_markup=admin_menu_kb())


@router.callback_query(F.data == "admin:menu")
async def admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    stats = await db.get_stats()
    text = (
        "⚙️ <b>Админ-панель</b>\n\n"
        f"📦 Товаров: {stats['products_active']} активных из {stats['products_total']}\n"
        f"🧾 Заказов: {stats['orders_total']} (новых: {stats['orders_new']})\n"
        f"👥 Пользователей: {stats['users']}"
    )
    await safe_edit(callback, text, admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery) -> None:
    stats = await db.get_stats()
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b>\n"
        f"📦 Товаров: <b>{stats['products_total']}</b> (активных: {stats['products_active']})\n\n"
        f"🧾 Заказов всего: <b>{stats['orders_total']}</b>\n"
        f"🆕 Новых: {stats['orders_new']}\n"
        f"✅ Принятых: {stats['orders_accepted']}\n"
        f"🚚 Отправленных: {stats['orders_shipped']}\n"
        f"🏁 Выполненных: {stats['orders_completed']}\n"
        f"❌ Отменённых: {stats['orders_cancelled']}"
    )
    await safe_edit(callback, text, admin_menu_kb())
    await callback.answer()


# -------------------------------------------------------------- admin products
@router.callback_query(F.data == "admin:products")
async def admin_products(callback: CallbackQuery) -> None:
    categories = await db.get_categories(only_active_products=False)
    text = "📦 <b>Товары</b>\n\nВыберите категорию для управления товарами:"
    await safe_edit(callback, text, admin_categories_kb(categories))
    await callback.answer()


@router.callback_query(F.data.startswith("apcat:"))
async def admin_category_products(callback: CallbackQuery) -> None:
    _, category_id_raw, page_raw = callback.data.split(":")
    category_id = int(category_id_raw)
    page = max(0, int(page_raw))

    category = await db.get_category(category_id)
    if category is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    total = await db.count_products(category_id, only_active=False)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, total_pages - 1)
    products = await db.get_products_page(category_id, page, PAGE_SIZE, only_active=False)

    if not products:
        text = (
            f"{category['emoji']} <b>{html.escape(category['title'])}</b>\n\n"
            "Товаров пока нет. Добавьте первый товар."
        )
    else:
        text = (
            f"{category['emoji']} <b>{html.escape(category['title'])}</b>\n\n"
            "Нажмите на товар для редактирования:"
        )
    await safe_edit(callback, text, admin_products_kb(products, category_id, page, total_pages))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^ap:\d+:\d+:\d+$"))
async def admin_product_card(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    product_id = int(parts[1])
    category_id = int(parts[2])
    page = int(parts[3])

    product = await db.get_product(product_id)
    if product is None:
        await callback.answer("Товар не найден", show_alert=True)
        return

    status = "✅ Активен" if int(product["is_active"]) else "🚫 Скрыт"
    description = html.escape(product["description"]) if product["description"] else "—"
    caption = (
        f"<b>{html.escape(product['name'])}</b>\n\n"
        f"📝 {description}\n\n"
        f"💰 Цена: <b>{fmt_price(product['price'])}</b>\n"
        f"📦 Остаток: {product['stock']} шт.\n"
        f"Статус: {status}\n"
        f"🆔 ID: {product_id}"
    )
    await replace_with_photo_or_text(
        callback,
        product["photo_file_id"],
        caption,
        admin_product_kb(product_id, category_id, page, bool(int(product["is_active"]))),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ap:toggle:"))
async def admin_product_toggle(callback: CallbackQuery) -> None:
    _, _, product_id_raw, category_id_raw, page_raw = callback.data.split(":")
    product_id = int(product_id_raw)
    product = await db.get_product(product_id)
    if product is None:
        await callback.answer("Товар не найден", show_alert=True)
        return
    new_value = 0 if int(product["is_active"]) else 1
    await db.update_product(product_id, "is_active", new_value)
    await callback.answer("👁 Товар показан" if new_value else "🙈 Товар скрыт")
    await admin_product_card(
        _FakeCallback(callback, f"ap:{product_id}:{category_id_raw}:{page_raw}")
    )


class _FakeCallback:
    """Lightweight wrapper so we can re-render a product card from a callback."""

    def __init__(self, original: CallbackQuery, data: str) -> None:
        self._original = original
        self.data = data

    def __getattr__(self, item):
        return getattr(self._original, item)


@router.callback_query(F.data.startswith("ap:delete:"))
async def admin_product_delete_ask(callback: CallbackQuery) -> None:
    _, _, product_id_raw, category_id_raw, page_raw = callback.data.split(":")
    product = await db.get_product(int(product_id_raw))
    if product is None:
        await callback.answer("Товар не найден", show_alert=True)
        return
    text = (
        f"🗑 Удалить товар «<b>{html.escape(product['name'])}</b>»?\n\n"
        "Действие необратимо."
    )
    await safe_edit(
        callback,
        text,
        admin_delete_confirm_kb(int(product_id_raw), int(category_id_raw), int(page_raw)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ap:delconfirm:"))
async def admin_product_delete(callback: CallbackQuery) -> None:
    _, _, product_id_raw, category_id_raw, page_raw = callback.data.split(":")
    await db.delete_product(int(product_id_raw))
    await callback.answer("🗑 Товар удалён")
    await admin_category_products(
        _FakeCallback(callback, f"apcat:{category_id_raw}:{page_raw}")
    )


# ---------------------------------------------------------------- edit product
@router.callback_query(F.data.startswith("ap:edit:"))
async def admin_product_edit(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, product_id_raw, field = callback.data.split(":")
    product_id = int(product_id_raw)
    product = await db.get_product(product_id)
    if product is None:
        await callback.answer("Товар не найден", show_alert=True)
        return
    if field not in EDIT_PROMPTS:
        await callback.answer("Неизвестное поле", show_alert=True)
        return

    await state.set_state(EditProduct.value)
    await state.update_data(product_id=product_id, field=field)
    await callback.message.answer(
        f"✏️ Редактирование: <b>{html.escape(product['name'])}</b>\n\n{EDIT_PROMPTS[field]}"
    )
    await callback.answer()


@router.message(EditProduct.value)
async def admin_product_edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = int(data["product_id"])
    field = data["field"]
    product = await db.get_product(product_id)
    if product is None:
        await state.clear()
        await message.answer("Товар не найден.")
        return

    if field == "photo":
        if message.photo:
            new_value = message.photo[-1].file_id
        elif message.text and message.text.strip() == "-":
            new_value = None
        else:
            await message.answer("Отправьте фото или «-», чтобы удалить фото.")
            return
    elif field in {"price", "stock"}:
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer("Введите целое неотрицательное число.")
            return
        new_value = int(raw)
    else:
        raw = (message.text or "").strip()
        if not raw:
            await message.answer("Значение не может быть пустым.")
            return
        new_value = raw

    db_field = "photo_file_id" if field == "photo" else field
    await db.update_product(product_id, db_field, new_value)
    await state.clear()
    await message.answer("✅ Изменения сохранены.")
    await message.answer(
        "Откройте товар заново:",
        reply_markup=admin_menu_kb(),
    )


# ----------------------------------------------------------------- add product
@router.callback_query(F.data == "admin:add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddProduct.name)
    await state.update_data()
    categories = await db.get_categories(only_active_products=False)
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [InlineKeyboardButton(text=f"{c['emoji']} {c['title']}", callback_data=f"admin:addcat:{c['id']}")]
        for c in categories
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel")])
    await callback.message.answer(
        "➕ <b>Добавление товара</b>\n\nВыберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:addcat:"))
async def admin_add_category(callback: CallbackQuery, state: FSMContext) -> None:
    category_id = int(callback.data.split(":")[2])
    category = await db.get_category(category_id)
    if category is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    await state.update_data(category_id=category_id)
    await state.set_state(AddProduct.name)
    await callback.message.answer(
        f"Категория: <b>{category['emoji']} {html.escape(category['title'])}</b>\n\n"
        "Введите название товара:"
    )
    await callback.answer()


@router.message(AddProduct.name)
async def admin_add_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым. Введите название:")
        return
    await state.update_data(name=name)
    await state.set_state(AddProduct.price)
    await message.answer("Введите цену в рублях (целое число):")


@router.message(AddProduct.price)
async def admin_add_price(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Цена должна быть целым неотрицательным числом. Введите цену:")
        return
    await state.update_data(price=int(raw))
    await state.set_state(AddProduct.description)
    await message.answer("Введите описание товара (или «-», чтобы пропустить):")


@router.message(AddProduct.description)
async def admin_add_description(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    description = "" if raw == "-" else raw
    await state.update_data(description=description)
    await state.set_state(AddProduct.photo)
    await message.answer("Отправьте фото товара (или «-», чтобы без фото):")


@router.message(AddProduct.photo)
async def admin_add_photo(message: Message, state: FSMContext) -> None:
    if message.photo:
        photo_file_id = message.photo[-1].file_id
    elif message.text and message.text.strip() == "-":
        photo_file_id = None
    else:
        await message.answer("Отправьте фото или «-», чтобы без фото.")
        return
    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(AddProduct.stock)
    await message.answer("Введите количество на складе (целое число, можно 0):")


@router.message(AddProduct.stock)
async def admin_add_stock(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Остаток должен быть целым неотрицательным числом. Введите остаток:")
        return
    await state.update_data(stock=int(raw))
    await state.set_state(AddProduct.confirm)

    data = await state.get_data()
    category = await db.get_category(int(data["category_id"]))
    category_title = f"{category['emoji']} {category['title']}" if category else "—"
    photo_note = "есть" if data.get("photo_file_id") else "нет"
    description = html.escape(data.get("description") or "—")

    text = (
        "🧾 <b>Проверьте данные товара</b>\n\n"
        f"📦 Категория: {html.escape(category_title)}\n"
        f"🏷 Название: <b>{html.escape(data['name'])}</b>\n"
        f"💰 Цена: <b>{fmt_price(data['price'])}</b>\n"
        f"📝 Описание: {description}\n"
        f"📷 Фото: {photo_note}\n"
        f"📦 Остаток: {data['stock']} шт.\n\n"
        "Сохранить товар?"
    )
    await message.answer(text, reply_markup=add_product_confirm_kb())


@router.callback_query(AddProduct.confirm, F.data == "admin:addconfirm")
async def admin_add_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    if not data.get("name") or "category_id" not in data:
        await callback.answer("Данные утеряны, начните заново", show_alert=True)
        return
    product_id = await db.create_product(
        category_id=int(data["category_id"]),
        name=data["name"],
        price=int(data["price"]),
        description=data.get("description", ""),
        photo_file_id=data.get("photo_file_id"),
        stock=int(data.get("stock", 0)),
    )
    await callback.answer("✅ Товар добавлен")
    await safe_edit(
        callback,
        f"✅ Товар «<b>{html.escape(data['name'])}</b>» добавлен (ID: {product_id}).",
        admin_menu_kb(),
    )


@router.callback_query(F.data == "admin:cancel")
async def admin_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback, "❌ Действие отменено.", admin_menu_kb())
    await callback.answer()


# --------------------------------------------------------------- admin orders
@router.callback_query(F.data.startswith("admin:orders:"))
async def admin_orders(callback: CallbackQuery) -> None:
    _, _, status_filter, page_raw = callback.data.split(":")
    page = max(0, int(page_raw))
    status = None if status_filter == "all" else status_filter

    total = await db.count_orders(status)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, total_pages - 1)
    orders = await db.get_orders_page(status, page, PAGE_SIZE)

    title = "🆕 Новые заказы" if status == "new" else "🧾 Все заказы"
    if not orders:
        text = f"<b>{title}</b>\n\nЗаказов нет."
    else:
        text = f"<b>{title}</b>\n\nНажмите на заказ для управления:"
    await safe_edit(callback, text, admin_orders_kb(orders, status_filter, page, total_pages))
    await callback.answer()


@router.callback_query(F.data.startswith("aorder:"))
async def admin_order_card(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    items = await db.get_order_items(order_id)
    await safe_edit(callback, _order_admin_text(order, items), admin_order_kb(order_id, order["status"]))
    await callback.answer()


@router.callback_query(F.data.startswith("aos:"))
async def admin_order_status(callback: CallbackQuery) -> None:
    _, order_id_raw, new_status = callback.data.split(":")
    order_id = int(order_id_raw)
    old_status = await db.update_order_status(
        order_id, new_status, changed_by=callback.from_user.id
    )
    if old_status is None:
        await callback.answer("Это изменение недоступно", show_alert=True)
        return

    await callback.answer(f"Статус: {status_label(new_status)}")
    order = await db.get_order(order_id)
    if order is None:
        return
    try:
        await callback.bot.send_message(
            int(order["user_id"]),
            f"🔔 Статус вашего заказа №{order_id} изменён: "
            f"<b>{status_label(new_status)}</b>",
        )
    except Exception:
        pass

    items = await db.get_order_items(order_id)
    await safe_edit(callback, _order_admin_text(order, items), admin_order_kb(order_id, order["status"]))


@router.message(Command("cancel"))
async def admin_cancel_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено. Откройте /admin для админ-панели.")


@router.callback_query(F.data.startswith("admin:reply:"))
async def admin_reply_start(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[2])
    order = await db.get_order(order_id)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await state.set_state(ReplyToBuyer.message)
    await state.update_data(order_id=order_id, user_id=int(order["user_id"]))
    if callback.message is not None:
        await callback.message.answer(
            f"💬 <b>Ответ покупателю по заказу №{order_id}</b>\n\n"
            "Отправьте текст или фото. Оно будет доставлено покупателю в Telegram.\n"
            "Для отмены отправьте /cancel."
        )
    await callback.answer("Введите сообщение")


@router.message(ReplyToBuyer.message)
async def admin_reply_send(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data.get("order_id") or 0)
    user_id = int(data.get("user_id") or 0)
    if not order_id or not user_id:
        await state.clear()
        await message.answer("Не удалось определить заказ. Откройте заказ заново.")
        return
    if not message.text and not message.photo:
        await message.answer("Отправьте текст или фото.")
        return

    try:
        if message.photo:
            caption = (
                f"💬 <b>Ответ менеджера по заказу №{order_id}</b>\n\n"
                f"{html.escape(message.caption or '📷 Фото')}"
            )
            await message.bot.send_photo(
                user_id,
                photo=message.photo[-1].file_id,
                caption=caption,
                reply_markup=buyer_reply_kb(order_id),
            )
            await db.add_chat_message(
                user_id=user_id,
                sender="admin",
                order_id=order_id,
                message_type="photo",
                file_id=message.photo[-1].file_id,
                text=message.caption,
            )
        else:
            text = (
                f"💬 <b>Ответ менеджера по заказу №{order_id}</b>\n\n"
                f"{html.escape(message.text or '')}"
            )
            await message.bot.send_message(
                user_id, text, reply_markup=buyer_reply_kb(order_id)
            )
            await db.add_chat_message(
                user_id=user_id,
                sender="admin",
                order_id=order_id,
                message_type="text",
                text=message.text,
            )
    except Exception:
        await state.clear()
        await message.answer(
            "❌ Не удалось доставить сообщение. Возможно, покупатель заблокировал бота."
        )
        return

    await state.clear()
    await message.answer(f"✅ Сообщение доставлено покупателю по заказу №{order_id}.")
