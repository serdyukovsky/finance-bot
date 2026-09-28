"""Логика бота: записи, категории, платежи по долгам, отмена, напоминания."""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import reports
from .config import Config
from .parser import match_category, norm, parse
from .sheets import INTEREST_CAT, INTEREST_NOTE, TRANSFER_CAT, Sheets, _cell, to_serial

log = logging.getLogger(__name__)


def undo_kb(first: int, count: int, amount: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Отменить", callback_data=f"u:{first}:{count}:{round(amount, 2)}")
    ]])


class Service:
    """Синхронная часть: вызывается через asyncio.to_thread."""

    def __init__(self, cfg: Config, sheets: Sheets):
        self.cfg = cfg
        self.sh = sheets
        self.pending: dict[str, dict] = {}

    def today(self) -> date:
        return datetime.now(self.cfg.tz).date()

    def month_key(self) -> str:
        return self.today().strftime("%Y-%m")

    # ---------- запись ----------

    def handle_text(self, text: str) -> tuple[str, InlineKeyboardMarkup | None]:
        accounts = self.sh.accounts()
        p = parse(text, {a.key for a in accounts})
        if p is None:
            return ("Не понял. Начни с суммы: <code>450 магнит</code>, "
                    "<code>+15000 лендинг</code>, <code>5000 > нал</code>. /help", None)

        src = (self.sh.account_by_key(p.account_key) if p.account_key
               else self.sh.account_by_name(self.cfg.default_account))
        if src is None:
            return (f"Не нашёл счёт по умолчанию «{self.cfg.default_account}» в «Счетах».", None)

        if p.kind == "transfer":
            return self._transfer(p.amount, src, p.dest_key, p.comment)

        ctype = "расход" if p.kind == "expense" else "доход"
        amount = -p.amount if p.kind == "expense" else p.amount
        cats = self._pick_cats(ctype)
        name = match_category(p.words, p.comment, [(c.name, c.keywords) for c in cats])
        if name:
            first = self.sh.append_ops([[self.today(), amount, src.name, "", name, p.comment]])
            return reports.op_line(amount, name, src.name, comment=p.comment), undo_kb(first, 1, amount)

        pid = secrets.token_hex(3)
        self.pending[pid] = {"amount": amount, "account": src.name, "comment": p.comment,
                             "words": p.words, "type": ctype}
        buttons = [InlineKeyboardButton(text=c.name, callback_data=f"c:{pid}:{i}")
                   for i, c in enumerate(cats)]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        return (f"{reports.money(amount, sign=True)} · {src.name}\nКакая категория?",
                InlineKeyboardMarkup(inline_keyboard=rows))

    def _pick_cats(self, ctype: str):
        return [c for c in self.sh.categories() if c.type == ctype and c.name != INTEREST_CAT]

    def choose_category(self, pid: str, idx: int) -> tuple[str, InlineKeyboardMarkup | None]:
        item = self.pending.pop(pid, None)
        if item is None:
            return "Эта запись устарела — отправь сумму заново.", None
        cats = self._pick_cats(item["type"])
        if idx >= len(cats):
            return "Категория не найдена — отправь сумму заново.", None
        cat = cats[idx]
        first = self.sh.append_ops([[self.today(), item["amount"], item["account"], "", cat.name, item["comment"]]])
        text = reports.op_line(item["amount"], cat.name, item["account"], comment=item["comment"])
        word = next((w for w in item["words"] if len(w) >= 3 and not w.isdigit()), None)
        if word:
            self.sh.add_keyword(cat, word)
            text += f"\n<i>Запомнил: «{word}» → {cat.name}</i>"
        return text, undo_kb(first, 1, item["amount"])

    def _transfer(self, amount: float, src, dest_key: str | None, comment: str):
        if not dest_key:
            return "Куда перевод? Пример: <code>5000 > нал</code>", None
        dest = self.sh.account_by_key(dest_key)
        if dest is None:
            keys = ", ".join(a.key for a in self.sh.accounts() if a.key)
            return f"Не знаю счёт «{dest_key}». Ключи: {keys}", None
        if dest.name == src.name:
            return "Счёт списания и зачисления совпадают.", None

        rows = [[self.today(), -amount, src.name, dest.name, TRANSFER_CAT, comment]]
        extra = ""
        if dest.is_debt:
            est = self._interest_estimate(dest.name)
            if est:
                rows.append([self.today(), -est, dest.name, "", INTEREST_CAT, INTEREST_NOTE])
                extra = (f"\nПроценты за месяц ≈ {reports.money(est)} (записал оценкой)"
                         f"\nВ тело долга ≈ {reports.money(amount - est)}")
            else:
                extra = "\nПроценты за этот месяц уже записаны."
        first = self.sh.append_ops(rows)
        text = reports.op_line(-amount, TRANSFER_CAT, src.name, dest.name, comment) + extra
        return text, undo_kb(first, len(rows), -amount)

    def _interest_estimate(self, account_name: str) -> float:
        mk = self.month_key()
        for r in self.sh.ops():
            if len(r) >= 8 and r[2] == account_name and r[4] == INTEREST_CAT and r[7] == mk:
                return 0.0
        acc = next((a for a in self.sh.accounts(fresh=True) if a.name == account_name), None)
        if acc is None or acc.balance >= 0 or not acc.rate:
            return 0.0
        return float(round(-acc.balance * acc.rate / 12))

    # ---------- отмена ----------

    def undo(self, first: int, count: int, amount: float) -> str:
        rows = self.sh.delete_bot_rows(first, count, amount)
        if rows is None:
            return "Не получилось отменить: строки уже изменены или удалены. Проверь таблицу."
        return "↩️ Отменено: " + ", ".join(f"{reports.money(float(r[1]))} {r[4]}" for r in rows)

    def undo_last(self) -> str:
        data = self.sh.ops()
        i = next((i for i in range(len(data) - 1, -1, -1) if _cell(data[i], 6) == "бот"), None)
        if i is None:
            return "Нечего отменять."
        first, count = i, 1
        r = data[i]
        # платёж по долгу пишется двумя строками: перевод + оценка процентов — отменяем вместе
        if i > 0 and _cell(r, 4) == INTEREST_CAT and _cell(r, 5) == INTEREST_NOTE:
            p = data[i - 1]
            if (_cell(p, 6) == "бот" and _cell(p, 4) == TRANSFER_CAT
                    and _cell(p, 3) == _cell(r, 2) and _cell(p, 0) == _cell(r, 0)):
                first, count = i - 1, 2
        return self.undo(first + 2, count, float(data[first][1]))

    # ---------- отчёты ----------

    def today_report(self) -> str:
        return reports.today_text(self.sh.home())

    def balance_report(self) -> str:
        return reports.balance_text(self.sh.accounts(fresh=True))

    def debts_report(self) -> str:
        return reports.debts_text(self.sh.debts())

    def month_report(self) -> str:
        debt_names = {a.name for a in self.sh.accounts() if a.is_debt}
        return reports.month_text(self.sh.ops(), self.sh.categories(), self.month_key(), debt_names)

    # ---------- напоминание ----------

    def evening_reminder(self) -> str | None:
        today = self.today()
        serial = to_serial(today)
        has_today = any(r and r[0] == serial for r in self.sh.ops())
        parts = []
        if not has_today:
            parts.append("Сегодня ничего не записано. Были траты?")
        for d, name, amount in self.sh.plan_upcoming(today, 2):
            when = "сегодня" if d == today else reports.day(d)
            parts.append(f"⏰ {when}: {name} — {reports.money(abs(amount))}")
        for a in self.sh.accounts(fresh=True):
            if a.statement_day == today.day:
                parts.append(f"📄 Сегодня выписка по «{a.name}» — впиши новый мин. платёж в «Счета».")
        return "\n".join(parts) or None


