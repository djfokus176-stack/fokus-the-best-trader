# FOKU$ PAPER — dzienny hamulec strat (tylko symulacja)

Wersja badawcza. **Nie wysyła zleceń do brokera** i nie poprawia
statystycznej przewagi strategii. Ogranicza liczbę *nowych* symulowanych
pozycji po stracie, ale nie gwarantuje maksymalnej straty w danym dniu.

## Konfiguracja workera Northflank / GitHub Actions

```
FOKUS_PAPER_DAILY_STOP_PTS=20
```

- **Domyślnie:** 20 punktów US500 na instrument i źródło PAPER.
  To **przykładowy, ostrożny limit testowy**, nie próg wyliczony
  jako optymalny na dotychczasowych 22 transakcjach.
- **0**: świadomie wyłącza hamulec; ustawienie niepoprawne/ujemne:
  brak nowych wejść PAPER, `PAPER_DAILY_STOP_CONFIG_INVALID`.
- Kalkulacja w strefie **Europe/Warsaw** z automatyczną zmianą czasu,
  według **czasu zamknięcia** transakcji.
- Liczą się tylko rozliczone `CLOSED_SL`, `CLOSED_TP`,
  `CLOSED_TIMEOUT`, z `pnl_pts` po modelowanych kosztach.
  `PENDING`, `OPEN`, `INVALIDATED` nie liczą się do P&L.
- Hamulec działa według maksymalnego, zrealizowanego obsunięcia dziennego
  od szczytu skumulowanego P&L, z początkiem na 0 pkt.
  Po przekroczeniu progu **pozostaje aktywny do następnego dnia**.
- Zatrzymuje **tylko nowe PENDING**, istniejące OPEN dalej dostają
  aktualizacje i rozliczenia. Kontynuowane są też odczyty, archiwizacja
  świec oraz podstawowe raportowanie.
- W logach: `GATES=PAPER_DAILY_DRAWDOWN_LIMIT` i
  `DIAGNOSTICS=PAPER_DAILY_STOP:...`.
  W terminalu pojawi się stan hamulca po pobraniu nowszego checkpointu.

**Uwaga:** jedna transakcja może stracić więcej niż ustawiony próg
(duży ruch, luka, niedostępne dane). Hamulec nie zamyka automatycznie
istniejących pozycji i nie przełącza bota na realny handel.

**Wdrożenie:** samo scalenie kodu w GitHub nie potwierdza aktualizacji
działającego procesu na Northflank. Sprawdź commit i nowe diagnostyczne
pola w logach workera po jego wdrożeniu; dopiero wtedy można uznać
hamulec za aktywny na serwerze.

Następne badania, osobno od produkcyjnego PAPER:
porównanie niezmienionych sygnałów przy TP 1R, 1,5R, 2R
i przy horyzontach 10, 20, 30 M1, przy identycznych wejściach
i realnych kosztach; chronologiczny holdout, niezależny forward SHADOW,
testy dni/godzin sesji nowojorskiej. Nie dopasowuj kombinacji
do kilku historycznych strat.
