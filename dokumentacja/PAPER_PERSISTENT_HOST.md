# FOKU$ PAPER — niezależny worker 24/7 (opcjonalne wdrożenie)

## Status

Pliki `Dockerfile.paper-worker`, `railway.json` i
`trader/worker_service.py` są **gotową konfiguracją do wdrożenia**.
Ich obecność w GitHubie NIE oznacza, że serwer już działa.
To wyłącznie automatyczny **symulator PAPER**, nigdy prawdziwe zlecenia.
Nie zmieniamy starego SP500 Master Edition.

Ten sposób rozwiązuje problem nieregularnego GitHub Actions, bo worker
pozostaje uruchomiony na stale działającym serwerze. Sama infrastruktura
nie naprawia niedostępnego kalendarza BLS ani wadliwej historii świec:
bramki bezpieczeństwa nadal mogą zwracać WAIT.

## Wdrożenie (dla właściciela, bez wysyłania mi kluczy)

1. Zaloguj się do Railway i utwórz **Service** → **GitHub repo**
   `djfokus176-stack/fokus-the-best-trader`. Wybierz gałąź `main`.
   Usługa ma być **Background Worker**: bez domeny i bez portu HTTP.
2. Railway odczyta `railway.json`, który wskazuje `Dockerfile.paper-worker`.
   Jeśli nie wykryje pliku, ustaw zmienną:
   `RAILWAY_DOCKERFILE_PATH=Dockerfile.paper-worker`.
3. Obraz Docker zawiera `data/macro_calendar_manual.json`. Jego brak
   uniemożliwia zbudowanie obrazu. Plik nie zastępuje oficjalnych źródeł BLS.
4. W Railway → Variables (tylko tam, nie do repo) ustaw wartości:
   `FOKUS_PAPER_WORKER_ENABLED=true`,
   `FOKUS_CANDLE_TIME_CONFIRMED=open`,
   `FOKUS_PAPER_SCAN_INTERVAL_SECONDS=65`,
   `FOKUS_PAPER_ALIGN_MINUTE=true` (UTC + ok. 8 s po zamknięciu M1),
   `CAPITAL_ENV=DEMO`,
   `CAPITAL_API_KEY`,
   `CAPITAL_IDENTIFIER`,
   `CAPITAL_PASSWORD`,
   `FOKUS_SUPABASE_URL`,
   `FOKUS_SUPABASE_SECRET_KEY`.
   Opcjonalnie `CAPITAL_EPIC=US500`,
   `FOKUS_PAPER_STRATEGY=AUTO — 6 STRATEGII`,
   `OPENAI_API_KEY`, `FOKUS_AUTO_AI_ENABLED=false` dla niskich kosztów.
   Wszystkie wymagane sekrety muszą być tymi samymi wartościami co obecny
   działający worker GitHub; NIGDY nie umieszczaj ich w kodzie lub logach.
5. W Railway → Settings ustaw jedną replikę i sprawdź log:
   `PAPER HOST: DEMO READ-ONLY, durable remote checkpoint; scan loop active.`
   Kolejne skany powinny zwiększać `CLOUD_CHECKPOINT_VERSION` w Supabase.
   Najpierw obserwuj tylko jeden host; **nie dopuszczaj dwóch writerów**.
6. Gdy Railway zapisze pierwszy checkpoint i zachowa ciągłość przez
   kilka skanów, **wyłącz harmonogram GitHub Actions**:
   GitHub → Settings → Secrets and variables → Actions → Variables →
   `FOKUS_PAPER_WORKER_ENABLED=false`. Ta zmiana dotyczy wyłącznie
   zmiennych GitHub, nie konfiguracji usługi Railway.
   Potwierdź na ekranie, że kolejny checkpoint pochodzi z hosta.
7. Jeśli trzeba wrócić do GitHub Actions: najpierw zatrzymaj usługę Railway,
   potem przywróć `FOKUS_PAPER_WORKER_ENABLED=true` w GitHub.

## Ważne ograniczenia

- Konto Railway i ewentualne opłaty uruchamia właściciel projektu;
  **dodanie plików nie tworzy serwera ani płatności**. Railway liczy
  abonament i zużycie zasobów; ustaw limity wydatków i sprawdzaj Usage.
- Nie działa przez całą dobę sam rynek. Gdy Capital.com zwraca
  `CLOSED` lub `EDITS_ONLY`, wynik **WAIT / MARKET_CLOSED** jest
  prawidłowy. Weekend nie oznacza awarii. Odświeżanie 65 s nie daje
  sygnału 65 s — M1 zamyka się co minutę.
- Stary potwierdzony zegar OPEN, spread, jakość świec, MTF i filtr makro
  nadal obowiązują. Weryfikowany ręcznie plik awaryjny BLS ma datę ważności
  **16.11.2026 20:00 UTC**; odczytywany tylko po podwójnym HTTP 403
  z oficjalnych kanałów. Po wygaśnięciu konieczna jest ponowna
  weryfikacja aktualnego harmonogramu, bez automatycznego wydłużania daty.
- Płatny GPT jest wyłącznie ograniczonym komentarzem, **nie zleca pozycji**.
- Dopóki nie zobaczymy pełnego cyklu PENDING → OPEN → CLOSED w
  rzeczywistym DEMO i zweryfikowanych wyników netto, jest to narzędzie
  badawcze, a nie gotowy do inwestowania automat.
- Na stałym hostingu przez całą dobę pamiętaj o kontroli kosztów API,
  CPU, RAM, sieci, restartów i przechowywanych danych.