def build_router(cfg: Config, svc: Service) -> Router:
    router = Router()
    allowed = F.from_user.id == cfg.allowed_user_id

    async def run(fn, *args):
        return await asyncio.to_thread(fn, *args)

    @router.message(CommandStart(), ~allowed)
    @router.message(~allowed)
    async def stranger(m: Message):
        await m.answer(f"Это личный бот. Твой Telegram ID: <code>{m.from_user.id}</code>")

    @router.message(CommandStart(), allowed)
    @router.message(Command("help"), allowed)
    async def help_(m: Message):
        await m.answer(reports.HELP)

    reports_map = {
        "today": ("сегодня", Service.today_report),
        "balance": ("баланс", Service.balance_report),
        "debts": ("долги", Service.debts_report),
        "month": ("месяц", Service.month_report),
    }
    for cmd, (alias, method) in reports_map.items():
        def make(method=method):
            async def handler(m: Message):
                await m.answer(await run(method, svc))
            return handler
        router.message(Command(cmd), allowed)(make())
        router.message(F.text.lower() == alias, allowed)(make())

    @router.message(Command("undo"), allowed)
    @router.message(F.text.lower() == "отмена", allowed)
    async def undo_cmd(m: Message):
        await m.answer(await run(svc.undo_last))

    @router.message(F.text, allowed)
    async def text(m: Message):
        reply, kb = await run(svc.handle_text, m.text)
        await m.answer(reply, reply_markup=kb)

    @router.callback_query(F.data.startswith("c:"), allowed)
    async def cat_cb(c: CallbackQuery):
        _, pid, idx = c.data.split(":")
        text, kb = await run(svc.choose_category, pid, int(idx))
        await c.answer()
        await c.message.edit_text(text, reply_markup=kb)

    @router.callback_query(F.data.startswith("u:"), allowed)
    async def undo_cb(c: CallbackQuery):
        _, first, count, amount = c.data.split(":")
        text = await run(svc.undo, int(first), int(count), float(amount))
        await c.answer()
        await c.message.edit_text(text)

    return router


async def reminder_loop(bot, cfg: Config, svc: Service):
    last_sent: date | None = None
    while True:
        try:
            now = datetime.now(cfg.tz)
            if now.hour == cfg.reminder_hour and last_sent != now.date():
                last_sent = now.date()
                text = await asyncio.to_thread(svc.evening_reminder)
                if text and cfg.allowed_user_id:
                    await bot.send_message(cfg.allowed_user_id, text)
        except Exception:
            log.exception("reminder failed")
        await asyncio.sleep(30)
