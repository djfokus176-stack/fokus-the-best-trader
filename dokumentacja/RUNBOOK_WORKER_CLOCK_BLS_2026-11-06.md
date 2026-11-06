# FOKU$ PAPER — procedura bezpiecznego odblokowania, 6.11.2026

**Dotyczy tylko nowego** `djfokus176-stack/fokus-the-best-trader`. Starego
`SP500 Master Edition v7.1` nie modyfikować. Nie ujawniaj identyfikatora
Capital, haseł, tokenów CST ani kluczy OpenAI/Supabase.

## 1. Potwierdzone z GitHub Actions

Ostatni sprawdzony automatyczny run: `2026-11-06T11:30Z` (12:30 PL),
`WAIT`, `CANDLES=1396`, `GATES=SETUPS_DISABLED,MACRO_CALENDAR_UNAVAILABLE`,
`DIAGNOSTICS=BLS_CALENDAR:HTTPError:HTTP403`, konsensus 0/2,
`CLOUD_CHECKPOINT_VERSION=4`. Samo oznaczenie runu `success`
oznacza wykonanie skryptu, a **NIE** gotowość do otwierania PAPER.
Wersja nowych plików nie oznacza, że BLS 403 już zniknął.

## 2. Jeden klik: sprawdzenie surowego zegara w API

1. GitHub → to repozytorium → **Actions**.
2. W menu po lewej wybierz **FOKU$ CLOCK CHECK — Capital DEMO (read-only)**.
3. Kliknij **Run workflow** → `US500` → zielony **Run workflow**.
4. Po wykonaniu otwórz job **2 próbki etykiet czasu UTC** i skopiuj
   wyłącznie widoczne etykiety `snapshotTimeUTC` oraz UTC obu prób.
5. W terminalu **Capital.com DEMO** zobacz US500 na M1. Porównaj
   dokładnie *dwie kolejne zakończone* świece: ich początek i koniec,
   oraz to, czy API odpowiada początkowi czy końcowi świecy.
6. **Dopiero gdy jest to bezsprzecznie OPEN** ustaw
   Settings → Secrets and variables → Actions → Variables →
   `FOKUS_CANDLE_TIME_CONFIRMED` = `open`.
   W razie niezgodności nie ustawiaj nic i wróć do diagnostyki.

W odróżnieniu od starszej `raw_candle_time_diagnostic` nowe
`raw_candle_clock_labels` pobiera *wyłącznie* surowe etykiety, więc
`bid > ask` nie utrudnia weryfikacji czasu. Jest to odczyt API,
bez transakcji, bez zapisu sekretów i bez samoczynnego odblokowania bramki.

## 3. BLS HTTP 403 — czego NIE robić

Oficjalny kalendarz: https://www.bls.gov/schedule/news_release/bls.ics
Pobieramy go tylko z oficjalnego BLS z jawnym User-Agent identyfikującym
projekt. **403 pozostaje błędem i blokuje nowe PAPER**. Nie używać
proxy/udawania przeglądarki, nie wyłączać `strict_macro`, nie
interpretować braku kalendarza jako „brak danych makro”.

Weryfikuj oficjalny harmonogram: https://www.bls.gov/schedule/2026/11_sched_list.htm.
W chwili audytu źródło podawało: 6 listopada raport o zatrudnieniu,
10 listopada CPI, 13 listopada PPI (8:30 ET). To ręczna informacja,
a nie automatycznie zweryfikowany feed workera.

Jeśli BLS stale odrzuca środowisko GitHub, potrzebne jest inne
**autoryzowane, aktualne i datowane źródło kalendarza**, a nie ręczne
wyłączenie bramki. Obecny kod nie gwarantuje takiego źródła.

## 4. Harmonogram 5 min

Cron GitHub Actions `3-58/5 * * * *` jest **best effort**. Sprawdź log
`event=schedule` i stale rosnący `CLOUD_CHECKPOINT_VERSION`.
Zielony `tests + Streamlit boot` nie świadczy o pracy workera.
Żeby gwarantować prawie regularny cykl, konieczny jest monitorowany
zewnętrzny scheduler (np. uruchomiona maszyna / host z cron + odpytywanie
GH API), z sekretem `actions: write` tylko dla wybranego repozytorium.
Nie wklejaj tokenu do czatu ani repozytorium. Zewnętrzny wyzwalacz
może zwiększyć koszty i nie usuwa ograniczeń źródeł danych.

## 5. Kryteria odbioru

- Źródło Capital DEMO TRADEABLE i świeże dane M1/M5/M15/H1;
- 0 wadliwych świec `bid>ask`, NaN, Infinity oraz potwierdzone OPEN UTC;
- oficjalny aktualny kalendarz makro bez błędu 403 i bez blackout;
- `GATES=OK` w prawdziwym automatycznym jobie, bez bypassów;
- prawdziwy nowy `PENDING` → `OPEN` → `CLOSED_SL/TP/TIMEOUT`
  w checkpoint Supabase; model PAPER ma zawsze ryzyko nierealistycznej
  ceny wejścia i wyniki nie gwarantują zysku;
- dłuższy test out-of-sample z kosztami, zanim będzie mowa
  o skuteczności systemu.

**Wniosek:** ukończone testy jednostkowe ≠ gotowy autonomiczny bot
tradingowy. Nie odblokowywać REAL TRADE.
