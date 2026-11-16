# CLOUD /prices M1 W TRAKCIE — 16.11.2026

## Co naprawia

Wcześniej podgląd świecy w toku (`trader/live_chart_fragment.py`) nie uruchamiał
się przy `remote_paper_view_enabled()`, ponieważ bezpieczeństwo wyłącza
przeglądarkowy `auto_scan_active`. Celowo chroniło to konto przed drugą
sesją Capital.com i nadmiarowymi błędami HTTP 401 / 429.

**Nie kopiujemy bezpośrednio łatki Claude `FOKUS_CLOUD_LIVE_CHART=true`**, która
wymagałaby ponownego logowania do Capital w Streamlit. Korzystamy z jedynej
sesji **Capital.com DEMO** istniejącego workera **Northflank**.

## Architektura i przepływ

1. Worker sprawdza świeżą cenę MID/BID/ASK z `/markets?epics=US500`
   w wolnych chwilach między skanami M1 (najczęściej ~5 s, best effort).
2. **W tym samym workerze i sesji**, najwyżej raz na ~15 s, próbuje
   `GET /prices/US500?resolution=MINUTE&max=2` przez istniejącą,
   READ-ONLY `CapitalReadOnly.forming_candle()`.
3. Jeśli broker zwróci spójną, świeżą, bieżącą M1, pomocniczy
   `trader/cloud_forming_m1.py` waliduje jej czas, źródło, OHLC i spread.
4. Wpis **tylko do istniejącego `public.fokus_live_quotes.samples`**:
   najnowsza próbka MID dostaje opcjonalne podpole
   `forming_m1` (JSON). Nie trzeba nowej tabeli, migracji, sekreta,
   wspólnego brokera w Streamlit ani nowego workera.
5. Streamlit odczytuje Supabase co około 5 s i wyświetla na CLOUD M15
   **żółty** MID BID/ASK i **niebieski romb** nieukończonej M1
   (gdy ma maksymalnie 28 s i należy do otwartej minuty).
   Świece M15 pozostają tylko potwierdzonymi i zamkniętymi świecami.

**Nie równoważ:** odczyt HTTP co 5 s != gwarantowany nowy broker tick.
Wydajność zależy od aktywnego rynku, czasu skanów M1, sieci, REST i
przestrzegania limitów Capital. Jeśli M1 jest niedostępna lub stara,
pokaż WAIT, nigdy nie wymyślaj jej z minionej sesji. Obserwacja jest
wstępna i może odbiegać od późniejszej zakończonej świecy.

## Granice bezpieczeństwa

- `forming_m1` **NIE** trafia do
  `fokus_closed_candles`, `fokus_paper_checkpoint`,
  `queue_paper`, AUTO, 3F, WAVE, modelu ani do TP/SL.
- `CapitalReadOnly.forming_candle` to **GET**; zero metod wystawiania
  rzeczywistych lub PAPER zleceń w nowym module.
- Każdy błąd podglądu nie blokuje głównego workera i nie omija
  bramek danych, kalendarza BLS czy zegara świec.
- `FOKUS_CLOUD_FORMING_M1_ENABLED=false` na Northflank wyłącza
  tylko pobranie M1 w trakcie; stare mechanizmy PAPER pozostają bez zmian.
- Nadal **tylko jeden zapisujący** checkpoint Supabase i jeden worker.
- Maksymalnie 24 próbki istniejącej tabeli to NIE trwałe archiwum 5S.
  Pełny długoterminowy zapis wymaga osobnego projektu retencji i kosztów.

## Weryfikacja działania — produkcja

Po merge i potwierdzonym **redeploy Northflank**, kiedy US500 jest
`TRADEABLE` i quoty są świeże:

- ostatni prywatny rekord `fokus_live_quotes` powinien mieć próbkę z
  `forming_m1.kind=BROKER_INCOMPLETE_M1` i `collected_utc`;
- na wykresie zobaczysz żółty MID 5S i niebieski romb M1;
- po zamknięciu minuty stara M1 musi zniknąć lub zostać zastąpiona nową,
  a świeca M15 zmienia się dopiero po osobnym zapisie zamkniętego bar;
- jeśli zobaczysz status `BRAK_SWIEZEJ_M1_W_TRAKCIE` lub
  `NOT_TRADEABLE_OR_STALE_QUOTE`, sprawdź dostarczenie danych i logi
  Northflank, nie odblokowuj PAPER.

**Merge na GitHubie i zielone pytest nie dowodzą wdrożenia w Northflank.**
Przy ograniczonym dostępie do właściwej prywatnej bazy, status LIVE należy
pozostawić jako NIEZWERYFIKOWANY.
