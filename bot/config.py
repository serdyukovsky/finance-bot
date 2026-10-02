from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    bot_token: str
    sheet_id: str
    allowed_user_id: int | None
    google_credentials: str
    tz: ZoneInfo
    reminder_hour: int
    default_account: str
    weekly_hour: int = 20  # итоги недели в воскресенье


def load() -> Config:
    uid = os.getenv("ALLOWED_USER_ID", "").strip()
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        sheet_id=os.environ["SHEET_ID"],
        allowed_user_id=int(uid) if uid else None,
        google_credentials=os.getenv("GOOGLE_CREDENTIALS", "/app/secrets/google.json"),
        tz=ZoneInfo(os.getenv("TZ_NAME", "Asia/Barnaul")),
        reminder_hour=int(os.getenv("REMINDER_HOUR", "21")),
        default_account=os.getenv("DEFAULT_ACCOUNT", "Дебет Альфа"),
        weekly_hour=int(os.getenv("WEEKLY_HOUR", "20")),
    )
