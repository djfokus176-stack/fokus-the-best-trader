"""Capital.com WebSocket protocol and CLOUD UI integration, all offline fakes.

No broker account, network, second login, Supabase write or paper order is
made by these tests. Live deployment proof requires Northflank diagnostics.
"""
from datetime import datetime,timezone
from pathlib import Path
import json
import time

import pandas as pd
import pytest

from trader.cloud_ws_prices import (
    WS_URL,SOURCE,CACHE_SOURCE,TRANSPORT,
    StreamingPrices,CloudWSQuotePump,assess_streaming_candle,
)
from trader.cloud_chart_timeframes import sampled_chart_bar
from trader.cloud_scalp_5s_ui import assess_quote_snapshot
from trader.cloud_m15_live_overlay import cloud_quote_overlay

NOW=pd.Timestamp("2026-11-17T13:00:09Z")


def event(mid=7400.,at=NOW,epic="US500"):
    return {"status":"OK","destination":"quote","payload":{
        "epic":epic,"product":"CFD",
        "bid":mid-.3,"ofr":mid+.3,
        "timestamp":int(at.timestamp()*1000)}}


def ohlc(choice="M5",at=NOW,*,high=7420.,basis="bid"):
    code={"M1":"MINUTE","M5":"MINUTE_5",
          "M15":"MINUTE_15","H1":"HOUR"}[choice]
    secs={"M1":60,"M5":300,"M15":900,"H1":3600}[choice]
    return {"status":"OK","destination":"ohlc.event",
            "payload":{"epic":"US500","resolution":code,"type":"classic",
                       "priceType":basis,
                       "t":int(at.floor(f"{secs}s").timestamp()*1000),
                       "o":7398.,"h":high,"l":7390.,"c":7400.}}


def state_record(at=NOW):
    st=StreamingPrices()
    assert st.accept(event(7400.,at),now=at)=="quote"
    record=st.build_record(now=at)
    return st,record


def test_genuine_vendor_quote_creates_live_ws_row_in_old_unchanged_table():
    st,row=state_record()
    assert row["source"]==CACHE_SOURCE  # SQL CHECK requires canonical key
    assert row["samples"][-1]["transport"]==TRANSPORT
    assert row["broker_status"]=="STREAMING_ACTIVE"
    assert row["fresh"] is True
    assert row["broker_update_utc"]==NOW.isoformat()
    assert row["mid"]==7400.
    assert assess_quote_snapshot(row,now=NOW)["fresh"] is True
    assert cloud_quote_overlay(row,now=NOW)["visible"] is True
    assert len(row["samples"])==1
    assert st.updates==1


def test_ws_provisional_wicks_expand_only_on_real_received_quotes():
    st,row=state_record()
    st.accept(event(7409.,NOW+pd.Timedelta(seconds=2)),
              now=NOW+pd.Timedelta(seconds=2))
    st.accept(event(7391.,NOW+pd.Timedelta(seconds=4)),
              now=NOW+pd.Timedelta(seconds=4))
    row=st.build_record(now=NOW+pd.Timedelta(seconds=4))
    for tf in ("M1","M2","M5","M15","H1"):
        out=assess_streaming_candle(
            row,tf,now=NOW+pd.Timedelta(seconds=4))
        assert out["visible"] is True
        bar=out["bar"]
        assert (bar["open"],bar["high"],bar["low"],bar["close"])==(
            7400.,7409.,7391.,7391.)
        assert out["basis"]=="MID_OBSERVED"
        assert out["trade_permission"]=="WAIT"
        assert out["missing_extremes_possible"] is True
        if tf=="M15":
            assert bar["timeframe"]=="M15"
        else:
            assert sampled_chart_bar(
                row,tf,now=NOW+pd.Timedelta(seconds=4))["visible"]


def test_real_broker_bid_ohlc_preferred_over_sampled_mid_and_labeled():
    st,row=state_record()
    assert st.accept(ohlc("M5",high=7450.),now=NOW)=="ohlc"
    row=st.build_record(now=NOW)
    out=assess_streaming_candle(row,"M5",now=NOW)
    assert out["visible"]
    assert out["basis"]=="BID"
    assert out["bar"]["high"]==7450.
    assert out["bar"]["low"]==7390.
    assert out["missing_extremes_possible"] is False
    assert out["trade_permission"]=="WAIT"
    # It would be dishonest to pretend BID bars were MID bars.


