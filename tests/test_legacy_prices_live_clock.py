"""Legacy SP500 v7.1 used /prices latest OPEN candle directly.

Our CLOUD keeps the same browser READ-ONLY UX without another Capital
login, without broker orders, and without trusting unverified /markets.
"""
from datetime import datetime, timezone
from pathlib import Path
import ast

import pandas as pd
import pytest

from trader.market import MarketQuote, FeedError
from trader.cloud_scalp_quotes import Quote5sSampler
from trader.cloud_forming_m1 import assess_cloud_forming_m1
from trader.cloud_chart_timeframes import sampled_chart_bar
from trader.cloud_candle_clock import SECONDS


@pytest.fixture(autouse=True)
def legacy_m1_tests_disable_unrelated_m5_h1_polling(monkeypatch):
    monkeypatch.setenv("FOKUS_CLOUD_MTF_FORMING_ENABLED","false")


def _snapshot(tf):
    now=pd.Timestamp.now(tz="UTC")
    seconds={"MINUTE":60,"MINUTE_15":900}[tf]
    opened=now.floor(f"{seconds}s")
    return {"epic":"US500","environment":"DEMO","timeframe":tf,
            "source":"Capital.com /prices • bieżąca OHLC",
            "last_tick":opened,"time":opened+pd.Timedelta(seconds=seconds),
            "Open":7397.4,"High":7398.3,"Low":7395.6,
            "Close":7396.1,"bid":7395.8,"ask":7396.4,
            "spread":.6}


class _ReadOnlyDemo:
    environment="DEMO"
    def __init__(self,*,raise_market=False,closed=False):
        self.calls=[]
        self.raise_market=raise_market
        self.closed=closed
    def market_quote(self,epic):
        self.calls.append("GET /markets")
        if self.raise_market:
            raise FeedError("Cannot read GET /markets")
        now=datetime.now(timezone.utc)
        return MarketQuote(
            epic="US500",environment="DEMO",bid=7395.8,
            ask=7396.4,mid=7396.1,spread=.6,
            status="CLOSED" if self.closed else "TRADEABLE",
            update_utc=None,received_utc=now,
            delay_seconds=0.,fresh=False)
    def market_state(self,epic):
        self.calls.append("GET /markets/US500")
        return "CLOSED" if self.closed else "TRADEABLE"
    def forming_candle(self,epic,resolution):
        self.calls.append("GET /prices/"+resolution)
        return _snapshot(resolution)


class _Store:
    def __init__(self):
        self.rows=[]
    def upsert_live_quote(self,record):
        self.rows.append(record)


def test_stale_markets_quote_does_not_freeze_current_real_prices_m1(monkeypatch):
    monkeypatch.setenv("FOKUS_CLOUD_FORMING_M1_ENABLED","true")
    client=_ReadOnlyDemo()
    remote=_Store()
    sampler=Quote5sSampler()
    state=sampler.pulse(client,remote,monotonic=100.)
    assert state=="BROKER_M1_ONLY_UNVERIFIED_QUOTE"
    assert client.calls==[
        "GET /markets","GET /prices/MINUTE_15","GET /prices/MINUTE"]
    row=remote.rows[-1]
    assert row["fresh"] is False
    assert row["broker_update_utc"] is None
    assert row["delay_seconds"]==9999.
    assert row["samples"][-1]["source_delay_unknown"] is True
    assert row["samples"][-1]["forming_m1"]["high"]==7398.3
    current=pd.Timestamp.now(tz="UTC")
    m=assess_cloud_forming_m1(row,now=current)
    assert m["visible"] is True
    assert m["quote_verified"] is False
    preview=sampled_chart_bar(row,"M1",now=current)
    assert preview["visible"] is True
    assert preview["bar"]["high"]==7398.3
    assert preview["bar"]["low"]==7395.6
    assert preview["bar"]["close"]==7396.1
    assert preview["trade_permission"]=="WAIT"
    assert preview["missing_extremes_possible"] is False


def test_current_m1_only_can_be_shown_as_partial_m2_m5_h1(monkeypatch):
    monkeypatch.setenv("FOKUS_CLOUD_FORMING_M1_ENABLED","true")
    store=_Store()
    Quote5sSampler().pulse(_ReadOnlyDemo(),store,monotonic=100.)
    now=pd.Timestamp.now(tz="UTC")
    for tf in ("M2","M5","H1"):
        result=sampled_chart_bar(store.rows[-1],tf,now=now)
        assert result["visible"]
        assert result["broker_m1_only"] is True
        assert result["missing_extremes_possible"] is True
        assert result["trade_permission"]=="WAIT"


def test_unavailable_markets_still_uses_current_prices_without_second_login(monkeypatch):
    monkeypatch.setenv("FOKUS_CLOUD_PRICES_ONLY_FALLBACK_ENABLED","true")
    client=_ReadOnlyDemo(raise_market=True)
    remote=_Store()
    status=Quote5sSampler().pulse(client,remote,monotonic=100.)
    assert status=="BROKER_M1_ONLY_UNVERIFIED_QUOTE"
    assert client.calls==[
        "GET /markets","GET /markets/US500",
        "GET /prices/MINUTE","GET /prices/MINUTE_15"]
    row=remote.rows[-1]
    assert row["fresh"] is False
    assert row["samples"][-1]["fallback_only"] is True
    assert assess_cloud_forming_m1(row,now=pd.Timestamp.now(tz="UTC"))["visible"]
    assert "POST" not in str(client.calls)
    assert status!="LIVE_QUOTE_SAVED"


def test_market_closed_never_fakes_prices_or_ticks():
    client=_ReadOnlyDemo(closed=True)
    remote=_Store()
    status=Quote5sSampler().pulse(client,remote,monotonic=100.)
    assert status=="BROKER_NOT_FRESH"
    assert all(not x.startswith("GET /prices") for x in client.calls)
    assert not assess_cloud_forming_m1(
        remote.rows[-1],now=pd.Timestamp.now(tz="UTC"))["visible"]


def test_clock_runs_in_browser_without_restarting_streamlit_or_api():
    source=Path("trader/cloud_candle_clock.py").read_text()
    assert set(SECONDS)=={"M1","M2","M5","M15","H1"}
    assert 'setInterval(update,500)' in source
    assert "Europe/Warsaw" in source
    assert "Date.now()" in source
    assert "st.rerun(" not in source
    assert "requests." not in source
    assert "trade" not in source.lower().split("def render_candle_clock")[1]


def test_runtime_regression_does_not_reference_removed_moving_m15_variable():
    src=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf-8")
    tree=ast.parse(src)
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
            and n.name=="render_cloud_terminal")
    used={n.id for n in ast.walk(fn) if isinstance(n,ast.Name)
          and isinstance(n.ctx,ast.Load)}
    assert "moving_m15" not in used  # PREVIOUS PR88 NameError
    assert "moving_chart" in used
    assert "render_candle_clock(choice)" in src
    assert "LEGACY-PRICES-v1" in src
    assert "queue_paper(" not in src
