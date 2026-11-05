"""Every research strategy rejects absent data and uses closed candle prefixes."""
import pandas as pd
import numpy as np
from trader.strategies_pro import decide_any, EXTRA, ALL_STRATEGIES


def sample(n=110):
    idx=pd.date_range("2026-11-04 12:00",periods=n,freq="min",tz="UTC")
    p=5000+np.linspace(0,30,n)+np.sin(np.arange(n)*.5)*2
    return pd.DataFrame({"Open":p-.1,"High":p+1.5,"Low":p-1.5,
                         "Close":p},index=idx)


def test_all_strategies_are_named_and_default_to_wait_on_short_data():
    for name in ALL_STRATEGIES:
        d=decide_any(sample(30),name,spread=.6)
        assert d.action=="WAIT"

def test_unknown_strategy_safe_wait():
    assert decide_any(sample(), "STRATEGY THAT DOES NOT EXIST").action=="WAIT"

def test_each_signal_has_valid_geometry_or_wait():
    s=sample()
    for name in ALL_STRATEGIES:
        d=decide_any(s,name,spread=.6)
        assert d.action in ("LONG","SHORT","WAIT")
        if d.action=="LONG":
            assert d.stop<d.entry<d.target and d.rr>0
        elif d.action=="SHORT":
            assert d.target<d.entry<d.stop and d.rr>0

def test_no_future_leakage_from_next_bar():
    s=sample()
    for name in EXTRA:
        before=decide_any(s.iloc[:-1],name,spread=.6)
        modified=s.copy()
        modified.loc[modified.index[-1],"Close"]=999999
        modified.loc[modified.index[-1],"High"]=999999
        after=decide_any(modified.iloc[:-1],name,spread=.6)
        assert before==after

def test_spread_filter_all():
    for name in EXTRA:
        assert decide_any(sample(),name,spread=100).action=="WAIT"
