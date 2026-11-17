# FOKU$ THE BEST TRADER — automatyczne audyty archiwum

Audyty działają automatycznie w **Northflank worker** w ramach kolejnych
skanów (bez dodatkowego harmonogramu). Nie wymagają otwartej przeglądarki.
Wyniki są zapisywane w istniejącym checkpoint Supabase, bez nowej tabeli
SQL, bez zleceń DEMO/LIVE i bez ingerowania w strategię AUTO.

## Gdzie w programie

W **TERMINALU** pod wykresem świec:
- **AUDYT ARCHIWUM — DZIEŃ / TYDZIEŃ / MIESIĄC**
- wybierz datę, aby zobaczyć rozliczenia tego dnia;
- tabela pokazuje wszystkie trzy okresy osobno dla trzech rejestrów;
- wybierz tryb do analizy konkretnych strategii;
- rozwiń archiwum dnia i pobierz **CSV z datą zamknięcia, kierunkiem,
  metodą i wynikiem netto w punktach**;
- rozwiń historię 14 dni, 8 tygodni i 6 miesięcy.

## Trzy niezależne rejestry

1. **PAPER v3** — archiwalne pozycje w głównym SQLite/Supabase;
2. **MOMENTUM TEST** — wcześniejsza, niezależna symulacja;
3. **RAW M1 TEST** — osobny forward-only test sygnałów M1, także tych
   odrzuconych kierunkowym MTF.

Te same zdarzenia rynku mogą występować w różnych trybach, ale nie są
sumowane jako odrębne niezależne dowody skuteczności. Wyniki trybów nigdy
nie są dodawane do jednej wspólnej kwoty.

## Zasady księgowania

- Liczy się wyłącznie pozycja **CLOSED_SL / CLOSED_TP / CLOSED_TIMEOUT**,
  ze sprawdzonym czasem setupu, otwarcia, zamknięcia, kierunkiem i
  skończoną wartością P&L.
- Data rozliczenia to data **CLOSE w strefie Europe/Warsaw**, a nie data
  sygnału ani data UTC. Tydzień rozpoczyna się w poniedziałek.
- Restart workera ani ponowne pobranie tego samego archiwum nie tworzy
  drugiego wyniku: stabilny identyfikator pozycji jest deduplikowany.
- PENDING/OPEN, OBSEWUJ, SHADOW i niewykonane sygnały nie są
  liczone jako zamknięty zysk lub strata.
- Wartości `pnl_pts` pochodzą z istniejących modeli transakcji,
  po spread/slippage obliczonych przez te modele. Nie obliczamy ROI
  pieniędzy, bo nie przeprowadzono egzekucji na rachunku z kapitałem.
- Raport pokazuje skuteczność, liczbę zamknięć, LONG/SHORT, TP/SL/timeout,
  wynik netto i średni (pkt), profit factor, maksymalne obsunięcie (pkt),
  serię strat oraz wyniki metod.
- **Dzień/tydzień/miesiąc aktualny** porównywany jest do poprzedniego
  okresu o takim samym upływie czasu UTC. Nie porównujemy pół dnia do
  całego wczoraj.
- Wybrana wcześniejsza data w **bieżącym** tygodniu/miesiącu
  ogranicza analizę do końca wskazanego dnia.
- Okresy zamknięte porównywane są z pełnymi poprzednimi okresami.

## Brak danych i wiarygodność

Nie ma pozornych trafień i zysków z wcześniejszego 'obserwuj'.
Po nowym wdrożeniu historyczne CLOSED mogą zostać odczytane z
istniejącego checkpointu, lecz **pełna wiarygodność porównania**
wymaga, by audyt obejmował początek okresu poprzedniego. Gdy
nie ma takiej gwarancji, `comparison_ready = false`, a różnica
punktów wyświetlana jest jako brak danych, nie jako zero.

Archiwum audytu ma limit **3500 transakcji, 400 dni i 650 kB**,
plus margines rozmiaru całego checkpointu. Po osiągnięciu limitu
najstarsze wpisy są usuwane z samego audytu i informacja o retencji
jest zapisana w raporcie; istniejący PAPER v3 pozostaje bez zmian.

## Diagnostyka

- `periodic_audit_archive`: zarchiwizowane, zidentyfikowane CLOSED.
- `periodic_audit_report`: automatyczne porównania na ostatni skan
  dla bieżącego dnia, tygodnia, miesiąca.
- `periodic_audit_status`: błąd opcjonalnego audytu, jeśli wystąpił.
- `first_collected_utc`: początek obserwacji audytowej.
- `last_collected_utc`: ostatni skuteczny zapis.
- `retention_floor_utc`: najstarsza granica danych po obcięciu.

System liczy audyty także w pustym okresie (zerowe faktyczne zamknięcia),
ale **nie** przedstawia dat sprzed pokrycia archiwum jako udowodnione
wyniki zerowe.

Dla naukowej oceny przewagi konieczne są znacznie większe próby, niezależne
okresy poza próbą, ocena kosztów i uwzględnienie zależności między
jednoczesnymi strategiami.
