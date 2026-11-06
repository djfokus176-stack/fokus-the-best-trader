"""Raw timestamp checks work despite invalid OHLC and NEVER enable trading."""
from datetime import datetime, timezone, timedelta
import pytest
from trader.market import CapitalReadOnly, FeedError
from trader.candle_clock_check import observe


def response_candles(start=datetime(2026,11,6,14,0,tzinfo=timezone.utc),n=8):
    return {"prices":[{
        "snapshotTimeUTC":(start+timedelta(minutes=i)).isoformat(),
        "openPrice":{"bid":7335,"ask":7334},   # deliberately crossed
        "closePrice":{"bid":7330,"ask":7329},
    } for i in range(n)]}


class Response:
    def __init__(self,payload):self.payload=payload
    def raise_for_status(self):pass
    def json(self):return self.payload


def client_with_payload(monkeypatch,payload):
    client=CapitalReadOnly("test-api","demo-user","test-pass",environment="DEMO")
    calls=[]
    monkeypatch.setattr(client,"headers",lambda:{"CST":"fake"})
    def get(url,**kw):
        calls.append((url,kw))
        return Response(payload)
    monkeypatch.setattr(client.session,"get",get)
    return client,calls


def test_raw_clock_read_does_not_depend_on_bid_ask(monkeypatch):
    client,calls=client_with_payload(monkeypatch,response_candles())
    labels=client.raw_candle_clock_labels("US500","MINUTE",8)
    assert len(labels)==8
    assert labels[0].tzinfo is not None
    assert labels[-1]-labels[-2]==timedelta(minutes=1)
    assert len(calls)==1
    assert calls[0][0].endswith("/api/v1/prices/US500")
    assert calls[0][1]["params"]=={"resolution":"MINUTE","max":8}
    assert "api-key" not in repr(labels).lower()


def test_timestamp_only_rejects_invalid_and_duplicate_data(monkeypatch):
    bad=response_candles()
    bad["prices"][1]["snapshotTimeUTC"]=bad["prices"][0]["snapshotTimeUTC"]
    c,_=client_with_payload(monkeypatch,bad)
    with pytest.raises(FeedError,match="Powielone"):
        c.raw_candle_clock_labels()
    bad=response_candles()
    bad["prices"][0]["snapshotTimeUTC"]="some invalid date"
    c,_=client_with_payload(monkeypatch,bad)
    with pytest.raises(FeedError,match="Niepoprawna etykieta"):
        c.raw_candle_clock_labels()


def test_two_samples_print_without_leaking_credentials_or_setting_gate(monkeypatch):
    c,_=client_with_payload(monkeypatch,response_candles())
    messages=[]
    waits=[]
    vals=observe(c,epic="US500",samples=2,delay_seconds=65,
         sleep=lambda t:waits.append(t),
         now=lambda:datetime(2026,11,6,14,8,tzinfo=timezone.utc),
         emit=messages.append)
    result="\n".join(messages)
    assert len(vals)==2
    assert waits==[65]
    assert "ZAKOŃCZONA" in result
    assert "NIE ustawia FOKUS_CANDLE_TIME_CONFIRMED" in result
    assert "test-pass" not in result
    assert "test-api" not in result
    assert "demo-user" not in result


def test_workflow_is_manual_readonly_and_cannot_auto_unlock():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    yaml=(root/".github/workflows/capital-clock-check.yml").read_text(encoding="utf8")
    assert "workflow_dispatch:" in yaml
    assert "contents: read" in yaml
    assert "schedule:" not in yaml
    assert "python -m trader.candle_clock_check" in yaml
    assert "FOKUS_CANDLE_TIME_CONFIRMED" not in yaml
    script=(root/"trader/candle_clock_check.py").read_text(encoding="utf8")
    assert "queue_paper" not in script
    assert "place_order" not in script
