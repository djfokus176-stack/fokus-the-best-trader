"""WAVE REVERSAL AI OFFLINE M15 evaluation, not brokerage or AUTO logic.

Estimates conditional price excursions (0.25/0.5/1% by 1/2/4 h), plus
ONE separately modeled trade (1.5xATR SL/2.25xATR TP, 8 M15 closes).
All forward labels are computed AFTER signal formation. An M15 gap or
cross-session horizon is INVALIDATED, never a win/loss. No retroactively
computed filters, filled missing VWAP, fabricated BID/ASK or claimed edge.
"""
from __future__ import annotations

from math import isfinite, sqrt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .wave_reversal import detect_waves, validate_closed_m15

HORIZONS = {1:4,2:8,4:16}
TARGETS = (.25,.5,1.)
# A filter that lacks actual volume/VWAP data has UNKNOWN, not False/True.
FILTERS = (
    "BASE","EMA","RSI","ATR","VWAP","VOLUME","EMA+RSI+ATR",
    "EMA+RSI+ATR+VWAP+VOLUME",
)
COMPARE_COLUMNS=(
    "okres","direction","wave_count","pattern","confirmation","filter",
    "target_pct","horizon_h","n","hits","probability_pct",
    "wilson95_lower_pct","wilson95_upper_pct",
    "baseline_random_side_pct","lift_pp","lower95_lift_pp",
    "with_net_pnl","net_sum_pts","net_avg_pts","profit_factor",
    "max_drawdown_pts","net_avg_lower95","status",
)


def _filter_ok(row, name):
    keys={
       "EMA":("ema_filter",),"RSI":("rsi_filter",),
       "ATR":("atr_filter",),"VWAP":("vwap_filter",),
       "VOLUME":("volume_filter",),
       "EMA+RSI+ATR":("ema_filter","rsi_filter","atr_filter"),
       "EMA+RSI+ATR+VWAP+VOLUME":(
           "ema_filter","rsi_filter","atr_filter",
           "vwap_filter","volume_filter"),
    }.get(name,())
    return all(row[k] is not None and not pd.isna(row[k]) and
               bool(row[k]) for k in keys)


def _wilson(k,n):
    if n<=0:return (None,None)
    z=1.96
    p=k/n
    center=(p+z*z/(2*n))/(1+z*z/n)
    width=(z*sqrt((p*(1-p)+z*z/(4*n))/n))/(1+z*z/n)
    return (max(0,center-width)*100,min(1,center+width)*100)


def _maxdd(series):
    top=0.
    equity=0.
    worst=0.
    for x in series:
        equity+=x
        top=max(top,equity)
        worst=max(worst,top-equity)
    return round(worst,3)


