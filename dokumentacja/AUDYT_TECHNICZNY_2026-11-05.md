# Audyt FOKU$ THE BEST TRADER — 5 listopada 2026

## Zakres

Przegląd ścieżki danych i działania: `market.py` (Capital.com DEMO),
`runtime.py`, `mtf.py`, `strategies_pro.py`,
`auto_strategy.py`, `worker.py`, `remote_checkpoint.py`,
`paper_lifecycle.py`, `paper_reporting.py`, `paper_display.py`,
`chart_tracker.py`, `auto_ai.py`, `app.py`, harmonogram GitHub Actions,
testy integracyjne i nowo dodane testy regresyjne.

Nie należy mylić automatycznej kontroli poprawności kodu z faktycznym
testem skuteczności strategii na realnym feedzie; dokładny stan produkcyjny
zewnętrznych systemów wymaga oddzielnej obserwacji.

## Potwierdzone z wcześniejszego testu produkcyjnego

- 5.11.2026 pierwszy ręczny workflow zakończył się błędem SQLite
  `no such table: candle_history`; błąd naprawiono i przetestowano.
- Następny ręczny workflow zakończył się SUCCESS i zgłosił
  `CANDLES=1047`, `CLOUD_CHECKPOINT_VERSION=1`.
- Pierwszy skan dał `WAIT`, `QUEUE=NO`,
  `GATES=SETUPS_DISABLED,INCOMPLETE_MTF,MACRO_CALENDAR_UNAVAILABLE`.
- Panel RAPORTY pokazał `REMOTE PAPER: checkpoint version 1`,
  `SKIP_WAIT` i zero wywołań AI, brak zamkniętych PAPER.
- Nie jest to dowód działania skanera co pięć minut bez przerwy,
  dowód realnej analizy GPT, ani dowód osiągania zysków.

## Przyczyny obecnego braku zaakceptowanych transakcji

1. `FOKUS_CANDLE_TIME_CONFIRMED` pozostaje nieustawione.
   `capital_prices_as_close_times` zakłada etykiety OPEN, ale jawne
   potwierdzenie wymaga kolejnych obserwacji brokera. Bez tego
   nowe pozycje PAPER pozostają zablokowane.
2. AUTO wymaga >=2 zgodnych decyzji i braku choć jednego przeciwnego
   setupu; brak MTF M1/M5/M15/H1 daje WAIT.
3. BLS kalendarz publikacji musi działać; jego niedostępność blokuje
   wejścia. Nie usuwamy tego ograniczenia przy awarii API.
4. Po wykryciu `bid > ask` nowa poprawka pokazuje wykres z poprawnych
   świec, ale **blokuje zatwierdzony sygnał**, dopóki nie będzie
   kompletnego, czystego odczytu.

## Co dodano

- Radar surowych kandydatów i archiwum blokad; ich liczba jest
  niezależna od liczby transakcji PAPER.
- Szczegółowe wizualne znaczniki otwarć i zamknięć PAPER z czasem,
  ceną MID, statusem i modelem wyliczenia P&L netto.
- Dziennik wejść i wyjść także w terminalu; raporty z osobnym podziałem
  na strategie wyjścia `fixed` i `adaptive`.
- Opcjonalne alarmy dźwiękowe dla PAPER OPEN, SL, TP, timeoutu
  i zmian SL/TP; możliwość ręcznego testu bez fałszywego zlecenia.
- Eksperymentalny adaptive PAPER: trailing SL i runner TP po
  zamkniętej świecy; poziomy obowiązują dopiero na kolejnej świecy.
- Płatny GPT może skomentować odrzucony przez MTF surowy setup,
  jednocześnie wyraźnie oznaczając WAIT. Włączony tylko przy
  istniejącej konfiguracji API i z limitem wywołań.

## Rzeczy NIEZWERYFIKOWANE — nie nazywać ich zakończonymi testami

- Powtarzalność automatycznego harmonogramu GH schedule (nie tylko manual).
- Potwierdzenie zegara świec Capital.com, jakość danych M5/M15/H1
  przy różnych godzinach, awarie i ograniczenia API.
- Odbiór oficjalnego kalendarza BLS w zewnętrznym workerze i jego
  bezpieczny fallback po awarii (obecnie brak, WAIT).
- Działający odpłatny GPT na prawdziwym kluczu i jego faktura
  (dotąd jedynie testy kodu/mock, realny status SKIP_WAIT).
- Automatyczne odtwarzanie dźwięku na wszystkich przeglądarkach.
- Rentowność sześciu strategii oraz eksperymentalnego adaptive.
  Dla tego potrzebny jest walk-forward, podatki/opłaty i próbka.
- Dokładny rzeczywisty fill: PAPER używa rekonstrukcji po zamkniętej
  świecy, nie ma danych tickowych ani zleceń brokerowych.
- Trwała dostępność Supabase i Streamlit 24/7; w chmurze app jest
  tylko klientem odczytowym, worker pisze do bazy.

## Krytyczne warunki bezpiecznego testowania

- Nie wpisuj kluczy do logów lub czatu, nie zmieniaj LIVE na REAL trade.
- Nie przestawiaj zegara świec na `open` przed niezależną weryfikacją.
- Jeśli MTF lub BLS pokazują błędy, NIE próbuj usuwać blokad
  tylko po to, żeby LONG/SHORT pojawiały się częściej.
- Weryfikuj zdarzenia `PAPER_OPEN`, `PAPER_CLOSE_TP`,
  `PAPER_CLOSE_SL` i wersję checkpoint w bazie po każdym skanie.
- Dźwięk, strzałka i wiadomość GPT są wyłącznie powiadomieniami
  analitycznymi, nie dowodem wykonania zlecenia.
