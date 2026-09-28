#!/usr/bin/env bash
# Первичная настройка сервера под finance-bot (Ubuntu).
# Запуск на сервере:  bash server_setup.sh
# Ключи создаются здесь, на сервере, и никуда не отправляются.
set -euo pipefail

REPO="serdyukovsky/finance-bot"
SSH_DIR="$HOME/.ssh"
mkdir -p "$SSH_DIR" && chmod 700 "$SSH_DIR"

echo "== 1. Пакеты и Docker"
if command -v apt-get >/dev/null; then
  sudo apt-get update -qq && sudo apt-get install -y -qq git curl >/dev/null
fi
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
docker --version
docker compose version

echo "== 2. Доступность сервисов"
for url in https://api.telegram.org https://sheets.googleapis.com https://oauth2.googleapis.com; do
  code=$(curl -s -o /dev/null -m 10 -w "%{http_code}" "$url" || echo "нет связи")
  echo "$url -> $code"
done
# этот IP закреплён за api.telegram.org в docker-compose.yml (extra_hosts)
code=$(curl -s -o /dev/null -m 10 -w "%{http_code}" --resolve api.telegram.org:443:149.154.167.220 https://api.telegram.org || echo "нет связи")
echo "api.telegram.org через 149.154.167.220 -> $code"

echo "== 3. Ключ для чтения репозитория (deploy key)"
if [ ! -f "$SSH_DIR/finance_repo" ]; then
  ssh-keygen -t ed25519 -N "" -C "finance-bot-server" -f "$SSH_DIR/finance_repo" >/dev/null
fi
if ! grep -q "Host github-finance" "$SSH_DIR/config" 2>/dev/null; then
  cat >> "$SSH_DIR/config" <<CFG

Host github-finance
  HostName github.com
  User git
  IdentityFile $SSH_DIR/finance_repo
  IdentitiesOnly yes
CFG
  chmod 600 "$SSH_DIR/config"
fi
ssh-keyscan -q github.com >> "$SSH_DIR/known_hosts" 2>/dev/null || true

echo "== 4. Ключ, с которым GitHub Actions будет заходить на сервер"
if [ ! -f "$SSH_DIR/finance_deploy" ]; then
  ssh-keygen -t ed25519 -N "" -C "finance-bot-actions" -f "$SSH_DIR/finance_deploy" >/dev/null
fi
# ключ Actions умеет только одно — задеплоить finance-bot (на сервере есть другие проекты)
if ! grep -q "finance-bot-actions" "$SSH_DIR/authorized_keys" 2>/dev/null; then
  DEPLOY_CMD='cd ~/finance-bot && git pull --ff-only && docker compose up -d --build && docker image prune -f --filter label=com.docker.compose.project=finance-bot'
  echo "restrict,command=\"$DEPLOY_CMD\" $(cat "$SSH_DIR/finance_deploy.pub")" >> "$SSH_DIR/authorized_keys"
  chmod 600 "$SSH_DIR/authorized_keys"
fi

if [ "${1:-}" != "clone" ]; then
cat <<TXT

==================== ЧТО СДЕЛАТЬ НА GITHUB ====================
А) https://github.com/$REPO/settings/keys → Add deploy key
   Title: server, галочку «Allow write access» НЕ ставить. Ключ:

$(cat "$SSH_DIR/finance_repo.pub")

Б) https://github.com/$REPO/settings/secrets/actions → New repository secret
   SERVER_HOST    = $(curl -s -m 5 https://api.ipify.org || hostname -I | awk '{print $1}')
   SERVER_USER    = $(whoami)
   SERVER_SSH_KEY = весь текст ниже, включая строки BEGIN/END:

$(cat "$SSH_DIR/finance_deploy")

После этого запусти:  bash server_setup.sh clone
================================================================
TXT
fi

if [ "${1:-}" = "clone" ]; then
  echo "== 5. Клонирую репозиторий"
  [ -d "$HOME/finance-bot/.git" ] || git clone "git@github-finance:$REPO.git" "$HOME/finance-bot"
  cd "$HOME/finance-bot"
  git remote set-url origin "git@github-finance:$REPO.git"
  mkdir -p secrets
  [ -f .env ] || cp .env.example .env
  echo "Готово. Дальше: заполни ~/finance-bot/.env и положи ключ Google в ~/finance-bot/secrets/google.json,"
  echo "потом:  cd ~/finance-bot && docker compose up -d --build && docker compose logs -f"
fi
