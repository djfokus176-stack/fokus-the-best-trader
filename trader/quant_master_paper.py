"""FOKU$ QUANT MASTER — read-only, reproducible PAPER AUTO EV audit.

Only the original verified v3 AUTO positions that really CLOSED are used.
The stored pnl_pts is already net of the simulated execution model: never
subtract its spread/slippage twice. Extra cost stress tests change only the
research estimate, never ledger data, trade selection or execution.

Paper-only. No broker credentials, no order calls, no production gate changes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import ceil, isfinite
import random
from statistics import mean
from zoneinfo import ZoneInfo

from .auto_sim_journal import SOURCE
from .auto_strategy import AUTO_MODE
from .paper_method_labels import method_attribution

CLOSED = frozenset(("CLOSED_SL", "CLOSED_TP", "CLOSED_TIMEOUT"))
NEW_YORK = ZoneInfo("America/New_York")
BOOTSTRAP_SEED = 20261126
MIN_CLOSED = 30
MIN_INDEPENDENT_SESSIONS = 20


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


def _utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if time.tzinfo is None:
        return None
    return time.astimezone(timezone.utc)


def verified_auto_closed(payload_rows, *, epic="US500", source=SOURCE):
    """Unique saved AUTO closes; malformed or non-AUTO rows are reported.

    Do not silently include PENDING/OPEN/INVALIDATED, manual trades, RAW,
    unresolved signals, rows without real saved entry/exit or duplicated IDs.
    """
    diagnostics = {"examined": 0, "excluded": 0, "duplicates": 0,
                   "not_auto": 0, "closed": 0}
    out = []
    seen = set()
    for record in payload_rows:
        diagnostics["examined"] += 1
        if not isinstance(record, dict):
            diagnostics["excluded"] += 1
            continue
        if record.get("source") != source or record.get("epic") != epic:
            # The report is explicitly for one instrument and feed.
            continue
        if method_attribution(record)["mode"] != AUTO_MODE:
            diagnostics["not_auto"] += 1
            continue
        if record.get("status") not in CLOSED or record.get("side") not in ("LONG", "SHORT"):
            continue
        tid = record.get("trade_id")
        if not isinstance(tid, str) or not tid:
            diagnostics["excluded"] += 1
            continue
        if tid in seen:
            diagnostics["duplicates"] += 1
            continue
        seen.add(tid)
        opened, closed = _utc(record.get("opened_utc")), _utc(record.get("closed_utc"))
        entry, exit_price, pnl = (_number(record.get(key)) for key in (
            "entry_mid", "exit_mid", "pnl_pts"))
        if (opened is None or closed is None or closed < opened
                or entry is None or exit_price is None
                or entry <= 0 or exit_price <= 0 or pnl is None):
            diagnostics["excluded"] += 1
            continue
        spread, slip = _number(record.get("setup_spread")), _number(record.get("slippage"))
        model_cost = ((spread + 2 * slip) if
                      spread is not None and spread >= 0
                      and slip is not None and slip >= 0 else None)
        out.append({
            "id": tid, "strategy": method_attribution(record)["method"],
            "policy": record.get("exit_policy") or "fixed",
            "side": record["side"], "pnl": pnl,
            "opened": opened, "closed": closed,
            "session_et": closed.astimezone(NEW_YORK).date().isoformat(),
            "cost_proxy": model_cost, "status": record["status"],
        })
    out.sort(key=lambda r: (r["closed"], r["id"]))
    diagnostics["closed"] = len(out)
    return out, diagnostics


def _block_bootstrap_ci(trades, *, iterations=600):
    """Resample whole ET close sessions, not correlated individual M1 trades.

    Deliberately no CI for fewer than 8 independent observed sessions.
    This interval is descriptive and cannot establish forward edge.
    """
    groups = defaultdict(list)
    for trade in trades:
        groups[trade["session_et"]].append(trade["pnl"])
    sessions = sorted(groups)
    if len(sessions) < 8:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    samples = []
    for _ in range(iterations):
        sample = [v for _ in sessions
                  for v in groups[sessions[rng.randrange(len(sessions))]]]
        samples.append(mean(sample))
    samples.sort()
    low = samples[int(0.025 * (len(samples)-1))]
    high = samples[int(0.975 * (len(samples)-1))]
    return (round(low, 4), round(high, 4))


def paper_ev_metrics(trades):
    """Descriptive observed EV after existing modeled fees; no trade forecast."""
    n = len(trades)
    if not n:
        return {"n": 0, "sessions": 0, "status": "INSUFFICIENT_DATA",
                "mean_net_pts": None, "sum_net_pts": None,
                "win_rate_pct": None, "net_breakeven_winrate_pct": None,
                "stress_1_5_net_pts": None, "stress_2_net_pts": None,
                "ci95_mean_net_pts": None, "max_drawdown_pts": None,
                "cvar10_net_pts": None, "tp": 0, "sl": 0, "timeout": 0}
    ordered = sorted(trades, key=lambda x: (x["closed"], x["id"]))
    pnls = [r["pnl"] for r in ordered]
    wins = [v for v in pnls if v > 0]
    losses = [-v for v in pnls if v < 0]
    sessions = len(set(r["session_et"] for r in trades))
    eligible = n >= MIN_CLOSED and sessions >= MIN_INDEPENDENT_SESSIONS
    # PnL is ALREADY modeled NET. Breakeven uses observed net win/loss
    # magnitudes. Do not add another cost term to this ratio.
    be = ((mean(losses) / (mean(wins) + mean(losses))) * 100
          if wins and losses else None)
    running = 0.0
    peak = 0.0
    worst_dd = 0.0
    for pnl in pnls:
        running += pnl
        peak = max(peak, running)
        worst_dd = max(worst_dd, peak - running)
    cost_stress = None
    if all(r["cost_proxy"] is not None for r in trades):
        cost_stress = [r["cost_proxy"] for r in trades]
    cvar10 = None
    if n >= 10:
        tail = sorted(pnls)[:max(1, ceil(n * .1))]
        cvar10 = round(mean(tail), 4)
    return {
        "n": n, "sessions": sessions,
        "status": "RESEARCH_ONLY" if eligible else "INSUFFICIENT_DATA",
        "mean_net_pts": round(mean(pnls), 4),
        "sum_net_pts": round(sum(pnls), 4),
        "win_rate_pct": round(100 * len(wins) / n, 2),
        "net_breakeven_winrate_pct": round(be, 2) if be is not None else None,
        "stress_1_5_net_pts": (round(mean(p - .5 * c for p, c in zip(pnls, cost_stress)), 4)
                              if cost_stress is not None else None),
        "stress_2_net_pts": (round(mean(p - c for p, c in zip(pnls, cost_stress)), 4)
                            if cost_stress is not None else None),
        "ci95_mean_net_pts": _block_bootstrap_ci(ordered),
        "max_drawdown_pts": round(worst_dd, 4),
        "cvar10_net_pts": cvar10,
        "tp": sum(r["status"] == "CLOSED_TP" for r in trades),
        "sl": sum(r["status"] == "CLOSED_SL" for r in trades),
        "timeout": sum(r["status"] == "CLOSED_TIMEOUT" for r in trades),
    }


def quant_master_report(positions):
    """Produces a non-actionable, read-only report from v3 ledger dictionaries."""
    trades, diagnostics = verified_auto_closed(positions)
    per_side = {side: paper_ev_metrics(
        [r for r in trades if r["side"] == side]) for side in ("LONG", "SHORT")}
    per_strategy = []
    groups = defaultdict(list)
    for row in trades:
        groups[(row["strategy"], row["policy"], row["side"])].append(row)
    for (strategy, policy, side), subset in sorted(groups.items()):
        per_strategy.append({"strategy": strategy, "policy": policy, "side": side,
                             **paper_ev_metrics(subset)})
    recent = {}
    days = sorted(set(x["session_et"] for x in trades))
    for length in (20, 60, 120):
        allowed = set(days[-length:])
        recent[length] = paper_ev_metrics(
            [r for r in trades if r["session_et"] in allowed])
    return {
        "label": "FOKU$ QUANT MASTER — OBSERVED PAPER v3 (NO LIVE ORDER)",
        "champion": "CURRENT_AUTO_UNCHANGED",
        "challenger": "NOT_STARTED / NO_COMPARABLE_FORWARD_RESULTS",
        "source": "Capital.com DEMO REST / US500 / verified AUTO v3 CLOSED",
        "diagnostics": diagnostics,
        "overall": paper_ev_metrics(trades),
        "per_side": per_side,
        "per_strategy": per_strategy,
        "last_sessions": recent,
        "mae_mfe": "MISSING_IN_LEDGER — do not reconstruct from future candles",
        "calibrated_p_long_short": "NOT_AVAILABLE — observed winrate != calibrated forecast",
        "automatic_strategy_changes": False,
    }
