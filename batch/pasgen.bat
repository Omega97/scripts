@echo off
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
python "%ROOT%\Programs\PasGen 2026.py" %*
