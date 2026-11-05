"""Legacy-like 5-second *forming* OHLC /prices fetch, isolated from PAPER."""
from datetime import datetime,timedelta,timezone
import pandas as pd
import plotly.graph_objects as go
import pytest
from trader.market import CapitalReadOnly,FeedError
from trader.live_chart import show_quote_preview

NOW=datetime(2026,11,5,23,45,16,tzinfo=timezone.utc)


def payload(open_label="2026-11-05T23:45:00",close_bid=7330.7):
    def candle(t,mid):
        return {"snapshotTimeUTC":t,
            "openPrice":{"bid":mid-.3,"ask":mid+.3},
            "highPrice":{"bid":mid+1,"ask":mid+1.6},
            "lowPrice":{"bid":mid-1,"ask":mid-.4},
            "closePrice":{"bid":mid-.3,"ask":mid+.3}}
    return {"prices":[candle("2026-11-05T23:44:00",7330.0),
                       candle(open_label,close_bid+0.3)]}


def test_forming_candle_fetches_only_2_bars_same_source_as_old_app(monkeypatch):
    seen=[]
    client=CapitalReadOnly("test-api","demo-id","demo-pass","DEMO")
    class Response:
        def raise_for_status(self):pass
        def json(self):return payload()
    monkeypatch.setattr(client,"headers",lambda:{"CST":"fake"})
    def get(url,**kwargs):
        seen.append((url,kwargs))
        return Response()
    monkeypatch.setattr(client.session,"get",get)
    item=client.forming_candle("US500","MINUTE",now=NOW)
    assert len(seen)==1
    assert seen[0][0].endswith("/api/v1/prices/US500")
    assert seen[0][1]["params"]=={"resolution":"MINUTE","max":2}
    assert item["time"]==pd.Timestamp("2026-11-05T23:46:00Z")
    assert item["source"]=="Capital.com /prices • bieżąca OHLC"
    assert item["Close"]==pytest.approx(7331.0)
    fig=show_quote_preview(go.Figure(),item,bars=None)
    assert len(fig.data)==2
    assert "NIE PAPER" in fig.data[0].name
    assert not any("PAPER_OPEN" in str(t.name) for t in fig.data)


def test_stale_latest_bar_is_not_falsely_drawn_as_live(monkeypatch):
    client=CapitalReadOnly("api","id","pass","DEMO")
    class Response:
        def raise_for_status(self):pass
        def json(self):return payload()
    monkeypatch.setattr(client,"headers",lambda:{})
    monkeypatch.setattr(client.session,"get",lambda *args,**kw:Response())
    with pytest.raises(FeedError,match="nieaktualna"):
        client.forming_candle(now=NOW+timedelta(minutes=3))


def test_bad_current_bid_ask_never_draws_a_live_bar(monkeypatch):
    client=CapitalReadOnly("api","id","pass","DEMO")
    class Response:
        def raise_for_status(self):pass
        def json(self):
            x=payload()
            x["prices"][-1]["closePrice"]={"bid":7400,"ask":7300}
            return x
    monkeypatch.setattr(client,"headers",lambda:{})
    monkeypatch.setattr(client.session,"get",lambda *args,**kw:Response())
    with pytest.raises(FeedError,match="bid > ask"):
        client.forming_candle(now=NOW)
