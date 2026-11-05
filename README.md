# 🚀 FOKU$ THE BEST TRADER — v0.3 MASTER RESEARCH

## Wygodne logowanie bez wpisywania hasła co chwilę

**Nowy tryb Google (zalecany):** natywne Streamlit `st.login()` z OIDC.
Po **jednorazowym** ustawieniu konta Google, Streamlit przechowuje własną
tożsamość w ciasteczku nawet do **30 dni** (nie jest to gwarancja, że
Google nigdy ponownie nie poprosi o uwierzytelnienie). W tym trybie
własne `APP_ACCESS_PASSWORD` nie jest wymagane podczas każdej wizyty.

**Co ustawić jednorazowo:**

1. W konsoli Google Cloud utwórz klienta OAuth typu **Web application**, a
   jako autoryzowany redirect URI dodaj dokładnie
   `https://fokus-the-best-trader.streamlit.app/oauth2callback`.
   Zapisz otrzymane identyfikatory klienta **wyłącznie w Streamlit Secrets**.
2. W Streamlit Cloud → My apps → Settings → Secrets dodaj lub popraw:
   ```toml
   APP_AUTH_MODE = "google"
   OWNER_EMAIL = "twoj_adres_google@example.com"
   AUTO_SCAN_DEFAULT = true

   [auth]
   redirect_uri = "https://fokus-the-best-trader.streamlit.app/oauth2callback"
   cookie_secret = "TWOJ_DLUGI_LOSOWY_SEKRET"
   client_id = "GOOGLE_CLIENT_ID"
   client_secret = "GOOGLE_CLIENT_SECRET"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```
   Zamień WSZYSTKIE przykładowe wartości. `OWNER_EMAIL` jest **wyłącznie jednym**
   zweryfikowanym adresem Google (żaden inny użytkownik Google nie wejdzie).
   `cookie_secret` musi być mocnym, losowym sekretem, innym niż hasło dostępu i klucze API.
3. Kliknij **Save / Reboot app**, a następnie **Wejdź przez Google**.
   Po zalogowaniu przy następnych wejściach aplikacja powinna rozpoznać
   właściciela automatycznie. **Wyloguj** usuwa ciasteczko.
4. Jeśli nie skonfigurowałeś Google, pozostaw `APP_AUTH_MODE = "password"`
   i istniejące `APP_ACCESS_PASSWORD`. Ten tryb zachowuje dostęp jedynie w
   aktualnej sesji, co może wymagać ponownego wpisania po zamknięciu przeglądarki.

**Ograniczenia:** utworzenie klienta Google OAuth i wpisanie jego danych
w Secrets to ręczny jednorazowy etap właściciela — ChatGPT nie posiada
jego identyfikatorów ani nie może ich bezpiecznie odgadnąć. Google OIDC
nie zostało przetestowane na prywatnym koncie właściciela. Tożsamość
przywracana jest w oparciu o Streamlit OIDC i może zostać wylogowana
wcześniej przez dostawcę lub przeglądarkę. Aplikacja nie przechowuje
kluczy API w ciasteczkach.

**Udogodnienia:** pola API są zwinięte; Secretów nie trzeba wpisywać
ponownie. `AUTO_SCAN_DEFAULT=true` włącza skanowanie po zalogowaniu
przy otwartej stronie, bez automatycznych płatnych zapytań do OpenAI.
To **nie** włącza działania 24/7 przy zamkniętej stronie.

---

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

## Audyt UX — cache strzałek i czat (5 listopada 2026)

- **Cache strzałek:** `trader/arrow_cache.py` używa Streamlit `st.cache_data`, z limitem 40 wpisów i TTL 30 min. Klucz obejmuje **całą zawartość** DataFrame zamkniętych świec oraz EPIC, źródło, TF, strategię i okno. Odświeżenie interfejsu bez zmiany danych może ponownie wykorzystać wynik; NOWA lub skorygowana świeca powoduje ponowne obliczenie. Nie gwarantujemy poprawy na wszystkich komputerach i rozmiarach historii.
- **Okno strzałek:** dokładnie **6 opcji**: 60, 90, 120, 180, 240, 350 zamkniętych świec. To nie jest płynny suwak. Tabela pod wykresem zawiera godziny, ceny MID i powody historycznych układów PAPER.
- **Znacznik BOT / CSV:** punkt na ostatniej potwierdzonej świecy `snap.frame.iloc[-1]`. `evaluate_snapshot` wycina najnowszą, mogącą się dopiero tworzyć świecę. CSV jest oznaczany jako **REPLAY**, nigdy LIVE. Jest test odczytu CSV i dokładnego timestampu znacznika.
- **GPT:** wybór `medium` (domyślny, limit 2400 output tokens, 45 s) lub `high` (4200 output tokens, 65 s). Pytanie maksymalnie 800 znaków. Rzeczywiste dane `usage.input_tokens/output_tokens` są dołączone do odpowiedzi, jeśli API je przekazuje. Nie pokazujemy wymyślonej kwoty kosztu — zależy od aktualnego cennika i warunków naliczania.
- **Historia czatu:** jest tylko w `st.session_state`. Przetrwa standardowy AUTO-SKAN/rerun aktywnej sesji, **NIE** jest trwała po przeładowaniu karty, ponownym logowaniu czy restarcie instancji. Nie zapisujemy automatycznie rozmów ani prywatnych danych do publicznego repo.
- **Testy CI:** używa akcji GitHuba kompatybilnych z Node 24. Poprawiono ostrzeżenie Pandas wynikające z typu kolumny w teście symulowanego przeskoku stop loss.
- **Czego nie sprawdzono:** płatnych odpowiedzi prawdziwego OpenAI, zachowania aplikacji w przeglądarce właściciela przez długi czas i realnej poprawy rentowności strategii.

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