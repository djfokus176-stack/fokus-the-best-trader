# FOKU$ THE BEST TRADER — PAPER v4 (przygotowana infrastruktura)

**Data:** 2026-11-05. **Jedyny repozytorium:** `djfokus176-stack/fokus-the-best-trader`.
Stare repo `sp500-kolega-gemini` jest READ-ONLY. Żadnych zleceń na Capital.com.

## Gotowy kod; brak uruchomionej usługi

1. `trader/remote_checkpoint.py` — odczyt trwałego checkpointu ze **zdefiniowanej przez właściciela osobnej bazy Supabase**, przywrócenie tabel PAPER do izolowanego SQLite workera, blokada stale-version przez `PATCH ... &version=eq.N`, bezpieczna obsługa błędów RLS i deduplikacja OHLC w tabeli `fokus_closed_candles`.
2. `trader/worker.py` — jeśli są **oba** `FOKUS_SUPABASE_URL` i `FOKUS_SUPABASE_SECRET_KEY`, każdy skan ładuje aktualny checkpoint i zapisuje nową wersję, razem z timestampem potwierdzonego uruchomienia. Brak zapisu lub konflikt powoduje błąd; nie udajemy sukcesu. Domyślne DEMO, strict MTF i kalendarz BLS.
3. `.github/workflows/paper-v4-scan.yml` — harmonogram co 5 minut i ręczne uruchamianie; pojedynczy writer dzięki `concurrency`. **NIE ma włączonego połączenia z brokerem ani Supabase dopóki właściciel nie ustawi zmiennej i sekretów.** GitHub Actions nie zapewnia gwarancji punktualnego uruchomienia; może opóźnić lub zgubić job. To prototyp niezależnego monitoringu, nie profesjonalny serwer 24/7.
4. `app.py` — po wyraźnym ustawieniu `FOKUS_REMOTE_VIEW_ENABLED=true` panel **wyłącznie czyta** checkpoint workera, wyświetla pozycje, ceny, raporty i informuje, jeśli ostatni worker scan był >15 minut temu. Lokalny Streamlit nie tworzy wtedy konkurencyjnych transakcji PAPER.
5. `dokumentacja/supabase_paper_v4.sql` — SQL nowej prywatnej tabeli checkpointu i archiwum zamkniętych świec; RLS, brak uprawnień dla `anon` i `authenticated`, klucz backendu poza repo.

## Twoje jednorazowe kroki — NIE wpisuj żadnego hasła ani klucza do czatu

**A. Stwórz OSOBNY projekt Supabase dla FOKU$**. Użyj Supabase Dashboard → New project. Nie nadpisuj przypadkowo istniejącego projektu; widoczny projekt Supabase w koncie mógł służyć innej aplikacji. Utworzenie projektu może podlegać limitom lub opłatom zależnie od planu.

**B. W SQL Editor nowego projektu uruchom** zawartość `dokumentacja/supabase_paper_v4.sql`. Sprawdź, czy powstały dwie tabele `fokus_paper_checkpoint` i `fokus_closed_candles`. W `fokus_paper_checkpoint` powinien być **jeden** wiersz `main`, `version=0`.

**C. W nowym GitHub repo → Settings → Secrets and variables → Actions → Secrets** ustaw, każda jako osobna wartość:
```text
FOKUS_SUPABASE_URL           (Project URL, https://<project>.supabase.co)
FOKUS_SUPABASE_SECRET_KEY    (SECRET server-only key from the dedicated project)
CAPITAL_API_KEY              (klucz Capital.com DEMO)
CAPITAL_IDENTIFIER           (identyfikator Capital.com DEMO)
CAPITAL_PASSWORD             (hasło Capital.com API DEMO)
```
**Nie umieszczaj prawdziwego klucza Supabase w repozytorium, TXT, screenie, URL, otwartym JS ani w przeglądarce.** Nowoczesny klucz Secret jest przeznaczony wyłącznie na backend. Repo nie zawiera Twoich sekretów.

**D. Uruchom próbny skan tylko po konfiguracji — najpierw archiwizacja, potem PAPER.** W `Settings → Secrets and variables → Actions → Variables` ustaw `FOKUS_PAPER_WORKER_ENABLED=true` **dopiero** po konfiguracji kroku A–C. Następnie Actions → `FOKU$ PAPER v4 - scheduled DEMO scan (optional)` → `Run workflow`. Sprawdź status `CLOUD_CHECKPOINT_VERSION=1` i czy w Supabase `version` wzrosła. Gdy chcesz wyłączyć, zmień tę repo variable na `false`. Zaplanowane wywołania są BEST EFFORT co 5 minut — mogą się opóźniać.

