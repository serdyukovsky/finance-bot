"""Бюджет периода «от поступления до поступления» и проверка кассы.

Чистые функции без сети — покрыты тестами в tests/test_budget.py.

Период: между днями поступлений из «Главной» (B4 — зарплата, B5 — аванс; это самые поздние дни).
  бюджет   = доходы периода − обязательные платежи периода − доп. погашение долгов
  в день   = (бюджет − траты с начала периода) / дней до конца периода, включая сегодня

Доходы периода — фактически записанные поступления (зарплата не фиксированная, из «Плана» не берём).
Поступление за EARLY_DAYS дней до начала периода относится к нему: зарплата приходит 5–8, аванс 22–25.
Если учёт начат внутри периода, начальные остатки обычных счетов считаются его доходом,
а платежи до даты начала учёта — уже учтёнными в этих остатках.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

EARLY_DAYS = 3


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


@dataclass
class Period:
    start: date
    end: date  # не включительно: день следующего поступления

    def __contains__(self, d: date) -> bool:
        return self.start <= d < self.end


@dataclass
class Budget:
    period: Period
    days_left: int
    income: float
    obligatory: float
    extra_debt: float
    spent: float
    per_day: float  # ≥ 0
    overspent: float  # на сколько траты превысили бюджет, ≥ 0
    from_balances: bool  # в доходе есть начальные остатки (учёт начат в этом периоде)
    payments: list[tuple[date, str, float]] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.income - self.obligatory - self.extra_debt

    @property
    def left(self) -> float:
        return self.total - self.spent


@dataclass
class CashCheck:
    cash: float
    payments: list[tuple[date, str, float]]
    uncovered: tuple[date, str, float] | None  # первый платёж, на который не хватает

    @property
    def after(self) -> float:
        return self.cash - sum(a for _, _, a in self.payments)


def _on_day(y: int, m: int, d: int) -> date:
    """День месяца с поправкой на короткие месяцы: 31 → 30/28."""
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def _months(start: date, end: date):
    y, m = start.year, start.month
    while date(y, m, 1) < end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def period_for(today: date, income_days: list[int]) -> Period:
    days = sorted({d for d in income_days if d})
    marks = sorted(_on_day(y, m, d) for y, m in _months(today - timedelta(days=62), today + timedelta(days=62))
                   for d in days)
    start = max(x for x in marks if x <= today)
    end = min(x for x in marks if x > today)
    return Period(start, end)


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


def income_period(d: date, income_days: list[int]) -> Period:
    """К какому периоду относится поступление: за EARLY_DAYS до начала — уже к новому."""
    return period_for(d + timedelta(days=EARLY_DAYS), income_days)


def period_budget(today: date, income_days: list[int], ops: list[Op], plan: list[PlanRow],
                  cash_start: float, tracking_start: date | None, extra_debt: float = 0.0) -> Budget:
    p = period_for(today, income_days)
    from_balances = tracking_start is not None and tracking_start in p
    since = max(p.start, tracking_start) if from_balances else p.start

    income = cash_start if from_balances else 0.0
    income += sum(o.amount for o in ops if o.kind == "доход" and income_period(o.day, income_days) == p)
    payments = payments_between(plan, since, p.end)
    obligatory = sum(a for _, _, a in payments)
    spent = -sum(o.amount for o in ops if o.kind == "расход" and since <= o.day <= today)

    days_left = (p.end - today).days
    left = income - obligatory - extra_debt - spent
    return Budget(p, days_left, income, obligatory, extra_debt, spent,
                  per_day=round(left / days_left) if left > 0 else 0,
                  overspent=-left if left < 0 else 0.0,
                  from_balances=from_balances, payments=payments)


def cash_check(today: date, income_days: list[int], cash: float, plan: list[PlanRow]) -> CashCheck:
    """Хватит ли денег на обычных счетах на платежи до следующего поступления."""
    p = period_for(today, income_days)
    payments = payments_between(plan, today, p.end)
    left, uncovered = cash, None
    for pay in payments:
        left -= pay[2]
        if left < 0 and uncovered is None:
            uncovered = pay
    return CashCheck(cash, payments, uncovered)
