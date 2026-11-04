# 🚀 FOKU$ THE BEST TRADER — v0.2

## Aktualizacja 2026-11-04: właściciel + MARKET DNA (v0.2)

**Prywatność:** jeżeli kliknięto `Discard` w ustawieniach Sharing, zmiany dostępu NIE zostały zapisane. Aplikacja mogła pozostać publiczna. Aby korzystać z tego projektu, trzeba teraz **najpierw ustawić hasło do panelu** w Streamlit → My apps → Settings → Secrets:

```toml
APP_ACCESS_PASSWORD = "WPROWADZ_TUTAJ_DLUGIE_UNIKALNE_HASLO"
```

Wybierz własne hasło (minimum 12 znaków); nie używaj tego przykładu. Po zapisaniu Secrets wykonaj Reboot app. Na ekranie logowania wpisz hasło, a program pokaże 5 zakładek. Nie trzeba ponownie wpisywać Capital.com ani OpenAI, jeżeli są już w Secrets. Hasło pozostaje wyłącznie w Secrets. W aplikacji można użyć przycisku **WYLOGUJ Z TERMINALU**.

Bramka hasłowa chroni aplikację przed przypadkowym dostępem, ale **nie zastępuje dostępu ograniczonego przez platformę, profesjonalnego SSO ani serwerowego limitowania prób**. Gdy plan lub ustawienia na to pozwolą, zalecana jest również prywatna aplikacja i ograniczenie dostępu.

**Nowości badawcze:** osobna zakładka 🧬 MARKET DNA i poziomy potwierdzonych swing high/low na wykresie; rozpoznawanie HH/HL, LH/LL, reżimu trend/range/kompresja/ekspansja; hipotetyczne sweep i BOS bez użycia przyszłych świec. Moduł NIE zmienia decyzji LONG/SHORT/WAIT i nie wylicza niezweryfikowanych prawdopodobieństw.

**AUTO-SKAN:** opcjonalne pobieranie co 60/120/300 sekund wyłącznie podczas aktywnej sesji Streamlit. Nie jest to skaner 24/7. GPT-5.4 HIGH pozostaje ręczne i może generować koszty.

**Weryfikacja:** unit testy i smoke-test Streamlit przechodzą na GitHub Actions po bieżącym commicie; nie ma jeszcze zweryfikowanego wyniku PAPER na dużym zbiorze ani gwarancji działania streamingu.

---

**CAŁKOWICIE NOWY PROJEKT.** Nowe repo `fokus-the-best-trader`, nowe `app.py`, nowy moduł analityczny, nowe archiwum. ZERO integracji, push/pull czy użycia git remote `sp500-kolega-gemini`. Stary kod nie jest tu skopiowany.

## Audyt techniczny — poprawki PAPER v2 / 4 listopada 2026

- **Bilans PAPER:** poziomy SL/TP są interpretowane jako **MID**, a wejście/wyjście jako odpowiednio ASK/BID dla LONG i BID/ASK dla SHORT; poślizg jest liczony na obu końcach. Jeśli oba progi są dotknięte w tej samej świecy OHLC, konserwatywnie pierwszeństwo ma SL. Nie jest to egzekucja brokerska ani tick-by-tick.
- **Dwa spready:** `snap.spread` to spread z ostatniej zamkniętej świecy (dla setupu), a `snap.quote_spread` z najnowszego, potencjalnie niezakończonego baru (jako filtr warunków wykonania). Jeżeli którykolwiek przekroczy limit, nie wydajemy sygnału.
- **Trwała identyfikacja kosztu:** nowe kandydatury LONG/SHORT zapisują `entry_spread` na każdej transakcji PAPER. Późniejszy audyt używa zapisanego spreadu sygnału, nie spreadu z kolejnego skanowania. Historycznie zmienny spread wewnątrz transakcji nie jest jeszcze symulowany.
- **Oddzielne WAIT:** zapis `scan_decisions` zamiast `signals`; stare wpisy WAIT w `signals` pozostają w bazie, lecz są filtrowane z listy transakcji.
- **Zachowane wyniki historyczne:** starym `paper_outcomes` przypisywane jest `legacy_v1`. Nie usuwamy danych, ale nie liczymy ich do statystyk v2. Nie można ich rzetelnie przeliczyć bez oryginalnych świec i spreadów.
- **LIVE odblokowywane świadomie:** domyślnie wyłącznie DEMO. Aby udostępnić opcję read-only LIVE w panelu, właściciel może wpisać `CAPITAL_ALLOW_LIVE = true` w Streamlit Secrets.
- **Zależności:** przypięto **bezpośrednie** zależności w `requirements.txt` do wersji obserwowanych w GitHub Actions na Python 3.11. Wersje pośrednie nie są w pełni zablokowane.
- **Bezpieczeństwo:** aplikacja wymaga `APP_ACCESS_PASSWORD`. Nie jest to system SSO ani zaawansowana ochrona przed atakami brute-force.
- **NIE POTWIERDZONO:** pełnego działania z prawdziwymi kluczami Capital.com / OpenAI, poprawności historycznych statystyk na realnym rynku, stałej pracy 24/7 i wydajności w Streamlit Cloud.


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
- Brak automatycznej egzekucji pozycji DEMO/REAL. Odczyt API DEMO/LIVE z wyborem środowiska, bez zleceń.

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