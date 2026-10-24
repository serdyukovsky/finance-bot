"""HTTP для мини-приложения: страница и /api/dashboard.

Доступ — только из Telegram: страница присылает initData, проверяем подпись токеном бота
(https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app) и что это ALLOWED_USER_ID.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from .config import Config

log = logging.getLogger(__name__)

PAGE = Path(__file__).resolve().parent.parent / "webapp" / "index.html"
MAX_AGE = 24 * 3600  # initData старше суток не принимаем
CACHE_SECONDS = 30  # лимит Google — 60 чтений/мин, а приложение могут открывать часто


def check_init_data(init_data: str, bot_token: str, now: float | None = None) -> dict | None:
    """Пользователь из initData, если подпись верна и данные свежие; иначе None."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    if not received:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received):
        return None
    try:
        if (now or time.time()) - int(pairs.get("auth_date", 0)) > MAX_AGE:
            return None
        return json.loads(pairs.get("user", ""))
    except ValueError:
        return None


def build_app(cfg: Config, dashboard) -> web.Application:
    """dashboard — синхронная функция без аргументов, возвращает dict (Service.dashboard)."""
    cache: dict = {"at": 0.0, "data": None}
    lock = asyncio.Lock()

    async def page(_):
        return web.FileResponse(PAGE, headers={"Cache-Control": "no-cache"})

    async def api(req: web.Request):
        user = check_init_data(req.headers.get("X-Telegram-Init-Data", ""), cfg.bot_token)
        if not user or cfg.allowed_user_id is None or user.get("id") != cfg.allowed_user_id:
            return web.json_response({"error": "forbidden"}, status=403)
        async with lock:
            if cache["data"] is None or time.monotonic() - cache["at"] > CACHE_SECONDS:
                cache["data"] = await asyncio.to_thread(dashboard)
                cache["at"] = time.monotonic()
        return web.json_response(cache["data"], dumps=lambda o: json.dumps(o, ensure_ascii=False),
                                 headers={"Cache-Control": "no-store"})

    app = web.Application()
    app.router.add_get("/", page)
    app.router.add_get("/api/dashboard", api)
    return app


async def serve(cfg: Config, dashboard) -> web.AppRunner:
    runner = web.AppRunner(build_app(cfg, dashboard), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", cfg.web_port).start()
    log.info("mini app on :%d", cfg.web_port)
    return runner
