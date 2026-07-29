@echo off
setlocal enabledelayedexpansion

echo SHA256 hashes for files in: %CD%
echo ================================================================
echo.

:: Process each file in current directory (skip directories)
for %%F in (*.*) do (
    set "attrs=%%~aF"
    if not "!attrs!"=="" (
        if "!attrs:~0,1!" neq "d" (
            set "hash="
            for /f "tokens=1 delims= " %%H in ('certutil -hashfile "%%F" SHA256 2^>nul ^| findstr /r "^[0-9a-f][0-9a-f]*$"') do (
                if not defined hash set "hash=%%H"
            )
            if defined hash (
                echo !hash!  %%F
            ) else (
                echo ERROR: Failed to hash "%%F"
            )
        )
    )
)

echo.
echo ================================================================
echo Done.
