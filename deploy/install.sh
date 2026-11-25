#!/usr/bin/env bash
# Установка бота на Ubuntu/Debian VPS (запускать от root или через sudo).
set -euo pipefail

APP_DIR="/opt/chromavape"
APP_USER="chromavape"

echo "==> Установка системных пакетов"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git

echo "==> Создание пользователя $APP_USER"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> Копирование проекта в $APP_DIR"
mkdir -p "$APP_DIR"
# Скрипт запускается из папки проекта: копируем всё, кроме venv и базы
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude 'shop.db*' \
      --exclude '.env' ./ "$APP_DIR"/ || {
    cp -r bot.py config.py database.py keyboards.py utils.py filters.py \
          states.py handlers requirements.txt "$APP_DIR"/
}

echo "==> Виртуальное окружение и зависимости"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "==> Проверка .env"
if [ ! -f "$APP_DIR/.env" ]; then
    cp .env.example .env
    echo "!!! Заполните $APP_DIR/.env (BOT_TOKEN, ADMIN_IDS) и запустите скрипт снова."
fi

chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "==> Установка systemd-службы"
cp deploy/chromavape.service /etc/systemd/system/chromavape.service
systemctl daemon-reload
systemctl enable chromavape.service

echo
echo "Готово. Дальше:"
echo "  1) nano $APP_DIR/.env   # вписать BOT_TOKEN и ADMIN_IDS"
echo "  2) systemctl restart chromavape"
echo "  3) systemctl status chromavape"
echo "  4) journalctl -u chromavape -f   # логи в реальном времени"
