@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT=%%~fI"

:: Path to the venv relative to repo root
set "VENV_DIR=%ROOT%\venvs\_md_to_pdf_venv"

:: Path to the Python script
set "SCRIPT=%ROOT%\Programs\md_to_pdf.py"

:: Check if venv exists
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at "%VENV_DIR%"
    echo Please run the setup for a new venv:
    echo   py -m venv "%ROOT%\venvs\_md_to_pdf_venv"
    echo   "%ROOT%\venvs\_md_to_pdf_venv\Scripts\pip" install markdown xhtml2pdf pygments
    exit /b 1
)

:: Run the script using the venv's Python
"%VENV_DIR%\Scripts\python.exe" "%SCRIPT%" %*
