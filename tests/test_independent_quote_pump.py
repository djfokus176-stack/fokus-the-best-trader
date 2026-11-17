"""Regression: moving quotes remain independent of slow PAPER scans.

Use fake networks only. Never start a second Capital session or trade.
"""
from datetime import datetime, timezone
from pathlib import Path
import time

import pandas as pd
import pytest
import requests

from trader.cloud_quote_pump import (
    BorrowedDemoQuoteClient, CloudQuotePump,
)
from trader.cloud_scalp_quotes import Quote5sSampler
from trader.cloud_moving_m15 import assess_moving_m15
from trader.market import MarketQuote, FeedError


class Scanner:
    environment="DEMO"
    base_url="https://demo-api-capital.backend-capital.com"
    api_key="x-test"
    cst=None
    token=None
    session_started=0.0
    def __init__(self):
        self.session=requests.Session()
        self.login_count=0
    def authenticate_for_test(self):
        self.cst="CST_T"
        self.token="XSEC_T"
        self.session_started=time.time()


class Remote:
    def __init__(self):
        self.rows=[]
        self.http=requests.Session()
    def upsert_live_quote(self,row):
        self.rows.append(row)


def test_borrowed_client_never_creates_a_second_capital_login(monkeypatch):
    scan=Scanner()
    borrowed=BorrowedDemoQuoteClient(scan)
    assert borrowed.session is not scan.session
    with pytest.raises(FeedError,match="PAPER_BROKER_SESSION_NOT_READY"):
        borrowed.headers()
    scan.authenticate_for_test()
    assert borrowed.headers()=={
        "X-CAP-API-KEY":"x-test","CST":"CST_T",
        "X-SECURITY-TOKEN":"XSEC_T"}
    posts=[]
    def reject_second_login(*a,**kw):
        posts.append((a,kw))
        raise AssertionError("Second POST /session forbidden")
    monkeypatch.setattr(borrowed.session,"post",reject_second_login)
    class Response:
        def raise_for_status(self):pass
        def json(self):
            now=datetime.now(timezone.utc)
            return {"markets":[{
                "epic":"US500","marketStatus":"TRADEABLE",
                "bid":7500.,"offer":7500.8,
                "updateTimeUTC":now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
                "delayTime":0}]}
    calls=[]
    def get(url,**kwargs):
        calls.append((url,kwargs))
        return Response()
    monkeypatch.setattr(borrowed.session,"get",get)
    quote=borrowed.market_quote("US500")
    assert quote.fresh and quote.mid==7500.4
    assert len(calls)==1 and calls[0][0].endswith("/api/v1/markets")
    assert posts==[]
    borrowed.close()
    scan.session.close()


class FakeSampler:
    next_due=0.0
    def __init__(self):
        self.calls=0
    def pulse(self,client,remote,epic,*,monotonic):
        assert client.environment=="DEMO" and epic=="US500"
        self.calls+=1
        self.next_due=monotonic+.2
        return "LIVE_QUOTE_SAVED"


def test_pump_runs_without_needing_scan_idle_time():
    scan=Scanner()
    sampler=FakeSampler()
    db=Remote()
    pump=CloudQuotePump(scan,db,sampler=sampler)
    assert pump.tick()=="WAIT_BROKER_SESSION"
    assert sampler.calls==0
    scan.authenticate_for_test()
    pump.start()
    try:
        # Simulate a 2.2-second CPU/network-bound PAPER scan in the OTHER
        # (main) thread. No call to idle_quote_pulses in this interval.
        time.sleep(2.2)
        assert sampler.calls>=2
        report=pump.snapshot()
        assert report["attempts"]>=2
        assert report["status"]=="LIVE_QUOTE_SAVED"
        assert report["last_fresh_utc"] is not None
        assert report["last_attempt_utc"] is not None
        assert report["trade_permission"]=="WAIT"
    finally:
        pump.stop()
        scan.session.close()


def test_clock_and_token_failure_never_authenticates_in_pump():
    scan=Scanner()
    scan.authenticate_for_test()
    scan.session_started=time.time()-610
    with pytest.raises(FeedError,match="PAPER_BROKER_SESSION_NOT_READY"):
        BorrowedDemoQuoteClient(scan).headers()


