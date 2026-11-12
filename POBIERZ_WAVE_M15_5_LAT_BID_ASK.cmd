@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "OUT=%~dp0DANE_SP500_WAVE_M15"
if not exist "%OUT%" mkdir "%OUT%"
echo.
echo FOKUS WAVE — POBIERANIE 5 LAT SUROWYCH M15 BID + ASK
echo Instrument: Dukascopy usa500idxusd CFD
echo Zrodlo: 2021-11-11 ... 2026-11-11 (end exclusive)
echo.
where npx.cmd >nul 2>&1
if errorlevel 1 (
  echo Brak Node.js/npx. Zainstaluj Node.js LTS z nodejs.org
  pause
  exit /b 1
)
set /a BAD=0
for %%P in (bid ask) do (
  call :GET %%P 2021-11-11 2022-11-11
  call :GET %%P 2022-11-11 2023-11-11
  call :GET %%P 2023-11-11 2024-11-11
  call :GET %%P 2024-11-11 2025-11-11
  call :GET %%P 2025-11-11 2026-11-11
)
if %BAD% GTR 0 (
  echo BLAD POBIERANIA: %BAD% CZESCI. Nie uruchamiam badan na niepelnych danych.
  pause
  exit /b 1
)
echo.
echo Wszystkie 10 czesci M15 pobrano lub znaleziono lokalnie.
echo Folder: %OUT%
where py.exe >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0scripts\prepare_wave_m15.py" --folder "%OUT%" --out "%~dp0FOKUS_WAVE_M15_5_LAT_BID_ASK.csv"
  if errorlevel 1 echo Nie polaczono CSV: sprawdz komunikaty. Wymagane: Python 3 + pandas + numpy.
) else (
  echo Brak py.exe. Polacz pliki poleceniem:
  echo python scripts\prepare_wave_m15.py --folder DANE_SP500_WAVE_M15
)
echo.
echo Po polaczeniu wrzuc FOKUS_WAVE_M15_5_LAT_BID_ASK.csv
echo do RAPORTY / WAVE INTELLIGENCE 2.0 w terminalu Streamlit.
pause
exit /b 0

:GET
set "PRICE=%~1"
set "FROM=%~2"
set "TO=%~3"
set "FILE=usa500_m15_%PRICE%_%FROM%_%TO%"
if exist "%OUT%\%FILE%.csv" (
  echo POMIN: %FILE%.csv
  exit /b 0
)
echo POBIERAM: %FILE%.csv
call npx.cmd --yes dukascopy-node@1.51.1 -i usa500idxusd -from %FROM% -to %TO% -t m15 -p %PRICE% -f csv -v -dir "%OUT%" -fn "%FILE%" --cache --cache-path "%OUT%\.dukascopy-cache" --retries 3 --batch-size 5 --batch-pause 2000
if errorlevel 1 (
  echo BLAD: %FILE%
  set /a BAD+=1
  exit /b 1
)
if not exist "%OUT%\%FILE%.csv" (
  echo BRAK PLIKU: %FILE%
  set /a BAD+=1
  exit /b 1
)
exit /b 0
