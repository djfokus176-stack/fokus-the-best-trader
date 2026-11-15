# FOKU$ — kolejność strategii i dokładna metoda wejścia PAPER

## Co widzi właściciel

**1. AUTO — 6 STRATEGII** jest zawsze pierwszą i domyślną pozycją menu Streamlit.
Pozostałe pozycje to **priorytet prezentacyjny do badań**, a NIE ranking
udowodnionej skuteczności ani zmiana silnika AUTO:

2. BREAKOUT RETEST
3. VOLATILITY BREAKOUT
4. EMA PULLBACK
5. LIQUIDITY SWEEP
6. DRUGA FALA
7. EMA TREND
8. EMA50 WAVE (porównanie)

Właściciel dostarczył osobne 5-letnie badanie **23 innych wariantów M15
(Dukascopy BID, 2021–2026)**. W tym badaniu żaden wariant nie dał dodatniego
wyniku łącznego przy założonym koszcie 2 pkt; nie można automatycznie
porównać ich wyników z sześcioma metodami AUTO ani zastosować rankingu
jako reguły wybierania transakcji. Dane 2025–26 nie są w pełni świeżym
testem OOS. Nie importować arkusza do egzekucji.

## Jak pokazywana jest metoda

- Dla **bieżącego kandydata AUTO**: `LONG | AUTO → EMA PULLBACK`.
  To nadal tylko kandydat, **nie** pozycja.
- Dla **pozycji PAPER OPEN**: `OPEN | LONG | AUTO → EMA PULLBACK`.
  Metoda pochodzi z `paper_positions_v3.strategy`, a tryb AUTO jest
  potwierdzony tekstem `AUTO PAPER (eksperyment 1 sygnału)` w oryginalnym
  `setup_reason`. Nie wolno dopisać „AUTO” na podstawie aktualnego menu.
- Dla trybu pojedynczego i historycznego wpisu bez dowodu: `METODA: EMA TREND`,
  tryb `NIEUSTALONY / POJEDYNCZY`, aby nie przypisywać fałszywie AUTO.
- W **CLOUD M15** rysowane są tylko zdarzenia OPEN/CLOSED z istniejącego
  checkpointu, również pozycje pochodzące z M1 (opis zawiera dokładny TF,
  ID, punkt otwarcia/wyjścia i modelowy P&L). Nie są to nowe sygnały ani
  wypełnienia zleceń przez brokera.
- Dziennik CSV ma dodatkowe kolumny `tryb_sygnalu`, `wybrana_metoda`,
  `opis_sygnalu`. Oryginalny `strategy` i ID transakcji pozostają.
- Worker oznacza osobno `CANDIDATE_METHOD` i `ACTIVE_METHOD`:
  bieżący kandydat może różnić się od metody istniejącej pozycji.

## Bez zmian w handlu

Nie zmieniono `evaluate_auto`, `select_approved`, `queue_paper`,
granic MTF, SL/TP, kosztów ani wartości sekretów. Ponieważ nazwę
metody da się odczytać z istniejącego archiwum, **nie ma migracji Supabase**.

Pomysł drugiego czatu `FOKU$ 3F` (trzy fale, filtr EMA21 i ATR)
jest osobną niezweryfikowaną hipotezą. Nie dodawać do AUTO i nie otwierać
PAPER bez osobnej implementacji RESEARCH, testów i danych OOS.

Przykłady w interfejsie nie oznaczają rzeczywistych transakcji.
