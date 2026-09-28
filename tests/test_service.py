"""Service на поддельной таблице: запись, категории, долги, отмена, отчёты."""
from __future__ import annotations

import threading
from datetime import date
from zoneinfo import ZoneInfo

from bot import reports
from bot.config import Config
from bot.handlers import Service
from bot.sheets import INTEREST_CAT, Account, Category, Sheets, to_serial

TODAY = date(2026, 9, 28)


class FakeSheets:
    def __init__(self):
        self.rows: list[list] = []  # как «Операции» без заголовка: A..H
        self.accs = [
            Account("Карта", "обычный", "карта", 0, 0, None, None, 50000),
            Account("Кредитка Сбер", "кредитка", "сбер", 0.36, 10545, 5, None, -200000),
        ]
        self.cats = [
            Category("Продукты", "расход", True, ["магнит"], 2),
            Category("Кафе", "расход", False, [], 3),
            Category("Зарплата", "доход", False, ["зп"], 4),
            Category("Перевод", "служебная", False, [], 5),
            Category(INTEREST_CAT, "расход", True, [], 6),
        ]
        self.keywords_added = []

    def accounts(self, fresh=False):
        return self.accs

    def categories(self, fresh=False):
        return self.cats

    def account_by_key(self, key):
        return next((a for a in self.accs if a.key == key), None)

    def account_by_name(self, name):
        return next((a for a in self.accs if a.name == name), None)

    def add_keyword(self, cat, word):
        self.keywords_added.append((cat.name, word))

    def append_ops(self, rows):
        first = len(self.rows) + 2
        for r in rows:
            self.rows.append([to_serial(r[0]), r[1], r[2], r[3], r[4], r[5], "бот", r[0].strftime("%Y-%m")])
        return first

    def ops(self):
        return self.rows

    def delete_bot_rows(self, first, count, amount):
        chunk = self.rows[first - 2:first - 2 + count]
        if len(chunk) != count or chunk[0][1] != amount:
            return None
        del self.rows[first - 2:first - 2 + count]
        return chunk


def make():
    cfg = Config("t", "s", 1, "", ZoneInfo("Asia/Barnaul"), 21, "Карта")
    svc = Service(cfg, FakeSheets())
    svc.today = lambda: TODAY
    return svc


def test_expense_by_keyword():
    svc = make()
    text, kb = svc.handle_text("450 магнит")
    assert svc.sh.rows[0][1:5] == [-450, "Карта", "", "Продукты"]
    assert kb.inline_keyboard[0][0].callback_data.startswith("u:2:1:")


def test_income():
    svc = make()
    svc.handle_text("+15000 зп")
    assert svc.sh.rows[0][1] == 15000 and svc.sh.rows[0][4] == "Зарплата"


def test_category_button_writes_and_offers_undo():
    svc = make()
    _, kb = svc.handle_text("300 шаурма")
    assert not svc.sh.rows
    names = [b.text for row in kb.inline_keyboard for b in row]
    assert INTEREST_CAT not in names and "Зарплата" not in names
    pid = kb.inline_keyboard[0][0].callback_data.split(":")[1]
    text, undo = svc.choose_category(pid, names.index("Кафе"))
    assert svc.sh.rows[0][4] == "Кафе"
    assert svc.sh.keywords_added == [("Кафе", "шаурма")]
    assert undo is not None and undo.inline_keyboard[0][0].callback_data.startswith("u:2:1:")


def test_debt_payment_adds_interest_once():
    svc = make()
    text, kb = svc.handle_text("10545 > сбер")
    assert [r[4] for r in svc.sh.rows] == ["Перевод", INTEREST_CAT]
    assert svc.sh.rows[0][1:4] == [-10545, "Карта", "Кредитка Сбер"]
    assert svc.sh.rows[1][1] == -6000  # 200000 × 36% / 12
    assert kb.inline_keyboard[0][0].callback_data == "u:2:2:-10545.0"
    svc.handle_text("1000 > сбер")
    assert [r[4] for r in svc.sh.rows][2:] == ["Перевод"]


def test_undo_last_removes_transfer_with_interest():
    svc = make()
    svc.handle_text("450 магнит")
    svc.handle_text("10545 > сбер")
    msg = svc.undo_last()
    assert "Перевод" in msg and INTEREST_CAT in msg
    assert len(svc.sh.rows) == 1 and svc.sh.rows[0][4] == "Продукты"
    svc.undo_last()
    assert svc.sh.rows == []
    assert svc.undo_last() == "Нечего отменять."


def test_month_report():
    svc = make()
    svc.handle_text("+15000 зп")
    svc.handle_text("450 магнит")
    svc.handle_text("10545 > сбер")
    text = svc.month_report()
    assert "Доходы: 15\u202f000 ₽" in text
    assert "Расходы: 6\u202f450 ₽" in text  # продукты + проценты, перевод не расход
    assert "Внесено в долги: 10\u202f545 ₽, из них проценты 6\u202f000 ₽" in text


def test_append_ops_is_serialized():
    """Два параллельных сообщения не должны писать в одну строку."""
    class WS:
        row_count = 1000

        def __init__(self):
            self.col = ["Дата"]
            self.gate = threading.Barrier(2, timeout=0.3)

        def col_values(self, _):
            n = list(self.col)
            try:
                self.gate.wait()  # без блокировки оба потока прочитают одинаковую длину
            except threading.BrokenBarrierError:
                pass
            return n

        def update(self, values, rng, value_input_option=None):
            row = int(rng.split(":")[0][1:])
            assert row == len(self.col) + 1, "перезапись чужой строки"
            self.col += [v[0] for v in values]

    sh = Sheets.__new__(Sheets)
    sh._cache, sh._write_lock = {}, threading.Lock()
    ws = WS()
    sh._ws = {"Операции": ws}
    res = []
    ts = [threading.Thread(target=lambda: res.append(sh.append_ops([[TODAY, -1, "Карта", "", "Кафе", ""]])))
          for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(res) == [2, 3]


def test_money_format():
    assert reports.money(-10545) == "−10\u202f545 ₽"


def test_pct_format():
    assert reports.pct(0.5849) == "58,5%"
