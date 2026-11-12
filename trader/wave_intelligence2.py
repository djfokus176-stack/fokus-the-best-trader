"""WAVE INTELLIGENCE 2.0: auditable M15 A/B/C/D/E research, NEVER AUTO.

Every anchor is a third peak/trough confirmed by two *closed* later candles
from wave_reversal.detect_waves. B/C/D signals are recognized only at later
CLOSED candles; hypothetical entries use the NEXT bar's executable OPEN.
Instruments, feed and timestamp conventions must remain explicit. Gaps, cross-
session entry, and cross-split exits are unscored. Stop first on ambiguous OHLC.
This is not an execution engine or proof of positive expected value.
"""
from __future__ import annotations

from math import isfinite, sqrt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .wave_reversal import detect_waves, validate_closed_m15
from .strategy import indicators

VERSION = "wave_intelligence2_research_v1"
NY = ZoneInfo("America/New_York")
VARIANTS = ("A_RAW", "B_BOS", "C_BOS_RETEST", "D_BREAKOUT_HOLD", "E_WAIT")
RR_VALUES = (1.0, 1.5, 2.0, 3.0)
# Ten and twenty minutes are NOT representable on M15; never round them.
M15_EXITS_MIN = (30, 45, 60, 120)
M15_UNSUPPORTED_MIN = (10, 20)


def _day(ts):
    return ts.tz_convert(NY).date()


def _same_session(a, b):
    local=b.tz_convert(NY)
    return (_day(a)==local.date() and local.weekday()<5 and
            (9*60+45)<=local.hour*60+local.minute<=16*60)


def _continuous(frame, start, last):
    if last <= start:
        return False
    for k in range(start+1, last+1):
        if (frame.index[k]-frame.index[k-1] != pd.Timedelta(minutes=15)
                or not _same_session(frame.index[start], frame.index[k])):
            return False
    return True


def _context(frame, raw_idx, anchor):
    """Feature vector using only information available at the RAW close."""
    prefix=frame.iloc[:raw_idx+1]
    tail=prefix.iloc[max(0,len(prefix)-210):]
    bars=indicators(tail)
    cur=bars.iloc[-1]
    ema200=float(prefix.Close.ewm(span=200,adjust=False).mean().iloc[-1])
    atr=float(cur.ATR)
    pivot_idx=int(frame.index.get_loc(pd.Timestamp(anchor["pivot_utc"])))
    pivot=frame.iloc[pivot_idx]
    height=max(1e-10,float(pivot.High-pivot.Low))
    wick=((float(pivot.High)-max(float(pivot.Open),float(pivot.Close)))
          if anchor["direction"]=="SHORT" else
          (min(float(pivot.Open),float(pivot.Close))-float(pivot.Low)))
    prior=frame.iloc[max(0,pivot_idx-12):pivot_idx]
    # A peak's false breakout is a past wick beyond a prior high followed
    # by a close back inside; the mirrored low case is symmetrical.
    if len(prior):
        level=float(prior.High.max() if anchor["direction"]=="SHORT"
                    else prior.Low.min())
        falsebreak=bool((pivot.High>level and pivot.Close<level)
                        if anchor["direction"]=="SHORT" else
                        (pivot.Low<level and pivot.Close>level))
    else:
        falsebreak=False
    win=bars.iloc[-20:]
    atr_hist=win.ATR.dropna()
    atr_ratio=(float(cur.ATR)/float(atr_hist.iloc[0])
               if len(atr_hist) and float(atr_hist.iloc[0])>0 else None)
    vol_available=("Volume" in prefix.columns and
                   pd.to_numeric(prefix.Volume,errors="coerce").notna().all())
    vwap=None
    if vol_available:
        today=prefix.index.map(lambda t:_day(t)==_day(prefix.index[-1]))
        intra=prefix.loc[today]
        v=pd.to_numeric(intra.Volume,errors="coerce")
        if len(intra) and (v>=0).all() and v.sum()>0:
            vwap=float((((intra.High+intra.Low+intra.Close)/3)*v).sum()/v.sum())
    return {
        "wave_structure":anchor.get("wave_structure","NIEZNANA"),
        "pattern":anchor.get("pattern","NIEZNANA"),
        "regime":anchor.get("regime","NIEZNANY"),
        "ema200_relation":"ABOVE" if cur.Close>ema200 else "BELOW",
        "ema200":round(ema200,4),
        "vwap_relation": ("ABOVE" if cur.Close>vwap else "BELOW")
                          if vwap is not None else "BRAK DANYCH",
        "volume_available":bool(vol_available),
        "wick_ratio":round(max(0.,wick/height),4),
        "large_rejection_wick":bool(wick/height>=.5),
        "false_break_at_pivot":falsebreak,
        "atr_ratio_20":round(atr_ratio,4) if atr_ratio is not None else None,
        "atr_rising":bool(atr_ratio>1.1) if atr_ratio is not None else None,
        "momentum_4_bars":round(float(bars.Close.iloc[-1]-bars.Close.iloc[-5]),4),
        "signal_et_hour":prefix.index[-1].tz_convert(NY).strftime("%H:%M"),
        "signal_close":round(float(cur.Close),4),
        "atr":round(atr,4),
    }


