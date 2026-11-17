# FOKU$ — Capital.com DEMO WebSocket (tylko wykres)

## Dlaczego zmieniamy

17.11.2026 na działającym terminalu występował HTTP 429 i
"BROKER_M1_ONLY_UNVERIFIED_QUOTE", mimo bieżących brokerowych świec
REST /prices. W poprzednim modelu kilka interwałów, /markets i dodatkowy
wątek pobierały równolegle REST. Każdy niepotrzebny GET zwiększał obciążenie
wspólnego limitu Capital. Nowy transport odłącza cały REST quote sampler
od podglądu, pozostawiając REST dla niezależnych skanów zamkniętych świec
PAPER, analizy MTF i historii.

Oficjalne protokoły:
- wss://api-streaming-capital.backend-capital.com/connect
- marketData.subscribe → quote: bid, ofr, timestamp (UNIX ms)
- OHLCMarketData.subscribe → ohlc.event: MINUTE, MINUTE_5,
  MINUTE_15, HOUR. Gdy priceType=bid, to **BID**, nie MID.
- ping co ~240 sekund (wymagane minimum raz na 10 minut).

## Jeden login, zero transakcji

Istniejący scanner Capital.com DEMO nadal loguje się w dotychczasowy
sposób i odnawia CST/X-SECURITY-TOKEN. JEDEN wątek WebSocket pożycza
te tokeny; nie wykonuje POST /session, nie wysyła żadnych zleceń
i nie generuje sygnałów.

Wykres otrzymuje:
- M1, M5, M15, H1: brokerową OHLC BID, jeśli aktualna i dostarczona;
  w jej braku wyłącznie obserwowane wartości MID z rzeczywistych zdarzeń
  quote (nie muszą uwzględniać wszystkich ekstremów);
- M2: wyłącznie obserwowaną OHLC MID podczas formowania;
  historia M2 nadal powstaje tylko z dwóch kompletów CLOSED M1.
- Żaden streamingowy bar nie trafia do bazy zamkniętych świec, strategii,
  zamknięć PAPER, stop loss, target ani scoringu.

## Zgodność z istniejącą tabelą Supabase

W sql/fokus_live_quotes_setup.sql kolumna source ma CHECK wartości
"Capital.com DEMO REST". **Bez migracji SQL**, top-level source pozostaje
starym identyfikatorem kanonicznym brokera, ale ostatni JSON sample zawiera
"transport": "CAPITAL_WS_V1". Wyłącznie obecność tego markera plus
broker_status STREAMING_ACTIVE i świeży vendor timestamp pozwala
interfejsowi oznaczyć WebSocket jako aktywny. Na tymczasowym provider
OHLC w JSON widnieje faktyczny source "Capital.com DEMO WS".

Wszystko jest w jednej dotychczasowej tabeli (bez kluczy w przeglądarce).
Zapisy prywatnego cache co około 5 s, choć stream może dostarczać wiele
zdarzeń częściej. Stream nie znaczy, że cena zmienia się co 5 sekund.

## Awaria i bezpieczny powrót

FOKUS_CLOUD_QUOTE_TRANSPORT=websocket (domyślnie):
- zerwanie socketu → reconnect z backoffem 5–120 sekund;
- odrzucenie subskrypcji albo brak aktualizacji → status WAIT;
- brak danych → UI NIE rysuje fikcyjnych aktualnych świec;
- sam serwer PAPER nadal pobiera zamknięte świece przez REST;
- aplikacja nigdy nie uruchamia drugiej sesji Capital.com.

Jeśli WebSocket okaże się niedostępny z danej sieci/hostingu, można
świadomie cofnąć **wyłącznie transport podglądu** zmienną na:
FOKUS_CLOUD_QUOTE_TRANSPORT=rest
Wtedy dotychczasowy REST quote sampler powróci. Nie należy uruchamiać
równocześnie obu kolektorów.

## Weryfikacja po deployu

Na Northflank:
- worker musi wdrożyć najnowszy commit i zainstalować websocket-client.
- w checkpoint.meta.quote_pump.mode powinno widnieć CAPITAL_WS_STREAMING.
- status WS_QUOTE_SAVED, ostatni świeży zapis maksymalnie kilkanaście
  sekund temu, i rosnąca liczba zapisanych prawdziwych obserwacji.
- w Supabase fokus_live_quotes.samples[-1].transport = CAPITAL_WS_V1.
- M1/M5/M15/H1 pokazują ostatnią świecę BID, jeśli broker wyśle
  zdarzenie OHLC; w przeciwnym razie podgląd MID z obserwacji.
- M2 ma osobny niezamknięty bar z obserwacji MID.
- REST /prices nie jest już odpytywany przez widżet LIVE, tylko przez
  niezależny worker do badań i historii.
- błędy HTTP 429 nadal **mogą** pojawiać się z innych REST żądań workera,
  bo limit per user obejmuje także inne równoległe procesy.

Nie twierdź, że WebSocket już działa w produkcji, jeśli w logach i
danych Supabase nie potwierdzono rzeczywistych aktualizacji.

## Koszt

Capital.com dokumentuje WebSocket obok REST w istniejącym API; brak
w tej dokumentacji osobnej opłaty za uruchomienie strumienia.
Koszty hostingu Northflank i transferu Supabase pozostają niezależne.
