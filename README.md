## ✅ AKTUALNY STAN — 9/10 LISTOPADA 2026 (PAPER DEMO, bez zleceń brokerskich)

**Źródłem prawdy jest `main`, nie archiwalne opisy v0.1/v3 niżej.**

### 10.11 — AUTO: przesłanki 0/3–3/3 oraz samouczenie SHADOW

- **TERMINAL → M1:** tabela sześciu nazwanych strategii pokazuje warunki
  1/3 kontekst, 2/3 sygnał wstępny, 3/3 pełen setup po MTF i globalnych
  blokadach. Wszystkie trzy etapy pochodzą z zamkniętych świec, nie z GPT.
  Nie jest to 33/66/100% szans ani sygnał kupna. Konflikt LONG/SHORT
  uniemożliwia 3/3. Brak danych i blokady nigdy nie są ukrywane.
- **WORKER:** zapisuje wynik 0/3–3/3 wraz z nazwą w checkpoint Supabase;
  `SETUP_PROGRESS` i `SIX_VOTES` są w logach Northflank. W RAPORTY jest
  odczyt ostatnich wartości; gdy świeca jest stara, nie udawaj LIVE.
- **NIEZALEŻNE SHADOW:** sześć strategii prowadzi osobne, przedkrokowe
  papierowe statystyki z nowo nadejścia kolejnych świec M1. Dopiero
  ZAMKNIĘTA następna świeca ujawnia retrospektywny OPEN; przy pominiętym
  interwale wynik unieważnia się, nie dopisuje fikcyjnych filli.
  Uwzględnione spread, poślizg oraz konserwatywne rozstrzygnięcie SL.
- **UCZENIE OGRANICZONE:** AUTO może przestawić priorytet *tylko jeśli*
  DWIE LUB WIĘCEJ już zatwierdzonych strategii mają KAŻDA co najmniej
  100 niezależnie zamkniętych SHADOW z dodatnim dolnym 95% oszacowaniem
  średniego R na ostatnich 30% wyników. Wcześniej MARKET DNA + RR
  pozostają bez zmian. Repeated holdout peeking nie jest niezależnym
  dowodem rentowności. Nigdy nie dostrajamy progów lub nie odblokowujemy
  przeciwnego sygnału / RR / MTF / broker status / BLS.
- **Nowy RANGE REJECTION:** siódma hipoteza badawcza na konsolidację.
  Jest w terminalu i archiwum RADAR jako SHADOW, lecz NIE w zbiorze
  sześciu strategii AUTO oraz NIE w egzekucji pozycji PAPER.
- Wykres w Streamlit i praca Northflank to osobne procesy. Do
  czytania checkpointów i nowych statystyk w Streamlit potrzebne są
  prywatne `FOKUS_SUPABASE_URL` i `FOKUS_SUPABASE_SECRET_KEY`
  w ustawieniach **Streamlit Cloud**. Nie wolno ich kopiować do GitHuba.
  Nie uruchamiaj drugiego zapisującego skanera z przeglądarki lub Actions.


Ostatni audyt kodu: 392 testy na Pythonie 3.11 i 3.12 po #43.

- **AUTO — 6 STRATEGII:** eksperymentalnie wystarcza 1 pełny sygnał po MTF
  przy zerowym konflikcie LONG/SHORT i wszystkich obowiązkowych bramkach.
  Nowy dobór metody (#43) rozpoznaje reżim rynku (trend, konsolidacja,
  kompresja, ekspansja, sweep/BOS), ale może wybrać TYLKO metodę, która
  już wyprodukowała poprawny setup. Wiele opcji: najpierw dopasowanie
  reżimu, następnie RR. Brak poprawnego setupu = WAIT.
- **Obserwacje na wykresie:** `OBSERWUJ LONG/SHORT` to wczesne,
  wyraźnie oddzielone hipotezy; NIE są wejściami PAPER ani brokerowymi.
- **Wybór nie jest wyuczony z zysków.** Ranking historycznych pozycji
  PAPER jest badawczy i ocenia tylko strategie faktycznie wybrane przez
  bot. Nie stanowi bezstronnego porównania wszystkich sześciu metod;
  nie ma potwierdzonej skuteczności i nie wolno jej wymyślać.
