# FOKU$ — AUDYT KODU I WAVE REVERSAL AI, 2026-11-11

## Co wiadomo z kodu (sprawdzone w `main` przed tą zmianą)

- Six AUTO: `DRUGA FALA`, `EMA TREND`, `LIQUIDITY SWEEP`,
  `BREAKOUT RETEST`, `EMA PULLBACK`, `VOLATILITY BREAKOUT`.
  Osobno są badawcze `EMA50 WAVE`, `RANGE REJECTION`,
  `NY OPEN TRAP`, `EMA PULLBACK + RETEST`.
- `market_dna.confirmed_pivots` już używa dwóch **późniejszych
  zamkniętych** świec. Nie było jednak badań fal 2–5,
  równych szczytów/dołków i warunkowego BOS M15.
- `research.replay` obsługuje chronologię M1, wariant kosztów
  historyczny/stały, unieważnianie luk, SL-first, brak nakładania
  pozycji; `exit_grid` porównuje zamrożone wejścia M1.
  To nie zastępuje wieloletniego testu BID/ASK M15.
- `remote_checkpoint.RemoteCheckpoint` zapisuje do Supabase
  `fokus_paper_checkpoint` (JSON CAS) i `fokus_closed_candles`.
  Typy archiwalnych świec to M1/M5/M15/H1; nie potwierdzono
  osobnej historii D1 w tym systemie ani pełnego BID/ASK M15.
- `shadow_learning.advance_shadow` unieważnia otwarte próby,
  gdy następny skan pomija chociaż 1 minutę. Wcześniejszy audyt
  wskazał 18 zamknięć i 41 unieważnień: wymagany diagnostyczny
  raport ciągłości skanów na działającym Northflank.
- `paper_daily_risk` wstrzymuje nowe symulowane wejścia przy
  dziennym obsunięciu, ale aktywacji odpowiedniego commita
  na serwerze NIE potwierdza samo scalenie GitHub.
- Konto Supabase dostępne z tego narzędzia pokazuje tylko
  **nieaktywny i niepotwierdzony jako FOKU$** projekt; dlatego
  nie odczytywano ani nie zmieniano tabel produkcyjnego workera.

## Dane pięcioletnie i niepewność

Dostarczony wcześniejszy raport pilota:
Dukascopy US500IDXUSD **BID M15**, 114 121 świec
(2021-11-11..2026-11-10), 8 wariantów, 10 559
symulowanych transakcji, SL=1.5 ATR, TP=2.25 ATR, max 8 M15.
Wszystkie warianty PF<1 przy **umownym koszcie 2 pkt**;
nie jest to test wykonania Capital.com ani pełnego BID/ASK.
Wyszukane w bibliotece zestawienie fal miało tylko wcześniejsze
zdarzenia; podana statystyka **72/240 = 30%** jest hipotezą
do odtworzenia z *źródłowych* M15 i definicji 3. szczytu.
NIE wolno porównywać wyników testu EMA9/21+EMA200 z
AUTO `EMA TREND` jako identycznej strategii.

## WAVE REVERSAL AI v1 — etap badawczy

1. Zamknięte M15 UTC; CSV ma zadeklarowaną konwencję
   `Time=CLOSE` albo `OPEN`. Tylko po jednoznacznym wyborze
   `OPEN` przesuwamy etykietę **+15 minut**.
2. Sesja NY: pierwsza zamknięta M15 09:45, ostatnia 16:00
   America/New_York, wliczając zmianę DST; dni tygodnia 1–5.
   **Nie posiadamy potwierdzonego kalendarza świąt NYSE**:
   danych świątecznych nie wolno nazywać zweryfikowaną sesją.
3. Szczyt/dołek potwierdzony lewymi i prawymi świecami
   (domyślnie 2/2), znany dopiero na zamknięciu drugiej po prawej.
   Zliczanie 2,3,4,5 fal z naprzemiennymi pivotami,
   struktury rising/falling/flat/mixed.
4. Formacje DOUBLE/TRIPLE TOP/BOTTOM: odchylenie ekstremów
   maksymalnie 0,25×ATR; próg wstępny, nie optymalizowany.
5. `RAW`: na świecy potwierdzającej pivot.
   `BOS`: osobne zdarzenie, dopiero po **późniejszym**
   zamknięciu przez lokalne wsparcie/opór, maksymalnie
   8 kolejnych pełnych M15.
