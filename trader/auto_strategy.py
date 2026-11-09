"""FOKU$ AUTO — independent closed-bar PAPER hypotheses.

Experimental single-approved setup: from one after-MTF valid candidate,
provided no opposite raw side exists, broker/data/macro/risk gates still pass.
Never mistake N approved / M raw candidates for win probability.
"""
from __future__ import annotations
from dataclasses import replace
from .strategy import Decision
from .strategies_pro import ALL_STRATEGIES, decide_any
from .mtf import filter_mtf_decision

AUTO_MODE = "AUTO — 6 STRATEGII"
MIN_AGREEMENT = 1


def vote_summary(rows):
    """Approved/RAW vote count for a single closed-bar snapshot, not probability.

    Raw = LONG/SHORT hypotheses detected before MTF.
    Approved = those same hypotheses surviving MTF. WAIT is not a vote.
    A raw LONG/SHORT conflict always vetoes the joint setup.
    """
    raw = [r for r in rows if r.get("Setup OHLC") in ("LONG", "SHORT")]
    allowed = [r for r in rows if r.get("Po filtrze MTF") in ("LONG", "SHORT")]
    sides = {r["Setup OHLC"] for r in raw}
    return {
        "approved": len(allowed),
        "raw": len(raw),
        "label": f"{len(allowed)}/{len(raw)}",
        "long": sum(r["Po filtrze MTF"] == "LONG" for r in allowed),
        "short": sum(r["Po filtrze MTF"] == "SHORT" for r in allowed),
        "vetoed": len(raw) - len(allowed),
        "conflict": len(sides) > 1,
        "approved_names": [r["Strategia"] for r in allowed],
        "raw_names": [r["Strategia"] for r in raw],
    }


def evaluate_auto(frame, spread, snapshots=None, *, asof=None, use_mtf=True):
    """Return PAPER hypothesis plus a six-row transparent audit.

    One independent after-MTF setup is sufficient in experimental PAPER.
    Never override an opposite raw candidate, MTF veto, stale market, BLS
    blackout or subsequent worker/risk gates.
    """
    snapshots = snapshots or {}
    rows = []
    approved = []
    for name in ALL_STRATEGIES:
        raw = decide_any(frame, name, spread=spread)
        screened, _ = (filter_mtf_decision(raw, snapshots, asof=asof)
                       if use_mtf else (raw, []))
        rows.append({"Strategia": name, "Setup OHLC": raw.action,
                     "Po filtrze MTF": screened.action,
                     "RR": raw.rr if raw.action in ("LONG", "SHORT") else None,
                     "Powód": screened.reason if screened.action != raw.action else raw.reason})
        if screened.action in ("LONG", "SHORT"):
            approved.append(screened)
    counts = vote_summary(rows)
    atr = next((v.atr for v in approved if v.atr is not None), None)
    prefix = (f"GŁOSY MTF {counts['label']} (LONG:{counts['long']}, "
              f"SHORT:{counts['short']}, veto MTF:{counts['vetoed']}). ")
    if counts["conflict"]:
        return (Decision("WAIT", AUTO_MODE, prefix +
            "Konflikt surowych LONG/SHORT: nie otwieram nawet gdy jeden sygnał "
            "przeszedł MTF.", atr=atr), rows)
    if {d.action for d in approved} == {"LONG", "SHORT"}:
        return (Decision("WAIT", AUTO_MODE, prefix +
            "Konflikt LONG/SHORT po MTF.", atr=atr), rows)
    if len(approved) < MIN_AGREEMENT:
        return (Decision("WAIT", AUTO_MODE, prefix +
            f"Zatwierdzonych setupów: {len(approved)}, wymagane: {MIN_AGREEMENT}. "
            "Nie wymuszam PAPER.", atr=atr), rows)
    selected = sorted(approved, key=lambda d: (-float(d.rr or 0), d.strategy))[0]
    return (replace(selected, reason=(
        prefix + "AUTO PAPER (eksperyment 1 sygnału): zatwierdzone strategie: "
        + ", ".join(d.strategy for d in approved) +
        f". Wybrano {selected.strategy} po RR. Bez potwierdzonej przewagi "
        "statystycznej. " + selected.reason)), rows)
