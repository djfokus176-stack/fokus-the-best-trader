"""PAPER v3 performance on CLOSED positions only, separated from replay."""
from __future__ import annotations
import sqlite3
from zoneinfo import ZoneInfo
import pandas as pd
from .paper_lifecycle import ensure_tables

COMPLETE=("CLOSED_SL","CLOSED_TP","CLOSED_TIMEOUT")
WARSAW=ZoneInfo("Europe/Warsaw")

def _metrics(frame):
    if frame.empty:
        return {"liczba":0,"TP":0,"SL":0,"timeout":0,"win_rate_pct":None,
                "expectancy_pkt":None,"suma_pkt":0.0,"avg_R":None,
                "profit_factor":None,"max_drawdown_pkt":0.0}
    frame=frame.sort_values(["closed_utc","trade_id"])
    pnl=frame.pnl_pts.astype(float)
    curve=pnl.cumsum()
    dd=curve-curve.cummax().clip(lower=0)
    denominator=(frame.entry_mid-frame.stop_mid).abs()+frame.setup_spread+2*frame.slippage
    r=pnl/denominator.where(denominator>0,float("nan"))
    gross_up=pnl[pnl>0].sum()
    gross_down=-pnl[pnl<0].sum()
    return {"liczba":len(frame),"TP":int((frame.status=="CLOSED_TP").sum()),
            "SL":int((frame.status=="CLOSED_SL").sum()),
            "timeout":int((frame.status=="CLOSED_TIMEOUT").sum()),
            "win_rate_pct":round(100*float((pnl>0).mean()),2),
            "expectancy_pkt":round(float(pnl.mean()),3),
            "suma_pkt":round(float(pnl.sum()),2),
            "avg_R":round(float(r.mean()),3),
            "profit_factor":round(float(gross_up/gross_down),3)
                            if gross_down>0 else None,
            "max_drawdown_pkt":round(max(0.0,-float(dd.min())),2)}


def daily_weekly(db, source="Capital.com DEMO REST", epic=None):
    """Never merge archived signal v2 or CSV research with ongoing PAPER v3."""
    ensure_tables(db)
    db.row_factory=sqlite3.Row
    query="""SELECT * FROM paper_positions_v3
             WHERE status IN ('CLOSED_SL','CLOSED_TP','CLOSED_TIMEOUT')
             AND source=?"""
    params=[source]
    if epic is not None:
        query+=" AND epic=?"
        params.append(epic)
    query+=" ORDER BY closed_utc ASC,trade_id ASC"
    # Full available on-disk archive, no artificial 1000-position truncation.
    all_rows=pd.DataFrame([dict(r) for r in db.execute(query,tuple(params))])
    if all_rows.empty:
        return pd.DataFrame(),pd.DataFrame(),_metrics(all_rows)
    all_rows["closed_local"]=pd.to_datetime(all_rows.closed_utc,utc=True).dt.tz_convert(WARSAW)
    all_rows["day"]=all_rows.closed_local.dt.strftime("%Y-%m-%d")
    all_rows["week"]=all_rows.closed_local.dt.strftime("%G-W%V")
    d=[]
    w=[]
    for name,group in all_rows.groupby("day",sort=True):
        d.append({"okres":name,**_metrics(group)})
    for name,group in all_rows.groupby("week",sort=True):
        w.append({"okres":name,**_metrics(group)})
    return pd.DataFrame(d),pd.DataFrame(w),_metrics(all_rows)



def performance_by_policy(db, epic, source="Capital.com DEMO REST"):
    """Separate experimental adaptive PAPER from baseline fixed exits."""
    ensure_tables(db)
    db.row_factory=sqlite3.Row
    rows=db.execute("""SELECT exit_policy,status,pnl_pts FROM paper_positions_v3
        WHERE epic=? AND source=?
          AND status IN ('CLOSED_SL','CLOSED_TP','CLOSED_TIMEOUT')
          AND pnl_pts IS NOT NULL""",(epic,source)).fetchall()
    result={}
    for row in rows:
        policy=row["exit_policy"] or "fixed"
        item=result.setdefault(policy,{"Wariant":policy,"Zamknięte":0,
            "Dodatnie P&L":0,"Suma pkt":0.0,"Wyjścia SL":0})
        item["Zamknięte"]+=1
        item["Suma pkt"]+=float(row["pnl_pts"])
        if float(row["pnl_pts"])>0:
            item["Dodatnie P&L"]+=1
        if row["status"]=="CLOSED_SL":
            item["Wyjścia SL"]+=1
    for r in result.values():
        r["Suma pkt"]=round(r["Suma pkt"],2)
        r["Skuteczność %"]=round(100*r["Dodatnie P&L"]/r["Zamknięte"],1)
    return [result[k] for k in sorted(result)]
