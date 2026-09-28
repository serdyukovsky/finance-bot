"""Логика бота: записи, категории, платежи по долгам, отмена, напоминания."""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import date, datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from . import keyboards as kb
from . import reports
from .config import Config
from .parser import match_category, parse, parse_amount
from .sheets import INTEREST_CAT, INTEREST_NOTE, TRANSFER_CAT, Sheets, _cell, to_serial

log = logging.getLogger(__name__)

Reply = tuple[str, InlineKeyboardMarkup | None]


class Service:
    """Синхронная часть: вызывается через asyncio.to_thread."""

    def __init__(self, cfg: Config, sheets: Sheets):
        self.cfg = cfg
        self.sh = sheets
        self.pending: dict[str, dict] = {}
        self.awaiting_pay: str | None = None  # ключ долга, для которого ждём «свою сумму»

    def today(self) -> date:
        return datetime.now(self.cfg.tz).date()

    def month_key(self) -> str:
        return self.today().strftime("%Y-%m")

    # ---------- запись ----------

    def handle_text(self, text: str) -> Reply:
        if self.awaiting_pay:
            key, self.awaiting_pay = self.awaiting_pay, None
            res = parse_amount(text)
            if res and not res[0] and not res[2]:  # просто число — сумма платежа
                return self.pay_source(key, res[1])

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
            return (reports.op_line(amount, name, src.name, comment=p.comment),
                    kb.record(first, 1, amount, editable=True))

        pid = secrets.token_hex(3)
        self.pending[pid] = {"amount": amount, "account": src.name, "comment": p.comment,
                             "words": p.words, "type": ctype}
        return (f"{reports.money(amount, sign=True)} · {src.name}\nКакая категория?",
                kb.pick_category([c.name for c in cats], f"c:{pid}"))

    def _pick_cats(self, ctype: str):
        return [c for c in self.sh.categories() if c.type == ctype and c.name != INTEREST_CAT]

    def choose_category(self, pid: str, idx: int) -> Reply:
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
        return text, kb.record(first, 1, item["amount"], editable=True)

    def _transfer(self, amount: float, src, dest_key: str | None, comment: str) -> Reply:
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
        return text, kb.record(first, len(rows), -amount, editable=False)

    def _interest_estimate(self, account_name: str) -> float:
        mk = self.month_key()
        for r in self.sh.ops():
            if len(r) >= 8 and r[2] == account_name and r[4] == INTEREST_CAT and r[7] == mk:
                return 0.0
        acc = next((a for a in self.sh.accounts(fresh=True) if a.name == account_name), None)
        if acc is None or acc.balance >= 0 or not acc.rate:
            return 0.0
        return float(round(-acc.balance * acc.rate / 12))

    # ---------- правка записи кнопками ----------

    def _spendable(self, income: bool):
        """Счета, на которые можно перекинуть запись: доход — только обычные."""
        types = ("обычный",) if income else ("обычный", "кредитка")
        return [a for a in self.sh.accounts() if a.key and a.type in types]

    def edit_menu(self, what: str, row: int, amount: float) -> InlineKeyboardMarkup:
        back = f"eb:{row}:{kb.num(amount)}"
        if what == "c":
            names = [c.name for c in self._pick_cats("доход" if amount > 0 else "расход")]
            return kb.pick_category(names, f"sc:{row}:{kb.num(amount)}", back)
        return kb.pick_account(self._spendable(amount > 0), f"sa:{row}:{kb.num(amount)}", back)

    def set_category(self, row: int, amount: float, idx: int) -> Reply:
        cats = self._pick_cats("доход" if amount > 0 else "расход")
        if idx >= len(cats):
            return "Категория не найдена.", None
        return self._apply_edit(row, amount, "E", cats[idx].name)

    def set_account(self, row: int, amount: float, key: str) -> Reply:
        acc = self.sh.account_by_key(key)
        if acc is None:
            return "Счёт не найден.", None
        return self._apply_edit(row, amount, "C", acc.name)

    def _apply_edit(self, row: int, amount: float, col: str, value: str) -> Reply:
        r = self.sh.update_bot_row(row, amount, col, value)
        if r is None:
            return "Не получилось изменить: строка уже изменена или удалена. Проверь таблицу.", None
        return (reports.op_line(amount, str(r[4]), str(r[2]), comment=str(r[5])),
                kb.record(row, 1, amount, editable=True))

    # ---------- платёж по долгу ----------

    def _debts(self):
        return [a for a in self.sh.accounts(fresh=True) if a.is_debt and a.key and a.balance < 0]

    def pay_start(self) -> Reply:
        self.awaiting_pay = None
        debts = sorted(self._debts(), key=lambda a: -a.rate)  # лавина: дорогой долг первым
        if not debts:
            return "Долгов нет 🎉", None
        return ("<b>Какой долг гасим?</b>\n🔥 — максимальная ставка, сверх минимумов гасить его",
                kb.pick_debt(debts, debts[0].key))

    def pay_amount(self, key: str) -> Reply:
        self.awaiting_pay = None
        a = self.sh.account_by_key(key)
        if a is None:
            return "Долг не найден.", None
        lines = [f"<b>{reports.escape(a.name)}</b> — {reports.money(-a.balance)} под {reports.pct(a.rate)}"]
        if a.min_payment > 0:
            lines.append(f"Мин. платёж: {reports.money(a.min_payment)}")
        else:
            lines.append("Мин. платёж в «Счетах» не указан.")
        lines.append("\nСколько вносишь?")
        return "\n".join(lines), kb.pick_pay_amount(key, a.min_payment)

    def pay_custom(self, key: str) -> Reply:
        a = self.sh.account_by_key(key)
        if a is None:
            return "Долг не найден.", None
        self.awaiting_pay = key
        return f"Напиши сумму платежа по «{reports.escape(a.name)}» числом, например <code>15000</code>.", None

    def pay_source(self, key: str, amount: float) -> Reply:
        dest = self.sh.account_by_key(key)
        if dest is None:
            return "Долг не найден.", None
        sources = [a for a in self.sh.accounts(fresh=True) if a.key and a.type == "обычный"]
        return (f"{reports.money(amount)} → {reports.escape(dest.name)}\n<b>С какого счёта?</b>",
                kb.pick_account(sources, f"px:{key}:{kb.num(amount)}", back="pc", show_balance=True))

    def pay_do(self, key: str, amount: float, src_key: str) -> Reply:
        src = self.sh.account_by_key(src_key)
        if src is None:
            return "Счёт не найден.", None
        return self._transfer(amount, src, key, "")

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

    async def edit(c: CallbackQuery, text: str, markup=None):
        await c.answer()
        try:
            await c.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as e:  # двойное нажатие: «message is not modified»
            if "not modified" not in str(e):
                raise

    @router.message(CommandStart(), ~allowed)
    @router.message(~allowed)
    async def stranger(m: Message):
        await m.answer(f"Это личный бот. Твой Telegram ID: <code>{m.from_user.id}</code>")

    @router.callback_query(~allowed)
    async def stranger_cb(c: CallbackQuery):
        await c.answer("Это личный бот.")

    @router.message(CommandStart(), allowed)
    @router.message(Command("help"), allowed)
    async def help_(m: Message):
        await m.answer(reports.HELP, reply_markup=kb.main_menu())

    reports_map = {
        "today": ("сегодня", kb.MENU_TODAY, Service.today_report),
        "balance": ("баланс", kb.MENU_BALANCE, Service.balance_report),
        "debts": ("долги", kb.MENU_DEBTS, Service.debts_report),
        "month": ("месяц", kb.MENU_MONTH, Service.month_report),
    }
    for cmd, (alias, label, method) in reports_map.items():
        def make(method=method):
            async def handler(m: Message):
                await m.answer(await run(method, svc))
            return handler
        router.message(Command(cmd), allowed)(make())
        router.message(F.text.lower() == alias, allowed)(make())
        router.message(F.text == label, allowed)(make())

    @router.message(Command("undo"), allowed)
    @router.message(F.text.lower() == "отмена", allowed)
    @router.message(F.text == kb.MENU_UNDO, allowed)
    async def undo_cmd(m: Message):
        await m.answer(await run(svc.undo_last))

    @router.message(Command("pay"), allowed)
    @router.message(F.text == kb.MENU_PAY, allowed)
    async def pay_cmd(m: Message):
        text, markup = await run(svc.pay_start)
        await m.answer(text, reply_markup=markup)

    @router.message(F.text, allowed)
    async def text(m: Message):
        reply, markup = await run(svc.handle_text, m.text)
        await m.answer(reply, reply_markup=markup)

    # --- новая запись: выбор категории ---
    @router.callback_query(F.data.startswith("c:"), allowed)
    async def cat_cb(c: CallbackQuery):
        _, pid, idx = c.data.split(":")
        await edit(c, *await run(svc.choose_category, pid, int(idx)))

    # --- под записью ---
    @router.callback_query(F.data.startswith("u:"), allowed)
    async def undo_cb(c: CallbackQuery):
        _, first, count, amount = c.data.split(":")
        await edit(c, await run(svc.undo, int(first), int(count), float(amount)))

    @router.callback_query(F.data.regexp(r"^e[ca]:"), allowed)
    async def edit_menu_cb(c: CallbackQuery):
        what, row, amount = c.data.split(":")
        markup = await run(svc.edit_menu, what[1], int(row), float(amount))
        await c.answer()
        await c.message.edit_reply_markup(reply_markup=markup)

    @router.callback_query(F.data.startswith("eb:"), allowed)
    async def edit_back_cb(c: CallbackQuery):
        _, row, amount = c.data.split(":")
        await c.answer()
        await c.message.edit_reply_markup(reply_markup=kb.record(int(row), 1, float(amount), editable=True))

    @router.callback_query(F.data.startswith("sc:"), allowed)
    async def set_cat_cb(c: CallbackQuery):
        _, row, amount, idx = c.data.split(":")
        await edit(c, *await run(svc.set_category, int(row), float(amount), int(idx)))

    @router.callback_query(F.data.startswith("sa:"), allowed)
    async def set_acc_cb(c: CallbackQuery):
        _, row, amount, key = c.data.split(":")
        await edit(c, *await run(svc.set_account, int(row), float(amount), key))

    # --- платёж по долгу ---
    @router.callback_query(F.data == "pb", allowed)
    async def pay_back_cb(c: CallbackQuery):
        await edit(c, *await run(svc.pay_start))

    @router.callback_query(F.data == "pc", allowed)
    async def pay_cancel_cb(c: CallbackQuery):
        svc.awaiting_pay = None
        await edit(c, "Платёж не записан.")

    @router.callback_query(F.data.startswith("pd:"), allowed)
    async def pay_debt_cb(c: CallbackQuery):
        await edit(c, *await run(svc.pay_amount, c.data.split(":")[1]))

    @router.callback_query(F.data.startswith("po:"), allowed)
    async def pay_other_cb(c: CallbackQuery):
        await edit(c, *await run(svc.pay_custom, c.data.split(":")[1]))

    @router.callback_query(F.data.startswith("pa:"), allowed)
    async def pay_amount_cb(c: CallbackQuery):
        _, key, amount = c.data.split(":")
        await edit(c, *await run(svc.pay_source, key, float(amount)))

    @router.callback_query(F.data.startswith("px:"), allowed)
    async def pay_do_cb(c: CallbackQuery):
        _, key, amount, src = c.data.split(":")
        await edit(c, *await run(svc.pay_do, key, float(amount), src))

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
