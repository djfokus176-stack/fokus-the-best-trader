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

from pathlib import Path
from zoneinfo import ZoneInfo

import json

import pandas as pd

from .market import CapitalReadOnly,FeedError,PERIOD

WARSAW=ZoneInfo("Europe/Warsaw")
PRICE_FIELDS=(("open","openPrice"),("high","highPrice"),("low","lowPrice"),("close","closePrice"))


def build_records(payload,*,resolution="MINUTE",now_utc=None):
    """Turn RAW Capital payload into auditable records. Never drops bad bars.

    Each record: raw stamp (UTC), Warsaw time (DST-aware), finished flag,
    in-progress flag, BID/ASK/MID OHLC and a 'crossed' flag when bid > ask.
    The label is NOT shifted here: interpretation (open vs close) is a manual
    comparison with the broker terminal.
    """
    if resolution not in PERIOD:
        raise ValueError("Nieobsługiwany interwał")
    step=PERIOD[resolution]
    now=pd.Timestamp(now_utc or pd.Timestamp.now(tz="UTC"))
    if now.tzinfo is None:
        now=now.tz_localize("UTC")
    items=payload.get("prices") if isinstance(payload,dict) else None
    if not isinstance(items,list):
        raise FeedError("Brak listy prices w odpowiedzi API")
    records=[]
    for item in items:
        if not isinstance(item,dict):
            records.append({"error":"NIEPRAWIDLOWY_REKORD"}); continue
        raw=item.get("snapshotTimeUTC")
        stamp=pd.to_datetime(raw,utc=True,errors="coerce") if raw else pd.NaT
        rec={"snapshotTimeUTC_raw":str(raw)[:40]}
        if pd.isna(stamp):
            rec["error"]="NIEPRAWIDLOWY_CZAS"; records.append(rec); continue
        rec["stamp_utc"]=stamp.isoformat()
        rec["stamp_warsaw"]=stamp.tz_convert(WARSAW).strftime("%Y-%m-%d %H:%M:%S %Z")
        end=stamp+pd.Timedelta(seconds=step)
        rec["finished"]=bool(end<=now)
        rec["in_progress"]=bool(stamp<=now<end)
        crossed=False
        for side in ("bid","ask","mid"):
            ohlc={}
            for name,key in PRICE_FIELDS:
                block=item.get(key) if isinstance(item.get(key),dict) else {}
                if side=="mid":
                    b,a=block.get("bid"),block.get("ask")
                    try:
                        val=(float(b)+float(a))/2
                    except (TypeError,ValueError):
                        val=None
                else:
                    try:
                        val=float(block.get(side))
                    except (TypeError,ValueError):
                        val=None
                ohlc[name]=val
            rec[side.upper()]=ohlc
        for name,key in PRICE_FIELDS:
            block=item.get(key) if isinstance(item.get(key),dict) else {}
            try:
                if float(block.get("bid"))>float(block.get("ask")):
                    crossed=True
            except (TypeError,ValueError):
                crossed=True
        rec["crossed_bid_gt_ask"]=crossed
        records.append(rec)
    good=[r for r in records if "stamp_utc" in r]
    good.sort(key=lambda r:r["stamp_utc"])
    return good


def summarize(records):
    finished=[r for r in records if r.get("finished")]
    return {
        "liczba_etykiet":len(records),
        "zakonczone_kandydaci":[r["stamp_utc"] for r in finished[-4:]],
        "w_trakcie":[r["stamp_utc"] for r in records if r.get("in_progress")],
        "wadliwe_crossed":[r["stamp_utc"] for r in records if r.get("crossed_bid_gt_ask")],
        "bledne_rekordy":sum(1 for r in records if "error" in r),
    }


def write_report(out_dir,*,epic,resolution,observations,payload_records_by_sample):
    """Write JSON + TXT report. Contains only times and prices, never secrets."""
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    doc={"epic":epic,"resolution":resolution,"read_only":True,
         "uwaga":"Etykiety NIE są przesunięte. Potwierdź OPEN/CLOSE ręcznie w terminalu.",
         "proby":payload_records_by_sample}
    (out/"clock_report.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["RAPORT ZEGARA ŚWIEC — Capital.com DEMO (tylko odczyt)",
           f"EPIC: {epic} | TF: {resolution}","Etykiety NIE są przesunięte.",""]
    for n,recs in enumerate(payload_records_by_sample,1):
        lines.append(f"--- PRÓBA {n} ---")
        for r in recs:
            if "error" in r:
                lines.append(f"  BŁĄD {r['error']} raw={r.get('snapshotTimeUTC_raw','')}")
                continue
            tag=("W TRAKCIE" if r["in_progress"] else "ZAKOŃCZONA" if r["finished"] else "?")
            flag=" CROSSED(bid>ask)" if r["crossed_bid_gt_ask"] else ""
            mid=r["MID"]
            lines.append(f"  {r['stamp_utc']} | PL {r['stamp_warsaw']} | {tag}{flag} | "
                         f"MID O={mid['open']} H={mid['high']} L={mid['low']} C={mid['close']}")
    (out/"clock_report.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return out/"clock_report.json", out/"clock_report.txt"


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


def run_report(client,*,epic="US500",resolution="MINUTE",samples=2,
               report_dir="clock-report",sleep=time.sleep,now=None,emit=print):
    """Two raw reads (~65 s apart), records with BID/ASK/MID, JSON+TXT report."""
    if samples not in (1,2):
        raise ValueError("Zezwolono wyłącznie na 1 lub 2 próbki")
    now=now or (lambda: datetime.now(timezone.utc))
    per_sample=[]
    emit("DEMO READ-ONLY • raport zegara • nie są składane zlecenia")
    for i in range(samples):
        observed=now().astimezone(timezone.utc)
        payload=client.raw_candle_payload(epic,resolution,count=8)
        recs=build_records(payload,resolution=resolution,now_utc=observed)
        per_sample.append(recs)
        emit(f"PRÓBA {i+1}/{samples} | odczyt UTC: {observed.isoformat()} | {summarize(recs)}")
        if i+1<samples:
            sleep(65)
    json_path,txt_path=write_report(report_dir,epic=epic,resolution=resolution,
                                    observations=None,payload_records_by_sample=per_sample)
    emit(f"RAPORT: {json_path} oraz {txt_path}")
    emit("WYNIK: ręcznie porównaj zakończone świece z terminalem. NIE ustawia FOKUS_CANDLE_TIME_CONFIRMED.")
    return per_sample


def main(argv=None):
    parser=argparse.ArgumentParser(description="Capital.com DEMO clock check only")
    parser.add_argument("--epic",default=os.getenv("CAPITAL_EPIC","US500"))
    parser.add_argument("--samples",type=int,choices=[1,2],default=2)
    parser.add_argument("--report-dir",default="",help="zapis raportu JSON/TXT (opcjonalnie)")
    args=parser.parse_args(argv)
    try:
        client=CapitalReadOnly(
            os.environ.get("CAPITAL_API_KEY",""),
            os.environ.get("CAPITAL_IDENTIFIER",os.environ.get("CAPITAL_LOGIN","")),
            os.environ.get("CAPITAL_PASSWORD",""),
            environment="DEMO")
        if args.report_dir:
            run_report(client,epic=args.epic,samples=args.samples,report_dir=args.report_dir)
        else:
            observe(client,epic=args.epic,samples=args.samples)
    except (FeedError,ValueError) as exc:
        # This only prints sanitized diagnostic error, never credentials.
        parser.exit(1,f"BŁĄD WERYFIKACJI: {type(exc).__name__}: {str(exc)[:180]}\n")


if __name__=="__main__":
    main()
