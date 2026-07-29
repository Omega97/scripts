@echo off
cd C:\Users\monfalcone\PycharmProjects\VillageHorizons

echo Starting Village Horizons server on http://localhost:8080 ...
start "Village Horizons Server" py -3.12 -m http.server 8080

timeout /t 2 /nobreak >nul

start firefox http://localhost:8080

echo.
echo Game opened in Firefox. Close the "Village Horizons Server" window to stop the server.
echo.