def _net_result(frame, loc, side, atr, *, assumed_spread, slippage):
    """8 closed M15 bars; model executable sides if full bid/ask OHLC exists.

    If no complete bid/ask, use the previous CLOSE's observed Spread, if
    supplied, otherwise the explicit fixed assumption. Never invent true
    quote observations. Stop has priority if one OHLC bar spans stop+TP.
    """
    future=frame.iloc[loc+1:loc+9]
    if len(future)<8:
        return {"status":"INVALIDATED_HORIZON","net":None,
                "execution":"BRAK PEŁNEGO HORYZONTU"}
    t0=frame.index[loc]
    local=t0.tz_convert("America/New_York").date()
    prev=t0
    for t in future.index:
        if t-prev!=pd.Timedelta(minutes=15) or t.tz_convert(
                "America/New_York").date()!=local or t.tz_convert(
                "America/New_York").time()>pd.Timestamp("16:00").time():
            return {"status":"INVALIDATED_GAP_OR_SESSION","net":None,
                    "execution":"NIEPEŁNY HORYZONT"}
        prev=t
    if not isfinite(float(atr)) or atr<=0:
        return {"status":"INVALIDATED_ATR","net":None,"execution":"BRAK ATR"}
    bidask=all(c in frame.columns for c in (
        "BidOpen","BidHigh","BidLow","BidClose",
        "AskOpen","AskHigh","AskLow","AskClose"))
    if bidask:
        cols=["BidOpen","BidHigh","BidLow","BidClose",
              "AskOpen","AskHigh","AskLow","AskClose"]
        raw=frame.iloc[loc+1:loc+9][cols].apply(pd.to_numeric,errors="coerce")
        if (raw.isna().any().any() or not np.isfinite(raw.to_numpy()).all()
                or (raw[["AskOpen","AskHigh","AskLow","AskClose"]].to_numpy()
                    <raw[["BidOpen","BidHigh","BidLow","BidClose"]].to_numpy()).any()):
            return {"status":"INVALIDATED_QUOTES","net":None,
                    "execution":"WADLIWE BID/ASK"}
        mode="BID_ASK_OHLC"
        # At entry we can actually observe the next opening bid/ask,
        # not assume signal close was a fill.
        entry_mid=(float(future.iloc[0].BidOpen)+
                   float(future.iloc[0].AskOpen))/2
    else:
        mode=("SPREAD_M15_CLOSE_MODEL" if "Spread" in frame.columns
              else "SPREAD_FIXED_ASSUMPTION")
        entry_mid=float(future.iloc[0].Open)
    stop_mid=(entry_mid-1.5*atr if side=="LONG" else entry_mid+1.5*atr)
    tp_mid=(entry_mid+2.25*atr if side=="LONG" else entry_mid-2.25*atr)
    if not isfinite(stop_mid) or not isfinite(tp_mid):
        return {"status":"INVALIDATED_GEOMETRY","net":None,
                "execution":mode}
    observed_spreads=None
    if not bidask:
        if "Spread" in frame.columns:
            values=pd.to_numeric(frame.Spread.iloc[loc:loc+8],errors="coerce")
            if (values.isna().any() or (values<0).any()
                    or not np.isfinite(values.to_numpy()).all()):
                return {"status":"INVALIDATED_SPREAD","net":None,
                        "execution":"WADLIWY SPREAD"}
            observed_spreads=values.astype(float).tolist()
        else:
            observed_spreads=[float(assumed_spread)]*8
    if bidask:
        first=future.iloc[0]
        entry=(float(first.AskOpen)+slippage if side=="LONG" else
               float(first.BidOpen)-slippage)
    else:
        entry_spread=observed_spreads[0]
        entry=(entry_mid+entry_spread/2+slippage if side=="LONG" else
               entry_mid-entry_spread/2-slippage)
    if not isfinite(entry):
        return {"status":"INVALIDATED_ENTRY","net":None,
                "execution":mode}
    exitval=None
    exitreason="TIMEOUT"
    for k,bar in enumerate(future.itertuples(index=False)):
        if bidask:
            # Executable bid for LONG and ask for SHORT; no future close
            # spreads or midpoint fills are used for a hypothetical stop.
            hi=(float(bar.BidHigh) if side=="LONG" else float(bar.AskHigh))
            lo=(float(bar.BidLow) if side=="LONG" else float(bar.AskLow))
            opening=(float(bar.BidOpen) if side=="LONG" else float(bar.AskOpen))
        else:
            hi=float(bar.High);lo=float(bar.Low);opening=float(bar.Open)
        spread=(0. if bidask else observed_spreads[k])
        if side=="LONG":
            if lo<=stop_mid:
                exitval=min(stop_mid,opening)-spread/2-slippage
                exitreason="SL"
            elif hi>=tp_mid:
                exitval=tp_mid-spread/2-slippage
                exitreason="TP"
        else:
            if hi>=stop_mid:
                exitval=max(stop_mid,opening)+spread/2+slippage
                exitreason="SL"
            elif lo<=tp_mid:
                exitval=tp_mid+spread/2+slippage
                exitreason="TP"
        if exitval is not None:
            break
    if exitval is None:
        last=future.iloc[-1]
        if bidask:
            exitval=(float(last.BidClose)-slippage if side=="LONG"
                     else float(last.AskClose)+slippage)
        else:
            # Historical closing spread at M15 bar close is known at the
            # hypothetical TIMEOUT exit; not an intrabar SL/TP future quote.
            finish=(float(last.Spread) if "Spread" in frame.columns
                    else float(assumed_spread))
            if not isfinite(finish) or finish<0:
                return {"status":"INVALIDATED_SPREAD","net":None,
                        "execution":"WADLIWY SPREAD"}
            exitval=(float(last.Close)-finish/2-slippage if side=="LONG"
                     else float(last.Close)+finish/2+slippage)
    net=exitval-entry if side=="LONG" else entry-exitval
    return {"status":exitreason,"net":round(float(net),3),
            "execution":mode}


