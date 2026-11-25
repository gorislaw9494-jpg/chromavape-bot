# 🚀 Развёртывание бота на VPS (Ubuntu/Debian)

Инструкция для работы бота **24/7** на сервере. После настройки бот работает
автономно и перезапускается сам при сбоях и перезагрузке сервера.

## 1. Что нужно

- VPS с **Ubuntu 22.04/24.04** или **Debian 12** (минимально: 1 CPU, 512 МБ RAM, 5 ГБ диска).
- Доступ по SSH (root или пользователь с `sudo`).
- Токен бота и ваш Telegram ID (уже есть в `.env`).

## 2. Загрузить проект на сервер

С локального компьютера (Windows PowerShell / cmd, из папки проекта):

```bash
scp -r ./* root@ВАШ_IP:/root/chromavape/
```

Либо через Git, если проект в репозитории:

```bash
git clone <URL_репозитория> /root/chromavape
```

> Не загружайте папку `.venv` — она не нужна на сервере (создастся заново).

## 3. Установить (одной командой)

Подключитесь к серверу и запустите установочный скрипт:

```bash
ssh root@ВАШ_IP
cd /root/chromavape
chmod +x deploy/install.sh
sudo bash deploy/install.sh
```

Скрипт сам:
- поставит Python и зависимости;
- создаст системного пользователя `chromavape`;
- скопирует проект в `/opt/chromavape`;
- создаст виртуальное окружение и поставит `requirements.txt`;
- зарегистрирует systemd-службу с автозапуском.

## 4. Заполнить `.env` и запустить

```bash
sudo nano /opt/chromavape/.env
```

Вписать:

```
BOT_TOKEN=9248973784:AAH...
ADMIN_IDS=1931043258
SHOP_NAME=ChromaVape
SUPPORT_CONTACT=@ChromaVapeShop_ru_bot
DB_PATH=shop.db
```

Сохранить (Ctrl+O, Enter, Ctrl+X) и запустить:

```bash
sudo systemctl restart chromavape
sudo systemctl status chromavape
```

В статусе должно быть `active (running)`. Логи в реальном времени:

```bash
sudo journalctl -u chromavape -f
```

## 5. Управление службой

| Действие | Команда |
|---|---|
| Статус | `sudo systemctl status chromavape` |
| Перезапуск | `sudo systemctl restart chromavape` |
| Остановить | `sudo systemctl stop chromavape` |
| Запустить | `sudo systemctl start chromavape` |
| Логи | `sudo journalctl -u chromavape -f` |

Служба включена в автозапуск (`enable`) — после перезагрузки сервера бот
поднимется сам.

## 6. Обновление кода

```bash
# загрузить новые файлы, затем:
cd /opt/chromavape
sudo -u chromavape .venv/bin/pip install -r requirements.txt   # если менялись зависимости
sudo systemctl restart chromavape
```

## 7. Резервная копия базы

Все товары и заказы хранятся в `/opt/chromavape/shop.db`. Копируйте его для бэкапа:

```bash
sudo cp /opt/chromavape/shop.db /root/shop-backup-$(date +%F).db
```

## 8. Передача бота другому человеку

- **Передать владение ботом:** @BotFather → `/mybots` → выбрать бота →
  **Bot Settings → Transfer Ownership**. Токен остаётся прежним, бот продолжает
  работать на сервере без перезапуска.
- **Передать сервер:** отдайте доступ к VPS и файл `.env`. Новый владелец сможет
  управлять ботом через `systemctl` и менять товары через `/admin`.

## Частые проблемы

- **`active (running)` нет / бот молчит** — проверьте `journalctl -u chromavape -f`.
  Чаще всего неверный `BOT_TOKEN` в `.env`.
- **`Conflict: terminated by other getUpdates`** — бот запущен в двух местах
  (например, локально и на сервере). Остановите один экземпляр.
- **Нет команды `/admin`** — нажмите Start в боте от аккаунта с ID из `ADMIN_IDS`.
