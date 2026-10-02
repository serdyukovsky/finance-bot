"""Тексты: итоги трат, /today, /month."""
from datetime import date

from bot import reports
from bot.budget import PlanRow, cash_check, period_budget, Op
from bot.sheets import INTEREST_CAT, Category

CATS = [
    Category("Продукты", "расход", True, [], 2),
    Category("Такси", "расход", False, [], 3),
    Category("Зарплата", "доход", False, [], 4),
    Category("Перевод", "служебная", False, [], 5),
    Category(INTEREST_CAT, "расход", True, [], 6),
]
TODAY, MONTH = 46294, "2026-09"  # 29.09.2026
PLAN = [PlanRow("Кредитка Сбер — платёж", -10545, "ежемесячно", day=5),
        PlanRow("Кредит — платёж", -4083, "ежемесячно", day=27)]


def op(day, amount, acc, cat, month=MONTH):
    return [day, amount, acc, "", cat, "", "бот", month]


def test_spending_counts_only_real_expenses():
    ops = [
        op(TODAY, -200, "Дебет Альфа", "Такси"),
        op(TODAY, -300, "Кредитка Альфа", "Продукты"),
        op(TODAY, -6487, "Кредитка Сбер", INTEREST_CAT),
        op(TODAY, -5000, "Дебет Альфа", "Перевод"),
        op(TODAY, 15000, "Дебет Альфа", "Зарплата"),
        op(TODAY - 1, -1000, "Наличные", "Продукты"),
        op(TODAY - 40, -999, "Наличные", "Продукты", "2026-08"),
    ]
    assert reports.spending(ops, CATS, TODAY, MONTH) == {"day": 500, "month": 1500}


def test_spent_line_format():
    assert reports.spent_line({"day": 1289, "month": 5400}, MONTH) == \
        "<i>Сегодня: 1 289 ₽ · Сентябрь: 5 400 ₽</i>"


def test_today_real_case():
    """29.09: учёт с 28.09, на утро 3 176 ₽, потрачено 1 289 ₽, Сберу 10 545 ₽ 5 октября."""
    today = date(2026, 9, 29)
    b = period_budget(today, [8, 25], [Op(today, -1289, "Дебет Альфа", "расход")], PLAN,
                      3176, date(2026, 9, 28))
    c = cash_check(today, [8, 25], 1887, PLAN)
    text = reports.today_text(b, c, "Итоги дня", [(date(2026, 10, 5), "Кредитка Сбер — платёж", 10545)])
    assert "Бюджет периода превышен на 8 658 ₽" in text and "можно в день: 0 ₽" in text
    assert "Период 25 сентября → 8 октября</b>, осталось 9 дн." in text
    assert "Кредит — платёж" not in text  # 27.09 — до начала учёта
    assert "не покрыт платёж 5 октября — Кредитка Сбер — платёж" in text


def test_today_ok_and_no_income():
    today = date(2026, 10, 10)
    ok = period_budget(today, [8, 25], [Op(date(2026, 10, 6), 60000, "А", "доход")], PLAN, 0, None)
    text = reports.today_text(ok, cash_check(today, [8, 25], 50000, PLAN), "", [])
    assert "Можно тратить в день: 4 000 ₽" in text and "✅" in text  # 60000 / 15 дн.
    empty = period_budget(today, [8, 25], [], PLAN, 0, None)
    assert "поступлений в этом периоде не записано" in reports.today_text(
        empty, cash_check(today, [8, 25], 0, PLAN), "", [])


def test_month_interest_separate():
    ops = [op(TODAY, 15000, "А", "Зарплата"), op(TODAY, -450, "А", "Продукты"),
           op(TODAY, -6000, "С", INTEREST_CAT)]
    text = reports.month_text(ops, CATS, MONTH, set())
    assert "Траты: 450 ₽" in text and "Проценты по долгам: 6 000 ₽" in text
    assert "Итог: <b>+8 550 ₽</b>" in text and "Куда ушло</b>\nПродукты" in text
