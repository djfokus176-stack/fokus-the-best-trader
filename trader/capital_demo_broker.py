"""Opt-in Capital.com DEMO broker execution, separate from PAPER ledgers.

Cannot use LIVE URL, does not place orders by default. Requires the owner
to explicitly arm DEMO and supply an exact DEMO account ID and size. Records
an ATTEMPTED intent in durable Supabase CAS BEFORE any broker POST so a
worker restart or network timeout can NEVER silently duplicate the order.

This is REAL execution on the DEMO broker account using VIRTUAL funds.
Not a simulation of OHLC fills, but still not proof of profitable trading.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
import os
import re
import requests

DEMO_BASE="https://demo-api-capital.backend-capital.com"
ENABLED_VALUE="DEMO_ONLY_CONFIRMED"
MAX_ORDERS_PER_UTC_DAY=3


class DemoExecutionError(Exception):
    """Nonsecret programmatic error (no raw vendor response content)."""


def config(env=None):
    env=os.environ if env is None else env
    flag=str(env.get("FOKUS_DEMO_BROKER_MODE","OFF")).strip()
    result={"enabled":False,"status":"OFF","size":None,"account_id":None}
    if flag != ENABLED_VALUE:
        return result
    account=str(env.get("FOKUS_DEMO_BROKER_ACCOUNT_ID","")).strip()
    try:
        size=float(env.get("FOKUS_DEMO_BROKER_SIZE",""))
    except (ValueError,TypeError,OverflowError):
        size=None
    if not re.fullmatch(r"[0-9]{8,25}",account):
        return {**result,"status":"MISSING_CONFIRMED_DEMO_ACCOUNT"}
    if size is None or not isfinite(size) or not 0.01<=size<=1.0:
        return {**result,"status":"MISSING_VALID_EXPLICIT_SIZE"}
    return {"enabled":True,"status":"ARMED_DEMO_ONLY",
            "size":size,"account_id":account}


def _dt(value):
    if not isinstance(value,str):
        return None
    try:
        out=datetime.fromisoformat(value.replace("Z","+00:00"))
    except (ValueError,OverflowError):
        return None
    return out.astimezone(timezone.utc) if out.tzinfo is not None else None


def _broker(client):
    if (getattr(client,"environment",None)!="DEMO" or
            getattr(client,"base_url",None)!=DEMO_BASE or
            not hasattr(client,"headers") or
            not hasattr(client,"session")):
        raise DemoExecutionError("BROKER_NOT_VERIFIED_DEMO")
    return client


def _json(response,stage):
    try:
        response.raise_for_status()
        payload=response.json()
    except (requests.RequestException,ValueError,TypeError):
        raise DemoExecutionError(stage+"_HTTP_OR_JSON_ERROR") from None
    if not isinstance(payload,dict):
        raise DemoExecutionError(stage+"_BAD_PAYLOAD")
    return payload


def _read(client,path):
    _broker(client)
    try:
        rsp=client.session.get(DEMO_BASE+"/api/v1/"+path,
            headers=client.headers(),timeout=8)
    except requests.RequestException:
        raise DemoExecutionError("READ_CONNECTION_ERROR") from None
    return _json(rsp,"READ")


def _session_matches(client,expected_account):
    session=_read(client,"session")
    return str(session.get("accountId",""))==expected_account


def _positions(client):
    value=_read(client,"positions").get("positions")
    if not isinstance(value,list):
        raise DemoExecutionError("BROKER_POSITIONS_UNVERIFIED")
    return value


def _us500_deal_ids(positions):
    found=[]
    for row in positions:
        if not isinstance(row,dict):
            raise DemoExecutionError("BROKER_POSITION_BAD_ROW")
        market=row.get("market")
        trade=row.get("position")
        if not isinstance(market,dict) or not isinstance(trade,dict):
            raise DemoExecutionError("BROKER_POSITION_UNVERIFIED")
        if market.get("epic")=="US500":
            deal=trade.get("dealId")
            if not isinstance(deal,str) or not deal:
                raise DemoExecutionError("BROKER_POSITION_MISSING_DEAL_ID")
            found.append(deal)
    return found


def _eligible(payload,now):
    """Only one verified NEW PENDING from independent momentum test lane."""
    meta=payload.get("meta") if isinstance(payload,dict) else None
    audit=payload.get("last_vote_audit") if isinstance(payload,dict) else None
    test=payload.get("momentum_paper_test") if isinstance(payload,dict) else None
    if not all(isinstance(v,dict) for v in (meta,audit,test)):
        return None,"NO_VERIFIED_CHECKPOINT"
    if (meta.get("source")!="Capital.com DEMO REST" or
            meta.get("epic")!="US500" or
            meta.get("strategy")!="AUTO — 6 STRATEGII" or
            meta.get("clock_confirmed_open") is not True or
            meta.get("setups_enabled") is not True):
        return None,"UNVERIFIED_DEMO_MODE"
    pending=test.get("active")
    if not isinstance(pending,dict) or pending.get("status")!="PENDING":
        return None,"NO_NEW_TEST_PENDING"
    stamp=_dt(pending.get("setup_utc"))
    candle=_dt(audit.get("candle_utc"))
    scanned=_dt(meta.get("last_scan_utc"))
    if not stamp or stamp!=candle or not scanned:
        return None,"UNVERIFIED_SETUP_CANDLE"
    if not (0<=(now-stamp).total_seconds()<=85 and
            0<=(now-scanned).total_seconds()<=60):
        return None,"SETUP_EXPIRED"
    if not str(meta.get("last_scan_summary","")).startswith(
            str(audit.get("candle_utc"))+" / "):
        return None,"AUDIT_NOT_CURRENT_SCAN"
    if audit.get("blockers"):
        return None,"WORKER_GLOBAL_GATES"
    if pending.get("side") not in ("LONG","SHORT"):
        return None,"UNKNOWN_SIDE"
    try:
        stop=float(pending["stop"])
        target=float(pending["target"])
        mid=float(pending["entry_signal"])
        atr=float(pending["atr"])
    except (TypeError,ValueError,KeyError,OverflowError):
        return None,"BAD_ORDER_LEVELS"
    if not all(isfinite(x) for x in (stop,target,mid,atr)) or atr<=0:
        return None,"BAD_ORDER_LEVELS"
    if not (stop<mid<target if pending["side"]=="LONG" else target<mid<stop):
        return None,"BAD_ORDER_GEOMETRY"
    return {"setup_utc":stamp.isoformat(),"side":pending["side"],
            "stop":round(stop,2),"target":round(target,2),
            "signal_mid":mid,"atr":atr}, "ELIGIBLE"


def _preflight(client,cfg,order):
    _broker(client)
    if not _session_matches(client,cfg["account_id"]):
        raise DemoExecutionError("WRONG_DEMO_ACCOUNT_ID")
    all_positions=_positions(client)
    if _us500_deal_ids(all_positions):
        raise DemoExecutionError("US500_ALREADY_OPEN_AT_BROKER")
    quote=client.market_quote("US500")
    if (quote.environment!="DEMO" or quote.epic!="US500" or
            quote.status!="TRADEABLE" or not quote.fresh):
        raise DemoExecutionError("DEMO_QUOTE_NOT_FRESH_TRADEABLE")
    if quote.spread>2.0:
        raise DemoExecutionError("BROKER_SPREAD_TOO_WIDE")
    if abs(quote.mid-order["signal_mid"])>min(order["atr"]*.70,2.0):
        raise DemoExecutionError("PRICE_MOVED_TOO_FAR_FROM_SIGNAL")
    if order["side"]=="LONG":
        if not order["stop"]<quote.bid<quote.ask<order["target"]:
            raise DemoExecutionError("BROKER_LONG_SL_TP_INVALID")
    else:
        if not order["target"]<quote.bid<quote.ask<order["stop"]:
            raise DemoExecutionError("BROKER_SHORT_SL_TP_INVALID")
    return {
        "epic":"US500","direction":"BUY" if order["side"]=="LONG" else "SELL",
        "size":cfg["size"],"guaranteedStop":False,
        "stopLevel":order["stop"],"profitLevel":order["target"],
    }


def _submit(client,request_payload):
    _broker(client)
    try:
        rsp=client.session.post(DEMO_BASE+"/api/v1/positions",
             json=request_payload,
             headers={**client.headers(),"Content-Type":"application/json"},
             timeout=10)
    except requests.RequestException:
        # Network timeout does NOT prove the order failed! Caller already
        # persisted ATTEMPTED; retries are intentionally forbidden.
        raise DemoExecutionError("SUBMISSION_UNCERTAIN_NO_RETRY") from None
    result=_json(rsp,"POST")
    reference=result.get("dealReference")
    if not isinstance(reference,str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,100}",reference):
        raise DemoExecutionError("SUBMISSION_UNCERTAIN_NO_REFERENCE")
    return reference


def _confirm(client,reference):
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,100}",str(reference)):
        raise DemoExecutionError("BAD_CONFIRM_REFERENCE")
    value=_read(client,"confirms/"+reference)
    if value.get("dealReference")!=reference:
        raise DemoExecutionError("BROKER_CONFIRM_REFERENCE_MISMATCH")
    if value.get("epic")!="US500":
        raise DemoExecutionError("BROKER_CONFIRM_WRONG_MARKET")
    status=str(value.get("dealStatus","")).upper()
    if status=="REJECTED":
        return "REJECTED",None
    deals=value.get("affectedDeals")
    if status!="ACCEPTED" or not isinstance(deals,list):
        return "CONFIRM_PENDING",None
    accepted=[x.get("dealId") for x in deals if isinstance(x,dict)
              and x.get("status")=="OPENED" and isinstance(x.get("dealId"),str)]
    return ("ACCEPTED",accepted[0]) if accepted else ("CONFIRM_PENDING",None)


def _save_state(remote,version,payload,state):
    # CAS of entire existing checkpoint; the producer must be a SINGLE
    # Northflank process. No broker credentials or API tokens persisted.
    updated={**payload,"capital_demo_broker":state}
    new_version=remote.save(version,updated)
    return new_version,updated


def _state(payload):
    raw=payload.get("capital_demo_broker")
    return dict(raw) if isinstance(raw,dict) else {
        "status":"IDLE","last_setup_utc":None,"attempts":[],
        "deal_reference":None,"deal_id":None,
    }


def _append_attempt(state,setup):
    attempts=list(state.get("attempts") or [])
    return (attempts+[setup])[-60:]


def advance_demo_broker(remote,client,version,payload,*,now=None,env=None):
    """At most one DEMO POST per fresh setup, safely durable before POST.

    All reconciliation uses GET. If the network fails after ATTEMPTED,
    system remains UNRESOLVED with ZERO retries. Never place an order from
    OBSERVE/WAIT/old setup or LIVE account. No broker calls unless armed.
    """
    cfg=config(env)
    if not cfg["enabled"]:
        return version,payload,{"status":cfg["status"],"submitted":False}
    _broker(client)
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise DemoExecutionError("NOW_NEEDS_UTC")
    current=current.astimezone(timezone.utc)
    state=_state(payload)
    status=state.get("status")
    if status in ("ATTEMPTED","UNRESOLVED"):
        return version,payload,{"status":"UNRESOLVED_NO_RETRY",
                                "submitted":False}
    if status=="CONFIRM_PENDING":
        reference=state.get("deal_reference")
        if not reference:
            return version,payload,{"status":"UNRESOLVED_NO_REFERENCE",
                                    "submitted":False}
        try:
            resolved,deal_id=_confirm(client,reference)
        except DemoExecutionError:
            return version,payload,{"status":"CONFIRM_PENDING",
                                    "submitted":False}
        if resolved=="CONFIRM_PENDING":
            return version,payload,{"status":resolved,"submitted":False}
        state.update(status=resolved,deal_id=deal_id)
        version,payload=_save_state(remote,version,payload,state)
        return version,payload,{"status":resolved,"submitted":False}
    if status=="ACCEPTED":
        try:
            if not _session_matches(client,cfg["account_id"]):
                return version,payload,{"status":"WRONG_DEMO_ACCOUNT_ID",
                                        "submitted":False}
            ids=_us500_deal_ids(_positions(client))
        except DemoExecutionError:
            return version,payload,{"status":"BROKER_RECONCILE_UNAVAILABLE",
                                    "submitted":False}
        if state.get("deal_id") in ids:
            return version,payload,{"status":"DEMO_POSITION_OPEN",
                                    "submitted":False}
        if ids:
            return version,payload,{"status":"OTHER_US500_POSITION_OPEN",
                                    "submitted":False}
        state["status"]="BROKER_POSITION_NO_LONGER_OPEN"
        version,payload=_save_state(remote,version,payload,state)
    order,reason=_eligible(payload,current)
    if order is None:
        return version,payload,{"status":reason,"submitted":False}
    if order["setup_utc"]==state.get("last_setup_utc"):
        return version,payload,{"status":"SETUP_ALREADY_PROCESSED",
                                "submitted":False}
    today=current.date().isoformat()
    used=sum(str(x)[:10]==today for x in state.get("attempts") or [])
    if used>=MAX_ORDERS_PER_UTC_DAY:
        return version,payload,{"status":"DEMO_DAILY_POST_LIMIT",
                                "submitted":False}
    # Check exact account, broker positions and fresh quote BEFORE spending
    # any order attempt. NO POST unless all checks pass.
    try:
        request_payload=_preflight(client,cfg,order)
    except DemoExecutionError as exc:
        return version,payload,{"status":str(exc),"submitted":False}
    state.update(status="ATTEMPTED",
                 last_setup_utc=order["setup_utc"],
                 attempts=_append_attempt(state,order["setup_utc"]),
                 deal_reference=None,deal_id=None,side=order["side"],
                 size=cfg["size"],stop=order["stop"],target=order["target"],
                 attempted_utc=current.isoformat())
    # CRITICAL: Durable intent before order POST. If this fails, no order.
    version,payload=_save_state(remote,version,payload,state)
    try:
        reference=_submit(client,request_payload)
    except DemoExecutionError:
        state["status"]="UNRESOLVED"
        # Save best effort. ATTEMPTED already persisted safely, preventing
        # any future repeat even if this save fails.
        version,payload=_save_state(remote,version,payload,state)
        return version,payload,{"status":"UNRESOLVED_NO_RETRY","submitted":True}
    state.update(status="CONFIRM_PENDING",deal_reference=reference)
    version,payload=_save_state(remote,version,payload,state)
    try:
        status,deal_id=_confirm(client,reference)
    except DemoExecutionError:
        return version,payload,{"status":"CONFIRM_PENDING","submitted":True}
    if status!="CONFIRM_PENDING":
        state.update(status=status,deal_id=deal_id)
        version,payload=_save_state(remote,version,payload,state)
    return version,payload,{"status":status,"submitted":True}
