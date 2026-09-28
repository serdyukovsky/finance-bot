import asyncio

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetUpdates, SendMessage

from bot import main


def run(method, fails):
    calls = []

    async def make_request(bot, m):
        calls.append(m)
        if len(calls) <= fails:
            raise TelegramNetworkError(method=m, message="Request timeout error")
        return "ok"

    async def no_sleep(_):
        pass

    orig, main.asyncio.sleep = main.asyncio.sleep, no_sleep
    try:
        return asyncio.run(main.RetryNetwork()(make_request, None, method)), len(calls)
    finally:
        main.asyncio.sleep = orig


def test_retries_send_until_success():
    assert run(SendMessage(chat_id=1, text="x"), fails=2) == ("ok", 3)


def test_gives_up_after_three_attempts():
    with pytest.raises(TelegramNetworkError):
        run(SendMessage(chat_id=1, text="x"), fails=3)


def test_get_updates_not_retried():
    with pytest.raises(TelegramNetworkError):
        run(GetUpdates(), fails=1)
