import pandas as pd
import numpy as np
from trader.research import replay,stats,chronological_report,rolling_oos


def candles(n=320):
    idx=pd.date_range("2026-11-02",periods=n,freq="min",tz="UTC")
    p=5000+np.arange(n)*.06+np.sin(np.arange(n)/6)*1.5
    return pd.DataFrame({"Open":p-.1,"Close":p,"High":p+1,
                         "Low":p-1,"Spread":[.6]*n},index=idx)


def test_chronological_holdout_uses_requested_strategy():
    x=candles()
    r=chronological_report(x,strategies=("EMA TREND","LIQUIDITY SWEEP"),spread=.6)
    assert len(r)==4
    assert set(r.okres)=={"TRAIN / REPLAY","HOLDOUT / PÓŹNIEJSZE"}
    assert (r.n>=0).all()


def test_stats_no_fake_proof_and_cautious_sample():
    assert stats(pd.DataFrame())["status"]=="BRAK TRANSAKCJI"
    d=pd.DataFrame({"status":["WIN","LOSS","TIMEOUT"],
                    "pnl_pts":[1.4,-2.6,-.5],"r_net":[.4,-.8,-.1]})
    v=stats(d)
    assert v["n"]==3 and v["wins"]==1
    assert v["sum_pts"]==-1.7
    assert v["max_drawdown_pts"]>0
    assert "MAŁA PRÓBA" in v["status"]


def test_replay_no_overlap_and_future_prefix(monkeypatch):
    import trader.research as research
    from trader.strategy import Decision
    seen=[]
    def fake_decide(df, strategy,spread):
        seen.append(df.index[-1])
        return Decision("WAIT",strategy,"no entry")
    monkeypatch.setattr(research,"decide_any",fake_decide)
    out=replay(candles(125),"EMA TREND",holding=5,evaluation_start=90)
    assert out.empty
    assert all(ts <= candles(125).index[-6] for ts in seen)


def test_rolling_oos_and_invalid_args():
    data=candles(360)
    r=rolling_oos(data,"DRUGA FALA")
    assert len(r)>1
    import pytest
    with pytest.raises(ValueError):
        replay(data,"BAD STRATEGY")
