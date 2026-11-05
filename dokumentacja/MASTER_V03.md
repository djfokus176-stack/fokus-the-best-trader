# FOKU$ THE BEST TRADER — MASTER RESEARCH v0.3
## Faktyczna architektura i granice działania

**Repozytorium:** `djfokus176-stack/fokus-the-best-trader`. Żaden plik projektu `sp500-kolega-gemini` nie był modyfikowany ani importowany.

### 1. Terminal — dziewięć zakładek
- **📊 TERMINAL:** świeczki Capital.com US500 w cenie MID, EMA9/21/50, poziomy ostatnich potwierdzonych swingów, historyczne strzałki LONG/SHORT, wejście/SL/TP dla bieżącego rozpoznanego setupu, status danych, status rynku, skaner.
- **🧬 MARKET DNA:** HH/HL, LH/LL, potwierdzone pivots, sweep/BOS oraz reżim zmienności. To kontekst badawczy, nie samodzielna strategia.
- **🧭 M1–H1:** cztery **oddzielne** zbiory świec z Capital.com: M1, M5, M15, H1. Brak świeżych odczytów któregokolwiek TF = WAIT. Zgodność wyższych TF może veto sygnał, ale nigdy go nie tworzy.
- **🎯 STRATEGIE:** DRUGA FALA, EMA TREND, LIQUIDITY SWEEP, BREAKOUT RETEST, EMA PULLBACK, VOLATILITY BREAKOUT. Każda posiada deterministyczną definicję, ale NIE ma udowodnionej przewagi.
- **🧪 LABORATORIUM:** dotychczasowe historyczne testy dwóch strategii + forward PAPER.
- **📰 NEWS / MAKRO:** osobne odczyty oficjalnych RSS FED/BLS/BEA oraz kalendarza BLS. Kalendarz NIE uwzględnia wszystkich publikacji FOMC/BEA. Zweryfikowany okres blackout BLS może wstrzymać sygnał. Brak kalendarza nie jest dowodem braku publikacji.
- **📈 RAPORTY:** replay po kosztach 6 strategii, chronologiczny podział 70/30, kroczące testy, CSV, statystyki forward PAPER.
- **📚 ARCHIWUM:** LONG/SHORT i WAIT jako osobne rejestry.
- **⚙️ STATUS / API:** stan integracji; konfiguracja właściwych Secrets.

### 2. Logowanie i klucze
Zachowano dotychczasowe `APP_ACCESS_PASSWORD` oraz opcjonalny OIDC przez Google (`APP_AUTH_MODE="google"` po **jednorazowym** utworzeniu własnego klienta OAuth). Google może pamiętać sesję ~30 dni — nie jest to aktywne bez konfiguracji Google.

Klucze Capital.com i OpenAI pozostają w **Streamlit Secrets**. Zapisany klucz nie wymaga ponownego wklejania przy otwieraniu panelu.

Opcjonalny limit ręcznych zapytań GPT (na jedną sesję, NIE konto OpenAI):
```toml
OPENAI_MAX_CALLS_PER_SESSION = "12"
```
GPT-5.4 HIGH nie uruchamia się automatycznie po każdej świecy. Zapytanie wymaga użycia przycisku AI.

