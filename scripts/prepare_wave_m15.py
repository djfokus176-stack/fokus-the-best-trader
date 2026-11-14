"""Merge original dukascopy-node m15 BID/ASK yearly CSV into one audited M15.

Original CLI timestamps are UNIX milliseconds at OPEN of candle; output Time
is explicitly UTC CLOSE (+15m), matching WAVE research importer. No ffill,
interpolation, alternate instruments, fake prices or volume. Requires exact
timestamp intersections and rejects mismatches by default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.wave_quote_qc import (CrossedQuoteError, inspect_and_quarantine_crossed)

EXPECTED_START=pd.Timestamp("2021-11-11",tz="UTC")
EXPECTED_END=pd.Timestamp("2026-11-11",tz="UTC")
FIELDS=("open","high","low","close")


def _source(path):
    df=pd.read_csv(path)
    required={"timestamp",*FIELDS}
    if not required.issubset(df.columns):
        raise ValueError(f"{path.name}: brak timestamp/open/high/low/close")
    if df.empty:
        raise ValueError(f"{path.name}: pusty CSV")
    stamp=pd.to_numeric(df["timestamp"],errors="raise")
    if stamp.isna().any() or stamp.min()<1e12 or stamp.max()>1e14:
        raise ValueError(f"{path.name}: oczekiwano UNIX MILLISECONDS")
    if not (stamp%900000==0).all():
        raise ValueError(f"{path.name}: znaczniki nie są OPEN M15 UTC")
    if stamp.duplicated().any() or not stamp.is_monotonic_increasing:
        raise ValueError(f"{path.name}: zduplikowane lub niechronologiczne czasy")
    for c in FIELDS:
        df[c]=pd.to_numeric(df[c],errors="raise")
    prices=df[list(FIELDS)].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices<=0).any():
        raise ValueError(f"{path.name}: puste/niepoprawne ceny")
    if ((df["high"]<df[list(FIELDS)].max(axis=1)).any() or
        (df["low"]>df[list(FIELDS)].min(axis=1)).any()):
        raise ValueError(f"{path.name}: niespójne OHLC")
    if "volume" in df:
        v=pd.to_numeric(df["volume"],errors="raise")
        if v.isna().any() or (v<0).any() or not np.isfinite(v).all():
            raise ValueError(f"{path.name}: uszkodzony wolumen")
    return df[[c for c in ("timestamp",*FIELDS,"volume") if c in df]].copy()


def _load_side(folder,side):
    files=sorted(folder.glob(f"usa500_m15_{side}_*.csv"))
    if len(files)!=5:
        raise ValueError(f"Wymagane 5 rocznych plików M15 {side}, znaleziono {len(files)}")
    chunks=[_source(p) for p in files]
    joined=pd.concat(chunks,ignore_index=True).sort_values("timestamp")
    if joined.timestamp.duplicated().any():
        raise ValueError(f"Uwaga: duplikaty pomiędzy fragmentami {side}")
    hashes={}
    for p in files:
        with p.open("rb") as f:
            h=hashlib.file_digest(f,"sha256")
        hashes[p.name]=h.hexdigest()
    return joined,hashes


def merge_bid_ask(folder:Path, *, crossed_max_fraction=0., crossed_max_points=0.):
    folder=Path(folder)
    bid,bhash=_load_side(folder,"bid")
    ask,ahash=_load_side(folder,"ask")
    bid_ts=set(bid.timestamp)
    ask_ts=set(ask.timestamp)
    miss_bid=len(ask_ts-bid_ts)
    miss_ask=len(bid_ts-ask_ts)
    if miss_bid or miss_ask:
        raise ValueError(
            f"BID/ASK nie zgadzają się: {miss_bid} świec bez BID i "
            f"{miss_ask} bez ASK. Nie uzupełniam luk przyszłymi cenami.")
    rows=bid.merge(ask,on="timestamp",how="inner",suffixes=("Bid","Ask"),
                   validate="one_to_one").sort_values("timestamp")
    if rows.empty:
        raise ValueError("Nie znaleziono wspólnych świec BID i ASK")
    # Forensic QC: by default ANY meaningful ASK<BID fails. A caller may
    # explicitly quarantine a tiny bounded fraction of entire candles.
    # Holes stay as real timestamp gaps, never filled by invented MID.
    rows,quality=inspect_and_quarantine_crossed(
        rows,max_fraction=crossed_max_fraction,
        max_cross_points=crossed_max_points)
    out=pd.DataFrame({
        "Time":pd.to_datetime(rows.timestamp,unit="ms",utc=True)+
               pd.Timedelta(minutes=15),
        **{fld.capitalize():(rows[f"{fld}Bid"]+rows[f"{fld}Ask"])/2
           for fld in FIELDS},
        **{side+fld.capitalize():rows[f"{fld}{side}"]
           for side in ("Bid","Ask") for fld in FIELDS},
        "Spread":rows["closeAsk"]-rows["closeBid"],
    })
    if "volumeBid" in rows:
        out["Volume"]=rows["volumeBid"]
    if out.Time.duplicated().any() or not out.Time.is_monotonic_increasing:
        raise ValueError("Duplikaty czasów M15 CLOSE")
    original_start=pd.to_datetime(rows.timestamp.iloc[0],unit="ms",utc=True)
    original_end=pd.to_datetime(rows.timestamp.iloc[-1],unit="ms",utc=True)
    # This audit should NEVER fake missing candles or assert calendar coverage
    # on weekends and US-market holidays.
    coverage={
        "source":"dukascopy-node usa500idxusd BID+ASK CFD",
        "source_timestamp":"UNIX milliseconds, M15 OPEN UTC",
        "output_timestamp":"Time = M15 CLOSE UTC (+15 minutes)",
        "start_open_utc":str(original_start),"end_open_utc":str(original_end),
        "requested_start_utc":str(EXPECTED_START),
        "requested_end_exclusive_utc":str(EXPECTED_END),
        "full_requested_dates":bool(original_start<=EXPECTED_START and
                                     original_end>=EXPECTED_END-pd.Timedelta(days=2)),
        "n_bars":len(out),
        "n_bid":len(bid),"n_ask":len(ask),
        "n_timestamp_mismatches":0,
        "rows_by_year":{str(k):int(v) for k,v in
                        out.Time.dt.year.value_counts().sort_index().items()},
        "bid_sha256":bhash,"ask_sha256":ahash,
        "instrument_warning":"CFD, not ES future or S&P500 cash",
        "volume_warning":"Dukascopy volume is feed activity, not CME ES volume",
        "no_gap_filling":True,"holidays_verified":False,
        "quote_quality":quality,
    }
    return out,coverage


def main():
    a=argparse.ArgumentParser(description="Strict five-year M15 BID+ASK audit merger")
    a.add_argument("--folder",type=Path,required=True)
    a.add_argument("--out",type=Path,default=Path("FOKUS_WAVE_M15_5_LAT_BID_ASK.csv"))
    a.add_argument("--crossed-max-fraction",type=float,default=0.,
                   help="Explicit maximum fraction of M15 bars to QUARANTINE, "
                        "not correct; e.g. 0.001 = 0.1 percent.")
    a.add_argument("--crossed-max-points",type=float,default=0.,
                   help="Explicit maximum crossed BID/ASK magnitude in points.")
    args=a.parse_args()
    try:
        data,report=merge_bid_ask(
            args.folder,crossed_max_fraction=args.crossed_max_fraction,
            crossed_max_points=args.crossed_max_points)
    except CrossedQuoteError as exc:
        # A failed five-year run still publishes actual-count diagnostics,
        # avoiding another blind 25-minute re-download.
        outpath=args.out.with_suffix(".quality.json")
        outpath.parent.mkdir(parents=True,exist_ok=True)
        outpath.write_text(
            json.dumps(exc.report,ensure_ascii=False,indent=2),
            encoding="utf-8")
        print("WAVE DATA QUALITY FAILED: "+str(exc),flush=True)
        print("QUOTE_QC_REPORT="+str(outpath),flush=True)
        raise SystemExit(2) from None
    args.out.parent.mkdir(parents=True,exist_ok=True)
    data.to_csv(args.out,index=False,date_format="%Y-%m-%dT%H:%M:%S%z")
    report_path=args.out.with_suffix(".audit.json")
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),
                           encoding="utf-8")
    # Keep a standalone QC manifest for clear year-by-year crossed bars.
    args.out.with_suffix(".quality.json").write_text(
        json.dumps(report["quote_quality"],ensure_ascii=False,indent=2),
        encoding="utf-8")
    print(f"Zapisano {len(data)} rzeczywistych M15 BID+ASK -> {args.out}")
    print(f"Kontrola pochodzenia/czasów i kompletności -> {report_path}")
    if not report["full_requested_dates"]:
        print("UWAGA: zakres nie pokrywa całego żądanego okresu!")


if __name__=="__main__":
    main()
