"""Display-only attribution of PAPER strategies without changing execution.

A PAPER ledger stores the ORIGINAL selected method in `strategy`. AUTO
selection is documented in `setup_reason` by the unchanged AUTO engine.
Do not infer AUTO from the current UI choice, a recent signal or price.

The manual order is an owner-requested research PRESENTATION priority, not
an empirical win-rate ranking and not the AUTO selection algorithm.
"""
from __future__ import annotations

from .auto_strategy import AUTO_MODE
from .strategies_pro import ALL_STRATEGIES
from .ema50_wave import STRATEGY_NAME as WAVE_NAME
from .fokus_3f import NAME as THREEF_NAME

RESEARCH_DISPLAY_ORDER = (
    AUTO_MODE,
    "BREAKOUT RETEST",
    "VOLATILITY BREAKOUT",
    "EMA PULLBACK",
    "LIQUIDITY SWEEP",
    "DRUGA FALA",
    "EMA TREND",
    WAVE_NAME,
    THREEF_NAME,
)
assert set(RESEARCH_DISPLAY_ORDER) == {AUTO_MODE, *ALL_STRATEGIES, WAVE_NAME, THREEF_NAME}
assert len(set(RESEARCH_DISPLAY_ORDER)) == len(RESEARCH_DISPLAY_ORDER)


def display_choice(name):
    """Owner's preferred ordering; not a return or profitability claim."""
    if name not in RESEARCH_DISPLAY_ORDER:
        return str(name)
    return f"{RESEARCH_DISPLAY_ORDER.index(name) + 1}. {name}"


def method_attribution(position):
    """Mode + actual selected method, using only this trade's stored data.

    The AUTO origin is verified from the original setup_reason. Older
    entries lacking it cannot be retrospectively tagged AUTO merely
    because AUTO is the default in today's browser.
    """
    if not isinstance(position, dict):
        return {"mode": "NIEUSTALONY", "method": "BRAK",
                "label": "METODA NIEUSTALONA"}
    method = str(position.get("strategy") or "").strip()
    if method not in ALL_STRATEGIES and method != WAVE_NAME:
        return {"mode": "NIEUSTALONY", "method": "BRAK",
                "label": "METODA NIEUSTALONA"}
    reason = position.get("setup_reason")
    auto_proven = (isinstance(reason, str)
                   and "AUTO PAPER (eksperyment 1 sygnału)" in reason)
    if auto_proven and method in ALL_STRATEGIES:
        return {"mode": AUTO_MODE, "method": method,
                "label": "AUTO → " + method}
    return {"mode": "NIEUSTALONY / POJEDYNCZY", "method": method,
            "label": "METODA: " + method}


def decision_attribution(requested_strategy, decision):
    """Label a CURRENT hypothesis, never a confirmed PAPER fill."""
    action = getattr(decision, "action", None)
    method = getattr(decision, "strategy", None)
    if action not in ("LONG", "SHORT"):
        return "WAIT — BRAK ZATWIERDZONEJ METODY"
    if method not in ALL_STRATEGIES and method != WAVE_NAME:
        return "SYGNAŁ BEZ POTWIERDZONEJ METODY"
    if requested_strategy == AUTO_MODE and method in ALL_STRATEGIES:
        return "AUTO → " + method
    return "METODA: " + method
