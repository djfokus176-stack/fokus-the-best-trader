# 🌊 FOKU$ 3F v1 — FALA · FILTR · FINAŁ

**Status:** tylko RESEARCH / SHADOW M15, `trade_permission=WAIT`. Metoda jest **nr 9 w menu**, a `AUTO — 6 STRATEGII` pozostaje **nr 1** i **bez zmian**. Nie ma brokerowych orderów, automatycznych transakcji PAPER ani głosu w AUTO. Zielona strzałka PAPER nie powstaje wskutek 3F.

## Logika v1, krótkie wyjaśnienie

- Źródło: zamknięte świece OHLC M15, CLOSE-labeled UTC; regularna sesja NY 09:30–16:00 czasu lokalnego (pierwsze CLOSE 09:45), z DST. Kalendarz świąt i konkretne godziny CFD u brokera **nie są zweryfikowane** przez samą funkcję.
- **SHORT:** trzy odrębne, potwierdzone lokalne szczyty (2 zamknięte świece po obu stronach) w **jednej** sesji. Wysokości szczytów różnią się maksymalnie o `0,35 × ATR14`. Po prawym potwierdzeniu trzeciego pivotu trzeba uzyskać (maks. 8 świec później) zamknięcie **poniżej** najniższej ceny Low między szczytem nr 2 a 3 minus `0,1 × ATR14`. Poprzednie zamknięcie musi być przed wybiciem. Cena ma być poniżej EMA21, a EMA21 nierosnąca względem 4 świec wcześniej.
- **LONG:** analogicznie trzy potwierdzone dołki, wybicie ponad najwyższe High między dołkiem 2 a 3 plus `0,1 × ATR14`, cena ponad EMA21 i EMA21 niemalejąca.
- SL za ekstremum pivotów nr 2 i 3 o `0,15 × ATR14`; początkowy TP **1,8R**; można porównać **1,5R** i **2R** w badaniach. Koszt spread + 2 × poślizg jest modelowany; zbyt duży względem dystansu SL daje WAIT. Wariant trzech coraz wyższych szczytów NIE jest częścią tej wersji — celowo testujemy jedną definicję.
- Maksymalnie **jeden niezależny sygnał na sesję NY** i maksymalnie 8 świec M15 hipotetycznego utrzymania (120 min), koniec najpóźniej 16:00 NY. Jeśli brak następnej kompletnej świecy, wejścia nie ma. Jeśli brak dalszych świec, status pozostaje PENDING zamiast fikcyjnego zamknięcia.
- W replay wejście to **retrospektywnie odtworzone OPEN następnej zamkniętej świecy**, nie rzeczywista możliwość złożenia zlecenia w czasie wykonania. Przy równoczesnym SL i TP wygrywa **SL**; brakująca M15 unieważnia. Koszt w chwili sygnału i na wyjściu jest modelem, nie prawdziwym fill'em.

## Dane i działanie automatyczne

- `trader/fokus_3f.py`: czysty silnik as-of i replay, bez orderów.
- `trader/fokus_3f_forward.py`: pierwsza M15 **tylko inicjalizuje watermark**. Od kolejnych nowych zamkniętych M15 zbierane są sygnały SHADOW i ich modelowe późniejsze wyniki. Istniejące rozliczenia pozostają niezmienione. Limit 120 zdarzeń (ochrona rozmiaru checkpointu).
- `trader/worker.py`: osobny callback badawczy na M15 zapisuje `fokus_3f_forward` i `fokus_3f_forward_report` w istniejącym checkpointcie Supabase. Domyślnie włączony, **dopiero po wdrożeniu commita na Northflank i zweryfikowanym zegarze M15**. Jeśli nie chcesz zbierać 3F, można ustawić `FOKUS_3F_SHADOW_ENABLED=false` na serwerze. Nie wymaga nowej tabeli SQL, osobnego workera ani nowego klucza.
- `trader/fokus_3f_ui.py`: zakładka **RAPORTY**, panel nr 9. Pokazuje stan automatycznego archiwum i umożliwia **ręczny replay** do 3000 historycznych M15 z Supabase albo weryfikowanego CSV; rozbija wyniki na LONG/SHORT, rok i wcześniejsze 70% / późniejsze 30%, eksport do CSV.

**Ważne:** 70/30 nie jest niezależnym OOS po przeglądaniu konfiguracji. Bez wielotygodniowego nowego FORWARD, kalibracji rzeczywistego spreadu, testu walk-forward i dodatniego wyniku po kosztach `TRADE_PERMISSION=WAIT`. Testy jednostkowe nie potwierdzają rentowności. Starego archiwum WAVE A–E nie łączymy z 3F ani z AUTO.

## Odporność na błędy

Brak M15, zły format czasu, luka w świecach, niedziałający checkpoint i błędy SHADOW nie mogą odblokować transakcji. 3F jest izolowane od `evaluate_auto`, `select_approved`, `queue_paper`, SL/TP pozycji PAPER oraz realnych zleceń. Po zmianie oprogramowania worker NORTHFLANK może nadal pracować na starym commicie: dopiero odczyt `fokus_3f_status` i `fokus_3f_last_m15` z nowego checkpointu potwierdzi rzeczywisty start.