- **PAPER:** stany PENDING → OPEN → CLOSED* są zaimplementowane
  i testowane; ale nie potwierdzono ciągłego rzeczywistego cyklu
  na koncie użytkownika z pełnym dziennikiem wykonania.
- **Praca cykliczna:** GitHub Actions około co 5 min (best-effort,
  opt-in), skan w otwartej przeglądarce ~1 min, lokalny lub
  dedykowany host może uruchamiać pętlę ~65 s. **Bez
  działającego workera nie ma autonomicznego 24/7 M1.**
  Nie uruchamiaj jednocześnie dwóch niezależnych workerów.
- **Kalendarz BLS:** oficjalny odczyt, potem awaryjne sprawdzone
  źródło `data/macro_calendar_manual.json` gdy BLS zwraca HTTP 403;
  ręczna zweryfikowana kopia ważna tylko do
  **2026-11-16T20:00:00+00:00**. Po wygaśnięciu i braku oficjalnego
  odczytu nowe PAPER zostaje zablokowane. FED/BEA to dodatkowy
  **radar informacyjny**, a nie kompletny filtr veto FOMC/PCE.
- **Telegram CLOUD:** zdalne alerty nadal nie są gwarantowane /
  są wyłączone z powodu atomowej deduplikacji przy awarii.
  Opcjonalna analiza GPT jest komentarzem, nie sygnałem wejścia.

### Jutro: minimalna kontrola bez zmiany progów

1. W Streamlit wybierz DEMO, US500, M1 i `AUTO — 6 STRATEGII`.
   W sekcji STRATEGIE sprawdź
   `AUTO — SAM DOBIERAM METODĘ DO WARUNKÓW RYNKU`.
2. Sprawdź świeże M1/M5/M15/H1 oraz status TRADEABLE, potem
   `GATES=OK` w ostatnim SKANIE WORKERA (to osobny system od strony).
3. Jeśli `WAIT`, zobacz głosy `0/0`, `1/2`, `2/3`, powód
   i historyczny audyt ostatnich 20–40 zamkniętych M1.
4. W RAPORTY zweryfikuj `QUEUE`, `PENDING`, `OPEN`, `CLOSED_*`
   i rzeczywiste punkty **po modelowanych kosztach**.
5. Przed 16.11 ponownie zweryfikuj kalendarz BLS. Nie ustawiaj
   żadnej bramki na zielono ręcznie tylko po to, aby uruchomić LONG.

---
## ✅ AKTYWACJA 8.11.2026 — AUTO GPT + FED/BEA + PAPER (tylko DEMO)

Właściciel zlecił aktywację automatycznych analiz GPT oraz radaru FED/BEA. 
Po wdrożeniu workflow **domyślnie próbuje włączyć AUTO GPT**, ale wyłącznie gdy
GitHub Actions ma prywatny sekret `OPENAI_API_KEY`. Domyślne bezpieczne limity:
**6 wywołań dziennie i 60 miesięcznie**, model `gpt-5.4-mini`, komentarze
nie tylko do LONG/SHORT, ale także godzinowe WAIT. Nie jest to limit wydatków
w USD/PLN! ChatGPT Plus NIE opłaca OpenAI API.

**Jednorazowy wymóg właściciela, bez przesyłania mi klucza:**

1. GitHub → repo → Settings → Secrets and variables → Actions → Secrets:
   upewnij się, że istnieje `OPENAI_API_KEY` z oddzielnego konta OpenAI API.
   Bez sekretu bezpiecznie pozostaje **NOT_READY**, bez wywołań.
2. GitHub → Actions → Variables: jeżeli `FOKUS_AUTO_AI_ENABLED=false`, zmień
   na `true` (jawne `false` zawsze nadpisuje nowy domyślny tryb). Analogicznie
   inne zapisane wcześniej wartości limitów mają pierwszeństwo.
3. W Actions → `FOKU$ PAPER v4 - scheduled DEMO scan (optional)` →
   `Run workflow` zobacz komunikat `AUTO_GPT=READY` albo `NOT_READY`.
   Sam zielony workflow nie potwierdza odpowiedzi GPT: raport w
   Streamlit → RAPORTY → AUTO GPT zawiera rzeczywisty status `SUCCESS`.
