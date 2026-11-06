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
import math

import pandas as pd

from .market import CapitalReadOnly,FeedError,PERIOD

WARSAW=ZoneInfo("Europe/Warsaw")
PRICE_FIELDS=(("open","openPrice"),("high","highPrice"),("low","lowPrice"),("close","closePrice"))


def _finite_positive(value):
    """Invalid/missing prices cannot be classified as genuine BID>ASK."""
    try:
        v=float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def build_records(payload, *, resolution="MINUTE", now_utc=None):
    """Read-only audit preserving every bar, including malformed timestamps.

    The API timestamp is NEVER shifted. finished/in_progress refer to the
    hypothetical OPEN-label model, which still needs broker confirmation.
    """
    if resolution not in PERIOD:
        raise ValueError("Nieobsługiwany interwał")
    step=PERIOD[resolution]
    now=pd.Timestamp(now_utc) if now_utc is not None else pd.Timestamp.now(tz="UTC")
    if now.tzinfo is None:
        raise ValueError("Wymagany świadomy strefy czas UTC")
    now=now.tz_convert("UTC")
    items=payload.get("prices") if isinstance(payload,dict) else None
    if not isinstance(items,list):
        raise FeedError("Brak listy prices w odpowiedzi API")
    records=[]
    for idx,item in enumerate(items):
        if not isinstance(item,dict):
            records.append({"index":idx,"snapshotTimeUTC_raw":"",
                            "error":"NIEPRAWIDLOWY_REKORD"})
            continue
        raw=item.get("snapshotTimeUTC")
        rec={"index":idx,"snapshotTimeUTC_raw":str(raw)[:40] if raw is not None else ""}
        try:
            stamp=pd.to_datetime(raw,utc=True,errors="coerce") if raw else pd.NaT
        except (TypeError,ValueError,OverflowError):
            stamp=pd.NaT
        if pd.isna(stamp):
            rec["error"]="NIEPRAWIDLOWY_CZAS"
            records.append(rec)
            continue
        rec["stamp_utc"]=stamp.isoformat()
        rec["stamp_warsaw"]=stamp.tz_convert(WARSAW).strftime("%Y-%m-%d %H:%M:%S %Z")
        end=stamp+pd.Timedelta(seconds=step)
        rec["finished"]=bool(end<=now)
        rec["in_progress"]=bool(stamp<=now<end)
        rec["time_label_interpretation"]="NIEPOTWIERDZONA_OPEN_LUB_CLOSE"
        rec["status_if_open"]=("ZAKONCZONA" if rec["finished"]
                               else "W_TRAKCIE" if rec["in_progress"]
                               else "PRZYSZLA")
        invalid=[]
        crossed=[]
        prices={side:{} for side in ("BID","ASK","MID")}
        for name,key in PRICE_FIELDS:
            block=item.get(key) if isinstance(item.get(key),dict) else {}
            bid=_finite_positive(block.get("bid"))
            ask=_finite_positive(block.get("ask"))
            if bid is None or ask is None:
                invalid.append(name)
            elif bid>ask:
                crossed.append(name)
            prices["BID"][name]=bid
            prices["ASK"][name]=ask
            prices["MID"][name]=(bid+ask)/2 if bid is not None and ask is not None else None
        rec.update(prices)
        rec["crossed_bid_gt_ask"]=bool(crossed)
        rec["crossed_fields"]=crossed
        rec["invalid_price_fields"]=invalid
        if invalid:
            rec["error"]="BRAK_LUB_NIEPRAWIDLOWA_CENA"
        elif crossed:
            rec["error"]="CROSSED_BID_GT_ASK"
        records.append(rec)
    records.sort(key=lambda r:("stamp_utc" not in r,r.get("stamp_utc",""),r["index"]))
    return records


def summarize(records):
    finished=[r for r in records if r.get("finished")]
    return {
        "liczba_rekordow":len(records),
        "liczba_etykiet":sum("stamp_utc" in r for r in records),
        "zakonczone_kandydaci":[r["stamp_utc"] for r in finished[-4:]],
        "w_trakcie_jesli_open":[r["stamp_utc"] for r in records if r.get("in_progress")],
        "wadliwe_crossed":[r["stamp_utc"] for r in records if r.get("crossed_bid_gt_ask")],
        "bledne_rekordy":sum(1 for r in records if "error" in r),
    }


def write_report(out_dir, *, epic, resolution, observations, payload_records_by_sample):
    """Write only whitelisted OHLC/timestamps; never broker session JSON."""
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    note=("Etykiety NIE są przesunięte. 'ZAKOŃCZONA JEŚLI OPEN' nie "
          "potwierdza, że API używa czasu otwarcia. Porównaj BID/ASK/MID "
          "z dwiema świecami w Capital.com DEMO (M1).")
    doc={"epic":epic,"resolution":resolution,"read_only":True,
         "clock_confirmed":False,"uwaga":note,
         "sample_observed_utc":observations or [],
         "proby":payload_records_by_sample}
    jp=out/"clock_report.json"
    jp.write_text(json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    lines=["RAPORT ZEGARA ŚWIEC — Capital.com DEMO (tylko odczyt)",
           f"EPIC: {epic} | TF: {resolution}",note,""]
    for n,recs in enumerate(payload_records_by_sample,1):
        lines.append(f"--- PRÓBA {n} ---")
        if observations and n<=len(observations):
            lines.append("  MOMENT ODCZYTU UTC: "+str(observations[n-1]))
        for rec in recs:
            if "stamp_utc" not in rec:
                lines.append("  BŁĄD "+rec["error"]+" raw="+rec["snapshotTimeUTC_raw"])
                continue
            tag=("ZAKOŃCZONA JEŚLI OPEN" if rec["finished"]
                 else "W TRAKCIE JEŚLI OPEN" if rec["in_progress"]
                 else "PRZYSZŁA JEŚLI OPEN")
            flags=[]
            if rec["crossed_bid_gt_ask"]:
                flags.append("CROSSED(bid>ask):"+",".join(rec["crossed_fields"]))
            if rec["invalid_price_fields"]:
                flags.append("NIEPOPRAWNA CENA:"+",".join(rec["invalid_price_fields"]))
            lines.append(f"  {rec['stamp_utc']} | PL {rec['stamp_warsaw']} | {tag} "+" ".join(flags))
            for side in ("BID","ASK","MID"):
                d=rec[side]
                lines.append(f"    {side}: O={d['open']} H={d['high']} L={d['low']} C={d['close']}")
    tp=out/"clock_report.txt"
    tp.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return jp,tp


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
    sample_times=[]
    emit("DEMO READ-ONLY • raport zegara • nie są składane zlecenia")
    for i in range(samples):
        observed=now().astimezone(timezone.utc)
        payload=client.raw_candle_payload(epic,resolution,count=8)
        recs=build_records(payload,resolution=resolution,now_utc=observed)
        per_sample.append(recs)
        sample_times.append(observed.isoformat())
        emit(f"PRÓBA {i+1}/{samples} | odczyt UTC: {observed.isoformat()} | {summarize(recs)}")
        if i+1<samples:
            sleep(65)
    json_path,txt_path=write_report(report_dir,epic=epic,resolution=resolution,
                                    observations=sample_times,payload_records_by_sample=per_sample)
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
