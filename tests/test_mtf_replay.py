"""Causal M1 close-time CSV -> 5m/15m/H1 replay. No future bars."""
from io import StringIO
import pandas as pd
import numpy as np
import pytest
from trader.csv_data import read_ohlc_csv
from trader.mtf_replay import (build_higher_closed_bars,HistoricalMTFGate,
                               compare_mtf_on_m1_csv,validate_close_time_m1)


def m1_sample(n=4750):
    idx=pd.date_range("2026-10-30T00:01:00Z",periods=n,freq="min",tz="UTC")
    p=5000 + .002*np.arange(n)+.65*np.sin(np.arange(n)/13)
    return pd.DataFrame({"Open":p-.2,"High":p+.8,"Low":p-.8,
                         "Close":p,"Spread":np.full(n,.6)},index=idx)


def test_aggregation_right_closes_only_complete_htf_hours():
    df=m1_sample(120)
    h=build_higher_closed_bars(df)
    assert len(h["MINUTE_5"])==24
    assert len(h["MINUTE_15"])==8
    assert len(h["HOUR"])==2
    first=pd.Timestamp("2026-10-30T01:00:00Z")
    assert h["HOUR"].index[0]==first
    assert h["HOUR"].loc[first,"Open"]==df.iloc[0].Open
    assert h["HOUR"].loc[first,"Close"]==df.iloc[59].Close
    assert h["HOUR"].loc[first,"High"]==df.iloc[:60].High.max()
    assert h["HOUR"].loc[first,"Spread"]==df.iloc[59].Spread


def test_aggregation_drops_bar_when_one_minute_missing():
    df=m1_sample(125)
    df=df.drop(df.index[28])  # within first hour
    h=build_higher_closed_bars(df)
    assert pd.Timestamp("2026-10-30T01:00:00Z") not in h["HOUR"].index
    assert pd.Timestamp("2026-10-30T00:30:00Z") not in h["MINUTE_5"].index
    assert pd.Timestamp("2026-10-30T00:30:00Z") not in h["MINUTE_15"].index
    assert pd.Timestamp("2026-10-30T02:00:00Z") in h["HOUR"].index


def test_mtf_refuses_future_data_or_not_enough_hours():
    df=m1_sample(4100)
    gate=HistoricalMTFGate(df,build_higher_closed_bars(df))
    assert gate.consensus(df.index[-1])=="WAIT"
    with pytest.raises(ValueError):
        compare_mtf_on_m1_csv(df,strategies=("EMA TREND",))
    with pytest.raises(ValueError):
        validate_close_time_m1(df.tz_localize(None))


def test_csv_parser_and_mtf_compare_is_reproducible(monkeypatch):
    df=m1_sample()
    io=StringIO(df.reset_index(names="Time").to_csv(index=False))
    parsed=read_ohlc_csv(io)
    assert len(parsed)==len(df)
    assert parsed.index.equals(df.index)
    import trader.research as research
    from trader.strategy import Decision
    # No candidate: exercise all 4 variants and both periods fast.
    monkeypatch.setattr(research,"decide_any",
                        lambda frame,strategy,spread: Decision("WAIT",strategy,"no setup"))
    table,trades,bars=compare_mtf_on_m1_csv(parsed,strategies=("EMA TREND",),holding=20)
    assert len(table)==4
    assert set(table.wariant)=={"BEZ MTF","Z MTF"}
    assert all(table.n==0)
    assert trades.empty
    assert bars["HOUR"]>=70
    again,_,_=compare_mtf_on_m1_csv(parsed,strategies=("EMA TREND",),holding=20)
    pd.testing.assert_frame_equal(table,again)


def test_mtf_never_sees_future_htf_after_signal(monkeypatch):
    # Introduce a dramatic LAST minute change; past MTF consensus is invariant.
    df=m1_sample(4800)
    earlier_time=df.index[4700]
    gate1=HistoricalMTFGate(df,build_higher_closed_bars(df))
    before=gate1.consensus(earlier_time)
    later=df.copy()
    later.loc[later.index[-1],"Close"]=8000.
    later.loc[later.index[-1],"High"]=8001.
    gate2=HistoricalMTFGate(later,build_higher_closed_bars(later))
    assert gate2.consensus(earlier_time)==before


def test_mtf_uses_last_completed_h1_not_inprogress_hour():
    df=m1_sample(4750)
    gate=HistoricalMTFGate(df,build_higher_closed_bars(df))
    full_hour=pd.Timestamp("2026-11-02T07:00:00Z")
    assert full_hour in gate.series["HOUR"].index
    incomplete=full_hour+pd.Timedelta(minutes=1)
    assert incomplete in df.index
    # A new M1 candle at 07:01 must NOT create a fresh H1 candle at 07:01.
    assert gate.series["HOUR"].index.max()<=full_hour
    assert gate.consensus(incomplete) in ("UP","DOWN","NEUTRAL","WAIT")


def test_historical_mtf_veto_measures_rejections_not_phantom_trades(monkeypatch):
    df=m1_sample(4800)
    df["Open"]=10000-df["Open"]
    df["High"]=10000-df["Low"]
    df["Low"]=10000-(5000+ .002*np.arange(len(df))+.65*np.sin(np.arange(len(df))/13)+.8)
    df["Close"]=10000-df["Close"]
    # Ensure valid OHLC for a synthetic downtrend.
    import trader.research as research
    from trader.strategy import Decision
    def always_long(prefix,strategy,spread):
        entry=float(prefix.Close.iloc[-1])
        return Decision("LONG",strategy,"synthetic test candidate",
                        entry=entry,stop=entry-2,target=entry+4,rr=1.5)
    monkeypatch.setattr(research,"decide_any",always_long)
    report,trade_rows,_=compare_mtf_on_m1_csv(
        df,strategies=("EMA TREND",),holding=10)
    earlier=report[report.okres=="WCZEŚNIEJSZE / 70%"]
    baseline=earlier[earlier.wariant=="BEZ MTF"].iloc[0]
    filtered=earlier[earlier.wariant=="Z MTF"].iloc[0]
    assert baseline["n"]>0
    assert filtered["odrzucone_mtf"]>0
    assert filtered["n"]<=baseline["n"]
