"""Тексты ответов бота (HTML)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from html import escape

from .sheets import DEBT_TYPES, INTEREST_CAT, Account, Category, from_serial

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
              "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


def money(x: float, sign: bool = False) -> str:
    v = int(round(x))
    s = f"{abs(v):,}".replace(",", " ")
    if v < 0:
        return f"−{s} ₽"
    return f"+{s} ₽" if sign and v > 0 else f"{s} ₽"


def pct(rate: float) -> str:
    return f"{rate * 100:.1f}".replace(".", ",") + "%"


def day(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


HELP = (
    "<b>Как записывать</b>\n"
    "<code>450 магнит</code> — расход с Дебет Альфа\n"
    "<code>450 сбер такси</code> — расход с другого счёта (по ключу)\n"
    "<code>+15000 лендинг</code> — доход\n"
    "<code>5000 > нал</code> — перевод с Дебет Альфа на Наличные\n"
    "<code>10545 сбер > ксбер</code> — платёж по долгу (проценты месяца добавлю сам)\n"
    "Ключи: альфа, сбер — дебетовки; кальфа, ксбер — кредитки; нал, кредит\n"
    "<code>2к кафе</code> — «к» значит тысячи\n\n"
    "<b>Команды</b>\n"
    "/today — сколько можно тратить сегодня\n"
    "/balance — остатки по счетам\n"
    "/debts — долги и куда гасить\n"
    "/month — итоги месяца\n"
    "/undo — отменить последнюю запись бота\n\n"
    "Можно и без слеша: «сегодня», «баланс», «долги», «месяц», «отмена»."
)


def op_line(amount: float, category: str, account: str, dest: str = "", comment: str = "") -> str:
    where = f"{escape(account)} → {escape(dest)}" if dest else escape(account)
    line = f"✅ <b>{money(amount, sign=True)}</b> · {escape(category)} · {where}"
    if comment:
        line += f"\n<i>{escape(comment)}</i>"
    return line


def today_text(h: dict) -> str:
    lines = [
        f"<b>Можно тратить в день: {money(h['per_day'])}</b>",
        "",
        f"Свободно: {money(h['free'])}",
    ]
    if h["next_income"]:
        lines.append(f"До поступления ({day(h['next_income'])}): {int(h['days'])} дн.")
    lines.append(f"Обязательные до него: {money(h['obligatory'])}")
    if h["upcoming"]:
        lines += ["", "<b>Ближайшие платежи</b>"]
        for d, name, amount in h["upcoming"]:
            lines.append(f"{day(d)} — {escape(name)}: {money(abs(amount))}")
    return "\n".join(lines)


def balance_text(accounts: list[Account]) -> str:
    normal = [a for a in accounts if a.type == "обычный"]
    debts = [a for a in accounts if a.type in DEBT_TYPES]
    people = [a for a in accounts if a.type == "долг" and abs(a.balance) >= 1]
    lines = ["<b>Счета</b>"]
    lines += [f"{escape(a.name)}: {money(a.balance)}" for a in normal]
    lines.append(f"<b>Всего: {money(sum(a.balance for a in normal))}</b>")
    if debts:
        lines += ["", "<b>Долги</b>"]
        lines += [f"{escape(a.name)}: {money(-a.balance)}" for a in debts]
        lines.append(f"<b>Всего: {money(-sum(a.balance for a in debts))}</b>")
    if people:
        lines += ["", "<b>С людьми</b> (плюс — должны мне)"]
        lines += [f"{escape(a.name)}: {money(a.balance, sign=True)}" for a in people]
    lines += ["", f"Чистый капитал: {money(sum(a.balance for a in accounts))}"]
    return "\n".join(lines)


def debts_text(d: dict) -> str:
    lines = ["<b>Долги</b>"]
    total = interest = 0.0
    for r in d["rows"]:
        if r["balance"] <= 0:
            continue
        total += r["balance"]
        interest += r["interest"]
        months = r["months"]
        m = f"{int(months)} мес." if isinstance(months, (int, float)) else str(months)
        lines.append(
            f"\n<b>{escape(r['name'])}</b> — {money(r['balance'])} под {pct(r['rate'])}\n"
            f"проценты ≈ {money(r['interest'])}/мес, платёж {money(r['payment'])}, "
            f"в тело {money(r['principal'])}\nдо нуля: {m}"
        )
    lines += [
        "",
        f"Всего: <b>{money(total)}</b>, проценты ≈ {money(interest)}/мес",
        f"Гасить сверх минимума → <b>{escape(str(d['target']))}</b>",
        f"Уплачено процентов с начала учёта: {money(d['paid_interest'])}",
    ]
    return "\n".join(lines)


def month_text(ops: list[list], cats: list[Category], month_key: str, debt_names: set[str]) -> str:
    types = {c.name: c for c in cats}
    income = 0.0
    expenses: dict[str, float] = defaultdict(float)
    essential = interest = to_debts = 0.0
    for r in ops:
        if len(r) < 8 or r[7] != month_key:
            continue
        amount = float(r[1] or 0)
        cat = str(r[4])
        dest = str(r[3])
        c = types.get(cat)
        if dest in debt_names:
            to_debts += -amount
        if not c:
            continue
        if c.type == "доход":
            income += amount
        elif c.type == "расход":
            expenses[cat] += -amount
            if c.essential:
                essential += -amount
            if cat == INTEREST_CAT:
                interest += -amount
    spent = sum(expenses.values())
    y, m = month_key.split("-")
    lines = [
        f"<b>{MONTHS_NOM[int(m) - 1]} {y}</b>",
        f"Доходы: {money(income)}",
        f"Расходы: {money(spent)} (обязательные {money(essential)})",
        f"Итог: <b>{money(income - spent, sign=True)}</b>",
    ]
    top = sorted(expenses.items(), key=lambda kv: kv[1], reverse=True)[:7]
    if top:
        lines += ["", "<b>Куда ушло</b>"]
        lines += [f"{escape(k)}: {money(v)}" for k, v in top if v]
    lines += ["", f"Внесено в долги: {money(to_debts)}, из них проценты {money(interest)}"]
    return "\n".join(lines)
