# 🚀 FOKU$ THE BEST TRADER — v0.1

**CAŁKOWICIE NOWY PROJEKT.** Nowe repo `fokus-the-best-trader`, nowe `app.py`, nowy moduł analityczny, nowe archiwum. ZERO integracji, push/pull czy użycia git remote `sp500-kolega-gemini`. Stary kod nie jest tu skopiowany.

## Co rzeczywiście jest w v0.1

- Streamlit + Plotly: świece M1/M5/M15/H1 i EMA9/21/50 z danych Capital.com DEMO REST (wymagają osobnych API), albo edukacyjny import CSV.
- Deterministyczne strategie badawcze `DRUGA FALA` i `EMA TREND`: LONG/SHORT/WAIT, geometria SL/TP, filtr spreadu, ATR, wsparcia/oporu.
- Zasada *ostatnia świeca nie jest pewna*: analiza na świecach, które mają już następną świecę; monitor wieku danych.
- Osobne archiwum zdarzeń i audyt późniejszych wyników PAPER w SQLite, deduplikacja ID. Historyczny, konserwatywny replay intrabar z kosztem spreadu i poślizgu.
- Opcjonalny asystent OpenAI objaśnia **te same numeryczne OHLC**, które widzisz na wykresie (to NIE jest AI analizujące screenshot).
- Samodzielny proces `worker` do uruchomienia na stale włączonym hoście (tylko PAPER). Żadnych metod do handlu brokerowego.

## Czego jeszcze nie ma (nie udawać)

- Brak gwarantowanego live streaming/WebSocket i 24/7 hostingu. Streamlit Cloud nie służy jako worker stale działający.
- Brak wdrożonego WebSocket, kalendarza makro, źródeł news, Telegram alertów, walidowanego OOS/walk-forward czy automatycznej nauki AI.
- Brak podpiętej zewnętrznej trwałej bazy. Streamlit Cloud może resetować lokalny katalog SQLite.
- Żaden backtest na rzeczywistych danych użytkownika nie został ukończony. Nie ma znanej skuteczności ani podstaw do przejścia na REAL.
- Brak automatycznej egzekucji pozycji DEMO/REAL. Tylko odczyt API DEMO.

## Uruchomienie w Windows (PowerShell)

```powershell
cd fokus-the-best-trader
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
# Edytuj TYLKO lokalne secrets.toml. Plik jest w .gitignore
streamlit run app.py
```

Wymaga Python 3.11+ (preferowane 3.11–3.12). Bez API można użyć CSV z datą w UTC i kolumnami `Time,Open,High,Low,Close`.

Dla dodatkowego skanera PAPER w stale uruchomionej konsoli:

```powershell
$env:CAPITAL_API_KEY='...'
$env:CAPITAL_IDENTIFIER='...'
$env:CAPITAL_PASSWORD='...'
python -m trader.worker --once
# lub bez --once (dopóki proces działa)
python -m trader.worker --interval 65
```

**Uwaga:** skaner `worker` nie wysyła zleceń ani Telegramów; zapisuje kandydatów PAPER i WAIT. Lokalna baza działa na jednym hoście; dla wdrożenia cloud wymagany będzie Postgres/Supabase i prywatne sekrety.

## Streamlit Community Cloud — całkiem nowa aplikacja

1. Utwórz **nowe repo** na GitHubie o nazwie `fokus-the-best-trader` (najpierw puste, bez kopiowania starego repo).
2. Wgraj rozpakowane pliki ZIP do głównego katalogu tego nowego repo (bez lokalnego `secrets.toml`).
3. Wejdź na [share.streamlit.io](https://share.streamlit.io) -> **Create app** -> wybierz NOWE repo, plik `app.py`, branch `main`.
4. Secrets w panelu Streamlit: podaj swoje klucze Capital DEMO, ewentualnie OpenAI. Nie wklejaj kluczy do GitHuba ani do rozmowy.
5. Uruchom. Testuj wyświetlanie świec, ścieżkę WAIT i własny CSV. Brak kluczy = brak ceny, bez wymyślania notowań.

## Priorytety v0.2

1. Utrwalanie OHLC i PAPER w Postgres + watchdog niezależny od Streamlit.
2. Test na demo Capital.com weryfikujący znaczenie `snapshotTimeUTC` i zbieżność M1 / M5 / M15.
3. Wiarygodne news, kalendarz makro, blackout i Telegram, następnie OOS/walk-forward.
4. Rozszerzenie forward PAPER o partial TP/trailing, poślizg zależny od sesji i koszty. Nie zmieniać algorytmu po kilku stratach.

## Bezpieczeństwo

`.streamlit/secrets.toml`, `data/`, `.env` i tokeny są ignorowane przez Git. Nie ma żadnego `git remote`, workflow, zleceń brokerowych ani operacji na starym repo. Publiczny GitHub nie jest sejfem na API.

**Wygoda na Windows:** po pierwszej instalacji uruchom `start_windows.bat` (jeśli system Python/venv jest skonfigurowany). To uruchamia aplikację, a nie całodobowy skaner.