def _seek(frame, anchor_idx, side, support, breakout, atr, *, max_wait=8,
          max_retest=6):
    """Emit the first actually-known bar for B, C, D; never backdate."""
    sig={"A_RAW":anchor_idx, "B_BOS":None,
         "C_BOS_RETEST":None,"D_BREAKOUT_HOLD":None,"E_WAIT":None}
    tolerance=max(.05*atr,0.01)
    breakout_run=0
    for j in range(anchor_idx+1,min(len(frame),anchor_idx+max_wait+max_retest+2)):
        if not _continuous(frame,anchor_idx,j):
            break
        now=frame.iloc[j]
        prev=frame.iloc[j-1]
        if j<=anchor_idx+max_wait and sig["B_BOS"] is None:
            bos=(prev.Close>=support and now.Close<support-tolerance)
            if side=="LONG":bos=(prev.Close<=support and now.Close>support+tolerance)
            if bos:sig["B_BOS"]=j
        if sig["B_BOS"] is not None and sig["C_BOS_RETEST"] is None:
            elapsed=j-sig["B_BOS"]
            if 1<=elapsed<=max_retest:
                if side=="SHORT":
                    retest=now.High>=support-tolerance and now.Close<support
                else:
                    retest=now.Low<=support+tolerance and now.Close>support
                if retest:sig["C_BOS_RETEST"]=j
        if j<=anchor_idx+max_wait:
            beyond=(now.Close>breakout+tolerance if side=="SHORT"
                    else now.Close<breakout-tolerance)
            breakout_run=breakout_run+1 if beyond else 0
            if breakout_run==2:
                sig["D_BREAKOUT_HOLD"]=j
        if (sig["B_BOS"] is not None and sig["C_BOS_RETEST"] is not None
                and sig["D_BREAKOUT_HOLD"] is not None):
            break
    return sig


