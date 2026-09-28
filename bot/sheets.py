"""Работа с Google Таблицей через сервисный аккаунт.

Все методы синхронные (gspread) — из асинхронного кода вызываются через
asyncio.to_thread.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta

import gspread
from gspread.http_client import BackOffHTTPClient
from gspread.utils import ValueRenderOption, ValueInputOption

OPS = "Операции"
ACC = "Счета"
CAT = "Категории"
PLAN = "План"
HOME = "Главная"
DEBT = "Долги"

EPOCH = date(1899, 12, 30)
INTEREST_CAT = "Проценты и комиссии"
INTEREST_NOTE = "оценка — сверь с банком"
TRANSFER_CAT = "Перевод"
DEBT_TYPES = ("кредитка", "кредит")


def to_serial(d: date) -> int:
    return (d - EPOCH).days


def from_serial(v) -> date | None:
    if isinstance(v, (int, float)) and v > 0:
        return EPOCH + timedelta(days=int(v))
    return None


def _num(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return 0.0


def _cell(row: list, i: int, default=""):
    return row[i] if i < len(row) else default


@dataclass
class Account:
    name: str
    type: str
    key: str
    rate: float
    min_payment: float
    pay_day: int | None
    statement_day: int | None
    balance: float

    @property
    def is_debt(self) -> bool:
        return self.type in DEBT_TYPES


@dataclass
class Category:
    name: str
    type: str  # расход | доход | служебная
    essential: bool
    keywords: list[str]
    row: int  # номер строки на листе «Категории»


class Sheets:
    CACHE_TTL = 60

    def __init__(self, credentials_path: str, sheet_id: str):
        # BackOff: при 429 (лимит 60 чтений/мин) ждёт и повторяет, а не падает
        gc = gspread.service_account(filename=credentials_path, http_client=BackOffHTTPClient)
        self.ss = gc.open_by_key(sheet_id)
        self._ws: dict[str, gspread.Worksheet] = {}
        self._cache: dict[str, tuple[float, object]] = {}
        # «прочитать номер строки → записать» должно быть атомарным:
        # aiogram обрабатывает сообщения параллельно
        self._write_lock = threading.Lock()

    # ---------- helpers ----------

    def ws(self, sheet: str) -> gspread.Worksheet:
        """Лист по имени; ss.worksheet() каждый раз тратит запрос на метаданные."""
        if sheet not in self._ws:
            self._ws[sheet] = self.ss.worksheet(sheet)
        return self._ws[sheet]

    def _get(self, sheet: str, rng: str) -> list[list]:
        return self.ws(sheet).get(
            rng, value_render_option=ValueRenderOption.unformatted
        )

    def _cached(self, key: str, loader, fresh: bool):
        now = time.time()
        if not fresh and key in self._cache and now - self._cache[key][0] < self.CACHE_TTL:
            return self._cache[key][1]
        val = loader()
        self._cache[key] = (now, val)
        return val

    # ---------- справочники ----------

    def accounts(self, fresh: bool = False) -> list[Account]:
        def load():
            res = []
            for r in self._get(ACC, "A2:J100"):
                name = str(_cell(r, 0)).strip()
                if not name:
                    continue
                pd = _cell(r, 5)
                sd = _cell(r, 6)
                res.append(Account(
                    name=name,
                    type=str(_cell(r, 1)).strip(),
                    key=str(_cell(r, 2)).strip().lower().replace("ё", "е"),
                    rate=_num(_cell(r, 3, 0)),
                    min_payment=_num(_cell(r, 4, 0)),
                    pay_day=int(pd) if isinstance(pd, (int, float)) and pd else None,
                    statement_day=int(sd) if isinstance(sd, (int, float)) and sd else None,
                    balance=_num(_cell(r, 9, 0)),
                ))
            return res
        return self._cached("accounts", load, fresh)

    def categories(self, fresh: bool = False) -> list[Category]:
        def load():
            res = []
            for i, r in enumerate(self._get(CAT, "A2:D200"), start=2):
                name = str(_cell(r, 0)).strip()
                if not name:
                    continue
                kws = [k.strip() for k in str(_cell(r, 3)).split(",") if k.strip()]
                res.append(Category(name, str(_cell(r, 1)).strip(), bool(_cell(r, 2, False)), kws, i))
            return res
        return self._cached("categories", load, fresh)

    def account_by_key(self, key: str) -> Account | None:
        key = key.lower().replace("ё", "е")
        for a in self.accounts():
            if a.key == key or a.name.lower() == key:
                return a
        return None

    def account_by_name(self, name: str) -> Account | None:
        for a in self.accounts():
            if a.name == name:
                return a
        return None

    def add_keyword(self, category: Category, word: str) -> None:
        if word in [k.lower() for k in category.keywords]:
            return
        new = ", ".join(category.keywords + [word])
        self.ws(CAT).update_acell(f"D{category.row}", new)
        self._cache.pop("categories", None)

    # ---------- операции ----------

    def append_ops(self, rows: list[list]) -> int:
        """rows: [дата(date), сумма, счёт, куда, категория, комментарий]. Возвращает первую строку."""
        with self._write_lock:
            ws = self.ws(OPS)
            first = len(ws.col_values(1)) + 1
            last = first + len(rows) - 1
            if last > ws.row_count:
                ws.add_rows(max(500, last - ws.row_count))
            values = [[to_serial(r[0]), r[1], r[2], r[3], r[4], r[5], "бот"] for r in rows]
            ws.update(values, f"A{first}:G{last}", value_input_option=ValueInputOption.raw)
        self._cache.pop("accounts", None)
        return first

    def ops(self) -> list[list]:
        """Все строки операций (без заголовка), значения без форматирования."""
        return self._get(OPS, "A2:H")

    def delete_bot_rows(self, first: int, count: int, amount: float) -> list[list] | None:
        """Удаляет строки, если они всё ещё бот-строки и сумма первой совпадает."""
        with self._write_lock:
            ws = self.ws(OPS)
            rows = ws.get(f"A{first}:G{first + count - 1}",
                          value_render_option=ValueRenderOption.unformatted)
            if len(rows) != count:
                return None
            if any(_cell(r, 6) != "бот" for r in rows):
                return None
            if abs(_num(_cell(rows[0], 1)) - amount) > 0.01:
                return None
            ws.delete_rows(first, first + count - 1)
        self._cache.pop("accounts", None)
        return rows

    # ---------- отчёты ----------

    def home(self) -> dict:
        v = self._get(HOME, "B8:B15")
        vals = [_cell(r, 0, "") for r in v] + [""] * (8 - len(v))
        upcoming = []
        for r in self._get(HOME, "D5:F20"):
            d = from_serial(_cell(r, 0))
            if d:
                upcoming.append((d, str(_cell(r, 1)), _num(_cell(r, 2, 0))))
        return {
            "free": _num(vals[0]),
            "next_income": from_serial(vals[1]),
            "days": _num(vals[2]),
            "obligatory": _num(vals[3]),
            "per_day": _num(vals[4]),
            "net_worth": _num(vals[5]),
            "debt": _num(vals[6]),
            "interest_month": _num(vals[7]),
            "upcoming": upcoming,
        }

    def debts(self) -> dict:
        rows = []
        for r in self._get(DEBT, "A4:J13"):
            name = str(_cell(r, 0)).strip()
            if not name:
                continue
            rows.append({
                "name": name,
                "balance": _num(_cell(r, 1, 0)),
                "rate": _num(_cell(r, 2, 0)),
                "interest": _num(_cell(r, 3, 0)),
                "payment": _num(_cell(r, 4, 0)),
                "principal": _num(_cell(r, 5, 0)),
                "months": _cell(r, 6, ""),
                "overpay": _cell(r, 7, ""),
            })
        extra = self._get(DEBT, "B17:B18")
        target = _cell(extra[0], 0, "—") if extra else "—"
        paid_interest = _num(_cell(extra[1], 0, 0)) if len(extra) > 1 else 0.0
        return {"rows": rows, "target": target, "paid_interest": paid_interest}

    def plan_upcoming(self, today: date, days: int) -> list[tuple[date, str, float]]:
        res = []
        for r in self._get(PLAN, "A2:H200"):
            d = from_serial(_cell(r, 7))
            if d and today <= d <= today + timedelta(days=days):
                res.append((d, str(_cell(r, 0)), _num(_cell(r, 1, 0))))
        return sorted(res)
