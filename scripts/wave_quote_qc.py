"""Forensic QC of historical Dukascopy BID/ASK M15 bars.

Quotes for separate sides are aggregated from ticks and can contain
crossed OHLC points. A crossed bar is NOT repaired: under an explicit,
strict quality budget it is removed entirely, leaving an observable M15
gap which research engines must invalidate. Any excess aborts the run
with full diagnostic details. No synthetic spread or price is substituted.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite

import numpy as np
import pandas as pd

FIELDS=("open","high","low","close")
MIN_SIGNIFICANT_CROSS=1e-8


class CrossedQuoteError(ValueError):
    def __init__(self,message,report):
        super().__init__(message)
        self.report=report


def inspect_and_quarantine_crossed(rows:pd.DataFrame, *,
                                   max_fraction:float=0.0,
                                   max_cross_points:float=0.0):
    """Return (valid input rows, full human-auditable QC report).

    Default is STRICT and fails at any crossed quote. A *deliberately
    explicit* nonzero cap quarantines a small, bounded number of whole
    M15 candles without fabricating prices or reordering series.
    """
    if (not isfinite(float(max_fraction)) or
        not 0<=float(max_fraction)<=0.01):
        raise ValueError("Limit crossed quotes musi być w zakresie 0..1%")
    if (not isfinite(float(max_cross_points)) or
        not 0<=float(max_cross_points)<=5.):
        raise ValueError("Maksymalne crossing points musi być w zakresie 0..5")
    n=len(rows)
    if not n:
        raise ValueError("Brak zgodnych timestampów BID+ASK")
    bad=np.zeros(n,dtype=bool)
    per_field={}
    worst=0.0
    first_field=None
    crosses={}
    for field in FIELDS:
        delta=(rows[f"{field}Ask"].to_numpy(dtype=float)-
               rows[f"{field}Bid"].to_numpy(dtype=float))
        crossed=delta<-MIN_SIGNIFICANT_CROSS
        per_field[field]=int(crossed.sum())
        crosses[field]=delta
        bad|=crossed
        if first_field is None and crossed.any():
            first_field=field
        if crossed.any():
            worst=max(worst,float((-delta[crossed]).max()))
    bad_idx=np.flatnonzero(bad)
    timestamps=pd.to_datetime(rows["timestamp"],unit="ms",utc=True)
    examples=[]
    for i in bad_idx[:30]:
        examples.append({
            "candle_open_utc":timestamps.iloc[i].isoformat(),
            "negative_spread_fields":{
                field:round(float(crosses[field][i]),6)
                for field in FIELDS
                if crosses[field][i]<-MIN_SIGNIFICANT_CROSS},
        })
    years=Counter(str(timestamps.iloc[int(i)].year) for i in bad_idx)
    rate=len(bad_idx)/n
    policy={
        "max_fraction":float(max_fraction),
        "max_cross_points":float(max_cross_points),
        "significant_cross_epsilon":MIN_SIGNIFICANT_CROSS,
    }
    quality={
        "input_rows":n,
        "crossed_rows":len(bad_idx),
        "crossed_rate_pct":round(100*rate,6),
        "worst_cross_points":round(worst,6),
        "crossed_by_field":per_field,
        "crossed_by_year":dict(sorted(years.items())),
        "examples_first_30":examples,
        "quarantine_policy":policy,
        "no_price_correction":True,
        "no_forward_fill":True,
    }
    if len(bad_idx):
        if rate>float(max_fraction)+1e-12 or worst>float(max_cross_points)+1e-8:
            quality["decision"]="REJECT_ALL_INPUT_UNTIL_REVIEWED"
            quality["retained_rows"]=0
            quality["quarantined_rows"]=0
            raise CrossedQuoteError(
                "ASK < BID w "+str(first_field)+": "
                f"{len(bad_idx)}/{n} świec "
                f"({rate*100:.4f}%), max crossing {worst:.3f} pkt. "
                f"Limit {max_fraction*100:.4f}% / {max_cross_points:.3f} pkt. "
                "Zapis diagnostyczny .quality.json; bez fałszywych świec.",
                quality,
            )
        quality["decision"]="QUARANTINE_EXPLICIT_SMALL_FRACTION"
    else:
        quality["decision"]="PASS_NO_CROSSING"
    quality["retained_rows"]=n-len(bad_idx)
    quality["quarantined_rows"]=len(bad_idx)
    quality["quarantined_open_utc"]=[
        timestamps.iloc[int(i)].isoformat() for i in bad_idx]
    return rows.loc[~bad].copy(),quality
