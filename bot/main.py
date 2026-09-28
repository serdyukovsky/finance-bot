from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import GetUpdates
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


class RetryNetwork(BaseRequestMiddleware):
    """Сеть до Telegram с сервера рвётся (~1 соединение из 10 висит) — повторяем запрос.
    getUpdates не трогаем: polling сам переподключается."""

    async def __call__(self, make_request, bot, method):
        if isinstance(method, GetUpdates):
            return await make_request(bot, method)
        for attempt in range(3):
            try:
                return await make_request(bot, method)
            except TelegramNetworkError:
                if attempt == 2:
                    raise
                logging.warning("Telegram не ответил на %s, повтор %d", type(method).__name__, attempt + 1)
                await asyncio.sleep(1 + attempt)


async def set_commands(bot: Bot) -> None:
    """Меню команд — не критично: пробуем в фоне, пока не получится."""
    while True:
        try:
            await bot.set_my_commands(COMMANDS)
            return
        except TelegramNetworkError:
            await asyncio.sleep(60)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load()
    sheets = await asyncio.to_thread(Sheets, cfg.google_credentials, cfg.sheet_id)
    svc = Service(cfg, sheets)

    # 20 с вместо 60: зависшее соединение быстрее бросаем и повторяем
    session = AiohttpSession(timeout=20)
    session.middleware(RetryNetwork())
    bot = Bot(cfg.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(build_router(cfg, svc))

    @dp.errors()
    async def on_error(event: ErrorEvent):
        logging.exception("handler error", exc_info=event.exception)
        upd = event.update
        target = upd.message or (upd.callback_query.message if upd.callback_query else None)
        if target:
            try:
                await target.answer(f"⚠️ Ошибка: {type(event.exception).__name__}. "
                                    "Запись могла не сохраниться — проверь таблицу.")
            except TelegramNetworkError:
                pass
        return True

    # ссылки держат задачи от GC
    tasks = [asyncio.create_task(reminder_loop(bot, cfg, svc)), asyncio.create_task(set_commands(bot))]
    try:
        await dp.start_polling(bot)
    finally:
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    asyncio.run(main())
