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


def test_timeout_with_positive_pnl_is_not_mistaken_for_target_hit():
    d=pd.DataFrame({"status":["TIMEOUT","LOSS","WIN"],
                    "pnl_pts":[27.0,-12.0,8.0],
                    "r_net":[.7,-1,.3]})
    s=stats(d)
    assert s["n"]==3
    assert s["wins"]==1       # Exact target hit; UI labels it TP
    assert s["profitable_trades"]==2
    assert s["pnl_win_rate_pct"]==66.67
    assert s["positive_timeouts"]==1
    assert s["timeouts"]==1


def test_replay_reuses_slot_after_actual_first_bar_tp(monkeypatch):
    from trader.strategy import Decision
    import trader.research as research

    x=candles(n=170)
    # Each future first bar hits its target, never its stop.
    x["Open"]=5000+np.arange(170)*.02
    x["Close"]=x["Open"]+.02
    x["High"]=x["Open"]+1.6
    x["Low"]=x["Open"]-.2

    def approved(prefix,strategy,spread):
        price=float(prefix.Close.iloc[-1])
        return Decision("LONG",strategy,"test entry",price,price-1,
                        price+1,1.6)
    monkeypatch.setattr(research,"decide_any",approved)
    result=replay(x,"EMA TREND",spread=.4,slippage=.25,
                  holding=20,evaluation_start=90)
    assert len(result)>=30, ("Must not skip 20 bars after a first-bar TP")
    assert (result.status=="WIN").all()
    assert result.time_utc.is_monotonic_increasing
    # New signal can be generated from first exited candle, not before.
    diffs=result.time_utc.diff().dropna().dt.total_seconds()
    assert (diffs==60).all()


def test_exit_bar_counter_preserves_sl_first_on_same_bar():
    from trader.research import _bars_through_exit
    t=pd.date_range("2026-11-10",periods=3,freq="min",tz="UTC")
    bars=pd.DataFrame({"Open":[100,100,100],
                       "High":[102,100.1,100.1],
                       "Low":[98,99.9,99.9],"Close":[100,100,100]},index=t)
    assert _bars_through_exit(bars,"LONG",stop=99,target=101)==1
    assert _bars_through_exit(bars,"SHORT",stop=101,target=99)==1
    assert _bars_through_exit(bars,"LONG",stop=97,target=103)==3
