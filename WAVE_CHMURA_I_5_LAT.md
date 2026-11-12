# FOKU$ — WAVE 2.0, pięcioletnie M15 i chmurowe SHADOW

## Stan i bezpieczeństwo

- PR #62 (badawczy WAVE REVERSAL + WAVE INTELLIGENCE A–E) został
  scalony do main, ale NIE stanowi dowodu zyskowności.
- WAVE SHADOW wykorzystuje już istniejący w checkpointcie zdalnym
  klucz JSON `wave_shadow` i nie wymaga nowej tabeli Supabase.
- Dane pozostają w oryginalnej tabeli `fokus_paper_checkpoint`;
  brak dostępu do właściwego projektu chmury oznacza brak potwierdzenia,
  że nowy kod jest wdrożony i zapisuje kolejne obserwacje.
- WAVE **NIE** wpływa na sześć AUTO, głosowanie, MTF, bramki, SL, TP
  ani nowe pozycje PAPER; powód błędu badania jest diagnostyką.
- Aktywne tylko dla źródła `Capital.com DEMO REST`, instrumentu z
  aktualnego workera i dobrej, zamkniętej świecy M15.
- Potrzebne jest wcześniej potwierdzone
  `FOKUS_CANDLE_TIME_CONFIRMED=open`. W przeciwnym razie
  WAVE pozostaje `CLOCK_UNVERIFIED`.
- Można wyłączyć: `FOKUS_WAVE_SHADOW_ENABLED=false`.
  Domyślna wartość w kodzie to `true`, ale nie oznacza aktywacji
  procesu na serwerze.

## Zbieranie danych bez patrzenia w przyszłość

1. Worker odczytuje cztery zamknięte interwały jak dotychczas.
2. Dla poprawnej M15 wykrywa potwierdzone swingi: dwie **później
   zamknięte** świece są konieczne, ale sygnał jest dopiero na czasie
   ich zamknięcia, nie przy historycznym szczycie.
3. Zapisuje w checkpointcie do 240 unikalnych zdarzeń wraz z ID,
   kierunkiem, wzorcem, liczbą fal, ceną, wersją algorytmu i
   momentem zamknięcia; przy skanie nie nadpisuje duplikatów.
4. Pierwsza synchronizacja oznacza starsze zdarzenia jako `BACKFILL`.
   Jedynie kolejne nowe zdarzenia dostają status `FORWARD`.
5. Gdy minie pełne 1/2/4h i są wszystkie ciągłe M15 tej samej
   sesji NY, dopisuje wynik UP/DOWN/BOTH/FLAT dla progów
   0,25/0,5/1%. Braki danych oznacza `INVALIDATED`, a nie stratę.
6. Wyniki są **opisowymi statystykami SHADOW**, nie skalibrowaną
   prognozą i nie są używane przez AUTO.
7. Zapis odbywa się atomowo wraz z głównym checkpointem przez
   dotychczasowy mechanizm porównywania wersji (CAS).
8. Z uwagi na limit 2,5MB checkpointu archiwum jest **ograniczone do
   ostatnich 240 zdarzeń**, a nie nieograniczone. Dla długoterminowej
   historii będzie potrzebna osobna tabela i zweryfikowany projekt
   Supabase z RLS; obecnie nie twórzymy nieznanej bazy.

## Pięcioletnie M15 Dukascopy 2021–2026

Prawdziwe pliki BID i ASK nie były dostępne w tej rozmowie. Plik
`SP500_M15_FALOWANIE_ZDARZENIA.csv` zawiera tylko 1000 **gotowych
zdarzeń**, nie 114121 świec M15 OHLC. Plik pilotowy Excel to
zagregowane wyniki ośmiu strategii, a nie źródłowe notowania.

Aby zebrać źródła w systemie Windows:

1. Zainstaluj Node.js LTS oraz Python 3 z pandas, numpy.
2. W głównym folderze repo uruchom
   `POBIERZ_WAVE_M15_5_LAT_BID_ASK.cmd`. Korzysta z wersji
   `dukascopy-node@1.51.1`, instrumentu `usa500idxusd`,
   interwału `m15`, oddzielnych BID i ASK oraz pięciu
   rocznych okresów od 2021-11-11 do 2026-11-11 (koniec wyłączony).
3. Jeżeli kompilator nie wystartował, uruchom:
   `python -m pip install pandas numpy`
   `python scripts/prepare_wave_m15.py --folder DANE_SP500_WAVE_M15 --out FOKUS_WAVE_M15_5_LAT_BID_ASK.csv`
