"""Research reporting for WAVE 2.0, with explicit missing data and OOS.

Conditional excursions UP/DOWN are not complementary: one horizon may hit
both sides. FLAT means neither threshold was touched. All windows must be
fully observed within the same verified NY cash session. Confidence bounds
are descriptive; correlated events and many hypotheses preclude proof of alpha.
"""
from __future__ import annotations

from math import sqrt
import numpy as np
import pandas as pd

from .wave_intelligence2 import VARIANTS, _continuous

THRESHOLDS=(.25,.5,1.,1.5,2.)
HORIZONS_MIN=(60,120,240)


def wilson_95(hits, count):
    if count<=0:return (None,None)
    z=1.96
    p=hits/count
    den=1+z*z/count
    center=(p+z*z/(2*count))/den
    half=z*sqrt((p*(1-p)+z*z/(4*count))/count)/den
    return (round(100*max(0,center-half),2),
            round(100*min(1,center+half),2))


def wave_excursion_audit(frame, logs):
    """Per opportunity, return up/down/both/neither or missing for each horizon.

    Use one anchor per day/direction (as in A-E), and strictly 15min future
    closed OHLC bars. No post-signal data is used to set features or entry.
    """
    if logs is None or logs.empty:
        return pd.DataFrame(),pd.DataFrame()
    anchors=logs[logs.variant=="E_WAIT"].drop_duplicates("anchor_id")
    idx={ts:i for i,ts in enumerate(frame.index)}
    events=[]
    for a in anchors.itertuples(index=False):
        at=idx.get(a.anchor_utc)
        if at is None:continue
        price=float(frame.Close.iloc[at])
        for minutes in HORIZONS_MIN:
            end=at+minutes//15
            full=end<len(frame) and _continuous(frame,at,end)
            future=frame.iloc[at+1:end+1] if full else None
            for pct in THRESHOLDS:
                up=(bool(future.High.max()>=price*(1+pct/100))
                    if full else None)
                down=(bool(future.Low.min()<=price*(1-pct/100))
                      if full else None)
                events.append({"anchor_id":a.anchor_id,
                    "anchor_utc":a.anchor_utc,"year":a.event_year,
                    "period":a.period,"third_extremum":a.anchor_extremum,
                    "pattern":a.pattern,"structure":a.wave_structure,
                    "threshold_pct":pct,"horizon_min":minutes,
                    "up":up,"down":down,
                    "both":up and down if full else None,
                    "flat":(not up and not down) if full else None,
                    "valid":bool(full)})
    detail=pd.DataFrame(events)
    groups=[]
    for key,g in detail.groupby(
        ["period","third_extremum","threshold_pct","horizon_min"],sort=True):
        eligible=g[g.valid]
        n=len(eligible)
        ups=int(eligible.up.sum()) if n else 0
        downs=int(eligible.down.sum()) if n else 0
        both=int(eligible.both.sum()) if n else 0
        flat=int(eligible.flat.sum()) if n else 0
        ulo,uhi=wilson_95(ups,n)
        dlo,dhi=wilson_95(downs,n)
        groups.append(dict(zip(
           ["period","third_extremum","threshold_pct","horizon_min"],key))|
           {"eligible":len(g),"n":n,"missing_horizon":len(g)-n,
            "up":ups,"down":downs,"both":both,"flat":flat,
            "up_pct":round(100*ups/n,2) if n else None,
            "down_pct":round(100*downs/n,2) if n else None,
            "flat_pct":round(100*flat/n,2) if n else None,
            "up_wilson95":(ulo,uhi),"down_wilson95":(dlo,dhi),
            "status":"BRAK DANYCH" if not n else
                     "MAŁA PRÓBA (<100)" if n<100 else
                     "BADANIE — NIE POTWIERDZA PRZEWAGI NETTO"})
    return pd.DataFrame(groups),detail


def hour_ranking(logs):
    """NY local hour buckets: no fake hourly returns for unsupported feeds."""
    if logs is None or logs.empty:return pd.DataFrame()
    rows=logs[(logs.variant!="E_WAIT") & logs.pnl_pts.notna()].copy()
    if rows.empty:return pd.DataFrame()
    rows["hour_et"]=pd.to_datetime(rows.signal_utc,utc=True).dt.tz_convert(
            "America/New_York").dt.strftime("%H")
    result=rows.groupby(["period","variant","direction","hour_et"],dropna=False).agg(
        n=("pnl_pts","size"),net_pts=("pnl_pts","sum"),
        mean_pts=("pnl_pts","mean"),
        wins=("pnl_pts",lambda s:int((s>0).sum()))).reset_index()
    result["win_pct"]=(100*result.wins/result.n).round(2)
    return result


def feature_audit(logs):
    """Exploratory winner/loser conditional distribution, not a causal model."""
    if logs is None or logs.empty:return pd.DataFrame()
    raw=logs[(logs.variant=="A_RAW") & logs.pnl_pts.notna()].copy()
    if raw.empty:return pd.DataFrame()
    fields=("wave_structure","pattern","ema200_relation",
            "vwap_relation","large_rejection_wick","false_break_at_pivot",
            "atr_rising","regime","signal_et_hour")
    records=[]
    for col in fields:
        for (period,side,value),g in raw.groupby(
            ["period","anchor_side",col],dropna=False):
            n=len(g)
            pos=int((g.pnl_pts>0).sum())
            records.append({"feature":col,"value":str(value),
                            "period":period,"anchor_side":side,
                            "n":n,"positive":pos,"positive_pct":round(100*pos/n,2),
                            "mean_net_pts":round(float(g.pnl_pts.mean()),3),
                            "sum_net_pts":round(float(g.pnl_pts.sum()),2),
                            "status":"BRAK DOWODU, PRÓBA <30" if n<30 else
                                     "BADANIE, WYMAGA PRZYSZŁEJ WALIDACJI"})
    return pd.DataFrame(records).sort_values(
        ["feature","anchor_side","period","n"],ascending=[True,True,True,False])


def timeframe_coverage():
    """Do not claim M1/M5/H1 ranked from an M15-only source."""
    return pd.DataFrame([
        {"interwal":"M1","status":"BRAK DANYCH — wymaga źródłowych M1"},
        {"interwal":"M5","status":"BRAK DANYCH — wymaga źródłowych M5"},
        {"interwal":"M15","status":"BADANIE NA WGRANYCH M15"},
        {"interwal":"H1","status":"BRAK ODRĘBNEGO BADANIA H1"},
    ])
