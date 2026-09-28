"""Клавиатуры бота: главное меню и inline-кнопки.

callback_data (≤ 64 байт):
  u:{first}:{count}:{amount}  — отменить запись (count строк)
  c:{pid}:{idx}               — категория для новой записи
  ec|ea|eb:{row}:{amount}     — под записью: выбрать категорию / счёт / назад
  sc:{row}:{amount}:{idx}     — поменять категорию записи
  sa:{row}:{amount}:{key}     — поменять счёт записи
  pd:{key} / po:{key}         — платёж: долг выбран / своя сумма
  pb                          — платёж: назад к списку долгов
  pa:{key}:{amount}           — платёж: сумма выбрана → откуда
  px:{key}:{amount}:{src}     — платёж: записать
  pc                          — платёж: отмена
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as B
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from .reports import money

MENU_TODAY = "📊 Сегодня"
MENU_BALANCE = "💳 Баланс"
MENU_DEBTS = "📉 Долги"
MENU_MONTH = "📅 Месяц"
MENU_PAY = "💸 Платёж по долгу"
MENU_UNDO = "↩️ Отменить"


def num(x: float) -> str:
    """Сумма для callback_data: без хвостовых нулей и экспоненты."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_TODAY), KeyboardButton(text=MENU_BALANCE)],
            [KeyboardButton(text=MENU_DEBTS), KeyboardButton(text=MENU_MONTH)],
            [KeyboardButton(text=MENU_PAY), KeyboardButton(text=MENU_UNDO)],
        ],
        resize_keyboard=True,
        is_persistent=False,  # сворачивается иконкой в поле ввода
        input_field_placeholder="450 магнит · +15000 зп · 5000 > нал",
    )


def _grid(buttons: list[B], cols: int = 2) -> list[list[B]]:
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def record(first: int, count: int, amount: float, editable: bool) -> InlineKeyboardMarkup:
    """Под записью: отмена, а для одиночной строки — ещё смена категории и счёта."""
    a = num(amount)
    rows = [[B(text="↩️ Отменить", callback_data=f"u:{first}:{count}:{a}")]]
    if editable:
        rows[0] += [B(text="🏷 Категория", callback_data=f"ec:{first}:{a}"),
                    B(text="💳 Счёт", callback_data=f"ea:{first}:{a}")]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_category(names: list[str], prefix: str, back: str | None = None) -> InlineKeyboardMarkup:
    rows = _grid([B(text=n, callback_data=f"{prefix}:{i}") for i, n in enumerate(names)])
    if back:
        rows.append([B(text="« Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_account(accounts, prefix: str, back: str | None = None, show_balance: bool = False) -> InlineKeyboardMarkup:
    def label(a):
        return f"{a.name} · {money(a.balance)}" if show_balance else a.name
    rows = _grid([B(text=label(a), callback_data=f"{prefix}:{a.key}") for a in accounts],
                 cols=1 if show_balance else 2)
    if back:
        rows.append([B(text="« Назад" if back != "pc" else "✖️ Отмена", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_debt(debts, hot_key: str | None) -> InlineKeyboardMarkup:
    rows = []
    for a in debts:
        mark = "🔥 " if a.key == hot_key else ""
        rows.append([B(text=f"{mark}{a.name} · {money(-a.balance)}", callback_data=f"pd:{a.key}")])
    rows.append([B(text="✖️ Отмена", callback_data="pc")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_pay_amount(key: str, min_payment: float) -> InlineKeyboardMarkup:
    rows = []
    if min_payment > 0:
        rows.append([B(text=f"Минимум · {money(min_payment)}", callback_data=f"pa:{key}:{num(min_payment)}")])
    rows.append([B(text="✏️ Своя сумма", callback_data=f"po:{key}")])
    rows.append([B(text="« Назад", callback_data="pb"), B(text="✖️ Отмена", callback_data="pc")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
