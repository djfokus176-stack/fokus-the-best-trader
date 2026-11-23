"""Candle journal: only confirmed bars, exact source/instrument/TF partition."""
import pandas as pd
import pytest
from trader.storage import connect,archive_candles,load_candles

def sample():
    idx=pd.date_range("2026-11-04T12:00:00Z",periods=5,freq="min")
    return pd.DataFrame({"Open":[100.]*5,"High":[101.]*5,
        "Low":[99.]*5,"Close":[100.]*5,"Spread":[0.6]*5},index=idx)

def test_dedup_and_isolation(tmp_path):
    con=connect(tmp_path/"db.sqlite3")
    bars=sample()
    assert archive_candles(con,bars,"US500","Capital.com DEMO REST","MINUTE")==5
    assert archive_candles(con,bars,"US500","Capital.com DEMO REST","MINUTE")==0
    assert archive_candles(con,bars,"US500","Capital.com LIVE REST","MINUTE")==5
    assert archive_candles(con,bars,"OTHER","Capital.com DEMO REST","MINUTE")==5
    assert archive_candles(con,bars,"US500","Capital.com DEMO REST","MINUTE_5")==5
    result=load_candles(con,"US500","Capital.com DEMO REST","MINUTE")
    assert len(result)==5 and result.index.tz is not None
    assert result.Close.iloc[-1]==100.
    assert len(load_candles(con,"FOO","Capital.com DEMO REST","MINUTE"))==0

def test_rejects_naive_candles(tmp_path):
    con=connect(tmp_path/"db.sqlite3")
    frame=sample();frame.index=frame.index.tz_localize(None)
    with pytest.raises(ValueError):archive_candles(con,frame,"US500","Capital.com DEMO REST","MINUTE")

def test_csv_not_recorded_as_real_broker(tmp_path):
    con=connect(tmp_path/"db.sqlite3")
    assert archive_candles(con,sample(),"US500","CSV NAUKA (NIE LIVE)","MINUTE")==0
