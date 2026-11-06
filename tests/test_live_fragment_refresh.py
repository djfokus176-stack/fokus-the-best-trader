"""The live Streamlit chart must update independently from expensive full scans."""
from datetime import datetime, timezone, timedelta
import pandas as pd
import pytest
from trader.live_chart_fragment import (
    preview_is_usable,live_chart_refresh_state,
)

NOW=datetime(2026,11,6,0,10,10,tzinfo=timezone.utc)


class CandleClient:
    def __init__(self):
        self.calls=0
        self.raise_error=None
        self.price=7333.25

    def forming_candle(self,epic,timeframe,*,now):
        self.calls+=1
        if self.raise_error:
            raise self.raise_error
        return dict(epic=epic,environment="DEMO",timeframe=timeframe,
                    time=pd.Timestamp(now).floor("min")+pd.Timedelta(minutes=1),
                    last_tick=pd.Timestamp(now).floor("min"),
                    Open=7330.0,High=7336.,Low=7329.5,Close=self.price,
                    bid=self.price-.3,ask=self.price+.3,spread=.6,
                    source="Capital.com /prices • bieżąca OHLC",samples=0)


def test_five_second_updates_are_actual_requests_not_full_reruns():
    state={}
    c=CandleClient()
    a=live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=100,
        utc=NOW)
    assert a and c.calls==1
    a=live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=102,
        utc=NOW+timedelta(seconds=2))
    assert not a and c.calls==1
    c.price=7336.0
    a=live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=105,
        utc=NOW+timedelta(seconds=5))
    assert a and c.calls==2
    assert state["_live_chart_preview"]["Close"]==7336.0
    assert state["_live_chart_attempts"]==2
    assert preview_is_usable(state["_live_chart_preview"],
        instrument="US500",timeframe="MINUTE",environment="DEMO",
        last_closed=NOW-timedelta(minutes=1),fetched_at=105,
        monotonic_now=105,max_age=12)


def test_same_price_is_visible_but_marked_unchanged():
    state={};c=CandleClient()
    live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=100,utc=NOW)
    live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=105,
        utc=NOW+timedelta(seconds=5))
    assert state["_live_chart_unchanged"]==1


def test_failed_read_invalidates_live_candle_and_explains_error():
    from trader.market import FeedError
    state={};c=CandleClient()
    live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=100,utc=NOW)
    c.raise_error=FeedError("DANE_WADLIWE: bid > ask")
    live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=105,utc=NOW)
    assert state["_live_chart_preview"] is None
    assert "bid > ask" in state["_live_chart_error"]
    assert not preview_is_usable(state["_live_chart_preview"],
        instrument="US500",timeframe="MINUTE",environment="DEMO",
        last_closed=NOW,fetched_at=105,monotonic_now=105,max_age=12)


def test_429_backoff_and_cross_market_reset():
    from trader.market import FeedError
    state={};c=CandleClient()
    c.raise_error=FeedError("HTTP 429 Too Many Requests")
    live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=100,utc=NOW)
    assert state["_live_chart_backoff"]==160
    assert not live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=110,utc=NOW)
    c.raise_error=None
    assert live_chart_refresh_state(state,client=c,instrument="NAS100",
        timeframe="MINUTE",environment="DEMO",period=5,tick=160,utc=NOW)
    assert state["_live_chart_scope"]==("NAS100","MINUTE","DEMO")
    assert state["_live_chart_attempts"]==1
    assert state["_live_chart_preview"]["epic"]=="NAS100"


def test_only_current_and_matching_candle_can_be_called_live():
    snap=dict(epic="US500",environment="DEMO",timeframe="MINUTE",
              time=pd.Timestamp("2026-11-06T00:11:00Z"),
              Open=10.,High=11.,Low=9.,Close=10.)
    for key,val in [("epic","NAS100"),("environment","LIVE"),
                    ("timeframe","HOUR")]:
        copy=dict(snap);copy[key]=val
        assert not preview_is_usable(copy,instrument="US500",timeframe="MINUTE",
             environment="DEMO",last_closed=NOW,fetched_at=100,
             monotonic_now=100,max_age=12)
    assert not preview_is_usable(snap,instrument="US500",timeframe="MINUTE",
        environment="DEMO",last_closed=NOW,fetched_at=100,
        monotonic_now=120,max_age=12)
    assert preview_is_usable(snap,instrument="US500",timeframe="MINUTE",
        environment="DEMO",last_closed=NOW,fetched_at=100,
        monotonic_now=105,max_age=12)


def test_live_fragment_is_distinct_from_full_app_refresh():
    from pathlib import Path
    src=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "render_independent_live_chart(fig,snap.frame" in src
    assert "chart_slot.plotly_chart" not in src
    hb=src.split("def auto_scan_heartbeat():",1)[1].split("auto_scan_heartbeat()",1)[0]
    assert "_scheduled_live_quote" not in hb
    assert "if tick-last_full >= max(60,interval)-1:" in hb
