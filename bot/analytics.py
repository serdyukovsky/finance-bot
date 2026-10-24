"""Данные для мини-приложения: один JSON со всей аналитикой. Чистые функции, без сети."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta

from . import budget
from .reports import MONTHS, MONTHS_NOM, money
from .sheets import DEBT_TYPES, INTEREST_CAT, Account, Category, _cell, _num, from_serial

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _ops(rows: list[list], cats: list[Category]) -> list[dict]:
    """Строки «Операций» → записи с видом: расход | доход | служебная | проценты."""
    kinds = {c.name: c.type for c in cats}
    res = []
    for r in rows:
        d = from_serial(_cell(r, 0))
        if d is None or len(r) < 5:
            continue
        cat = str(r[4])
        res.append({"day": d, "amount": _num(r[1]), "account": str(r[2]), "dest": str(_cell(r, 3)),
                    "cat": cat, "comment": str(_cell(r, 5)),
                    "kind": "проценты" if cat == INTEREST_CAT else kinds.get(cat, "")})
    return res


def _sum(ops, kind, start: date, end: date) -> float:
    """Сумма по виду за [start, end]; расходы — положительным числом."""
    s = sum(o["amount"] for o in ops if o["kind"] == kind and start <= o["day"] <= end)
    return -s if kind in ("расход", "проценты") else s


def _by(ops, key, start: date, end: date) -> dict[str, float]:
    res: dict[str, float] = defaultdict(float)
    for o in ops:
        if o["kind"] == "расход" and start <= o["day"] <= end:
            res[o[key]] += -o["amount"]
    return res


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _prev_month(d: date) -> date:
    return (_month_start(d) - timedelta(days=1)).replace(day=1)


def _same_day_prev(d: date) -> date:
    """Тот же день прошлого месяца (31 → последний)."""
    p = _prev_month(d)
    return p.replace(day=min(d.day, calendar.monthrange(p.year, p.month)[1]))


def build(today: date, rows: list[list], accounts: list[Account], cats: list[Category],
          plan: list[budget.PlanRow], settings: dict, debts: dict) -> dict:
    ops = _ops(rows, cats)
    cash_accs = [a for a in accounts if a.type == "обычный"]
    debt_accs = [a for a in accounts if a.type in DEBT_TYPES]
    starts = [a.start_date for a in accounts if a.start_date]
    tracking_start = min(starts) if starts else (min((o["day"] for o in ops), default=today))

    # ---- свободно до зарплаты (та же логика, что /today) ----
    b_ops = [budget.Op(o["day"], o["amount"], o["account"], o["kind"], o["cat"], o["dest"]) for o in ops]
    free = None
    if settings.get("income_days"):
        f = budget.free_money(today, settings["income_days"], b_ops, plan,
                              sum(a.balance for a in cash_accs), settings.get("extra_debt", 0))
        free = {"until": _iso(f.until), "days_left": f.days_left, "cash": f.cash, "extra_debt": f.extra_debt,
                "payments": [{"date": _iso(d), "name": n, "amount": a} for d, n, a in f.payments],
                "free": f.free, "per_day": f.per_day, "spent_today": f.spent_today, "left_today": f.left_today,
                "uncovered": ({"date": _iso(f.uncovered[0]), "name": f.uncovered[1], "amount": f.uncovered[2]}
                              if f.uncovered else None)}

    # ---- месяц ----
    m0 = _month_start(today)
    m_days = calendar.monthrange(today.year, today.month)[1]
    pm0, pm_same = _prev_month(today), _same_day_prev(today)
    prev_full = tracking_start <= pm0  # прошлый месяц учтён целиком — с ним можно сравнивать
    spent_m = _sum(ops, "расход", m0, today)
    elapsed = (today - max(m0, tracking_start)).days + 1
    cats_m, cats_prev = _by(ops, "cat", m0, today), _by(ops, "cat", pm0, pm_same)
    month = {
        "key": today.strftime("%Y-%m"), "label": MONTHS_NOM[today.month - 1],
        "spent": spent_m, "income": _sum(ops, "доход", m0, today), "interest": _sum(ops, "проценты", m0, today),
        "avg_day": spent_m / elapsed if elapsed > 0 else 0,
        "forecast": spent_m / elapsed * (m_days - max(m0, tracking_start).day + 1) if elapsed > 0 else 0,
        "prev_same_day": _sum(ops, "расход", pm0, pm_same) if prev_full else None,
        "prev_label": MONTHS_NOM[pm0.month - 1],
        "days": [{"date": _iso(d), "spent": _sum(ops, "расход", d, d)}
                 for d in (m0 + timedelta(days=i) for i in range(m_days))],
        "by_cat": sorted(({"name": k, "spent": v, "prev": cats_prev.get(k) if prev_full else None}
                          for k, v in cats_m.items() if round(v)), key=lambda x: -x["spent"]),
        "by_acc": sorted(({"name": k, "spent": v} for k, v in _by(ops, "account", m0, today).items() if round(v)),
                         key=lambda x: -x["spent"]),
    }

    # ---- недели: последние 8 полных и текущая ----
    w0 = today - timedelta(days=today.weekday())
    weeks = []
    for i in range(7, -1, -1):
        s = w0 - timedelta(weeks=i)
        if s + timedelta(days=6) < tracking_start:
            continue
        weeks.append({"start": _iso(s), "spent": _sum(ops, "расход", s, min(s + timedelta(days=6), today)),
                      "current": i == 0})

    # ---- счета и долги ----
    by_name = {r["name"]: r for r in debts.get("rows", [])}
    debt_list = []
    for a in debt_accs:
        r = by_name.get(a.name, {})
        months_left = r.get("months")
        debt_list.append({"name": a.name, "balance": -a.balance, "start": -a.start_balance, "rate": a.rate,
                          "interest": r.get("interest", 0), "payment": r.get("payment", a.min_payment),
                          "months": months_left if isinstance(months_left, (int, float)) else None,
                          "pay_day": a.pay_day})
    debt_list.sort(key=lambda x: -x["rate"])
    total_debt = sum(x["balance"] for x in debt_list)
    accs = {
        "cash": [{"name": a.name, "balance": a.balance} for a in cash_accs if round(a.balance) or a.start_balance],
        "cash_total": sum(a.balance for a in cash_accs),
        "debts": debt_list, "debt_total": total_debt, "debt_start": sum(x["start"] for x in debt_list),
        "interest_month": sum(x["interest"] for x in debt_list),
        "paid_interest": debts.get("paid_interest", 0), "target": debts.get("target"),
        "net": sum(a.balance for a in accounts), "net_start": sum(a.start_balance for a in accounts),
    }

    # ---- операции для приложения: недели/месяцы/категории оно считает само ----
    # [дата, сумма, категория, счёт, куда, комментарий, вид]
    op_list = [[_iso(o["day"]), round(o["amount"], 2), o["cat"], o["account"], o["dest"], o["comment"], o["kind"]]
               for o in ops]
    # цвет категории = её место по тратам за всё время: не меняется от выбранного периода
    totals = _by(ops, "cat", tracking_start, today)
    cat_rank = sorted(totals, key=lambda c: -totals[c])

    upcoming = [{"date": _iso(d), "name": n, "amount": a}
                for d, n, a in budget.payments_between(plan, today, today + timedelta(days=15))]

    data = {
        "today": _iso(today), "tracking_start": _iso(tracking_start),
        "free": free, "month": month, "weeks": weeks,
        "accounts": accs, "upcoming": upcoming, "ops": op_list, "cat_rank": cat_rank,
    }
    data["insights"] = insights(data, ops, today)
    return data


def insights(d: dict, ops: list[dict], today: date) -> list[dict]:
    """Важные моменты: warn — требует действия, good — хорошо, info — к сведению. Порядок = важность."""
    res: list[dict] = []
    add = lambda level, title, text: res.append({"level": level, "title": title, "text": text})
    f, m, a = d["free"], d["month"], d["accounts"]

    if f and f["uncovered"]:
        u = f["uncovered"]
        dd = date.fromisoformat(u["date"])
        add("warn", f"До зарплаты не хватает {money(-f['free'])}",
            f"Платёж {dd.day} {MONTHS[dd.month - 1]} — {u['name']} ({money(u['amount'])}) не покрыт деньгами на счетах.")
    elif f and f["left_today"] < 0:
        add("warn", f"Сегодня сверх лимита на {money(-f['left_today'])}",
            f"Лимит {money(f['per_day'])} в день до зарплаты — завтра он станет меньше.")

    for x in a["debts"]:
        if x["balance"] > 0 and not x["payment"]:
            add("warn", f"{x['name']}: не указан мин. платёж",
                "Впиши его в «Счета» — без него не посчитать срок погашения и кассу.")

    grew = a["debt_total"] - a["debt_start"]
    if grew > 500:
        add("warn", f"Долг вырос на {money(grew)} с начала учёта",
            f"Было {money(a['debt_start'])}, сейчас {money(a['debt_total'])}. "
            "Траты с кредиток и проценты обгоняют платежи.")
    elif grew < -500:
        add("good", f"Долг меньше на {money(-grew)} с начала учёта",
            f"Было {money(a['debt_start'])}, сейчас {money(a['debt_total'])}.")

    if a["interest_month"] and m["avg_day"]:
        days = a["interest_month"] / m["avg_day"]
        add("info", f"Проценты ≈ {money(a['interest_month'])} в месяц",
            f"Это примерно {days:.0f} дн. твоих обычных трат. "
            f"Гасить сверх минимума — {a['target']}, самая высокая ставка.")

    credit = sum(-o["amount"] for o in ops if o["kind"] == "расход" and o["day"] >= date.fromisoformat(m["days"][0]["date"])
                 and o["account"] in {x["name"] for x in a["debts"]})
    if credit and m["spent"] and credit / m["spent"] > 0.25:
        add("warn", f"{credit / m['spent'] * 100:.0f}% трат месяца — с кредиток",
            f"{money(credit)} в долг под проценты. Плати с дебетовой карты, где можно.")

    if m["by_cat"]:
        c = m["by_cat"][0]
        line = f"{c['name']} — {money(c['spent'])}, {c['spent'] / m['spent'] * 100:.0f}% трат {MONTHS[today.month - 1]}."
        if c["prev"]:
            ch = (c["spent"] - c["prev"]) / c["prev"] * 100
            line += f" Месяц назад на эту дату: {money(c['prev'])} ({'+' if ch > 0 else '−'}{abs(ch):.0f}%)."
        add("info", "Больше всего уходит", line)

    wk = d["weeks"]
    full = [w for w in wk if not w["current"]]
    if len(full) >= 2 and full[-2]["spent"]:
        ch = (full[-1]["spent"] - full[-2]["spent"]) / full[-2]["spent"] * 100
        if abs(ch) >= 20:
            add("good" if ch < 0 else "info",
                f"Прошлая неделя: {'−' if ch < 0 else '+'}{abs(ch):.0f}% к позапрошлой",
                f"{money(full[-1]['spent'])} против {money(full[-2]['spent'])}.")

    zero = [x for x in m["days"] if x["spent"] == 0 and d["tracking_start"] <= x["date"] <= d["today"]]
    if zero:
        add("good", f"Дней без трат в этом месяце: {len(zero)}", "")
    return res
