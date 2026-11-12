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
            "atr_rising","momentum_slowing","time_to_new_extremum_slower",
            "successive_rebound_weaker","regime","signal_et_hour")
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


def same_entries_exit_grid(frame, logs, *, split_cutoff, spread=2., slippage=.25):
    """Frozen A/B/C/D entry signals with 4 R targets x 6 horizons.

    M15 lacks 10/20-minute closes, so those combinations are explicit
    BRAK DANYCH. Signals, candidates, and entries do NOT change as
    stop/target/time configurations change. This is diagnostic only.
    """
    from .wave_intelligence2 import (_trade, RR_VALUES,
                                      M15_EXITS_MIN,M15_UNSUPPORTED_MIN)
    if logs is None or logs.empty:
        return pd.DataFrame(),pd.DataFrame()
    idx={t:i for i,t in enumerate(frame.index)}
    cutoff=pd.Timestamp(split_cutoff)
    if cutoff.tzinfo is None:
        raise ValueError("Wymagany rzeczywisty graniczny timestamp OOS UTC")
    cutoff=cutoff.tz_convert("UTC")
    rows=[]
    for t in logs.itertuples(index=False):
        if t.variant=="E_WAIT" or not t.triggered or pd.isna(t.signal_utc):
            continue
        signal_idx=idx.get(pd.Timestamp(t.signal_utc))
        if signal_idx is None:continue
        for rr in RR_VALUES:
            for hold in (*M15_UNSUPPORTED_MIN,*M15_EXITS_MIN):
                if hold in M15_UNSUPPORTED_MIN:
                    outcome={"status":"BRAK DANYCH M15","pnl_pts":None}
                else:
                    outcome=_trade(frame,signal_idx,t.direction,t.atr,
                                   rr=rr,minutes=hold,spread=spread,
                                   slippage=slippage,split_ts=cutoff)
                rows.append({"anchor_id":t.anchor_id,"anchor_utc":t.anchor_utc,
                    "period":t.period,"year":t.event_year,
                    "side":t.direction,"variant":t.variant,
                    "rr_tp":rr,"holding_min":hold,
                    "status":outcome["status"],"pnl_pts":outcome.get("pnl_pts"),
                    "mfe_pts":outcome.get("mfe_pts"),"mae_pts":outcome.get("mae_pts"),
                    "exit_min":outcome.get("exit_min")})
    detail=pd.DataFrame(rows)
    summary=[]
    if detail.empty:return pd.DataFrame(),detail
    for (period,side,variant,rr,hold),g in detail.groupby(
        ["period","side","variant","rr_tp","holding_min"],sort=True):
        v=g.pnl_pts.dropna().astype(float)
        gains=v[v>0].sum();loss=-v[v<0].sum()
        eq=v.cumsum();dd=eq-eq.cummax().clip(lower=0)
        summary.append({"period":period,"side":side,"variant":variant,
            "rr_tp":rr,"holding_min":hold,"entries":len(g),
            "scored":len(v),"profitable":int((v>0).sum()),
            "win_pct":round(float(100*(v>0).mean()),2) if len(v) else None,
            "net_pts":round(float(v.sum()),3) if len(v) else None,
            "expectancy":round(float(v.mean()),3) if len(v) else None,
            "profit_factor":round(float(gains/loss),3) if loss else None,
            "max_dd_pts":round(float(-dd.min()),3) if len(v) else None,
            "status": "BRAK DANYCH M15" if hold in M15_UNSUPPORTED_MIN else
                      "BRAK DANYCH" if len(v)==0 else
                      "ZA MAŁA PRÓBA (<30)" if len(v)<30 else
                      "BADANIE — WYMAGA NOWEGO FORWARD"})
    return pd.DataFrame(summary),detail


def wave_pattern_ranking(summary):
    """Compact A--E ranking; OOS is descriptive until a new forward period.

    Number of years positive ignores missing years. 2021 and 2026 are not
    counted as full years in a Dukascopy 2021-11 -> 2026-11 dataset.
    """
    cols=("FORMACJA","LONG_SHORT","INTERWAL","PROBY_TRAIN","WIN_RATE_TRAIN",
          "PF_TRAIN","NETTO_TRAIN","MAX_DD_TRAIN","LATA_PLUS_2022_25",
          "PROBY_OOS","PF_OOS","NETTO_OOS","EXPECTANCY_OOS","STATUS")
    if summary is None or summary.empty:return pd.DataFrame(columns=cols)
    rows=[]
    base=summary[summary.year.isna()]
    annual=summary[summary.year.notna()]
    for side in ("SHORT","LONG"):
        for variant in VARIANTS:
            t=base[(base.anchor_side==side)&(base.variant==variant)&
                   (base.period=="WCZESNIEJSZE")]
            o=base[(base.anchor_side==side)&(base.variant==variant)&
                   (base.period=="POZNIEJSZE")]
            if t.empty or o.empty:continue
            tr,os=t.iloc[0],o.iloc[0]
            yearly=annual[(annual.anchor_side==side)&(annual.variant==variant)&
                         (annual.year.isin([2022,2023,2024,2025]))]
            nplus=int(((yearly.net_pts>0)&(yearly.closed>0)).groupby(yearly.year).any().sum())
            rows.append(dict(zip(cols,(
                variant,side,"M15",int(tr.closed),tr.win_pct,tr.profit_factor,
                tr.net_pts,tr.max_drawdown_pts,nplus,int(os.closed),
                os.profit_factor,os.net_pts,os.expectancy_pts,
                "WAIT — BRAK NOWEGO FORWARD" if (tr.closed and os.closed)
                else "BRAK DANYCH"))))
    return pd.DataFrame(rows,columns=cols)
