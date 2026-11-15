# FOKU$ — niezależny watchdog zdalnego checkpointu

Status: **opcjonalny, NIEAKTYWNY bez opt-in**. Nie jest drugim workerem PAPER i nie wykonuje odczytów Capital.com.

## Zasada

GitHub Actions `.github/workflows/fokus-checkpoint-watchdog.yml` sprawdza co około 5 minut aktualność `meta.last_scan_utc` we wpisie `public.fokus_paper_checkpoint.main` na Supabase. Próg: 8 minut. Odczyt jest wykonywany prywatnym kluczem serwerowym; kod nie zapisuje rekordów, nie otwiera pozycji i nie włącza realnych zleceń.

## Aktywacja (jednorazowa, właściciel)

1. W repozytorium GitHub wejdź w **Settings → Secrets and variables → Actions**.
2. W **Secrets** potrzebne są istniejące `FOKUS_SUPABASE_URL` i `FOKUS_SUPABASE_SECRET_KEY`. **Nie udostępniaj ich w rozmowach, logach ani w Variables.**
3. W **Variables** utwórz `FOKUS_WATCHDOG_ENABLED` z wartością `true`.
4. W **Actions** wybierz workflow `FOKU$ WATCHDOG - remote PAPER checkpoint health (read-only)`, uruchom ręcznie `Run workflow` i sprawdź pierwszy wynik.

Nie dotykaj wartości `FOKUS_PAPER_EXECUTOR` ani aktualnego Northflank — watchdog jest odczytowy i nie konkuruje o zapis checkpointu.

## Interpretacja

- `RECENT_CHECKPOINT`: ostatni zapis ma maksymalnie 8 minut; **nie** dowodzi poprawności świec ani cen.
- `STALE_CHECKPOINT`: ostatni zapis jest starszy niż 8 minut. Workflow kończy się błędem.
- `CLOCK_SKEW`: zapis jest w przyszłości o ponad 2 minuty. Workflow kończy się błędem.
- `ERROR`: nie można zweryfikować bazy/formatu (np. brak uprawnień, niedostępność sieci). Workflow kończy się błędem.

**GitHub Actions nie gwarantuje wykonania dokładnie co 5 minut**. Błąd joba nie jest równoznaczny z dostarczeniem SMS/Telegram; powiadomienia GitHub należy ustawić osobno. Gdy Northflank zostanie świadomie wyłączony, watchdog zgłosi STALE — to zamierzone.

## Ograniczenia

To nie jest monitor poprawności świec, wyników, 5-sekundowego rynku ani brokerowego wykonania. To nie jest gwarancja 24/7. Przegląd sesji i osobny system alarmowania wymagają niezależnej weryfikacji.
