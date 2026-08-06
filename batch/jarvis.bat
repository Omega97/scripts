@echo off
:: Force the command prompt to use UTF-8 encoding for emoji support
chcp 65001 > nul

title Omar's Grok Telegram Bot

:: 1. Navigate to your project folder
cd /d "C:\Users\monfalcone\PycharmProjects\Omar_private_vault"

:: 2. Check if the virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at .venv\Scripts\activate.bat
    pause
    exit /b
)

:: 3. Activate the virtual environment
call .venv\Scripts\activate.bat

:: 4. Run the bot
python telegram\bot.py

:: 5. If the bot stops or crashes, keep the window open so you can see the error
pause
