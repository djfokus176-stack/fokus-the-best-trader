# FOKU$ AUTO — automatyczny handel na niby

W trybie `AUTO — 6 STRATEGII` bot sam analizuje, zakłada wirtualne
`PENDING → OPEN`, monitoruje SL/TP/limit czasu i rozlicza wynik do
istniejącego archiwum w punktach. Nie kupuje na rachunku brokera.

20.11.2026 z pliku z archiwum: +1,10, −13,95 i −11,27 pkt.
Zamknięcie o 02:00 czasu polskiego powodowało maksymalne dzienne
obsunięcie 25,22 pkt. Stary wirtualny dzienny hamulec domyślnie wynosił
20 pkt, więc mógł blokować każdą kolejną zatwierdzoną pozycję AUTO.
Zielone `SCAN_STATE=OK` przy `WAIT` nie dowodziło braku dziennego stopu,
ponieważ stary warunek obliczał stop dopiero przy kandydacie LONG/SHORT.

## Naprawa

Dla wirtualnego `AUTO — 6 STRATEGII` dzienny hamulec wyników jest
teraz **domyślnie wyłączony**, nawet jeśli poprzednio ustawiono zmienną
`FOKUS_PAPER_DAILY_STOP_PTS=20`. Pozwala to kontynuować badanie wyników
zamiast przerywać dzień po kilku przegranych symulacjach.

Nie zmieniono i nie wyłączono: danych Capital.com, jakości świec,
sprawdzania spreadu, 4 interwałów MTF, godzin rynku, blokad makro,
reguł wyboru strategii, SL/TP/TIMEOUT, ochrony przed duplikatami ani
istniejącej historii. Nadal `WAIT` może oznaczać brak poprawnego sygnału.

Aby przywrócić dzienny hamulec dla AUTO, trzeba świadomie dodać na
workerze `FOKUS_AUTO_VIRTUAL_DAILY_BRAKE_ENABLED=true`.
Pozostałe tryby poza AUTO zachowują dotychczasowe ustawienie
`FOKUS_PAPER_DAILY_STOP_PTS`.

Nowa kontrola wypisuje `AUTO_DAILY_BRAKE=OFF/ON`,
`LAST_DECISION=WAIT/LONG/SHORT`, `LAST_GATES` i `LAST_QUEUED`,
pozwalając rozróżnić brak sygnału od blokady. Nowe wirtualne transakcje
mogą pojawić się tylko, gdy sama strategia zatwierdzi LONG lub SHORT.
