@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\pip.exe install -r requirements.txt
)

if not exist ".env" (
    echo.
    echo ВНИМАНИЕ: файл .env не найден.
    echo Скопируйте .env.example в .env и заполните BOT_TOKEN и ADMIN_IDS.
    echo.
    pause
    exit /b 1
)

echo Запуск бота...
.venv\Scripts\python.exe bot.py
pause