def _trade(frame, signal_idx, side, atr, *, rr, minutes, spread, slippage,
           split_ts=None, source="MODEL"):
    """SL-first, conservative candle OHLC simulation; no broker orders."""
    if minutes%15:
        return {"status":"BRAK DANYCH M15", "pnl_pts":None}
    target_bars=minutes//15
    if signal_idx+1>=len(frame) or not _continuous(frame,signal_idx,signal_idx+1):
        return {"status":"NO_NEXT_OPEN", "pnl_pts":None}
    if split_ts is not None and frame.index[signal_idx]<split_ts<=frame.index[signal_idx+1]:
        return {"status":"SPLIT_EMBARGO", "pnl_pts":None}
    quote_cols=["BidOpen","BidHigh","BidLow","BidClose",
                "AskOpen","AskHigh","AskLow","AskClose"]
    quotes=all(x in frame.columns for x in quote_cols)
    if not quotes and 0<len(set(quote_cols).intersection(frame.columns)):
        return {"status":"INCOMPLETE_BID_ASK", "pnl_pts":None}
    # All values below are hypothetical; mid is inferred from available price.
    bar=frame.iloc[signal_idx+1]
    if quotes:
        mid=(float(bar.BidOpen)+float(bar.AskOpen))/2.
        entry=float(bar.AskOpen)+slippage if side=="LONG" else float(bar.BidOpen)-slippage
        execution="BID_ASK_OHLC_MODEL"
    else:
        if "Spread" in frame.columns:
            spread0=float(frame.Spread.iloc[signal_idx])
            execution="LAST_KNOWN_CLOSE_SPREAD_MODEL"
        else:
            spread0=float(spread)
            execution="FIXED_SPREAD_ASSUMPTION"
        if spread0<0 or not isfinite(spread0):
            return {"status":"BAD_SPREAD", "pnl_pts":None}
        mid=float(bar.Open)
        entry=mid+(spread0/2+slippage) if side=="LONG" else mid-(spread0/2+slippage)
    risk=1.5*float(atr)
    if not isfinite(risk) or risk<=0:
        return {"status":"BAD_ATR", "pnl_pts":None}
    stop=mid-risk if side=="LONG" else mid+risk
    target=mid+rr*risk if side=="LONG" else mid-rr*risk
    mfe=-float("inf");mae=float("inf")
    last=None;exitval=None;status=None
    first=signal_idx+1
    for k in range(first,min(len(frame),first+target_bars)):
        if not _continuous(frame,signal_idx,k):
            if last is None:
                return {"status":"GAP_BEFORE_FIRST", "pnl_pts":None}
            # A discontinuity cannot retroactively justify an exit on
            # the previous candle. Don't manufacture a fill after a gap.
            return {"status":"INVALIDATED_GAP", "pnl_pts":None}
        row=frame.iloc[k]
        if quotes:
            hi=float(row.BidHigh if side=="LONG" else row.AskHigh)
            lo=float(row.BidLow if side=="LONG" else row.AskLow)
            open_exec=float(row.BidOpen if side=="LONG" else row.AskOpen)
            close_exec=float(row.BidClose if side=="LONG" else row.AskClose)
            exitspread=0.
        else:
            exitspread=(float(frame.Spread.iloc[k-1]) if "Spread" in frame.columns
                        else float(spread))
            if not isfinite(exitspread) or exitspread<0:
                return {"status":"BAD_SPREAD", "pnl_pts":None}
            hi=float(row.High);lo=float(row.Low)
            open_exec=float(row.Open)
            close_exec=float(row.Close)
        good_move=(hi-entry if side=="LONG" else entry-lo)
        bad_move=(lo-entry if side=="LONG" else entry-hi)
        mfe=max(mfe,good_move)
        mae=min(mae,bad_move)
        if side=="LONG":
            if lo<=stop:
                exitval=min(stop,open_exec)-exitspread/2-slippage
                status="SL"
            elif hi>=target:
                exitval=target-exitspread/2-slippage
                status="TP"
        else:
            if hi>=stop:
                exitval=max(stop,open_exec)+exitspread/2+slippage
                status="SL"
            elif lo<=target:
                exitval=target+exitspread/2+slippage
                status="TP"
        last=k
        if exitval is not None:
            break
    if last is None:
        return {"status":"NO_EXIT_BAR", "pnl_pts":None}
    if exitval is None and last-first+1 < target_bars:
        # Early closing at 16 ET is a scheduled, observable time boundary.
        # File truncation before this session close is NOT a valid fill.
        clock=frame.index[last].tz_convert(NY)
        if (clock.hour,clock.minute)!=(16,0):
            return {"status":"INCOMPLETE_HORIZON", "pnl_pts":None}
    if exitval is None:
        lastrow=frame.iloc[last]
        if quotes:
            exitval=float(lastrow.BidClose if side=="LONG" else lastrow.AskClose)
        else:
            endspread=(float(lastrow.Spread) if "Spread" in frame.columns
                       else float(spread))
            if endspread<0 or not isfinite(endspread):
                return {"status":"BAD_SPREAD", "pnl_pts":None}
            exitval=float(lastrow.Close)-endspread/2 if side=="LONG" else float(lastrow.Close)+endspread/2
        exitval+=(-slippage if side=="LONG" else slippage)
        status=status or ("TIMEOUT" if last-first+1>=target_bars else "SESSION_TIMEOUT")
    if split_ts is not None and frame.index[signal_idx]<split_ts<=frame.index[last]:
        return {"status":"SPLIT_EMBARGO", "pnl_pts":None}
    pnl=(exitval-entry if side=="LONG" else entry-exitval)
    return {"status":status, "pnl_pts":round(pnl,4),
            "r_net":round(pnl/risk,4),"mfe_pts":round(mfe,4),
            "mae_pts":round(mae,4),
            "exit_min":15*(last-first+1),
            "entry_utc":frame.index[first],"exit_utc":frame.index[last],
            "entry_executable":round(entry,4),"exit_executable":round(exitval,4),
            "stop_mid":round(stop,4),"target_mid":round(target,4),
            "execution":execution, "strategy_version":VERSION,
            "spread_assumption":spread,"slippage":slippage}


def _features_direction(anchor, context, side):
    """Attach pre-entry, as-of features; never use whether trade later won."""
    same=anchor["direction"]==side
    return {
        "anchor_extremum":"THIRD_PEAK" if anchor["direction"]=="SHORT" else "THIRD_TROUGH",
        "anchor_side":anchor["direction"],"direction":side,
        **context,
        "is_contrarian":same,
    }


