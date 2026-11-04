"""Historical chart markers must be derived only from completed past bars."""
import pandas as pd
from trader import visuals
from trader.strategy import Decision

def test_marks_use_closed_prefixes(monkeypatch):
    seen = []
    def fake_decide(df, strategy, spread):
        seen.append((len(df), df.index[-1], spread))
        return Decision("LONG", strategy, "test", entry=float(df.Close.iloc[-1]))
    monkeypatch.setattr(visuals, "decide", fake_decide)
    n = 82
    idx = pd.date_range("2026-11-04", periods=n, freq="min", tz="UTC")
    df = pd.DataFrame({"Open":range(n),"High":[k+1 for k in range(n)],
                       "Low":[k-1 for k in range(n)],"Close":range(n),
                       "Spread":[0.4]*n}, index=idx)
    marks = visuals.historical_marks(df, "EMA TREND", max_bars=7)
    assert len(marks)==7
    assert seen[0][0]==76
    assert seen[-1][0]==82
    assert all(length == df.index.get_loc(t)+1 for length,t,_ in seen)
    assert all(spread==0.4 for _,_,spread in seen)

def test_empty_and_invalid_spread(monkeypatch):
    n=74
    idx = pd.date_range("2026-11-04", periods=n, freq="min", tz="UTC")
    df=pd.DataFrame({"Open":[1]*n,"High":[2]*n,"Low":[0]*n,"Close":[1]*n,
                     "Spread":[float("nan")]*n},index=idx)
    assert visuals.historical_marks(df,"DRUGA FALA").empty
