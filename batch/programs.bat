@echo off
echo.
echo Folder: %~dp0
echo.
for /f "delims=" %%F in ('dir /b /on "%~dp0*.bat" 2^>nul') do echo %%~nF
