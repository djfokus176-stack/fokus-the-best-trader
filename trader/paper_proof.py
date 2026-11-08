"""Read-only evidence of actual Capital.com DEMO-sourced PAPER event cycles.

Never confuses a successful GitHub Action with a PENDING -> OPEN -> CLOSED
cycle. Safe aggregate counts only, no secret/token or full ledger printing.
"""
from __future__ import annotations
from datetime import datetime,timezone
import math

CLOSED={"CLOSED_SL":"PAPER_CLOSE_SL",
        "CLOSED_TP":"PAPER_CLOSE_TP",
        "CLOSED_TIMEOUT":"PAPER_TIMEOUT"}


def paper_proof(payload, *, epic="US500", source="Capital.com DEMO REST"):
    tables=payload.get("tables") if isinstance(payload,dict) else None
    if not isinstance(tables,dict):
        raise ValueError("No durable PAPER ledger in checkpoint")
    positions=tables.get("paper_positions_v3",[])
    events=tables.get("paper_events_v3",[])
    if not isinstance(positions,list) or not isinstance(events,list):
        raise ValueError("Malformed PAPER ledger")
    by_id={}
    for event in events:
        if isinstance(event,dict):
            by_id.setdefault(event.get("trade_id"),[]).append(event)
    counts={"PENDING":0,"OPEN":0,"CLOSED":0,"INVALIDATED":0}
    proven=0
    invalid_closed=0
    for pos in positions:
        if not isinstance(pos,dict) or pos.get("source")!=source or pos.get("epic")!=epic:
            continue
        state=pos.get("status")
        if state in ("PENDING","OPEN","INVALIDATED"):
            counts[state]+=1
        if state not in CLOSED:
            continue
        counts["CLOSED"]+=1
        stages=by_id.get(pos.get("trade_id"),[])
        types={x.get("kind") for x in stages}
        if not (pos.get("side")+"_SETUP" in types and "PAPER_OPEN" in types
                and CLOSED[state] in types):
            invalid_closed+=1
            continue
        try:
            pnl=float(pos["pnl_pts"])
            if not math.isfinite(pnl) or not pos.get("entry_detected_utc"):
                raise ValueError("Missing simulated fill evidence")
            def when(kind):
                d=next(x["candle_utc"] for x in stages if x.get("kind")==kind)
                stamp=datetime.fromisoformat(str(d))
                if stamp.tzinfo is None:
                    raise ValueError("Unaware timestamp")
                return stamp.astimezone(timezone.utc)
            start=when(pos["side"]+"_SETUP")
            opened=when("PAPER_OPEN")
            closed=when(CLOSED[state])
            if not start<opened<=closed:
                raise ValueError("Out-of-order lifecycle")
        except (KeyError,TypeError,ValueError,StopIteration):
            invalid_closed+=1
            continue
        proven+=1
    return {"epic":epic,"mode":"PAPER_DEMO_ONLY",
            "status":"OBSERVED_COMPLETE_PAPER_CYCLE" if proven else "NOT_PROVEN",
            "verified_cycles":proven,"incomplete_closed":invalid_closed,
            "counts":counts, "ledger_scoped":True,
            "note":"Hypothetical fills on closed bars; not broker executions or profitable-trading proof."}


def main():
    import json
    from .remote_checkpoint import RemoteCheckpoint
    try:
        version,payload=RemoteCheckpoint.from_env().fetch()
        record=paper_proof(payload)
        print("PAPER PROOF / CHECKPOINT_VERSION="+str(version)+" / "+json.dumps(
              record,ensure_ascii=False,sort_keys=True),flush=True)
    except Exception as exc:
        print("PAPER PROOF / ERROR="+type(exc).__name__,flush=True)
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
