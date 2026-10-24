"""Свободные деньги до зарплаты.

Чистые функции без сети — покрыты тестами в tests/test_budget.py.

  свободно  = деньги на обычных счетах − обязательные платежи до зарплаты − доп. погашение долгов (Главная B6)
  в день    = (свободно + потрачено сегодня) / дней до зарплаты, включая сегодня
              — лимит «на утро»: в течение дня не скачет от каждой траты
  на сегодня осталось = в день − потрачено сегодня

До зарплаты — до ближайшего дня поступления из «Главной» (B4, B5), за который деньги ещё не пришли:
если «Зарплата» записана за EARLY_DAYS дней до этого дня или позже, она уже на счетах — считаем до следующего.
Ежемесячный платёж «Плана» уже сделан, если за PAID_DAYS дней до его даты был перевод на счёт
из его названия («Кредит — платёж» → «Кредит»). Разовые пропускаются по статусу «оплачено/пришло».
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

SALARY_CAT = "Зарплата"
SALARY_MIN = 1000  # мелочь вроде компенсации дороги — не зарплата
EARLY_DAYS = 7
PAID_DAYS = 10


@dataclass
class PlanRow:
    name: str
    amount: float
    repeat: str  # ежемесячно | разово
    day: int | None = None  # день месяца для «ежемесячно»
    once: date | None = None  # дата для «разово»
    status: str = ""


@dataclass
class Op:
    day: date
    amount: float
    account: str
    kind: str  # расход | доход | служебная | проценты
    cat: str = ""
    dest: str = ""


@dataclass
class Free:
    today: date
    until: date  # день зарплаты (не включительно)
    cash: float  # на обычных счетах
    payments: list[tuple[date, str, float]] = field(default_factory=list)
    extra_debt: float = 0.0
    spent_today: float = 0.0

    @property
    def days_left(self) -> int:
        return (self.until - self.today).days

    @property
    def obligatory(self) -> float:
        return sum(a for _, _, a in self.payments)

    @property
    def free(self) -> float:
        return self.cash - self.obligatory - self.extra_debt

    @property
    def per_day(self) -> float:
        return max(0, round((self.free + self.spent_today) / self.days_left))

    @property
    def left_today(self) -> float:
        return self.per_day - self.spent_today

    @property
    def uncovered(self) -> tuple[date, str, float] | None:
        """Первый платёж, на который не хватает денег на счетах."""
        left = self.cash
        for p in self.payments:
            left -= p[2]
            if left < 0:
                return p
        return None


def _on_day(y: int, m: int, d: int) -> date:
    """День месяца с поправкой на короткие месяцы: 31 → 30/28."""
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def _months(start: date, end: date):
    y, m = start.year, start.month
    while date(y, m, 1) < end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def income_dates(today: date, income_days: list[int]) -> list[date]:
    """Дни поступлений после сегодня, на ~2 месяца вперёд."""
    days = sorted({d for d in income_days if d})
    return sorted(x for y, m in _months(today, today + timedelta(days=70)) for d in days
                  if (x := _on_day(y, m, d)) > today)


def next_income(today: date, income_days: list[int], ops: list[Op]) -> date:
    """Ближайший день зарплаты, за который она ещё не пришла."""
    marks = income_dates(today, income_days)
    for d in marks:
        got = sum(o.amount for o in ops if o.kind == "доход" and o.cat == SALARY_CAT
                  and d - timedelta(days=EARLY_DAYS) <= o.day <= today)
        if got < SALARY_MIN:
            return d
    return marks[-1]


def plan_dates(row: PlanRow, start: date, end: date) -> list[date]:
    """Даты строки «Плана» в [start, end)."""
    if row.repeat == "разово":
        if row.status in ("пришло", "оплачено") or row.once is None:
            return []
        return [row.once] if start <= row.once < end else []
    if not row.day:
        return []
    return [d for y, m in _months(start, end) if start <= (d := _on_day(y, m, row.day)) < end]


def payments_between(plan: list[PlanRow], start: date, end: date) -> list[tuple[date, str, float]]:
    """Обязательные платежи (сумма < 0) в [start, end), по дате; суммы положительные."""
    res = [(d, r.name, -r.amount) for r in plan if r.amount < 0 for d in plan_dates(r, start, end)]
    return sorted(res)


def _paid(name: str, due: date, today: date, ops: list[Op]) -> bool:
    target = name.split(" — ")[0].strip()
    return any(o.kind == "служебная" and o.dest == target and due - timedelta(days=PAID_DAYS) <= o.day <= today
               for o in ops)


def free_money(today: date, income_days: list[int], ops: list[Op], plan: list[PlanRow],
               cash: float, extra_debt: float = 0.0) -> Free:
    until = next_income(today, income_days, ops)
    pays = [p for p in payments_between(plan, today, until) if not _paid(p[1], p[0], today, ops)]
    spent = -sum(o.amount for o in ops if o.kind == "расход" and o.day == today)
    return Free(today, until, cash, pays, extra_debt, spent)