def test_main_worker_uses_background_sampler_no_concurrent_idle_poll():
    code=Path("trader/worker.py").read_text(encoding="utf-8")
    assert 'quote_pump=build_quote_pump' in code
    assert 'if quote_pump is not None:' in code
    assert 'quote_health=quote_pump.snapshot if quote_pump else None' in code
    assert 'quote_pump.snapshot()' in code
    assert '"quote_pump":(' in code
    assert '"last_fresh_utc"' in code
    assert 'time.sleep(idle_seconds)' in code
    assert '"FOKUS_PAPER_STRATEGY"' in code
    assert "self.session.post(" not in Path("trader/cloud_quote_pump.py").read_text()
    assert "self.session.put(" not in Path("trader/cloud_quote_pump.py").read_text()


def _current_m15():
    now=pd.Timestamp.now(tz="UTC")
    opened=now.floor("15min")
    return {"epic":"US500","environment":"DEMO",
            "timeframe":"MINUTE_15",
            "source":"Capital.com /prices • bieżąca OHLC",
            "time":opened+pd.Timedelta(minutes=15),
            "last_tick":opened,
            "Open":7500.,"High":7504.,"Low":7499.,"Close":7502.,
            "bid":7501.7,"ask":7502.3,"spread":.6}


class QuoteFailButPricesWork:
    environment="DEMO"
    def __init__(self):
        self.calls=[]
    def market_quote(self,epic):
        self.calls.append("markets")
        raise FeedError("Capital /markets returned 500")
    def market_state(self,epic):
        self.calls.append("status")
        return "TRADEABLE"
    def forming_candle(self,epic,tf):
        self.calls.append(tf)
        return _current_m15()


def test_documented_prices_fallback_is_visual_only_and_delay_unknown(monkeypatch):
    monkeypatch.setenv("FOKUS_CLOUD_PRICES_ONLY_FALLBACK_ENABLED","true")
    sampler=Quote5sSampler()
    c=QuoteFailButPricesWork();db=Remote()
    assert sampler.pulse(c,db,monotonic=10.)=="BROKER_M15_ONLY_UNVERIFIED_QUOTE"
    assert c.calls==["markets","status","MINUTE","MINUTE_15"]
    assert len(db.rows)==1
    row=db.rows[-1]
    assert row["fresh"] is False
    assert row["delay_seconds"]==9999.
    assert row["broker_update_utc"] is None
    assert row["samples"][-1]["fallback_only"] is True
    assert row["samples"][-1]["source_delay_unknown"] is True
    result=assess_moving_m15(row,now=pd.Timestamp.now(tz="UTC"))
    assert result["visible"] is True
    assert result["quote_verified"] is False
    assert result["kind"]=="BROKER_INCOMPLETE_M15"
    assert result["trade_permission"]=="WAIT"
    assert sampler.next_due==20


def test_prices_only_fallback_does_not_allow_closed_unknown_markets(monkeypatch):
    c=QuoteFailButPricesWork()
    c.market_state=lambda epic:"CLOSED"
    db=Remote()
    sampler=Quote5sSampler()
    assert sampler.pulse(c,db,monotonic=0)=="QUOTE_WAIT_FeedError"
    assert db.rows==[]
    assert sampler.next_due==30.
    monkeypatch.setenv("FOKUS_CLOUD_PRICES_ONLY_FALLBACK_ENABLED","false")
    c.market_state=lambda epic: "TRADEABLE"
    assert sampler.pulse(c,db,monotonic=30.)=="QUOTE_WAIT_FeedError"
    assert db.rows==[]


def test_prices_only_fallback_never_passes_to_paper_state():
    pump_code=Path("trader/cloud_quote_pump.py").read_text(encoding="utf-8")
    sampler_code=Path("trader/cloud_scalp_quotes.py").read_text(encoding="utf-8")
    for forbidden in ("queue_paper(", "progress_paper(", "broker_order("):
        assert forbidden not in pump_code
        assert forbidden not in sampler_code
