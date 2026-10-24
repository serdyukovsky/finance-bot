"""Тексты: итоги трат, /today, /month."""
from datetime import date

from bot import reports
from bot.budget import Free, PlanRow
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


def test_today_shows_how_free_money_is_counted():
    pays = [(date(2026, 10, 27), "Кредит — платёж", 4083), (date(2026, 11, 5), "Кредитка Сбер — платёж", 10545)]
    f = Free(date(2026, 10, 24), date(2026, 11, 8), 25919, pays, spent_today=342)
    text = reports.today_text(f, "Итоги дня", pays)
    assert text.startswith("Итоги дня")
    assert f"Можно ещё сегодня: {reports.money(434)}</b> (лимит {reports.money(776)} в день)" in text
    assert "До зарплаты 8 ноября</b> — 15 дн." in text
    assert f"− 27 октября — Кредит — платёж: {reports.money(4083)}" in text
    assert f"= свободно: <b>{reports.money(11291)}</b>" in text and "⚠️" not in text


def test_today_over_limit_and_shortfall():
    over = Free(date(2026, 10, 24), date(2026, 11, 8), 15000, [], spent_today=3000)
    assert "Сегодня сверх лимита" in reports.today_text(over, "", [])
    short = Free(date(2026, 10, 24), date(2026, 11, 8), 5000, [(date(2026, 11, 5), "Сбер", 10545)])
    text = reports.today_text(short, "", [])
    assert f"До зарплаты не хватает {reports.money(5545)}" in text and "не покрыт платёж 5 ноября — Сбер" in text


def test_month_interest_separate():
    ops = [op(TODAY, 15000, "А", "Зарплата"), op(TODAY, -450, "А", "Продукты"),
           op(TODAY, -6000, "С", INTEREST_CAT)]
    text = reports.month_text(ops, CATS, MONTH, set())
    assert "Траты: 450 ₽" in text and "Проценты по долгам: 6 000 ₽" in text
    assert "Итог: <b>+8 550 ₽</b>" in text and "Куда ушло</b>\nПродукты" in text
