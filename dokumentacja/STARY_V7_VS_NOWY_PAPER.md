# Analiza porównawcza: stary SP500 Master Edition v7.1 vs NOWY FOKU$ THE BEST TRADER

**Nie modyfikować starego programu.** Ten dokument i moduł EMA50 WAVE
należą wyłącznie do repozytorium `fokus-the-best-trader`.

## Co wynika z przesłanych przez użytkownika starych plików

Stary `app.py` w `detect_signals_and_waves()` sprawdza:
- EMA 9, 21, 50 i nachylenie EMA (3 zamknięte świece);
- RSI 14 i ATR 14, filtr konsolidacji;
- cztery formacje po każdej stronie (pinbar, engulfing, pullback EMA21,
  fala po przecięciu EMA9/21);
- HTF może ograniczyć kierunek, ale nie wymaga jednoczesnej zgody
  czterech interwałów ani dwóch niezależnych strategii;
- etykietę OPEN następnej świecy podczas *historycznego* replayu,
  która na żywo nie jest wcześniej znaną ceną wejścia.

Przesłane archiwum zawiera 322 wpisy (158 LONG, 164 SHORT), z czego
318 oznaczonych jako zakończone. Sygnały z replayu/archiwum NIE są
tożsame ze zleceniami potwierdzonymi przez Capital.com i nie stanowią
audytowanego testu rentowności. Stary kod nie jest tu importowany, kopiowany,
zastępowany ani uruchamiany.

## Czemu nowy bot nie pokazuje tej samej strzałki

W NOWYM programie:
1. AUTO wymaga dwóch zgodnych spośród 6 i odrzuca każdy konflikt.
2. MTF wymaga prawidłowych danych M1, M5, M15, H1 i potwierdzenia
   trendu przez co najmniej dwa wyższe interwały bez kierunku przeciwnego.
3. Nowe PAPER wymagają stanu TRADEABLE, zatwierdzenia sposobu oznaczania
   czasu świec Capital.com i obowiązkowego kalendarza makro.
4. W chmurze pozycje PAPER zapisuje niezależny worker GitHub Actions,
   który musi faktycznie działać. Sam widoczny Streamlit nie otwiera
   cloud pozycji.
5. Strzałki na wykresie nie mogą udawać wykonanych pozycji: tylko
   potwierdzone przez wewnętrzny ledger stany PAPER_OPEN/CLOSE.

## Co dodano wyłącznie do NOWEGO repozytorium

**`EMA50 WAVE (PORÓWNANIE)`** — niezależna, opcjonalna hipoteza na
ostatniej ZAMKNIĘTEJ świecy, inspirowana formacjami starej wersji.
Nie importuje starego archiwum, nie używa danych przyszłej świecy i
nie kopiuje historycznych P&L.

- Gdy użytkownik zostawia `AUTO — 6 STRATEGII`, nowy radar pokazuje
  osobno obserwację EMA50 WAVE (SHADOW), **bez zwiększania
  liczby głosów konsensusu AUTO** i bez otwarcia pozycji.
- Można wybrać wariant porównawczy w terminalu (wtedy widać jego
  własny LONG / SHORT / WAIT, nadal z filtrami).
- **Opcjonalny tryb workera**: GitHub → Settings → Secrets and variables
  → Actions → Variables → New repository variable:
  `FOKUS_PAPER_STRATEGY` = `EMA50 WAVE (PORÓWNANIE)`.
  Dopiero wtedy w następnym skanie worker może rozważać ten wariant
  zamiast AUTO; bez tej zmiennej pozostał stary tryb 6-strategii.

PAMIĘTAJ: wybór trybu NIE wyłącza żadnej blokady czasu świec,
MTF, kalendarza makro, poprawności OHLC ani spreadu.
`PAPER_OPEN` jest symulacją odtworzoną z zamknięcia kolejnej świecy,
a nie prawdziwym zleceniem czy opóźnionym oznaczeniem historycznej formacji.
Stary program nie zostaje zmieniony.

## Co sprawdzić przed testami

1. GitHub → Actions → `FOKU$ PAPER v4 - scheduled DEMO scan (optional)`.
   W sprawdzonej historii workflow na 5 listopada były jedynie
   dwa ręczne uruchomienia; **brak dowodu działania cyklicznego**.
   Sprawdź, czy harmonogram jest aktywny i pojawiają się zdarzenia
   `schedule` (nie tylko `workflow_dispatch`). Cron to best-effort.
2. W logu pracy szukaj `GATES=` oraz `QUEUE=`, potem
   `CLOUD_CHECKPOINT_VERSION=`. Jeśli `SETUPS_DISABLED`,
   zegar Capital.com musi zostać niezależnie sprawdzony;
   nie wpisuj `open` bez weryfikacji dwóch próbek z brokera.
3. `INCOMPLETE_MTF` → sprawdź diagnozy interwałów i realność
   odczytów. `MACRO_CALENDAR_UNAVAILABLE` → napraw oficjalne źródło
   (nie usuwaj całej blokady).
4. Testuj najpierw PAPER/DEMO, porównaj warianty na tym samym,
   przyszłym okresie out-of-sample i z kosztami. Więcej sygnałów
   nie oznacza większej przewagi ani wyższych zysków.
