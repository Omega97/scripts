@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT=%%~fI"

set "VENV_DIR=%ROOT%\venvs\_nodenet_venv"
set "APP_DIR=%ROOT%\NodeNet"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at "%VENV_DIR%"
    echo Please run the setup for a new venv:
    echo   py -m venv "%ROOT%\venvs\_nodenet_venv"
    echo   "%ROOT%\venvs\_nodenet_venv\Scripts\pip" install -r "%APP_DIR%\requirements.txt"
    exit /b 1
)

pushd "%APP_DIR%"
"%VENV_DIR%\Scripts\python.exe" -m src.cli.main %*
set "EXITCODE=%ERRORLEVEL%"
popd

exit /b %EXITCODE%
