"""Бюджет на день и итоги трат."""
from datetime import date

from bot import reports
from bot.sheets import INTEREST_CAT, Category

CATS = [
    Category("Продукты", "расход", True, [], 2),
    Category("Такси", "расход", False, [], 3),
    Category("Зарплата", "доход", False, [], 4),
    Category("Перевод", "служебная", False, [], 5),
    Category(INTEREST_CAT, "расход", True, [], 6),
]
TODAY, MONTH = 46294, "2026-09"
CASH = {"Дебет Альфа", "Наличные"}


def op(day, amount, acc, cat, month=MONTH):
    return [day, amount, acc, "", cat, "", "бот", month]


def home(free, obligatory, days, upcoming=()):
    return {"free": free, "obligatory": obligatory, "days": days,
            "next_income": date(2026, 10, 8), "upcoming": list(upcoming)}


def test_spending_counts_only_real_expenses():
    ops = [
        op(TODAY, -200, "Дебет Альфа", "Такси"),
        op(TODAY, -300, "Кредитка Альфа", "Продукты"),   # трата, но не с «живых» денег
        op(TODAY, -6487, "Кредитка Сбер", INTEREST_CAT),  # проценты — не траты
        op(TODAY, -5000, "Дебет Альфа", "Перевод"),
        op(TODAY, 15000, "Дебет Альфа", "Зарплата"),
        op(TODAY - 1, -1000, "Наличные", "Продукты"),
        op(TODAY - 40, -999, "Наличные", "Продукты", "2026-08"),
    ]
    sp = reports.spending(ops, CATS, TODAY, MONTH, CASH)
    assert sp == {"day": 500, "day_cash": 200, "month": 1500}


def test_limit_is_fixed_for_the_day():
    """Лимит считается от денег на утро: трата уменьшает «осталось», а не сам лимит."""
    sp = {"day": 1000, "day_cash": 1000, "month": 1000}
    b = reports.budget(home(free=8000, obligatory=0, days=9), sp)  # утром было 9000
    assert b["limit"] == 1000 and b["left"] == 0


def test_real_case_deficit():
    """29.09: 1 887 ₽ на счетах, 1 289 ₽ уже потрачено, 10 545 ₽ Сберу до 8 октября."""
    sp = {"day": 1289, "day_cash": 1289, "month": 1289}
    h = home(1887, 10545, 9, [(date(2026, 10, 5), "Кредитка Сбер — платёж", -10545)])
    b = reports.budget(h, sp)
    assert b["morning"] == 3176 and b["spare"] == 3176 - 10545 and b["limit"] == 0
    text = reports.today_text(h, sp)
    assert "не хватает 7 369 ₽" in text and "−" not in text.split("\n")[0]
    assert "5 октября — Кредитка Сбер — платёж" in text
    assert "не хватает" in reports.spent_line(h, sp)


def test_today_text_ok_and_overspend():
    h = home(free=8500, obligatory=0, days=10)
    ok = reports.today_text(h, {"day": 500, "day_cash": 500, "month": 500})  # утром 9000 → 900/день
    assert "На сегодня осталось 400 ₽" in ok and "из 900 ₽" in ok
    over = reports.spent_line(home(7000, 0, 10), {"day": 2000, "day_cash": 2000, "month": 2000})
    assert "перерасход 1 100 ₽" in over
