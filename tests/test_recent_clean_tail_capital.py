"""Safe recent tail after old Capital /prices anomalies (PAPER only).

All data is synthetic; neither MID synthesis nor real trading enabled.
"""
from datetime import timedelta
import sqlite3
import pandas as pd
from trader.market import parse_prices,capital_prices_as_close_times,evaluate_snapshot
from trader import worker


NOW=pd.Timestamp("2026-11-09T16:12:34Z")


def make_payload(n=300, corrupted=(), absent=()):
    # API timestamps are OPEN; engine shifts to CLOSE; final bar is forming.
    timestamps=pd.date_range(end=NOW.floor("min"),periods=n,freq="min")
    values=[]
    for i,t in enumerate(timestamps):
        if i in absent:continue
        bad=i in corrupted
        values.append({"snapshotTimeUTC":t.isoformat(),
           "openPrice":{"bid":100.0,"ask":99.0 if bad else 100.6},
           "highPrice":{"bid":101.0,"ask":101.6},
           "lowPrice":{"bid":99.0,"ask":99.6},
           "closePrice":{"bid":100.0,"ask":100.6}})
    return {"prices":values}


def snap(payload):
    raw=capital_prices_as_close_times(
        parse_prices(payload,quarantine_bad=True),"MINUTE")
    return evaluate_snapshot(raw,"US500","MINUTE",now=NOW.to_pydatetime())


def test_corrupt_old_history_does_not_block_last_200_clean_bars():
    s=snap(make_payload(corrupted=(0,2,6,8,9,10,20,35,55,72,90)))
    assert s.good and len(s.frame)>70
    assert "POMINIĘTO_STARE_BŁĘDY=11" in s.reason
    assert s.confirmed_utc==NOW.floor("min").to_pydatetime()
    assert s.frame.index.is_unique
    assert s.frame.index.is_monotonic_increasing


def test_corrupt_recent_bar_cannot_be_hidden_by_older_clean_bars():
    s=snap(make_payload(corrupted=(290,)))
    assert not s.good
    assert "Ostatnia poprawna seria:" in s.reason
    assert "DANE_WADLIWE" in s.reason


def test_corrupt_forming_bar_never_promoted_to_entry():
    s=snap(make_payload(corrupted=(299,)))
    assert not s.good
    assert "Wadliwa najnowsza świeca" in s.reason


def test_missing_timestamp_is_not_assumed_old_even_with_long_clean_tail():
    payload=make_payload()
    payload["prices"].insert(0,{"snapshotTimeUTC":"garbled",
        "openPrice":{"bid":99,"ask":100}})
    s=snap(payload)
    assert not s.good
    assert "Brak czasu wadliwej świecy" in s.reason


def test_recent_missing_minute_refuses_to_backfill_from_older_bars():
    s=snap(make_payload(corrupted=(10,),absent=(270,)))
    assert not s.good
    assert "DANE_WADLIWE" in s.reason
    assert "Ostatnia poprawna seria" in s.reason


def test_old_corruption_does_not_bypass_stale_data_gate():
    old=NOW-pd.Timedelta(minutes=30)
    payload=make_payload(corrupted=(0,))
    for record in payload["prices"]:
        t=pd.Timestamp(record["snapshotTimeUTC"])-pd.Timedelta(minutes=30)
        record["snapshotTimeUTC"]=t.isoformat()
    s=snap(payload)
    assert not s.good
    assert "przestarzałe" in s.reason


def test_old_corruption_does_not_bypass_excessive_spread():
    payload=make_payload(corrupted=(0,))
    for row in payload["prices"][-5:]:
        row["closePrice"]["ask"]=104.0
    s=snap(payload)
    assert not s.good
    assert "Spread" in s.reason or "spread" in s.reason


def test_weekend_broker_closed_is_not_reported_as_api_corruption(monkeypatch):
    class Client:
        environment="DEMO"
        def market_state(self,epic):return "CLOSED"
    monkeypatch.setattr(worker,"fetch_all_timeframes",lambda *a,**k:({},{
        "MINUTE":"older data with crossed BID/ASK"}))
    db=sqlite3.connect(":memory:")
    outcome=worker.scan_once(Client(),"US500","MINUTE",
        worker.AUTO_MODE,2.0,db,strict_macro=False)
    assert "MARKET_CLOSED" in outcome
    assert "BROKER_STATUS=CLOSED" in outcome
    assert "DATA_STALE" not in outcome
    assert "QUEUE=YES" not in outcome


def test_unknown_market_status_cannot_be_called_weekend_or_tradeable(monkeypatch):
    class Client:
        environment="DEMO"
        def market_state(self,epic):return "UNKNOWN"
    monkeypatch.setattr(worker,"fetch_all_timeframes",lambda *a,**k:({},{}))
    db=sqlite3.connect(":memory:")
    outcome=worker.scan_once(Client(),"US500","MINUTE",
        worker.AUTO_MODE,2.0,db,strict_macro=False)
    assert "NO_FEED" in outcome
    assert "BROKER_STATUS=UNKNOWN" in outcome
    assert "MARKET_CLOSED" not in outcome