**Krytyczny bezpiecznik zegara:** dopóki nie zweryfikujesz `snapshotTimeUTC` na prawdziwych świecach DEMO, worker gromadzi OHLC, ale **NIE tworzy nowych pozycji PAPER**. W raporcie pracy pojawia się `CANDLE_TIME_UNVERIFIED` / `SETUPS_DISABLED`. Po porównaniu zegara API z wykresem brokera i potwierdzeniu, że timestamp jest godziną **ZAMKNIĘCIA**, możesz ustawić w GitHub Actions Variables `FOKUS_CANDLE_TIME_CONFIRMED=close`. **Nie ustawiaj tego w ciemno.** Jeśli broker opisuje czas OTWARCIA, najpierw trzeba dostosować przesunięcia czasu w silniku, a nie włączać setupy.

**E. Streamlit Cloud → My Apps → FOKU$ → Settings → Secrets**, zachowaj istniejące klucze, dopisz:
```toml
FOKUS_REMOTE_VIEW_ENABLED = true
FOKUS_SUPABASE_URL = "https://TWOJ_OSOBNY_PROJEKT.supabase.co"
FOKUS_SUPABASE_SECRET_KEY = "TWOJ_BACKEND_ONLY_SECRET_KEY"
```
Nie kasuj aktualnych `APP_ACCESS_PASSWORD`, OpenAI czy Capital.com. Po Save/Reboot zaloguj się i sprawdź `RAPORTY → PAPER v3`, etykietę `REMOTE PAPER` oraz czas ostatniego skanu. Użytkownik, który nie ma zdalnej bazy, powinien pozostawić `FOKUS_REMOTE_VIEW_ENABLED=false`.

## Kluczowe ograniczenia i zasady

- **Jeden writer:** worker GitHub Actions zapisuje cloud state; Streamlit z remote mode jest wyłącznie czytnikiem PAPER. Nie uruchamiaj wielu niezależnych procesów writer z tym samym checkpointem. Optymistyczne wersjonowanie chroni przed cichym nadpisaniem, ale nie zapewnia bezstratnej obsługi wszystkich wyścigów pomiędzy pracownikami.
- **Telegram CLOUD WYŁĄCZONY**: jego stare 'jedna próba przed zapisem' z lokalnego SQLite nie chroni przed restartem stateless workera między wysłaniem a zapisem checkpointu. Nie włączam tego pozornie bezpiecznie. Osobny outbox remote + potwierdzane retry to osobny etap.
- **Tylko sygnały z DEMO**; brak zleceń i rzeczywistych cen wykonania. Paper fill jest rekonstruowany po zamknięciu kolejnej świecy.
- **Konwencja Capital.com `snapshotTimeUTC` nadal niepotwierdzona** na rzeczywistym koncie; trzymamy dwa czasy: `entry_assumed_utc` i `entry_detected_utc`. Nie nazywaj ich rzeczywistym momentem wykonania.
- **Dane historyczne:** świeczki są idempotentnie upsertowane do `fokus_closed_candles`. W trybie `FOKUS_REMOTE_VIEW_ENABLED=true` w zakładce `RAPORTY → Podstawowy replay` dostępny jest przycisk `POBIERZ DO 5000 ZAMKNIĘTYCH ŚWIEC Z TRWAŁEJ BAZY`. Pobiera stronicowane OHLC wyłącznie dla Capital DEMO i właściwego EPIC/TF; laboratorium używa dłuższej historii po świadomym kliknięciu. Nadal nie ma automatycznego wieloletniego walk-forward na całym archiwum.
- **Limit checkpointu 2,5 MB:** w obecnej wersji pełen zbiór pozycji/eventów jest przechowywany jako jeden JSON. Po przekroczeniu limitu worker przerywa zapis i wymaga przejścia na normalizowane tabele historyczne. To nie jest nieskończone archiwum; nie obiecuj trwałości przy nieograniczonym wzroście.
- **Kontrola niepowodzeń:** przy 401/403 Supabase, braku pliku schema SQL, konflikcie CAS lub braku potwierdzenia PATCH worker ma kończyć uruchomienie błędem, a nie tworzyć fałszywy raport SUCCESS.
- **Płatności i limity:** darmowe plany mogą mieć limity wywołań i przechowywania. Nie zweryfikowano działania z rzeczywistymi sekretami, projektem Supabase ani długotrwałej niezawodności.
- **Praca co minutę i prawdziwa ciągłość 24/7:** potrzebny stały hosting; cron GitHub Actions minimum 5 min i brak gwarancji punktualności.
- **Niezweryfikowane rzeczy:** PENDING→OPEN→CLOSED na rzeczywistych cenach Capital DEMO, faktyczny obieg workera→Supabase→Streamlit, realny Telegram i skuteczność strategii. Testy jednostkowe/integracyjne stosują mocki i nie zastępują testów na koncie.

**Stan:** przygotowany kod i migracja; **nieprzyłączona** zewnętrzna baza; **wyłączony** harmonogram (bez `FOKUS_PAPER_WORKER_ENABLED=true`).
