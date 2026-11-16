# Diagnoza unieruchomionej świecy US500 — 2026-11-16

## Twarde fakty z terminala

Około 10:26 Europe/Warsaw widać:
- checkpoint ostatniego PAPER sprzed ~0,6 minuty;
- zamknięte M15 do 09:15 UTC;
- `broker_status=TRADEABLE`, ale **wiek ostatniej ceny BID/ASK = 2246,2 sekundy (~37,4 min)**;
- `M15 LIVE NIEAKTYWNA: QUOTE_NIEAKTUALNY_LUB_RYNEK_ZAMKNIETY`;
- UI rozpoznaje `WICK-M15-v1`.

**Wniosek:** kod renderujący ruchome knoty jest wdrożony do STREAMLIT, ale
nie otrzymuje aktualnych próbek z Northflank. Ponieważ PAPER checkpoint
jest świeży, nie wolno już utożsamiać świeżości PAPER ze świeżością 5S.

## Przyczyna w logice worker.py

Wcześniej `idle_quote_pulses(...)` działało tylko **po zakończeniu**
`remote_scan_once`, przez czas `seconds_until_next_m1_scan`. Przy długich
skanach MTF/archiwizacji/GPT/SQL/Supabase przerwa mogła wynieść sekundy
lub zniknąć. Wtedy pozostawał świeży PAPER checkpoint, lecz stary
`fokus_live_quotes`. Dodatkowo zwykły błąd GET /markets powodował
`ERROR_INTERVAL=300s`, czyli pięć minut braku prób.

## Naprawa bez drugiego loginu i bez drugiego workera

- `trader/cloud_quote_pump.py`: jeden **wątek** obserwacyjny w tym samym
  procesie Northflank; działa także gdy główna pętla skanuje lub archiwizuje.
- Osobne `requests.Session` i `RemoteCheckpoint` chronią wątki przed
  równoczesnym używaniem obiektów HTTP. Obserwator pożycza aktualne
  tokeny CST/X-SECURITY-TOKEN z GŁÓWNEGO logowania DEMO; **nie
  wysyła `POST /session`**, nie tworzy drugiego konta/sesji brokera,
  nie uruchamia drugiej instancji PAPER ani zleceń.
- Status `quote_pump` z liczbą prób, czasem ostatniej próby/zapisu
  i ostatniej FRESH ceny jest bezpiecznie dopisywany do istniejącego
  `payload.meta` checkpointu tuż przed CAS save (bez sekretów).
- UI pokazuje status i oznacza cenę archiwalną **NIE LIVE**.
- Typowe błędy danych Capital: retry po 30 sekundach; HTTP 429:
  120 sekund. Awaria Supabase nadal 300 sekund, aby nie przeciążać
  usługi. Wszystko bez obchodzenia ograniczeń API.
- Gdy `GET /markets?epics=US500` jest niemożliwy, wątek może
  wykonać osobne read-only `GET /markets/US500` (tylko po status)
  i `GET /prices/US500?resolution=MINUTE_15&max=2` (tylko po
  bieżącą świecę). Ten odczyt ma jawne
  `fresh=false`, `delay_seconds=9999` (niezweryfikowane) i
  `samples[-1].fallback_only=true`,
  `source_delay_unknown=true`. Wyłącznie wykres może z niego
  wyświetlić **nieukończony broker M15 z ostrzeżeniem**.
  Nie wolno przedstawiać tych pól jako świeżego kwotowania 5S,
  sygnału AUTO, świecy potwierdzonej albo brokerowego fillu.
- Zwykły `Quote5sSampler` nadal odczytuje BID/ASK co **około**
  5 sekund, jeśli źródło zwraca nowe dane; nie ma gwarancji ticków.

## Jak rozstrzygnąć przyczynę po wdrożeniu

Na stronie w CLOUD M15 odszukaj sekcję:

`📡 NIEZALEŻNY KOLEKTOR 5S | stan: ... | ostatnia próba ... | ostatni zapis ... | ostatnia ŚWIEŻA cena ...`

Możliwe statusy:
- **`LIVE_QUOTE_SAVED`**: prawdziwa świeża cena dotarła do Supabase;
  ruchomy M15 może zmieniać H/L/C, jeśli cena faktycznie się zmienia.
- **`BROKER_M15_ONLY_UNVERIFIED_QUOTE`**: bieżąca, niezamknięta
  M15 z `/prices`, ale brak potwierdzonego quote UTC/delay;
  podgląd będzie działał tylko jako oznaczony NIEZWERYFIKOWANY.
- **`BROKER_NOT_FRESH`**: Capital zwrócił odpowiedź, ale nie przeszła
  bramki świeżości (nie zgaduj).
- **`QUOTE_WAIT_FeedError`**: odczyt rynku z Capital nie powiódł
  się, nawet z fallbackiem.
- **`QUOTE_WAIT_RemoteError`**: prywatny zapis Supabase nie powiódł się,
  niezależnie od działającego checkpointu PAPER.
- **`NO_BACKGROUND_PUMP`**: wdrożono stary worker, w Northflank
  ustawiono `FOKUS_SCALP_5S_ENABLED=false`, albo checkpoint zapisuje
  inne źródło niż bieżąca nowa wersja.

Jeśli frontend ma `WICK-M15-v1`, ale brak
`BACKGROUND_SAME_CAPITAL_LOGIN` w `meta.quote_pump.mode`, należy
zweryfikować **deployment workera Northflank do najnowszego commita**.
Sam merge GitHub tego nie potwierdza.

## Ograniczenia i bezpieczeństwo

- Brak migracji SQL i nowych API secrets. Legacy `Quote5sSampler`,
  `idle_quote_pulses` i testy pozostają dostępne dla istniejących
  starszych wywołań, ale Northflank używa teraz niezależnego wątku.
- Tylko podgląd; ZERO zmian `evaluate_auto`, `queue_paper`,
  `progress_paper`, zasad MTF i SL/TP, FOKU$ 3F oraz LIVE orders.
- Nie wywnioskuj z zielonego testu, że broker jest dostępny, nowy commit
  działa na Northflank lub że system jest rentowny.
- Długoterminowo Capital.com udostępnia WebSocket do streaming
  kwotowań; to osobna praca wymagająca obsługi subskrypcji, tokenów
  i testów produkcyjnych. NIE zastępuj automatycznie tego REST
  protokołem o nieprzetestowanej egzekucji.
