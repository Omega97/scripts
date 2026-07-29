@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT=%%~fI"

:: Run the shortcut from the Programs folder
start "" "%ROOT%\Programs\token_tactics.lnk"

exit