def test_bad_ohlc_and_ask_only_events_cannot_fabricate_bid_bar():
    st,row=state_record()
    assert st.accept(ohlc(basis="ask"),now=NOW)=="ignored"
    bad=ohlc()
    bad["payload"]["h"]=7380.
    assert st.accept(bad,now=NOW)=="ignored"
    wrong=ohlc(at=NOW-pd.Timedelta(minutes=6))
    assert st.accept(wrong,now=NOW)=="ignored"
    row=st.build_record(now=NOW)
    assert assess_streaming_candle(row,"M5",now=NOW)["basis"]=="MID_OBSERVED"


def test_unknown_epic_out_of_order_timestamps_closed_and_stale_data_ignored():
    st,row=state_record()
    assert st.accept(event(9999.,NOW,epic="GER40"),now=NOW)=="ignored"
    assert st.accept(event(9999.,NOW),now=NOW)=="ignored"
    assert st.accept(event(9999.,NOW-pd.Timedelta(seconds=4)),
                     now=NOW)=="ignored"
    assert st.accept(event(9999.,NOW+pd.Timedelta(seconds=20)),
                     now=NOW)=="ignored"
    assert st.accept(event(9999.,NOW-pd.Timedelta(minutes=3)),
                     now=NOW)=="ignored"
    assert st.build_record(now=NOW+pd.Timedelta(seconds=16)) is None
    assert st.updates==1


def test_current_interval_rolls_on_m1_and_m2_independently():
    before=pd.Timestamp("2026-11-17T13:01:58Z")
    after=pd.Timestamp("2026-11-17T13:02:01Z")
    st=StreamingPrices()
    st.accept(event(7410.,before),now=before)
    st.accept(event(7420.,after),now=after)
    row=st.build_record(now=after)
    m1=assess_streaming_candle(row,"M1",now=after)["bar"]
    m2=assess_streaming_candle(row,"M2",now=after)["bar"]
    assert m1["open"]==7420.
    assert m2["open"]==7420.
    assert m1["bar_close_utc"]==pd.Timestamp(
        "2026-11-17T13:03:00Z").isoformat()


def test_stale_or_unmarked_stream_is_not_live():
    st,row=state_record()
    assert not assess_streaming_candle(
        row,"M5",now=NOW+pd.Timedelta(seconds=16))["visible"]
    row["samples"][-1].pop("transport")
    assert not assess_quote_snapshot(row,now=NOW)["fresh"]
    assert not assess_streaming_candle(row,"M5",now=NOW)["visible"]
    row["samples"][-1]["transport"]=TRANSPORT
    row["broker_status"]="CLOSED"
    assert not assess_quote_snapshot(row,now=NOW)["fresh"]
    assert not assess_streaming_candle(row,"M5",now=NOW)["visible"]
    row["broker_status"]="STREAMING_ACTIVE"
    row["broker_update_utc"]=(NOW-pd.Timedelta(seconds=40)).isoformat()
    assert not assess_quote_snapshot(row,now=NOW)["fresh"]


class _Scanner:
    environment="DEMO"
    cst="CST_FAKE"
    token="TOKEN_FAKE"
    def borrowed_headers(self):
        return {"CST":self.cst,"X-SECURITY-TOKEN":self.token}


class _Remote:
    def __init__(self):
        self.rows=[]
    def upsert_live_quote(self,row):
        self.rows.append(row)


class _Conn:
    def __init__(self,messages):
        self.messages=list(messages)
        self.sent=[]
        self.closed=False
    def settimeout(self,value): self.timeout=value
    def send(self,data): self.sent.append(json.loads(data))
    def recv(self):
        if not self.messages:
            raise RuntimeError("FAKE_END")
        return json.dumps(self.messages.pop(0))
    def close(self):self.closed=True