4. Streamlit Cloud → app → Settings → Secrets: `CAPITAL_API_KEY`,
   `CAPITAL_IDENTIFIER`, `CAPITAL_PASSWORD`, `CAPITAL_ENV="DEMO"`.
   Jeśli wykres pokazuje HTTP 401, popraw sekrety; kod nie ma dostępu
   do prywatnych wartości. Do zdalnego podglądu PAPER w Streamlit
   potrzebne są **oba** `FOKUS_SUPABASE_URL` i
   `FOKUS_SUPABASE_SECRET_KEY`; wtedy panel automatycznie wybiera
   tryb wyłącznie do odczytu, o ile `FOKUS_REMOTE_VIEW_ENABLED` nie jest
   jawnie `false`.

**FED/BEA:** radar pobiera urzędowe daty FOMC, GDP, PCE, trade; zapisuje czas
pobrania i błędy do checkpointu. Zdarzenia są wysyłane jako KONTEKST do GPT,
nie generują zleceń ani nie usuwają obowiązkowej blokady BLS. Coverage jest
częściowe: brak źródła nie oznacza braku publikacji.

**Pozostałe ograniczenia:** GitHub cron nie zapewnia regularnej pracy co
5 minut, Streamlit nie aktualizuje wykresu przy zamkniętej przeglądarce,
pozycje PAPER nie są zleceniami Capital.com. Podczas zamkniętej giełdy
mogą nie pojawić się nowe komentarze GPT ani nowe prognozy.

---

## 🧠 Płatny GPT w osobnym workerze — opcjonalny, z limitami

Dodano bezpieczną integrację komentarzy GPT do skanów PAPER w GitHub Actions. Domyślnie **WYŁĄCZONA**, nie generuje opłat bez osobnego sekretu i opt-in. Model nie zmienia deterministycznych sygnałów ani żadnych blokad i nigdy nie wysyła zleceń REAL. Domyślne limity to 24 próby dziennie i 200 miesięcznie; nie są to limity kwotowe OpenAI. Historia i licznik pokazują się w panelu RAPORTY przy połączeniu Supabase.

Instrukcja konfiguracji: [dokumentacja/AUTO_GPT_WORKER.md](dokumentacja/AUTO_GPT_WORKER.md). ChatGPT Plus nie obejmuje API; rozliczenia w osobnym panelu OpenAI.

---

## 🤖 AUTO — 6 STRATEGII i 5-minutowy skan (PAPER, bez zleceń)

Domyślny tryb w terminalu: **AUTO — 6 STRATEGII**. Na dokładnie
tych samych zamkniętych świecach co wykres ocenia niezależnie:
DRUGA FALA, EMA TREND, LIQUIDITY SWEEP, BREAKOUT RETEST,
EMA PULLBACK i VOLATILITY BREAKOUT.

**Deterministyczny filtr badawczy:** co najmniej **1 sygnał**
LONG lub SHORT zatwierdzony po MTF, brak choćby jednego przeciwnego
surowego setupu i wszystkie aktualne M1/M5/M15/H1 oraz pozostałe bramki.
Brak tych warunków → **WAIT**, a tabela pokazuje sześć ocen i powody.
Gdy kilka zgodnych strategii pozostanie, bot wybiera deterministycznie
metodę najlepiej pasującą do aktualnego reżimu MARKET DNA,
a przy równym dopasowaniu po deklarowanym RR. To nie model ML,
nie udowodnione samouczenie, nie prawdopodobieństwo wygranej ani
automatyczne zlecenie brokerskie.

AUTO-SKAN interfejsu (zwykle około **60 sekund** dla zamkniętych M1;
szybsza cena LIVE co 5 s), wyłącznie przy otwartej
sesji przeglądarki Streamlit; historyczne strzałki AUTO są
przeliczeniem OHLC **bez pełnego historycznego MTF/makro** i nie
są rozliczonymi pozycjami. Osobny worker GitHub Actions też ma
harmonogram około 5 minut, ale jest opt-in i pozostaje
wyłączony bez konfiguracji właściciela. Przestój internetu,
Streamlit Cloud, GitHub Actions lub broker API oznacza brak
gwarancji pracy ciągłej. Telegram i automatyczne płatne wywołania
OpenAI są domyślnie wyłączone (GPT można jawnie włączyć w workerze z limitami).

**Bramka zegara API**: nowe pozycje PAPER nie są tworzone,
dopóki użytkownik nie potwierdzi OPEN-label timestampów
Capital.com w dwóch odczytach i wykresie brokera
(`FOKUS_CANDLE_TIME_CONFIRMED=open`). Nie ustawiaj w ciemno.

