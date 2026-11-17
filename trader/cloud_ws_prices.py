"""Capital.com DEMO WebSocket: ONE read-only price stream for CLOUD charts.

Official protocol:
  wss://api-streaming-capital.backend-capital.com/connect
  marketData.subscribe -> quote (bid, ofr, timestamp in epoch ms)
  OHLCMarketData.subscribe -> ohlc.event (bid or ask OHLC per resolution)
  application-level ping at least every 10 minutes

Uses the EXISTING scanner CST/SECURITY-TOKEN (no second REST login).
Does not handle orders, PAPER, closed-candle archive, strategy inputs or SL/TP.
A missing/old quote makes the display WAIT; no synthetic price movement.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from math import isfinite
from threading import Event, Lock, Thread
import json
import os
import time

import pandas as pd

WS_URL = "wss://api-streaming-capital.backend-capital.com/connect"
SOURCE = "Capital.com DEMO WS"
# The existing Supabase table enforces source='Capital.com DEMO REST'.
# Preserve its canonical instrument/source key WITHOUT a SQL migration.
# The immutable transport marker in each sample distinguishes WebSocket
# provenance. UI must never claim the cache was filled through REST.
CACHE_SOURCE = "Capital.com DEMO REST"
TRANSPORT = "CAPITAL_WS_V1"
RESOLUTIONS = {"M1":60,"M2":120,"M5":300,"M15":900,"H1":3600}
BROKER_RES = {"MINUTE":"M1","MINUTE_5":"M5",
              "MINUTE_15":"M15","HOUR":"H1"}
WS_PING_SECONDS = 240
WRITE_SECONDS = 5.0
# If the server keeps a socket open but sends no quotes, reconnect to refresh
# subscriptions. Never extend the quoted price's freshness in the UI.
WS_QUOTE_IDLE_RECONNECT_SECONDS = 45.0
QUOTE_MAX_AGE_SECONDS = 15.0
BROKER_OHLC_MAX_AGE_SECONDS = 20.0


def _utc(value):
    t=pd.Timestamp(value)
    if pd.isna(t) or t.tzinfo is None:
        raise ValueError("Timestamp must contain timezone")
    return t.tz_convert("UTC")


def _unix_ms(raw):
    if type(raw) not in (int,float) or not isfinite(raw):
        raise ValueError("Invalid vendor epoch")
    if not 1_000_000_000_000 < raw < 4_100_000_000_000:
        raise ValueError("Expected UNIX milliseconds")
    return pd.Timestamp(int(raw),unit="ms",tz="UTC")


def _prices(raw):
    vals=[float(v) for v in raw]
    if not all(isfinite(v) and v>0 for v in vals):
        raise ValueError("Invalid streaming price")
    return vals


class StreamingPrices:
    """Pure verified observations from broker messages, no network, no trades."""

    def __init__(self):
        self.samples=deque(maxlen=24)
        self.partial={}
        self.broker_ohlc={}
        self.last_vendor=None
        self.last_quote=None
        self.last_received=None
        self.updates=0

    def accept(self,msg,*,now=None):
        """Return quote, ohlc, ignored. Unknown messages have no side effect."""
        if not isinstance(msg,dict) or msg.get("status")!="OK":
            return "ignored"
        payload=msg.get("payload")
        if not isinstance(payload,dict) or payload.get("epic")!="US500":
            return "ignored"
        instant=_utc(now if now is not None else datetime.now(timezone.utc))
        if msg.get("destination")=="quote":
            try:
                bid,ask=_prices([payload["bid"],payload["ofr"]])
                if ask<bid:
                    return "ignored"
                vendor=_unix_ms(payload["timestamp"])
                age=(instant-vendor).total_seconds()
                if not -2<=age<=QUOTE_MAX_AGE_SECONDS:
                    return "ignored"
                if self.last_vendor is not None and vendor<=self.last_vendor:
                    return "ignored"
            except (KeyError,ValueError,TypeError,OverflowError):
                return "ignored"
            self.last_vendor=vendor
            self.last_quote=(bid,ask)
            self.last_received=instant
            mid=(bid+ask)/2
            self.samples.append({"utc":vendor.isoformat(),"bid":bid,"ask":ask})
            for name,seconds in RESOLUTIONS.items():
                opened=vendor.floor(f"{seconds}s")
                closed=opened+pd.Timedelta(seconds=seconds)
                existing=self.partial.get(name)
                if existing is None or existing["bar_open_utc"]!=opened.isoformat():
                    self.partial[name]={
                        "kind":"CAPITAL_WS_OBSERVED_MID",
                        "source":SOURCE,"epic":"US500","environment":"DEMO",
                        "timeframe":name,"basis":"MID_OBSERVED",
                        "bar_open_utc":opened.isoformat(),
                        "bar_close_utc":closed.isoformat(),
                        "first_vendor_utc":vendor.isoformat(),
                        "last_vendor_utc":vendor.isoformat(),
                        "collected_utc":instant.isoformat(),
                        "open":mid,"high":mid,"low":mid,"close":mid,
                        "samples":1}
                else:
                    bar=existing
                    bar["high"]=max(bar["high"],mid)
                    bar["low"]=min(bar["low"],mid)
                    bar["close"]=mid
                    bar["samples"]+=1
                    bar["last_vendor_utc"]=vendor.isoformat()
                    bar["collected_utc"]=instant.isoformat()
            self.updates+=1
            return "quote"
        if msg.get("destination")=="ohlc.event":
            choice=BROKER_RES.get(payload.get("resolution"))
            if not choice or payload.get("priceType")!="bid" or payload.get("type")!="classic":
                return "ignored"
            try:
                barstamp=_unix_ms(payload["t"])
                opened=instant.floor(f"{RESOLUTIONS[choice]}s")
                closed=opened+pd.Timedelta(seconds=RESOLUTIONS[choice])
                # Capital examples give 't' as an interval label; accept
                # either precise OPEN or CLOSE, not stale prior periods.
                if barstamp not in (opened,closed):
                    return "ignored"
                o,h,l,c=_prices([payload[k] for k in ("o","h","l","c")])
                if h<max(o,l,c) or l>min(o,h,c):
                    return "ignored"
            except (KeyError,TypeError,ValueError,OverflowError):
                return "ignored"
            self.broker_ohlc[choice]={
                "kind":"CAPITAL_WS_BROKER_BID","source":SOURCE,
                "epic":"US500","environment":"DEMO","timeframe":choice,
                "basis":"BID","bar_open_utc":opened.isoformat(),
                "bar_close_utc":closed.isoformat(),
                "first_vendor_utc":opened.isoformat(),
                "last_vendor_utc":instant.isoformat(),
                "collected_utc":instant.isoformat(),
                "open":o,"high":h,"low":l,"close":c,"samples":1}
            return "ohlc"
        return "ignored"

    def build_record(self,*,now=None):
        at=_utc(now if now is not None else datetime.now(timezone.utc))
        if self.last_quote is None or self.last_vendor is None:
            return None
        age=(at-self.last_vendor).total_seconds()
        if not -2<=age<=QUOTE_MAX_AGE_SECONDS:
            return None
        bid,ask=self.last_quote
        sample=list(self.samples)
        if not sample:
            return None
        previews={}
        for choice,seconds in RESOLUTIONS.items():
            opened=at.floor(f"{seconds}s")
            p=self.partial.get(choice)
            b=self.broker_ohlc.get(choice)
            usable=lambda v,max_age:(isinstance(v,dict)
                and v.get("bar_open_utc")==opened.isoformat()
                and 0<=(at-_utc(v["collected_utc"])).total_seconds()<=max_age)
            # Prefer REAL provider BID OHLC. For M2 there is no native
            # broker subscription: derive MID only from observed quotes.
            if usable(b,BROKER_OHLC_MAX_AGE_SECONDS):
                previews[choice]=dict(b)
            elif usable(p,QUOTE_MAX_AGE_SECONDS):
                previews[choice]=dict(p)
        sample[-1]={**sample[-1],"stream_candles":previews,
                    "transport":TRANSPORT}
        return {
            "epic":"US500","source":CACHE_SOURCE,
            "bid":bid,"ask":ask,"mid":(bid+ask)/2,"spread":ask-bid,
            # Stream protocol has no marketStatus. Do NOT fake TRADEABLE.
            "broker_status":"STREAMING_ACTIVE",
            "broker_update_utc":self.last_vendor.isoformat(),
            "received_utc":self.last_received.isoformat(),
            # Zero detected timestamp lag, NOT a tradability guarantee.
            "delay_seconds":0.0,"fresh":True,"samples":sample}


def assess_streaming_candle(record,choice,*,now=None,last_closed_utc=None):
    """UI-only parser with strict current TF and vendor freshness checks."""
    empty={"visible":False,"reason":"BRAK_AKTUALNEGO_WS_OHLC",
           "bar":None,"quote_verified":False,
           "trade_permission":"WAIT","missing_extremes_possible":True}
    if choice not in RESOLUTIONS or not isinstance(record,dict) or (
            record.get("source")!=CACHE_SOURCE or record.get("epic")!="US500"):
        return empty
    from .cloud_scalp_5s_ui import assess_quote_snapshot
    try:
        at=_utc(now if now is not None else datetime.now(timezone.utc))
        if not assess_quote_snapshot(record,now=at)["fresh"]:
            return {**empty,"reason":"WS_CENA_NIEAKTUALNA"}
        raw=record.get("samples")
        if not isinstance(raw,list) or not raw or not isinstance(raw[-1],dict):
            return empty
        if raw[-1].get("transport")!=TRANSPORT:
            return empty
        item=raw[-1].get("stream_candles",{}).get(choice)
        if not isinstance(item,dict) or item.get("source")!=SOURCE or (
                item.get("epic")!="US500" or
                item.get("environment")!="DEMO" or
                item.get("timeframe")!=choice):
            return empty
        expected_kind=("CAPITAL_WS_BROKER_BID","CAPITAL_WS_OBSERVED_MID")
        if item.get("kind") not in expected_kind:
            return empty
        observed=item["kind"]=="CAPITAL_WS_OBSERVED_MID"
        if item.get("basis")!=("MID_OBSERVED" if observed else "BID"):
            return empty
        opened=_utc(item["bar_open_utc"])
        closed=_utc(item["bar_close_utc"])
        stamp=_utc(item["collected_utc"])
        limit=(QUOTE_MAX_AGE_SECONDS if observed
               else BROKER_OHLC_MAX_AGE_SECONDS)
        if (opened!=at.floor(f"{RESOLUTIONS[choice]}s")
                or closed-opened!=pd.Timedelta(seconds=RESOLUTIONS[choice])
                or not 0<=(at-stamp).total_seconds()<=limit
                or not opened<=at<closed):
            return {**empty,"reason":"WS_OHLC_WYGASLA"}
        if last_closed_utc is not None and closed<=_utc(last_closed_utc):
            return {**empty,"reason":"JUZ_ZAMKNIETA_W_ARCHIWUM"}
        o,h,l,c=_prices([item[k] for k in ("open","high","low","close")])
        if h<max(o,l,c) or l>min(o,h,c):
            return {**empty,"reason":"WS_OHLC_NIESPOJNA"}
        if observed:
            n=int(item["samples"])
            first=_utc(item["first_vendor_utc"])
            last=_utc(item["last_vendor_utc"])
            if n<1 or not opened<=first<=last<=stamp:
                return empty
    except (KeyError,TypeError,ValueError,OverflowError,AttributeError):
        return empty
    return {"visible":True,"reason":"WS_BROKER_BID_OHLC" if not observed
            else "WS_MID_Z_OBSERWACJI",
            "bar":{**item,"at":closed,
                   "capture_age_seconds":round((at-stamp).total_seconds(),1)},
            "basis":item["basis"],"quote_verified":True,
            "missing_extremes_possible":observed,
            "trade_permission":"WAIT","incomplete":True}


class CloudWSQuotePump:
    """Dedicated thread; WS quotes -> one existing private Supabase row."""

    def __init__(self,scanner,remote,epic="US500",*,factory=None,clock=time.monotonic):
        if epic!="US500" or getattr(scanner,"environment",None)!="DEMO":
            raise ValueError("WS viewer supports DEMO US500 only")
        self.scanner=scanner
        self.remote=remote
        self.epic=epic
        self.factory=factory or self._connect
        self.clock=clock
        self.observed=StreamingPrices()
        self._stop=Event()
        self._thread=None
        self._lock=Lock()
        self._conn=None
        self._last_write=0.0
        self._state={
            "mode":"CAPITAL_WS_STREAMING","status":"WS_STARTING",
            "attempts":0,"last_attempt_utc":None,
            "last_write_utc":None,"last_fresh_utc":None,
            "trade_permission":"WAIT"}

    @staticmethod
    def _connect():
        from websocket import create_connection
        return create_connection(WS_URL,timeout=10,enable_multithread=True)

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def _mark(self,status,*,attempt=False,wrote=False,fresh=False):
        now=datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._state["status"]=str(status)[:64]
            if attempt:
                self._state["attempts"]+=1
                self._state["last_attempt_utc"]=now
            if wrote:
                self._state["last_write_utc"]=now
            if fresh:
                self._state["last_fresh_utc"]=now

    def _credentials(self):
        borrow=getattr(self.scanner,"borrowed_headers",None)
        if callable(borrow):
            headers=borrow()
        else:
            headers={"CST":getattr(self.scanner,"cst",None),
                     "X-SECURITY-TOKEN":getattr(self.scanner,"token",None)}
        if not headers.get("CST") or not headers.get("X-SECURITY-TOKEN"):
            raise RuntimeError("WS_NO_SCANNER_SESSION")
        return headers["CST"],headers["X-SECURITY-TOKEN"]

    @staticmethod
    def _send(conn,kind,cst,token,correlation_id,payload=None):
        envelope={"destination":kind,"correlationId":str(correlation_id),
                  "cst":cst,"securityToken":token}
        if payload is not None:
            envelope["payload"]=payload
        conn.send(json.dumps(envelope))

    def feed(self,msg,*,now=None):
        """Classify known protocol outcomes without revealing broker data.

        A rejected OHLC subscription must not tear down the independent
        BID/ASK quote subscription (the live chart can still display the
        observed MID, correctly labelled as incomplete).
        """
        if not isinstance(msg,dict):
            return "ignored"
        dest=msg.get("destination")
        if dest=="OHLCMarketData.subscribe":
            subs=(msg.get("payload") or {}).get("subscriptions",{})
            if (msg.get("status")!="OK" or not isinstance(subs,dict)
                    or not subs or any(v!="PROCESSED" for v in subs.values())):
                self._mark("WS_OHLC_UNAVAILABLE")
                return "ignored"
        elif dest=="marketData.subscribe":
            subs=(msg.get("payload") or {}).get("subscriptions",{})
            if (msg.get("status")!="OK" or not isinstance(subs,dict)
                    or not subs or any(v!="PROCESSED" for v in subs.values())):
                raise RuntimeError("WS_QUOTE_SUBSCRIPTION_REJECTED")
        elif msg.get("status") not in ("OK",None):
            raise RuntimeError("WS_SERVER_REJECTED")
        return self.observed.accept(msg,now=now)

    @staticmethod
    def _safe_error_code(exc):
        # No exception text beyond our own fixed codes. Network exceptions
        # sometimes contain credential-bearing request details.
        if isinstance(exc,RuntimeError):
            code=str(exc)
            if code in ("WS_NO_SCANNER_SESSION",
                        "WS_CREDENTIALS_ROTATED","WS_CONNECTION_CLOSED",
                        "WS_QUOTE_SUBSCRIPTION_REJECTED","WS_SERVER_REJECTED",
                        "WS_NO_QUOTES_45S"):
                return code
        return "WS_WAIT_"+type(exc).__name__

    def flush(self,*,now=None,force=False):
        moment=self.clock()
        if not force and moment-self._last_write<WRITE_SECONDS:
            return False
        record=self.observed.build_record(now=now)
        if record is None:
            return False
        self.remote.upsert_live_quote(record)
        self._last_write=moment
        self._mark("WS_QUOTE_SAVED",wrote=True,fresh=True)
        return True

    def _one_connection(self):
        cst,token=self._credentials()
        conn=self.factory()
        self._conn=conn
        self._mark("WS_CONNECTED",attempt=True)
        try:
            conn.settimeout(1.0)
            self._send(conn,"marketData.subscribe",cst,token,1,
                       {"epics":[self.epic]})
            self._send(conn,"OHLCMarketData.subscribe",cst,token,2,
                       {"epics":[self.epic],
                        "resolutions":["MINUTE","MINUTE_5","MINUTE_15","HOUR"],
                        "type":"classic"})
            self._mark("WS_SUBSCRIBED_WAIT_QUOTE")
            last_ping=self.clock()
            last_auth_check=self.clock()
            last_quote_received=self.clock()
            while not self._stop.is_set():
                moment=self.clock()
                if moment-last_quote_received>=WS_QUOTE_IDLE_RECONNECT_SECONDS:
                    # The server may be silently wedged even when recv() only
                    # times out. Never manufacture prices to keep the chart up.
                    raise RuntimeError("WS_NO_QUOTES_45S")
                if moment-last_ping>=WS_PING_SECONDS:
                    self._send(conn,"ping",cst,token,3)
                    last_ping=moment
                if moment-last_auth_check>=60:
                    # Main REST scanner may refresh its tokens. Reconnect
                    # with the new tokens; never perform a second login.
                    new_cst,new_token=self._credentials()
                    if (new_cst,new_token)!=(cst,token):
                        raise RuntimeError("WS_CREDENTIALS_ROTATED")
                    last_auth_check=moment
                try:
                    incoming=conn.recv()
                except Exception as exc:
                    if type(exc).__name__ in ("WebSocketTimeoutException",
                                               "TimeoutError"):
                        self.flush()
                        continue
                    raise
                if incoming in ("",None):
                    raise RuntimeError("WS_CONNECTION_CLOSED")
                try:
                    msg=json.loads(incoming)
                except (TypeError,ValueError):
                    continue
                kind=self.feed(msg)
                if kind=="quote":
                    last_quote_received=self.clock()
                if kind in ("quote","ohlc"):
                    self.flush()
        finally:
            self._conn=None
            try:
                conn.close()
            except Exception:
                pass

    def _loop(self):
        errors=0
        while not self._stop.is_set():
            try:
                self._one_connection()
                errors=0
            except Exception as exc:
                # No raw exception text: it might contain CST/session tokens.
                errors=min(errors+1,6)
                self._mark(self._safe_error_code(exc))
            if self._stop.is_set():
                break
            # Bounded reconnect, but never a high-frequency login storm.
            # Uses the scanner's existing credentials (no extra REST login).
            self._stop.wait(min(60,10*(2**(errors-1))))

    def start(self):
        if self._thread is not None:
            raise ValueError("WS pump already active")
        self._thread=Thread(target=self._loop,
                            name="fokus-ws-quotes",daemon=True)
        self._thread.start()
        return self

    def stop(self,timeout=3.0):
        self._stop.set()
        conn=self._conn
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._thread is None or not self._thread.is_alive():
            http=getattr(self.remote,"http",None)
            if http is not None and hasattr(http,"close"):
                http.close()
