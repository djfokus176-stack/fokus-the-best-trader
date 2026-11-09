@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FOKU$ THE BEST TRADER - TERMINAL WINDOWS

echo ===========================================================
echo   FOKU$ THE BEST TRADER - TERMINAL NA KOMPUTERZE
echo ===========================================================
echo.
echo To jest INTERFEJS wykresow, nie skaner PAPER w tle.
echo Klucze ze Streamlit Cloud NIE sa automatycznie na komputerze.
echo Okno CMD musi pozostac otwarte, gdy korzystasz z programu.
echo.

if not exist "app.py" goto missing_app

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Przygotowuje Python w folderze .venv ...
    py -3.12 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        py -3.12 -m venv ".venv"
    ) else (
        py -3.11 -c "import sys" >nul 2>&1
        if not errorlevel 1 (
            py -3.11 -m venv ".venv"
        ) else (
            python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,12)" >nul 2>&1
            if errorlevel 1 goto python_error
            python -m venv ".venv"
        )
    )
    if not exist ".venv\Scripts\python.exe" goto python_error
)

echo [2/3] Sprawdzam biblioteki...
".venv\Scripts\python.exe" -c "import streamlit,pandas,numpy,plotly,requests,openai" >nul 2>&1
if errorlevel 1 (
    echo Brakuje bibliotek panelu. Instaluje z requirements.txt...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto dependencies_error
)

echo [3/3] Otwieram terminal FOKU$ na http://localhost:8501
echo Jesli przegladarka nie otworzy sie sama, wpisz powyzszy adres.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8501
set "code=%errorlevel%"
echo.
echo Panel zostal zatrzymany, kod: %code%.
if not "%code%"=="0" echo Jesli port 8501 jest zajety, zamknij stara sesje lub sprawdz log powyzej.
pause
exit /b %code%

:missing_app
echo BLAD: nie ma app.py. Uruchom BAT z rozpakowanego PELNEGO ZIP, nie osobno.
pause
exit /b 2

:python_error
echo BLAD: brak Python 3.11/3.12. Zainstaluj Python i zaznacz Add Python to PATH.
pause
exit /b 2

:dependencies_error
echo BLAD: instalacja bibliotek nie powiodla sie. Sprawdz internet i log powyzej.
pause
exit /b 2