---

# 🚀 FOKU$ THE BEST TRADER — PAPER v4: przygotowana chmura (NIE AKTYWOWANA)

**Stan faktyczny:** do repozytorium dodano prywatny model bazy Supabase,
checkpoint PAPER w wersji CAS, archiwum zamkniętych OHLC, worker z odczytem
z chmury i zapisem po skanie, opcjonalny podgląd remote w Streamlit,
opcjonalny workflow GitHub Actions co około 5 minut oraz przycisk
diagnostyki czasu świec Capital.com.

**Ten opis pochodzi z początkowego wdrożenia.** W obecnych logach
potwierdzono poprawne zapisy checkpointu do Supabase, ale brak
gwarancji, że worker jest włączony nieprzerwanie. Stan Secrets
i bieżącego workera trzeba odczytać w działającym środowisku.
GitHub Actions wymaga `FOKUS_PAPER_WORKER_ENABLED=true` i Secrets;
zegar 5-minutowy jest best-effort, nie jest usługą 24/7 co minutę.

**Instrukcja jednorazowego uruchomienia:**
[dokumentacja/PAPER_V4_SETUP.md](dokumentacja/PAPER_V4_SETUP.md)

**Migracja SQL nowej, osobnej bazy:**
[dokumentacja/supabase_paper_v4.sql](dokumentacja/supabase_paper_v4.sql)

**Bezpieczeństwo:** bez realnych zleceń brokerskich, źródło DEMO,
tryb remote panelu tylko do odczytu, oddzielna archiwizacja danych,
blokada konfliktu wersji przy zapisie. Telegram cloud wyłączony,
ponieważ dotychczasowy mechanizm nie gwarantuje deduplikacji po crashu
pomiędzy wysłaniem a zapisem.

**Otwarte ryzyka:** brak potwierdzenia na prawdziwym Capital.com,
niezweryfikowana semantyka `snapshotTimeUTC`, brak wspólnego hostingu
i bazy dopóki właściciel nie skonfiguruje osobnego Supabase, limit
checkpointu JSON 2,5 MB. Testy syntetyczne ≠ dowód rentowności.

---

## 🧪 PAPER v3 — pozycja PENDING → OPEN → SL/TP/TIMEOUT

Dostępny nowy stan pozycji **tylko dla DEMO, wyłącznie PAPER**.
Bot czeka na ukończenie kolejnej świecy po sygnale i dopiero potem
**retrospektywnie** symuluje fill na jej OPEN. To nie jest natychmiastowe
zlecenie ani rzeczywista cena do wykonania. Pozycja przechodzi przez
`PENDING`, `OPEN`, `CLOSED_SL`, `CLOSED_TP`, `CLOSED_TIMEOUT` lub
`INVALIDATED`; przy lukach nie zgadujemy wyników. Na wykresie linie
ENTRY/SL/TP pojawiają się tylko dla pozycji w stanie `OPEN`.

W **RAPORTY** są dziennik zdarzeń, odrzucone WAIT, raporty dzienne i
tygodniowe. Powiadomienia Telegram to opcja:
`PAPER_TELEGRAM_ALERTS_ENABLED = true` w Streamlit Secrets oraz
`TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID`.
Alerty są wyłączone domyślnie. Deduplikacja ogranicza próby wysyłki do
jednej na event_id, ale może utracić wiadomość przy błędzie sieci.

**Pełny opis i ograniczenia:** [dokumentacja/PAPER_V3_LIFECYCLE.md](dokumentacja/PAPER_V3_LIFECYCLE.md).
**Powyższe historyczne ograniczenie dotyczyło etapu lokalnego SQLite.**
Aktualnie obsługiwany jest osobny trwały checkpoint Supabase, pod
warunkiem że użytkownik rzeczywiście podał prywatne Secrets.
GitHub cron nadal nie gwarantuje pracy 24/7; dedykowany
`trader.worker_service` może działać bez otwartej przeglądarki na
osobnym hoście. Nie uruchamiaj równoległych writerów.
Konwencja `snapshotTimeUTC` (czas OPEN czy CLOSE świecy) pozostaje
niepotwierdzona na rzeczywistym feedzie użytkownika.

