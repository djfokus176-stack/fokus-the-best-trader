"""WAVE REVERSAL AI — CLOSED M15 structural observations only.

Not a trading strategy, a broker signal, or confirmed statistical alpha.
A local extremum at candle p becomes KNOWN only at p+right (default 2).
A break of support/resistance is accepted only on a subsequent CLOSED bar.
Never allow a third top to open AUTO/PAPER by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from math import isfinite
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .strategy import indicators

NY = ZoneInfo("America/New_York")
VERSION = "wave_reversal_research_v1"
COUNT_RANGE = (2, 3, 4, 5)
CASH_FIRST_CLOSE = time(9,45)
CASH_LAST_CLOSE = time(16,0)
COLUMNS = (
    "event_id","signal_utc","pivot_utc","direction","wave_count",
    "extremum","pattern","confirmation","bos_level","signal_close",
    "atr","ema21","rsi","vwap_available","volume_available",
    "ema_filter","rsi_filter","atr_filter","vwap_filter",
    "volume_filter","regime","session_ny","strategy_version",
)


def validate_closed_m15(frame:pd.DataFrame):
    """Input MUST have M15 *CLOSE* timestamps. Never silently shift OPEN."""
    if frame is None or not isinstance(frame,pd.DataFrame) or len(frame)<60:
        raise ValueError("WAVE wymaga >=60 zamkniętych M15 (UTC).")
    if (not isinstance(frame.index,pd.DatetimeIndex)
            or frame.index.tz is None or not frame.index.is_monotonic_increasing
            or frame.index.has_duplicates):
        raise ValueError("WAVE wymaga M15 UTC: rosnące, unikalne daty ze strefą.")
    utc=frame.index.tz_convert("UTC")
    if any(t.minute%15 or t.second or t.microsecond for t in utc):
        raise ValueError("Znaczniki muszą leżeć na siatce 15 minut (M15 CLOSE).")
    needed=("Open","High","Low","Close")
    if not set(needed).issubset(frame.columns):
        raise ValueError("CSV M15 musi zawierać Open,High,Low,Close.")
    for c in needed:
        values=pd.to_numeric(frame[c],errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy()).all():
            raise ValueError("Niepoprawne dane OHLC M15.")
    if ((frame["High"]<frame[["Open","Low","Close"]].max(axis=1)).any()
            or (frame["Low"]>frame[["Open","High","Close"]].min(axis=1)).any()
            or (frame["Low"]<=0).any()):
        raise ValueError("Niespójne ceny M15.")


def _features(frame):
    df=indicators(frame)
    # No fake volume or VWAP from price-only inputs.
    vol=None
    if "Volume" in df.columns:
        v=pd.to_numeric(df.Volume,errors="coerce")
        if (v.notna().all() and np.isfinite(v.to_numpy()).all()
                and (v>=0).all() and (v>0).any()):
            vol=v
    df["_vol_ok"]=False
    df["_vol_filter"]=False
    df["_vwap"]=np.nan
    df["_vol_med"]=np.nan
    if vol is not None:
        local=df.index.tz_convert(NY)
        sessions=pd.Series(local.date,index=df.index)
        cash=(pd.Series([(d.weekday()<5 and
              CASH_FIRST_CLOSE<=clock.time()<=CASH_LAST_CLOSE)
              for d,clock in zip(local.date,local)],index=df.index))
        typical=(df.High+df.Low+df.Close)/3.
        numerator=(typical*vol).where(cash,0).groupby(sessions).cumsum()
        denominator=vol.where(cash,0).groupby(sessions).cumsum()
        df["_vwap"]=numerator/denominator.replace(0,np.nan)
        df["_vol_ok"]=True
        df["_vol_med"]=vol.shift(1).rolling(10,min_periods=5).median()
        df["_vol_filter"]=(vol>=1.2*df["_vol_med"]) & (df["_vol_med"]>0)
    df["_atr_med"]=df.ATR.shift(1).rolling(40,min_periods=20).median()
    return df


def _regime(row):
    if pd.isna(row.ATR) or pd.isna(row._atr_med) or row._atr_med<=0:
        return "BRAK DANYCH"
    if row.ATR>=1.5*row._atr_med:
        return "HIGH VOLATILITY"
    if row.EMA21>row.EMA50 and row.EMA9>row.EMA21:
        return "TREND UP"
    if row.EMA21<row.EMA50 and row.EMA9<row.EMA21:
        return "TREND DOWN"
    return "RANGE/MIXED"


def _make_event(df, day, side, wave_count, recent, idx, pivot_idx,
                level, confirmation):
    now=df.iloc[idx]
    atr=float(now.ATR)
    if not isfinite(atr) or atr<=0 or not isfinite(float(now.RSI)):
        return None
    # "Similar level" uses only levels already confirmed by now.
    last2=[p[1] for p in recent[-2:]]
    last3=[p[1] for p in recent[-3:]]
    close2=max(last2)-min(last2)<=.25*atr
    close3=(len(last3)==3 and max(last3)-min(last3)<=.25*atr)
    if close3:
        kind="TRIPLE TOP" if side=="SHORT" else "TRIPLE BOTTOM"
    elif close2:
        kind="DOUBLE TOP" if side=="SHORT" else "DOUBLE BOTTOM"
    else:
        kind="WAVE PEAK" if side=="SHORT" else "WAVE TROUGH"
    near=float(now.Close)
    has_vwap=pd.notna(now._vwap)
    ema=(bool(now.Close<now.EMA21 and now.EMA9<=now.EMA21)
         if side=="SHORT" else
         bool(now.Close>now.EMA21 and now.EMA9>=now.EMA21))
    rsi=bool(now.RSI<50 if side=="SHORT" else now.RSI>50)
    atrpass=(bool(now.ATR>=now._atr_med)
             if pd.notna(now._atr_med) and now._atr_med>0 else None)
    vwap=(bool(near<float(now._vwap)) if side=="SHORT"
          else bool(near>float(now._vwap))) if has_vwap else None
    volfilter=(bool(now._vol_filter) if bool(now._vol_ok) and
               pd.notna(now._vol_med) and now._vol_med>0 else None)
    stamp=df.index[idx]
    return {
      "event_id":f"{VERSION}|{stamp.isoformat()}|{side}|{wave_count}|{confirmation}",
      "signal_utc":stamp,"pivot_utc":df.index[pivot_idx],
      "direction":side,"wave_count":wave_count,
      "extremum":"PEAK" if side=="SHORT" else "TROUGH",
      "pattern":kind,"confirmation":confirmation,"bos_level":round(level,5),
      "signal_close":round(near,5),"atr":round(atr,5),
      "ema21":round(float(now.EMA21),5),
      "rsi":round(float(now.RSI),3),
      "vwap_available":bool(has_vwap),
      "volume_available":bool(now._vol_ok),
      "ema_filter":ema,"rsi_filter":rsi,"atr_filter":atrpass,
      "vwap_filter":vwap,"volume_filter":volfilter,
      "regime":_regime(now),"session_ny":str(day),
      "strategy_version":VERSION,
    }


def detect_waves(frame:pd.DataFrame, *, left=2, right=2,
                 max_bos_wait=8)->pd.DataFrame:
    """Per New York cash session, count 2..5 structurally distinct pivots.

    Input is M15 CLOSE labeled, a 09:30--16:00 ET CASH session convention.
    We never infer US exchange holidays from weekday alone. An incomplete
    session, a gap or a non-NY candle can only REDUCE event coverage.
    RAW is emitted on the right-confirmation candle, BOS only on a later
    candle closing through support/resistance from the correct side.
    """
    validate_closed_m15(frame)
    if left<1 or right<1 or max_bos_wait<1:
        raise ValueError("Swing confirmation needs positive bar counts.")
    df=_features(frame)
    local=df.index.tz_convert(NY)
    cash=(np.array([x.weekday()<5 and
          CASH_FIRST_CLOSE<=x.time()<=CASH_LAST_CLOSE for x in local]))
    indices=np.flatnonzero(cash)
    by_day={}
    for p in indices:
        by_day.setdefault(local[p].date(),[]).append(int(p))
    events=[]
    for day,ids in by_day.items():
        # A gap cannot be interpreted as 2 completed confirmation candles.
        chunks=[]
        group=[]
        for ix in ids:
            if group and df.index[ix]-df.index[group[-1]]!=pd.Timedelta(minutes=15):
                chunks.append(group)
                group=[]
            group.append(ix)
        if group:chunks.append(group)
        for chunk in chunks:
            if len(chunk)<max(7,left+right+3):
                continue
            highs=[];lows=[]
            pending=[]
            for k in range(left+right,len(chunk)):
                cur=chunk[k]
                candidate=chunk[k-right]
                left_ids=chunk[k-right-left:k-right]
                right_ids=chunk[k-right+1:k+1]
                h=float(df.High.iloc[candidate]);l=float(df.Low.iloc[candidate])
                newh=all(h>float(df.High.iloc[j]) for j in left_ids+right_ids)
                newl=all(l<float(df.Low.iloc[j]) for j in left_ids+right_ids)
                # One ambiguous outside candle cannot be a top and bottom.
                if newh and newl:
                    newh=newl=False
                if newh:
                    if not highs or any(x[0]>highs[-1][0] and x[0]<candidate
                                         for x in lows):
                        highs.append((candidate,h))
                        if 2<=len(highs)<=5:
                            first=highs[-2][0]
                            # Lowest known LOW between last two confirmed peaks.
                            level=float(df.Low.iloc[first:candidate+1].min())
                            ev=_make_event(df,day,"SHORT",len(highs),
                                           highs,cur,candidate,level,"RAW")
                            if ev is not None:
                                events.append(ev)
                                pending.append((ev,cur))
                if newl:
                    if not lows or any(x[0]>lows[-1][0] and x[0]<candidate
                                       for x in highs):
                        lows.append((candidate,l))
                        if 2<=len(lows)<=5:
                            first=lows[-2][0]
                            level=float(df.High.iloc[first:candidate+1].max())
                            ev=_make_event(df,day,"LONG",len(lows),
                                           lows,cur,candidate,level,"RAW")
                            if ev is not None:
                                events.append(ev)
                                pending.append((ev,cur))
                next_pending=[]
                for ev,confirmed_bar in pending:
                    age=(df.index[cur]-df.index[confirmed_bar]).total_seconds()/900
                    if age==0:
                        next_pending.append((ev,confirmed_bar))
                        continue
                    if age>max_bos_wait:
                        continue
                    level=ev["bos_level"]
                    prev=float(df.Close.iloc[chunk[k-1]])
                    close=float(df.Close.iloc[cur])
                    if ev["direction"]=="SHORT":
                        broke=prev>=level and close<level
                    else:
                        broke=prev<=level and close>level
                    if broke:
                        # At BOS time recompute all features from that bar:
                        # not from the RAW candle or future bars.
                        pivot_idx=int(df.index.get_loc(ev["pivot_utc"]))
                        latest=highs if ev["direction"]=="SHORT" else lows
                        newev=_make_event(df,day,ev["direction"],
                            ev["wave_count"],latest[:ev["wave_count"]],
                            cur,pivot_idx,level,"BOS")
                        if newev is not None:
                            # Preserve the RAW pattern classification.
                            newev["pattern"]=ev["pattern"]
                            events.append(newev)
                    else:
                        next_pending.append((ev,confirmed_bar))
                pending=next_pending
    return pd.DataFrame(events,columns=COLUMNS)
