"""Owner-side OHLC archive export is causal, UTC-close, and credential-free."""
from io import BytesIO
import pandas as pd
import pytest

from trader.cloud_research_export import research_csv_from_closed_m1
from trader.csv_data import read_ohlc_csv


def candles(n=4800):
    # Each stamp is a completed minute; 00:01 through 80:00, 80 full H1.
    idx=pd.date_range("2026-11-02T00:01:00Z",periods=n,freq="min")
    price=5000+pd.Series(range(n)).to_numpy()*.01
    return pd.DataFrame({"Open":price,"High":price+.5,"Low":price-.5,
                         "Close":price+.1,"Spread":[.6]*n},index=idx)


def test_export_is_exact_utc_close_csv_with_no_secrets():
    frame=candles()
    output=research_csv_from_closed_m1(frame)
    assert output["preflight_mtf"]
    assert output["count"]==4800
    assert output["full_h1"]>=70
    assert output["gaps"]==0
    assert output["first"]==frame.index[0].isoformat()
    assert output["last"]==frame.index[-1].isoformat()
    assert b"apikey" not in output["csv"].lower()
    parsed=read_ohlc_csv(BytesIO(output["csv"]))
    assert parsed.index.equals(frame.index)
    assert len(parsed)==len(frame)
    assert parsed.iloc[-1].Spread==.6


def test_export_reports_missing_hours_without_faking_mtf():
    incomplete=candles().drop(candles().index[::60])
    output=research_csv_from_closed_m1(incomplete)
    assert output["count"]<4600 or output["full_h1"]<70
    assert output["full_h1"]<70
    assert output["gaps"]>0
    assert not output["preflight_mtf"]


def test_export_fails_closed_on_unverified_time_or_more_than_5000():
    naive=candles(120)
    naive.index=naive.index.tz_localize(None)
    with pytest.raises(ValueError):
        research_csv_from_closed_m1(naive)
    with pytest.raises(ValueError):
        research_csv_from_closed_m1(candles(5001))
