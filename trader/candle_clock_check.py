"""Owner-triggered DEMO read-only candle-time verification.

GitHub Actions -> "FOKUS DEMO — sprawdz czas swiec (tylko odczyt)"
-> Run workflow. Compare two consecutive CLOSED candles with Capital.com
DEMO terminal manually. Do NOT automatically enable setup gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import os
import time

from .market import CapitalReadOnly,FeedError


def observe(client, *, epic="US500", resolution="MINUTE",
            samples=2, delay_seconds=65, sleep=time.sleep,
            now=None, emit=print):
    if samples not in (1,2):
        raise ValueError("Zezwolono wyłącznie na 1 lub 2 próbki")
    now=now or (lambda:datetime.now(timezone.utc))
    observations=[]
    emit("DEMO READ-ONLY • nie są składane zlecenia ani odblokowywane pozycje")
    emit("snapshotTimeUTC może oznaczać OPEN lub CLOSE — wymaga porównania z terminalem")
    for i in range(samples):
        observed=now().astimezone(timezone.utc)
        labels=client.raw_candle_clock_labels(epic,resolution,count=8)
        # The newest bar may be forming; compare earlier, finished bars
        # with identical bars in the user's Capital.com DEMO terminal.
        latest=labels[-1]
        done=labels[-5:-1]
        emit(f"PRÓBA {i+1}/{samples} | serwer UTC (czas odczytu): {observed.isoformat()}")
        emit(f"Instrument: {epic} | TF: {resolution} | liczba etykiet API: {len(labels)}")
        for stamp in done:
            emit(" ZAKOŃCZONA (kandydat do porównania): "+stamp.isoformat())
        emit(" OSTATNIA, BYĆ MOŻE W TRAKCIE: "+latest.isoformat())
        observations.append({"observed_utc":observed,"labels":labels})
        if i+1<samples:
            sleep(delay_seconds)
    emit("WYNIK: porównaj dwie kolejne świece z DEMO terminalem. "
         "Jeżeli zgodne: potwierdź interpretację ręcznie. "
         "Ta diagnostyka NIE ustawia FOKUS_CANDLE_TIME_CONFIRMED.")
    return observations


def main(argv=None):
    parser=argparse.ArgumentParser(description="Capital.com DEMO clock check only")
    parser.add_argument("--epic",default=os.getenv("CAPITAL_EPIC","US500"))
    parser.add_argument("--samples",type=int,choices=[1,2],default=2)
    args=parser.parse_args(argv)
    try:
        client=CapitalReadOnly(
            os.environ.get("CAPITAL_API_KEY",""),
            os.environ.get("CAPITAL_IDENTIFIER",os.environ.get("CAPITAL_LOGIN","")),
            os.environ.get("CAPITAL_PASSWORD",""),
            environment="DEMO")
        observe(client,epic=args.epic,samples=args.samples)
    except (FeedError,ValueError) as exc:
        # This only prints sanitized diagnostic error, never credentials.
        parser.exit(1,f"BŁĄD WERYFIKACJI: {type(exc).__name__}: {str(exc)[:180]}\\n")


if __name__=="__main__":
    main()