### 3. Pobieranie danych i bezpieczeństwo
- DEMO domyślne, LIVE odczyt tylko gdy `CAPITAL_ALLOW_LIVE=true`.
- API korzysta z GET cen i rynku oraz POST **wyłącznie do logowania**, bez endpointów składania zleceń.
- **Warunki nowego sygnału PAPER:** świeżość OHLC, status brokerowy `TRADEABLE`, poprawny spread, brak zatwierdzonego blackout BLS, pełny setup oraz (domyślnie) MTF.
- Dane źródłowe Capital.com są osobno przypisane do DEMO/LIVE, EPIC i interwału. CSV jest wyłącznie edukacyjnym zbiorem.
- MTF pobierany przy pierwszym skanie i ponownie według kadencji: M1 ~60s, M5 ~300s, M15 ~900s, H1 ~3600s, podczas gdy strona jest otwarta.
- AUTO-SKAN Streamlit co 60/120/300 sekund, **tylko w aktywnej sesji przeglądarki**.
- Status brak feedu / brak świeżości / CLOSED / brak kompletnych danych oznacza **WAIT**.
- Strzałki historyczne to wykryte układy OHLC, bez historycznej walidacji MTF, statusu brokera ani makro. Nie przedstawiają rzeczywistych transakcji.
- Model PAPER v2: cena MID poziomów SL/TP, wejście/wyjście BID/ASK i stały zadany spread + slippage; w jednej świecy SL ma pierwszeństwo.

### 4. Nauka / raporty
- Rejestr `candle_history` w lokalnej bazie SQLite zbiera tylko **zamknięte** świece, deduplikuje je i oddziela instrumenty, TF i źródła. Laboratorium wykorzystuje zgromadzoną historię, jeśli jest dłuższa niż pojedynczy skan.
- Wyniki PAPER starego modelu `legacy_v1` pozostają zachowane, lecz nie są wliczane do nowych statystyk `v2_mid_bidask`.
- Jest backtest, walidacja holdout 70/30 i rolling OOS **ze stałymi regułami**. **Nie ma adaptacyjnego modelu machine learning**, automatycznej optymalizacji parametrów ani udowodnionego dodatniego EV.
- Sugerowana minimalna próba: wiele miesięcy rzeczywistych danych z prawdziwą strukturą spreadu i późniejsze oddzielne testy forward. Wbudowane ~350 świec z jednego pobrania to za mało do oceny rentowności.

### 5. Co NIE JEST gotowe
1. **Skaner 24/7 poza Streamlit** — worker jest napisany, ale nie ma niezależnego hostingu, harmonogramu i trwałej bazy.
2. **Trwałe archiwum w zewnętrznej bazie** — SQLite w Community Cloud może zostać utracone przy wdrożeniu/restarcie.
3. **Udowodniona strategia** — brak istotnej statystycznie, zweryfikowanej przewagi na niezależnej próbie.
4. **Tick-level bid/ask i prawdziwe wypełnienia** — replay z OHLC jest uproszczonym modelem.
5. **Automatyczne rozumowanie GPT na każdej świecy** — świadomie wyłączone z uwagi na koszt i jakość.
6. **Pełny kalendarz wydarzeń makro** — obecnie harmonogram BLS + informacje RSS, bez niezawodnego blackout FOMC.
7. **Logowanie Google bez konfiguracji Google Cloud** — nie można utworzyć cudzych prywatnych poświadczeń OAuth automatycznie.
8. **Sprawdzenie prawdziwego działania na Twoim koncie Streamlit i rzeczywistych API** — wymagany test w przeglądarce właściciela.

### 6. Jak sprawdzić po aktualizacji
1. Otwórz `https://fokus-the-best-trader.streamlit.app/` i zaloguj się dotychczasowym hasłem lub skonfigurowanym Google.
2. Sprawdź, czy AUTO-SKAN jest włączony i czy istnieje potwierdzenie statusu instrumentu `TRADEABLE`.
3. Przejdź do M1–H1: oczekiwane 4 wiersze bez błędu źródła.
4. W Strategiach porównaj 6 wyników.
5. W News/Makro kliknij skan źródeł; program pokaże błędy źródeł, jeśli jakieś będą niedostępne.
6. W Raportach kliknij test 6 strategii, potem CSV. Nie obiecuj sobie wyników na krótkim fragmencie.
7. W diagnostyce AUTO-SKAN sprawdź, czy przy kolejnych świecach pojawia się `NEW_BAR`. Brak nowych barów podczas CLOSED nie musi oznaczać awarii skanera.
