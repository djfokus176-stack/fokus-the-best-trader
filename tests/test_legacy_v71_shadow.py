"""Legacy v7.1 entry comparison never controls worker, AUTO or broker."""
from pathlib import Path

import numpy as np
import pandas as pd

from trader.auto_strategy import AUTO_MODE, evaluate_auto
from trader.legacy_v71_shadow import (
    DEFAULT_SENSITIVITY, LEGACY_V71_LABEL, evaluate_v71_shadow,
)
from trader.strategies_pro import ALL_STRATEGIES


def sample_frames():
    t = pd.date_range("2026-11-09T17:01Z", periods=120, freq="min")
    closes = np.array([100 + i * .08 for i in range(120)],dtype=float)
    op = closes-.02
    hi = closes+.15
    lo = closes-.15
    # Bullish candle that reclaims EMA9 after tapping EMA21.
    lo[-1] = closes[-1] - 1.1
    op[-1] = closes[-1] - .09
    m5times = pd.date_range("2026-11-09T15:00Z", periods=60, freq="5min")
    m5 = pd.DataFrame({"Close":[80+i*.3 for i in range(60)]},index=m5times)
    m1 = pd.DataFrame({"Open":op,"High":hi,"Low":lo,"Close":closes},index=t)
    return m1,m5


def test_legacy_v71_observes_bullish_ema21_pullback():
    m1,m5=sample_frames()
    d=evaluate_v71_shadow(m1,m5,.5)
    assert d.action=="LONG",d
    assert d.pattern=="odbicie EMA21"
    assert d.m5_bias=="UP"
    assert d.close_mid==float(m1.Close.iloc[-1])


def test_legacy_ignores_future_m5_bars():
    m1,m5=sample_frames()
    baseline=evaluate_v71_shadow(m1,m5,.5)
    # A strong bearish M5 candle AFTER M1 signal time must have no effect.
    future=pd.DataFrame({"Close":[1.,2.,3.]},index=pd.date_range(
        m1.index[-1]+pd.Timedelta(minutes=5),periods=3,freq="5min"))
    replay=evaluate_v71_shadow(m1,pd.concat([m5,future]),.5)
    assert replay==baseline


def test_legacy_requires_real_closed_m5_and_consistent_ohlc():
    m1,m5=sample_frames()
    assert evaluate_v71_shadow(m1,None,.5).action=="WAIT"
    bad=m1.copy()
    bad.loc[bad.index[-1],"High"]=float(bad.Close.iloc[-1])-1.
    assert evaluate_v71_shadow(bad,m5,.5).action=="WAIT"
    future=m5.loc[m5.index>m1.index[-1]]
    assert evaluate_v71_shadow(m1,future,.5).action=="WAIT"
    assert evaluate_v71_shadow(m1,m5,float("nan")).action=="WAIT"


def test_legacy_never_affects_six_strategy_auto_consensus():
    assert LEGACY_V71_LABEL not in ALL_STRATEGIES
    assert len(ALL_STRATEGIES)==6
    assert AUTO_MODE=="AUTO — 6 STRATEGII"
    # Shadow is evaluated independently; worker imports only ALL_STRATEGIES.
    m1,m5=sample_frames()
    legacy=evaluate_v71_shadow(m1,m5,.5)
    assert legacy.action=="LONG"
    from trader.auto_strategy import MIN_AGREEMENT
    assert MIN_AGREEMENT==2
    code=(Path(__file__).resolve().parents[1]/"trader"/"worker.py").read_text("utf-8")
    assert "evaluate_v71_shadow" not in code


def test_ui_labels_legacy_method_as_shadow_and_explains_scope():
    code=(Path(__file__).resolve().parents[1]/"app.py").read_text("utf-8")
    assert "SP500 SIGNAL AI PRO v7.1 (sp500-kolega-gemini)" in code
    assert "METODA ZE STAREGO SYSTEMU v7.1 — LEGACY SHADOW" in code
    assert "Nie jest częścią AUTO 6, nie otwiera PAPER" in code
    assert "Zamknięta M1 (SHADOW)" in code
    assert "Procentu trafności nie podaję" in code
