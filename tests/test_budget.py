from datetime import date

from bot.budget import Op, PlanRow, free_money, next_income, payments_between

DAYS = [8, 25]
PLAN = [
    PlanRow("Кредитка Сбер — платёж", -10545, "ежемесячно", day=5),
    PlanRow("Кредит — платёж", -4083, "ежемесячно", day=27),
    PlanRow("Кредитка Альфа — мин. платёж", 0, "ежемесячно"),
]


def D(m, d, y=2026):
    return date(y, m, d)


def salary(d, amount=30000):
    return Op(d, amount, "Дебет Альфа", "доход", "Зарплата")


def test_until_next_salary_day():
    assert next_income(D(10, 10), DAYS, []) == D(10, 25)
    assert next_income(D(12, 30), DAYS, []) == D(1, 8, 2027)
    assert next_income(D(10, 25), DAYS, [salary(D(10, 25))]) == D(11, 8)  # в день зарплаты — уже до следующей


def test_early_salary_moves_to_next_day():
    """Аванс пришёл 19-го вместо 25-го — он уже на счетах, считаем до 8-го."""
    assert next_income(D(10, 24), DAYS, [salary(D(10, 19))]) == D(11, 8)
    assert next_income(D(10, 24), DAYS, [salary(D(10, 6))]) == D(10, 25)  # это зарплата за 8-е
    assert next_income(D(10, 24), DAYS, [salary(D(10, 20), 100)]) == D(10, 25)  # компенсация — не зарплата


def test_free_money_real_case():
    """24.10: на счетах 25 919, аванс уже пришёл, до 8.11 — кредит 27-го и Сбер 5-го."""
    ops = [salary(D(10, 19)), Op(D(10, 24), -342, "Дебет Альфа", "расход")]
    f = free_money(D(10, 24), DAYS, ops, PLAN, 25919)
    assert f.until == D(11, 8) and f.days_left == 15
    assert [n for _, n, _ in f.payments] == ["Кредит — платёж", "Кредитка Сбер — платёж"]
    assert f.free == 25919 - 4083 - 10545
    # лимит «на утро»: сегодняшние траты возвращаем, чтобы он не скакал в течение дня
    assert f.per_day == round((11291 + 342) / 15) and f.left_today == f.per_day - 342
    assert f.uncovered is None


def test_paid_monthly_payment_not_counted_twice():
    ops = [salary(D(10, 19)), Op(D(10, 22), -4083, "Дебет Альфа", "служебная", "Перевод", "Кредит")]
    f = free_money(D(10, 24), DAYS, ops, PLAN, 20000)
    assert [n for _, n, _ in f.payments] == ["Кредитка Сбер — платёж"]


def test_shortfall_names_uncovered_payment():
    f = free_money(D(10, 24), DAYS, [salary(D(10, 19))], PLAN, 5000)
    assert f.free == 5000 - 4083 - 10545 and f.per_day == 0
    assert f.uncovered[1] == "Кредитка Сбер — платёж"


def test_extra_debt_reduces_free():
    f = free_money(D(10, 10), DAYS, [], PLAN, 30000, extra_debt=15000)
    assert f.until == D(10, 25) and f.payments == [] and f.free == 15000 and f.per_day == 1000


def test_payment_on_salary_day_is_after_it():
    plan = [PlanRow("Налог", -1000, "ежемесячно", day=8)]
    assert payments_between(plan, D(9, 25), D(10, 8)) == []
    assert payments_between(plan, D(10, 8), D(10, 25)) == [(D(10, 8), "Налог", 1000)]


def test_one_time_and_statuses():
    plan = [PlanRow("Ремонт", -5000, "разово", once=D(10, 1)),
            PlanRow("Штраф", -700, "разово", once=D(10, 2), status="оплачено"),
            PlanRow("Сбер", -10545, "ежемесячно", day=5, status="оплачено")]
    names = [n for _, n, _ in payments_between(plan, D(9, 25), D(10, 8))]
    assert names == ["Ремонт", "Сбер"]  # ежемесячный не пропускаем: статус про прошлый месяц


def test_short_month_clamps_day():
    plan = [PlanRow("Аренда", -1, "ежемесячно", day=31)]
    assert payments_between(plan, D(2, 1), D(3, 1)) == [(D(2, 28), "Аренда", 1)]
