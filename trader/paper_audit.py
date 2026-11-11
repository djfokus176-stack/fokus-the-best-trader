"""Read-only PAPER v3 diagnostic summaries and safe CSV export.

Never extrapolate a strategy label from side/entry time. Original PAPER
positions have strategy, trade_id and signal provenance in the SQLite/
Supabase checkpoint; the compact terminal journal used to omit them.
These are modeled P&L points, NOT actual fills or a trading recommendation.
"""
from __future__ import annotations

import pandas as pd

FINISHED = ("CLOSED_SL","CLOSED_TP","CLOSED_TIMEOUT")
EXPORT_COLUMNS = (
    "trade_id","strategy","epic","source","timeframe","setup_utc",
    "entry_assumed_utc","opened_utc","entry_detected_utc","closed_utc",
    "side","status","setup_reason","entry_mid","entry_executable",
    "initial_risk_mid","stop_mid","target_mid","original_target_mid",
    "exit_mid","exit_executable","setup_spread","slippage","bars_held",
    "pnl_pts","close_reason","exit_policy","model_version",
)


def paper_export_table(positions: list[dict]) -> pd.DataFrame:
    """Return only documented non-secret position fields; preserve attribution."""
    frame=pd.DataFrame(positions or [])
    return pd.DataFrame({c:frame[c] if c in frame else pd.Series(dtype=object)
                         for c in EXPORT_COLUMNS}).reindex(columns=EXPORT_COLUMNS)


def paper_strategy_audit(positions: list[dict]) -> tuple[pd.DataFrame,dict]:
    """Summary of CLOSED records only, never count PENDING/OPEN as losses."""
    empty={"n":0,"sum_pts":0.0,"profitable":0,"sl":0,
           "tp":0,"timeout":0,"named_positions":0}
    frame=pd.DataFrame(positions or [])
    required={"status","pnl_pts","side"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(),empty
    closed=frame[frame["status"].isin(FINISHED)].copy()
    closed["pnl_pts"]=pd.to_numeric(closed["pnl_pts"],errors="coerce")
    closed=closed.loc[closed["pnl_pts"].notna()].copy()
    if closed.empty:
        return pd.DataFrame(),empty
    if "strategy" not in closed.columns:
        closed["strategy"]="NIEUSTALONA"
    closed["strategy"]=closed["strategy"].fillna("NIEUSTALONA").astype(str)
    closed.loc[closed.strategy.str.strip()=="","strategy"]="NIEUSTALONA"
    closed["side"]=closed["side"].astype(str)
    closed["positive"]=closed["pnl_pts"]>0
    closed["is_sl"]=closed["status"]=="CLOSED_SL"
    closed["is_tp"]=closed["status"]=="CLOSED_TP"
    closed["is_timeout"]=closed["status"]=="CLOSED_TIMEOUT"
    overview={
        "n":len(closed),
        "sum_pts":round(float(closed.pnl_pts.sum()),2),
        "profitable":int(closed.positive.sum()),
        "sl":int(closed.is_sl.sum()),
        "tp":int(closed.is_tp.sum()),
        "timeout":int(closed.is_timeout.sum()),
        "named_positions":int((closed.strategy!="NIEUSTALONA").sum()),
    }
    results=(closed.groupby(["strategy","side"],dropna=False,sort=True)
             .agg(liczba=("pnl_pts","size"),
                  zyskowne=("positive","sum"),
                  trafione_tp=("is_tp","sum"),
                  zamkniete_sl=("is_sl","sum"),
                  timeout=("is_timeout","sum"),
                  suma_pkt=("pnl_pts","sum"),
                  srednio_pkt=("pnl_pts","mean"))
             .reset_index())
    results["skutecznosc_pnl_pct"]=(100*results.zyskowne/results.liczba).round(1)
    results["suma_pkt"]=results["suma_pkt"].round(2)
    results["srednio_pkt"]=results["srednio_pkt"].round(2)
    results["przykladow_za_malo"]=results.liczba<30
    results=results.sort_values(["suma_pkt","liczba"],
                                ascending=[False,False]).reset_index(drop=True)
    return results,overview
