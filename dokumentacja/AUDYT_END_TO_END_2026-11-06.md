# FOKU$ THE BEST TRADER — audyt end-to-end, 6 listopada 2026

**Dotyczy WYŁĄCZNIE nowego repozytorium `fokus-the-best-trader`.**
Nie zmieniać starego programu SP500 Master Edition v7.1 ani jego archiwum.

## Werdykt

**Kod, testy automatyczne i realne działanie brokera to trzy różne rzeczy.**
W chwili audytu: wdrożono osobny fragment LIVE 5 s, skan na ostatnich
ZAMKNIĘTYCH świecach około co 60 s przy otwartej stronie, sześć strategii
i opcjonalną EMA50 WAVE, wiadomości RSS i osobnego workera PAPER.
NIE POTWIERDZONO prawdziwego cyklu wejście→OPEN→TP/SL na feedzie DEMO.
Nie przedstawiać aplikacji jako sprawnego systemu automatycznego tradingu,
dopracowanego modelu AI uczącego się ani systemu o znanej rentowności.

## P0 — BLOKADY PRZED RZECZYWISTYM TESTOWANIEM

| ID | Ustalenie z kodu / logów | Stan i dalszy warunek |
|---|---|---|
| P0-1 | Automatyczny worker 5.11 23:49 UTC: `WAIT / CANDLE_TIME_UNVERIFIED`. | **NIE ROZWIĄZANE**. Weryfikacja 2 kolejnych oznaczeń świec M1 u dostawcy. Ustawić zmienną `FOKUS_CANDLE_TIME_CONFIRMED=open` wyłącznie po niezależnej weryfikacji (nie na ślepo). |
| P0-2 | Ten sam worker: `DATA_STALE`, **240 rekordów `bid > ask`**, brak nowych PAPER. | **NIE ROZWIĄZANE**. Potrzeba surowej próbki danych demo i porównania pól openPrice/highPrice/lowPrice/closePrice z odpowiedzią brokera. Poprawiony parser liczy błędy według pola, nadal BLOKUJE trading; nie odwraca BID/ASK automatycznie. |
| P0-3 | GH Actions schedule `3-58/5` jest best effort. Potwierdzony AUTOMATYCZNY run 5.11 23:48 UTC, ale nie ciągłość 5 min. | **CZĘŚCIOWO**, istnieje cron i checkpoint. Na 24/7 wymagany monitorowany, stale działający worker; status opóźnień pokazuje UI. |
| P0-4 | Makro BLS brak/kalendarz nieaktualny lub MTF niegotowe → WAIT. | **CELOWE ZABEZPIECZENIE**. Trzeba zweryfikować oficjalne źródło, czasy i zgodność MTF na aktualnym feedzie; nie usuwać filtrów tylko dla większej liczby typów. |

## P1 — WYKRES I WIDOCZNE DZIAŁANIE

1. `trader/live_chart_fragment.py`: `@st.fragment(run_every="5s")`
   odświeża osobno /prices (`max=2`) zamiast przebudowywać cały Streamlit
   co 5 s. Licznik **prób i udanych odczytów**, świeżość API oraz miniwykres
   ostatnich rzeczywistych MID (maks. 90 próbek) umożliwiają wykrycie:
   **API ERROR / CENA BEZ ZMIANY / CENA ZMIENIONA**. Nie gwarantuje to
   nowego ticka co 5 s (REST to nie streaming). Po HTTP429: backoff.
2. `trader/live_chart.py`: aktualna forming candle lub podgląd z próbek
   `/markets` opisane inaczej; żadna nie trafia do strategii PAPER.
   `PAPER_OPEN/CLOSE` wyłącznie z trwałego ledgera.
3. `app.py`: status blokady źródła jest widoczny także wtedy, gdy
   snapshot z rynku ma `good=False`; nie pokazujemy jako LIVE
   nieaktualnego OHLC. `uirevision` Plotly może zachować powiększenie —
   jeśli miniwykres się zmienia, lecz duży nie, sprawdzić ręczny zoom.
4. **Do sprawdzenia na przeglądarce właściciela**: włączone AUTO-SKAN,
   źródło `Capital.com DEMO REST`, wzrost liczników co 5 s, realne
   `last_success_utc`, brak blokady autoplay (głosy). Nie mogę
   potwierdzić GUI użytkownika z samych testów GitHub.

## P1 — JAKOŚĆ DANYCH BROKERA

1. `trader/market.py`: odmowa braków danych, NaN, ±Infinity, cen
   niepozytywnych, `bid > ask`, nieprawidłowego High/Low, duplikatów,
   przyszłych/starych świec, dużych luk i niewłaściwego spreadu.
2. Wadliwe świece mogą trafić do **kwarantanny tylko w celu diagnostyki**;
   `Snapshot.good=False` blokuje nowy sygnał. Nie tolerujemy
   240 błędnych świec, bo wynik EMA/ATR/backtest byłby niewiarygodny.
3. Czas Capital.com w kodzie jest warunkowo interpretowany jako etykieta
   otwarcia. Każda zamknięta świeca jest reprezentowana jej końcem
   interwału. `FOKUS_CANDLE_TIME_CONFIRMED` pozostaje jawną blokadą.

## P1 — NIEZALEŻNY WORKER I LEDGER

