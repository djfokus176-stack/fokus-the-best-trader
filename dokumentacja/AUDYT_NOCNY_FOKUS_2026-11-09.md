# FOKU$ THE BEST TRADER — audyt techniczny po zmianach #38–#42

**Zakres i moment:** stan repozytorium `djfokus176-stack/fokus-the-best-trader`, 9 listopada 2026 UTC, ostatni odczyt GitHub Actions. Testy po poprawce #43 są wykonywane osobno. **Brak dostępu do prywatnych wartości Secrets, przeglądarki użytkownika i bieżących rekordów Supabase; nie deklarujemy rzeczywistej pracy 24/7 ani zysku.**

## Wynik w skrócie

Kod i testy są w dużo lepszym stanie niż potwierdzony system operacyjny. Ostatni widoczny skan z **2026-11-09 20:50 UTC** miał `GATES=OK`, `SIX_VOTES` wszystkich sześciu `WAIT`, `QUEUE=NO`, `ACTIVE=NONE`, `CLOUD_CHECKPOINT_VERSION=133`. W tym samym uruchomieniu `paper_proof` dał `NOT_PROVEN`, `verified_cycles=0` (brak zamkniętych cykli z prawdziwego strumienia DEMO). [Logi skanu](https://github.com/djfokus176-stack/fokus-the-best-trader/actions/runs/42696714858).

Żaden test jednostkowy nie dowodzi, że harmonogram działa co minutę, że wskazania zarabiają, ani że serwer Streamlit wykonuje skan bez otwartej karty.

## Potwierdzone w kodzie / testach

| Obszar | Wynik | Podstawa i granica |
|---|---|---|
| Uruchomienie i autoryzacja panelu | Implementacja i smoke test OK | `tests/test_streamlit_start.py`; nie dowodzi skutecznego dostępu produkcyjnego do Capital.com |
| Kapital.com DEMO OHLC | Kontrola poprawności, świeżości, spreadu, luk, statusu rynku | `trader/market.py`; połączenie było udane w skanie 20:50, ale nie jest weryfikowane stale |
| LIVE 5 s | Osobny fragment pobiera niepełną świecę/quote i jawnie oznacza syntetyczny podgląd | `trader/live_chart_fragment.py`; tylko przy otwartej sesji |
| MTF M1/M5/M15/H1 | Cztery niezależne interwały, kompletność i synchronizacja czasowa | `trader/mtf.py`; lokalna przeglądarka może mieć czerwone MTF, gdy worker ma zielone |
| AUTO 6 strategii | `MIN_AGREEMENT=1`, przeciwne sygnały veto, po MTF tylko poprawny układ | `trader/auto_strategy.py`; tryb **eksperymentalny**, nieprzebadany statystycznie |
| Wczesne `OBSERWUJ LONG/SHORT` | Osobna heurystyka z zamkniętych świec; puste kółka, nie transakcje | `trader/early_watch.py`; bez MTF/RR/BLS i bez dowodu opłacalności |
| Porównanie v7.1 | `SHADOW`, nie siódmy głos AUTO | `trader/legacy_v71_shadow.py` |
| Historyczny audyt pominiętych wejść | Diagnoza reguł po każdej świecy, bez historii prawdziwych wykonań | `trader/signal_audit.py` |
| PAPER PENDING → OPEN → CLOSED | Działa w testach jednostkowych na symulowanych świecach | `trader/paper_lifecycle.py`; **brak potwierdzonego pełnego cyklu w faktycznym DEMO** |
| Supabase | CAS checkpoint i osobne OHLC | `trader/remote_checkpoint.py`; ostatni potwierdzony wersja 133 |
| GPT | Komentarz oparty na liczbach, opcjonalny płatny API | `trader/assistant.py`, `trader/auto_ai.py`; nigdy nie podejmuje decyzji o zleceniach |
| Telegram chmurowy | **Wyłączony** | Log `TELEGRAM_REMOTE=DISABLED`; panel nie wyśle wiadomości po zamknięciu strony |
| Prognozy / uczenie | Badawcze `SHADOW` rankingi i prognozy; bez strojenia głównej strategii | `trader/paper_learning.py`, `trader/forecast_audit.py` |

## Najważniejsze problemy i ryzyka (kolejność)

### P0 — brak potwierdzenia ciągłego wykonywania workera

Workflow `.github/workflows/paper-v4-scan.yml` ma nominalnie cron co 5 minut, ale jego ostatni potwierdzony zaplanowany skan z otrzymanych wyników jest z **20:50 UTC 09.11**. GitHub Actions może opóźniać lub pomijać zaplanowane uruchomienia. Zewnętrzny cron-job.org nie został w tym audycie odczytany; nie da się potwierdzić jego skuteczności bez historii odpowiedzi lub logów runów. Należy sprawdzić harmonogram, a dla rzeczywistego scalpingu M1 uruchomić **jeden** trwały worker z odstępem 60–65 s, deduplikacją checkpointu i kontrolą błędów. Dwa niezależne workery na tym samym stanie NIE powinny działać równocześnie.

### P0 — brak zweryfikowanego, pełnego cyklu PAPER i brak przewagi

`paper_proof` 09.11 20:50 UTC: `NOT_PROVEN`, `verified_cycles=0`. Nie wolno interpretować 385 zaliczonych testów jako 385 zyskownych transakcji. Potrzebne są rzeczywiste zapisane przykłady `SETUP → PENDING → OPEN → CLOSED_SL/TP/TIMEOUT`, bez luki danych, z rozliczeniem spreadu, poślizgu i kosztów oraz kontroli czasu decyzji.

**Ograniczenie strukturalne:** 5-minutowy worker odtwarza `OPEN` z początku następnej zamkniętej świecy M1 dopiero po późniejszym pobraniu jej OHLC; to hipotetyczny fill odtworzony z historii, nie zlecenie wykonane na Capital.com. Dla oceny 1-minutowego scalpingu ważna jest znacznie lepsza punktualność.

### P1 — zbyt rzadkie wejścia i niezweryfikowana skuteczność

Ostatni skan: `0/0` głosów, MTF gotowe (`M1 NEUTRAL, M5 UP, M15 UP, H1 UP`), ale żadna metoda nie przeszła swoich warunków przed MTF. Część metod odrzuca nawet prawidłową formację przez pobliski opór/wsparcie, RR lub spread. Nie znamy realnej liczby sygnałów na 1000 świec ani ROI netto. Uruchomić testy na spójnych, historycznych rzeczywistych cenach z osobnym odcinkiem out-of-sample i nie mylić liczby obserwacji z jakością.

### P1 — lokalne MTF i ponowne odpytywanie API

Przeglądarka utrzymuje własny cache czterech interwałów, niezależny od checkpointu workera. W nocy wprowadzono poprawkę #42: zegar próby obejmuje także nieudane pobrania MTF; ponowienie nie jest automatycznie bez ograniczeń. Czerwony lokalny MTF blokuje lokalną ocenę PAPER, nawet jeśli ostatni worker miał wcześniej `GATES=OK`. Trzeba sprawdzić dokładny tekst interwału i wynik przycisku **POBIERZ PONOWNIE BRAKUJĄCE MTF**.

### P1 — kalendarz makro

Zweryfikowane kopie BLS mają twardą ważność; aktualny plik `data/macro_calendar_manual.json` wygasa **2026-11-16 20:00 UTC**. To nie jest automatycznie aktualizowany kalendarz; po tej dacie bez zweryfikowanego źródła worker musi blokować nowy PAPER. **10 listopada 2026 CPI o 13:30 UTC = 14:30 czasu polskiego**. BLS należy traktować niezależnie od FED/BEA WATCH, który nie jest kompletną bramką makro. [BLS listopad](https://www.bls.gov/schedule/2026/11_sched_list.htm), [BLS grudzień](https://www.bls.gov/schedule/2026/12_sched_list.htm).

### P2 — wspólne limity API i złożoność

Kilka innych otwartych aplikacji może zużywać limity Capital.com, lecz **w ostatnim udanym skanie brak dowodu limitu HTTP 429**. Nie usuwać używanych aplikacji na ślepo; w razie błędów zapisywać ich kody i timestampy. 5-sekundowy wykres pobiera ceny inaczej niż 60-sekundowy pełny skan i niezależny worker. Ilość zapytań i koszt GPT należy monitorować osobno (limit liczby wywołań to nie limit pieniędzy).

## Plan próby następnego dnia — w tej kolejności

1. Otworzyć [Streamlit FOKU$](https://fokus-the-best-trader.streamlit.app/), odświeżyć i sprawdzić, czy najnowszy `main` został wdrożony. Nie instalować starych ZIP-ów.
2. Ustawić **M1 / AUTO — 6 STRATEGII**, włączyć **Wczesne LONG/SHORT — OBSERWUJ**, wykonać **SKANUJ ŚWIECE**. Zobaczyć realny wykres i kółka OBSERWUJ oddzielone od strzałek PAPER. Gdy brak okazji, dozwolony jest WAIT.
3. Otworzyć **DLACZEGO BOT NIE OTWIERA PAPER?**. Jeśli MTF czerwone, przeczytać dokładną przyczynę i użyć **POBIERZ PONOWNIE BRAKUJĄCE MTF**. Nie wyłączać filtra.
4. Wejść w **STRATEGIE → DLACZEGO BRAK LONG/SHORT? — AUDYT OSTATNICH ŚWIEC M1**; wybrać 10–20 świec i porównać `AUTO`, `LEGACY SHADOW`, powody `WAIT`, wykryte formacje i odrzucenia RR.
5. Sprawdzić [GitHub Actions](https://github.com/djfokus176-stack/fokus-the-best-trader/actions/workflows/paper-v4-scan.yml). Jeden uruchomiony skan powinien być świeży, a log powinien zawierać `GATES=OK` albo konkretny powód blokady, `CLOUD_CHECKPOINT_VERSION` i `MACRO_SOURCE`. Nie ufać samemu zielonemu znaczkowi uruchomienia.
6. Sprawdzić, czy po 10.11 00:00 UTC worker używa **`BLS_VERIFIED_MANUAL_NOT_LIVE`** z `EXPIRES_UTC=2026-11-16T20:00:00+00:00`, albo zweryfikowanego źródła LIVE; gdy nie, nowa pozycja ma pozostać zablokowana.
7. Porównać checkpointy i historyczne zdarzenia w Supabase. **Dopiero faktyczny zapis** pełnego `PENDING → OPEN → CLOSED_*` pozwoli twierdzić, że pełny cykl działa operacyjnie.
8. Po dowiedzeniu pracy M1 i zebraniu danych wykonać analizę częstotliwości, średniego P&L netto, maksymalnego obsunięcia, profit factor i OOS. Nie przełączać na rzeczywisty handel na podstawie pojedynczego korzystnego przebiegu.

## Absolutne ograniczenia

- **Żadnych rzeczywistych zleceń.** PAPER-only; uruchomienie brokera DEMO nie oznacza autotradingu.
- **Nie otwierać pozycji na świecach niezakończonych lub sztucznie uzupełnionych.**
- **Nie wyłączać MTF, zegara ani daty ważności BLS po to, aby wyświetlić zielone bramki.**
- **Nie utożsamiać liczby wskazań `OBSERWUJ`, głosów `1/2`, komentarzy GPT ani testów jednostkowych z prawdopodobieństwem sukcesu.**

## Gdzie sprawdzać źródła prawdy

- [Testy i wdrożenia](https://github.com/djfokus176-stack/fokus-the-best-trader/actions)
- [Skan PAPER na GitHubie](https://github.com/djfokus176-stack/fokus-the-best-trader/actions/workflows/paper-v4-scan.yml)
- [Kod workera](https://github.com/djfokus176-stack/fokus-the-best-trader/blob/main/trader/worker.py)
- [MTF](https://github.com/djfokus176-stack/fokus-the-best-trader/blob/main/trader/mtf.py)
- [PAPER z prawdziwych świec DEMO — dowód](https://github.com/djfokus176-stack/fokus-the-best-trader/blob/main/trader/paper_proof.py)
- [Wczesne wskazania](https://github.com/djfokus176-stack/fokus-the-best-trader/blob/main/trader/early_watch.py)
- [Kalendarz BLS](https://github.com/djfokus176-stack/fokus-the-best-trader/blob/main/data/macro_calendar_manual.json)

**Ocena:** kod testowany; infrastruktura scalpingu 24/7 i skuteczność ekonomiczna **nieudowodnione**. Najpierw stale działający worker i kompletny PAPER, potem kalibracja wejść, a nie odwrotnie.
