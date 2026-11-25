from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from utils import STATUS_EMOJI, fmt_price, truncate


def _btn(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def _markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ------------------------------------------------------------------ main menu
def main_menu_kb(admin: bool, cart_count: int) -> InlineKeyboardMarkup:
    cart_text = f"🧺 Корзина ({cart_count})" if cart_count else "🧺 Корзина"
    rows = [
        [_btn("🛍 Каталог товаров", "menu:catalog")],
        [_btn(cart_text, "menu:cart"), _btn("🧾 Оформить заказ", "menu:checkout")],
        [_btn("📦 Мои заказы", "menu:orders")],
        [_btn("💬 Связаться с менеджером", "menu:contacts")],
        [_btn("❓ Помощь", "menu:help")],
    ]
    if admin:
        rows.append([_btn("⚙️ Админ-панель", "admin:menu")])
    return _markup(rows)


def back_to_main_kb() -> InlineKeyboardMarkup:
    return _markup([[_btn("🏠 Главное меню", "menu:main")]])


# -------------------------------------------------------------------- catalog
def categories_kb(categories) -> InlineKeyboardMarkup:
    rows = [
        [_btn(f"{cat['emoji']} {cat['title']} ({cat['product_count']})", f"cat:{cat['id']}:0")]
        for cat in categories
    ]
    rows.append([_btn("🏠 Главное меню", "menu:main")])
    return _markup(rows)


def products_kb(products, category_id: int, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    for product in products:
        stock_note = "" if int(product["stock"]) > 0 else " · нет в наличии"
        text = f"{truncate(product['name'], 32)} — {fmt_price(product['price'])}{stock_note}"
        rows.append([_btn(text, f"product:{product['id']}:{category_id}:{page}")])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(_btn("⬅️", f"cat:{category_id}:{page - 1}"))
        nav.append(_btn(f"{page + 1}/{total_pages}", "noop"))
        if page + 1 < total_pages:
            nav.append(_btn("➡️", f"cat:{category_id}:{page + 1}"))
        rows.append(nav)

    rows.append([_btn("⬅️ Категории", "menu:catalog")])
    return _markup(rows)


def product_card_kb(product_id: int, category_id: int, page: int, in_stock: bool) -> InlineKeyboardMarkup:
    add_button = (
        _btn("🛒 В корзину", f"cart:add:{product_id}")
        if in_stock
        else _btn("😔 Нет в наличии", "noop")
    )
    return _markup(
        [
            [add_button],
            [_btn("⬅️ Назад", f"cat:{category_id}:{page}")],
        ]
    )


# ----------------------------------------------------------------------- cart
def cart_kb(items) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        if not int(item["is_active"]):
            continue
        product_id = int(item["product_id"])
        rows.append(
            [
                _btn("➖", f"cart:dec:{product_id}"),
                _btn(f"{truncate(item['name'], 18)} × {item['qty']}", "noop"),
                _btn("➕", f"cart:inc:{product_id}"),
                _btn("🗑", f"cart:del:{product_id}"),
            ]
        )

    if rows:
        rows.append([_btn("🧾 Оформить заказ", "cart:checkout")])
        rows.append([_btn("🧹 Очистить корзину", "cart:clear")])
    rows.append([_btn("🛍 Продолжить покупки", "menu:catalog")])
    rows.append([_btn("🏠 Главное меню", "menu:main")])
    return _markup(rows)


def cart_clear_confirm_kb() -> InlineKeyboardMarkup:
    return _markup(
        [
            [_btn("🗑 Да, очистить", "cart:clear_confirm")],
            [_btn("⬅️ Назад в корзину", "menu:cart")],
        ]
    )


def checkout_confirm_kb() -> InlineKeyboardMarkup:
    return _markup(
        [
            [_btn("✅ Подтвердить заказ", "order:confirm")],
            [_btn("❌ Отменить оформление", "checkout:cancel")],
        ]
    )


def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться контактом", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def skip_name_kb() -> InlineKeyboardMarkup:
    return _markup([[_btn("Пропустить", "checkout:skip_name")]])


def delivery_kb() -> InlineKeyboardMarkup:
    return _markup(
        [
            [_btn("🚚 Доставка", "checkout:delivery:delivery")],
            [_btn("🏪 Самовывоз", "checkout:delivery:pickup")],
        ]
    )


def skip_comment_kb() -> InlineKeyboardMarkup:
    return _markup([[_btn("Пропустить комментарий", "checkout:skip_comment")]])


def chat_end_kb() -> InlineKeyboardMarkup:
    return _markup([[_btn("Завершить чат", "chat:end")]])


# --------------------------------------------------------------------- orders
def user_orders_kb(orders) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn(
                f"№{order['id']} · {fmt_price(order['total'])} · {STATUS_EMOJI.get(order['status'], '')}",
                f"myorder:{order['id']}",
            )
        ]
        for order in orders
    ]
    rows.append([_btn("🏠 Главное меню", "menu:main")])
    return _markup(rows)


# ---------------------------------------------------------------------- admin
def admin_menu_kb() -> InlineKeyboardMarkup:
    return _markup(
        [
            [_btn("📦 Товары", "admin:products"), _btn("➕ Добавить товар", "admin:add")],
            [_btn("🧾 Заказы", "admin:orders:all:0"), _btn("📊 Статистика", "admin:stats")],
            [_btn("🏠 В главное меню", "menu:main")],
        ]
    )


