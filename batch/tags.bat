@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT=%%~fI"

:: Path to the venv relative to repo root
set "VENV_DIR=%ROOT%\venvs\tags_venv"

:: Path to the Python script
set "SCRIPT=%ROOT%\Programs\tags.py"

:: Check if venv exists
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at "%VENV_DIR%"
    echo Please run the setup for a new venv:
    echo   py -m venv "%ROOT%\venvs\tags_venv"
    echo   "%ROOT%\venvs\tags_venv\Scripts\pip" install requests
    exit /b 1
)

:: Run the script using the venv's Python
"%VENV_DIR%\Scripts\python.exe" "%SCRIPT%" %*

pause