def _probes(frame,loc,side):
    result=[]
    at=frame.index[loc]
    nyday=at.tz_convert("America/New_York").date()
    close=float(frame.Close.iloc[loc])
    for hours,bars in HORIZONS.items():
        future=frame.iloc[loc+1:loc+bars+1]
        valid=len(future)==bars
        prev=at
        for t in future.index:
            if (t-prev!=pd.Timedelta(minutes=15)
                    or t.tz_convert("America/New_York").date()!=nyday
                    or t.tz_convert("America/New_York").time()>
                       pd.Timestamp("16:00").time()):
                valid=False
                break
            prev=t
        for pct in TARGETS:
            if not valid:
                result.append((hours,pct,None,None))
                continue
            pctval=pct/100.
            high=float(future.High.max())
            low=float(future.Low.min())
            down=int(low<=close*(1-pctval))
            up=int(high>=close*(1+pctval))
            result.append((hours,pct,down if side=="SHORT" else up,
                           .5*(up+down)))
    return result


def _independent_period(rows, horizon):
    """De-correlate overlapping event windows within each session/direction.

    All 9 horizon-probability rankings are evaluated on a separately
    non-overlapping subset of events; no portfolio P&L is claimed.
    """
    selected=[]
    last={}
    for row in sorted(rows,key=lambda x:x["signal_utc"]):
        key=(row["session_ny"],row["direction"])
        at=row["signal_utc"]
        if key in last and at-last[key]<pd.Timedelta(hours=horizon):
            continue
        selected.append(row)
        last[key]=at
    return selected


def _stats(results):
    nets=[r["net"] for r in results if r["net"] is not None]
    if not nets:
        return (0,None,None,None,None)
    gains=sum(max(0,v) for v in nets)
    losses=sum(-min(0,v) for v in nets)
    pf=(round(gains/losses,3) if losses else None)
    n=len(nets)
    lower=(sum(nets)/n-1.96*np.std(nets,ddof=1)/sqrt(n)
           if n>=2 else None)
    return (n,round(sum(nets),2),round(sum(nets)/n,3),
            pf,round(lower,3) if lower is not None else None)


