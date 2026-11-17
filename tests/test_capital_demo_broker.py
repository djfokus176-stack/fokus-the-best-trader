"""Broker DEMO opt-in: tests contain NO real credentials or HTTP requests."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from trader import capital_demo_broker as demo

NOW=datetime(2026,11,17,17,59,40,tzinfo=timezone.utc)
SETUP="2026-11-17T17:59:00+00:00"
ENV={
    "FOKUS_DEMO_BROKER_MODE":"DEMO_ONLY_CONFIRMED",
    "FOKUS_DEMO_BROKER_SIZE":"0.1",
    "FOKUS_DEMO_BROKER_ACCOUNT_ID":"12345678901234567",
}


def packet():
    return {
        "meta":{
            "source":"Capital.com DEMO REST",
            "epic":"US500",
            "strategy":"AUTO — 6 STRATEGII",
            "clock_confirmed_open":True,
            "setups_enabled":True,
            "last_scan_utc":"2026-11-17T17:59:30+00:00",
            "last_scan_summary":SETUP+" / WAIT / QUEUE=NO / GATES=OK",
        },
        "last_vote_audit":{"candle_utc":SETUP,"blockers":[]},
        "momentum_paper_test":{"last_candle_utc":SETUP,
            "active":{"status":"PENDING","setup_utc":SETUP,
                "side":"LONG","entry_signal":7400,
                "stop":7390,"target":7420,"atr":5.0}},
    }


class Rsp:
    def __init__(self,obj):
        self.obj=obj
    def raise_for_status(self):
        return None
    def json(self):
        return self.obj


class Session:
    def __init__(self):
        self.posts=[]
        self.gets=[]
        self.open_ids=[]
        self.timeout=False
    def get(self,url,**kwargs):
        self.gets.append(url)
        assert url.startswith(demo.DEMO_BASE+"/api/v1/")
        if url.endswith("/session"):
            return Rsp({"accountId":"12345678901234567"})
        if url.endswith("/positions"):
            return Rsp({"positions":[{
                "market":{"epic":"US500"},
                "position":{"dealId":ident}} for ident in self.open_ids]})
        if "/confirms/" in url:
            return Rsp({
                "dealReference":"o_test_accepted123",
                "epic":"US500",
                "dealStatus":"ACCEPTED",
                "affectedDeals":[{"dealId":"demo_deal_777",
                                  "status":"OPENED"}],
            })
        raise AssertionError("Unexpected GET path")
    def post(self,url,**kwargs):
        self.posts.append({"url":url,**kwargs})
        assert url==demo.DEMO_BASE+"/api/v1/positions"
        if self.timeout:
            raise requests.Timeout("simulate uncertain result")
        return Rsp({"dealReference":"o_test_accepted123"})


class Client:
    environment="DEMO"
    base_url=demo.DEMO_BASE
    def __init__(self):
        self.session=Session()
    def headers(self):
        return {"CST":"FAKE","X-SECURITY-TOKEN":"FAKE"}
    def market_quote(self,epic):
        assert epic=="US500"
        return SimpleNamespace(environment="DEMO",epic="US500",
             status="TRADEABLE",fresh=True,mid=7400,bid=7399.7,
             ask=7400.3,spread=.6)


class Remote:
    def __init__(self):
        self.saved=[]
        self.version=100
    def save(self,version,payload):
        assert version==self.version
        import copy
        self.saved.append(copy.deepcopy(payload.get("capital_demo_broker")))
        self.version+=1
        return self.version


def test_demo_exec_disabled_by_default_no_broker_calls():
    client=Client()
    remote=Remote()
    version,payload,out=demo.advance_demo_broker(remote,client,100,packet(),
                                                now=NOW,env={})
    assert out=={"status":"OFF","submitted":False}
    assert client.session.posts==[] and client.session.gets==[]
    assert not remote.saved


def test_explicit_config_requires_account_id_and_size_and_fixed_demo():
    assert demo.config({"FOKUS_DEMO_BROKER_MODE":"true"})["enabled"] is False
    assert demo.config({"FOKUS_DEMO_BROKER_MODE":"DEMO_ONLY_CONFIRMED"})["enabled"] is False
    assert demo.config({**ENV,"FOKUS_DEMO_BROKER_SIZE":"100"})["enabled"] is False
    assert demo.config({**ENV,"FOKUS_DEMO_BROKER_SIZE":"nan"})["enabled"] is False
    assert demo.config(ENV)["enabled"] is True
    live=Client()
    live.environment="LIVE"
    with pytest.raises(demo.DemoExecutionError,match="BROKER_NOT_VERIFIED_DEMO"):
        demo.advance_demo_broker(Remote(),live,100,packet(),now=NOW,env=ENV)
    assert not live.session.posts


def test_real_demo_one_post_after_precommitted_durable_intent_and_confirmation():
    remote=Remote()
    client=Client()
    version,payload,status=demo.advance_demo_broker(
        remote,client,100,packet(),now=NOW,env=ENV)
    assert version==103
    assert status=={"status":"ACCEPTED","submitted":True}
    assert [x["status"] for x in remote.saved]==[
        "ATTEMPTED","CONFIRM_PENDING","ACCEPTED"]
    assert remote.saved[0]["last_setup_utc"]==SETUP
    assert remote.saved[-1]["deal_id"]=="demo_deal_777"
    assert len(client.session.posts)==1
    body=client.session.posts[0]["json"]
    assert body=={
        "epic":"US500","direction":"BUY","size":0.1,
        "guaranteedStop":False,"stopLevel":7390.0,"profitLevel":7420.0,
    }
    # Broker still reports deal is open; no second order for same signal.
    client.session.open_ids=["demo_deal_777"]
    vv,pp,repeat=demo.advance_demo_broker(
        remote,client,version,payload,now=NOW,env=ENV)
    assert repeat["status"]=="DEMO_POSITION_OPEN"
    assert len(client.session.posts)==1
    assert vv==version


def test_network_timeout_must_block_any_retry_after_precommit():
    remote=Remote()
    client=Client()
    client.session.timeout=True
    v,p,o=demo.advance_demo_broker(remote,client,100,packet(),now=NOW,env=ENV)
    assert o["status"]=="UNRESOLVED_NO_RETRY"
    assert remote.saved[0]["status"]=="ATTEMPTED"
    assert remote.saved[-1]["status"]=="UNRESOLVED"
    _,_,repeat=demo.advance_demo_broker(remote,client,v,p,now=NOW,env=ENV)
    assert repeat["status"]=="UNRESOLVED_NO_RETRY"
    assert len(client.session.posts)==1


def test_wrong_account_and_manual_us500_positions_never_post():
    client=Client()
    client.session.open_ids=["MANUAL_US500"]
    _,_,r=demo.advance_demo_broker(Remote(),client,100,packet(),now=NOW,env=ENV)
    assert r["status"]=="US500_ALREADY_OPEN_AT_BROKER"
    assert not client.session.posts
    client2=Client()
    wrong={**ENV,"FOKUS_DEMO_BROKER_ACCOUNT_ID":"98765432109876543"}
    _,_,r=demo.advance_demo_broker(Remote(),client2,100,packet(),now=NOW,env=wrong)
    assert r["status"]=="WRONG_DEMO_ACCOUNT_ID"
    assert not client2.session.posts


def test_old_or_unverified_or_just_observe_signal_no_order():
    for alteration in ("old","observation","macro","no_candle_clock"):
        p=packet()
        if alteration=="old":
            at=datetime(2026,11,17,18,5,tzinfo=timezone.utc)
        else:
            at=NOW
        if alteration=="observation":
            p["momentum_paper_test"]["active"]=None
            p["last_vote_audit"]["watch"]={"side":"LONG","score":6}
        if alteration=="macro":
            p["last_vote_audit"]["blockers"]=["MACRO_BLACKOUT"]
        if alteration=="no_candle_clock":
            p["meta"]["clock_confirmed_open"]=False
        client=Client()
        _,_,res=demo.advance_demo_broker(
            Remote(),client,100,p,now=at,env=ENV)
        assert not res["submitted"] and not client.session.posts


def test_duplicate_setup_rejected_even_if_broker_position_was_closed():
    p=packet()
    p["capital_demo_broker"]={
        "status":"BROKER_POSITION_NO_LONGER_OPEN",
        "last_setup_utc":SETUP,
        "attempts":[SETUP],
    }
    c=Client()
    _,_,out=demo.advance_demo_broker(Remote(),c,100,p,now=NOW,env=ENV)
    assert out["status"]=="SETUP_ALREADY_PROCESSED"
    assert not c.session.posts


def test_worker_is_decommissioned_for_live_and_demo_mode_explicit():
    worker=Path("trader/worker.py").read_text("utf8")
    ui=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    engine=Path("trader/capital_demo_broker.py").read_text("utf8")
    assert "new_version=remote.save(version,payload)" in worker
    assert "advance_demo_broker(" in worker
    assert "CAPITAL.COM DEMO — POZYCJE NA KONCIE TESTOWYM" in ui
    assert "DEMO_ONLY_CONFIRMED" in engine
    assert "https://demo-api-capital.backend-capital.com" in engine
    assert "https://api-capital.backend-capital.com" not in engine
    assert "queue_paper(" not in engine
    assert "FOKUS_DEMO_BROKER_SIZE" in engine
    assert "CAPITAL_ALLOW_LIVE" not in engine
