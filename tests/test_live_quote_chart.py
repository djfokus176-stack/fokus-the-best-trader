"""Real REST price snapshots may animate the chart but NEVER create trade data."""
from datetime import datetime, timezone, timedelta
import pandas as pd
import pytest
import plotly.graph_objects as go

from trader.market import MarketQuote, FeedError, CapitalReadOnly, parse_market_quote
from trader.live_chart import quote_sample, sampled_preview, show_quote_preview


NOW=datetime(2026,11,5,23,45,16,tzinfo=timezone.utc)


def payload(bid=7331.4,ask=7332.0,updated="2026-11-05T23:45:15"):
    return {"instrument":{"marketStatus":"TRADEABLE"},
            "snapshot":{"bid":bid,"offer":ask,
                        "updateTimeUTC":updated,"delayTime":0,
                        "marketStatus":"TRADEABLE"}}


def test_live_market_snapshot_validates_quote_not_ohlc():
    quote=parse_market_quote(payload(),"US500","DEMO",now=NOW)
    assert quote.fresh
    assert quote.mid==pytest.approx(7331.7)
    assert quote.spread==pytest.approx(.6)
    assert quote.status=="TRADEABLE"
    assert quote.update_utc.tzinfo is not None
    with pytest.raises(FeedError,match="bid"):
        parse_market_quote(payload(ask=7330),"US500","DEMO",NOW)


def test_old_closed_or_delayed_quote_cannot_be_labeled_live():
    assert not parse_market_quote(payload(updated="2026-11-05T23:42:00"),
                                  "US500","DEMO",NOW).fresh
    p=payload()
    p["snapshot"]["delayTime"]=60
    assert not parse_market_quote(p,"US500","DEMO",NOW).fresh
    p=payload()
    p["snapshot"].pop("updateTimeUTC")
    assert not parse_market_quote(p,"US500","DEMO",NOW).fresh
    p=payload()
    p["snapshot"]["marketStatus"]="CLOSED"
    assert not parse_market_quote(p,"US500","DEMO",NOW).fresh


def test_live_rest_method_is_read_only_and_uses_one_market_get(monkeypatch):
    client=CapitalReadOnly("secret-key","test-login","pass","DEMO")
    seen=[]
    class Response:
        def raise_for_status(self): pass
        def json(self): return payload()
    monkeypatch.setattr(client,"headers",lambda:{"CST":"fake"})
    def get(url,**kwargs):
        seen.append((url,kwargs))
        return Response()
    monkeypatch.setattr(client.session,"get",get)
    # use monkeypatch clock in the parse step: historic test quote is stale
    quote=client.market_quote("US500")
    assert quote.mid==pytest.approx(7331.7)
    assert len(seen)==1
    assert seen[0][0].endswith("/api/v1/markets/US500")
    assert "/prices/" not in seen[0][0]


def test_live_preview_moves_on_new_quote_while_closed_bars_do_not_change():
    idx=pd.date_range(end="2026-11-05T23:45:00Z",periods=75,freq="min")
    frame=pd.DataFrame({"Open":[7330]*75,"High":[7333]*75,
        "Low":[7328]*75,"Close":[7331]*75},index=idx)
    raw_copy=frame.copy(deep=True)
    quote1=parse_market_quote(payload(7331.4,7332.0),"US500","DEMO",NOW)
    quote2=parse_market_quote(payload(7332.8,7333.2,updated="2026-11-05T23:45:20"),
                              "US500","DEMO",NOW+timedelta(seconds=6))
    samples=quote_sample([],quote1,"MINUTE")
    samples=quote_sample(samples,quote2,"MINUTE")
    p=sampled_preview(samples,closed_time=idx[-1])
    assert p["time"]==pd.Timestamp("2026-11-05T23:46:00Z")
    assert p["Close"]==pytest.approx(7333.0)
    assert p["Open"]==pytest.approx(7331.7)
    assert p["High"]>=p["Close"]
    assert p["samples"]==2
    fig=show_quote_preview(go.Figure(),p,bars=frame,visible_bars=30)
    assert len(fig.data)==2
    assert "niepełna świeca" in fig.data[0].name
    assert fig.data[0].close[0]==pytest.approx(7333.0)
    assert fig.layout.yaxis.range[0] < 7328
    assert fig.layout.yaxis.range[1] > 7333
    pd.testing.assert_frame_equal(frame,raw_copy)


def test_duplicate_quote_vendor_timestamp_does_not_fake_new_bar():
    q=parse_market_quote(payload(),"US500","DEMO",NOW)
    records=quote_sample([],q,"MINUTE")
    assert quote_sample(records,q,"MINUTE")==records


def test_quote_samples_cannot_leak_between_epics_or_timeframes():
    q=parse_market_quote(payload(),"US500","DEMO",NOW)
    rows=quote_sample([],q,"MINUTE")
    assert quote_sample(rows,q,"MINUTE_5")!=rows
    other=parse_market_quote(payload(),"NAS100","DEMO",NOW)
    assert len(quote_sample(rows,other,"MINUTE"))==1


def test_stale_and_missing_quote_do_not_create_provisional_bar():
    old=parse_market_quote(payload(updated="2026-11-05T23:42:00"),
                           "US500","DEMO",NOW)
    assert quote_sample([],old,"MINUTE")==[]
    assert sampled_preview([],closed_time=NOW) is None
    p=parse_market_quote(payload(),"US500","DEMO",NOW)
    assert sampled_preview(quote_sample([],p,"MINUTE"),
                           closed_time=pd.Timestamp("2026-11-05T23:46:00Z")) is None


def test_live_preview_never_creates_trade_markers():
    q=parse_market_quote(payload(),"US500","DEMO",NOW)
    preview=sampled_preview(quote_sample([],q,"MINUTE"))
    fig=show_quote_preview(go.Figure(),preview,bars=None)
    assert all("PAPER" not in str(trace.name) for trace in fig.data)
