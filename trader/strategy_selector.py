"""Causal market-regime selector for the six already-approved PAPER setups.

The selector can ONLY rank candidates that passed their original strategy
entry rules and MTF veto. It never changes LONG/SHORT direction, SL/TP, the
number of votes, costs, broker clock, data freshness or macro safety.
Scores are descriptive relative fit scores, not calibrated probabilities,
win rates, learned ML weights or proven profitability.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .market_dna import analyze_market
from .strategies_pro import ALL_STRATEGIES

# Priors, NOT fitted to data; use current regime as a deterministic tiebreaker.
# The regime classification is based entirely on the supplied closed bars.
PRIORITY = {
    "TREND WZROSTOWY": {
        "EMA PULLBACK": 4, "EMA TREND": 3, "DRUGA FALA": 3,
        "BREAKOUT RETEST": 2, "VOLATILITY BREAKOUT": 1, "LIQUIDITY SWEEP": 0},
    "TREND SPADKOWY": {
        "EMA PULLBACK": 4, "EMA TREND": 3, "DRUGA FALA": 3,
        "BREAKOUT RETEST": 2, "VOLATILITY BREAKOUT": 1, "LIQUIDITY SWEEP": 0},
    "EKSPANSJA ZMIENNOŚCI": {
        "VOLATILITY BREAKOUT": 4, "BREAKOUT RETEST": 3,
        "DRUGA FALA": 3, "EMA TREND": 2,
        "EMA PULLBACK": 1, "LIQUIDITY SWEEP": 0},
    "KOMPRESJA ZMIENNOŚCI": {
        "VOLATILITY BREAKOUT": 4, "BREAKOUT RETEST": 3,
        "LIQUIDITY SWEEP": 2, "EMA PULLBACK": 1,
        "EMA TREND": 0, "DRUGA FALA": 0},
    "KONSOLIDACJA / MAŁA EFEKTYWNOŚĆ": {
        "LIQUIDITY SWEEP": 4, "BREAKOUT RETEST": 3,
        "VOLATILITY BREAKOUT": 2, "EMA PULLBACK": 1,
        "DRUGA FALA": 0, "EMA TREND": 0},
    "MIESZANY / PRZEJŚCIOWY": {
        "BREAKOUT RETEST": 2, "LIQUIDITY SWEEP": 2,
        "DRUGA FALA": 1, "EMA PULLBACK": 1,
        "EMA TREND": 1, "VOLATILITY BREAKOUT": 1},
}

@dataclass(frozen=True)
class MarketSelection:
    regime: str
    market_event: str
    market_status: str
    preferred: tuple[str, ...]
    selected: str | None
    selection_reason: str
    ranking: tuple[dict, ...]


def market_context(frame):
    """Read-only context. Unavailable data never creates a trade."""
    if frame is None or len(frame) < 85:
        return "BRAK WIARYGODNEGO REŻIMU", "BRAK", "NOT_READY"
    try:
        dna=analyze_market(frame)
        if dna.regime not in PRIORITY:
            return "MIESZANY / PRZEJŚCIOWY", dna.event, "UNKNOWN_REGIME"
        return dna.regime,dna.event,"READY"
    except (ValueError,KeyError,TypeError,IndexError,ArithmeticError):
        return "BRAK WIARYGODNEGO REŻIMU","BRAK","NOT_READY"


def _rating(name, regime, event):
    base=PRIORITY.get(regime,{})
    score=base.get(name,0)
    # Recognized break/sweep event from completed bars may break ties, but
    # never overrides a strategy/MTF veto or a numeric RR requirement.
    if name=="LIQUIDITY SWEEP" and event.startswith("SWEEP "):
        score+=2
    if name=="BREAKOUT RETEST" and event.startswith("BOS "):
        score+=1
    return score


def select_approved(frame, approved):
    """Return (approved decision or None, market summary).

    A single eligible strategy is selected without extra veto. With several
    eligible candidates choose best regime fit, then their original net RR,
    then a deterministic name. Never rank WAIT as executable.
    """
    regime,event,status=market_context(frame)
    preferred=tuple(sorted(
        ALL_STRATEGIES,key=lambda n:(-_rating(n,regime,event),n)))
    candidates=[]
    for decision in approved:
        if decision.strategy not in ALL_STRATEGIES or decision.action not in ("LONG","SHORT"):
            continue
        try:
            rr=float(decision.rr)
        except (ValueError,TypeError,OverflowError):
            rr=float("-inf")
        if not isfinite(rr):
            rr=float("-inf")
        candidates.append({
            "strategy":decision.strategy,"side":decision.action,
            "regime_fit":_rating(decision.strategy,regime,event),
            "rr":rr,"decision":decision})
    candidates.sort(key=lambda c:(-c["regime_fit"] if status=="READY" else 0,
                                   -c["rr"],c["strategy"]))
    selected=candidates[0]["decision"] if candidates else None
    if selected is None:
        why=("Brak zatwierdzonego setupu po MTF. Reżim rynku służy tylko "
             "do kolejności obserwacji, nie tworzy LONG/SHORT.")
    elif status=="READY":
        why=(f"Reżim: {regime}; zdarzenie: {event}. "
             f"Wybrano {selected.strategy} spośród {len(candidates)} "
             "zatwierdzonych metod: dopasowanie do rynku, potem RR. "
             "Ocena dopasowania NIE jest procentem skuteczności.")
    else:
        why=(f"Brak zweryfikowanego reżimu — spośród {len(candidates)} "
             "zatwierdzonych metod wybrano najwyższe RR. "
             "Dopasowanie rynku nie zostało potwierdzone.")
    return selected, MarketSelection(
        regime=regime,market_event=event,market_status=status,
        preferred=preferred,selected=selected.strategy if selected else None,
        selection_reason=why,
        ranking=tuple({"Strategia":c["strategy"],
                       "Kierunek":c["side"],
                       "Dopasowanie (nie %)":c["regime_fit"] if status=="READY" else None,
                       "RR":c["rr"] if isfinite(c["rr"]) else None}
                      for c in candidates))
