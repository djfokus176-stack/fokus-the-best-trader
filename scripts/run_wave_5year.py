"""One-off five-year WAVE 2.0 historical study on original BID/ASK M15.

Runs offline in GitHub Actions or on Windows. No AUTO/worker/database writes.
Historical training/holdout is exploratory; it does NOT validate alpha.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from trader.wave_reversal_eval import read_wave_m15_csv
from trader.wave_intelligence2 import run_wave_abcd
from trader.wave_intelligence2_stats import (
    wave_pattern_ranking,wave_excursion_audit,feature_audit,
    hour_ranking,same_entries_exit_grid,
)


def run(csv_path:Path,output:Path,*,spread=2.,slippage=.25,
        rr=1.5,hold=120):
    csv_path=Path(csv_path)
    output=Path(output)
    # Input file must exist. These results cannot be generated from
    # previously aggregated 72/240 or 50/133 signals.
    if not csv_path.exists():
        raise FileNotFoundError(
            "BRAK DANYCH: wymagany pełny źródłowy CSV M15 BID+ASK")
    history=read_wave_m15_csv(csv_path,timestamp_convention="close")
    if len(history)<40000:
        raise ValueError(
            "WAVE 5Y: plik zawiera mniej niż 40000 świec M15; "
            "nie podpisuję go jako pięcioletniego backtestu.")
    quotes=("BidOpen","BidHigh","BidLow","BidClose",
            "AskOpen","AskHigh","AskLow","AskClose")
    if not all(c in history.columns for c in quotes):
        raise ValueError("WAVE 5Y: ten tryb wymaga pełnych 8 kolumn BID/ASK.")
    summary,log,meta=run_wave_abcd(
        history,spread=spread,slippage=slippage,
        rr=rr,hold_minutes=hold,split=.70)
    patterns=wave_pattern_ranking(summary)
    excursion,exc_detail=wave_excursion_audit(history,log)
    features=feature_audit(log)
    hours=hour_ranking(log)
    exit_grid,exit_trades=same_entries_exit_grid(
        history,log,split_cutoff=meta["oos_cutoff"],
        spread=spread,slippage=slippage)
    years=(summary.loc[summary.year.notna()]
           if not summary.empty else pd.DataFrame())
    output.mkdir(parents=True,exist_ok=True)
    files={
        "WAVE_5Y_RANKING.csv":patterns,
        "WAVE_5Y_TRADES_ABCD_WAIT.csv":log,
        "WAVE_5Y_YEARS.csv":years,
        "WAVE_5Y_PROBABILITIES.csv":excursion,
        "WAVE_5Y_PROBABILITY_EVENTS.csv":exc_detail,
        "WAVE_5Y_FEATURES.csv":features,
        "WAVE_5Y_HOURS.csv":hours,
        "WAVE_5Y_EXIT_GRID.csv":exit_grid,
        "WAVE_5Y_EXIT_TRADES.csv":exit_trades,
        "WAVE_5Y_SUMMARY_ALL.csv":summary,
    }
    for name,table in files.items():
        table.to_csv(output/name,index=False,encoding="utf-8-sig")
    with csv_path.open("rb") as f:
        sha=hashlib.file_digest(f,"sha256").hexdigest()
    manifest={
        "run":"5-year Dukascopy M15 BID+ASK, research-only",
        "input_sha256":sha,"input_rows":len(history),
        "input_first_utc":history.index[0].isoformat(),
        "input_last_utc":history.index[-1].isoformat(),
        "price_instrument":"Dukascopy usa500idxusd CFD",
        "risk":"SL=1.5×ATR, TP="+str(rr)+"R, "+str(hold)+"min, next M15 OPEN",
        "data_source":"true historical BID+ASK candle OHLC, not execution ticks",
        "slippage_each_side":slippage,
        "commission_in_model":"0; known broker commissions still unverified",
        "source_spread_assumption_ignored_when_bidask":True,
        "bars_without_filled_gaps":True,
        "waves_meta":meta,
        "verified_positive_out_of_sample_edge":False,
        "trading_permission":"WAIT",
        "caveat":(
            "70/30 exploratory split is not an untouched future sample after "
            "results are inspected. Candle OHLC cannot determine intrabar "
            "SL/TP sequence; stop-first is assumed. Historical BID/ASK from "
            "Dukascopy CFD differs from live Capital.com execution. "
            "No strategy is approved for broker orders."),
    }
    (output/"WAVE_5Y_MANIFEST.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2,default=str),
        encoding="utf-8")
    print(f"RESEARCH COMPLETE: {len(history)} M15, "
          f"{meta.get('anchors',0)} third-wave anchors; "
          f"files={len(files)}; status=WAIT, no verified edge")
    return manifest


def main():
    parser=argparse.ArgumentParser(description="Research-only 5yr BID ASK M15 WAVE A–E")
    parser.add_argument("--csv",type=Path,required=True)
    parser.add_argument("--out",type=Path,default=Path("WAVE_5Y_RESULTS"))
    parser.add_argument("--slippage",type=float,default=.25)
    parser.add_argument("--rr",type=float,default=1.5)
    parser.add_argument("--hold",type=int,default=120)
    args=parser.parse_args()
    run(args.csv,args.out,slippage=args.slippage,rr=args.rr,hold=args.hold)


if __name__=="__main__":
    main()
