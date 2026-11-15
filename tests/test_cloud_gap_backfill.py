"""No credentials, live orders or network calls in Capital gap-backfill tests."""
from datetime import datetime, timezone
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from trader.cloud_gap_backfill import backfill_pass
from trader.market import CapitalReadOnly, FeedError
from trader.remote_checkpoint import RemoteCheckpoint, RemoteError


NOW = pd.Timestamp("2026-11-15T12:00:00Z")


def _bars(labels):
    idx=pd.DatetimeIndex(labels,tz="UTC")
    return pd.DataFrame({"Open":[100.]*len(idx), "High":[101.]*len(idx),
                         "Low":[99.]*len(idx),"Close":[100.]*len(idx),
                         "Spread":[.6]*len(idx)},index=idx)


class FakeCloud:
    def __init__(self, stamps):
        self.stamps=pd.DatetimeIndex(stamps,tz="UTC")
        self.writes=[]
        self.requests=[]
    def fetch_candle_times(self,epic,tf,*,before=None,limit=1000):
        self.requests.append((epic,tf,before,limit))
        if tf!="MINUTE":
            return pd.DatetimeIndex([],tz="UTC")
        index=self.stamps
        if before:
            index=index[index<=pd.Timestamp(before)]
        return index[-limit:]
    def insert_missing_candles(self,epic,tf,frame):
        self.writes.append((epic,tf,frame.copy()))
        return len(frame)


class FakeBroker:
    environment="DEMO"
    def __init__(self,bars):
        self.bars=bars
        self.calls=[]
    def historical_closed_candles(self,epic,tf,start,end,*,max_count):
        self.calls.append((epic,tf,start,end,max_count))
        return self.bars


def test_backfill_only_broker_proven_candles_and_no_repeat_before_one_hour():
    cloud=FakeCloud(["2026-11-05 12:00","2026-11-05 12:01",
                     "2026-11-05 12:04","2026-11-05 12:05"])
    broker=FakeBroker(_bars(["2026-11-05 12:02","2026-11-05 12:03",
                            "2026-11-05 12:04"]))
    state=backfill_pass(cloud,broker,now=NOW,page_limit=8)
    assert state["status"]=="SUBMITTED_VERIFIED_CANDLES"
    assert state["unobserved_slots"]==2
    assert state["broker_rows"]==2
    assert state["submitted_rows"]==2
    assert len(cloud.writes)==1
    assert list(cloud.writes[0][2].index)==list(broker.bars.index[:2])
    assert broker.calls[0][2]==pd.Timestamp("2026-11-05 12:01Z")
    assert broker.calls[0][3]==pd.Timestamp("2026-11-05 12:03Z")
    repeated=backfill_pass(cloud,broker,state,now=NOW+pd.Timedelta(minutes=10),
                           page_limit=8)
    assert repeated==state
    assert len(broker.calls)==1


def test_broker_empty_keeps_gap_unmodified_and_skips_daily_break():
    cloud=FakeCloud(["2026-11-05 13:00","2026-11-05 13:04"])
    broker=FakeBroker(_bars([]))
    out=backfill_pass(cloud,broker,now=NOW,page_limit=8)
    assert out["status"]=="BROKER_NO_MATCHING_BARS"
    assert not cloud.writes
    night=FakeCloud(["2026-11-09 22:00","2026-11-09 22:06"])
    out=backfill_pass(night,broker,now=NOW,page_limit=8)
    assert out["status"]=="NO_ELIGIBLE_GAP"
    assert len(broker.calls)==1


def test_refuses_live_or_wrong_market():
    cloud=FakeCloud([])
    with pytest.raises(ValueError,match="DEMO"):
        backfill_pass(cloud,SimpleNamespace(environment="LIVE"),now=NOW)
    with pytest.raises(ValueError,match="instrumentu"):
        backfill_pass(cloud,FakeBroker(_bars([])),now=NOW,epic="NAS100")


def _price(at):
    price=lambda val:{"bid":val-.3,"ask":val+.3}
    return {"snapshotTimeUTC":at,
            "openPrice":price(100.),"highPrice":price(101.),
            "lowPrice":price(99.),"closePrice":price(100.)}


class Reply:
    status_code=200
    def __init__(self,prices):
        self.prices=prices
    def raise_for_status(self):
        pass
    def json(self):
        return {"prices":self.prices}


class FakePriceSession:
    def __init__(self,prices):
        self.prices=prices
        self.requests=[]
    def get(self,url,*,params,headers,timeout):
        self.requests.append((url,params,headers))
        return Reply(self.prices)


def test_historical_api_from_to_is_open_time_and_converts_to_close_once():
    prices=[_price("2026-11-05T12:01:00"),
            _price("2026-11-05T12:02:00"),
            _price("2026-11-05T12:03:00")]
    broker=CapitalReadOnly("example-api-key","demo-user","secret",environment="DEMO")
    broker.session=FakePriceSession(prices)
    broker.cst="mock-cst"; broker.token="mock-token"
    broker.session_started=time.time()
    df=broker.historical_closed_candles(
        "US500","MINUTE",pd.Timestamp("2026-11-05T12:01Z"),
        pd.Timestamp("2026-11-05T12:03Z"),max_count=4)
    assert list(df.index)==list(pd.date_range(
        "2026-11-05T12:02Z",periods=3,freq="min"))
    assert all(abs(x-.6)<1e-9 for x in df.Spread)
    req=broker.session.requests[0][1]
    assert req["from"]=="2026-11-05T12:01:00"
    assert req["to"]=="2026-11-05T12:03:00"
    assert req["resolution"]=="MINUTE"
    broker.environment="LIVE"
    with pytest.raises(FeedError,match="DEMO"):
        broker.historical_closed_candles("US500","MINUTE",
            pd.Timestamp("2026-11-05T12:01Z"),
            pd.Timestamp("2026-11-05T12:03Z"))


class CloudReply:
    status_code=201
    def json(self):
        return []


class CloudSession:
    def __init__(self):
        self.calls=[]
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs))
        return CloudReply()


def test_remote_missing_only_insert_must_ignore_duplicates():
    session=CloudSession()
    remote=RemoteCheckpoint("https://isolated-fokus-trader.supabase.co",
                            "sb_secret_"+"x"*48,session=session)
    idx=_bars(["2026-11-05 12:02","2026-11-05 12:03"])
    assert remote.insert_missing_candles("US500","MINUTE",idx)==2
    method,url,kwargs=session.calls[-1]
    assert method=="POST"
    assert kwargs["headers"]["Prefer"]=="resolution=ignore-duplicates,return=minimal"
    assert kwargs["params"]["on_conflict"]=="source,epic,timeframe,candle_utc"
    assert len(kwargs["json"])==2
    bad=idx.copy()
    bad.loc[bad.index[0],"High"]=98.
    with pytest.raises(RemoteError,match="OHLC"):
        remote.insert_missing_candles("US500","MINUTE",bad)
    assert len(session.calls)==1