**Poprawki audytu:** osobne linie ENTRY MID i modelowany fill BID/ASK,
`entry_assumed_utc` (teoretyczna godzina OPEN) i `entry_detected_utc`
(faktyczny czas wykrycia przez skaner), raporty z całej dostępnej historii
SQLite bez limitu 1000 rekordów. Telegram nadal tylko at-most-once attempt,
bez potwierdzonego delivery/retry. Nie testowano rzeczywistego konta API.

---

# 🚀 FOKU$ THE BEST TRADER — v0.3 MASTER RESEARCH

## Wygodne logowanie bez wpisywania hasła co chwilę

**Nowy tryb Google (zalecany):** natywne Streamlit `st.login()` z OIDC.
Po **jednorazowym** ustawieniu konta Google, Streamlit przechowuje własną
tożsamość w ciasteczku nawet do **30 dni** (nie jest to gwarancja, że
Google nigdy ponownie nie poprosi o uwierzytelnienie). W tym trybie
własne `APP_ACCESS_PASSWORD` nie jest wymagane podczas każdej wizyty.

**Co ustawić jednorazowo:**

1. W konsoli Google Cloud utwórz klienta OAuth typu **Web application**, a
   jako autoryzowany redirect URI dodaj dokładnie
   `https://fokus-the-best-trader.streamlit.app/oauth2callback`.
   Zapisz otrzymane identyfikatory klienta **wyłącznie w Streamlit Secrets**.
2. W Streamlit Cloud → My apps → Settings → Secrets dodaj lub popraw:
   ```toml
   APP_AUTH_MODE = "google"
   OWNER_EMAIL = "twoj_adres_google@example.com"
   AUTO_SCAN_DEFAULT = true

   [auth]
   redirect_uri = "https://fokus-the-best-trader.streamlit.app/oauth2callback"
   cookie_secret = "TWOJ_DLUGI_LOSOWY_SEKRET"
   client_id = "GOOGLE_CLIENT_ID"
   client_secret = "GOOGLE_CLIENT_SECRET"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```
   Zamień WSZYSTKIE przykładowe wartości. `OWNER_EMAIL` jest **wyłącznie jednym**
   zweryfikowanym adresem Google (żaden inny użytkownik Google nie wejdzie).
   `cookie_secret` musi być mocnym, losowym sekretem, innym niż hasło dostępu i klucze API.
3. Kliknij **Save / Reboot app**, a następnie **Wejdź przez Google**.
   Po zalogowaniu przy następnych wejściach aplikacja powinna rozpoznać
   właściciela automatycznie. **Wyloguj** usuwa ciasteczko.
4. Jeśli nie skonfigurowałeś Google, pozostaw `APP_AUTH_MODE = "password"`
   i istniejące `APP_ACCESS_PASSWORD`. Ten tryb zachowuje dostęp jedynie w
   aktualnej sesji, co może wymagać ponownego wpisania po zamknięciu przeglądarki.

**Ograniczenia:** utworzenie klienta Google OAuth i wpisanie jego danych
w Secrets to ręczny jednorazowy etap właściciela — ChatGPT nie posiada
jego identyfikatorów ani nie może ich bezpiecznie odgadnąć. Google OIDC
nie zostało przetestowane na prywatnym koncie właściciela. Tożsamość
przywracana jest w oparciu o Streamlit OIDC i może zostać wylogowana
wcześniej przez dostawcę lub przeglądarkę. Aplikacja nie przechowuje
kluczy API w ciasteczkach.

**Udogodnienia:** pola API są zwinięte; Secretów nie trzeba wpisywać
ponownie. `AUTO_SCAN_DEFAULT=true` włącza skanowanie po zalogowaniu
przy otwartej stronie, bez automatycznych płatnych zapytań do OpenAI.
To **nie** włącza działania 24/7 przy zamkniętej stronie.

---

## Aktualizacja 2026-11-04: właściciel + MARKET DNA (v0.2)

**Prywatność:** jeżeli kliknięto `Discard` w ustawieniach Sharing, zmiany dostępu NIE zostały zapisane. Aplikacja mogła pozostać publiczna. Aby korzystać z tego projektu, trzeba teraz **najpierw ustawić hasło do panelu** w Streamlit → My apps → Settings → Secrets:

```toml
APP_ACCESS_PASSWORD = "WPROWADZ_TUTAJ_DLUGIE_UNIKALNE_HASLO"
```

