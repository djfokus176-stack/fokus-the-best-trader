"""Legacy-inspired EMA50 hypothesis: no old files edited, no fake trade arrows."""
import numpy as np
import pandas as pd
from trader.ema50_wave import STRATEGY_NAME,wave_decision
from trader.strategies_pro import ALL_STRATEGIES,decide_any
from trader.auto_strategy import evaluate_auto,AUTO_MODE


def trending_frame(direction=1, n=100):
    idx=pd.date_range("2026-11-05T16:00:00Z",periods=n,freq="min")
    close=np.array([100+direction*i*.3 for i in range(n)],dtype=float)
    open_=close-direction*.1
    high=close+.6
    low=close-.6
    # The last bar pulls back to EMA21 then closes back with the trend.
    moving=pd.Series(close).ewm(span=21,adjust=False).mean().iloc[-1]
    if direction==1:
        low[-1]=min(low[-1],float(moving)-.2)
    else:
        high[-1]=max(high[-1],float(moving)+.2)
    return pd.DataFrame({"Open":open_,"High":high,"Low":low,
        "Close":close},index=idx)


def test_wave_detects_latest_finished_long_and_short_without_future():
    for direction, expected in ((1,"LONG"),(-1,"SHORT")):
        df=trending_frame(direction)
        result=wave_decision(df,.6)
        assert result.strategy==STRATEGY_NAME
        assert result.action==expected, result.reason
        assert result.entry==round(float(df.Close.iloc[-1]),2)
        assert result.rr>1.35
        assert (result.stop<result.entry<result.target if direction==1
                else result.target<result.entry<result.stop)


def test_bad_data_and_spread_fail_closed():
    df=trending_frame()
    assert wave_decision(df.iloc[:60]).action=="WAIT"
    assert wave_decision(df,spread=10).action=="WAIT"
    broken=df.copy()
    broken.loc[broken.index[-1],"Close"]=np.nan
    assert wave_decision(broken).action=="WAIT"


def test_wave_never_enters_six_strategy_auto_consensus():
    assert len(ALL_STRATEGIES)==6
    assert STRATEGY_NAME not in ALL_STRATEGIES
    assert decide_any(trending_frame(),STRATEGY_NAME).action=="LONG"
    verdict,votes=evaluate_auto(trending_frame(),.6,use_mtf=False)
    assert verdict.strategy==AUTO_MODE or verdict.action in ("LONG","SHORT")
    assert len(votes)==6
    assert all(v["Strategia"]!=STRATEGY_NAME for v in votes)


def test_new_app_does_not_import_or_modify_legacy_files():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    wave=(root/"trader"/"ema50_wave.py").read_text(encoding="utf-8")
    app=(root/"app.py").read_text(encoding="utf-8")
    assert "archiwum_sygnalow_sp500.json" not in wave
    assert "archiwum_sygnalow_sp500.json" not in app
    assert "cached_historical_marks(" not in app
    assert "annotate_paper_history(fig," in app
