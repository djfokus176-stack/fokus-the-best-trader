# FOKU$ THE BEST TRADER — opcjonalny GPT dla workera PAPER

**Domyślnie wyłączony.** Samo wdrożenie tego kodu nie robi płatnych wywołań.
Dotyczy wyłącznie `djfokus176-stack/fokus-the-best-trader`, nigdy starego
`sp500-kolega-gemini`.

## Jak działa

Worker GitHub Actions odczytuje **zamknięte** świece Capital.com **DEMO**,
przelicza niezależnie sześć strategii AUTO i filtry MTF/makro. Dopiero
potem opcjonalnie pyta OpenAI o **krótki komentarz** do sygnału i blokad.
Odpowiedź jest zapisywana w dedykowanym checkpoint Supabase `auto_ai`
i pokazywana w **RAPORTY → PAPER v3 → AUTOMATYCZNY GPT**.

**GPT NIE podejmuje decyzji transakcyjnych**, nie omija blokad,
nie zmienia strategii, nie wysyła zleceń do Capital.com. Nie widzi
screenshotu ani wiadomości live: otrzymuje najnowsze OHLC DEMO,
zestawienie strategii, MTF i status blokad. Gdy dane są niepełne
lub rynek zamknięty, program nie dopisuje fikcyjnego sygnału.

## Uruchomienie — zrób to dopiero po skonfigurowaniu budżetu API

1. W **GitHub → repo `fokus-the-best-trader` → Settings →
   Secrets and variables → Actions → Secrets** dodaj
   **`OPENAI_API_KEY`** jako osobny sekret workera. Klucza nie wklejaj
   do kodu, README ani czatu. Sekret w **Streamlit Cloud** do ręcznego
   CZAT AI **nie jest automatycznie dostępny** w GitHub Actions.
2. W tym samym miejscu → **Variables**, po uruchomieniu worker PAPER
   wg `PAPER_V4_SETUP.md`, ustaw:
   - `FOKUS_AUTO_AI_ENABLED=true`
   - `FOKUS_AUTO_AI_MODEL=gpt-5.4-mini` (oszczędniejsza opcja)
   - `FOKUS_AUTO_AI_DAILY_LIMIT=24` (domyślnie maks. 24 próby/dobę)
   - `FOKUS_AUTO_AI_MONTHLY_LIMIT=200` (domyślnie maks. 200 prób/miesiąc)
   - `FOKUS_AUTO_AI_INCLUDE_WAIT=false` (domyślnie GPT nie jest wołany
     dla WAIT; zmiana na true dopuszcza maks. jedną ocenę WAIT/godzinę).
3. Ustaw też limity wydatków w panelu rozliczeń **OpenAI API** i sprawdź
   rachunek po kilku testach. **ChatGPT Plus nie obejmuje opłat API.**
4. Po pierwszym zakończonym skanie sprawdź checkpoint w aplikacji.
   `SUCCESS` i liczby zużytych tokenów potwierdzają odpowiedź modelu;
   `SKIP_WAIT` nie oznacza awarii. Brak logu oznacza m.in. wyłączony worker,
   niegotowy Supabase, brak danych czy brak wywołania GPT.

## Kontrola kosztów i ograniczenia

Model dostaje do 8 zamkniętych świec M1 oraz streszczenie maksymalnie
6 strategii i 4 TF. Limit odpowiedzi to **900 tokenów wyjścia**, tryb
`reasoning=low`, **bez automatycznych ponowień**. Każda próba jest
liczona do dziennych i miesięcznych limitów; informacja o użytych
tokenach jest widoczna w checkpoint. Dzienny limit maks. 288,
miesięczny maks. 8640 (po ręcznym zwiększeniu).

To są **limity liczby wywołań, nie gwarantowany limit kwotowy**.
Cena zależy od wybranego modelu, liczby tokenów, kursów walut i cennika.
Rachunek może też objąć żądanie zakończone błędem, jeśli dotarło do
serwera OpenAI. Awaria zapisu Supabase po odpowiedzi GPT może spowodować
ponowny rachunek przy kolejnej próbie. GitHub Actions może opóźnić
harmonogram. Zewnętrzne limity API i monitoring rozliczeń są konieczne.

**Zalecenie**: na start 24 analizy/dobę i 200/miesiąc. Pozwoli to
porównać jakość komentarzy i rzeczywiste zużycie przed zwiększaniem
limitów. Aby liczyć każde 5 minut bez pauzy, liczba prób może sięgać
8640/miesiąc, a cena rośnie proporcjonalnie. Skany regułowe AUTO działają
niezależnie od płatnych wywołań.
