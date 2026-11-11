"""Independent nine-way TP/holding research on the EXACT SAME M1 entries.

For one predeclared strategy (default EMA TREND), identify each hypothetical
signal from an as-of CLOSED M1 prefix. Reserve 30 future bars for every
qualifying signal, regardless of how quickly any specific exit variant would
close. This gives all nine variants the SAME timestamps, side, entry and SL.
No HTF, news/macro, session-status or worker execution is reproduced.

Entry MID is the next candle's OPEN, reconstructed ONLY after it closes.
OHLC stop-first convention, adverse slippage and last-known spreads are
consistent with trader.research; never claim tick-level broker fills.
Research only: never changes AUTO, worker, PAPER, Supabase or live orders.
"""
from __future__ import annotations

from math import isfinite, sqrt
from zoneinfo import ZoneInfo

import pandas as pd

from .research import stats, _consecutive_future, _bars_through_exit
from .strategy import simulate_outcome
from .strategies_pro import decide_any, ALL_STRATEGIES

R_MULTIPLES = (1.0, 1.5, 2.0)
HOLDINGS = (10, 20, 30)
NY = ZoneInfo("America/New_York")
COLUMNS = (
    "sygnal_utc", "rok", "sesja_et", "okres", "strategia", "strona",
    "wejscie_mid", "sl_mid", "tp_mid", "rr_tp", "limit_m1",
    "status", "pnl_pts", "gross_mid_pts", "koszty_pkt", "r_net",
    "spread_model", "spread_wejscie", "spread_wyjscie", "candle_exit_utc",
)


def _validate(frame, strategy, spread, slippage, split, spread_mode):
    if (frame is None or not isinstance(frame,pd.DataFrame) or
            not 220 <= len(frame) <= 6500):
        raise ValueError("Test potrzebuje 220–6500 zamkniętych M1.")
    if strategy not in ALL_STRATEGIES:
        raise ValueError("Porównanie dotyczy wyłącznie sześciu istniejących metod.")
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Czas świec M1 musi mieć strefę UTC.")
    if (not frame.index.is_monotonic_increasing or frame.index.has_duplicates or
            not {"Open","High","Low","Close"}.issubset(frame.columns)):
        raise ValueError("Wymagane uporządkowane i unikalne świeczki OHLC M1.")
    if not .5 <= split <= .85 or spread_mode not in ("fixed","historical"):
        raise ValueError("Niepoprawny chronologiczny podział lub model spreadu.")
    if not all(isfinite(float(v)) and float(v)>=0 for v in (spread,slippage)):
        raise ValueError("Spread i poślizg muszą być skończone i nieujemne.")
    if spread_mode=="historical":
        if "Spread" not in frame.columns:
            raise ValueError("Brak kolumny Spread w historycznym CSV.")
        values=pd.to_numeric(frame["Spread"],errors="coerce")
        if (values.isna().any() or (values<0).any() or
                not values.map(isfinite).all()):
            raise ValueError("Nieprawidłowy historyczny spread M1.")


