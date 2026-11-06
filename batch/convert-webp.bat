@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT=%%~fI"

set "VENV_DIR=%ROOT%\venvs\_convert_webp_venv"
set "SCRIPT=%ROOT%\Programs\convert_webp.py"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at "%VENV_DIR%"
    echo Please run the setup for a new venv:
    echo   py -m venv "%ROOT%\venvs\_convert_webp_venv"
    echo   "%ROOT%\venvs\_convert_webp_venv\Scripts\pip" install Pillow
    exit /b 1
)

"%VENV_DIR%\Scripts\python.exe" "%SCRIPT%" %*
