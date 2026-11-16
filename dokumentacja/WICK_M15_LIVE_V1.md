# FOKU$ — WICK-M15-v1: ruchome knoty świecy w trakcie

## Przyczyna dotychczasowej nieruchomej świecy

W widoku `US500 M15 CLOUD` wykres rysował TYLKO zamknięte świece
`fokus_closed_candles`, aktualizowane po zamknięciu 15 minut. PR #82
dodał żółty MID REST, PR #84 niebieski punkt M1, **ale nie dodawał
kolejnej, dynamicznej świecy z HIGH/LOW**. Wcześniejszy LIVE w
`live_chart_fragment.py` używał `/prices` bezpośrednio w przeglądarce,
a to było celowo wyłączone w trybie CLOUD, by uniknąć 2. sesji Capital.

## Teraz, bez drugiego logowania

- Ten sam Northflank `Quote5sSampler` odbiera wyłącznie prawdziwe,
  świeże `TRADEABLE` BID/ASK z DEMO. Prowadzi niewielki,
  osobny **M15 MID z próbek**: początkowy MID w bieżącym kwadransie,
  maksimum z zaobserwowanych MID, minimum i ostatnia cena.
  Podgląd **może pomijać ekstremalne ceny pomiędzy pollami lub przed
  pierwszą próbką w danym kwadransie**. Nie są to brokerowe ticki.
- Jako pomocnicze dane, maksymalnie co ok. 30 sekund w tej SAMEJ sesji,
  worker pobiera brokerowe `/prices/US500?resolution=MINUTE_15&max=2`
  i sprawdza UTC oraz spójność nieukończonego OHLC. Błędy tego odczytu
  nie niszczą próbnego M15 i nie zatrzymują PAPER. Jeśli serwer
  ogranicza REST, `FOKUS_CLOUD_FORMING_M15_ENABLED=false` wyłącza
  tylko dodatkowe odpytywanie M15; świeca z próbek MID nadal działa.
- Prywatna, istniejąca tabela `fokus_live_quotes` przechowuje w OSTATNIEJ
  próbce `samples[-1]` opcjonalne JSON `sampled_m15` i
  `forming_m15`. **Nie ma migracji SQL, nowego worker, 2. sesji,
  haseł Capital w Streamlit ani zapisów do checkpointu PAPER.**
- Streamlit co około 5 s aktualizuje wykres i rysuje ZAWSZE OSOBNO
  jasnoniebieską/pomarańczową **M15 W TRAKCIE** jako prawdziwy obiekt
  `go.Candlestick`, `Open/High/Low/Close` z obserwacji MID. Właśnie
  jego knot HIGH i LOW oraz korpus C mogą się zmieniać.
  W razie braku MID może użyć oddzielnie potwierdzonej świeżej,
  nieukończonej `/prices` M15.
- Nie ma syntetycznej animacji. Jeśli cena naprawdę stoi albo broker
  nie zapisuje świeżych danych, podgląd się NIE poruszy. Zamiast
  milczeć pokaże diagnostykę `M15 LIVE NIEAKTYWNA` wraz z powodem.

## Jak jednoznacznie odróżnić nowy kod od starego

Na głównej stronie Streamlit, w panelu CLOUD, pojawia się napis
`Wersja podglądu: WICK-M15-v1`. Jeśli go nie ma, frontend nie
wdrożył jeszcze tej poprawki. Jeśli napis jest, ale brakuje
`M15 LIVE — RUCHOME KNOTY`, sprawdzić bieżący prywatny rekord
`fokus_live_quotes.US500` na Supabase (bez udostępniania sekretów):

- `broker_status=TRADEABLE`, `fresh=true`,
  `received_utc` i `broker_update_utc` świeże;
- `samples[-1].sampled_m15` istnieje, ma `kind=SAMPLED_M15_MID`,
  `samples` rośnie, `bar_close_utc` należy do bieżącego kwadransa;
- opcjonalnie `samples[-1].forming_m15.kind=BROKER_INCOMPLETE_M15`.

Jeśli oba wpisy są nieobecne przy `TRADEABLE`, trzeba sprawdzić, czy
Northflank pobrał bieżący commit, czy działa sam worker i czy 5s quote
sampler nie raportuje `QUOTE_WAIT_...`. Nie otwierać drugiego workera.

## Bezpieczeństwo

NIE używamy `sampled_m15` i `forming_m15` do:
`fokus_closed_candles`, strategii AUTO/3F/WAVE, PAPER,
SL/TP, scoringu, backtestu ani realnych zleceń.
Tylko prezentacja, `trade_permission=WAIT`. Gdy rynek zamknięty,
wiek próbki >12 sekund, kwadrans minął lub ostatnia M15 jest już
zamknięta, jasnoniebieska/pomarańczowa świeca znika.

**Uwaga:** Merge GitHub/pytest potwierdza kod, nie stan usługi.
Do potwierdzenia LIVE potrzebne są świeże rekordy Supabase i
wdrożony Northflank.
