"""Rolling frequency of *observed* AUTO PAPER candidates and vetoes.

Never estimates profitability or expected frequency from configuration.
Counts unique verified worker archive rows; observations are NOT trades.
Older checkpoints may lack full six-strategy reasons and stage diagnostics.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .strategies_pro import ALL_STRATEGIES

SOURCE = "Capital.com DEMO REST"
EPIC = "US500"
FRAME = "MINUTE"
VALID_ACTIONS = {"WAIT", "LONG", "SHORT"}
ARCHIVE_LIMIT = 120


def _parse_stamp(value):
    if not isinstance(value,str):
        return None
    try:
        stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
    except (OverflowError,ValueError):
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def summarize_entry_frequency(history, *, limit=ARCHIVE_LIMIT):
    """Return descriptive frequencies of valid historical scans only.

    Each scan is counted ONCE. A raw candidate surviving MTF is not necessarily
    a final queue or OPEN, and an OPEN is not necessarily a profitable trade.
    """
    if type(limit) is not int or not 1<=limit<=ARCHIVE_LIMIT:
        raise ValueError("Invalid frequency audit window")
    all_rows={}
    for row in history if isinstance(history,list) else []:
        if not isinstance(row,dict):
            continue
        if row.get("epic")!=EPIC or row.get("timeframe")!=FRAME:
            continue
        stamp=_parse_stamp(row.get("candle_utc"))
        if stamp is None:
            continue
        exact=SOURCE+"|"+EPIC+"|"+FRAME+"|"+stamp.isoformat()
        # Historical keys may be Z-labelled; compare their validated prefix.
        key=row.get("key")
        if not isinstance(key,str) or not key.startswith(SOURCE+"|"+EPIC+"|"+FRAME+"|"):
            continue
        if _parse_stamp(key.split("|",3)[-1])!=stamp:
            continue
        if row.get("decision") not in VALID_ACTIONS:
            continue
        if not isinstance(row.get("blockers"),list):
            continue
        candidates=row.get("raw_candidates")
        if not isinstance(candidates,list):
            continue
        all_rows[stamp]=row
    ordered=sorted(all_rows.items(),key=lambda pair:pair[0])[-limit:]
    totals={"scans":len(ordered), "raw_scans":0,"approved_scans":0,
            "decision_scans":0,"unblocked_decision_scans":0,
            "gated_decision_scans":0,"conflict_scans":0,
            "raw_wait_scans":0,"vetoed_signal_scans":0,
            "audit_complete_scans":0,"stage_complete_scans":0,
            "first_utc":ordered[0][0].isoformat() if ordered else None,
            "last_utc":ordered[-1][0].isoformat() if ordered else None,
            "by_strategy":[],
            "global_gate_reasons":[],"waiting_reasons":[]}
    counts={s:{"strategy":s,"raw":0,"approved":0,
               "mtf_veto":0,"audited_scans":0,
               "stage_2of3":0,"stage_3of3":0,
               "wait_reasons":Counter()} for s in ALL_STRATEGIES}
    gate_counts=Counter()
    overall_wait=Counter()
    for _,row in ordered:
        diagnostic=row.get("strategy_audit")
        has_full=(isinstance(diagnostic,list) and len(diagnostic)==6 and
                  {v.get("strategy") for v in diagnostic if isinstance(v,dict)}
                  ==set(ALL_STRATEGIES))
        if has_full:
            totals["audit_complete_scans"]+=1
            candidates=diagnostic
            has_stages=all(type(x.get("stage")) is int and 0<=x["stage"]<=3
                           for x in candidates)
            if has_stages:
                totals["stage_complete_scans"]+=1
        else:
            candidates=row["raw_candidates"]
        sides=set()
        had_raw=False
        had_approved=False
        had_veto=False
        for vote in candidates:
            if not isinstance(vote,dict):
                continue
            name=vote.get("strategy")
            if name not in counts:
                continue
            # Old format uses 'direction'; full audit uses 'raw'.
            raw=vote.get("raw",vote.get("direction"))
            after=vote.get("after_mtf")
            if raw not in VALID_ACTIONS or after not in VALID_ACTIONS:
                continue
            cc=counts[name]
            if has_full:
                cc["audited_scans"]+=1
                if raw=="WAIT":
                    reason=str(vote.get("reason") or "BRAK_POWODU")[:120]
                    cc["wait_reasons"][reason]+=1
                    overall_wait[reason]+=1
                if has_stages:
                    stage=vote["stage"]
                    if stage==2: cc["stage_2of3"]+=1
                    if stage==3: cc["stage_3of3"]+=1
            if raw in ("LONG","SHORT"):
                cc["raw"]+=1; had_raw=True; sides.add(raw)
                if after==raw:
                    cc["approved"]+=1; had_approved=True
                else:
                    cc["mtf_veto"]+=1; had_veto=True
        if had_raw: totals["raw_scans"]+=1
        else: totals["raw_wait_scans"]+=1
        if had_approved: totals["approved_scans"]+=1
        if had_veto: totals["vetoed_signal_scans"]+=1
        if len(sides)>1: totals["conflict_scans"]+=1
        approved_decision=row["decision"] in ("LONG","SHORT")
        if approved_decision:
            totals["decision_scans"]+=1
            if row["blockers"]:
                totals["gated_decision_scans"]+=1
            else:
                totals["unblocked_decision_scans"]+=1
        # These are risk/data gates; not a proxy for actual queued trades.
        for reason in set(str(v)[:90] for v in row["blockers"]):
            gate_counts[reason]+=1
    for name in ALL_STRATEGIES:
        c=counts[name]
        totals["by_strategy"].append({
            "Strategia":name,
            "Surowe LONG/SHORT":c["raw"],
            "Po MTF":c["approved"],
            "Veto MTF":c["mtf_veto"],
            "Etap 2/3":c["stage_2of3"] if totals["stage_complete_scans"] else None,
            "Etap 3/3":c["stage_3of3"] if totals["stage_complete_scans"] else None,
            "Prób z diagnozą":c["audited_scans"],
            "Najczęstszy WAIT":(
                c["wait_reasons"].most_common(1)[0][0]
                if c["wait_reasons"] else "BRAK W ARCHIWUM"),
        })
    totals["global_gate_reasons"]=gate_counts.most_common(8)
    totals["waiting_reasons"]=overall_wait.most_common(8)
    return totals
