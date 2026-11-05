# FOKU$ — własne głosy z ElevenLabs

Ten folder jest docelową lokalizacją plików MP3 odtwarzanych w **FOKU$ THE BEST TRADER**.

## Dokładne nazwy (małe litery)

| Plik | Kiedy zagra | Tekst do wklejenia w ElevenLabs Text to Speech |
|---|---|---|
| `open_long.mp3` | PAPER_OPEN dla LONG | FOKUS. Otwarta symulowana pozycja LONG. |
| `open_short.mp3` | PAPER_OPEN dla SHORT | FOKUS. Otwarta symulowana pozycja SHORT. |
| `close_profit.mp3` | PAPER_CLOSE_TP | FOKUS. Pozycja testowa zamknięta. Take profit! |
| `close_stop.mp3` | PAPER_CLOSE_SL, także gdy trailing SL zamknął z zyskiem | FOKUS. Pozycja testowa zamknięta przez stop loss. |
| `close_timeout.mp3` | PAPER_TIMEOUT | FOKUS. Pozycja testowa zamknięta po limicie czasu. |
| `move_stop.mp3` | PAPER_TRAIL_SL | FOKUS. Przesunięto stop loss pozycji testowej. |
| `extend_target.mp3` | PAPER_EXTEND_TP | FOKUS. Podwyższono cel zysku pozycji testowej. |

**Wszystkie** pliki muszą mieć dokładnie rozszerzenie `.mp3` i nazwy
zgodne z tabelą (wielkość liter ma znaczenie). Zalecane krótkie nagrania
1–4 sekundy, poniżej 2 MiB każde. Dowolny model głosu ElevenLabs, do
którego użytkownik ma prawa/zgodę.

## Jak wgrać

1. W ElevenLabs otwórz Text to Speech, wybierz lektora, wklej jeden tekst
   z tabeli, wygeneruj audio i pobierz wynik jako **MP3**. Powtórz.
2. Zmień nazwy siedmiu pobranych plików dokładnie jak w tabeli.
3. Na GitHub w repozytorium `djfokus176-stack/fokus-the-best-trader`
   otwórz folder `assets/voices`, kliknij **Add file → Upload files**,
   przeciągnij pliki i zatwierdź **Commit changes**.
4. W Streamlit odśwież aplikację (Ctrl+Shift+R). W bocznym panelu włącz
   **DŹWIĘKI PAPER** i wybierz **Głos ElevenLabs (nagrania MP3)**.
   Wybierz typ dźwięku i przetestuj przyciskiem testowym.

Nagrania są wgrane do repozytorium. Jeśli repozytorium jest publiczne,
również nagrania stają się publiczne. **Nie przesyłaj tu kluczy ElevenLabs,
API, tokenów ani cudzych nagrań bez zgody.**

## Reguły bezpieczeństwa

- Nie jest potrzebny żaden token ElevenLabs. To lokalne, gotowe nagrania.
- Nagrania zastępują dźwięki tylko dla nowych zdarzeń PAPER w archiwum.
  Po pierwszym włączeniu aplikacja nie odtwarza starych alarmów.
- Gdy MP3 nie istnieje albo jest niepoprawny/za duży, program wraca
  automatycznie do dotychczasowego tonu WAV.
- Zdarzenie `PAPER_OPEN` jest rekonstrukcją z zamkniętej świecy,
  a nie zleceniem u brokera.
- Kwota/punkty P&L zmieniają się przy każdej transakcji. **Stały MP3
  nie potrafi przeczytać zmiennej liczby punktów**. Liczba pojawia się
  w tabeli i na wykresie. Dynamiczna mowa liczb wymaga oddzielnego
  rozwiązania (TTS przeglądarkowy albo płatny ElevenLabs API).
- Przeglądarka może zablokować autoplay; po kliknięciu testowym
  sprawdź głośność systemu i aktywną kartę.