def test_real_protocol_subscriptions_one_connection_no_second_broker_login():
    ack1={"status":"OK","destination":"marketData.subscribe",
          "payload":{"subscriptions":{"US500":"PROCESSED"}}}
    ack2={"status":"OK","destination":"OHLCMarketData.subscribe",
          "payload":{"subscriptions":{"US500:MINUTE:classic":"PROCESSED"}}}
    at=pd.Timestamp.now(tz="UTC")
    conn=_Conn([ack1,ack2,event(7400.,at),ohlc("M1",at)])
    db=_Remote()
    pump=CloudWSQuotePump(_Scanner(),db,factory=lambda:conn)
    with pytest.raises(RuntimeError,match="FAKE_END"):
        pump._one_connection()
    assert conn.closed
    assert [v["destination"] for v in conn.sent]==[
        "marketData.subscribe","OHLCMarketData.subscribe"]
    assert conn.sent[1]["payload"]["resolutions"]==[
        "MINUTE","MINUTE_5","MINUTE_15","HOUR"]
    assert "US500" in conn.sent[0]["payload"]["epics"]
    assert not any("positions" in v["destination"] for v in conn.sent)
    assert len(db.rows)>=1
    assert db.rows[-1]["samples"][-1]["transport"]==TRANSPORT
    assert pump.snapshot()["last_fresh_utc"] is not None


def test_connection_errors_cannot_fake_live_quote_or_write():
    bad={"status":"ERROR","destination":"marketData.subscribe",
         "payload":{}}
    conn=_Conn([bad])
    db=_Remote()
    pump=CloudWSQuotePump(_Scanner(),db,factory=lambda:conn)
    with pytest.raises(RuntimeError,match="WS_QUOTE_SUBSCRIPTION_REJECTED"):
        pump._one_connection()
    assert db.rows==[]
    assert conn.closed


def test_worker_only_substitutes_websocket_quote_pump_not_paper_ledger():
    worker=Path("trader/worker.py").read_text()
    factory=Path("trader/cloud_quote_pump.py").read_text()
    stream=Path("trader/cloud_ws_prices.py").read_text()
    assert "quote_pump=build_quote_pump" in worker
    assert '"websocket"' in factory
    assert "CloudWSQuotePump" in factory
    assert "POST /positions" not in stream
    assert "queue_paper(" not in stream
    assert "progress_paper(" not in stream
    assert "marketData.subscribe" in stream
    assert "OHLCMarketData.subscribe" in stream
    assert '"destination":kind' in stream
    assert "WS_PING_SECONDS = 240" in stream
    assert WS_URL.startswith("wss://")

def test_ohlc_subscription_rejected_but_real_bid_ask_quote_still_saved():
    """Losing optional native candles must not kill the independently subscribed quote."""
    ack_quote={"status":"OK","destination":"marketData.subscribe",
               "payload":{"subscriptions":{"US500":"PROCESSED"}}}
    rejected_ohlc={"status":"ERROR","destination":"OHLCMarketData.subscribe",
                   "payload":{"subscriptions":{"US500:MINUTE:classic":"REJECTED"}}}
    at=pd.Timestamp.now(tz="UTC")
    conn=_Conn([ack_quote,rejected_ohlc,event(7400.,at)])
    db=_Remote()
    pump=CloudWSQuotePump(_Scanner(),db,factory=lambda:conn)
    with pytest.raises(RuntimeError,match="FAKE_END"):
        pump._one_connection()
    assert db.rows and db.rows[-1]["fresh"] is True
    assert db.rows[-1]["samples"][-1]["transport"]==TRANSPORT
    checked=assess_streaming_candle(db.rows[-1],"M1",now=pd.Timestamp.now(tz="UTC"))
    assert checked["visible"] is True
    assert checked["basis"]=="MID_OBSERVED"


@pytest.mark.parametrize("reason",[
    "WS_QUOTE_SUBSCRIPTION_REJECTED", "WS_CREDENTIALS_ROTATED",
    "WS_NO_SCANNER_SESSION", "WS_CONNECTION_CLOSED","WS_NO_QUOTES_45S",
])
def test_safe_explicit_websocket_runtime_reason(reason):
    assert CloudWSQuotePump._safe_error_code(RuntimeError(reason))==reason


def test_error_reason_must_never_leak_unknown_vendor_message_or_tokens():
    assert CloudWSQuotePump._safe_error_code(
        RuntimeError("WS_SERVER_REJECTED CST_SENSITIVE_TOKEN"))=="WS_WAIT_RuntimeError"
    assert CloudWSQuotePump._safe_error_code(
        ValueError("secret"))=="WS_WAIT_ValueError"
