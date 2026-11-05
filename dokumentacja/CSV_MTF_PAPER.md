# Reprodukowalny test CSV M1: 6 strategii bez MTF i z MTF

**Stan: moduł badawczy PAPER, bez zleceń brokerskich i bez rzeczywistych cen wykonania.**

## Format wejściowy

CSV musi zawierać kolumny:
```csv
Time,Open,High,Low,Close,Spread
2026-11-02T13:01:00Z,5000.0,5001.0,4999.0,5000.5,0.6
2026-11-02T13:02:00Z,5000.5,5002.0,5000.0,5001.8,0.6
```
To wyłącznie **przykładowy format**, nie rzeczywiste notowania.

**Definicja absolutnie obowiązkowa:** `Time` to moment **ZAMKNIĘCIA** świecy M1 w UTC, nie moment jej otwarcia. Dostawca podający moment *otwarcia* musi zostać uprzednio przekształcony przez dodanie jednej minuty (i zweryfikowanie sesji). Program nie zgaduje, jaką konwencję przyjął zewnętrzny plik. `Spread` opcjonalny, gdy go brak loader przyjmuje 0,6 pkt; w replay aktualnego modułu używany jest ustawiony w formularzu **stały spread na wejściu i wyjściu**, nie dynamiczna seria CSV.

Indeks powinien być UTC, rosnący, bez duplikatów, dokładnie na minutach. Wymagana spójność `High >= max(Open,Close,Low)` i `Low <= min(Open,Close,High)`. Luki w danych są dozwolone, ale **niekompletne** agregaty M5/M15/H1 są pomijane. Liczba oryginalnych świec: minimum 4600, maksymalnie 6500 w jednym uruchomieniu (limit wydajności; rozdziel większe archiwa na okresy, które można oceniać osobno).

## Logika bez look-ahead

1. Jednym plikiem wejściowym jest **M1**. M5/M15/H1 nie są osobno pobierane z Capital.com. Program agreguje wyłącznie kompletne grupy odpowiednio 5, 15 i 60 minut z prawostronną etykietą czasu **zamknięcia**.
2. Najpierw potrzebnych jest **70 pełnych H1** (co najmniej 70 godzin kompletnych M1); to okres rozgrzewki EMA/ATR, nie okres pomiaru wyników.
3. Z pozostałej części pliku wyznaczany jest stały **podział chronologiczny 70% wcześniejsze / 30% późniejsze**. Żadne parametry strategii nie są uczone ani optymalizowane na wcześniejszej części.
4. Każda świeca sygnałowa wykorzystuje co najwyżej zamknięte świece **do swojego timestampu**. W celu ograniczenia obliczeń M1 jest analizowane w oknie 350 poprzednich świec; to **aproksymacja** wskaźników EMA na bardzo długiej historii i obydwa warianty liczone są tak samo.
5. Wariant **BEZ MTF** sprawdza podstawowy setup wybranej strategii. Wariant **Z MTF** używa tego samego setupu, ale odrzuca LONG przy braku potwierdzenia UP i SHORT przy braku DOWN z historycznie ukończonych M5/M15/H1. Filtr nigdy nie tworzy transakcji.
6. Każdy wariant obsługuje maksymalnie **jedną pozycję PAPER na raz**, z horyzontem 20 przyszłych świec. Wejście to cena OPEN następnej świecy, SL/TP to poziomy MID, wyjście BID/ASK przy stałym spreadzie i poślizgu 0,25 pkt na stronę (zmienialnym w UI). Jeśli w jednej świecy dotknięto SL i TP, pierwszeństwo ma SL.
7. Każdy wariant ma **własny chronologiczny ciąg pozycji**. Wyniki nie są parowaniem transakcja-po-transakcji, dlatego mniejsza liczba strat po MTF sama w sobie nie dowodzi przewagi.
8. Pojawiają się liczba kandydatów, liczba veto przez MTF, n rozliczonych, WIN, win rate, suma punktów netto, expectancy i profit factor oraz eksport surowych transakcji. Nie pokazujemy ROI w złotych bez rzeczywistych nominałów/punktowej wartości instrumentu.

## Jak użyć

1. Uruchom `https://fokus-the-best-trader.streamlit.app/`, zaloguj się do swojego programu.
2. Otwórz **📈 RAPORTY → 🧪 CSV M1 — PORÓWNAJ...**.
3. Załaduj własny plik CSV zawierający 4600–6500 rzeczywistych, zamkniętych minut M1. Przed użyciem potwierdź konwencję timestampów.
4. Ustal **spread stały** i **poślizg**. Kliknij **TEST OFFLINE: BEZ MTF vs Z MTF — 6 STRATEGII**.
5. Sprawdź szczególnie **PÓŹNIEJSZE / 30%** i liczebność. Pusty raport, FAIL przy lukach lub mniej niż 30 rozliczeń NIE oznacza skuteczności.
6. Pobierz raport CSV i dziennik transakcji PAPER. W panelu zapisany jest także skrót SHA256 pliku, dzięki któremu można potwierdzić niezmieniony plik wejściowy.

## Ważne ograniczenia

- Agregowane HTF z CSV nie dowodzą zgodności z oddzielnymi świecami brokera (różne sesje, spready, częściowe świece i definicje czasu).
- To stały spread, stały poślizg, uproszczony OHLC. Brak booku, ticków, intrabarowej kolejności ruchu, prowizji, częściowych wypełnień i wyłączeń makro FOMC/BLS w tym trybie offline.
- Brak statystycznego dowodu przewagi, brak optymalizacji/walk-forward ze zmieniającymi się parametrami; holdout jest chronologiczną symulacją na stałych zasadach.
- Wynik 6 strategii zwiększa ryzyko błędu wielokrotnych porównań. Nie wybieraj „najlepszej” wyłącznie na tym samym pliku, na którym ją oceniono.
- Historia czatu, dane Streamlit i lokalny SQLite nie są trwałą zewnętrzną bazą danych.
- Bez rzeczywistego pliku użytkownika **nie można potwierdzić skuteczności** na rynku.
