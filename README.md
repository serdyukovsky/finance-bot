# finance-bot

Личный учёт денег: Google Таблица + Telegram-бот для быстрого ввода.

- **Таблица** — хранилище и интерфейс. Разметка: `sheets/finance_setup.gs` (Apps Script, запускается один раз).
- **Бот** — Python, aiogram 3, gspread. Работает в Docker на своём сервере, пишет в таблицу через сервисный аккаунт Google.
- **Деплой** — push в `main` → GitHub Actions гоняет тесты и перезапускает бота на сервере.

## Как пользоваться ботом

| Пишешь | Что происходит |
|---|---|
| `450 магнит` | расход с Карты, категория по ключевому слову |
| `450 альфа такси` | расход с другого счёта (ключ из «Счетов») |
| `+15000 лендинг` | доход |
| `5000 > нал` | перевод Карта → Наличные |
| `10545 > сбер` | платёж по долгу; проценты месяца бот добавит оценкой один раз |
| `2к кафе` | «к» = тысячи |

Не угадал категорию — покажет кнопки и запомнит слово.
Команды: `/today`, `/balance`, `/debts`, `/month`, `/undo`, `/help` (или словами: «сегодня», «баланс», «долги», «месяц», «отмена»).
В 21:00 — напоминание, если за день ничего не записано, плюс платежи на ближайшие 2 дня и дни выписки по кредиткам.

## Правила таблицы

- «Операции» — только дописывать строки в конец, не вставлять строки в середину и не сортировать.
- Порядок колонок A–G не менять: бот пишет по позициям.
- Счета, ключи для бота, ставки и платежи — на листе «Счета»; категории и ключевые слова — в «Категориях».
- Раз в месяц сверять остатки с банком, расхождение — строкой «Корректировка».

## Установка

### 1. Сервисный аккаунт Google
1. https://console.cloud.google.com → создать проект `finance-bot`.
2. APIs & Services → Library → включить **Google Sheets API**.
3. APIs & Services → Credentials → Create credentials → **Service account** → создать (роли не нужны).
4. Открыть аккаунт → Keys → Add key → JSON. Скачается файл — это `google.json`.
5. Скопировать email аккаунта (`...@...iam.gserviceaccount.com`) и дать ему доступ **редактора** к таблице через «Настройки доступа».

### 2. Сервер
```bash
scp scripts/server_setup.sh root@SERVER:~
ssh root@SERVER 'bash server_setup.sh'
```
Скрипт поставит Docker, проверит доступ к Telegram и Google и создаст два ключа прямо на сервере.
Выведенное им нужно вставить на GitHub (deploy key и три секрета Actions), затем:
```bash
ssh root@SERVER 'bash server_setup.sh clone'
scp ~/Downloads/<файл>.json root@SERVER:~/finance-bot/secrets/google.json
ssh root@SERVER 'nano ~/finance-bot/.env'   # BOT_TOKEN, SHEET_ID, ALLOWED_USER_ID
ssh root@SERVER 'cd ~/finance-bot && docker compose up -d --build'
```
`ALLOWED_USER_ID` можно оставить пустым на первый запуск: бот ответит на `/start` твоим ID.

### 3. Обновления
Правки → `git push` в `main` → Actions сами прогонят тесты и перезапустят бота.
Логи: `ssh root@SERVER 'cd ~/finance-bot && docker compose logs --tail 100'`.

## Разработка

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q
```
