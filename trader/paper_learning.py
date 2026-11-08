"""PAPER v3 self-updating strategy performance, for SHADOW research only.

Scores only completed positions with actual simulated P&L; excludes signals,
WAIT, pending, open, invalidated and CSV/replay. Never retunes production
entry thresholds and never calls a broker.
"""
from __future__ import annotations
from collections import defaultdict
from math import sqrt, isfinite
import sqlite3

CLOSED = ("CLOSED_SL", "CLOSED_TP", "CLOSED_TIMEOUT")


def _wilson_lower(wins, n, z=1.96):
    if n == 0:
        return 0.0
    p = wins/n
    return max(0.0, (p+z*z/(2*n)-z*sqrt((p*(1-p)+z*z/(4*n))/n))/
               (1+z*z/n))


def _score(rows):
    pnl = [float(r["pnl_pts"]) for r in rows]
    n = len(pnl)
    if not n:
        return {"n":0, "wins":0, "win_rate_pct":None,
                "mean_pts":None,"sum_pts":0.0,"profit_factor":None,
                "win_rate_lower95_pct":None}
    wins = sum(x>0 for x in pnl)
    gain = sum(x for x in pnl if x>0)
    loss = -sum(x for x in pnl if x<0)
    return {"n":n, "wins":wins, "win_rate_pct":round(100*wins/n,2),
            "win_rate_lower95_pct":round(100*_wilson_lower(wins,n),2),
            "mean_pts":round(sum(pnl)/n,4), "sum_pts":round(sum(pnl),3),
            "profit_factor":round(gain/loss,3) if loss>0 else None}


def strategy_scorecard(db, *, epic="US500", source="Capital.com DEMO REST"):
    """70/30 chronological test with strict non-overlap and minimum sizes.

    Shadow ranking updates after new closed PAPER fills, never on each signal.
    Performance is in MODELLED POINTS, not broker profit or guaranteed ROI.
    """
    from .paper_lifecycle import ensure_tables
    ensure_tables(db)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        """SELECT trade_id, strategy, exit_policy, closed_utc, pnl_pts, status
           FROM paper_positions_v3
           WHERE epic=? AND source=? AND status IN
                 ('CLOSED_SL','CLOSED_TP','CLOSED_TIMEOUT')
             AND pnl_pts IS NOT NULL
           ORDER BY closed_utc ASC, trade_id ASC""", (epic,source)).fetchall()
    by = defaultdict(list)
    for row in rows:
        if not isfinite(float(row["pnl_pts"])):
            continue
        # Never pool materially different stop/target management policies.
        key = (row["strategy"], row["exit_policy"] or "fixed")
        by[key].append(row)
    result = []
    for (name,policy),group in sorted(by.items()):
        n = len(group)
        split = max(1, int(n*0.70))
        # Until 30 positions are available do NOT call the last 30% OOS.
        train = group[:split] if n>=30 else group
        test = group[split:] if n>=30 else []
        train_scores = _score(train)
        holdout = _score(test)
        eligible = n>=100 and holdout["n"]>=30
        # Even positive chronological holdout alone is not a statistically
        # validated live edge; ranking always stays SHADOW.
        result.append({
            "strategy":name, "exit_policy":policy,
            "total":n, "train":train_scores, "holdout":holdout,
            "holdout_eligible":eligible,
            "shadow_priority":("BETTER_THAN_ZERO_OOS" if eligible and
                               holdout["mean_pts"]>0 and
                               holdout["win_rate_lower95_pct"]>50
                               else "INSUFFICIENT_EVIDENCE"),
            "live_edge_proven":False,
        })
    result.sort(key=lambda r:(not r["holdout_eligible"],
        -(r["holdout"]["mean_pts"] if r["holdout"]["mean_pts"] is not None else -1e9),
        -r["total"], r["strategy"],r["exit_policy"]))
    return {"source":source,"epic":epic,"closed_positions":sum(map(len,by.values())),
            "status":"SHADOW_ONLY_NO_LIVE_EDGE_PROVEN",
            "strategies":result[:24]}