6. Cechy warunkowe EMA9/21/50, RSI14, ATR14, reżim oraz
   VWAP i filtr `Volume` **tylko jeśli rzeczywisty Volume
   jest w CSV**. Brak Volume → `BRAK DANYCH`, zero VWAP
   nie jest uzupełniane. Tick volume CFD to nie kontrakty CME.
7. Prawdopodobieństwo przyszłego dotknięcia poziomu
   0,25/0,5/1% w ciągu 1/2/4h, LONG i SHORT osobno.
   Zdarzenia z luką lub niepełnym horyzontem nie są trafieniem
   ani pudłem. Kiedy tylko MID/BID jest dostępny, przyszłe
   progi są przybliżeniem dotknięcia ceny, **nie transakcją**.
8. Osobno: orientacyjny trade P&L, SL 1,5 ATR,
   TP 2,25 ATR, max 8 świec, następny OPEN,
   brak lookahead, konserwatywny SL-first.
   Pełne historyczne BID/ASK OHLC → użycie cen wykonania.
   Sam BID/Close/Spread → MODEL z kosztami.
   Brak spreadu → użytkownik podaje jawne założenie.
   Prowizja, swap i poślizg rzeczywisty nie są zweryfikowane.
9. Wyniki rok po roku, 70/30 chronologicznie, osobny ranking
   kierunków, fal 2–5 i filtrów z dolnym 95% (Wilson).
   Punkt odniesienia 50/50 losowy *kierunek na tych samych
   timestampach*; nie udaje losowych godzin.
10. Zdarzenia wielu wariantów mogą się nakładać: NIE SUMOWAĆ
    wyników i nie traktować jako jednego portfela.
    Wiele wariantów to wielokrotne testowanie — nawet
    dodatnie OOS 70/30 to **kandydat do nowego testu**,
    a nie "ZWERYFIKOWANA przewaga".

## Status implementacji względem 10 postulatów audytu

| Postulat | Stan |
|---|---|
| STRATEGY RANKING MASTER | Raporty istnieją; WAVE ma osobny ranking statystyczny, nie wspólny pewny lider |
| MTF M1/M5/M15/H1/D1 + 100 metod | M1/MTF i WAVE M15: częściowe. Brak pełnej D1/100 implementacji. Nie twórz pustych zwycięzców |
| BID/ASK, prowizje, slippage | M1 i nowy M15 mają model; pełne BID/ASK M15 zależą od CSV; brak rzeczywistych filli |
| Market regime | market_dna + WAVE tags; pełny porównywalny ranking reżimów wymaga dalszej pracy |
| Year-by-year | Dostępny dla WAVE M15 i archiwalnego pilota |
| Walk-forward / OOS | WAVE ma 70/30 (exploratory); pełna walidacja walk-forward i oddzielny forward P&L nadal wymagana |
| Statusy strategii | WAVE tylko badawcza; brak automatycznej promocji do LIVE |
| LONG vs SHORT | Oddzielone w WAVE i dzienniku PAPER |
| Trade audit | PAPER v3: ID, sygnał, koszty, close; osobny WAVE event_id i wersja; brak tick execution |
| LIVE vs BACKTEST drift | Do wdrożenia jako kolejny etap, nie deklarować ukończenia |

## Rekomendowane kolejne etapy (bez kasowania funkcji)

- **P1 (w tym PR):** WAVE M15 z testami, 70/30, precyzyjnym
  pochodzeniem danych, markowaniem braków, bez zmian AUTO.
- **P2:** Uzgodnić dokładną definicję trzeciego szczytu z
  wcześniejszym pilotem oraz sprowadzić źródłowy M15 BID+ASK;
  odtworzyć 72/240 i roczne przedziały ufności.
- **P3:** Dodać niezależny ranking reżimów i roll-forward
  na wielu **nieużytych** okresach; porównać z losowym czasem
  i losowym kierunkiem; uwzględnić korektę wielokrotnych testów.
- **P4:** Raport ciągłości SHADOW/worker i porównywalnego
  PnL PAPER vs identyczny model symulacji. Potwierdzić
  działający commit workera i brak realnych zleceń.
- **P5:** Dopiero potem rozpatrzyć promocję WAVE do
  osobnego PAPER, na podstawie statystycznie wiarygodnego
  wynikowego forward testu; nigdy tylko `wave_count=3`.

Nie zmieniaj startowego progu po obejrzeniu wycinka OOS.