Wybierz własne hasło (minimum 12 znaków); nie używaj tego przykładu. Po zapisaniu Secrets wykonaj Reboot app. Na ekranie logowania wpisz hasło, a program pokaże 5 zakładek. Nie trzeba ponownie wpisywać Capital.com ani OpenAI, jeżeli są już w Secrets. Hasło pozostaje wyłącznie w Secrets. W aplikacji można użyć przycisku **WYLOGUJ Z TERMINALU**.

Bramka hasłowa chroni aplikację przed przypadkowym dostępem, ale **nie zastępuje dostępu ograniczonego przez platformę, profesjonalnego SSO ani serwerowego limitowania prób**. Gdy plan lub ustawienia na to pozwolą, zalecana jest również prywatna aplikacja i ograniczenie dostępu.

**Nowości badawcze:** osobna zakładka 🧬 MARKET DNA i poziomy potwierdzonych swing high/low na wykresie; rozpoznawanie HH/HL, LH/LL, reżimu trend/range/kompresja/ekspansja; hipotetyczne sweep i BOS bez użycia przyszłych świec. Moduł NIE zmienia decyzji LONG/SHORT/WAIT i nie wylicza niezweryfikowanych prawdopodobieństw.

**AUTO-SKAN:** opcjonalne pobieranie co 60/120/300 sekund wyłącznie podczas aktywnej sesji Streamlit. Nie jest to skaner 24/7. GPT-5.4 HIGH pozostaje ręczne i może generować koszty.

**Weryfikacja:** unit testy i smoke-test Streamlit przechodzą na GitHub Actions po bieżącym commicie; nie ma jeszcze zweryfikowanego wyniku PAPER na dużym zbiorze ani gwarancji działania streamingu.

---

**CAŁKOWICIE NOWY PROJEKT.** Nowe repo `fokus-the-best-trader`, nowe `app.py`, nowy moduł analityczny, nowe archiwum. ZERO integracji, push/pull czy użycia git remote `sp500-kolega-gemini`. Stary kod nie jest tu skopiowany.

## 🧪 Odtwarzalny CSV M1 — wpływ filtra MTF na 6 strategii

Dostępny w panelu **📈 RAPORTY → CSV M1 (OFFLINE)**. Porównuje sześć strategii
przy stałym spreadzie i poślizgu, w wariantach **bez MTF / z MTF**, na
chronologicznym podziale 70/30 **po** rozgrzewce 70 kompletnych godzin H1.
Wyższe interwały M5/M15/H1 są jawnie wyliczane z M1 z oznaczeniami
zamknięcia UTC (to nie są osobne szeregi Capital.com). Raport ma SHA256 CSV,
tabelę veto MTF i eksport pojedynczych symulacji. Nie jest to dowód zysków.

**Instrukcja formatu, wymagań i ograniczeń:** [dokumentacja/CSV_MTF_PAPER.md](dokumentacja/CSV_MTF_PAPER.md).

**Testy:** w CI uruchamiamy osobno Python 3.11 i Python 3.12. W lokalnym
środowisku niektóre ostrzeżenia NumPy/Streamlit mogą zależeć od innych
wersji bibliotek. Zmiana w `trader/chart_tracker.py` zastępuje
`pd.Timedelta` przez `datetime.timedelta` dla osi znacznika BOT.

---

## Audyt UX — cache strzałek i czat (5 listopada 2026)

