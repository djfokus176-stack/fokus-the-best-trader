# FOKU$ — przygotowanie do sesji testowej PAPER (DEMO)

## Co zobaczysz w aplikacji

- **TERMINAL**: radar surowych LONG/SHORT z 6 strategii. Surowy setup
  (przed MTF) NIE jest zatwierdzonym sygnałem, wykonanym wejściem ani
  historycznym zyskiem. Brak sygnałów oznacza brak setupu.
- **TERMINAL → DZIENNIK WEJŚĆ I WYJŚĆ**: rzeczywiste stany programu PAPER
  PENDING, OPEN, CLOSED_SL, CLOSED_TP, CLOSED_TIMEOUT, INVALIDATED;
  cena MID, odtworzony fill po spreadzie i poślizgu, wynik w punktach.
- **Wykres**: trójkąty przy odtworzonym wejściu PAPER, symbole przy
  zamknięciu i wynik netto. Osobne historyczne strzałki to jedynie
  wyszukane formacje, nie transakcje.
- **RAPORTY → ARCHIWUM RADARU**: w Supabase checkpoint zapisywane są
  oceny na kolejnych zamkniętych świecach, wraz z blokadami.
- **🔔 DŹWIĘKI PAPER**: domyślnie wyłączone; włącz ręcznie w lewym
  panelu. Różne krótkie tony dla OPEN, CLOSE_TP, CLOSE_SL, TIMEOUT,
  podciągnięcia SL i wydłużenia TP. Dźwięki dotyczą dopiero nowych
  zdarzeń zapisanych w bazie po włączeniu, nie historii.
  Przeglądarki mogą blokować autoplay; testuj z aktywną kartą,
  włączonym dźwiękiem i po kliknięciu przełącznika. Brak dźwięku
  nie znaczy, że zabrakło pozycji w bazie.
  Własne nagrane komunikaty głosowe to oddzielna funkcja, nie została
  wdrożona (brak plików od użytkownika).

## PAPER adaptive — tylko eksperyment

Użytkownik może w GitHub → Settings → Secrets and variables → Actions →
**Variables** utworzyć:
`FOKUS_PAPER_EXIT_POLICY=adaptive`.

Wtedy tylko NOWE pozycje PAPER (po przejściu wszystkich rygorystycznych
filtrów) otrzymują eksperymentalny profil:
- po >= 1 R korzystnego ruchu **zamknięcia świecy**, SL przesuwa się
  w stronę pokrycia modelowanego spreadu i poślizgu;
- po >= 1.5 R, SL podąża za zamknięciem z odstępem 0.7 R;
- gdy na zamkniętej świecy korzystny ruch przekroczy 1.2 R,
  można zwiększyć cel z pierwotnego poziomu do maks. 2.8 R.
- najpierw rozliczane są dotknięcia starych SL/TP na aktualnej
  świecy, dopiero potem zmiana poziomów **na NASTĘPNĄ** świecę.
  Przy dotknięciu SL i TP na jednej świecy najpierw rozliczany jest SL.
- nie ma gwarancji pozytywnego wyniku. Przesunięcie SL poprawia
  ochronę zysków tylko w niektórych trajektoriach. Przed użyciem
  w handlu rzeczywistym konieczne są rozliczenia OOS i porównanie
  transakcji tych samych setupów w wersji FIXED oraz ADAPTIVE.

Bez tej zmiennej (domyślnie `fixed`) działa poprzedni, stały SL/TP.
Zasada jest zapisywana w każdej pozycji; zmiana zmiennej nie edytuje
pozycji istniejącej. `model_version` odróżnia warianty.

## Blokady, których nie znosimy

- Capital.com API działa tylko w DEMO i wyłącznie do odczytu.
- Przed nową pozycją PAPER nadal wymagane są prawidłowe zamknięte świece,
  potwierdzenie konwencji timestamp (`FOKUS_CANDLE_TIME_CONFIRMED=open`
  **dopiero po weryfikacji**), status TRADEABLE, MTF i kalendarz makro.
- Kandydaci w radarze pojawiają się mimo blokad, ale nie są
  dodawani do liczby rozegranych transakcji.
- W chmurze pojedynczy worker GitHub Actions jest autoratywnym writerem;
  Streamlit czyta dane, sam nie tworzy nowych remote PAPER trades.
- GitHub Actions schedule jest best effort ~5 min, nie gwarantuje
  sekundowej dokładności ani całodobowej niezawodności.
- Wyniki PAPER są modelowane z zamkniętych świec, spreadu i poślizgu.
  Nie ma danych tickowych i nie wiadomo, po jakiej cenie dałoby się
  faktycznie zrealizować wejście lub wyjście.
- Bez statystyki po większej liczbie prób nie mamy podstaw do
  stwierdzenia rentowności.

## Checklista testów przed sesją

1. W GitHub Actions potwierdź udany **scheduled** skan PAPER,
   a nie jedynie ręczny workflow.
2. W RAPORTY sprawdź aktualny checkpoint, makro/MTF diagnostykę
   i archiwum kandydatów.
3. W terminalu sprawdź prawidłowy EPIC i interwał.
4. Włącz dźwięki, odtwórz test syntetyczny w CI i sprawdź, czy
   realny nowy event PAPER wywołuje alarm (może wymagać kliknięcia
   playera przez ograniczenia przeglądarki).
5. Zanim zatwierdzisz zegar Capital.com, obejrzyj dwie kolejne
   surowe próbki LIVE BROKER DEMO z oznaczeniami otwarć i
   porównaj z wykresem platformy. Nie ustawiaj wartości na zgadywanie.

## Wykryte ograniczenia w obecnej implementacji

1. Radar nie jest modelem prognostycznym ani źródłem 'pewnych typów'.
2. MTF i BLS pozostają krytycznymi zależnościami; przy awarii WAIT.
3. Adaptacyjne wyjścia można oceniać dopiero po rozliczeniu próby
   i uczciwym porównaniu stałego vs adaptacyjnego wyjścia na tych
   samych świecach; efekt optymalizacji nie jest potwierdzony.
4. Browser odpytywanie co 5 s nie sprawia, że M1 zamyka się
   co 5 s, a częste REST API może podlegać limitowi.
