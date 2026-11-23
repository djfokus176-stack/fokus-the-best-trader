"""Capital.com bad-quote containment: chart remains visible, signals WAIT."""
import pandas as pd
import pytest
from trader.market import CapitalReadOnly, FeedError, parse_prices, PERIOD


def prices(n=100,bad=None):
    idx=pd.date_range(end="2026-11-05T20:24:00Z",periods=n,freq="min")
    out=[]
    for i,t in enumerate(idx):
        out.append({"snapshotTimeUTC":t.isoformat(),
            "openPrice":{"bid":100,"ask":100.6},
            "highPrice":{"bid":101,"ask":101.6},
            "lowPrice":{"bid":99,"ask":99.6},
            "closePrice":{"bid":100,"ask":100.6}})
    if bad is not None:
        out[bad]["closePrice"]={"bid":101,"ask":100}
    return {"prices":out}


def test_strict_diagnostic_rejects_crossed_quote():
    with pytest.raises(FeedError,match="bid > ask"):
        parse_prices(prices(bad=40))


def test_single_midwindow_bad_bar_quarantined_but_signals_blocked(monkeypatch):
    client=CapitalReadOnly("testkey","id","pass","DEMO")
    class Response:
        def raise_for_status(self): pass
        def json(self):return prices(bad=40)
    monkeypatch.setattr(client,"headers",lambda:{"CST":"test"})
    monkeypatch.setattr(client.session,"get",lambda *args,**kwargs:Response())
    snapshot=client.candles("US500","MINUTE")
    assert len(snapshot.frame)==98  # 100 - bad bar - newest potentially forming
    assert "DANE_WADLIWE" in snapshot.reason
    assert "bid > ask" in snapshot.reason
    assert snapshot.good is False
    assert snapshot.frame.index.is_monotonic_increasing
    assert all(snapshot.frame.High >= snapshot.frame[["Open","Close","Low"]].max(axis=1))
    assert all(snapshot.frame.Low <= snapshot.frame[["Open","Close","High"]].min(axis=1))
    assert snapshot.frame.index.to_series().diff().max()==pd.Timedelta(minutes=2)


def test_bad_latest_bar_never_promoted_to_valid_closed_signal(monkeypatch):
    client=CapitalReadOnly("key","id","pass","DEMO")
    class Response:
        def raise_for_status(self):pass
        def json(self):return prices(bad=99)
    monkeypatch.setattr(client,"headers",lambda:{})
    monkeypatch.setattr(client.session,"get",lambda *args,**kwargs:Response())
    snap=client.candles()
    assert not snap.good
    assert len(snap.frame)==98
    assert "DANE_WADLIWE" in snap.reason


def test_no_valid_bars_fails_closed():
    payload=prices(n=1,bad=0)
    with pytest.raises(FeedError,match="Brak poprawnych świec"):
        parse_prices(payload,quarantine_bad=True)
