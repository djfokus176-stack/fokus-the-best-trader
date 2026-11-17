# FOKU$ THE BEST TRADER — broker DEMO (nie PAPER)

Ten tryb jest **DOMYŚLNIE WYŁĄCZONY**. Wewnętrzne strategie, historyczne
transakcje PAPER v3 i niezależny M1 PAPER TEST działają jak dotychczas.

## Różnica

- **OBSERWUJ / SHADOW**: brak zleceń, wstępne układy.
- **PAPER / PAPER TEST**: symulacja wejść/wyjść na zamkniętych świecach.
- **CAPITAL.COM DEMO**: prawdziwe zlecenie wysłane wyłącznie na **rachunek
  testowy brokera** z wirtualnymi środkami. To nie LIVE ani prawdziwe pieniądze.

## Warunki przed włączeniem

1. Zaloguj się na **Capital.com DEMO** i sprawdź, czy instrument US500
   jest dostępny, ma poprawną minimalną wielkość i pozwala ustawić SL/TP.
2. W ustawieniach workera Northflank użyj tej samej sesji Capital DEMO,
   która już dostarcza dane. NIE konfiguruj kluczy LIVE.
3. Sprawdź identyfikator **rachunku DEMO** przez prywatny ekran brokera;
   nie wklejaj numeru ani kluczy w publicznej rozmowie.
4. Ustaw na **Northflank / Environment Variables**:
   - `FOKUS_DEMO_BROKER_MODE=DEMO_ONLY_CONFIRMED`
   - `FOKUS_DEMO_BROKER_ACCOUNT_ID=<twój_numer_rachunku_DEMO>`
   - `FOKUS_DEMO_BROKER_SIZE=<wielkość_poziomu_US500_według_brokera>`
5. Wybierz niewielką, obsługiwaną przez rachunek testowy wielkość,
   np. nie wpisuj 1 bez sprawdzenia specyfikacji konkretnego US500.
   Implementacja akceptuje 0.01–1.0, ale Capital.com może wymagać
   innej wielkości minimalnej i ją odrzucić. Nie zgaduj wartości.
6. Zapisz i przeładuj usługę, sprawdź zakładkę **TERMINAL**.
   Panel **CAPITAL.COM DEMO** powinien pokazać potwierdzoną pozycję
   tylko po tym, gdy broker potwierdzi ją przez `GET /confirms/{dealReference}`.

## Zabezpieczenia

- Tylko klient API z `environment=DEMO` i ściśle stały host
  `https://demo-api-capital.backend-capital.com`. Żadna ścieżka
  LIVE nie jest dostępna w nowym module.
- Sprawdzenie tożsamości `GET /session.accountId` przed każdym nowym
  zleceniem i blokada, jeśli US500 jest już otwarte.
- Nowe zlecenie wyłącznie z aktualnego, zapisanego testowego setupu
  `momentum_paper_test.active.status=PENDING` z zamkniętego M1,
  bez globalnych blokad. Zawsze stopLevel i profitLevel na serwerze brokera.
- Aktualny BID/ASK musi być świeży, instrument TRADEABLE, a odchylenie
  od sygnału małe.
- Maksymalnie **3 próby POST dziennie UTC** i jedno otwarte US500
  na rachunku DEMO.
- **Najpierw zapis ATTEMPTED w Supabase, dopiero potem POST /positions**.
  Gdy po POST wystąpi timeout lub restart, stan zostaje nierozstrzygnięty
  i moduł NIE PONAWIA zlecenia. Konieczna jest ręczna weryfikacja w
  Capital.com DEMO i naprawa stanu przez administratora.
- Potwierdzenie `GET /confirms/{dealReference}` jest wymagane; sam HTTP 200
  nie dowodzi otwarcia. Unikamy fałszywych znaczników OPEN.
- Zamknięcia SL/TP są obsługiwane przez BROKERA, a nie na podstawie świecy
  M1 i nie muszą mieć tego samego wyniku co niezależny PAPER TEST.
  Ten moduł **nie zamyka ręcznie po 20 minutach**; jeśli SL/TP nie zostanie
  uruchomione, pozycja może pozostać otwarta. Sprawdzaj DEMO.
- Na razie nie łączyć wyników broker DEMO z PAPER v3 ani SHADOW.

## Jak wyłączyć

Ustaw `FOKUS_DEMO_BROKER_MODE=OFF` i zrestartuj worker.
**Uwaga**: wyłączenie modułu nie zamyka otwartych już pozycji brokera DEMO.
Weryfikuj/zamykaj je bezpośrednio na rachunku testowym Capital.com.

## Jeżeli nie działa

- `WRONG_DEMO_ACCOUNT_ID`: niewłaściwy rachunek — nie ponawiam zlecenia.
- `US500_ALREADY_OPEN_AT_BROKER`: najpierw sprawdź otwarte pozycje DEMO.
- `DEMO_QUOTE_NOT_FRESH_TRADEABLE`: rynek lub cena niezweryfikowane.
- `BROKER_LONG_SL_TP_INVALID` / `BROKER_SHORT_SL_TP_INVALID`:
  SL/TP nie są po prawidłowej stronie ceny.
- `UNRESOLVED_NO_RETRY`: możliwy POST bez potwierdzenia — nie resetuj
  automatycznie. Ręcznie sprawdź DEMO, zanim cokolwiek ponownie uzbroisz.

Ten kod jest testowany offline. Testów integracyjnych na prawdziwym
rachunku Capital DEMO nie można przeprowadzić bez prywatnych poświadczeń
i wyraźnego uzbrojenia środowiska przez właściciela.
