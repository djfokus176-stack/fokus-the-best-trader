"""No second Capital session, no new Supabase schema, no counterfeit bars."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from trader.market import MarketQuote, FeedError
from trader.cloud_forming_m1 import (
    SOURCE,TYPE, serialize_forming_m1,assess_cloud_forming_m1,
)
from trader.cloud_scalp_quotes import Quote5sSampler
from trader.cloud_scalp_5s_ui import assess_quote_snapshot

NOW=pd.Timestamp("2026-11-16T08:25:20Z")
ORIGIN="Capital.com DEMO REST"


def broker_m1(now=NOW):
    open_time=now.floor("min")
    return {"epic":"US500","environment":"DEMO","timeframe":"MINUTE",
            "source":SOURCE,"time":open_time+pd.Timedelta(minutes=1),
            "last_tick":open_time,
            "Open":7530.0,"High":7534.4,"Low":7528.3,"Close":7532.7,
            "bid":7532.4,"ask":7533.0,"spread":0.6}


def cloud_quote(now=NOW,*,fresh=True,status="TRADEABLE"):
    return {"epic":"US500","source":ORIGIN,
            "bid":7532.4,"ask":7533.0,"mid":7532.7,
            "spread":0.6,"broker_status":status,
            "fresh":fresh,"delay_seconds":0.0,
            "received_utc":now.isoformat(),
            "broker_update_utc":now.isoformat(),
            "samples":[{"utc":now.isoformat(),"bid":7532.4,"ask":7533.0}]}


def test_broker_m1_schema_remains_entirely_separate_from_confirmed_candles():
    m=serialize_forming_m1(broker_m1(),collected_utc=NOW)
    assert m["kind"]==TYPE
    assert m["source"]==SOURCE
    assert m["collected_utc"]==NOW.isoformat()
    assert m["open_utc"]<m["close_utc"]
    assert m["close"]==7532.7
    assert m["environment"]=="DEMO"
    assert "paper" not in str(m).lower()
    assert "schema" not in m


def test_cloud_only_shows_preview_when_market_and_source_are_fresh():
    data=cloud_quote()
    data["samples"][-1]["forming_m1"]=serialize_forming_m1(
        broker_m1(),collected_utc=NOW)
    info=assess_cloud_forming_m1(data,now=NOW+pd.Timedelta(seconds=2))
    assert info["visible"] is True
    assert info["preview"]["age_seconds"]==2.
    assert info["preview"]["high"]>info["preview"]["low"]
    assert info["not_closed_candle"] is True
    assert info["trade_permission"]=="WAIT"
    assert assess_quote_snapshot(data,now=NOW)["fresh"] is True


@pytest.mark.parametrize("when,broker_status,fresh",[
    (NOW+pd.Timedelta(seconds=33),"TRADEABLE",True),
    (NOW,"CLOSED",False),
    (NOW,"TRADEABLE",False),
    (NOW+pd.Timedelta(minutes=1),"TRADEABLE",True),
])
def test_stale_or_closed_never_draws_active_incomplete_m1(when,broker_status,fresh):
    data=cloud_quote(status=broker_status,fresh=fresh)
    data["samples"][-1]["forming_m1"]=serialize_forming_m1(
        broker_m1(),collected_utc=NOW)
    info=assess_cloud_forming_m1(data,now=when)
    assert info["visible"] is False
    assert info["preview"] is None


@pytest.mark.parametrize("change",[
    {"epic":"GER40"},
    {"environment":"LIVE"},
    {"timeframe":"MINUTE_15"},
    {"source":"fake candle"},
    {"High":7529},
    {"Low":7540},
    {"spread":-1},
    {"bid":7540},
])
def test_untrusted_forming_candle_is_rejected(change):
    raw={**broker_m1(),**change}
    with pytest.raises(ValueError):
        serialize_forming_m1(raw,collected_utc=NOW)


def test_absent_preview_is_not_a_bad_m15_or_new_paper():
    data=cloud_quote()
    result=assess_cloud_forming_m1(data,now=NOW)
    assert result["visible"] is False
    assert result["trade_permission"]=="WAIT"
    data["samples"][-1]["forming_m1"]={"kind":"fake"}
    assert not assess_cloud_forming_m1(data,now=NOW)["visible"]



def test_minute_rollover_never_labels_prior_bar_as_forming():
    end=NOW.floor("min")+pd.Timedelta(minutes=1)
    captured=end-pd.Timedelta(seconds=2)
    data=cloud_quote(now=end+pd.Timedelta(seconds=1))
    data["samples"][-1]["forming_m1"]=serialize_forming_m1(
        broker_m1(now=NOW),collected_utc=captured)
    status=assess_cloud_forming_m1(data,now=end+pd.Timedelta(seconds=1))
    assert status["visible"] is False
    assert status["trade_permission"]=="WAIT"
    with pytest.raises(ValueError,match="wrong market minute"):
        serialize_forming_m1(
            broker_m1(now=NOW),collected_utc=end+pd.Timedelta(seconds=2))


class _MockBroker:
    environment="DEMO"

    def __init__(self,*,fail=False):
        self.fail=fail
        self.forming_calls=0
        self.quote_calls=0
    def market_quote(self,epic):
        self.quote_calls+=1
        now=datetime.now(timezone.utc)
        return MarketQuote(
            epic=epic,environment="DEMO",bid=7532.4,ask=7533.,
            mid=7532.7,spread=.6,status="TRADEABLE",
            update_utc=now,received_utc=now,delay_seconds=0.,fresh=True)
    def forming_candle(self,epic,tf):
        assert epic=="US500" and tf=="MINUTE"
        self.forming_calls+=1
        if self.fail:raise FeedError("Do not expose broker details")
        return broker_m1(pd.Timestamp.now(tz="UTC"))


class _Cache:
    def __init__(self):
        self.records=[]
    def upsert_live_quote(self,row):
        self.records.append(row)


def test_existing_worker_writes_safely_in_same_loop_without_new_table(monkeypatch):
    monkeypatch.setenv("FOKUS_CLOUD_FORMING_M1_ENABLED","true")
    worker=Quote5sSampler()
    client=_MockBroker()
    remote=_Cache()
    assert worker.pulse(client,remote,monotonic=100.)=="LIVE_QUOTE_SAVED"
    first=remote.records[-1]
    assert set(first)=={"epic","source","bid","ask","mid","spread",
                         "broker_status","broker_update_utc","received_utc",
                         "delay_seconds","fresh","samples"}
    assert first["samples"][-1]["forming_m1"]["kind"]==TYPE
    assert len(first["samples"])==1
    assert client.forming_calls==1
    assert worker.pulse(client,remote,monotonic=105.)=="LIVE_QUOTE_SAVED"
    assert client.forming_calls==1  # /prices no faster than every 15s
    assert client.quote_calls==2
    assert len(remote.records)==2
    assert len(remote.records[-1]["samples"])==2


def test_forming_endpoint_error_never_breaks_quote_cache_or_paper(monkeypatch):
    monkeypatch.setenv("FOKUS_CLOUD_FORMING_M1_ENABLED","true")
    worker=Quote5sSampler()
    client=_MockBroker(fail=True)
    remote=_Cache()
    assert worker.pulse(client,remote,monotonic=100.)=="LIVE_QUOTE_SAVED"
    assert "forming_m1" not in remote.records[-1]["samples"][-1]
    assert worker.forming_m1_status=="M1_WAIT_FeedError"
    assert client.forming_calls==1
    assert worker.pulse(client,remote,monotonic=105.)=="LIVE_QUOTE_SAVED"
    assert client.forming_calls==1
    assert worker.forming_m1_next_due==160.
    assert "Do not expose" not in worker.forming_m1_status


def test_forming_preview_is_optional_and_disabled_without_streamlit_secrets(monkeypatch):
    monkeypatch.setenv("FOKUS_CLOUD_FORMING_M1_ENABLED","false")
    client=_MockBroker()
    remote=_Cache()
    worker=Quote5sSampler()
    assert worker.pulse(client,remote,monotonic=100.)=="LIVE_QUOTE_SAVED"
    assert client.forming_calls==0
    assert all("forming_m1" not in s for s in remote.records[-1]["samples"])


def test_ui_writes_no_capital_login_or_paper_order():
    worker=Path("trader/cloud_scalp_quotes.py").read_text(encoding="utf-8")
    ui=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf-8")
    assert "assess_cloud_forming_m1(quote_record" in ui
    assert "forming[\"visible\"]" in ui
    assert "client.forming_candle" not in ui
    assert "capital" not in ui.lower().split("remote.fetch_live_quote")[1][:130].split("except")[0]
    assert "queue_paper(" not in worker
    assert "queue_paper(" not in ui
    assert "FOKUS_CLOUD_LIVE_CHART" not in ui