- `.github/workflows/paper-v4-scan.yml`: cron około 5 minut,
  pojedynczy writer, ręczny workflow_dispatch i warunek włączenia
  `FOKUS_PAPER_WORKER_ENABLED=true`; sam zielony test CI
  **nie potwierdza** działania PAPER 24/7.
- `trader/worker.py`: `FOKUS_PAPER_STRATEGY` ze zmiennych repozytorium
  (dropdown Streamlit NIE zmienia ustawienia worker). Metadata zapisuje
  strategię, zegar, blokady, czas skanu i status RSS.
- `trader/remote_checkpoint.py`: CAS przy zapisie checkpointu,
  odczyt bez publikowania sekretów, osobna tabela OHLC.
- `trader/paper_lifecycle.py`: PENDING ≠ OPEN; OPEN dopiero po otrzymaniu
  **zamkniętej kolejnej świecy**, odtworzony retrospektywnie.
  SL ma priorytet gdy jedna świeca obejmuje SL i TP, zapisuje spread
  i poślizg. To **model PAPER**, nie prawdziwy kurs wykonania.
- **Niezweryfikowane**: regularne tworzenie PENDING, OPEN i CLOSE,
  trwałość po restarcie i kompletna analiza późniejszych spóźnionych
  skanów na realnym środowisku DEMO.

## P1 — STRATEGIE, EFEKTYWNOŚĆ I KOSZTY

- `AUTO — 6 STRATEGII` to konsensus: co najmniej dwa zgodne setupy,
  brak przeciwnego kierunku, potwierdzenie MTF; WAIT nie jest awarią,
  jeśli przyczyna jest jawna.
- `EMA50 WAVE (PORÓWNANIE)` to osobna hipoteza inspirowana starym kodem,
  bez kopiowania starego archiwum lub historycznych strzałek.
- `adaptive` i `fixed` to warianty wyjść PAPER do **porównania**;
  brak dowodu, że adaptive „łapie więcej punktów”.
- Brak udowodnionego zysku netto, edge, wiarygodnej skuteczności
  out-of-sample i porównania drawdown. Wymagany replay z kontrolą
  leakage, walk-forward, koszty i prawidłowy czas świec.

## P2 — GPT I WIADOMOŚCI

- `trader/news_radar.py`: wyłącznie oficjalne RSS FED/BLS/BEA;
  kalendarz BLS osobno. Nie oznacza to kompletnego kalendarza FOMC,
  NFP, wszystkich wiadomości rynkowych i globalnego sentymentu.
- `trader/news_context.py`: **udane pobranie ≠ świeża publikacja**.
  Do AI trafiają tylko nagłówki z parsowalną datą, hostem
  na allowliście, wiekiem maks. 72 h i ograniczoną długością.
- Czat GPT w Streamlit jest **ręczny i płatny**. Opcjonalny
  worker-GPT ma osobne limity liczby wywołań i na podstawie
  zamkniętych świec + wiadomości może komentować setup/WAIT.
  Nie jest autonomicznym silnikiem, który sam zleca handel.
- Brak gwarantowanego budżetu kwotowego API; limity liczby
  wywołań nie zastępują billing/alerts i limitów w OpenAI.
- Do weryfikacji: poprawny model i odpowiedź ze stanu worker
  `SUCCESS`; na starszych logach widoczne było `SKIP_WAIT`
  oraz 0 wywołań.

## P2 — ALERTY, ZABEZPIECZENIA, RAPORTY

- `assets/voices` / `trader/paper_sounds.py`: głosy LONG, SHORT,
  zamknięcie oraz dźwięki SL/TP; autoplay może wymagać kliknięcia.
- `trader/paper_reporting.py`: metryki tylko z zamkniętych pozycji,
  osobne dzienne/tygodniowe oraz `fixed/adaptive`.
- `trader/auth.py`, `owner_auth.py`: owner-only access
  do kluczy; nie wprowadzać sekretów do repo, screenshotów ani logów.
- `Supabase` ma pozostać jedynym cloud ledger writerem; frontend
  tylko odczytuje. NIE publikować publicznie endpointów z
  `sb_secret_*` i tokenów sesji Capital.com.

## Procedura odbioru, bez domysłów

1. Zamknięty i otwarty rynek: sprawdź liczniki REST, miniwykres MID
   i komunikaty „cena bez zmiany”, timestamp aktualnej świecy.
2. Zweryfikuj raw OPEN/CLOSE nazewnictwo na **dwóch kolejnych M1**,
   zobacz raport błędów 240 × bid>ask z podziałem na pola. Jeśli nadal
   występuje — testuj API/EPIC DEMO, nie omijaj parsera.
3. Zweryfikuj 4 niezależne interwały M1/M5/M15/H1 (min. 70 świec),
   oficjalny kalendarz oraz status TRADEABLE.
4. Porównaj status workera/strategy w Supabase z rzeczywistym
   GitHub Actions logiem i czasem ostatniego zapisu.
5. Dopiero po braku blokad technicznych: sprawdź pojedynczy
   PENDING, odtworzone OPEN na następnej zamkniętej świecy,
   STOP/TP i raport P&L, audio i nieretrowane strzałki.
6. Na podstawie co najmniej kilkudziesięciu *rzeczywiście zamkniętych*
   pozycji PAPER zrób analizę walk-forward i kosztów.
   Więcej sygnałów ≠ większa rentowność.

**Wersja gotowa do testów technicznych, lecz NIE certyfikowana do
autonomicznego scalpowania lub realnych transakcji.**
