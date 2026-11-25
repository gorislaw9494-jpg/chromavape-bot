from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from config import config
from database import db
from handlers import admin, user


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def _setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="help", description="Помощь"),
        ],
        scope=BotCommandScopeDefault(),
    )
    for admin_id in config.admin_ids:
        try:
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="Главное меню"),
                    BotCommand(command="admin", description="Админ-панель"),
                    BotCommand(command="help", description="Помощь"),
                ],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:  # admin might not have started the bot yet
            logging.warning("Не удалось установить команды для админа %s", admin_id)


async def main() -> None:
    _setup_logging()
    if not config.bot_token:
        logging.error(
            "BOT_TOKEN не задан. Скопируйте .env.example в .env и укажите токен бота."
        )
        return
    if not config.admin_ids:
        logging.warning(
            "ADMIN_IDS не задан — админ-панель будет недоступна. "
            "Укажите свой Telegram ID в .env"
        )

    await db.connect()
    logging.info("База данных подключена: %s", config.db_path)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)
    dp.include_router(user.router)

    try:
        await _setup_commands(bot)
        me = await bot.get_me()
        logging.info("Бот запущен: @%s", me.username)
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
