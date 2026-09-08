@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT=%%~fI"

set "VENV_DIR=%ROOT%\venvs\_tagstore_venv"
set "SCRIPT=%ROOT%\Programs\TagStore.py"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at "%VENV_DIR%"
    echo Please run the setup for a new venv:
    echo   py -m venv "%ROOT%\venvs\_tagstore_venv"
    echo   "%ROOT%\venvs\_tagstore_venv\Scripts\pip" install rich
    exit /b 1
)

"%VENV_DIR%\Scripts\python.exe" "%SCRIPT%" %*
