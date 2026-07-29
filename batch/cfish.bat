@echo off
cls

:: Abilita l'elaborazione delle sequenze di escape ANSI per la sessione corrente
reg add "HKCU\Console" /v VirtualTerminalLevel /t REG_DWORD /d 1 /f >nul 2>&1

:: Definizione del carattere ESC tramite comando prompt
for /F "tokens=1,2 delims=#" %%a in ('"prompt #$H#$E# & echo on & for %%b in (1) do rem"') do set "ESC=%%b"

set "RESET=%ESC%[0m"
set "BLUE=%ESC%[94m"
set "YELLOW=%ESC%[93m"
set "CYAN=%ESC%[96m"

echo %CYAN%============================================================%RESET%
echo                    %CYAN%CFISH CHESS ENGINE%RESET%
echo %CYAN%============================================================%RESET%
echo  Inizializzazione e Opzioni:
echo   - %BLUE%uci%RESET%                  : Inizializza il motore
echo   - %BLUE%isready%RESET%              : Verifica stato (risponde 'readyok')
echo   - %BLUE%setoption name Hash value %YELLOW%1024%RESET% : Allocazione RAM in MB
echo   - %BLUE%setoption name Threads value %YELLOW%4%RESET% : Imposta i thread CPU
echo   - %BLUE%ucinewgame%RESET%           : Resetta la Transposition Table (nuova partita)
echo.
echo  Impostazione Posizione:
echo   - %BLUE%position startpos%RESET%   : Posizione iniziale standard
echo   - %BLUE%position startpos moves %YELLOW%e2e4 e7e5%RESET% : Posizione + mosse
echo   - %BLUE%position fen %YELLOW%[stringa_FEN]%RESET% : Posizione da FEN specifica
echo.
echo  Ricerca ed Esecuzione:
echo   - %BLUE%go depth %YELLOW%20%RESET%          : Ricerca a profondita fissa (es. %YELLOW%20%RESET% semi-mosse)
echo   - %BLUE%go movetime %YELLOW%5000%RESET%      : Analisi per N millisecondi (es. %YELLOW%5%RESET% sec)
echo   - %BLUE%go nodes %YELLOW%10000000%RESET%      : Interrompe dopo N nodi analizzati
echo   - %BLUE%go wtime %YELLOW%300000%RESET% %BLUE%btime %YELLOW%300000%RESET% : Simulazione tempo di gioco reale
echo   - %BLUE%go infinite%RESET%         : Ricerca continua (usa %BLUE%stop%RESET% per fermare)
echo   - %BLUE%stop%RESET%                 : Ferma la ricerca e restituisce %BLUE%bestmove%RESET%
echo.
echo  Strumenti Utili e Debug:
echo   - %BLUE%d%RESET%                    : Stampa la scacchiera grafica ASCII + FEN
echo   - %BLUE%eval%RESET%                 : Mostra la valutazione statica dettagliata (NNUE)
echo   - %BLUE%compiler%RESET%             : Mostra i flag del compilatore usati per la build
echo   - %BLUE%quit%RESET%                 : Chiude ed esce da Cfish
echo %CYAN%============================================================%RESET%
echo.

rem Spostamento nella cartella dei sorgenti ed esecuzione
cd /d "%USERPROFILE%\PycharmProjects\TinyMLInternship\Cfish\src"
cfish.exe
