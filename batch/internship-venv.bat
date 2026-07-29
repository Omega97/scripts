@echo off
echo Starting TinyML Internship Environment...

:: Change to the project directory
cd /d "C:\Users\monfalcone\PycharmProjects\TinyMLInternship"

:: Activate the virtual environment
call .venv\Scripts\activate.bat

echo Virtual environment activated successfully!
echo Current path: %CD%
echo Python: 
python --version

:: Optional: Keep the window open
cmd /k