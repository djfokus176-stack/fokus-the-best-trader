"""Cache must reuse identical candles and invalidate on amended OHLC."""
import pandas as pd
from trader import arrow_cache, visuals
from trader.strategy import Decision

def sample():
    idx=pd.date_range("2026-11-05",periods=110,freq="min",tz="UTC")
    close=[5000.0+i*.02 for i in range(110)]
    return pd.DataFrame({"Open":close,"High":[x+1 for x in close],
        "Low":[x-1 for x in close],"Close":close,
        "Spread":[0.4]*110},index=idx)

def test_cache_hit_and_content_change(monkeypatch):
    calls=[]
    def fake(df, strategy, max_bars):
        calls.append((strategy,max_bars,len(df),float(df.Close.iloc[-1])))
        return pd.DataFrame([{"time":df.index[-1],"action":"LONG",
                              "price":float(df.Close.iloc[-1]),"reason":"test"}])
    monkeypatch.setattr(visuals,"historical_marks",fake)
    arrow_cache.cached_historical_marks.clear()
    df=sample()
    a=arrow_cache.cached_historical_marks(df,"US500","MINUTE","Capital.com DEMO REST","EMA TREND",60)
    b=arrow_cache.cached_historical_marks(df.copy(),"US500","MINUTE","Capital.com DEMO REST","EMA TREND",60)
    assert len(calls)==1
    assert a.equals(b)
    changed=df.copy()
    changed.loc[changed.index[-1],"Close"]+=2.
    arrow_cache.cached_historical_marks(changed,"US500","MINUTE","Capital.com DEMO REST","EMA TREND",60)
    assert len(calls)==2

def test_cache_isolated_by_strategy_window_and_feed(monkeypatch):
    calls=[]
    def fake(df,strategy,max_bars):
        calls.append(1)
        return pd.DataFrame(columns=["time","action","price","reason"])
    monkeypatch.setattr(visuals,"historical_marks",fake)
    arrow_cache.cached_historical_marks.clear()
    d=sample()
    for strategy,window,src in [
        ("DRUGA FALA",120,"Capital.com DEMO REST"),
        ("EMA TREND",120,"Capital.com DEMO REST"),
        ("EMA TREND",240,"Capital.com DEMO REST"),
        ("EMA TREND",240,"Capital.com LIVE REST")
    ]:
        arrow_cache.cached_historical_marks(d,"US500","MINUTE",src,strategy,window)
    assert len(calls)==4
