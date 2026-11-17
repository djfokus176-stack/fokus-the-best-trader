"""Automatic, checkpoint-backed D/W/M audits of actually CLOSED PAPER trades.

Three distinct simulation ledgers, immutable trade identities, Poland-time
period boundaries, no broker orders, no reconstructed/hindsight fill.
Uses existing Supabase checkpoint JSON (no SQL/schema migration).
Important: early dates are marked PARTIAL until collection coverage exists.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from math import isfinite
from zoneinfo import ZoneInfo
import json

WARSAW=ZoneInfo("Europe/Warsaw")
SCHEMA=1
SOURCE="Capital.com DEMO REST"
LANES=("PAPER v3","MOMENTUM TEST","RAW M1 TEST")
DONE=frozenset(("CLOSED_TP","CLOSED_SL","CLOSED_TIMEOUT"))
MAX_ROWS=3500
MAX_DAYS=400
MAX_AUDIT_BYTES=650000
MAX_METHOD_LENGTH=58


def _utc(value):
    if isinstance(value, datetime):
        parsed=value
    elif isinstance(value,str):
        try:
            parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        except (TypeError,ValueError,OverflowError):
            return None
    else:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _number(value):
    if isinstance(value,bool):
        return None
    try:
        x=float(value)
    except (TypeError,ValueError,OverflowError):
        return None
    return x if isfinite(x) else None


def _valid_trade(row,lane,now):
    if (not isinstance(row,dict) or row.get("status") not in DONE
            or row.get("side") not in ("LONG","SHORT")):
        return None
    close=_utc(row.get("closed_utc"))
    opened=_utc(row.get("opened_utc"))
    setup=_utc(row.get("setup_utc"))
    pnl=_number(row.get("pnl_pts"))
    if (not close or not opened or not setup or pnl is None
            or setup>opened or opened>close or close>now+timedelta(seconds=60)):
        return None
    if lane=="PAPER v3":
        if (row.get("epic")!="US500" or row.get("source")!=SOURCE
                or not isinstance(row.get("trade_id"),str)
                or not row["trade_id"]):
            return None
        unique=row["trade_id"]
        method=str(row.get("strategy") or "BRAK METODY")
    else:
        unique=setup.isoformat()+"|"+row["side"]
        if lane=="RAW M1 TEST":
            methods=row.get("methods")
            method=(" + ".join(str(x) for x in methods[:4])
                    if isinstance(methods,list) and methods else "RAW M1")
        else:
            method=str(row.get("strategy") or "MOMENTUM_M1_TEST")
    digest=sha256((lane+"|"+unique).encode("utf8")).hexdigest()[:22]
    return digest,{
        "l":lane,
        "t":close.isoformat(timespec="seconds"),
        "o":opened.isoformat(timespec="seconds"),
        "p":round(pnl,4),
        "s":row["side"],
        "m":method[:MAX_METHOD_LENGTH],
        "e":str(row["status"])[7:],  # TP/SL/TIMEOUT
    }


def _extract(payload,now):
    tables=payload.get("tables") or {}
    v3=tables.get("paper_positions_v3") if isinstance(tables,dict) else []
    raw=payload.get("raw_m1_forward_paper") or {}
    momentum=payload.get("momentum_paper_test") or {}
    sources=[
        ("PAPER v3",v3),
        ("MOMENTUM TEST",momentum.get("closed") if isinstance(momentum,dict) else []),
        ("RAW M1 TEST",raw.get("closed") if isinstance(raw,dict) else []),
    ]
    for lane,rows in sources:
        if not isinstance(rows,list):
            continue
        for row in rows:
            event=_valid_trade(row,lane,now)
            if event is not None:
                yield event


def empty():
    return {"schema":SCHEMA,"trades":{},"first_collected_utc":None,
            "last_collected_utc":None,"retention_floor_utc":None,
            "seen_scans":0,"removed_count":0,"bad_records":0}


def advance_periodic_archive(previous,payload,*,now=None):
    """Called by Northflank worker after updating all three ledgers.

    Repeated scans and restarts re-read old closed positions safely; stable
    IDs prevent double booking. A full log from day N is comparable to
    previous weeks/months once the archive has been collecting sufficiently
    long. No old chart candles are transformed into pretend trades.
    """
    current=_utc(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError("Required timezone-aware UTC timestamp")
    old=(previous if isinstance(previous,dict) and
         previous.get("schema")==SCHEMA else empty())
    data={**old}
    rows=dict(old.get("trades") or {})
    floor=_utc(old.get("retention_floor_utc"))
    data["first_collected_utc"]=(old.get("first_collected_utc")
                                 or current.isoformat(timespec="seconds"))
    data["last_collected_utc"]=current.isoformat(timespec="seconds")
    data["seen_scans"]=int(old.get("seen_scans") or 0)+1

    for key,record in _extract(payload,current):
        if floor is not None and _utc(record["t"])<=floor:
            continue
        if key not in rows:
            rows[key]=record

    earliest=current-timedelta(days=MAX_DAYS)
    too_old=[(key,record) for key,record in rows.items()
             if _utc(record.get("t")) is None or
             _utc(record.get("t"))<earliest]
    for key,_ in too_old:
        del rows[key]

    if len(rows)>MAX_ROWS:
        remove=sorted(rows,key=lambda key:(rows[key]["t"],key))[:len(rows)-MAX_ROWS]
        too_old.extend((key,rows[key]) for key in remove)
        for key in remove:
            del rows[key]

    data["removed_count"]=int(data.get("removed_count",0))+len(too_old)
    if too_old:
        removed_dates=[_utc(x.get("t")) for _,x in too_old]
        removed_dates=[x for x in removed_dates if x is not None]
        if removed_dates:
            new_floor=max(removed_dates)
            data["retention_floor_utc"]=max(filter(None,(floor,new_floor))).isoformat()
    data["trades"]=rows

    # Preserve other checkpoint tables: caller adds this to payload only,
    # below the 2.5 MiB global CAS limit.
    while (rows and
           len(json.dumps(data,ensure_ascii=False,separators=(",",":")).encode("utf8"))>MAX_AUDIT_BYTES):
        key=min(rows,key=lambda k:(rows[k]["t"],k))
        floor=max(filter(None,(_utc(data.get("retention_floor_utc")),
                              _utc(rows[key]["t"]))))
        del rows[key]
        data["retention_floor_utc"]=floor.isoformat()
        data["removed_count"]+=1
    return data


def _start(kind,day):
    if kind=="day":
        return day
    if kind=="week":
        return day-timedelta(days=day.weekday())
    if kind=="month":
        return day.replace(day=1)
    raise ValueError("Unknown period")


def _next(kind,day):
    if kind=="day":
        return day+timedelta(days=1)
    if kind=="week":
        return day+timedelta(days=7)
    if kind=="month":
        return day.replace(year=day.year+1,month=1) if day.month==12 else day.replace(month=day.month+1)
    raise ValueError("Unknown period")


def _previous(kind,day):
    if kind=="day":
        return day-timedelta(days=1)
    if kind=="week":
        return day-timedelta(days=7)
    if kind=="month":
        return day.replace(year=day.year-1,month=12) if day.month==1 else day.replace(month=day.month-1)
    raise ValueError("Unknown period")


def _at_midnight(day):
    return datetime.combine(day,time.min,tzinfo=WARSAW).astimezone(timezone.utc)


def _metrics(archive,lane,start,end):
    trades=archive.get("trades") or {}
    seq=[]
    for key,row in trades.items():
        if not isinstance(row,dict) or row.get("l")!=lane:
            continue
        stamp=_utc(row.get("t"))
        if stamp is not None and start<=stamp<end:
            pnl=_number(row.get("p"))
            if pnl is not None:
                seq.append((stamp,key,pnl,row))
    seq.sort(key=lambda x:(x[0],x[1]))
    plus=sum(p for _,_,p,_ in seq if p>0)
    minus=-sum(p for _,_,p,_ in seq if p<0)
    running=0.0
    peak=0.0
    drawdown=0.0
    losing=0
    max_losing=0
    methods={}
    for _,_,p,row in seq:
        running+=p
        peak=max(peak,running)
        drawdown=max(drawdown,peak-running)
        losing=(losing+1 if p<0 else 0)
        max_losing=max(max_losing,losing)
        method=str(row.get("m") or "BRAK")
        m=methods.setdefault(method,{"count":0,"pnl_pts":0.0,"wins":0})
        m["count"]+=1
        m["wins"]+=int(p>0)
        m["pnl_pts"]+=p
    n=len(seq)
    return {
        "closed":n,
        "wins":sum(p>0 for _,_,p,_ in seq),
        "win_rate_pct":round(100*sum(p>0 for _,_,p,_ in seq)/n,2) if n else None,
        "net_pts":round(sum(p for _,_,p,_ in seq),2),
        "avg_pts":round(sum(p for _,_,p,_ in seq)/n,3) if n else None,
        "profit_factor":round(plus/minus,3) if minus else None,
        "max_drawdown_pts":round(drawdown,2),
        "max_losing_streak":max_losing,
        "best_pts":round(max(p for _,_,p,_ in seq),2) if n else None,
        "worst_pts":round(min(p for _,_,p,_ in seq),2) if n else None,
        "long":sum(row.get("s")=="LONG" for _,_,_,row in seq),
        "short":sum(row.get("s")=="SHORT" for _,_,_,row in seq),
        "tp":sum(row.get("e")=="TP" for _,_,_,row in seq),
        "sl":sum(row.get("e")=="SL" for _,_,_,row in seq),
        "timeout":sum(row.get("e")=="TIMEOUT" for _,_,_,row in seq),
        "methods":{k:{"count":v["count"],"wins":v["wins"],
                      "net_pts":round(v["pnl_pts"],2)}
                   for k,v in sorted(methods.items())},
    }


def period_comparison(archive,lane,kind,*,reference=None,now=None):
    """One period and the preceding one; current periods matched by duration.

    'delta' is omitted when archive coverage cannot substantiate both windows.
    Never treat an unobserved prior period as 0 transactions.
    """
    current=_utc(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError("UTC-aware now required")
    if lane not in LANES:
        raise ValueError("Unknown audit lane")
    day=(reference if isinstance(reference,date) and not isinstance(reference,datetime)
         else current.astimezone(WARSAW).date())
    if day>current.astimezone(WARSAW).date():
        raise ValueError("Cannot audit future dates")
    period_start=_start(kind,day)
    period_end=_next(kind,period_start)
    prev_start=_previous(kind,period_start)
    start,end,old_start,old_end=map(_at_midnight,
        (period_start,period_end,prev_start,period_start))
    is_current=start<=current<end
    through=min(end,current) if is_current else end
    prev_match=min(old_end,old_start+(through-start)) if is_current else old_end
    current_stats=_metrics(archive,lane,start,through)
    previous_stats=_metrics(archive,lane,old_start,prev_match)
    previous_full=_metrics(archive,lane,old_start,old_end)
    coverage=_utc(archive.get("first_collected_utc"))
    floor=_utc(archive.get("retention_floor_utc"))
    required=max(filter(None,(coverage,floor)),default=None)
    complete=bool(required is not None and required<=old_start)
    if not (archive.get("trades") or {}):
        # Zero events can be a valid observed day AFTER data collection,
        # but never classify an arbitrary unobserved historical period as 0.
        complete=bool(complete)
    return {
        "lane":lane,"kind":kind,"period":period_start.isoformat(),
        "reference_date":day.isoformat(),
        "current_partial":is_current,
        "current":current_stats,
        "previous_matched":previous_stats,
        "previous_full":previous_full,
        "delta_net_pts":round(current_stats["net_pts"]-previous_stats["net_pts"],2)
                         if complete else None,
        "delta_closed":current_stats["closed"]-previous_stats["closed"]
                         if complete else None,
        "comparison_ready":complete,
        "coverage_from_utc":required.isoformat() if required else None,
        "range_start_utc":start.isoformat(),
        "range_end_utc":through.isoformat(),
        "previous_range_end_utc":prev_match.isoformat(),
        "matching":("SAME_ELAPSED_UTC_DURATION" if is_current else "FULL_PREVIOUS_PERIOD"),
    }


def automatic_audit_report(archive,*,now=None):
    current=_utc(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError("UTC-aware now required")
    periods={kind:{
        lane:period_comparison(archive,lane,kind,now=current)
        for lane in LANES} for kind in ("day","week","month")}
    return {
        "status":"ARCHIVE_AUDIT_PAPER_ONLY",
        "asof_utc":current.isoformat(timespec="seconds"),
        "timezone":"Europe/Warsaw",
        "stored_trades":len(archive.get("trades") or {}),
        "first_collected_utc":archive.get("first_collected_utc"),
        "last_collected_utc":archive.get("last_collected_utc"),
        "removed_count":archive.get("removed_count",0),
        "periods":periods,
        "limits":"Up to 3500 distinct closed transactions / 400 days / 650 KB; earlier comparisons can be PARTIAL",
        "real_broker_orders":False,
    }


def archive_day_trades(archive,day,*,lane=None):
    """Exactly one selected Poland-local date, no mixing simulations."""
    if lane is not None and lane not in LANES:
        raise ValueError("Unknown archive lane")
    if not isinstance(day,date) or isinstance(day,datetime):
        raise ValueError("Expected Python date")
    entries=[]
    for key,r in (archive.get("trades") or {}).items():
        if not isinstance(r,dict) or lane is not None and r.get("l")!=lane:
            continue
        ts=_utc(r.get("t"))
        if ts is None or ts.astimezone(WARSAW).date()!=day:
            continue
        if r.get("l") not in LANES:
            continue
        op=_utc(r.get("o"))
        entries.append({
            "ID":key[:10],
            "Tryb":r["l"],"Kierunek":r.get("s"),
            "Strategia":r.get("m"),
            "OPEN (Polska)":op.astimezone(WARSAW).strftime("%d.%m %H:%M") if op else "—",
            "CLOSE (Polska)":ts.astimezone(WARSAW).strftime("%d.%m %H:%M"),
            "Powód zamknięcia":r.get("e"),
            "Netto pkt":r.get("p"),
        })
    return sorted(entries,key=lambda e:(e["CLOSE (Polska)"],e["ID"]))
