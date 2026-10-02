"""Тексты ответов бота (HTML)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from html import escape

from .budget import Budget, CashCheck
from .sheets import DEBT_TYPES, INTEREST_CAT, Account, Category, _num, from_serial

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
    "Под записью: ↩️ отменить, 🏷 сменить категорию, 💳 сменить счёт.\n"
    "Аванс и зарплату записывай, когда пришли (<code>+52000 зп</code>) — из них считается бюджет периода.\n\n"
    "<b>Команды</b> (или кнопки меню внизу)\n"
    "/today — можно в день по бюджету периода (от поступления до поступления) и касса до зарплаты\n"
    "/balance — остатки по счетам\n"
    "/debts — долги и куда гасить\n"
    "/month — итоги месяца\n"
    "/pay — платёж по долгу по шагам\n"
    "/undo — отменить последнюю запись бота\n\n"
    "Можно и без слеша: «сегодня», «баланс», «долги», «месяц», «отмена»."
)


def op_line(amount: float, category: str, account: str, dest: str = "", comment: str = "") -> str:
    where = f"{escape(account)} → {escape(dest)}" if dest else escape(account)
    line = f"✅ <b>{money(amount, sign=True)}</b> · {escape(category)} · {where}"
    if comment:
        line += f"\n<i>{escape(comment)}</i>"
    return line


def spending(ops: list[list], cats: list[Category], today_serial: int, month_key: str) -> dict:
    """Траты = расходные категории, кроме процентов (цена долга, а не трата)."""
    kinds = {c.name for c in cats if c.type == "расход" and c.name != INTEREST_CAT}
    res = {"day": 0.0, "month": 0.0}
    for r in ops:
        if len(r) < 5 or r[4] not in kinds:
            continue
        a = -_num(r[1])
        if len(r) >= 8 and r[7] == month_key:
            res["month"] += a
        if r[0] == today_serial:
            res["day"] += a
    return res


def spent_line(sp: dict, month_key: str) -> str:
    """Строка под тратой: «Сегодня: X ₽ · Сентябрь: Y ₽»."""
    month = MONTHS_NOM[int(month_key[5:7]) - 1]
    return f"<i>Сегодня: {money(sp['day'])} · {month}: {money(sp['month'])}</i>"


def _pay(d: date, name: str, amount: float) -> str:
    return f"{day(d)} — {escape(name)}: {money(amount)}"


def cash_warning(c: CashCheck, until: date) -> str | None:
    if c.uncovered is None:
        return None
    d, name, _ = c.uncovered
    return (f"⚠️ До {day(until)} не хватает {money(-c.after)}: "
            f"не покрыт платёж {day(d)} — {escape(name)}")


def today_text(b: Budget, c: CashCheck, sp: dict, upcoming: list[tuple[date, str, float]]) -> str:
    p = b.period
    if b.overspent:
        head = f"<b>⚠️ Бюджет периода превышен на {money(b.overspent)}</b> — можно в день: 0 ₽"
    else:
        head = f"<b>Можно тратить в день: {money(b.per_day)}</b>"
    lines = [head, f"Потрачено сегодня: {money(sp['day'])}", "",
             f"<b>Период {day(p.start)} → {day(p.end)}</b>, осталось {b.days_left} дн. (с сегодня)"]
    if b.from_balances:
        lines.append(f"Доход: {money(b.income)} — остатки на начало учёта + поступления")
    elif b.income:
        lines.append(f"Доход: {money(b.income)}")
    else:
        lines.append("Доход: поступлений в этом периоде не записано — запиши: <code>+52000 зп</code>")
    lines.append(f"− обязательные: {money(b.obligatory)}")
    lines += [f"   {_pay(*x)}" for x in b.payments]
    if b.extra_debt:
        lines.append(f"− доп. погашение долгов: {money(b.extra_debt)}")
    lines += [f"= бюджет: {money(b.total)}",
              f"Потрачено за период: {money(b.spent)}, осталось {money(max(b.left, 0))}"]

    lines += ["", f"<b>Касса до {day(p.end)}</b>"]
    warn = cash_warning(c, p.end)
    if warn:
        lines.append(warn)
    else:
        lines.append(f"✅ На счетах {money(c.cash)}, платежи {money(c.cash - c.after)} — хватает, "
                     f"останется {money(c.after)}")

    if upcoming:
        lines += ["", "<b>Ближайшие платежи</b>"] + [_pay(*x) for x in upcoming]
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
        elif cat == INTEREST_CAT:
            interest += -amount
        elif c.type == "расход":
            expenses[cat] += -amount
            if c.essential:
                essential += -amount
    spent = sum(expenses.values())
    y, m = month_key.split("-")
    lines = [
        f"<b>{MONTHS_NOM[int(m) - 1]} {y}</b>",
        f"Доходы: {money(income)}",
        f"Траты: {money(spent)} (обязательные {money(essential)})",
        f"Проценты по долгам: {money(interest)}",
        f"Итог: <b>{money(income - spent - interest, sign=True)}</b>",
    ]
    top = sorted(expenses.items(), key=lambda kv: kv[1], reverse=True)[:7]
    if top:
        lines += ["", "<b>Куда ушло</b>"]
        lines += [f"{escape(k)}: {money(v)}" for k, v in top if v]
    lines += ["", f"Внесено в долги: {money(to_debts)}, из них проценты {money(interest)}"]
    return "\n".join(lines)


# ---------- итоги дня и недели ----------

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def summary(ops: list[list], cats: list[Category], debt_names: set[str], start: date, end: date) -> dict:
    """Итоги за [start, end]: траты по счетам и категориям, поступления, внесено в долги."""
    types = {c.name: c.type for c in cats}
    res = {"spent": 0.0, "by_acc": defaultdict(float), "by_cat": defaultdict(float),
           "by_day": defaultdict(float), "income": 0.0, "incomes": defaultdict(float),
           "to_debts": defaultdict(float), "interest": 0.0}
    for r in ops:
        d = from_serial(r[0] if r else None)
        if d is None or not start <= d <= end or len(r) < 5:
            continue
        amount, acc, dest, cat = _num(r[1]), str(r[2]), str(r[3]), str(r[4])
        kind = types.get(cat)
        if cat == INTEREST_CAT:
            res["interest"] += -amount
        elif kind == "расход":
            res["spent"] += -amount
            res["by_acc"][acc] += -amount
            res["by_cat"][cat] += -amount
            res["by_day"][d] += -amount
        elif kind == "доход":
            res["income"] += amount
            res["incomes"][(cat, acc)] += amount
        elif dest in debt_names:
            res["to_debts"][dest] += -amount
    return res


def _top(items: dict, n: int | None = None) -> list[tuple[str, float]]:
    return sorted(((k, v) for k, v in items.items() if round(v)), key=lambda kv: kv[1], reverse=True)[:n]


def _joined(items: dict) -> str:
    return " · ".join(f"{escape(k)} {money(v)}" for k, v in _top(items))


def _income_lines(s: dict) -> list[str]:
    if not s["income"]:
        return []
    lines = [f"Поступило: <b>{money(s['income'], sign=True)}</b>"]
    lines += [f"   {escape(cat)} {money(v)} → {escape(acc)}" for (cat, acc), v in _top(s["incomes"])]
    return lines


def _debt_lines(s: dict) -> list[str]:
    if not s["to_debts"]:
        return []
    if len(s["to_debts"]) == 1:
        line = f"В долги: {_joined(s['to_debts'])}"
    else:
        line = f"В долги: {money(sum(s['to_debts'].values()))} — {_joined(s['to_debts'])}"
    if s["interest"]:
        line += f"\n   из них проценты ≈ {money(s['interest'])}"
    return [line]


def day_text(s: dict, d: date, month_spent: float) -> str:
    lines = [f"<b>Итоги дня · {day(d)}</b>"]
    if s["spent"]:
        lines += [f"Потрачено: <b>{money(s['spent'])}</b>",
                  f"💳 {_joined(s['by_acc'])}",
                  f"🏷 {_joined(s['by_cat'])}"]
    else:
        lines.append("Трат нет")
    lines += _income_lines(s) + _debt_lines(s)
    lines.append(f"<i>{MONTHS_NOM[d.month - 1]}: потрачено {money(month_spent)}</i>")
    return "\n".join(lines)


def week_text(s: dict, prev: dict, start: date, end: date) -> str:
    days = (end - start).days + 1
    lines = [f"<b>Итоги недели · {day(start)} – {day(end)}</b>",
             f"Потрачено: <b>{money(s['spent'])}</b>, в среднем {money(s['spent'] / days)}/день"]
    lines += _income_lines(s)
    lines.append(f"Итог: <b>{money(s['income'] - s['spent'], sign=True)}</b>")
    if s["spent"]:
        lines += ["", "<b>По счетам</b>"] + [f"{escape(k)}: {money(v)}" for k, v in _top(s["by_acc"])]
        lines += ["", "<b>По категориям</b>"] + [f"{escape(k)}: {money(v)}" for k, v in _top(s["by_cat"])]
        by_day = [f"{WEEKDAYS[d.weekday()]} {money(s['by_day'].get(d, 0)).removesuffix(' ₽')}"
                  for d in (start + timedelta(days=i) for i in range(days))]
        lines += ["", "<b>По дням</b>", " · ".join(by_day)]
    debts = _debt_lines(s)
    if debts:
        lines += [""] + debts
    if prev["spent"]:
        diff = (s["spent"] - prev["spent"]) / prev["spent"] * 100
        arrow = "↑" if diff > 0 else "↓"
        lines += ["", f"Прошлая неделя: {money(prev['spent'])} ({arrow}{abs(diff):.0f}%)"]
    return "\n".join(lines)
