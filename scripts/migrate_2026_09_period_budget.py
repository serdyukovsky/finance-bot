"""Миграция «Главной» под бюджет периода (сентябрь 2026).

1. A6:B6 — новая настройка «Доп. погашение долгов за период» = 0 (бот вычитает её из бюджета периода).
2. A12 — «Можно тратить в день» → «Касса в день до поступления»: формула B12 остаётся прежней
   (деньги − обязательные до поступления) / дни, а «можно в день» по бюджету периода теперь считает бот (/today).

Данные и формулы не трогает. Запуск на сервере (без --apply — только показать изменения):
  cd ~/finance-bot && docker compose exec -T bot python - [--apply] < scripts/migrate_2026_09_period_budget.py
"""
import sys

from bot.config import load
from bot.sheets import HOME, Sheets

APPLY = "--apply" in sys.argv
MONEY = "#,##0;[Red]-#,##0"
SETTING_BG = {"red": 254 / 255, "green": 247 / 255, "blue": 224 / 255}  # #fef7e0, как у B4:B5

OLD_A12, NEW_A12 = "Можно тратить в день", "Касса в день до поступления"
A6 = "Доп. погашение долгов за период"

cfg = load()
ws = Sheets(cfg.google_credentials, cfg.sheet_id).ws(HOME)
cur = ws.get("A6:B6")
a6, b6 = ((cur[0] if cur else []) + ["", ""])[:2]
a12 = ws.acell("A12").value

print("Сейчас:  A6=%r B6=%r | A12=%r" % (a6, b6, a12))
todo = []
if a6 == A6:
    print("A6:B6 — уже есть, пропускаю")
elif a6 or b6:
    sys.exit("A6:B6 заняты чем-то другим — остановился, ничего не изменено")
else:
    todo.append(f"A6 = {A6!r}, B6 = 0 (формат денег, фон настроек)")
if a12 == NEW_A12:
    print("A12 — уже переименована, пропускаю")
elif a12 != OLD_A12:
    sys.exit(f"A12 = {a12!r}, ожидал {OLD_A12!r} — остановился, ничего не изменено")
else:
    todo.append(f"A12: {OLD_A12!r} → {NEW_A12!r} (формула B12 не меняется)")

print("Изменения:" if todo else "Нечего менять.")
for t in todo:
    print("  •", t)
if not APPLY:
    print("\nЭто просмотр. Применить: добавь --apply")
    sys.exit(0)

if any(t.startswith("A6") for t in todo):
    ws.update([[A6, 0]], "A6:B6")
    ws.format("B6", {"numberFormat": {"type": "NUMBER", "pattern": MONEY}, "backgroundColor": SETTING_BG})
if any(t.startswith("A12") for t in todo):
    ws.update([[NEW_A12]], "A12")
print("Применено. Сейчас: A6:B6 =", ws.get("A6:B6"), "| A12 =", ws.acell("A12").value, "| B12 =", ws.acell("B12").value)
