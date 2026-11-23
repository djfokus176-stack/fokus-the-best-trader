"""Fixed entries, real cost accounting and chronological exits regression."""
import numpy as np
import pandas as pd
import pytest

from trader.strategy import Decision
import trader.exit_grid as grid
from trader.auto_strategy import AUTO_MODE
from trader.strategies_pro import ALL_STRATEGIES


def m1(n=400):
    idx=pd.date_range("2026-11-09T08:00:00Z",periods=n,freq="min")
    p=np.full(n,100.)
    return pd.DataFrame({
        "Open":p,"High":p+2.0,"Low":p-1.0,
        "Close":p,"Spread":np.full(n,.6)
    },index=idx)


def always_long(prefix,strategy,spread):
    assert prefix.index[-1] == prefix.index.max()
    return Decision("LONG",strategy,"synthetic verified close only",
                    100.,98.,104.,1.6,2.,"UP")


def test_grid_uses_frozen_identical_entries_and_conservative_exit(monkeypatch):
    monkeypatch.setattr(grid,"decide_any",always_long)
    ranking,detail,meta=grid.compare_same_entries(m1(),slippage=.25)
    assert len(ranking)==18
    assert len(detail)==9*sum(v["kwalifikowane"]
                               for v in meta["counts"].values())
    assert all(ranking.groupby("okres").proby.nunique()==1)
    assert len(set(detail.sl_mid))==1
    assert set(detail.rr_tp)=={1.,1.5,2.}
    assert set(detail.limit_m1)=={10,20,30}
    assert set(detail.strona)=={"LONG"}
    assert set(detail.spread_model)=={"fixed"}
    # Open 100, stop 98, 1R target 102. First bar touches target:
    # 2 gross MID, cost = 0.6 spread + 2*0.25 slippage = 1.1.
    first=detail[(detail.rr_tp==1.0)&(detail.limit_m1==10)].iloc[0]
    assert first.status=="WIN"
    assert first.pnl_pts==.9
    assert first.gross_mid_pts==2.
    assert first.koszty_pkt==1.1
    # 1.5R target 103 not touched: close 100 after 10 bars, -1.10 costs.
    other=detail[(detail.rr_tp==1.5)&(detail.limit_m1==10)].iloc[0]
    assert other.status=="TIMEOUT" and other.pnl_pts==-1.1
    # Same exact frozen signal time in all nine exit variants.
    assert detail.groupby(["okres","rr_tp","limit_m1"]).sygnal_utc.nunique().min()>0
    for period,g in detail.groupby("okres"):
        assert g.groupby(["rr_tp","limit_m1"]).sygnal_utc.apply(
            lambda s: tuple(s)).nunique()==1


def test_grid_does_not_use_future_candles_in_train(monkeypatch):
    seen=[]
    def decide(prefix,strategy,spread):
        seen.append(prefix.index[-1])
        return always_long(prefix,strategy,spread)
    monkeypatch.setattr(grid,"decide_any",decide)
    frame=m1(400)
    ranking,detail,meta=grid.compare_same_entries(frame)
    boundary=pd.Timestamp(meta["split_after_utc"])
    earlier=detail[detail.okres=="WCZESNIEJSZE 70%"]
    assert not earlier.empty
    assert (earlier.candle_exit_utc<boundary).all()
    later=detail[detail.okres=="POZNIEJSZE 30%"]
    assert (later.sygnal_utc>=boundary-pd.Timedelta(minutes=1)).all()
    assert all(ts in frame.index for ts in seen)
    assert all(ts<frame.index[-30] for ts in seen)


def test_gap_invalidates_all_variants_not_only_losing_ones(monkeypatch):
    monkeypatch.setattr(grid,"decide_any",always_long)
    frame=m1(400)
    # Time gap falls inside a 30-bar comparison window.
    frame=frame.drop(frame.index[135])
    _,details,meta=grid.compare_same_entries(frame)
    assert meta["counts"]["WCZESNIEJSZE 70%"]["odrzucone_luki"]>=1
    assert all(details.groupby(["okres","rr_tp","limit_m1"]).sygnal_utc.nunique()>=0)
    assert details.groupby(["okres","rr_tp","limit_m1"]).sygnal_utc.nunique().groupby(level=0).nunique().max()==1


def test_variable_spread_uses_last_known_close_not_future_close(monkeypatch):
    monkeypatch.setattr(grid,"decide_any",always_long)
    frame=m1(400)
    frame.Spread=1.0
    ranking,detail,_=grid.compare_same_entries(frame,spread_mode="historical",
                                                 slippage=0)
    rows=detail[(detail.rr_tp==1.) & (detail.limit_m1==10)]
    assert (rows.koszty_pkt==1.).all()
    assert (rows.pnl_pts==1.).all()
    assert set(detail.spread_model)=={"historical"}
    with pytest.raises(ValueError,match="Spread"):
        grid.compare_same_entries(frame.drop(columns=["Spread"]),
                                  spread_mode="historical")


def test_research_does_not_expand_six_auto_or_make_production_changes():
    assert AUTO_MODE=="AUTO — 6 STRATEGII"
    assert len(ALL_STRATEGIES)==6
    assert len(grid.R_MULTIPLES)==3 and len(grid.HOLDINGS)==3
    with pytest.raises(ValueError,match="sześciu"):
        grid.compare_same_entries(m1(),strategy="ORB30 New York")
    with pytest.raises(ValueError):
        grid.compare_same_entries(m1(),split=.9)
