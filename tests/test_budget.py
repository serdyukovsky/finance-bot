from datetime import date

from bot.budget import Op, Period, PlanRow, cash_check, payments_between, period_budget, period_for

DAYS = [8, 25]
PLAN = [
    PlanRow("Кредитка Сбер — платёж", -10545, "ежемесячно", day=5),
    PlanRow("Кредит — платёж", -4083, "ежемесячно", day=27),
    PlanRow("Кредитка Альфа — мин. платёж", 0, "ежемесячно"),
]


def D(m, d, y=2026):
    return date(y, m, d)


def test_period_crosses_month():
    assert period_for(D(9, 29), DAYS) == Period(D(9, 25), D(10, 8))
    assert period_for(D(12, 30), DAYS) == Period(D(12, 25), D(1, 8, 2027))


def test_first_and_last_day_of_period():
    first = period_budget(D(10, 8), DAYS, [Op(D(10, 6), 50000, "Дебет Альфа", "доход")], PLAN, 0, None)
    assert first.period == Period(D(10, 8), D(10, 25)) and first.days_left == 17
    last = period_budget(D(10, 24), DAYS, [Op(D(10, 6), 50000, "Дебет Альфа", "доход")], PLAN, 0, None)
    assert last.days_left == 1
    # в периоде 8→25 нет платежей (5-е и 27-е вне него): весь доход — на траты
    assert first.total == 50000 and first.per_day == round(50000 / 17) and last.per_day == 50000


def test_payment_on_income_day_belongs_to_new_period():
    plan = [PlanRow("Налог", -1000, "ежемесячно", day=8)]
    assert payments_between(plan, D(9, 25), D(10, 8)) == []
    assert payments_between(plan, D(10, 8), D(10, 25)) == [(D(10, 8), "Налог", 1000)]


def test_early_salary_goes_to_next_period():
    ops = [Op(D(9, 23), 30000, "Дебет Альфа", "доход"),   # аванс раньше 25-го
           Op(D(10, 5), 60000, "Дебет Альфа", "доход")]   # зарплата раньше 8-го
    b = period_budget(D(10, 1), DAYS, ops, PLAN, 0, None)
    assert b.income == 30000
    assert b.obligatory == 10545 + 4083  # 27.09 и 05.10
    assert period_budget(D(10, 10), DAYS, ops, PLAN, 0, None).income == 60000


def test_overspend_shows_zero_and_amount():
    ops = [Op(D(9, 26), 20000, "Дебет Альфа", "доход"), Op(D(9, 28), -9000, "Дебет Альфа", "расход")]
    b = period_budget(D(9, 29), DAYS, ops, PLAN, 0, None)
    # 20000 − (4083 + 10545) − 9000 = −3628
    assert b.per_day == 0 and b.overspent == 3628 and b.left == -3628


def test_interest_and_transfers_are_not_spending():
    ops = [Op(D(9, 26), 30000, "А", "доход"), Op(D(9, 28), -6487, "С", "проценты"),
           Op(D(9, 28), -10545, "А", "служебная"), Op(D(9, 28), -500, "А", "расход")]
    assert period_budget(D(9, 29), DAYS, ops, PLAN, 0, None).spent == 500


def test_extra_debt_reduces_budget():
    ops = [Op(D(10, 7), 60000, "А", "доход")]
    b = period_budget(D(10, 10), DAYS, ops, PLAN, 0, None, extra_debt=15000)
    assert b.total == 45000 and b.days_left == 15 and b.per_day == 3000


def test_first_period_counts_start_balances():
    """Учёт начат 28.09: аванс уже в остатках, платёж 27.09 уже оплачен из них."""
    ops = [Op(D(9, 29), -1289, "Дебет Альфа", "расход")]
    b = period_budget(D(9, 29), DAYS, ops, PLAN, cash_start=3176, tracking_start=D(9, 28))
    assert b.from_balances and b.income == 3176
    assert [n for _, n, _ in b.payments] == ["Кредитка Сбер — платёж"]
    assert b.overspent == 10545 + 1289 - 3176 and b.per_day == 0
    # в следующем периоде начальные остатки уже не доход
    assert not period_budget(D(10, 10), DAYS, ops, PLAN, 3176, D(9, 28)).from_balances


def test_one_time_and_statuses():
    plan = [PlanRow("Ремонт", -5000, "разово", once=D(10, 1)),
            PlanRow("Штраф", -700, "разово", once=D(10, 2), status="оплачено"),
            PlanRow("Сбер", -10545, "ежемесячно", day=5, status="оплачено")]
    names = [n for _, n, _ in payments_between(plan, D(9, 25), D(10, 8))]
    assert names == ["Ремонт", "Сбер"]  # ежемесячный не пропускаем: статус про прошлый месяц


def test_short_month_clamps_day():
    plan = [PlanRow("Аренда", -1, "ежемесячно", day=31)]
    assert payments_between(plan, D(2, 1), D(3, 1)) == [(D(2, 28), "Аренда", 1)]


def test_cash_check_names_uncovered_payment():
    c = cash_check(D(9, 29), DAYS, 1887, PLAN)
    assert c.uncovered[1] == "Кредитка Сбер — платёж" and c.after == 1887 - 10545
    assert cash_check(D(9, 29), DAYS, 20000, PLAN).uncovered is None
