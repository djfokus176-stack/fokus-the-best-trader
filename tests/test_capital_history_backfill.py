"""Research broker historical backfill must be read-only, bounded and causal."""
from __future__ import annotations

import pandas as pd
import pytest

from trader.capital_history_backfill import backfill_before_archive
from trader.market import FeedError


BASE = pd.Timestamp("2026-11-01T00:00:00Z")


def mid(close_stamp):
    return 5000+((close_stamp-BASE).total_seconds()/60)*.01


def rows_from_closes(times):
    vals=[mid(x) for x in times]
    return pd.DataFrame({
        "Open": vals,
        "High": [v+.5 for v in vals],
        "Low": [v-.5 for v in vals],
        "Close": [v+.05 for v in vals],
        "Spread": [.6]*len(vals),
    }, index=times)


def raw_price(open_stamp, corrupt=False):
    close_stamp=open_stamp+pd.Timedelta(minutes=1)
    value=mid(close_stamp)
    def ba(v):
        delta=2 if corrupt else 0
        return {"bid":v-.3+delta,"ask":v+.3+delta}
    return {
        "snapshotTimeUTC":open_stamp.strftime("%Y-%m-%dT%H:%M:%S"),
        "openPrice":ba(value),"highPrice":ba(value+.5),
        "lowPrice":ba(value-.5),"closePrice":ba(value+.05),
    }


class FakeResponse:
    def __init__(self,payload):
        self.payload=payload
    def raise_for_status(self):
        pass
    def json(self):
        return self.payload


class ReadOnlySession:
    def __init__(self,**kw):
        self.calls=[]
        self.kw=kw
    def get(self,url,params,headers,timeout):
        assert url.endswith("/api/v1/prices/US500")
        assert params["resolution"]=="MINUTE"
        assert params["max"]==1000
        assert headers=={"session":"redacted-test"}
        self.calls.append(params)
        a=pd.Timestamp(params["from"],tz="UTC")
        b=pd.Timestamp(params["to"],tz="UTC")
        assert (b-a).total_seconds()<900*60
        # An older broker history is available, but never a fabricated
        # candle; empty windows return the documented empty list.
        times=pd.date_range(a,b,freq="min")
        if self.kw.get("empty"):
            times=times[:0]
        records=[raw_price(t, corrupt=bool(self.kw.get("bad_overlap") and
            t==self.kw["bad_overlap"])) for t in times]
        if self.kw.get("out_of_range") and records:
            records[0]["snapshotTimeUTC"]="2020-01-01T00:00:00"
        return FakeResponse({"prices":records})


class FakeCapital:
    environment="DEMO"
    base_url="https://demo-api-capital.backend-capital.com"
    def __init__(self,**kw):
        self.session=ReadOnlySession(**kw)
    def headers(self):
        return {"session":"redacted-test"}


def archive(n=3476):
    idx=pd.date_range("2026-11-05T15:29:00Z",periods=n,freq="min")
    return rows_from_closes(idx)


def test_backfill_uses_exact_utc_ranges_without_overwriting_or_creating_prices():
    base=archive()
    client=FakeCapital()
    result=backfill_before_archive(client,base)
    updated=result["frame"]
    assert result["requests"]==2
    assert result["overlap_verified"]
    assert 4600<=len(updated)<=5000
    assert result["preflight_mtf"]
    assert updated.index[0]<base.index[0]
    assert updated.index[-1]==base.index[-1]
    pd.testing.assert_frame_equal(updated.loc[base.index],base)
    assert client.session.calls[0]["to"]=="2026-11-05T15:28:00"
    assert not updated.index.has_duplicates


def test_rejects_mismatched_archive_overlap():
    base=archive()
    client=FakeCapital(bad_overlap=base.index[0]-pd.Timedelta(minutes=1))
    with pytest.raises(FeedError,match="Niezgodność OHLC"):
        backfill_before_archive(client,base,max_batches=1)


def test_rejects_server_ignoring_requested_utc_filter():
    with pytest.raises(FeedError,match="spoza"):
        backfill_before_archive(FakeCapital(out_of_range=True),archive(),max_batches=1)


def test_empty_broker_history_does_not_invent_missing_bars():
    base=archive()
    out=backfill_before_archive(FakeCapital(empty=True),base,max_batches=2)
    pd.testing.assert_frame_equal(out["frame"],base)
    assert out["additional"]==0
    assert not out["preflight_mtf"]


def test_never_hits_broker_when_archive_has_enough_complete_h1():
    base=archive(4800)
    client=FakeCapital()
    result=backfill_before_archive(client,base)
    assert result["requests"]==0
    assert result["additional"]==0
    assert result["preflight_mtf"]


def test_live_mode_rejected_even_with_valid_ohlc():
    client=FakeCapital()
    client.environment="LIVE"
    with pytest.raises(ValueError,match="DEMO"):
        backfill_before_archive(client,archive())
