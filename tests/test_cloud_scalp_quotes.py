"""Cloud quote sampler and 5s UI: strictly read-only, no false freshness."""
from datetime import datetime, timezone, timedelta

import pytest

from trader.market import MarketQuote, FeedError
from trader.cloud_scalp_quotes import Quote5sSampler, idle_quote_pulses
from trader.cloud_scalp_5s_ui import assess_quote_snapshot
from trader.remote_checkpoint import RemoteError, RemoteCheckpoint


def _quote(*, status="TRADEABLE",fresh=True,now=None):
    now=now or datetime(2026,11,16,15,0,0,tzinfo=timezone.utc)
    return MarketQuote(
        epic="US500",environment="DEMO",
        bid=7500.0,ask=7500.8,mid=7500.4,spread=.8,
        status=status,update_utc=now,received_utc=now,
        delay_seconds=0.,fresh=fresh)


class Client:
    environment="DEMO"
    def __init__(self,quote=None,raise_error=False):
        self.quote=quote or _quote()
        self.calls=0
        self.raise_error=raise_error
    def market_quote(self,epic):
        assert epic=="US500"
        self.calls+=1
        if self.raise_error:
            raise FeedError("401 sensitive nonsense")
        return self.quote


class Remote:
    def __init__(self,fail=False):
        self.rows=[]
        self.fail=fail
    def upsert_live_quote(self,row):
        if self.fail:
            raise RemoteError("404 database table absent")
        self.rows.append(row)


def test_pulse_records_bidask_and_short_bounded_history():
    s=Quote5sSampler();c=Client();r=Remote()
    assert s.pulse(c,r,monotonic=100)=="LIVE_QUOTE_SAVED"
    assert c.calls==1
    data=r.rows[-1]
    assert data["epic"]=="US500"
    assert data["source"]=="Capital.com DEMO REST"
    assert data["bid"]==7500
    assert data["ask"]==7500.8
    assert data["fresh"] is True
    assert len(data["samples"])==1
    assert s.pulse(c,r,monotonic=104) is None
    assert c.calls==1
    for k in range(1,30):
        s.pulse(c,r,monotonic=100+5*k)
    assert c.calls==30
    assert len(r.rows[-1]["samples"])==24
    assert len(s.samples)==24


def test_closed_market_scales_down_and_never_claims_live():
    s=Quote5sSampler();c=Client(_quote(status="CLOSED",fresh=False));r=Remote()
    assert s.pulse(c,r,monotonic=1)=="BROKER_NOT_FRESH"
    assert not r.rows[-1]["fresh"]
    assert r.rows[-1]["broker_status"]=="CLOSED"
    assert s.next_due==61
    assert s.pulse(c,r,monotonic=30) is None
    assert c.calls==1


def test_failed_supabase_write_does_not_crash_paper_and_backs_off():
    s=Quote5sSampler();c=Client();r=Remote(fail=True)
    assert s.pulse(c,r,monotonic=10)=="QUOTE_WAIT_RemoteError"
    assert s.next_due==310
    assert s.pulse(c,r,monotonic=12) is None
    assert c.calls==1
    s.pulse(c,r,monotonic=310)
    assert c.calls==2


def test_failed_broker_login_never_writes_or_leaks_exception():
    s=Quote5sSampler();c=Client(raise_error=True);r=Remote()
    state=s.pulse(c,r,monotonic=0)
    assert state=="QUOTE_WAIT_FeedError"
    assert r.rows==[]
    assert "sensitive" not in state


def test_wait_interval_produces_5s_pulses_without_parallel_workers():
    s=Quote5sSampler();c=Client();r=Remote()
    runtime=[100.]
    def clock():return runtime[0]
    def sleep(seconds):runtime[0]+=seconds
    idle_quote_pulses(c,r,"US500",24.9,s,monotonic=clock,sleep=sleep)
    assert c.calls==5
    assert len(r.rows)==5
    assert runtime[0]>=124.9


def _live_record(now=None):
    now=now or datetime(2026,11,16,15,0,0,tzinfo=timezone.utc)
    return dict(epic="US500",source="Capital.com DEMO REST",
                bid=7500.,ask=7500.8,mid=7500.4,spread=.8,
                broker_status="TRADEABLE",received_utc=now.isoformat(),
                broker_update_utc=now.isoformat(),delay_seconds=0.,
                fresh=True,samples=[{"utc":now.isoformat(),
                                      "bid":7500.,"ask":7500.8}])


def test_quote_ui_requires_trustworthy_freshness_and_no_orders():
    now=datetime(2026,11,16,15,0,0,tzinfo=timezone.utc)
    row=_live_record(now)
    current=assess_quote_snapshot(row,now=now+timedelta(seconds=5))
    assert current["fresh"] is True
    assert current["age_seconds"]==5
    assert current["trade_permission"]=="WAIT"
    assert len(current["samples"])==1
    assert assess_quote_snapshot(row,now=now+timedelta(seconds=13))["fresh"] is False
    row["broker_status"]="CLOSED"
    assert assess_quote_snapshot(row,now=now)["fresh"] is False
    row["broker_status"]="TRADEABLE"
    row["fresh"]=False
    assert assess_quote_snapshot(row,now=now)["fresh"] is False


def test_ui_rejects_bad_quote_data():
    row=_live_record()
    row["ask"]=7490
    with pytest.raises(ValueError,match="BID/ASK"):
        assess_quote_snapshot(row)
    row=_live_record()
    row["received_utc"]="2026-11-16 15:00:00"
    with pytest.raises(ValueError,match="UTC"):
        assess_quote_snapshot(row)


def test_remote_post_is_to_dedicated_quote_table_not_checkpoint():
    remote=RemoteCheckpoint("https://fokus5s.supabase.co","K"*40)
    calls=[]
    def fake_call(method,path,**kwargs):
        calls.append((method,path,kwargs))
    remote._call=fake_call
    q=_live_record()
    assert remote.upsert_live_quote(q)
    assert calls[0][0]=="POST"
    assert calls[0][1]=="fokus_live_quotes"
    assert calls[0][2]["params"]=={"on_conflict":"epic"}
    assert "fokus_paper_checkpoint" not in str(calls)
    q["ask"]=0
    with pytest.raises(RemoteError):
        remote.upsert_live_quote(q)
