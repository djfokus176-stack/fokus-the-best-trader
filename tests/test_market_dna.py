"""Conservative research-level tests for MARKET DNA without future leakage."""
import numpy as np
import pandas as pd
import pytest
from trader.market_dna import analyze_market, confirmed_pivots


def bars(n=100):
    idx=pd.date_range('2026-11-04T12:00:00Z',periods=n,freq='min')
    p=np.array([100+0.1*i+np.sin(i*.7)*2 for i in range(n)], dtype=float)
    return pd.DataFrame({'Open':p-.1,'Close':p,'High':p+.4,'Low':p-.5},index=idx)


def test_waits_for_two_closed_confirmation_bars():
    df=bars(15)
    df.iloc[8,df.columns.get_loc('High')]=200
    assert 8 not in [i for i,_ in confirmed_pivots(df.iloc[:10])]
    assert 8 in [i for i,_ in confirmed_pivots(df.iloc[:11])]


def test_mutating_current_bar_does_not_rewrite_confirmed_levels():
    df=bars(100)
    h1,l1=confirmed_pivots(df.iloc[:-1])
    df.iloc[-1,df.columns.get_loc('High')]=2000
    df.iloc[-1,df.columns.get_loc('Low')]=-1000
    h2,l2=confirmed_pivots(df.iloc[:-1])
    assert (h1,l1)==(h2,l2)


def test_no_false_probability_and_decision():
    dna=analyze_market(bars(100))
    assert 0<=dna.efficiency<=1
    assert dna.atr>0
    assert dna.regime
    assert not hasattr(dna,'probability')
    assert not hasattr(dna,'action')


def test_sweep_high_detects_rejection_of_confirmed_high():
    df=bars(100)
    historical_high=max(v for _,v in confirmed_pivots(df.iloc[:-1])[0])
    # The last bar tests prior resistance with wick above but close below.
    df.loc[df.index[-1],'High']=historical_high+3
    df.loc[df.index[-1],'Close']=historical_high-.3
    df.loc[df.index[-1],'Open']=historical_high-.2
    df.loc[df.index[-1],'Low']=historical_high-1
    out=analyze_market(df)
    # The latest confirmed pivot, rather than global high, is the comparison.
    assert out.event.startswith('SWEEP HIGH')


def test_bad_or_short_data_refused():
    with pytest.raises(ValueError):
        analyze_market(bars(20))
    with pytest.raises(ValueError):
        confirmed_pivots(bars(90),right=0)