def _outcome_for_variant(future, *, side, entry, stop, target,
                         entry_spread, slippage, hold, spread_mode,
                         prior_spreads):
    selected=future.iloc[:hold]
    dynamic=(prior_spreads[:hold] if spread_mode=="historical" else None)
    status, pnl=simulate_outcome(selected,side,entry,stop,target,
                                entry_spread,slippage,exit_spreads=dynamic)
    if status in ("SKIPPED_GAP","INVALIDATED_GAP"):
        raise ValueError("Wejście poza SL/TP albo luka — nie liczę wyniku.")
    if status=="PENDING":
        status="TIMEOUT"
        bars=hold
        exit_mid=float(selected.iloc[-1].Close)
        exit_spread=(float(selected.iloc[-1].Spread)
                     if spread_mode=="historical" else entry_spread)
    else:
        bars=_bars_through_exit(selected,side,stop,target)
        bar=selected.iloc[bars-1]
        exit_spread=(prior_spreads[bars-1] if spread_mode=="historical"
                     else entry_spread)
        if status=="WIN":
            exit_mid=target
        else:
            exit_mid=(min(stop,float(bar.Open)) if side=="LONG"
                      else max(stop,float(bar.Open)))
    gross=(exit_mid-entry if side=="LONG" else entry-exit_mid)
    modeled_cost=(entry_spread+exit_spread)/2+2*slippage
    if status=="TIMEOUT":
        pnl=round(gross-modeled_cost,2)
    # The same fees are charged for every TP/SL/TIMEOUT exit.
    # Include gross result separately to isolate price behavior vs fees.
    risk=abs(entry-stop)+entry_spread+2*slippage
    return (status,round(float(pnl),2),round(float(gross),3),
            round(float(modeled_cost),3),round(float(pnl)/risk,4),
            float(exit_spread),selected.index[bars-1])