- **Cache strzałek:** `trader/arrow_cache.py` używa Streamlit `st.cache_data`, z limitem 40 wpisów i TTL 30 min. Klucz obejmuje **całą zawartość** DataFrame zamkniętych świec oraz EPIC, źródło, TF, strategię i okno. Odświeżenie interfejsu bez zmiany danych może ponownie wykorzystać wynik; NOWA lub skorygowana świeca powoduje ponowne obliczenie. Nie gwarantujemy poprawy na wszystkich komputerach i rozmiarach historii.
- **Okno strzałek:** dokładnie **6 opcji**: 60, 90, 120, 180, 240, 350 zamkniętych świec. To nie jest płynny suwak. Tabela pod wykresem zawiera godziny, ceny MID i powody historycznych układów PAPER.
- **Znacznik BOT / CSV:** punkt na ostatniej potwierdzonej świecy `snap.frame.iloc[-1]`. `evaluate_snapshot` wycina najnowszą, mogącą się dopiero tworzyć świecę. CSV jest oznaczany jako **REPLAY**, nigdy LIVE. Jest test odczytu CSV i dokładnego timestampu znacznika.
- **GPT:** wybór `medium` (domyślny, limit 2400 output tokens, 45 s) lub `high` (4200 output tokens, 65 s). Pytanie maksymalnie 800 znaków. Rzeczywiste dane `usage.input_tokens/output_tokens` są dołączone do odpowiedzi, jeśli API je przekazuje. Nie pokazujemy wymyślonej kwoty kosztu — zależy od aktualnego cennika i warunków naliczania.
- **Historia czatu:** jest tylko w `st.session_state`. Przetrwa standardowy AUTO-SKAN/rerun aktywnej sesji, **NIE** jest trwała po przeładowaniu karty, ponownym logowaniu czy restarcie instancji. Nie zapisujemy automatycznie rozmów ani prywatnych danych do publicznego repo.
- **Testy CI:** używa akcji GitHuba kompatybilnych z Node 24. Poprawiono ostrzeżenie Pandas wynikające z typu kolumny w teście symulowanego przeskoku stop loss.
- **Czego nie sprawdzono:** płatnych odpowiedzi prawdziwego OpenAI, zachowania aplikacji w przeglądarce właściciela przez długi czas i realnej poprawy rentowności strategii.

## Audyt techniczny — poprawki PAPER v2 / 4 listopada 2026

- **Bilans PAPER:** poziomy SL/TP są interpretowane jako **MID**, a wejście/wyjście jako odpowiednio ASK/BID dla LONG i BID/ASK dla SHORT; poślizg jest liczony na obu końcach. Jeśli oba progi są dotknięte w tej samej świecy OHLC, konserwatywnie pierwszeństwo ma SL. Nie jest to egzekucja brokerska ani tick-by-tick.
- **Dwa spready:** `snap.spread` to spread z ostatniej zamkniętej świecy (dla setupu), a `snap.quote_spread` z najnowszego, potencjalnie niezakończonego baru (jako filtr warunków wykonania). Jeżeli którykolwiek przekroczy limit, nie wydajemy sygnału.
- **Trwała identyfikacja kosztu:** nowe kandydatury LONG/SHORT zapisują `entry_spread` na każdej transakcji PAPER. Późniejszy audyt używa zapisanego spreadu sygnału, nie spreadu z kolejnego skanowania. Historycznie zmienny spread wewnątrz transakcji nie jest jeszcze symulowany.
- **Oddzielne WAIT:** zapis `scan_decisions` zamiast `signals`; stare wpisy WAIT w `signals` pozostają w bazie, lecz są filtrowane z listy transakcji.
- **Zachowane wyniki historyczne:** starym `paper_outcomes` przypisywane jest `legacy_v1`. Nie usuwamy danych, ale nie liczymy ich do statystyk v2. Nie można ich rzetelnie przeliczyć bez oryginalnych świec i spreadów.
- **LIVE odblokowywane świadomie:** domyślnie wyłącznie DEMO. Aby udostępnić opcję read-only LIVE w panelu, właściciel może wpisać `CAPITAL_ALLOW_LIVE = true` w Streamlit Secrets.
- **Zależności:** przypięto **bezpośrednie** zależności w `requirements.txt` do wersji obserwowanych w GitHub Actions na Python 3.11. Wersje pośrednie nie są w pełni zablokowane.
- **Bezpieczeństwo:** aplikacja wymaga `APP_ACCESS_PASSWORD`. Nie jest to system SSO ani zaawansowana ochrona przed atakami brute-force.
- **NIE POTWIERDZONO:** pełnego działania z prawdziwymi kluczami Capital.com / OpenAI, poprawności historycznych statystyk na realnym rynku, stałej pracy 24/7 i wydajności w Streamlit Cloud.


## Archiwum: co rzeczywiście było w v0.1 (NIE bieżący stan)

