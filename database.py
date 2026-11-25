from __future__ import annotations

from typing import Any, Optional

import aiosqlite

from config import config

CATEGORY_SEED = [
    ("liquids", "Жидкости", "🧴", 1),
    ("pods", "Под системы", "💨", 2),
    ("consumables", "Расходники", "🔧", 3),
]

ORDER_STATUSES = ("new", "accepted", "processing", "shipped", "completed", "cancelled")

STATUS_TRANSITIONS = {
    "new": {"accepted", "cancelled"},
    "accepted": {"processing", "shipped", "completed", "cancelled"},
    "processing": {"shipped", "completed", "cancelled"},
    "shipped": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL CHECK (price >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    photo_file_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_seen TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS cart_items (
    user_id INTEGER NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    qty INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (user_id, product_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    full_name TEXT,
    phone TEXT,
    delivery_method TEXT,
    address TEXT,
    comment TEXT,
    total INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER,
    product_name TEXT NOT NULL,
    price INTEGER NOT NULL,
    qty INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS order_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    changed_by INTEGER,
    changed_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    user_id INTEGER NOT NULL,
    sender TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    text TEXT,
    file_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_status_history_order ON order_status_history(order_id);
CREATE INDEX IF NOT EXISTS idx_chat_order ON chat_messages(order_id);
CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_messages(user_id);
"""


class OrderError(Exception):
    """Raised when an order cannot be created."""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def connect(self) -> None:
        # isolation_level=None -> autocommit; explicit transactions are used
        # where needed (BEGIN IMMEDIATE / COMMIT / ROLLBACK).
        self._conn = await aiosqlite.connect(self.path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._migrate_schema()
        for slug, title, emoji, sort_order in CATEGORY_SEED:
            await self._conn.execute(
                """INSERT OR IGNORE INTO categories (slug, title, emoji, sort_order)
                   VALUES (?, ?, ?, ?)""",
                (slug, title, emoji, sort_order),
            )

    async def _migrate_schema(self) -> None:
        """Add new order columns to an existing database without losing data."""
        async with self.conn.execute("PRAGMA table_info(orders)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        additions = {
            "phone": "TEXT",
            "delivery_method": "TEXT",
            "address": "TEXT",
            "comment": "TEXT",
        }
        for name, sql_type in additions.items():
            if name not in columns:
                await self.conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {sql_type}")
        await self.conn.execute(
            """INSERT INTO order_status_history (order_id, status, changed_at)
               SELECT o.id, o.status, o.created_at
               FROM orders o
               WHERE NOT EXISTS (
                   SELECT 1 FROM order_status_history h WHERE h.order_id = o.id
               )"""
        )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------ helpers
    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> Optional[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    # ------------------------------------------------------------------- users
    async def add_user(self, tg_id: int, username: str | None, first_name: str | None) -> None:
        await self.conn.execute(
            """INSERT INTO users (tg_id, username, first_name, last_seen)
               VALUES (?, ?, ?, datetime('now', 'localtime'))
               ON CONFLICT(tg_id) DO UPDATE SET
                   username = excluded.username,
                   first_name = excluded.first_name,
                   last_seen = datetime('now', 'localtime')""",
            (tg_id, username, first_name),
        )

    async def get_user(self, tg_id: int) -> Optional[aiosqlite.Row]:
        return await self.fetch_one("SELECT * FROM users WHERE tg_id = ?", (tg_id,))

    # -------------------------------------------------------------- categories
    async def get_categories(self, only_active_products: bool = True) -> list[aiosqlite.Row]:
        join_condition = "p.category_id = c.id"
        if only_active_products:
            join_condition += " AND p.is_active = 1"
        return await self.fetch_all(
            f"""SELECT c.*, COUNT(p.id) AS product_count
                FROM categories c
                LEFT JOIN products p ON {join_condition}
                GROUP BY c.id
                ORDER BY c.sort_order, c.id"""
        )

    async def get_category(self, category_id: int) -> Optional[aiosqlite.Row]:
        return await self.fetch_one("SELECT * FROM categories WHERE id = ?", (category_id,))

    # ---------------------------------------------------------------- products
    async def count_products(self, category_id: int, only_active: bool = True) -> int:
        sql = "SELECT COUNT(*) AS cnt FROM products WHERE category_id = ?"
        if only_active:
            sql += " AND is_active = 1"
        row = await self.fetch_one(sql, (category_id,))
        return int(row["cnt"]) if row else 0

    async def get_products_page(
        self,
        category_id: int,
        page: int = 0,
        per_page: int = 8,
        only_active: bool = True,
    ) -> list[aiosqlite.Row]:
        sql = "SELECT * FROM products WHERE category_id = ?"
        if only_active:
            sql += " AND is_active = 1"
        sql += " ORDER BY id LIMIT ? OFFSET ?"
        return await self.fetch_all(sql, (category_id, per_page, page * per_page))

    async def get_product(self, product_id: int) -> Optional[aiosqlite.Row]:
        return await self.fetch_one("SELECT * FROM products WHERE id = ?", (product_id,))

    async def create_product(
        self,
        category_id: int,
        name: str,
        price: int,
        description: str = "",
        photo_file_id: str | None = None,
        stock: int = 0,
    ) -> int:
        cursor = await self.conn.execute(
            """INSERT INTO products (category_id, name, price, description, photo_file_id, stock)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (category_id, name, price, description, photo_file_id, stock),
        )
        return int(cursor.lastrowid or 0)

    async def update_product(self, product_id: int, field: str, value: Any) -> None:
        allowed = {"name", "description", "price", "stock", "photo_file_id", "is_active"}
        if field not in allowed:
            raise ValueError(f"Unsupported product field: {field}")
        await self.conn.execute(
            f"UPDATE products SET {field} = ? WHERE id = ?", (value, product_id)
        )

    async def delete_product(self, product_id: int) -> None:
        await self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,))

    # -------------------------------------------------------------------- cart
    async def get_cart_items(self, user_id: int) -> list[aiosqlite.Row]:
        return await self.fetch_all(
            """SELECT ci.product_id, ci.qty, p.name, p.price, p.stock, p.is_active, p.photo_file_id
               FROM cart_items ci
               JOIN products p ON p.id = ci.product_id
               WHERE ci.user_id = ?
               ORDER BY ci.product_id""",
            (user_id,),
        )

    async def get_cart_count(self, user_id: int) -> int:
        row = await self.fetch_one(
            """SELECT COALESCE(SUM(ci.qty), 0) AS cnt
               FROM cart_items ci
               JOIN products p ON p.id = ci.product_id
               WHERE ci.user_id = ? AND p.is_active = 1""",
            (user_id,),
        )
        return int(row["cnt"]) if row else 0

    async def get_cart_item(self, user_id: int, product_id: int) -> Optional[aiosqlite.Row]:
        return await self.fetch_one(
            "SELECT * FROM cart_items WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )

    async def add_to_cart(self, user_id: int, product_id: int) -> str:
        product = await self.get_product(product_id)
        if product is None or not product["is_active"] or int(product["stock"]) <= 0:
            return "unavailable"
        item = await self.get_cart_item(user_id, product_id)
        current_qty = int(item["qty"]) if item else 0
        if current_qty + 1 > int(product["stock"]):
            return "limit"
        await self.conn.execute(
            """INSERT INTO cart_items (user_id, product_id, qty) VALUES (?, ?, 1)
               ON CONFLICT(user_id, product_id) DO UPDATE SET qty = qty + 1""",
            (user_id, product_id),
        )
        return "ok"

    async def change_cart_qty(self, user_id: int, product_id: int, delta: int) -> str:
        product = await self.get_product(product_id)
        if product is None or not product["is_active"]:
            return "unavailable"
        item = await self.get_cart_item(user_id, product_id)
        if item is None:
            return "empty"
        new_qty = int(item["qty"]) + delta
        if new_qty <= 0:
            await self.conn.execute(
                "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
                (user_id, product_id),
            )
            return "removed"
        if new_qty > int(product["stock"]):
            return "limit"
        await self.conn.execute(
            "UPDATE cart_items SET qty = ? WHERE user_id = ? AND product_id = ?",
            (new_qty, user_id, product_id),
        )
        return "ok"

    async def remove_cart_item(self, user_id: int, product_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )

    async def clear_cart(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------------ orders
    async def create_order(
        self,
        user_id: int,
        phone: str,
        delivery_method: str,
        address: str | None = None,
        comment: str | None = None,
        full_name: str | None = None,
    ) -> int:
        user = await self.get_user(user_id)
        username = user["username"] if user else None
        display_name = (full_name or (user["first_name"] if user else "") or "").strip() or None

        # BEGIN IMMEDIATE before reading the cart protects against double-click
        # creating two orders from the same cart.
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            items = [
                item for item in await self.get_cart_items(user_id) if int(item["is_active"])
            ]
            if not items:
                raise OrderError("empty_cart")

            for item in items:
                if int(item["qty"]) > int(item["stock"]):
                    raise OrderError(f"stock:{item['name']}")

            total = sum(int(item["price"]) * int(item["qty"]) for item in items)
            cursor = await self.conn.execute(
                """INSERT INTO orders
                       (user_id, username, full_name, phone, delivery_method,
                        address, comment, total, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', datetime('now', 'localtime'))""",
                (
                    user_id,
                    username,
                    display_name,
                    phone,
                    delivery_method,
                    address,
                    comment,
                    total,
                ),
            )
            order_id = int(cursor.lastrowid or 0)
            for item in items:
                await self.conn.execute(
                    """INSERT INTO order_items (order_id, product_id, product_name, price, qty)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        order_id,
                        int(item["product_id"]),
                        item["name"],
                        int(item["price"]),
                        int(item["qty"]),
                    ),
                )
                await self.conn.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ?",
                    (int(item["qty"]), int(item["product_id"])),
                )
            await self.conn.execute(
                """INSERT INTO order_status_history (order_id, status, changed_by)
                   VALUES (?, 'new', ?)""",
                (order_id, user_id),
            )
            await self.conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
            await self.conn.execute("COMMIT")
        except Exception:
            await self.conn.execute("ROLLBACK")
            raise
        return order_id

    async def get_order(self, order_id: int) -> Optional[aiosqlite.Row]:
        return await self.fetch_one("SELECT * FROM orders WHERE id = ?", (order_id,))

    async def get_order_items(self, order_id: int) -> list[aiosqlite.Row]:
        return await self.fetch_all(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
        )

    async def get_user_orders(self, user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        return await self.fetch_all(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

    async def get_last_user_order(self, user_id: int) -> Optional[aiosqlite.Row]:
        return await self.fetch_one(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )

    async def add_chat_message(
        self,
        user_id: int,
        sender: str,
        text: str | None = None,
        file_id: str | None = None,
        order_id: int | None = None,
        message_type: str = "text",
    ) -> int:
        cursor = await self.conn.execute(
            """INSERT INTO chat_messages
                   (order_id, user_id, sender, message_type, text, file_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (order_id, user_id, sender, message_type, text, file_id),
        )
        return int(cursor.lastrowid or 0)

    async def get_chat_history(
        self, order_id: int, limit: int = 10
    ) -> list[aiosqlite.Row]:
        return await self.fetch_all(
            """SELECT * FROM chat_messages
               WHERE order_id = ?
               ORDER BY id DESC LIMIT ?""",
            (order_id, limit),
        )

    async def get_status_history(self, order_id: int) -> list[aiosqlite.Row]:
        return await self.fetch_all(
            """SELECT * FROM order_status_history
               WHERE order_id = ? ORDER BY id""",
            (order_id,),
        )

    async def count_orders(self, status: str | None = None) -> int:
        if status is None:
            row = await self.fetch_one("SELECT COUNT(*) AS cnt FROM orders")
        else:
            row = await self.fetch_one("SELECT COUNT(*) AS cnt FROM orders WHERE status = ?", (status,))
        return int(row["cnt"]) if row else 0

    async def get_orders_page(
        self, status: str | None = None, page: int = 0, per_page: int = 8
    ) -> list[aiosqlite.Row]:
        if status is None:
            return await self.fetch_all(
                "SELECT * FROM orders ORDER BY id DESC LIMIT ? OFFSET ?",
                (per_page, page * per_page),
            )
        return await self.fetch_all(
            "SELECT * FROM orders WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (status, per_page, page * per_page),
        )

    async def update_order_status(
        self, order_id: int, new_status: str, changed_by: int | None = None
    ) -> str | None:
        """Change order status. Returns previous status or None if change is not allowed."""
        order = await self.get_order(order_id)
        if order is None:
            return None
        old_status = order["status"]
        if new_status == old_status or new_status not in STATUS_TRANSITIONS.get(old_status, set()):
            return None

        if new_status == "cancelled":
            items = await self.get_order_items(order_id)
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                await self.conn.execute(
                    "UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id)
                )
                for item in items:
                    if item["product_id"] is not None:
                        await self.conn.execute(
                            "UPDATE products SET stock = stock + ? WHERE id = ?",
                            (int(item["qty"]), int(item["product_id"])),
                        )
                await self.conn.execute(
                    """INSERT INTO order_status_history (order_id, status, changed_by)
                       VALUES (?, ?, ?)""",
                    (order_id, new_status, changed_by),
                )
                await self.conn.execute("COMMIT")
            except Exception:
                await self.conn.execute("ROLLBACK")
                raise
        else:
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                await self.conn.execute(
                    "UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id)
                )
                await self.conn.execute(
                    """INSERT INTO order_status_history (order_id, status, changed_by)
                       VALUES (?, ?, ?)""",
                    (order_id, new_status, changed_by),
                )
                await self.conn.execute("COMMIT")
            except Exception:
                await self.conn.execute("ROLLBACK")
                raise
        return old_status

    async def get_stats(self) -> dict[str, int]:
        products = await self.fetch_one(
            "SELECT COUNT(*) AS total, COALESCE(SUM(is_active), 0) AS active FROM products"
        )
        users = await self.fetch_one("SELECT COUNT(*) AS cnt FROM users")
        orders = await self.fetch_all("SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status")
        orders_by_status = {row["status"]: int(row["cnt"]) for row in orders}
        return {
            "products_total": int(products["total"]) if products else 0,
            "products_active": int(products["active"]) if products else 0,
            "users": int(users["cnt"]) if users else 0,
            "orders_total": sum(orders_by_status.values()),
            "orders_new": orders_by_status.get("new", 0),
            "orders_accepted": orders_by_status.get("accepted", 0),
            "orders_shipped": orders_by_status.get("shipped", 0),
            "orders_completed": orders_by_status.get("completed", 0),
            "orders_cancelled": orders_by_status.get("cancelled", 0),
        }


db = Database(config.db_path)