4. Powstały `FOKUS_WAVE_M15_5_LAT_BID_ASK.csv` ma:
   `Time` = **UTC CLOSE** (+15 min względem Dukascopy);
   `Open/High/Low/Close` = środek BID/ASK;
   pełne `BidOpen/BidHigh/BidLow/BidClose` i odpowiednie `Ask...`;
   `Spread` = ASK CLOSE - BID CLOSE;
   ewentualnie `Volume` (aktywność feedu Dukascopy, nie CME).
5. Kompilator zatrzymuje się, gdy brakuje jednego z dziesięciu
   plików, daty BID/ASK się nie zgadzają, występują duplikaty lub
   ujemny spread. **Nie interpoluje świec**. Wraz z CSV tworzy
   `.audit.json` z SHA256 źródłowych części.
6. W RAPORTY / WAVE INTELLIGENCE 2.0 wczytaj wynik CSV i wybierz
   `CLOSE` jako czas świecy. Przeglądaj wyniki A–E, roczne,
   LONG/SHORT, wynik po kosztach i eksperymentalny holdout.
7. W osobnym panelu WAVE REVERSAL AI możesz zbadać 2–5 fal,
   RAW/BOS i prawdopodobieństwa 0,25/0,5/1%.

W badaniu Dukascopy jest **CFD USA500**, a bieżącym
workerem zarządza **Capital.com US500 DEMO** — nie sumuj ich
transakcji bez uzgodnienia kontraktu, spreadu i zegara. Nawet
oryginalny BID+ASK OHLC nie zawiera tickowej kolejności SL/TP,
prowizji brokera ani poślizgu rzeczywistego. Wynik 2021–2026 po
obejrzeniu nie jest niezależnym, nienaruszonym testem forward.

## Jednorazowy test pięciu lat w GitHub Actions bez laptopa

- Workflow: `.github/workflows/wave-five-year.yml`. Po pierwszym
  dodaniu do `main` próbuje uruchomić się raz; można go również
  uruchomić świadomie przez `Actions → FOKU$ WAVE — five-year M15
  BID/ASK research (one-off) → Run workflow`.
- Uruchamia `scripts/download_wave_m15.sh`,
  `scripts/prepare_wave_m15.py` i
  `scripts/run_wave_5year.py`. Źródłowe M15 BID/ASK i wyniki
  zapisywane są jako artefakt Actions na 30 dni; nie są kopiowane
  do repozytorium ani używane przez aktywny worker.
- Zbiorczy ranking A–E, poszczególne rozliczenia, cechy, lata,
  godziny, horyzonty i warianty SL/TP są plikami CSV. Manifest
  zapisuje hash źródłowego CSV, źródło, daty, koszty i ograniczenia.
- Fail-closed: gdy pobieranie, zgodność BID/ASK albo kompletność
  danych zawiedzie, zadanie nie generuje fikcyjnego zysku.
- Konwencja danych Dukascopy jest zgodna z dokumentacją:
  `timestamp` UNIX ms oznacza **otwarcie** świecy, a importer
  wynikowy przesuwa czas o 15 min na M15 CLOSE UTC.
- Zielony GitHub Actions job pracy badawczej oznacza **ukończone
  obliczenia**, nie zweryfikowaną przewagę tradingową.

## Jak sprawdzić chmurę

- Po wdrożeniu **tego commita** do aktywnego workera sprawdź, czy
  checkpoint `meta.wave_shadow_status` pokazuje
  `OK_M15_<timestamp>_N=...`.
- W RAPORTY / PAPER v3 zobaczysz panel
  `WAVE SHADOW — ZAPIS PO KAŻDEJ M15`.
- Zwracaj uwagę na `wave_shadow_forward_events` — na pierwszym
  odczycie wszystkie starsze są `BACKFILL`, więc licznik FORWARD
  może wynosić zero.
- Jeśli w Northflank nadal działa starszy obraz bez tego commita,
  samo scalenie GitHub NIE uruchamia nowego archiwum.
- Jeśli RLS/klucze/konflikt checkpointu spowodują błąd,
  worker musi raportować problem; nie uznawaj przechowywania
  ani procesu 24/7 za potwierdzone bez logów i aktualnego stanu.

**Utrzymujemy WAIT dla WAVE.** Żaden historyczny wariant nie jest
automatycznie promowany do handlu.