def admin_categories_kb(categories) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn(
                f"{cat['emoji']} {cat['title']} ({cat['product_count']})",
                f"apcat:{cat['id']}:0",
            )
        ]
        for cat in categories
    ]
    rows.append([_btn("➕ Добавить товар", "admin:add")])
    rows.append([_btn("⬅️ Админ-меню", "admin:menu")])
    return _markup(rows)


def admin_products_kb(products, category_id: int, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    for product in products:
        mark = "✅" if int(product["is_active"]) else "🚫"
        text = (
            f"{mark} {truncate(product['name'], 24)} — {fmt_price(product['price'])} "
            f"· {product['stock']} шт."
        )
        rows.append([_btn(text, f"ap:{product['id']}:{category_id}:{page}")])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(_btn("⬅️", f"apcat:{category_id}:{page - 1}"))
        nav.append(_btn(f"{page + 1}/{total_pages}", "noop"))
        if page + 1 < total_pages:
            nav.append(_btn("➡️", f"apcat:{category_id}:{page + 1}"))
        rows.append(nav)

    rows.append([_btn("➕ Добавить товар", "admin:add")])
    rows.append([_btn("⬅️ Категории", "admin:products")])
    return _markup(rows)


def admin_product_kb(product_id: int, category_id: int, page: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "🙈 Скрыть" if is_active else "👁 Показать"
    return _markup(
        [
            [
                _btn("✏️ Название", f"ap:edit:{product_id}:name"),
                _btn("💰 Цена", f"ap:edit:{product_id}:price"),
            ],
            [
                _btn("📝 Описание", f"ap:edit:{product_id}:description"),
                _btn("📷 Фото", f"ap:edit:{product_id}:photo"),
            ],
            [
                _btn("📦 Остаток", f"ap:edit:{product_id}:stock"),
                _btn(toggle_text, f"ap:toggle:{product_id}:{category_id}:{page}"),
            ],
            [_btn("🗑 Удалить", f"ap:delete:{product_id}:{category_id}:{page}")],
            [_btn("⬅️ Назад", f"apcat:{category_id}:{page}")],
        ]
    )


def admin_delete_confirm_kb(product_id: int, category_id: int, page: int) -> InlineKeyboardMarkup:
    return _markup(
        [
            [_btn("🗑 Да, удалить", f"ap:delconfirm:{product_id}:{category_id}:{page}")],
            [_btn("⬅️ Отмена", f"ap:{product_id}:{category_id}:{page}")],
        ]
    )


def admin_orders_kb(orders, status_filter: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    for order in orders:
        name = order["full_name"] or order["username"] or f"id{order['user_id']}"
        text = (
            f"№{order['id']} · {truncate(name, 18)} · {fmt_price(order['total'])} "
            f"· {STATUS_EMOJI.get(order['status'], '')}"
        )
        rows.append([_btn(text, f"aorder:{order['id']}")])

    filters = []
    filters.append(_btn("🆕 Новые", "admin:orders:new:0"))
    filters.append(_btn("📋 Все", "admin:orders:all:0"))
    rows.append(filters)

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(_btn("⬅️", f"admin:orders:{status_filter}:{page - 1}"))
        nav.append(_btn(f"{page + 1}/{total_pages}", "noop"))
        if page + 1 < total_pages:
            nav.append(_btn("➡️", f"admin:orders:{status_filter}:{page + 1}"))
        rows.append(nav)

    rows.append([_btn("⬅️ Админ-меню", "admin:menu")])
    return _markup(rows)


def admin_order_kb(order_id: int, status: str) -> InlineKeyboardMarkup:
    rows = []
    if status == "new":
        rows.append([_btn("✅ Принять заказ", f"aos:{order_id}:accepted")])
    elif status == "accepted":
        rows.append([_btn("🛠 Заказ в работе", f"aos:{order_id}:processing")])
    elif status == "processing":
        rows.append([_btn("🚚 Отправить", f"aos:{order_id}:shipped")])
    if status in {"accepted", "processing", "shipped"}:
        rows.append([_btn("🏁 Заказ выполнен", f"aos:{order_id}:completed")])
    if status not in {"completed", "cancelled"}:
        rows.append([_btn("❌ Отменить заказ", f"aos:{order_id}:cancelled")])
    rows.append([_btn("💬 Ответить покупателю", f"admin:reply:{order_id}")])
    rows.append([_btn("⬅️ К заказам", "admin:orders:all:0")])
    return _markup(rows)


def admin_reply_kb(order_id: int) -> InlineKeyboardMarkup:
    return _markup([[_btn("💬 Ответить покупателю", f"admin:reply:{order_id}")]])


def buyer_reply_kb(order_id: int) -> InlineKeyboardMarkup:
    return _markup([[_btn("💬 Ответить менеджеру", f"chat:order:{order_id}")]])


def add_product_confirm_kb() -> InlineKeyboardMarkup:
    return _markup(
        [
            [_btn("✅ Сохранить товар", "admin:addconfirm")],
            [_btn("❌ Отмена", "admin:cancel")],
        ]
    )
