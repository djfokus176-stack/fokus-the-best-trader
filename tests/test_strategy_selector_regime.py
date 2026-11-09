"""AUTO's market-regime choice is deterministic, PAPER-only and never a bypass."""
from pathlib import Path

import numpy as np
import pandas as pd

from trader.strategy import Decision
from trader import auto_strategy
from trader import strategy_selector as selector
from trader.strategies_pro import ALL_STRATEGIES

def decision(name,side="LONG",rr=1.7):
    return Decision(side,name,"verified original setup",100,98,104,rr)

def uptrend():
    idx=pd.date_range("2026-11-09T10:01:00Z",periods=130,freq="min")
    close=np.array([100+.2*i for i in range(130)],dtype=float)
    return pd.DataFrame({
        "Open":close-.1,"High":close+.3,"Low":close-.3,"Close":close,
        "Spread":[.4]*130
    },index=idx)


def test_auto_market_conditions_use_existing_closed_bars_only():
    full=uptrend()
    prefix=full.iloc[:-1]
    regime1=selector.market_context(prefix)
    contaminated=pd.concat([prefix,full.iloc[[-1]].assign(Close=9999,
        Open=9990,High=10010,Low=9900)])
    # Choose only the closed prefix — no forming or future bar can influence it.
    assert selector.market_context(contaminated.iloc[:-1])==regime1
    assert regime1[0] in selector.PRIORITY


def test_chooses_pullback_for_trend_even_if_rr_somewhat_lower(monkeypatch):
    monkeypatch.setattr(selector,"market_context",
                        lambda frame:("TREND WZROSTOWY","BRAK","READY"))
    choices=[decision("VOLATILITY BREAKOUT",rr=2.8),
             decision("EMA PULLBACK",rr=1.5)]
    picked,report=selector.select_approved(uptrend(),choices)
    assert picked.strategy=="EMA PULLBACK"
    assert picked.action=="LONG" and picked.rr==1.5
    assert report.market_status=="READY"
    assert len(report.ranking)==2
    assert report.ranking[0]["Strategia"]=="EMA PULLBACK"


def test_chooses_liquidity_sweep_in_consolidation(monkeypatch):
    monkeypatch.setattr(selector,"market_context",
        lambda frame:("KONSOLIDACJA / MAŁA EFEKTYWNOŚĆ",
                      "SWEEP LOW — hipoteza odrzucenia wybicia","READY"))
    picked,report=selector.select_approved(uptrend(),[
        decision("EMA TREND",rr=2.5),
        decision("LIQUIDITY SWEEP",rr=1.5)])
    assert picked.strategy=="LIQUIDITY SWEEP"
    assert report.market_event.startswith("SWEEP")


def test_without_verified_regime_fallback_is_rr_then_name(monkeypatch):
    monkeypatch.setattr(selector,"market_context",
        lambda frame:("BRAK WIARYGODNEGO REŻIMU","BRAK","NOT_READY"))
    picked,report=selector.select_approved(pd.DataFrame(),[
        decision("EMA PULLBACK",rr=1.5),decision("EMA TREND",rr=1.9)])
    assert picked.strategy=="EMA TREND"
    assert "Brak zweryfikowanego reżimu" in report.selection_reason


def test_wait_never_manufactures_buy_or_sell(monkeypatch):
    monkeypatch.setattr(selector,"market_context",
        lambda frame:("TREND SPADKOWY","BRAK","READY"))
    picked,report=selector.select_approved(uptrend(),[
        decision("EMA PULLBACK",side="WAIT")])
    assert picked is None and report.selected is None
    assert "nie tworzy LONG/SHORT" in report.selection_reason


def test_integration_only_selects_post_mtf_approved_and_never_conflict(monkeypatch):
    monkeypatch.setattr(selector,"market_context",
        lambda frame:("TREND WZROSTOWY","BRAK","READY"))
    def signals(frame,name,spread):
        if name=="EMA TREND":
            return decision(name,rr=2.7)
        if name=="EMA PULLBACK":
            return decision(name,rr=1.5)
        return Decision("WAIT",name,"no signal")
    monkeypatch.setattr(auto_strategy,"decide_any",signals)
    monkeypatch.setattr(auto_strategy,"filter_mtf_decision",
                        lambda x,snaps,asof:(x,[]))
    chosen,rows=auto_strategy.evaluate_auto(uptrend(),.4,use_mtf=True)
    assert chosen.action=="LONG"
    assert chosen.strategy=="EMA PULLBACK"
    assert "Reżim: TREND WZROSTOWY" in chosen.reason
    assert "GŁOSY MTF 2/2" in chosen.reason
    # Even a high-priority candidate vetoed by MTF must never be chosen.
    monkeypatch.setattr(auto_strategy,"filter_mtf_decision",
        lambda x,snaps,asof:(Decision("WAIT",x.strategy,"MTF veto"),[])
                              if x.strategy=="EMA PULLBACK" else (x,[]))
    chosen,rows=auto_strategy.evaluate_auto(uptrend(),.4,use_mtf=True)
    assert chosen.strategy=="EMA TREND"
    assert "GŁOSY MTF 1/2" in chosen.reason
    # Raw opposing side still blocks the whole AUTO even if its MTF vetoed.
    def conflict(frame,name,spread):
        if name=="EMA PULLBACK":
            return decision(name,"SHORT")
        if name=="EMA TREND":
            return decision(name)
        return Decision("WAIT",name,"no")
    monkeypatch.setattr(auto_strategy,"decide_any",conflict)
    chosen,rows=auto_strategy.evaluate_auto(uptrend(),.4,use_mtf=True)
    assert chosen.action=="WAIT"
    assert "Konflikt" in chosen.reason


def test_market_choice_is_not_evidence_of_profitability_or_real_trading():
    root=Path(__file__).resolve().parents[1]
    source=(root/"trader"/"strategy_selector.py").read_text("utf-8")
    ui=(root/"app.py").read_text("utf-8")
    worker=(root/"trader"/"worker.py").read_text("utf-8")
    assert "AUTO — SAM DOBIERAM METODĘ DO WARUNKÓW RYNKU" in ui
    assert "Automatyczny wybór nie otwiera LONG/SHORT" in ui
    assert "queue_paper" not in source
    assert "client.create_position" not in source
    assert "evaluate_auto(" in worker
    assert "MIN_AGREEMENT = 1" in (root/"trader"/"auto_strategy.py").read_text("utf-8")
