"""Reproducible causal MTF comparison on an offline M1 CLOSED-time CSV.

CSV Time MUST mean UTC candle CLOSE. 5m/15m/H1 candles are DERIVED from
complete groups of M1 data, not independent Capital.com higher-timeframe
feeds. No current-time freshness checks in a historical simulation.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from .market import PERIOD
from .mtf import trend_from_closed
from .strategy import indicators
from .strategies_pro import ALL_STRATEGIES
from .research import replay, stats

RESOLUTIONS={"MINUTE_5":"5min","MINUTE_15":"15min","HOUR":"1h"}
PERIOD_COUNTS={"MINUTE_5":5,"MINUTE_15":15,"HOUR":60}

def validate_close_time_m1(m1: pd.DataFrame) -> None:
    if m1 is None or m1.empty:
        raise ValueError("Brak danych M1 CSV.")
    if not isinstance(m1.index,pd.DatetimeIndex) or m1.index.tz is None:
        raise ValueError("CSV wymaga indeksu strefowego UTC, czas ZAMKNIĘCIA świecy.")
    if not m1.index.is_monotonic_increasing or m1.index.has_duplicates:
        raise ValueError("Indeks M1 musi być rosnący i unikalny.")
    if not (m1.index==m1.index.floor("min")).all():
        raise ValueError("Każdy timestamp zamknięcia musi być dokładną minutą.")
    if not {"Open","High","Low","Close","Spread"}.issubset(m1.columns):
        raise ValueError("Wymagane kolumny OHLC i Spread.")
    if m1[["Open","High","Low","Close","Spread"]].isna().any().any():
        raise ValueError("Puste OHLC/Spread.")
    if (m1.Spread<0).any():
        raise ValueError("Ujemny spread.")
    if ((m1.High<m1[["Open","Low","Close"]].max(axis=1)) |
        (m1.Low>m1[["Open","High","Close"]].min(axis=1))).any():
        raise ValueError("Niespójne OHLC.")
    if m1.index.tz is None:
        raise ValueError("Wymagana strefa UTC.")


def build_higher_closed_bars(m1: pd.DataFrame) -> dict[str,pd.DataFrame]:
    """Only complete 5/15/60-minute groups; never leak incomplete hour."""
    validate_close_time_m1(m1)
    # Timezone-aware UTC anchors ensure correct right-labeled CLOSE timestamps.
    utc=m1.tz_convert("UTC")
    result={}
    for tf,rule in RESOLUTIONS.items():
        aggregation={"Open":"first","High":"max","Low":"min",
                     "Close":"last","Spread":"last"}
        groups=utc.resample(rule,label="right",closed="right",origin="epoch")
        higher=groups.agg(aggregation)
        higher["_bar_count"]=groups["Close"].count()
        # Each underlying timestamp is on the UTC minute grid, unique.
        # Exact count therefore ensures ALL expected minute closes are present.
        valid=higher["_bar_count"]==PERIOD_COUNTS[tf]
        result[tf]=higher.loc[valid].drop(columns=["_bar_count"])
    return result


@dataclass
class HistoricalMTFGate:
    """Precompute EMA/ATR trends just once, then binary search by signal time."""
    m1: pd.DataFrame
    higher: dict[str,pd.DataFrame]

    def __post_init__(self):
        self.series={}
        for tf,raw in self.higher.items():
            df=indicators(raw)
            if df.empty:
                self.series[tf]=pd.Series(dtype="object")
                continue
            up=(df.EMA9>df.EMA21)&(df.EMA21>df.EMA50)
            down=(df.EMA9<df.EMA21)&(df.EMA21<df.EMA50)
            out=pd.Series("NEUTRAL",index=df.index,dtype="object")
            out.loc[up]="UP";out.loc[down]="DOWN"
            out.iloc[:69]="UNKNOWN"
            out.loc[df.ATR.isna() | (df.ATR<=0)]="UNKNOWN"
            self.series[tf]=out

    def consensus(self, signal_closed_utc) -> str:
        """Match the actual live MTF rule: 2 of 3 HTF trends, no opposition."""
        t=pd.Timestamp(signal_closed_utc)
        if t.tzinfo is None:
            return "WAIT"
        # Avoid action at the beginning of a break in M1 sampling.
        loc=int(self.m1.index.searchsorted(t,side="right")-1)
        if loc<69 or self.m1.index[loc]!=t:
            return "WAIT"
        if (self.m1.index[loc]-self.m1.index[loc-1]).total_seconds()>60:
            return "WAIT"
        trends=[]
        for tf in ("MINUTE_5","MINUTE_15","HOUR"):
            ts=self.series[tf]
            last_idx=int(ts.index.searchsorted(t,side="right")-1)
            if last_idx<69:
                return "WAIT"
            closed_time=ts.index[last_idx]
            # A completed HTF candle must be <= signal time and recent enough.
            if closed_time>t or (t-closed_time).total_seconds()>=PERIOD[tf]:
                return "WAIT"
            direction=str(ts.iloc[last_idx])
            if direction=="UNKNOWN":
                return "WAIT"
            trends.append(direction)
        ups=trends.count("UP")
        downs=trends.count("DOWN")
        if ups>=2 and downs==0:
            return "UP"
        if downs>=2 and ups==0:
            return "DOWN"
        return "NEUTRAL"

    def allow(self, decision, signal_closed_utc) -> bool:
        expected="UP" if decision.action=="LONG" else "DOWN"
        return self.consensus(signal_closed_utc)==expected


def compare_mtf_on_m1_csv(m1:pd.DataFrame, strategies=ALL_STRATEGIES,
                           spread=.6, slippage=.25, holding=20, split=.7,
                           max_candles=6000):
    """Same fixed setup rules on chronological 70/30 split, with/without MTF.

    Rules are NOT optimized on either sample. This compares two independent
    non-overlapping position sequences, not identical trades pair-by-pair.
    At least 70 fully completed H1 bars are required before MTF is evaluable.
    """
    validate_close_time_m1(m1)
    if len(m1)>max_candles:
        raise ValueError(f"Za dużo świec ({len(m1)}): w tej wersji limit {max_candles}. Podziel CSV na niezależne okresy.")
    if len(m1)<4600:
        raise ValueError("MTF z H1 wymaga >=70 pełnych godzin M1 + miejsca na holdout: przygotuj co najmniej 4600 świec.")
    if not (0.5<=split<=0.85) or spread<0 or slippage<0 or holding<2:
        raise ValueError("Nieprawidłowe parametry replay.")
    higher=build_higher_closed_bars(m1)
    if len(higher["HOUR"])<70:
        raise ValueError("Za mało pełnych godzin H1; luki M1 uniemożliwiają rzetelny MTF.")
    gate=HistoricalMTFGate(m1,higher)
    bound=int(len(m1)*split)
    output=[];trade_rows=[]
    for name in strategies:
        for period,start,end in (("WCZEŚNIEJSZE / 70%",85,bound),
                                 ("PÓŹNIEJSZE / 30%",max(85,bound),len(m1))):
            for variant in ("BEZ MTF","Z MTF"):
                counted={"candidates":0,"rejected":0,"passed":0}
                def trade_filter(decision,stamp):
                    counted["candidates"]+=1
                    accepted=gate.allow(decision,stamp)
                    counted["passed" if accepted else "rejected"]+=1
                    return accepted
                trades=replay(m1,name,spread=spread,slippage=slippage,holding=holding,
                              evaluation_start=start,evaluation_end=end,
                              trade_gate=trade_filter if variant=="Z MTF" else None,
                              max_history=350)
                metrics=stats(trades)
                output.append({"strategia":name,"okres":period,"wariant":variant,
                     "kandydaci_mtf":counted["candidates"] if variant=="Z MTF" else None,
                     "odrzucone_mtf":counted["rejected"] if variant=="Z MTF" else None,
                     "zaakceptowane_mtf":counted["passed"] if variant=="Z MTF" else None,
                     **metrics})
                if not trades.empty:
                    trade_copy=trades.copy()
                    trade_copy["okres"]=period
                    trade_copy["wariant"]=variant
                    trade_rows.append(trade_copy)
    return (pd.DataFrame(output),
            pd.concat(trade_rows,ignore_index=True) if trade_rows else
            pd.DataFrame(columns=["time_utc","strategy","side","status","pnl_pts","wariant","okres"]),
            {k:len(v) for k,v in higher.items()})
