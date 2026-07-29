@echo off
echo Starting Anki...

:: Navigate to the directory
cd /d "C:\Users\monfalcone\AppData\Local\Programs\Anki"

:: Start the application and wait for the process to initialize
start "" /b "anki.exe"

:: Small pause to ensure you see the message (optional)
timeout /t 2 >nul

exit
