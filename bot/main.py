from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import BotCommand, ErrorEvent

from .config import load
from .handlers import Service, build_router, reminder_loop
from .sheets import Sheets

COMMANDS = [
    BotCommand(command="today", description="Сколько можно тратить сегодня"),
    BotCommand(command="balance", description="Остатки по счетам"),
    BotCommand(command="debts", description="Долги и куда гасить"),
    BotCommand(command="month", description="Итоги месяца"),
    BotCommand(command="pay", description="Платёж по долгу"),
    BotCommand(command="undo", description="Отменить последнюю запись"),
    BotCommand(command="help", description="Как записывать"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load()
    sheets = await asyncio.to_thread(Sheets, cfg.google_credentials, cfg.sheet_id)
    svc = Service(cfg, sheets)

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(build_router(cfg, svc))

    @dp.errors()
    async def on_error(event: ErrorEvent):
        logging.exception("handler error", exc_info=event.exception)
        upd = event.update
        target = upd.message or (upd.callback_query.message if upd.callback_query else None)
        if target:
            await target.answer(f"⚠️ Ошибка: {type(event.exception).__name__}. Запись могла не сохраниться — проверь таблицу.")
        return True

    try:
        # меню команд — не критично; сеть до Telegram с сервера бывает нестабильной
        await bot.set_my_commands(COMMANDS, request_timeout=15)
    except TelegramNetworkError:
        logging.warning("не удалось обновить меню команд — работаю дальше")
    reminder = asyncio.create_task(reminder_loop(bot, cfg, svc))  # ссылка держит задачу от GC
    try:
        await dp.start_polling(bot)
    finally:
        reminder.cancel()


if __name__ == "__main__":
    asyncio.run(main())
