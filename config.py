from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> frozenset[int]:
    result: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            result.add(int(chunk))
    return frozenset(result)


@dataclass(frozen=True)
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()
    admin_ids: frozenset[int] = field(
        default_factory=lambda: _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
    )
    db_path: str = os.getenv("DB_PATH", "shop.db").strip() or "shop.db"
    shop_name: str = os.getenv("SHOP_NAME", "VapeShop").strip() or "VapeShop"
    support_contact: str = os.getenv("SUPPORT_CONTACT", "").strip()


config = Config()
