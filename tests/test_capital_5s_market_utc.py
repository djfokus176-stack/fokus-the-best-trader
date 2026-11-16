"""Regression for the actual Capital.com 5-second UTC quote endpoint.

Docs: /markets/{epic} single-market snapshot sample includes updateTime
without UTC. Documented GET /markets?epics=US500 returns exact row with
updateTimeUTC. Never reinterpret timezone-ambiguous updateTime as UTC.
"""
from datetime import datetime, timedelta, timezone

import pytest

from trader.market import CapitalReadOnly, FeedError, parse_market_quote


def _row(*, stamp=None, epic="US500", status="TRADEABLE", delay=0):
    stamp=stamp or datetime.now(timezone.utc)
    return {
        "epic":epic, "bid":7539.1,"offer":7539.7,
        "marketStatus":status,"delayTime":delay,
        "updateTimeUTC":stamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "updateTime":stamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
    }


class _Response:
    def __init__(self,data):
        self.data=data
    def raise_for_status(self):pass
    def json(self):return self.data


class _Session:
    def __init__(self,data):
        self.data=data
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return _Response(self.data)


def _client(data):
    obj=object.__new__(CapitalReadOnly)
    obj.environment="DEMO"
    obj.base_url="https://demo-api-capital.backend-capital.com"
    obj.session=_Session(data)
    obj.headers=lambda:{"X-SECURITY-TOKEN":"test-only"}
    return obj


def test_5s_reads_documented_exact_epic_list_with_explicit_utc():
    row=_row()
    c=_client({"markets":[{"epic":"GER40","bid":2,"offer":3},row]})
    q=c.market_quote("US500")
    assert q.fresh is True
    assert q.status=="TRADEABLE"
    assert q.epic=="US500"
    assert q.bid==7539.1 and q.ask==7539.7
    assert q.update_utc is not None and q.update_utc.tzinfo is not None
    assert c.session.calls[0][0].endswith("/api/v1/markets")
    assert c.session.calls[0][1]["params"]=={"epics":"US500"}
    assert len(c.session.calls)==1


def test_singular_details_documented_updateTime_alone_cannot_claim_live():
    # This is the root cause of the previously unchanging overlay.
    single={"instrument":{"epic":"US500"},
            "snapshot":{"marketStatus":"TRADEABLE","bid":7539.1,
                        "offer":7539.7,
                        "updateTime":"2026-11-16T08:45:00.000",
                        "delayTime":0}}
    parsed=parse_market_quote(single,"US500","DEMO")
    assert parsed.fresh is False
    assert parsed.update_utc is None


def test_missing_utc_in_list_also_fails_closed_not_fake_chart():
    v=_row()
    v.pop("updateTimeUTC")
    c=_client({"markets":[v]})
    q=c.market_quote("US500")
    assert q.fresh is False and q.update_utc is None


@pytest.mark.parametrize("status,delay,offset,ok",[
    ("TRADEABLE",0,0,True),
    ("CLOSED",0,0,False),
    ("TRADEABLE",1,0,False),
    ("TRADEABLE",0,-61,False),
    ("TRADEABLE",0,45,False),
])
def test_broker_clock_and_market_veto_never_bypassed(status,delay,offset,ok):
    now=datetime.now(timezone.utc)
    row=_row(stamp=now+timedelta(seconds=offset),
             status=status,delay=delay)
    c=_client({"markets":[row]})
    assert c.market_quote("US500").fresh is ok


@pytest.mark.parametrize("data",[
    {"markets":[]},
    {"markets":[{"epic":"GER40","bid":1,"offer":2}]},
    {"markets":[_row(),_row()]},
    {},
    {"markets":{"epic":"US500"}},
])
def test_no_unambiguous_market_row_is_error_not_false_epic(data):
    c=_client(data)
    with pytest.raises(FeedError):
        c.market_quote("US500")


def test_price_is_never_read_from_wrong_instrument():
    c=_client({"markets":[{"epic":"GER40","bid":100,
                             "offer":101,"updateTimeUTC":"2026-11-16T08:45:00"}]})
    with pytest.raises(FeedError):
        c.market_quote("US500")


def test_collector_still_cannot_place_broker_order():
    import inspect
    code=inspect.getsource(CapitalReadOnly.market_quote)
    assert ".post(" not in code and "positions" not in code
    assert "epics" in code and "updateTimeUTC" in code
