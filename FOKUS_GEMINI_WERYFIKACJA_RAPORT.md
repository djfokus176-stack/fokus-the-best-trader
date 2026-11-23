# FOKU$ THE BEST TRADER — weryfikacja diagnozy Gemini i poprawki

**Wersja bazowa:** commit `234a38ed1d13485c2cf0ec91e5d26f95b72ed6b4` (PR #123), pobrany do paczki użytkownika 23.11.2026.  
**Status:** wyłącznie lokalna propozycja do przeglądu. **Nie wdrożono** zmian na GitHub `main`, Northflank, Streamlit ani Supabase.  
**Środowisko:** testy syntetyczne, bez realnych danych Capital.com i bez sekretów dostępowych.

## Uwaga o oryginalnej odpowiedzi Gemini

Gemini nie wygenerował własnego ZIP/patcha i nie wykonał `pytest`: przedstawił jedynie diagnozę i plan. Poniższy ZIP i patch **zostały przygotowane po niezależnym sprawdzeniu kodu**, nie są artefaktami zwróconymi przez Gemini.

## Potwierdzone poprawki

1. `trader/market.py` — odrzucone przez kwarantannę świece Capital.com otrzymują spójną z resztą serii etykietę CLOSE-time; zachowany jest również oryginalny czas OPEN. Wcześniej porównywano błędnie OPEN odrzuconych rekordów z CLOSE poprawnych świec.
2. `trader/market.py` — przy szukaniu minimum 70 czystych świec H1 parser może przejść przez **ściśle rozpoznaną** przerwę weekendową piątek→niedziela/poniedziałek, ale nigdy przez kwarantannowaną świecę. Nie tworzy świec ani nie luzuje kontroli innych interwałów. Wada z poprzedniej implementacji: parser przenikał przez odrzuconą świecę przy dopuszczalnej przerwie 2-3 godzin i w efekcie blokował całą serię, mimo wystarczającej liczby późniejszych prawidłowych H1.
3. `trader/raw_m1_forward_paper.py` — gdy przegapione przez skaner minuty da się odzyskać z istniejących, prawdziwych świec, są liczone jako `scan_skips_recovered`, a nie `gaps`. Licznik `gaps` rośnie wyłącznie przy nieodzyskiwalnej przerwie. Historię sprzed zmiany pozostawiono bez manipulacji.
4. `trader/raw_m1_forward_paper.py` — oddzielnie liczone minuty bez aktywnej pozycji (`recovered_bars_idle`), bez pozornego zwiększania `recovered_bars` przypisanych do pozycji. Zwalidowane są **wszystkie** odzyskiwane świece (OHLC), zanim nastąpi modelowe otwarcie lub zamknięcie.
5. `trader/worker_signal_diagnostics.py` — watchdog na podstawie **aktualnego i dopasowanego czasowo** audytu sygnałów pokazuje `MTF_FAILED_TFS` i `MTF_ISSUE_M1/M5/M15/H1`. Przy braku aktualnego audytu pokazuje `UNKNOWN`. W logach są wyłącznie bezpieczne nazwy/kody, bez tekstu API, tokenów, cen i danych zleceń.

## Testy

Lokalnie: **104 testy przeszły** (w tym nowe testy weekendu H1, konwencji czasu, licznika luk RAW, poprawności MTF oraz bezpieczeństwa logów). Testy nie korzystały z prawdziwego API. `git apply --check` dla dołączonego patcha zakończyło się pomyślnie. **Pełnego testu całej aplikacji Streamlit nie przeprowadzono w tym środowisku** (brak zależności Streamlit); konieczny CI przed wdrożeniem.

## Czego ta wersja celowo NIE robi

- Nie wyłącza kontroli `INCOMPLETE_MTF` i nie udaje, że jej produkcyjna przyczyna została potwierdzona. H1 weekend, kwarantanna czasu i MTF są hipotezami opartymi na kodzie; konkretny interwał wymaga logu serwera z nową diagnostyką.
- Nie zmienia limitu 12 setupów RAW/dzień ani 20 pkt dziennego stopu **odrębnego eksperymentu RAW**. To też ogranicza liczbę pozycji, niezależnie od błędów.
- Nie włącza LIVE, nie tworzy sztucznych świec, nie dopisuje historycznych wyników P&L i nie zmienia zabezpieczeń nowych wejść AUTO.
- Nie modyfikuje przeszłych 7 nierozliczonych otwarć eksperymentalnych RAW.
- Nie twierdzi, że naprawiono biały ekran Streamlit, błędy sieci 429 ani że wszystkie cztery MTF są gotowe na serwerze. Do tych ustaleń potrzebne są konkretne logi i osobne testy.

## Jak bezpiecznie przetestować

1. Z aktualnego GitHuba utwórz osobną gałąź; **nie podmieniaj od razu `main`**.
2. Ponieważ pakiet bazuje na ww. commicie, nałóż `FOKUS_GEMINI_WERYFIKACJA_POPRAWKI.patch` (`git apply --check`, potem `git apply`). Jeśli `main` został zmieniony później, najpierw zweryfikuj konflikty.
3. Uruchom `pip install -r requirements.txt pytest` i `PYTHONPATH=. pytest -q` w Pythonie 3.11 i 3.12; sprawdź start Streamlit.
4. Przed scaleniem poproś o kontrolę `git diff`, potwierdź brak sekretów, uruchom CI i dopiero wtedy wdrażaj.
5. Po wdrożeniu sprawdź, czy `MTF_FAILED_TFS` wskazuje konkretny interwał i czy `MTF_ISSUE_*` odróżnia publikację świecy, wadliwe OHLC i brak danych.

## Co zawiera paczka

Pełny kod programu z poprawionymi plikami, katalog `tests/` oraz ten raport. **Bez kluczy API / `.env` / bazy SQLite**. ZIP jest do analizy/testów, nie do bezpośredniego nadpisania całego repozytorium.
