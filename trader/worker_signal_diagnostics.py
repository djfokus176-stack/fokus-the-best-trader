"""Read-only AUTO decision diagnosis from a fresh, matching worker vote audit.

No strategy recomputation, no prices/trade identifiers, no broker orders.
Do not use stale earlier votes when the current scan has failed or moved on.
Only explicit, whitelisted status labels go into public watchdog logs.
"""
from __future__ import annotations

from .cloud_signal_radar import worker_signal_radar

EXPECTED = {"LONG", "SHORT", "WAIT"}
ENABLED_STAGES = (0, 1, 2, 3)


def _mtf_issue_code(reason):
    """Map the recorded human status to a non-secret diagnostic enum."""
    r=str(reason or "")[:220]
    for needle,code in (
        ("Brak współczesnej zamkniętej", "NO_CONTEMPORARY_CLOSED_BAR"),
        ("Nie pobrano świec", "NOT_FETCHED"),
        ("Za mało potwierdzonych", "INSUFFICIENT_CONFIRMED_BARS"),
        ("Za mało poprawnych", "INSUFFICIENT_VALID_BARS"),
        ("DANE_WADLIWE", "CORRUPT_OHLC"),
        ("Brak wskaźników", "INDICATORS_UNKNOWN"),
        ("Niezgodny instrument", "SOURCE_MISMATCH"),
        ("Brak świec M1", "NO_M1_FEED"),
        ("WYGASŁY ODCZYT", "CANDLES_STALE"),
        ("Dane przestarzałe", "CANDLES_STALE"),
        ("duże luki", "HOLES_IN_OHLC"),
        ("Spread", "SPREAD_TOO_WIDE"),
        ("spread", "SPREAD_TOO_WIDE"),
    ):
        if needle in r:
            return code
    return "OTHER_OR_UNKNOWN"


def verified_auto_wait_diagnosis(payload, *, now=None):
    """Return safe counters and one bounded reason for the latest scan only."""
    empty={
        "vote_audit":"UNVERIFIED", "raw_long": "UNKNOWN",
        "raw_short": "UNKNOWN", "mtf_long": "UNKNOWN",
        "mtf_short": "UNKNOWN", "mtf_veto": "UNKNOWN",
        "stage_0": "UNKNOWN", "stage_1": "UNKNOWN",
        "stage_2": "UNKNOWN", "stage_3": "UNKNOWN",
        "mtf_ready": "UNKNOWN", "mtf_missing": "UNKNOWN",
        "raw_conflict": "UNKNOWN", "auto_wait_reason": "NO_CURRENT_VOTES",
        "m1_trend":"UNKNOWN", "m5_trend":"UNKNOWN",
        "m15_trend":"UNKNOWN", "h1_trend":"UNKNOWN",
        "mtf_failed_tfs":"UNKNOWN", "mtf_issue_m1":"UNKNOWN",
        "mtf_issue_m5":"UNKNOWN", "mtf_issue_m15":"UNKNOWN",
        "mtf_issue_h1":"UNKNOWN",
    }
    radar=worker_signal_radar(payload,now=now)
    if not radar.get("current"):
        return empty
    rows=radar.get("rows") or []
    if len(rows)!=6:
        return empty
    raw_l=int(radar["raw_long"])
    raw_s=int(radar["raw_short"])
    mtf_l=int(radar["mtf_long"])
    mtf_s=int(radar["mtf_short"])
    veto=int(radar["veto"])
    hist={i:0 for i in ENABLED_STAGES}
    for row in rows:
        stage=str(row.get("Etap",""))
        if stage in ("0/3","1/3","2/3","3/3"):
            hist[int(stage[0])]+=1
    audit=payload.get("last_vote_audit") or {}
    views=audit.get("mtf")
    ready="UNKNOWN"
    missing="UNKNOWN"
    if isinstance(views,list) and len(views)==4:
        ready=sum(1 for v in views if isinstance(v,dict) and v.get("ready") is True)
        missing=4-ready
    failed=[]
    issues={"MINUTE":"UNKNOWN","MINUTE_5":"UNKNOWN",
            "MINUTE_15":"UNKNOWN","HOUR":"UNKNOWN"}
    if isinstance(views,list) and len(views)==4:
        for view in views:
            if not isinstance(view,dict) or view.get("timeframe") not in issues:
                continue
            tf=view["timeframe"]
            if view.get("ready") is True:
                issues[tf]="OK"
            else:
                failed.append(tf)
                issues[tf]=_mtf_issue_code(view.get("reason"))
    meta=payload.get("meta") or {}
    latest=str(meta.get("last_scan_summary") or "")
    decision=str(audit.get("decision") or "")
    if decision not in EXPECTED or decision not in latest.split(" / ")[:2]:
        return empty
    queued=("QUEUE=YES" in latest)
    # Prefer a protective gate over a heuristic no-signal explanation.
    import re
    gates=re.search(r"(?:^| / )GATES=([A-Z0-9_,]+)(?= /|$)",latest)
    gate_clear=bool(gates and gates.group(1)=="OK")
    trends={"MINUTE":"UNKNOWN","MINUTE_5":"UNKNOWN",
            "MINUTE_15":"UNKNOWN","HOUR":"UNKNOWN"}
    if isinstance(views,list):
        for v in views:
            if (isinstance(v,dict) and v.get("timeframe") in trends
                    and v.get("trend") in ("UP","DOWN","NEUTRAL","UNKNOWN")):
                trends[v["timeframe"]]=v["trend"]
    if not gate_clear:
        reason="PROTECTIVE_GATE_OR_UNKNOWN"
    elif raw_l and raw_s:
        reason="RAW_LONG_SHORT_CONFLICT"
    elif decision=="WAIT":
        if raw_l+raw_s==0:
            reason="NO_RAW_SETUP"
        elif mtf_l+mtf_s==0 and veto>0:
            reason="MTF_REJECTED_RAW"
        elif mtf_l+mtf_s>0:
            reason="AUTO_WAIT_WITH_MTF_APPROVAL"
        else:
            reason="WAIT_UNCLASSIFIED"
    elif queued:
        reason="SETUP_QUEUED"
    else:
        reason="CANDIDATE_NOT_QUEUED"
    return {
        "vote_audit":"CURRENT", "raw_long":raw_l,"raw_short":raw_s,
        "mtf_long":mtf_l,"mtf_short":mtf_s,
        "mtf_veto":veto,
        "stage_0":hist[0],"stage_1":hist[1],
        "stage_2":hist[2],"stage_3":hist[3],
        "mtf_ready":ready,"mtf_missing":missing,
        "raw_conflict":"YES" if raw_l and raw_s else "NO",
        "auto_wait_reason":reason,
        "m1_trend":trends["MINUTE"],"m5_trend":trends["MINUTE_5"],
        "m15_trend":trends["MINUTE_15"],"h1_trend":trends["HOUR"],
        "mtf_failed_tfs":",".join(failed) if failed else "NONE",
        "mtf_issue_m1":issues["MINUTE"],
        "mtf_issue_m5":issues["MINUTE_5"],
        "mtf_issue_m15":issues["MINUTE_15"],
        "mtf_issue_h1":issues["HOUR"],
    }
