"""Integration: Capital DEMO /prices -> quote sampler -> Supabase JSON -> CLOUD.

Every new bar is provider OHLC, not a reconstructed M1 or 24 MID quotes.
The entire path is display-only and never touches PAPER.
"""
from datetime import datetime, timezone
from pathlib import Path
import time

import pandas as pd
import pytest

from trader.market import CapitalReadOnly, MarketQuote, FeedError
from trader.cloud_quote_pump import BorrowedDemoQuoteClient
from trader.cloud_broker_timeframes import (
    CONFIG, serialize_broker_forming, assess_broker_forming,
)
from trader.cloud_chart_timeframes import sampled_chart_bar
from trader.cloud_scalp_quotes import Quote5sSampler


def _raw(choice, now, close=7550., high=7552.):
    resolution, seconds, _, _ = CONFIG[choice]
    opened = pd.Timestamp(now).floor(f"{seconds}s")
    return {
        "epic":"US500","environment":"DEMO",
        "timeframe":resolution,
        "source":"Capital.com /prices • bieżąca OHLC",
        "last_tick":opened,"time":opened+pd.Timedelta(seconds=seconds),
        "Open":7548.,"High":high,"Low":7546.,"Close":close,
        "bid":close-.3,"ask":close+.3,"spread":.6,
    }


@pytest.mark.parametrize("choice", ["M5","H1"])
def test_real_provider_ohlc_is_current_and_excludes_old_bar(choice):
    now = pd.Timestamp("2026-11-17T13:04:10Z")
    m = serialize_broker_forming(_raw(choice,now), choice, now=now)
    assert m["high"]==7552.
    assert m["kind"]==CONFIG[choice][3]
    assert m["bar_open_utc"] == now.floor(
        f"{CONFIG[choice][1]}s").isoformat()
    with pytest.raises(ValueError):
        serialize_broker_forming(_raw(choice,now),choice,
                                 now=now+pd.Timedelta(hours=2))
    bad = _raw(choice,now)
    bad["epic"]="GER40"
    with pytest.raises(ValueError):
        serialize_broker_forming(bad,choice,now=now)
    bad = _raw(choice,now)
    bad["High"]=7540.
    with pytest.raises(ValueError):
        serialize_broker_forming(bad,choice,now=now)


def _cached(m5=None,h1=None,*,fresh=True,at=None):
    at=at or pd.Timestamp("2026-11-17T13:04:10Z")
    sample={"utc":at.isoformat(),"bid":7549.7,"ask":7550.3}
    if m5 is not None:sample["forming_m5"]=m5
    if h1 is not None:sample["forming_h1"]=h1
    if not fresh:
        sample["fallback_only"]=True
        sample["source_delay_unknown"]=True
    return {
        "epic":"US500","source":"Capital.com DEMO REST",
        "bid":7549.7,"ask":7550.3,"mid":7550.,"spread":.6,
        "broker_status":"TRADEABLE",
        "fresh":fresh,"delay_seconds":0. if fresh else 9999.,
        "received_utc":at.isoformat(),
        "broker_update_utc":at.isoformat() if fresh else None,
        "samples":[sample],
    }


@pytest.mark.parametrize("choice",["M5","H1"])
def test_browser_prefers_actual_provider_wicks_over_inaccurate_mid_window(choice):
    now=pd.Timestamp("2026-11-17T13:04:10Z")
    key=CONFIG[choice][2]
    data=serialize_broker_forming(_raw(choice,now,high=7567.),choice,now=now)
    record=_cached(**{key:data})
    result=sampled_chart_bar(record,choice,now=now)
    assert result["visible"] is True
    assert result["bar"]["high"]==7567.
    assert result["bar"]["low"]==7546.
    assert result["bar"]["close"]==7550.
    assert result["missing_extremes_possible"] is False
    assert result["trade_permission"]=="WAIT"
    altered=serialize_broker_forming(
        _raw(choice,now,close=7556.,high=7572.),
        choice,now=now+pd.Timedelta(seconds=7))
    later=now+pd.Timedelta(seconds=7)
    record=_cached(at=later,**{key:altered})
    moved=sampled_chart_bar(record,choice,now=later)
    assert moved["bar"]["high"]==7572.
    assert moved["bar"]["close"]==7556.
    assert moved["bar"]["high"]!=result["bar"]["high"]


@pytest.mark.parametrize("choice",["M5","H1"])
def test_stale_unmarked_or_closed_provider_ohlc_cannot_animate(choice):
    now=pd.Timestamp("2026-11-17T13:04:10Z")
    key=CONFIG[choice][2]
    provider=serialize_broker_forming(_raw(choice,now),choice,now=now)
    record=_cached(fresh=False,**{key:provider})
    assert sampled_chart_bar(record,choice,now=now)["visible"]
    assert sampled_chart_bar(record,choice,now=now)["quote_verified"] is False
    record["samples"][-1].pop("fallback_only")
    assert not assess_broker_forming(record,choice,now=now)["visible"]
    record["samples"][-1]["fallback_only"]=True
    record["broker_status"]="CLOSED"
    assert not assess_broker_forming(record,choice,now=now)["visible"]
    record["broker_status"]="TRADEABLE"
    assert not assess_broker_forming(
        record,choice,now=now+pd.Timedelta(seconds=50))["visible"]


