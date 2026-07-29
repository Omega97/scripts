@echo off

:: Start Docker Desktop
echo Starting Docker Desktop...

:: Launch Docker Desktop
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"


:: Useful prints
echo.
echo Docker Desktop is starting...
echo Please wait until the Docker icon in the system tray shows "Engine running".
echo.
echo After it's ready, you can run:
echo docker compose --env-file .\env\.env up -d
echo.
echo Exporter: http://localhost:9205/metrics 
echo Prometheus: http://localhost:9090/targets
echo Grafana: http://localhost:3000
echo Locust: http://localhost:8089
echo.

pause