def compare_same_entries(frame:pd.DataFrame, *, strategy="EMA TREND",
                         spread=.6, slippage=.25, split=.7,
                         spread_mode="fixed"):
    """(summary, per_exit_trade, metadata) without changing AUTO entries.

    The first 120 bars are research warmup. Separate chronological 70/30
    windows, and reserve the full 30 M1 bars inside each window, so a
    TRAIN entry never uses HOLDOUT candles as its hypothetical future.
    Different exit variants are *paired*: exactly the same frozen entries.
    The holdout is a comparative diagnostic, NOT untouched after this run.
    """
    _validate(frame,strategy,spread,slippage,split,spread_mode)
    start=120
    boundary=start+int((len(frame)-start)*split)
    phases=(("WCZESNIEJSZE 70%",start,boundary),
            ("POZNIEJSZE 30%",boundary,len(frame)))
    events=[]
    counts={}
    # Conservative 30-bar embargo between frozen signals, identical for
    # every variant; active-position timing never changes candidate set.
    for phase,lo,hi in phases:
        i=lo
        counters={"sprawdzone_m1":0,"sygnaly_surowe":0,
                  "kwalifikowane":0,"odrzucone_luki":0,
                  "odrzucone_wejscia":0}
        while i+max(HOLDINGS)<=hi:
            counters["sprawdzone_m1"]+=1
            prefix=frame.iloc[max(0,i-160):i]
            entry_spread=(float(frame.Spread.iloc[i-1])
                          if spread_mode=="historical" else float(spread))
            decision=decide_any(prefix,strategy,spread=entry_spread)
            if decision.action not in ("LONG","SHORT"):
                i+=1
                continue
            counters["sygnaly_surowe"]+=1
            future,gap=_consecutive_future(
                frame.iloc[i:i+max(HOLDINGS)],frame.index[i-1])
            if gap or len(future)!=max(HOLDINGS):
                counters["odrzucone_luki"]+=1
                i+=max(HOLDINGS)
                continue
            entry=float(future.iloc[0].Open)
            side=decision.action
            stop=float(decision.stop)
            original_target=float(decision.target)
            if not ((stop<entry<original_target) if side=="LONG" else
                    (original_target<entry<stop)):
                counters["odrzucone_wejscia"]+=1
                i+=max(HOLDINGS)
                continue
            risk=abs(entry-stop)
            if not isfinite(risk) or risk<=0:
                counters["odrzucone_wejscia"]+=1
                i+=max(HOLDINGS)
                continue
            counters["kwalifikowane"]+=1
            signal_at=frame.index[i-1]
            ny=signal_at.tz_convert(NY)
            cash=(ny.weekday()<5 and
                  (9*60+30)<=ny.hour*60+ny.minute<16*60)
            session="GODZINY USA 09:30-16 ET" if cash else "POZA GODZINAMI USA"
            spreads=([float(v) for v in frame.Spread.iloc[i-1:i+29]]
                     if spread_mode=="historical" else None)
            for rr in R_MULTIPLES:
                target=entry+(risk*rr if side=="LONG" else -risk*rr)
                for hold in HOLDINGS:
                    status,pnl,gross,cost,r_net,exit_spread,exit_at=(
                        _outcome_for_variant(
                            future,side=side,entry=entry,stop=stop,target=target,
                            entry_spread=entry_spread,slippage=slippage,
                            hold=hold,spread_mode=spread_mode,
                            prior_spreads=spreads))
                    events.append(dict(
                        sygnal_utc=signal_at,rok=int(signal_at.year),
                        sesja_et=session,okres=phase,strategia=strategy,
                        strona=side,wejscie_mid=round(entry,3),
                        sl_mid=round(stop,3),tp_mid=round(target,3),
                        rr_tp=rr,limit_m1=hold,status=status,pnl_pts=pnl,
                        gross_mid_pts=gross,koszty_pkt=cost,r_net=r_net,
                        spread_model=spread_mode,spread_wejscie=entry_spread,
                        spread_wyjscie=exit_spread,candle_exit_utc=exit_at))
            i+=max(HOLDINGS)
        counts[phase]=counters
    details=pd.DataFrame(events,columns=COLUMNS)
    summary=[]
    for phase,_,_ in phases:
        for rr in R_MULTIPLES:
            for hold in HOLDINGS:
                trades=details[(details.okres==phase)&
                    (details.rr_tp==rr)&(details.limit_m1==hold)]
                metric=stats(trades.rename(columns={"status":"status",
                           "pnl_pts":"pnl_pts","r_net":"r_net"}))
                # Stats counts WIN as TP, not any positive timeouts.
                n=metric["n"]
                if n>=2:
                    mean=float(trades.pnl_pts.mean())
                    sd=float(trades.pnl_pts.std(ddof=1))
                    lower95=mean-1.96*sd/sqrt(n)
                else:
                    lower95=None
                summary.append({
                    "okres":phase,"strategia":strategy,"rr_tp":rr,
                    "limit_m1":hold,"proby":n,
                    "tp":metric["wins"],"sl":int((trades.status=="LOSS").sum()),
                    "timeout":metric["timeouts"],
                    "zyskowne":metric["profitable_trades"],
                    "zyskowne_pct":metric["pnl_win_rate_pct"],
                    "profit_factor":metric["profit_factor"],
                    "srednio_pkt":metric["expectancy_pts"],
                    "suma_pkt":metric["sum_pts"],
                    "max_dd_pkt":metric["max_drawdown_pts"],
                    "srednio_r":metric["avg_r"],
                    "suma_przed_kosztami":round(float(trades.gross_mid_pts.sum()),2),
                    "suma_kosztow":round(float(trades.koszty_pkt.sum()),2),
                    "dolny95_srednio_pkt":(
                        round(lower95,3) if lower95 is not None else None),
                    "status":("BRAK SYGNAŁÓW" if n==0 else
                              "MAŁA PRÓBA (<30)" if n<30 else
                              "BADANIE — BRAK POTWIERDZONEJ PRZEWAGI"),
                })
    result=pd.DataFrame(summary)
    # Every combination must share exactly the same signals within period.
    for phase,_,_ in phases:
        series=result[result.okres==phase].proby
        if series.nunique()!=1:
            raise AssertionError("Warianty wyjścia nie używają tych samych wejść.")
    metadata={"counts":counts,"strategy":strategy,"spread_mode":spread_mode,
              "split_after_utc":str(frame.index[boundary]),
              "samples":len(frame),"interval":"M1",
              "mtf":"NIE — RAW OHLC, BEZ BLOKAD WORKERA",
              "fill":"MODELOWANY następny OPEN; nie rzeczywisty broker BID/ASK",
              "status":"BADANIE; 9 porównań na tym samym zbiorze, bez automatycznej promocji"}
    return result,details,metadata
