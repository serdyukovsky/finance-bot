"""Данные для мини-приложения."""
from datetime import date

from bot import analytics
from bot.budget import PlanRow
from bot.sheets import INTEREST_CAT, Account, Category, to_serial

TODAY = date(2026, 10, 24)
ACCS = [Account("Дебет Альфа", "обычный", "альфа", 0, 0, None, None, 20000, 2000, date(2026, 9, 28)),
        Account("Кредитка Альфа", "кредитка", "кальфа", 0.5849, 0, None, 26, -90000, -75000, date(2026, 9, 28))]
CATS = [Category("Кафе", "расход", False, [], 2), Category("Продукты", "расход", True, [], 3),
        Category("Зарплата", "доход", False, [], 4), Category("Перевод", "служебная", False, [], 5),
        Category(INTEREST_CAT, "расход", True, [], 6)]


def row(d, amount, acc, cat, dest=""):
    return [to_serial(d), amount, acc, dest, cat, "", "бот", d.strftime("%Y-%m")]


def build(rows):
    return analytics.build(TODAY, rows, ACCS, CATS, [PlanRow("Кредит — платёж", -4000, "ежемесячно", day=27)],
                           {"income_days": [8, 25], "extra_debt": 0},
                           {"rows": [{"name": "Кредитка Альфа", "interest": 4400, "payment": 0, "months": "укажи платёж"}],
                            "target": "Кредитка Альфа", "paid_interest": 0})


def test_free_and_ops():
    d = build([row(date(2026, 10, 19), 30000, "Дебет Альфа", "Зарплата"),
               row(TODAY, -500, "Кредитка Альфа", "Кафе"), row(date(2026, 10, 20), -300, "Дебет Альфа", "Продукты")])
    assert d["free"]["until"] == "2026-11-08" and d["free"]["free"] == 16000
    assert d["ops"][1] == ["2026-10-24", -500, "Кафе", "Кредитка Альфа", "", "", "расход"]
    assert d["cat_rank"] == ["Кафе", "Продукты"]  # цвет категории — по тратам за всё время


def test_insights_flag_debt_growth_and_missing_payment():
    titles = [i["title"] for i in build([row(TODAY, -500, "Кредитка Альфа", "Кафе")])["insights"]]
    assert "Кредитка Альфа: не указан мин. платёж" in titles
    assert any(t.startswith("Долг вырос на") for t in titles)