def analyze_wave_m15(frame:pd.DataFrame, *, spread_assumption=1.5,
                     slippage=.25, split=.7):
    """Analyze RAW and BOS without choosing an 'optimal' profitable variant.

    Output: (ranking, event_log, yearly, meta). This includes every 2..5
    wave, LONG/SHORT, filter and 1h/2h/4h target-probability combination,
    with empty/nonobserved variants marked BRAK DANYCH.
    """
    validate_closed_m15(frame)
    if (not 0.5<=split<=.85 or
            not all(isfinite(float(x)) and float(x)>=0
                    for x in (spread_assumption,slippage))):
        raise ValueError("Niepoprawny podział lub model kosztów.")
    events=detect_waves(frame)
    start=frame.index[int(len(frame)*split)]
    details=[]
    index_map={t:i for i,t in enumerate(frame.index)}
    for rec in events.to_dict("records"):
        i=index_map[rec["signal_utc"]]
        period="WCZESNIEJSZE" if rec["signal_utc"]<start else "POZNIEJSZE"
        pnl=_net_result(frame,i,rec["direction"],rec["atr"],
                        assumed_spread=spread_assumption,slippage=slippage)
        random_side=("LONG" if rec["direction"]=="SHORT" else "SHORT")
        opposite=_net_result(frame,i,random_side,rec["atr"],
                             assumed_spread=spread_assumption,slippage=slippage)
        # Equal 50/50 random-direction expectation at the SAME timestamps.
        baseline_net=(.5*(pnl["net"]+opposite["net"])
                      if pnl["net"] is not None and opposite["net"] is not None
                      else None)
        for hours,pct,hit,random_hit in _probes(frame,i,rec["direction"]):
            details.append({
                **rec,"okres":period,"rok":rec["signal_utc"].year,
                "horizon_h":hours,"target_pct":pct,"hit":hit,
                "baseline_random_side":random_hit,
                "net_status":pnl["status"],"net_pts":pnl["net"],
                "baseline_random_net":baseline_net,
                "execution":pnl["execution"],
                "history_valid":hit is not None,
            })
    logs=pd.DataFrame(details)
    summary=[]
    years=[]
    periods=("WCZESNIEJSZE","POZNIEJSZE")
    directions=("LONG","SHORT")
    patterns=("ANY","DOUBLE TOP","TRIPLE TOP","DOUBLE BOTTOM","TRIPLE BOTTOM")
    for period in periods:
        for side in directions:
            for n in (2,3,4,5):
                for confirm in ("RAW","BOS"):
                    for pattern in patterns:
                        if pattern.endswith("TOP") and side!="SHORT":continue
                        if pattern.endswith("BOTTOM") and side!="LONG":continue
                        for filter_name in FILTERS:
                            for hours in HORIZONS:
                                for pct in TARGETS:
                                    if logs.empty: selected=[]
                                    else:
                                        subset=logs.loc[
                                            (logs.okres==period)&
                                            (logs.direction==side)&
                                            (logs.wave_count==n)&
                                            (logs.confirmation==confirm)&
                                            (logs.horizon_h==hours)&
                                            (logs.target_pct==pct)]
                                        if pattern!="ANY":
                                            subset=subset[subset.pattern==pattern]
                                        selected=[r for r in subset.to_dict("records")
                                                  if _filter_ok(r,filter_name)
                                                  and r["hit"] is not None]
                                    picked=_independent_period(selected,hours)
                                    nobs=len(picked)
                                    hits=int(sum(int(r["hit"]) for r in picked))
                                    low,high=_wilson(hits,nobs)
                                    baseline=(sum(float(r["baseline_random_side"])
                                                  for r in picked)/nobs
                                              if nobs else None)
                                    diffs=[float(r["hit"]-r["baseline_random_side"])
                                           for r in picked]
                                    lift=(sum(diffs)/nobs if nobs else None)
                                    lower=(lift-1.96*np.std(diffs,ddof=1)/sqrt(nobs)
                                           if nobs>=2 else None)
                                    net_rows={}
                                    for r in picked:
                                        net_rows[r["event_id"]]=(r["net_pts"],
                                                r["baseline_random_net"])
                                    pnl=[v[0] for v in net_rows.values()
                                         if v[0] is not None]
                                    gain=sum(v for v in pnl if v>0)
                                    loss=-sum(v for v in pnl if v<0)
                                    pf=round(gain/loss,3) if loss>0 else None
                                    net_lower=(float(np.mean(pnl))-
                                        1.96*float(np.std(pnl,ddof=1))/sqrt(len(pnl))
                                        if len(pnl)>=2 else None)
                                    # An exploratory 70/30 result is not
                                    # statistically VERIFIED, regardless of P&L.
                                    diagnostic=("BRAK DANYCH" if nobs==0 else
                                                "ZA MAŁO PRÓB (<100)" if nobs<100 else
                                                "KANDYDAT DO NOWEGO FORWARD" if
                                                low is not None and lower is not None and
                                                lower>0 and net_lower is not None and
                                                net_lower>0 and pf is not None and pf>1
                                                else "BRAK UDOWODNIONEJ PRZEWAGI")
                                    summary.append({
                                        "okres":period,"direction":side,"wave_count":n,
                                        "pattern":pattern,"confirmation":confirm,
                                        "filter":filter_name,"target_pct":pct,
                                        "horizon_h":hours,"n":nobs,"hits":hits,
                                        "probability_pct":round(hits*100/nobs,2)
                                                          if nobs else None,
                                        "wilson95_lower_pct":round(low,2)
                                                          if low is not None else None,
                                        "wilson95_upper_pct":round(high,2)
                                                          if high is not None else None,
                                        "baseline_random_side_pct":round(baseline*100,2)
                                                          if baseline is not None else None,
                                        "lift_pp":round(lift*100,2) if lift is not None else None,
                                        "lower95_lift_pp":round(lower*100,2)
                                                          if lower is not None else None,
                                        "with_net_pnl":len(pnl),
                                        "net_sum_pts":round(sum(pnl),2) if pnl else None,
                                        "net_avg_pts":round(float(np.mean(pnl)),3)
                                                      if pnl else None,
                                        "profit_factor":pf,
                                        "max_drawdown_pts":_maxdd(pnl) if pnl else None,
                                        "net_avg_lower95":round(net_lower,3)
                                                          if net_lower is not None else None,
                                        "status":diagnostic,
                                    })
    ranking=pd.DataFrame(summary,columns=COMPARE_COLUMNS)
    # Year by year is a separate annual breakdown of the unfiltered raw
    # and BOS events, no implicit pooling of LONG/SHORT or 2..5 waves.
    if not logs.empty:
        base=logs[(logs.horizon_h==2)&(logs.target_pct==.5)&
                  logs.history_valid].drop_duplicates("event_id")
        for (year,side,wave,confirm),g in base.groupby(
                ["rok","direction","wave_count","confirmation"],sort=True):
            pairs=g.net_pts.dropna().astype(float)
            yearly_hit=int(g.hit.astype(int).sum())
            years.append({
                "rok":int(year),"direction":side,"wave_count":int(wave),
                "confirmation":confirm,"n":len(g),
                "hits_0_5pct_2h":yearly_hit,
                "probability_pct":round(100*yearly_hit/len(g),2),
                "trades_scored":len(pairs),
                "net_pts":round(float(pairs.sum()),2) if len(pairs) else None,
                "profit_factor":(
                    round(float(pairs[pairs>0].sum() /
                                -pairs[pairs<0].sum()),3)
                    if len(pairs) and (pairs<0).any() else None),
            })
    annual=pd.DataFrame(years,columns=[
        "rok","direction","wave_count","confirmation","n",
        "hits_0_5pct_2h","probability_pct","trades_scored",
        "net_pts","profit_factor"])
    meta={
        "module":"WAVE REVERSAL AI v1 BADAWCZY",
        "signals":len(events),"outcome_rows":len(logs),
        "split_utc":str(start),"source_rows":len(frame),
        "period":"M15 CLOSE", "cash_session":"09:45–16:00 America/New_York",
        "reference_trade":"SL=1.5×ATR, TP=2.25×ATR, max 8×M15",
        "baseline":"50/50 LOSOWY KIERUNEK na TYCH SAMYCH godzinach, nie losowe wejścia",
        "bidask_full":all(c in frame.columns for c in (
            "BidOpen","BidHigh","BidLow","BidClose",
            "AskOpen","AskHigh","AskLow","AskClose")),
        "spread_in_file":"Spread" in frame.columns,
        "volume_in_file":"Volume" in frame.columns,
        "spread_assumption":spread_assumption,
        "slippage_each_side":slippage,
        "research_only":True,
        "verified_edge":False,
        "warnings":(
            "OOS chronologiczne jest tylko eksperymentalne; mnożone filtry "
            "i korelacje sygnałów wymagają niezależnego forward testu.",
            "M15 OHLC nie ustala kolejności dotknięcia SL/TP w jednej świecy "
            "(założenie SL-first); nie odtwarza rzeczywistych filli.",
            "Brak prawdziwego Volume/VWAP lub Bid/Ask => brak danych filtra "
            "lub modelowane koszty; nie wolno ich dopisywać.",
            "Święta NYSE nie są zweryfikowane; weekendy i przerwy są pomijane.",
        ),
    }
    return ranking,logs,annual,meta