- Streamlit + Plotly: świece M1/M5/M15/H1 i EMA9/21/50 z danych Capital.com DEMO REST (wymagają osobnych API), albo edukacyjny import CSV.
- Deterministyczne strategie badawcze `DRUGA FALA` i `EMA TREND`: LONG/SHORT/WAIT, geometria SL/TP, filtr spreadu, ATR, wsparcia/oporu.
- Zasada *ostatnia świeca nie jest pewna*: analiza na świecach, które mają już następną świecę; monitor wieku danych.
- Osobne archiwum zdarzeń i audyt późniejszych wyników PAPER w SQLite, deduplikacja ID. Historyczny, konserwatywny replay intrabar z kosztem spreadu i poślizgu.
- Opcjonalny asystent OpenAI objaśnia **te same numeryczne OHLC**, które widzisz na wykresie (to NIE jest AI analizujące screenshot).
- Samodzielny proces `worker` do uruchomienia na stale włączonym hoście (tylko PAPER). Żadnych metod do handlu brokerowego.

## Archiwum: czego nie było w v0.1 (NIE bieżący stan)

- Brak gwarantowanego live streaming/WebSocket i 24/7 hostingu. Streamlit Cloud nie służy jako worker stale działający.
- Brak wdrożonego WebSocket, kalendarza makro, źródeł news, Telegram alertów, walidowanego OOS/walk-forward czy automatycznej nauki AI.
- Brak podpiętej zewnętrznej trwałej bazy. Streamlit Cloud może resetować lokalny katalog SQLite.
- Żaden backtest na rzeczywistych danych użytkownika nie został ukończony. Nie ma znanej skuteczności ani podstaw do przejścia na REAL.
- Brak automatycznej egzekucji pozycji DEMO/REAL. Odczyt API DEMO/LIVE z wyborem środowiska, bez zleceń.

## Uruchomienie w Windows (PowerShell)

```powershell
cd fokus-the-best-trader
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
# Edytuj TYLKO lokalne secrets.toml. Plik jest w .gitignore
streamlit run app.py
```

Wymaga Python 3.11+ (preferowane 3.11–3.12). Bez API można użyć CSV z datą w UTC i kolumnami `Time,Open,High,Low,Close`.

Dla dodatkowego skanera PAPER w stale uruchomionej konsoli:

```powershell
$env:CAPITAL_API_KEY='...'
$env:CAPITAL_IDENTIFIER='...'
$env:CAPITAL_PASSWORD='...'
python -m trader.worker --once
# lub bez --once (dopóki proces działa)
python -m trader.worker --interval 65
```

**Uwaga:** skaner `worker` nie wysyła zleceń ani Telegramów; zapisuje kandydatów PAPER i WAIT. Lokalna baza działa na jednym hoście; dla wdrożenia cloud wymagany będzie Postgres/Supabase i prywatne sekrety.

## Streamlit Community Cloud — całkiem nowa aplikacja

1. Utwórz **nowe repo** na GitHubie o nazwie `fokus-the-best-trader` (najpierw puste, bez kopiowania starego repo).
2. Wgraj rozpakowane pliki ZIP do głównego katalogu tego nowego repo (bez lokalnego `secrets.toml`).
3. Wejdź na [share.streamlit.io](https://share.streamlit.io) -> **Create app** -> wybierz NOWE repo, plik `app.py`, branch `main`.
4. Secrets w panelu Streamlit: podaj swoje klucze Capital DEMO, ewentualnie OpenAI. Nie wklejaj kluczy do GitHuba ani do rozmowy.
5. Uruchom. Testuj wyświetlanie świec, ścieżkę WAIT i własny CSV. Brak kluczy = brak ceny, bez wymyślania notowań.

## Priorytety v0.2

1. Utrwalanie OHLC i PAPER w Postgres + watchdog niezależny od Streamlit.
2. Test na demo Capital.com weryfikujący znaczenie `snapshotTimeUTC` i zbieżność M1 / M5 / M15.
3. Wiarygodne news, kalendarz makro, blackout i Telegram, następnie OOS/walk-forward.
4. Rozszerzenie forward PAPER o partial TP/trailing, poślizg zależny od sesji i koszty. Nie zmieniać algorytmu po kilku stratach.

## Bezpieczeństwo

`.streamlit/secrets.toml`, `data/`, `.env` i tokeny są ignorowane przez Git. Nie ma żadnego `git remote`, workflow, zleceń brokerowych ani operacji na starym repo. Publiczny GitHub nie jest sejfem na API.

**Wygoda na Windows:** po pierwszej instalacji uruchom `start_windows.bat` (jeśli system Python/venv jest skonfigurowany). To uruchamia aplikację, a nie całodobowy skaner.