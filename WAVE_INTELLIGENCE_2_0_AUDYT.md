# FOKU$ — WAVE INTELLIGENCE 2.0 (research, not AUTO)

## Weryfikacja stanu istniejącego programu

- Już istnieją: sześć strategii AUTO, PAPER v3 (jedna aktywna pozycja na instrument), wynik po spreadzie i poślizgu, osobny dziennik, archiwum świec workera M1/M5/M15/H1 w Supabase, MTF, wstępne research porównania 70/30, wyliczanie swingów M15 w PR #62, filtr RAW/BOS, EMA/RSI/ATR i opcjonalne Volume/VWAP.
- Brak potwierdzenia bieżącej wersji Northflank i działania planowanych blokad. GitHub CI dla PR #62 nadal może czekać w kolejce.
- Znany plik `SP500_M15_FALOWANIE_ZDARZENIA.csv` zawiera 1000 zagregowanych zdarzeń do lutego 2024, a nie pełne 114121 OHLC M15. W 133 zdarzeniach `3. szczyt` spadek 0,5% w 2h wystąpił 50 razy (37,6%); rozszerzony wynik 72/240 = 30% pochodzi z innej/nieweryfikowanej próby. Brak porównywalnych definicji i odrębnego OOS.
- Backtest M15 ośmiu wariantów na 114121 świecach był dostępny jako zagregowany raport, bez źródłowych BID+ASK M15 w bieżącej sesji. Żaden wariant z podanego raportu nie miał PF>1 po modelowanych kosztach.
- Supabase w połączonym koncie pokazuje inny, nieaktywny projekt, nieidentyfikowalny jako baza FOKU$; nie wykonano żadnej mutacji ani audytu rzeczywistych tabel produkcyjnych.

## Co dodaje WAVE 2.0 (PR badawczy, nad poprzednim PR #62)

Causal A/B/C/D/E dla obu odwróconych sytuacji (trzeci szczyt i trzeci dołek):

| Wariant | Warunek sygnału | Kierunek względem trzeciego szczytu |
| --- | --- | --- |
| A_RAW | Trzeci swing potwierdzony przez zamknięte dwie późniejsze M15 | SHORT |
| B_BOS | Późniejsze zamknięcie poniżej wcześniejszego potwierdzonego lokalnego dołka | SHORT |
| C_BOS_RETEST | Dopiero po BOS: retest poziomu i zamknięcie z powrotem poniżej | SHORT |
| D_BREAKOUT_HOLD | Dwa zamknięcia ponad maksimum znanym w chwili trzeciego szczytu | LONG |
| E_WAIT | Brak wejścia; referencyjnie 0 transakcji, nie 100% skuteczności | WAIT |

Dla trzeciego dołka LONG/SHORT zostają odwrócone, a poziomy wsparcia/oporu odwrócone. A/B/C/D nie mają tej samej liczby **wyzwolonych** sygnałów. Każdy wariant ma jednak tę samą bazę kwalifikujących się *anchorów*; rankingi muszą pokazywać funnel `eligible_anchors` -> `triggered` -> `closed` -> `win` i nie porównywać wyłącznie P&L na hand-picked, różniących się wejściach.

- Nazywaj `RAW` momentem potwierdzenia pivotu, nie samą świecą pivotu.
- Oddziel świece 15-minutowe z etykietą `OPEN` od `CLOSE`. Dane Dukascopy zwykle oznaczają OPEN; import musi jawnie przesunąć czas o 15 minut, co obsługuje istniejący loader z PR #62.
- BADANY instrument: CFD Dukascopy USA500/Capital US500, nie ES futures.
- Bez źródłowej M1/M5 **nie ma** wiarygodnego wyjścia dokładnie po 10 lub 20 minutach; zamiast interpolacji wynik jest `BRAK DANYCH M15`.
- SL/TP liczone po następnej otwartej świecy, ze spreadem z ostatniej znanej zamkniętej świecy albo z kompletnym Bid/Ask OHLC; słabsza metoda jest jawnie oznaczona założeniem. Możliwa luka = unieważnienie, a w dwuznacznej świecy pierwszeństwo ma SL. Brak ticków uniemożliwia wiarygodne odtworzenie rzeczywistej kolejności i poślizgu wykonania.
- Nie pobieramy automatycznie danych z Capital.com LIVE, nie tworzymy zleceń; `WAIT` pozostaje stałym zalecanym statusem aż do przyszłej walidacji.
- Osobno zapisywane: przypadki UP/DOWN/BOTH/FLAT (nie traktuj braku spadku jako wzrostu), OOS 70/30, koszt pośredni, MFE/MAE, czas SL/TP, roczne net PnL i próba niezależnych sesji; ranking wg net i PF, nie WinRate.

## Brakujące etapy; bez fałszywych deklaracji

1. Załaduj oryginalne 114121 M15 (czas OPEN/CLOSE jawny), najlepiej pełne BID i ASK. Zweryfikuj przerwy, okresy dzienne, godziny NY i święta, źródło Volume.
2. Uruchom panel RAPORTY / WAVE INTELLIGENCE 2.0 i wyeksportuj raport A–E oraz surowy dziennik. Wynikami nie wolno zmieniać AUTO.
3. Kalibracja probabilistyczna może nastąpić dopiero na NOWYCH okresach forward; nie ma teraz weryfikacji, która pozwala wyświetlać prognozę prawdopodobieństwa LONG/SHORT LIVE.
4. Dodatkowe interwały M1/M5/H1 wymagają osobno przetestowanych źródeł i identycznej definicji setupu; `BRAK DANYCH` nie jest wynikiem zerowym.
5. Trwałe przechowywanie zrzutów po każdej świecy i rozliczeniu wymaga wskazania właściwego projektu Supabase, bezpiecznej migracji i weryfikacji wdrożenia Northflank. Nie utworzono niebezpiecznie nowych tabel ani niezidentyfikowanej bazy.
6. Ranking kilkudziesięciu cech, czterech RR i sześciu horyzontów niesie poważne ryzyko multiple testing. Wynik z późniejszych 30% po obejrzeniu PRZESTAJE być nietknięty. Każdą wybraną hipotezę należy zamrozić i badać na kolejnej nieoglądanej próbce.

**Status:** `BADANIA`. Brak statystycznie zweryfikowanej dodatniej wartości oczekiwanej netto; brak nowych strategii AUTO lub brokerowych transakcji.