def run_wave_abcd(frame:pd.DataFrame, *, anchors=None, spread=2.,
                  slippage=.25, rr=1.5, hold_minutes=120,
                  split=.70, max_wait=8):
    """Freeze a common third-wave opportunity cohort for A/B/C/D/E.

    70/30 is chronological exploratory holdout, NOT statistical validation
    after inspected many configurations. Never auto-select a winner.
    """
    validate_closed_m15(frame)
    if not .5<=split<=.85 or rr<=0 or spread<0 or slippage<0:
        raise ValueError("Bad split, risk/reward or costs")
    if hold_minutes not in M15_EXITS_MIN:
        raise ValueError("M15 cannot reconstruct 10/20 minute exits: upload M1/M5")
    if anchors is None:
        all_events=detect_waves(frame)
        anchors=all_events[(all_events.wave_count==3)&
                           (all_events.confirmation=="RAW")]
    if anchors is None or len(anchors)==0:
        return summarize_wave_runs(pd.DataFrame(),frame),pd.DataFrame(),{
            "anchors":0,"proven_edge":False,"source":"M15","reason":"BRAK TRZECICH PIVOTÓW"}
    sorted_anchors=anchors.sort_values("signal_utc")
    loc_map={t:i for i,t in enumerate(frame.index)}
    bound=frame.index[int(len(frame)*split)]
    records=[]; last_by_group={}
    for _,a in sorted_anchors.iterrows():
        timestamp=pd.Timestamp(a.signal_utc)
        i=loc_map.get(timestamp)
        if i is None or i<210:
            continue  # full EMA200 warmup; don't fake it from short window
        side=str(a.direction)
        if side not in ("SHORT","LONG"):
            continue
        # One anchor per day / direction; further same-day third waves are
        # diagnostically correlated, not independent trading observations.
        dedup_key=(_day(timestamp),side)
        if dedup_key in last_by_group:
            continue
        last_by_group[dedup_key]=timestamp
        feature=_context(frame,i,a)
        atr=feature["atr"]
        support=float(a.bos_level)
        # A peak's resistance, trough's support are immutable at RAW signal.
        j0=max(0,i-15)
        breakout=(float(frame.High.iloc[j0:i+1].max()) if side=="SHORT"
                  else float(frame.Low.iloc[j0:i+1].min()))
        signals=_seek(frame,i,side,support,breakout,atr,max_wait=max_wait)
        period="WCZESNIEJSZE" if timestamp<bound else "POZNIEJSZE"
        for variant in VARIANTS:
            signal_idx=signals[variant]
            decision_side=("LONG" if side=="SHORT" else "SHORT") if variant=="D_BREAKOUT_HOLD" else side
            base={"anchor_id":str(a.event_id),"anchor_utc":timestamp,
                  "event_year":int(timestamp.year),"period":period,
                  "variant":variant,"wave_count":3,
                  "signal_utc":(frame.index[signal_idx] if signal_idx is not None else pd.NaT),
                  "triggered":signal_idx is not None,
                  "anchor_stop_level":support,"breakout_level":breakout,
                  "bars_after_anchor":(signal_idx-i if signal_idx is not None else None),
                  "source_tf":"M15",**_features_direction(a,feature,decision_side)}
            if variant=="E_WAIT":
                records.append({**base,"status":"WAIT","pnl_pts":None,"exit_min":None})
            elif signal_idx is None:
                records.append({**base,"status":"NOT_TRIGGERED","pnl_pts":None})
            else:
                result=_trade(frame,signal_idx,decision_side,atr,
                              rr=rr,minutes=hold_minutes,spread=spread,
                              slippage=slippage,split_ts=bound)
                records.append({**base,**result})
    logs=pd.DataFrame(records)
    metadata={"anchors":(len(logs)//len(VARIANTS)),"proven_edge":False,
              "version":VERSION,"oos_cutoff":str(bound),
              "total_candles":len(frame),"interval":"M15",
              "assumed_roundtrip_spread":spread,
              "simulated_slippage_each_side":slippage,
              "bidask_full":all(c in frame for c in (
                  "BidOpen","BidHigh","BidLow","BidClose",
                  "AskOpen","AskHigh","AskLow","AskClose")),
              "unsupported_m15_exits_minutes":M15_UNSUPPORTED_MIN,
              "replay_limits":"NY cash session only; SL-first OHLC; as-of pivots; no broker fills",
              "warnings":["No independently available 2021-2026 source M15 in this session",
                          "A/B/C/D have different trigger rates and entry times; do not compare per-trade PnL as causal proof",
                          "The 70/30 holdout has been exposed; new untouched forward data required",
                          "Sampling one third-wave anchor per session/direction is conservative; no portfolio aggregation",
                          "No adjustment for many tested hypothesis combinations; no automatic deployment"]}
    return summarize_wave_runs(logs,frame),logs,metadata


def summarize_wave_runs(logs,frame):
    """All 5 options per SHORT/LONG in each sample + per year, no fake scores."""
    years=sorted({int(t.year) for t in frame.index})
    summary=[]
    for phase in ("WCZESNIEJSZE","POZNIEJSZE"):
        for side in ("SHORT","LONG"):
            for variant in VARIANTS:
                if logs.empty: subset=pd.DataFrame()
                else: subset=logs[(logs.period==phase)&(logs.anchor_side==side)&(logs.variant==variant)]
                scores=subset.loc[subset.pnl_pts.notna()] if len(subset) else pd.DataFrame()
                # E WAIT is a no-trade benchmark, not a zero-risk profit factory.
                pnl=scores.pnl_pts.astype(float).tolist() if len(scores) else []
                n=len(pnl)
                hits=sum(x>0 for x in pnl)
                gross_profit=sum(x for x in pnl if x>0)
                gross_loss=-sum(x for x in pnl if x<0)
                eq=0.;hi=0.;drawdown=0.
                for x in pnl:
                    eq+=x;hi=max(hi,eq);drawdown=max(drawdown,hi-eq)
                avg=sum(pnl)/n if n else None
                sd=float(np.std(pnl,ddof=1)) if n>=2 else None
                lower=avg-1.96*sd/sqrt(n) if n>=2 else None
                if n<30: status="BRAK DANYCH" if n==0 else "MAŁA PRÓBA"
                else: status="WYMAGA NOWEGO FORWARD — BRAK DOWODU PRZEWAGI"
                row={"period":phase,"anchor_side":side,"variant":variant,
                     "eligible_anchors":len(subset),
                     "triggered":int(subset.triggered.sum()) if len(subset) else 0,
                     "closed":n,"win":hits,"win_pct":round(100*hits/n,2) if n else None,
                     "tp":int((scores.status=="TP").sum()) if n else 0,
                     "sl":int((scores.status=="SL").sum()) if n else 0,
                     "timeout":int(scores.status.str.contains("TIMEOUT").sum()) if n else 0,
                     "net_pts":round(sum(pnl),2) if n else None,
                     "expectancy_pts":round(avg,3) if avg is not None else None,
                     "net_mean_lower95":round(lower,3) if lower is not None else None,
                     "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else None,
                     "max_drawdown_pts":round(drawdown,2) if n else None,
                     "mfe_avg_pts":round(float(scores.mfe_pts.mean()),3) if n else None,
                     "mae_avg_pts":round(float(scores.mae_pts.mean()),3) if n else None,
                     "avg_exit_min":round(float(scores.exit_min.mean()),2) if n else None,
                     "status":status}
                summary.append(row)
                for year in years:
                    if logs.empty: annual=pd.DataFrame()
                    else: annual=subset.loc[subset.event_year==year]
                    score=annual.loc[annual.pnl_pts.notna()] if len(annual) else pd.DataFrame()
                    vals=score.pnl_pts.astype(float) if len(score) else pd.Series(dtype=float)
                    summary.append({**{k:v for k,v in row.items() if k not in (
                        "eligible_anchors","triggered","closed","win","win_pct","tp","sl","timeout",
                        "net_pts","expectancy_pts","net_mean_lower95","profit_factor","max_drawdown_pts",
                        "mfe_avg_pts","mae_avg_pts","avg_exit_min","status")},
                        "year":year,"eligible_anchors":len(annual),
                        "triggered":int(annual.triggered.sum()) if len(annual) else 0,
                        "closed":len(vals),"win":int((vals>0).sum()),
                        "net_pts":round(float(vals.sum()),2) if len(vals) else None,
                        "expectancy_pts":round(float(vals.mean()),3) if len(vals) else None,
                        "profit_factor":round(float(vals[vals>0].sum()/-vals[vals<0].sum()),3)
                        if len(vals) and (vals<0).any() else None,
                        "status":"BADANIE ROCZNE" if len(vals) else "BRAK DANYCH"})
    output=pd.DataFrame(summary)
    if "year" not in output: output["year"]=pd.NA
    return output
