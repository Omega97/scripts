@echo off
setlocal

echo Opening your private Obsidian vault...

:: Obsidian URI with properly encoded path
start "" "obsidian://open/?path=C:%%2FUsers%%2Fmonfalcone%%2FIl%%20mio%%20Drive%%2FDocuments%%2FOmar_private_vault"

endlocal
