# FOKU$ — trzy głosy z Twoich nagrań ElevenLabs

**Folder docelowy na GitHubie:** `assets/voices/`

Trzy pliki przekazane przez właściciela:
- `long.mp3` → **`open_long.mp3`** — głos „Otwarcie long” wyłącznie po zdarzeniu `PAPER_OPEN` z pozycją LONG; zielona strzałka w górę.
- `short.mp3` → **`open_short.mp3`** — głos „Otwarcie short” wyłącznie po `PAPER_OPEN` z SHORT; czerwona strzałka w dół.
- `zamknij.mp3` → **`close.mp3`** — wspólny głos „Zamknij” po `PAPER_CLOSE_TP`, `PAPER_CLOSE_SL` albo `PAPER_TIMEOUT`; zielony kwadrat na wykresie i rzeczywisty wynik PAPER w punktach.

Uwaga: nie wystarczy wgrać archiwum ZIP jako pliku do repozytorium —
**rozpakuj** otrzymaną paczkę i przeciągnij do tego folderu trzy pliki
`open_long.mp3`, `open_short.mp3` i `close.mp3` (nie same ZIP).
Nazwy muszą zgadzać się dokładnie. W GitHub kliknij **Add file → Upload files**
oraz **Commit changes** na gałęzi `main`. W Streamlit po automatycznej
aktualizacji naciśnij Ctrl+Shift+R, włącz dźwięki PAPER, wybierz „Głos
ElevenLabs (nagrania MP3)” i użyj przycisku „PRZETESTUJ DŹWIĘK”.

**Ważne:** nagranie „Zamknij” brzmi jednakowo dla straty i zysku, ale
znacznik na wykresie wyświetla +/− punkty i powód zamknięcia.
W przyszłości można dodać osobne `close_profit.mp3`, `close_stop.mp3`,
`close_timeout.mp3`, które nadpiszą `close.mp3` dla odpowiednich zdarzeń.
Jeśli zabraknie głosu, odtwarzany jest ton WAV. Dodatkowe opcjonalne:
`move_stop.mp3` i `extend_target.mp3`.

Dźwięki są odtwarzane tylko dla *nowych zdarzeń rejestru PAPER*; pierwsze
otwarcie aplikacji nie odgrywa poprzedniej historii. Jeśli na tej samej
zamkniętej świecy powstają OPEN i CLOSE, grają kolejno przy następnych
odświeżeniach, bez nakładania nagrań. Player przeglądarki może zablokować
autoplay; kartę trzeba wcześniej aktywować.

PAPER to symulacja wykonania na danych zamkniętych świec, bez prawdziwych
zleceń i bez gwarancji ceny. **Wykres nie pokazuje historycznych strzałek
kandydatów**, a jedynie zarejestrowane pozycje PAPER.

Pliki MP3 są przechowywane w repozytorium; **jeśli repozytorium jest
publiczne, nagrania również będą publiczne**. Nie umieszczaj tutaj
sekretów ani kluczy API. Nie potrzeba ElevenLabs API do odtwarzania MP3.
