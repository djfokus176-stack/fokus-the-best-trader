@echo off
setlocal
cd /d "%~dp0"
title FOKU$ M1 SCALPING - PAPER DEMO

echo ==========================================================
echo FOKU$ THE BEST TRADER - AUTOMATYCZNY PAPER M1 NA KOMPUTERZE
echo Jedna petla co minute. Bez zlecen prawdziwych.
echo Komputer musi byc wlaczony. ZAMKNIJ okno aby przerwac.
echo ==========================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Pierwsze uruchomienie: tworzenie srodowiska Python...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 goto :python_error
)
".venv\Scripts\python.exe" -c "import pandas, requests, openai" >nul 2>&1
if errorlevel 1 (
    echo Instalowanie bibliotek. Wymagane jest polaczenie z internetem.
    ".venv\Scripts\python.exe" -m pip install -r requirements-worker.txt
    if errorlevel 1 goto :dependencies_error
)
".venv\Scripts\python.exe" -m trader.windows_scalping
set "exitcode=%errorlevel%"
echo.
echo Praca skanera zakonczona. Kod: %exitcode%.
echo Jesli brakuje kluczy lokalnych, instrukcja jest w START_SCALPING_M1.md.
pause
exit /b %exitcode%

:python_error
echo BLAD: nie mozna utworzyc srodowiska. Zainstaluj Python 3.11 albo 3.12.
pause
exit /b 2

:dependencies_error
echo BLAD: nie mozna zainstalowac wymaganych bibliotek.
pause
exit /b 2
