@echo off
title TinyML Internship Environment Launcher

echo ========================================
echo    TinyML Internship Environment
echo ========================================
echo.

:: 1) Aprire il vault Obsidian
echo [1/5] Opening Obsidian Vault: TinyMLInternship...
start obsidian://open?vault=TinyMLInternship
timeout /t 2 /nobreak >nul
echo Vault opened successfully!
echo.

:: 2) Aprire il prompt dei comandi nel repo con ambiente virtuale attivato
echo [2/5] Opening Command Prompt with Virtual Environment...
cd /d "C:\Users\monfalcone\PycharmProjects\TinyMLInternship"

:: Crea un file batch temporaneo per il nuovo terminale
set TEMP_BAT=%TEMP%\tinyml_env_%RANDOM%.bat
(
echo @echo off
echo title TinyML Internship - Virtual Environment
echo cd /d "C:\Users\monfalcone\PycharmProjects\TinyMLInternship"
echo call .venv\Scripts\activate.bat
echo echo.
echo echo ========================================
echo echo    Virtual Environment Active!
echo echo ========================================
echo echo.
echo echo Python Version:
echo python --version
echo echo.
) > "%TEMP_BAT%"

:: Avvia il nuovo terminale con il file batch temporaneo
start cmd /k "%TEMP_BAT%"
timeout /t 2 /nobreak >nul
echo Command prompt opened with virtual environment!
echo.

:: 3) Avviare Grok Build nel repo principale
echo [3/5] Starting Grok Build...
cd /d "C:\Users\monfalcone\PycharmProjects\TinyMLInternship"

:: Esegui grok nella finestra principale (non nella nuova finestra)
echo Running grok in current terminal...
grok

echo.
:: 4) Aprire Esplora File alla directory del progetto
echo [4/5] Opening File Explorer in project directory...
start explorer "C:\Users\monfalcone\PycharmProjects\TinyMLInternship"
timeout /t 1 /nobreak >nul
echo File Explorer opened successfully!
echo.

:: 5) Aprire GitHub Desktop
echo [5/5] Opening GitHub Desktop...
:: Prova diversi modi per avviare GitHub Desktop
if exist "C:\Users\monfalcone\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\GitHub, Inc" (
    start "" "C:\Users\monfalcone\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\GitHub, Inc"
) else if exist "C:\Program Files\GitHub Desktop\GitHubDesktop.exe" (
    start "" "C:\Program Files\GitHub Desktop\GitHubDesktop.exe"
) else if exist "C:\Program Files (x86)\GitHub Desktop\GitHubDesktop.exe" (
    start "" "C:\Program Files (x86)\GitHub Desktop\GitHubDesktop.exe"
) else (
    echo GitHub Desktop not found in standard locations.
    echo Trying to launch via start command...
    start github-desktop://
)
timeout /t 2 /nobreak >nul
echo GitHub Desktop opened successfully!
echo.

echo.
echo ========================================
echo All operations completed!
echo ========================================
echo.
echo - Obsidian vault is open
echo - New terminal with virtual environment is open
echo - Grok has been executed in this window
echo - File Explorer is open in the project directory
echo - GitHub Desktop is open
echo.

:: Mantieni la finestra aperta
pause
