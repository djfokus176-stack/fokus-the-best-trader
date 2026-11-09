# SCALPING US500 — URUCHOMIENIE PAPER M1 NA WINDOWS (jedno okno)

**To skaner badawczy PAPER, a nie realizacja zleceń.** Ocenia nowe zamknięte
świece M1 po ok. 8 sekundach od granicy minuty, korzystając z istniejących
sześciu strategii i filtrów MTF/BLS. W `AUTO` próg testowy wynosi
1 zatwierdzony sygnał, bez konfliktu LONG/SHORT. Bot wybiera metodę
z zatwierdzonych setupów według reżimu rynku i dopiero potem RR.
Brak poprawnej formacji nadal daje WAIT. Prowadzi PENDING/OPEN/CLOSED na
hipotetycznych wypełnieniach, zapisanych w Supabase.

## Wybierz jeden tryb

**A. Chcesz teraz oglądać ceny i sygnały:** otwórz Streamlit
`https://fokus-the-best-trader.streamlit.app/` → TERMINAL, US500, M1,
AUTO — 6 STRATEGII → AUTO-SKAN włączony, odświeżanie ceny co 5 s.
W zakładce STRATEGIE zobacz `AUTO — SAM DOBIERAM METODĘ DO WARUNKÓW RYNKU`.
Kółka `OBSERWUJ LONG/SHORT` nie są transakcjami PAPER.
Sygnały przeliczane są co >=60 s, tylko przy otwartej stronie.
Nie oznacza to, że cloud PAPER ma proces pracujący w tle.

**B. Chcesz PAPER co minutę niezależnie od przeglądarki:** uruchom
`URUCHOM_SCALPING_M1_PAPER.bat` na swoim Windows. Potrzebujesz
Python 3.11/3.12, Internetu i **jednorazowo** zapisanych lokalnych kluczy.

### Pierwsze uruchomienie

1. Pobierz repozytorium ZIP z GitHub i rozpakuj do prywatnego folderu na PC.
   Nie przesyłaj folderu z sekretami innym osobom.
2. Jeżeli masz już w tym folderze `.streamlit/secrets.toml`, **nie wpisuj
   kluczy ponownie**. Program sam je wczyta, nie wyświetlając ich.
   Jeśli korzystałeś WYŁĄCZNIE ze Streamlit Cloud / GitHub Secrets:
   lokalny Python **nie ma prawa odczytać ich automatycznie**.
   Zapisz je jednorazowo w lokalnym `.streamlit/secrets.toml` lub
   dostarcz bezpiecznymi zmiennymi środowiskowymi. Nie commituj tego pliku.
3. W lokalnym `secrets.toml` są wymagane nazwy (wartości wstawiasz
   wyłącznie u siebie, NIE do czatu):

   ```toml
   CAPITAL_API_KEY = "..."
   CAPITAL_IDENTIFIER = "..."
   CAPITAL_PASSWORD = "..."
   CAPITAL_ENV = "DEMO"
   FOKUS_SUPABASE_URL = "https://...supabase.co"
   FOKUS_SUPABASE_SECRET_KEY = "..."
   FOKUS_PAPER_WORKER_ENABLED = true
   # Ustaw TYLKO po rzeczywistym potwierdzeniu zegara świec z brokerem:
   FOKUS_CANDLE_TIME_CONFIRMED = "open"
   # Opcjonalnie, bez domyślnego włączania płatnego API:
   # OPENAI_API_KEY = "..."
   # FOKUS_AUTO_AI_ENABLED = true
   ```

4. **Jeden writer:** przed uruchomieniem trybu na Windows WYŁĄCZ
   istniejące zadanie cron-job.org i zaplanowane skany GitHub Actions.
   W GitHub Actions możesz wyłączyć workflow w jego menu. Nie zmieniaj
   żadnych bramek bezpieczeństwa i nie kasuj Supabase.
   Dwa niezależne skanery mogłyby konkurować o jeden checkpoint.
5. Kliknij dwa razy `URUCHOM_SCALPING_M1_PAPER.bat`. Pierwsze uruchomienie
   założy środowisko .venv i zainstaluje biblioteki; kolejne starty
   wykorzystują to samo środowisko i te same lokalne Secrets.
6. Zostaw okno CMD uruchomione i nie usypiaj komputera. Aby zatrzymać,
   zamknij okno lub użyj Ctrl+C. Przeglądarka Streamlit może być
   zamknięta; trwałe PAPER jest zapisane w Supabase.
7. W logach oczekuj `CLOUD_CHECKPOINT_VERSION=...`; przy braku setupu
   `WAIT / QUEUE=NO` jest poprawnym wynikiem.

### Co będzie działało, a czego to NIE rozwiązuje

- Skanowanie **zamkniętych** świec M1 po ~8 sekundach od zmiany minuty,
  jeżeli API/komputer nadążają. Nie ma gwarancji punktualności.
- Kontrola sześciu strategii, MTF M1/M5/M15/H1, statusu Capital.com, BLS.
  `MACRO_CALENDAR_UNAVAILABLE` blokuje nowe wejścia; **bez obejścia**.
  Historyczny awaryjny snapshot BLS wygasa 2026-11-10 00:00 UTC.
  Po jego wygaśnięciu kod może użyć oddzielnej, ręcznie
  zweryfikowanej kopii z `data/macro_calendar_manual.json`,
  **tylko** po odrzuceniu obu oficjalnych kanałów HTTP 403.
  Jej ważność kończy się 2026-11-16 20:00 UTC. Po tej dacie
  ponownie zweryfikuj oficjalny harmonogram; przy braku danych
  nowe PAPER nadal jest blokowane.
  Sam BLS nie pokrywa wszystkich ogłoszeń FED/FOMC i BEA.
- Obecny domyślny sposób wyjścia: `fixed`, maksymalnie 20 świec M1.
  Adaptacyjny wariant istnieje osobno, ale nie jest potwierdzony na PAPER
  i nie jest automatycznie aktywowany.
- To **nie jest tickowy scalper/HFT**: cena LIVE na ekranie może odświeżać
  się co 5 sekund, ale decyzje i symulowane wyjścia zależą od świec M1.
  Nie otwiera prawdziwych zleceń.
- Gdy PC jest wyłączony, praca ustaje. Dla niezależnego działania bez PC
  trzeba uruchomić ten sam `python -m trader.worker_service` na stabilnym
  hoście z prywatnymi ustawieniami (może być płatny).

**Nigdy nie wklejaj haseł/tokenów do czatu ani do publicznego GitHuba.**

## Diagnostyka doboru strategii

Gdy rynek się rusza, ale AUTO ma `WAIT`, rozwiń w STRATEGIE
`DLACZEGO BRAK LONG/SHORT?`. Wybierz ostatnie 20–40 zamkniętych M1,
porównaj wszystkie sześć metod i starą v7.1 SHADOW. Licznik głosów
`1/2` to zatwierdzony jeden setup z dwóch wykrytych, NIE
prawdopodobieństwo 50%.

**Ważne:** aktualny automatyczny dobór to reguły dopasowania do rynku,
**nie** empiryczne uczenie na każdej przegranej. Wyniki pojedynczo
wybieranych pozycji PAPER nie tworzą bezstronnego rankingu wszystkich
strategii. Dalszy krok: oddzielne rozliczenie równoległych metod SHADOW
na identycznych świecach i kosztach, potem chronologiczny holdout.
