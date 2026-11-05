# FOKU$ PAPER v3 — stan pozycji, SL/TP, alerty i raporty

**Data: 2026-11-05.** Repozytorium `djfokus176-stack/fokus-the-best-trader`, wyłącznie analiza **PAPER / READ-ONLY**. Stare repozytorium nie było zmieniane.

## Co naprawdę działa

- Terminal Capital.com DEMO tworzy rekord **PENDING** tylko dla pełnego setupu LONG/SHORT, po weryfikacji świeżości, statusu `TRADEABLE` i aktywnych filtrów MTF/makro. Nowy setup nie oznacza otwartej pozycji.
- Dopiero gdy API dostarczy *następną zamkniętą świecę*, silnik odczyta jej **OPEN** i **wstecznie zasymuluje** wejście `OPEN MID + spread/2 + slippage` dla LONG, `OPEN MID - spread/2 - slippage` dla SHORT. **Z tego powodu wejście PAPER jest rozpoznawane z opóźnieniem**; NIE jest to alert pozwalający faktycznie zawrzeć transakcję na tej samej cenie OPEN.
- Sprawdza SL/TP wyłącznie na kolejnych zamkniętych świecach MID. Gdy oba dotknięte w jednej świecy, przypisuje **SL**. Gap za poziom stop pogarsza wynik, a brak kolejnej świecy lub dziura historii powoduje `INVALIDATED` bez fikcyjnego P&L.
- Stany: `PENDING`, `OPEN`, `CLOSED_SL`, `CLOSED_TP`, `CLOSED_TIMEOUT`, `INVALIDATED`.
- Jedna aktywna pozycja PAPER na **źródło i instrument**, nawet przy różnych interwałach. Po zmianie TF silnik rozlicza pierwotny TF tylko wtedy, gdy jego świece są nadal pobierane (dlatego włącz MTF). Zły/intermittent feed blokuje aktualizację i może zakończyć się unieważnieniem.
- Wykres: wyłącznie **OPEN** ma linie `PAPER ENTRY`, `PAPER SL`, `PAPER TP` z oznaczeniem ID. `PENDING`, zamknięte pozycje i zwykłe historyczne strzałki **nie** mają linii aktywnej transakcji.
- Tabele SQLite `paper_positions_v3` i `paper_events_v3` zawierają odtwarzalny stan, czas, koszty i zdarzenia. Każdy event ma deterministyczne `event_id`; wykonanie skanu ponownie nie tworzy drugiej pozycji.
- Zakładka **RAPORTY → PAPER v3**: lista `PENDING/OPEN/CLOSED/INVALIDATED`, zdarzenia, dziennik WAIT, raport dzienny i tygodniowy w strefie Europe/Warsaw. Statystyki dotyczą tylko zamkniętych pozycji DEMO v3. **Nie mieszamy** ich z rozliczeniem v2 ani z offline CSV.

### Telegram: wyłącznie świadoma zgoda właściciela

W Streamlit Secrets, obok istniejących kluczy:

```toml
# Ustaw prawdziwe wartości wyłącznie w Streamlit, nie w GitHubie.
PAPER_TELEGRAM_ALERTS_ENABLED = true
TELEGRAM_BOT_TOKEN = "TWOJ_TOKEN_OD_BOTFATHER"
TELEGRAM_CHAT_ID = "TWOJ_NUMERYCZNY_CHAT_ID"
```

Obsługiwane: `LONG_SETUP`, `SHORT_SETUP`, `PAPER_OPEN`, `PAPER_CLOSE_SL`, `PAPER_CLOSE_TP`, `PAPER_TIMEOUT`, `PAPER_INVALIDATED`, `DATA_STALE`. Status `DATA_STALE` jest limitowany do jednego zdarzenia na 15 minut i dotyczy DEMO.

**Strategia dostarczania:** aby nie dublować wiadomości, rekord próby wysyłki jest **zapisany przed** wywołaniem Telegram API. Maksymalnie jedna **próba** na `event_id` (nie gwarantowane dostarczenie: przy awarii sieci/crashu alert może zaginąć). Zaległe alerty starsze niż 5 minut nie są masowo wysyłane. Domyślnie flagę `PAPER_TELEGRAM_ALERTS_ENABLED` pozostaw `false`. Do wysyłania Telegram bot musi mieć uprawnienia do rozmowy i prawidłowy Chat ID.

Kod testuje wysyłkę z **mockiem**, nie rzeczywistym tokenem. Nie testowano wysyłania na konto właściciela. Nigdy nie wysyłamy zleceń do Capital.com.

## Testy scenariuszowe
- PENDING bez następnej świecy; OPEN na następnej zamkniętej świecy; TP LONG/SHORT; SL w tej samej świecy co TP; TIMEOUT; gap i INVALIDATED; wznowienie po ponownym otwarciu SQLite; brak duplikatów wydarzeń.
- Jedna otwarta pozycja na instrument również przy zmianie TF.
- Brak poziomów SL/TP na wykresie dla samego sygnału bez OPEN.
- Wysyłka Telegram wyłączona bez zgody, at-most-one SEND ATTEMPT po restarcie.
- Dwa przebiegi aplikacji na symulowanym Capital.com DEMO: PENDING, potem OPEN.
- CI Python 3.11 i 3.12.

## Nie jest zrobione i czego NIE wolno twierdzić
1. **Brak rzeczywistych wejść w momencie OPEN.** Silnik czeka na zakończenie kolejnej świecy i dopiero wtedy wstecznie przypisuje papierowy fill. To nie jest usługa rzeczywistej egzekucji ani system zaleceń dla live tradingu.
2. **Brak trwałego hostingu 24/7 i zewnętrznej bazy.** SQLite jest stanem odtwarzalnym **na tym samym dysku**, ale Community Cloud może go wyczyścić przy restarcie/redeploy. Nie jest jeszcze gwarantowaną trwałą pamięcią w chmurze.
3. **Worker zewnętrzny nie jest jeszcze zintegrowany z nowym v3.** Stara ścieżka `trader/worker.py` nadal ma osobną logikę archiwum v2. Pełny cykl PAPER v3 działa obecnie poprzez **skany w otwartej aplikacji Streamlit**.
4. **Brak sprawdzenia na prawdziwym kluczu Capital.com / Telegram.** Testy odtwarzają zachowanie za pomocą danych kontrolowanych i mocków. Produkcyjna poprawność i terminowość alertów wymagają sprawdzenia u właściciela.
5. **Brak tick-level BID/ASK i rzeczywistego spreadu podczas każdego wyjścia**. Model stosuje spread z chwili sygnału i stały poślizg 0,25 pkt na stronę, który może odbiegać od wykonania u brokera.
6. **Brak dowodu rentowności**. Wyniki PAPER, nawet pozytywne, nie gwarantują dodatniej oczekiwanej wartości strategii na rynku rzeczywistym.

### Sprawdzenie w terminalu

Otwórz `https://fokus-the-best-trader.streamlit.app/`, zachowaj dotychczasowe hasło i klucze Capital.com DEMO. Włącz AUTO-SKAN oraz MTF. Przy setupie pojawi się `PENDING`, a po kolejnym **zamkniętym** barze stanie się `OPEN` lub `INVALIDATED`. W **RAPORTY** dostępna jest historia. Telegram pozostaw wyłączony, dopóki nie będziesz chciał otrzymywać wiadomości PAPER.
