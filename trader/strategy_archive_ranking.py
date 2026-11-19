"""Daily, weekly, monthly and whole-archive observed strategy rankings.

Ranking is research-only, per separate PAPER ledger. One CLOSED trade
counts once against its SAVED method/combination, never once per co-signal.
No search for hindsight best parameter; no claimed statistically proven edge.
Time ranges are defined by Warsaw calendar and CLOSED timestamp.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

from .periodic_archive_audit import (
    LANES, WARSAW, _at_midnight, _start, _next, _utc, _number,
)

WINDOWS=("day","week","month","all")
DIRECTIONS=("BOTH","LONG","SHORT")
MIN_SAMPLE=30


def _range(kind, day, current):
    if kind=="all":
        return None,current
    start=_at_midnight(_start(kind,day))
    stop=_at_midnight(_next(kind,_start(kind,day)))
    if start>current:
        raise ValueError("Future archive period")
    today=current.astimezone(WARSAW).date()
    # Looking at an earlier day in the current week/month should not
    # include trades from later days: use selected day as as-of.
    if day<today:
        stop=min(stop,_at_midnight(day+timedelta(days=1)))
    return start,min(stop,current)


def strategy_ranking(archive,lane,kind="month",*,reference=None,now=None,
                     direction="BOTH"):
    if lane not in LANES or kind not in WINDOWS or direction not in DIRECTIONS:
        raise ValueError("Unknown lane/window/direction")
    current=_utc(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError("Timezone-aware current time required")
    day=reference if isinstance(reference,date) and not isinstance(reference,datetime) else current.astimezone(WARSAW).date()
    if day>current.astimezone(WARSAW).date():
        raise ValueError("Cannot rank a future date")
    start,end=_range(kind,day,current)
    observed={}
    entries=(archive.get("trades") or {}) if isinstance(archive,dict) else {}
    for key,event in entries.items():
        if not isinstance(event,dict) or event.get("l")!=lane:
            continue
        if event.get("s") not in ("LONG","SHORT"):
            continue
        if direction!="BOTH" and event["s"]!=direction:
            continue
        stamp=_utc(event.get("t"))
        value=_number(event.get("p"))
        if (stamp is None or value is None or
                (start is not None and stamp<start) or stamp>=end):
            continue
        method=str(event.get("m") or "METODA NIEUSTALONA").strip()[:58]
        if not method:
            method="METODA NIEUSTALONA"
        rows=observed.setdefault(method,[])
        rows.append((stamp,str(key),value,event))
    result=[]
    for method,seq in observed.items():
        seq.sort(key=lambda e:(e[0],e[1]))
        n=len(seq)
        wins=sum(p>0 for _,_,p,_ in seq)
        loss=sum(p<0 for _,_,p,_ in seq)
        plus=sum(p for _,_,p,_ in seq if p>0)
        minus=-sum(p for _,_,p,_ in seq if p<0)
        net=sum(p for _,_,p,_ in seq)
        peak=0.
        running=0.
        drawdown=0.
        for _,_,p,_ in seq:
            running+=p
            peak=max(peak,running)
            drawdown=max(drawdown,peak-running)
        # A combined RAW setup is ONE empirical combination; its P&L
        # must never be attributed to each individual constituent strategy.
        combined=" + " in method
        result.append({
            "strategy":method,
            "count":n,
            "wins":wins,
            "losses":loss,
            "win_rate_pct":round(100*wins/n,2),
            "net_pts":round(net,2),
            "avg_pts":round(net/n,3),
            "profit_factor":round(plus/minus,3) if minus>0 else None,
            "max_drawdown_pts":round(drawdown,2),
            "long":sum(e.get("s")=="LONG" for _,_,_,e in seq),
            "short":sum(e.get("s")=="SHORT" for _,_,_,e in seq),
            "tp":sum(e.get("e")=="TP" for _,_,_,e in seq),
            "sl":sum(e.get("e")=="SL" for _,_,_,e in seq),
            "timeout":sum(e.get("e")=="TIMEOUT" for _,_,_,e in seq),
            "last_closed_pl":seq[-1][0].astimezone(WARSAW).strftime("%d.%m %H:%M"),
            "sample_sufficient":n>=MIN_SAMPLE,
            "evidence":("PRÓBA >=30 • BEZ POTWIERDZONEJ PRZEWAGI"
                        if n>=MIN_SAMPLE else "WSTĘPNIE • MAŁO TRANSAKCJI"),
            "combined_methods":combined,
        })
    # Ranking by recorded net points is descriptive, never a guarantee.
    result.sort(key=lambda item:(-item["net_pts"],-item["count"],
                                 -item["avg_pts"],item["strategy"]))
    for index,item in enumerate(result,1):
        item["rank"]=index
    return {
        "lane":lane,
        "period":kind,
        "reference_date":day.isoformat(),
        "direction":direction,
        "start_utc":start.isoformat() if start is not None else None,
        "end_utc":end.isoformat(),
        "sample_warning":True,
        "rows":result,
        "total_closed":sum(row["count"] for row in result),
        "total_net_pts":round(sum(row["net_pts"] for row in result),2),
        "note":"Ranking opisowy: wynik netto w punktach; >=30 prób nie potwierdza przewagi. Osobne rejestry i kombinacje RAW nie są podwójnie liczone.",
    }


def current_rankings(archive,*,now=None):
    """Lightweight checkpoint snapshot; recalculated after each worker scan."""
    current=_utc(now) if now is not None else datetime.now(timezone.utc)
    return {
        "status":"OBSERVED_STRATEGY_RANKING_PAPER_ONLY",
        "asof_utc":current.isoformat(timespec="seconds"),
        "data":{
            kind:{lane:strategy_ranking(archive,lane,kind,now=current)
                  for lane in LANES}
            for kind in ("day","week","month")
        },
        "no_auto_retraining":True,
        "no_live_orders":True,
    }
