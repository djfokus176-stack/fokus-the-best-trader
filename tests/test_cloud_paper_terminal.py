"""The owner terminal reads Supabase without requiring Capital auth."""
import pandas as pd
import pytest

from trader.cloud_paper_terminal import cloud_terminal_summary


def frame():
    idx=pd.date_range("2026-11-13T20:45:00Z",periods=5,freq="15min")
    return pd.DataFrame({
        "Open":[5000.]*5,"High":[5003.]*5,"Low":[4997.]*5,
        "Close":[5001.]*5,"Spread":[0.9]*5},index=idx)


def test_worker_checkpoint_view_does_not_require_capital_login():
    payload={"meta":{"source":"Capital.com DEMO REST","epic":"US500",
           "last_scan_utc":"2026-11-15T15:00:00Z",
           "last_scan_summary":"WAIT / MARKET_CLOSED",
           "candle_backfill_enabled":True}}
    r=cloud_terminal_summary(7430,payload,frame(),
                             now="2026-11-15T15:03:00Z")
    assert r["version"]==7430
    assert r["bars"]==5
    assert r["cloud_online_confirmed"] is True
    assert r["age_minutes"]==3
    assert r["trade_permission"]=="WAIT"
    assert r["no_direct_capital_login"] is True
    assert "MARKET_CLOSED" in r["worker_summary"]


def test_stale_worker_checkpoint_is_explicitly_unknown():
    r=cloud_terminal_summary(7000,{
        "meta":{"last_scan_utc":"2026-11-13T14:00:00Z",
                "source":"Capital.com DEMO REST"}},
        frame(),now="2026-11-15T15:00:00Z")
    assert r["cloud_online_confirmed"] is False
    assert r["last_m15_utc"]=="2026-11-13T21:45:00+00:00"


def test_empty_archive_does_not_forge_candles_or_signals():
    r=cloud_terminal_summary(1,{"meta":{}},pd.DataFrame(),
                             now="2026-11-15T16:00:00Z")
    assert r["bars"]==0
    assert r["last_scan_utc"] is None
    assert r["last_m15_utc"] is None
    assert r["cloud_online_confirmed"] is False
    assert r["trade_permission"]=="WAIT"


def test_corrupted_candles_are_refused():
    f=frame()
    f.loc[f.index[-1],"High"]=4999.
    with pytest.raises(ValueError,match="OHLC"):
        cloud_terminal_summary(3,{"meta":{}},f)
    with pytest.raises(ValueError,match="instrument"):
        cloud_terminal_summary(3,{"meta":{"epic":"BTCUSD"}},frame())
    dup=pd.concat([frame(),frame().iloc[-1:]])
    with pytest.raises(ValueError,match="UTC"):
        cloud_terminal_summary(3,{"meta":{}},dup)


def test_unverified_future_checkpoint_not_marked_online():
    r=cloud_terminal_summary(2,{"meta":{
        "last_scan_utc":"2026-11-15T19:00:00Z"}},
        frame(),now="2026-11-15T15:00:00Z")
    assert r["age_minutes"]<0
    assert r["cloud_online_confirmed"] is False