class _MemoryRemote:
    def __init__(self):self.records=[]
    def upsert_live_quote(self,record):self.records.append(record)


class _Broker:
    environment="DEMO"
    def __init__(self):
        self.calls=[]
    def market_quote(self,epic):
        now=datetime.now(timezone.utc)
        return MarketQuote(
            epic="US500",environment="DEMO",bid=7549.7,
            ask=7550.3,mid=7550.,spread=.6,
            status="TRADEABLE",update_utc=now,received_utc=now,
            delay_seconds=0.,fresh=True)
    def forming_candle(self,epic,resolution):
        self.calls.append(resolution)
        match=next((choice for choice,fields in CONFIG.items()
                    if fields[0]==resolution),None)
        if match is None:
            raise FeedError("Not offered in fake broker")
        return _raw(match,pd.Timestamp.now(tz="UTC"))


def test_real_provisional_m5_and_h1_pass_through_single_quote_cache(monkeypatch):
    monkeypatch.setenv("FOKUS_CLOUD_MTF_FORMING_ENABLED","true")
    client=_Broker()
    remote=_MemoryRemote()
    sampler=Quote5sSampler()
    assert sampler.pulse(client,remote,monotonic=100.)=="LIVE_QUOTE_SAVED"
    assert "MINUTE_5" in client.calls and "HOUR" in client.calls
    assert "MINUTE_15" in client.calls and "MINUTE" in client.calls
    record=remote.records[-1]
    for choice in ("M5","H1"):
        key=CONFIG[choice][2]
        assert record["samples"][-1][key]["kind"]==CONFIG[choice][3]
        bar=sampled_chart_bar(record,choice,now=pd.Timestamp.now(tz="UTC"))
        assert bar["visible"]
        assert bar["missing_extremes_possible"] is False
        assert bar["trade_permission"]=="WAIT"
    # Fast 5s poll never repeats expensive M5/H1 /prices.
    assert sampler.pulse(client,remote,monotonic=105.)=="LIVE_QUOTE_SAVED"
    assert client.calls.count("MINUTE_5")==1
    assert client.calls.count("HOUR")==1
    assert sampler.extra_forming_next_due["M5"]==130.
    assert sampler.extra_forming_next_due["H1"]==145.


def test_quote_pump_may_reuse_tokens_long_after_login_if_session_active():
    scanner=CapitalReadOnly("test-key","test-user","test-password",environment="DEMO")
    scanner.cst="CST"
    scanner.token="SEC"
    scanner.session_started=time.time()-3600
    pump=BorrowedDemoQuoteClient(scanner)
    # Capital REST tokens expire after ten minutes of INACTIVITY, not
    # ten minutes from login. The active quote pump keeps session in use.
    assert pump.headers()["CST"]=="CST"
    assert pump.headers()["X-SECURITY-TOKEN"]=="SEC"
    pump.close()
    scanner.session.close()


def test_scanner_renews_token_atomically_and_pump_uses_new_credentials(monkeypatch):
    scanner=CapitalReadOnly("test-key","test-user","test-password",environment="DEMO")
    scanner.cst="OLD"
    scanner.token="OLD_SEC"
    scanner.session_started=time.time()-600
    class Response:
        headers={"CST":"NEW","X-SECURITY-TOKEN":"NEW_SEC"}
        def raise_for_status(self):pass
    posts=[]
    def post(url,**kw):
        posts.append(url)
        return Response()
    monkeypatch.setattr(scanner.session,"post",post)
    fresh=scanner.headers()
    pump=BorrowedDemoQuoteClient(scanner)
    assert len(posts)==1
    assert fresh["CST"]==pump.headers()["CST"]=="NEW"
    assert fresh["X-SECURITY-TOKEN"]==pump.headers()["X-SECURITY-TOKEN"]=="NEW_SEC"
    assert pump.session is not scanner.session
    pump.close()
    scanner.session.close()


def test_ui_never_authenticates_to_capital_or_uses_partial_ohlc_for_trades():
    cloud=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf-8")
    scan=Path("trader/cloud_scalp_quotes.py").read_text(encoding="utf-8")
    module=Path("trader/cloud_broker_timeframes.py").read_text(encoding="utf-8")
    assert "sampled_chart_bar(" in cloud
    assert "fetch_live_quote" in cloud
    assert "queue_paper(" not in cloud+scan+module
    assert "progress_paper(" not in cloud+scan+module
    assert "POST /positions" not in module
