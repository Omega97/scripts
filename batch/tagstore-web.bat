@echo off
setlocal

rem Change into the folder that contains the tagstore package
cd /d "%~dp0..\Programs"

rem Open the page in the default browser once the server is up
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"

rem Start the TagStore web server
python -m tagstore.web --root "C:\Users\monfalcone\AppData\Roaming\h\_homework" --port 8000
