@echo off
echo ========================================
echo    Stopping CloudProject Stack...
echo ========================================

:: Stop the containers
docker compose --env-file .\env\.env down

echo.
echo All containers have been stopped successfully.
echo.
echo Operation completed.
pause
