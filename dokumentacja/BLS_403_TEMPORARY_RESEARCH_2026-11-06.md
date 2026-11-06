# Krótkoterminowe rozwiązanie BLS 403 — wyłącznie DEMO/PAPER

Na 6 listopada 2026 oficjalny harmonogram BLS (sekcja **November 2026**)
jest dostępny publicznie pod
https://www.bls.gov/schedule/2026/
i podaje datę ostatniej aktualizacji **3 listopada 2026**.
Urzędowe źródło BLS, nie prognoza; daty zweryfikowane 6.11.

GitHub Actions ma jednak HTTP 403 także na oficjalnej stronie .ics
i alternatywnej stronie HTML. **Nie wolno utożsamiać błędu 403
z brakiem publikacji makro.**

## Zastosowana procedura

1. Spróbuj pobrać kalendarz LIVE .ics z www.bls.gov.
2. Jeśli .ics zwraca 403, sprawdź oficjalny HTML bieżącego i następnego
   miesiąca (tak jak dotychczas).
3. Jeśli oba źródła odpowiedzą **dokładnie HTTP 403**, wprowadź
   jawnie oznaczoną, ręcznie zweryfikowaną kopię dat BLS, opracowaną
   **6.11.2026** i ważną tylko do **8.11.2026 00:00 UTC**.
   Przy jakimkolwiek innym błędzie łącza/kalendarza — nie używaj kopii.
4. Po upływie ważności bez odświeżenia oficjalnego źródła
   zwróć błąd `BLS_VERIFIED_SNAPSHOT_EXPIRED` i zablokuj **nowe PAPER**.
   Nie przesuwaj daty ważności automatycznie.
5. Status w logu: `MACRO_SOURCE=BLS_VERIFIED_SNAPSHOT_NOT_LIVE`,
   data ważności i brak twierdzenia o bieżącym dostępie LIVE.

Dokładne wybrane daty (US Eastern → UTC, w listopadzie EST = UTC-5):
- 6.11 08:30 ET / 13:30 UTC — Employment Situation;
- 10.11 08:30 ET / 13:30 UTC — CPI;
- 13.11 08:30 ET / 13:30 UTC — PPI;
- 17.11 08:30 ET / 13:30 UTC — Import/Export prices;
- 20.11 10:00 ET / 15:00 UTC — State Employment.

Pozostałe filtry (czas OPEN M1, MTF, snapshot freshness, spread,
risk, 2/6 konsensusu, czy TRADEABLE) nadal obowiązują.
**To tylko krótkoterminowe rozwiązanie do badawczych transakcji
PAPER, nie pełnowartościowy kalendarz do rzeczywistego handlu.**

## Utrzymanie

To rozwiązanie tymczasowe. Aby mieć wiarygodne 24/7 należy wdrożyć
dostęp do aktualnego oficjalnego kalendarza przez autoryzowaną usługę
poza IP GitHub Actions, walidować źródło i świeżość oraz przesyłać
zweryfikowany snapshot do Supabase na bieżąco. Bez takiego źródła
nie można obiecywać stałego działania bota PAPER.

## Odbiór

Po scaleniu uruchom `FOKU$ PAPER v4` ręcznie. W logu sprawdź:
`GATES`, `MACRO_SOURCE`, `DIAGNOSTICS` i `QUEUE`.
`WAIT` przy 0/2 zgodnych setupów jest poprawny i NIE oznacza
awarii bota.
