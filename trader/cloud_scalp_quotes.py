"""5-second best-effort DEMO BID/ASK observer in the EXISTING cloud worker.

This collector runs ONLY during the idle gaps between existing M1 PAPER
scans, not in a competing process. It never calls any order endpoint,
modifies PAPER/WAVE/MTF, or makes 5-second candles out of quote samples.

The provider may deliver unchanged quotes; broker CLOSED and API errors
back off. Persist a SINGLE latest quote + max 24 recent samples in a
separate private Supabase table, never in the versioned PAPER checkpoint.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime,timezone
import os
from math import isfinite
import time

from .market import FeedError
from .remote_checkpoint import RemoteError
from .cloud_forming_m1 import serialize_forming_m1
from .cloud_moving_m15 import update_sampled_m15, broker_forming_m15
from .cloud_broker_timeframes import CONFIG as BROKER_TF, serialize_broker_forming

SOURCE="Capital.com DEMO REST"
MAX_SAMPLES=24
LIVE_INTERVAL=5.0
CLOSED_INTERVAL=60.0
ERROR_INTERVAL=300.0
FEED_RETRY_INTERVAL=30.0
RATE_LIMIT_RETRY_INTERVAL=120.0
PRICES_FALLBACK_INTERVAL=10.0  # read-only display fallback, rate-limited
FORMING_INTERVAL=5.0  # read the actual unfinished M1 as in legacy v7.1
FORMING_ERROR_INTERVAL=60.0
M15_FORMING_INTERVAL=30.0  # extra broker M15 at most every 30s
M15_FORMING_ERROR_INTERVAL=120.0
EXTRA_FORMING_INTERVALS={"M5":30.0,"H1":45.0}
EXTRA_FORMING_ERROR_INTERVAL=90.0


class Quote5sSampler:
    def __init__(self):
        self.next_due=0.
        self.samples=deque(maxlen=MAX_SAMPLES)
        self.last_status="NOT_STARTED"
        self.forming_m1_next_due=0.
        self.forming_m1=None
        self.forming_m1_status="NOT_STARTED"
        self.sampled_m15=None
        self.forming_m15=None
        self.forming_m15_next_due=0.
        self.forming_m15_status="NOT_STARTED"
        self.extra_forming={}
        self.extra_forming_next_due={"M5":0.,"H1":0.}
        self.extra_forming_status={"M5":"NOT_STARTED","H1":"NOT_STARTED"}

    def _collect_extra_forming(self,client,epic,moment):
        """Optional real M5/H1 broker /prices; never affects accounting."""
        if os.getenv("FOKUS_CLOUD_MTF_FORMING_ENABLED","true").strip().lower() not in (
                "true","1","yes","on"):
            return
        method=getattr(client,"forming_candle",None)
        if not callable(method):
            return
        for choice in ("M5","H1"):
            if moment<self.extra_forming_next_due[choice]:
                continue
            self.extra_forming_next_due[choice]=(
                moment+EXTRA_FORMING_INTERVALS[choice])
            try:
                raw=method(epic,BROKER_TF[choice][0])
                self.extra_forming[choice]=serialize_broker_forming(
                    raw,choice,now=datetime.now(timezone.utc))
                self.extra_forming_status[choice]="BROKER_OHLC_SAVED"
            except (FeedError,RemoteError,ValueError,TypeError,KeyError,
                    AttributeError,OverflowError,OSError) as exc:
                self.extra_forming.pop(choice,None)
                self.extra_forming_status[choice]="BROKER_OHLC_WAIT_"+type(exc).__name__
                self.extra_forming_next_due[choice]=moment+(
                    RATE_LIMIT_RETRY_INTERVAL if "HTTP 429" in str(exc)
                    else EXTRA_FORMING_ERROR_INTERVAL)

    def _recent_extra(self,now):
        """Only genuinely current broker OHLC goes into the last JSON sample."""
        output={}
        for choice,(_,_,key,_) in BROKER_TF.items():
            val=self.extra_forming.get(choice)
            if not isinstance(val,dict):
                continue
            try:
                received=datetime.fromisoformat(val["collected_utc"])
                close=datetime.fromisoformat(val["bar_close_utc"])
                if (0 <= (now-received).total_seconds() <= 48
                        and now < close):
                    output[key]=val
            except (KeyError,ValueError,TypeError,OverflowError):
                continue
        return output

    def _prices_only_fallback(self,client,remote,epic,moment):
        """Read-only M15 display backup if /markets quote endpoint fails.

        Requires a SEPARATE broker marketStatus=TRADEABLE and an ACTUAL
        current /prices M15, both read using the SAME Capital login.
        Crucially fresh=False, delay UNKNOWN: never a certified LIVE price,
        tick, strategy candle or PAPER quote.
        """
        if (os.getenv("FOKUS_CLOUD_PRICES_ONLY_FALLBACK_ENABLED","true")
                .strip().lower() not in ("true","1","yes","on")):
            return None
        status_fn=getattr(client,"market_state",None)
        candle_fn=getattr(client,"forming_candle",None)
        if not callable(status_fn) or not callable(candle_fn):
            return None
        if str(status_fn(epic)).upper()!="TRADEABLE":
            return None
        # Legacy SP500 v7.1 displayed the CURRENT candle directly from
        # /prices. Do the same in the EXISTING Northflank login instead
        # of depending on the /markets timestamp. Both remain UI-only.
        now=datetime.now(timezone.utc)
        m1=None
        m15=None
        try:
            m1=serialize_forming_m1(candle_fn(epic,"MINUTE"),
                                   collected_utc=datetime.now(timezone.utc))
        except (FeedError,ValueError,TypeError,KeyError,OverflowError):
            pass
        try:
            m15=broker_forming_m15(candle_fn(epic,"MINUTE_15"),
                                   now=datetime.now(timezone.utc))
        except (FeedError,ValueError,TypeError,KeyError,OverflowError):
            pass
        self._collect_extra_forming(client,epic,moment)
        extras=self._recent_extra(datetime.now(timezone.utc))
        preferred=m1 or m15 or extras.get("forming_m5") or extras.get("forming_h1")
        if preferred is None:
            return None
        bid=float(preferred["bid"]);ask=float(preferred["ask"])
        # 9999 denotes UNKNOWN quote delay, never zero/confirmed.
        # Only the chart parser may use this explicitly flagged /prices
        # M15; all real quote/strategy guards continue to reject it.
        row={
            "epic":"US500","source":SOURCE,"bid":bid,"ask":ask,
            "mid":(bid+ask)/2,"spread":ask-bid,
            "broker_status":"TRADEABLE",
            "broker_update_utc":None,
            "received_utc":now.isoformat(),
            "delay_seconds":9999.0,"fresh":False,
            "samples":[{
                "utc":now.isoformat(),"bid":bid,"ask":ask,
                **({"forming_m1":m1} if m1 else {}),
                **({"forming_m15":m15} if m15 else {}),
                **extras,
                "fallback_only":True,
                "source_delay_unknown":True}],
        }
        remote.upsert_live_quote(row)
        self.last_status=("BROKER_M1_ONLY_UNVERIFIED_QUOTE" if m1 else
                          "BROKER_M15_ONLY_UNVERIFIED_QUOTE")
        self.next_due=moment+PRICES_FALLBACK_INTERVAL
        return self.last_status

    def pulse(self, client, remote, epic="US500", *, monotonic=None):
        """Return concise safe status, without surfacing exception details."""
        moment=float(time.monotonic() if monotonic is None else monotonic)
        if moment < self.next_due:
            return None
        try:
            if getattr(client,"environment","")!="DEMO" or epic!="US500":
                self.last_status="CONFIG_ERROR"
                self.next_due=moment+ERROR_INTERVAL
                return self.last_status
            try:
                quote=client.market_quote(epic)
            except FeedError:
                # Some Capital DEMO plans/responses do not provide usable
                # UTC quote data on /markets while /prices M15 works.
                # This does NOT certify a live BID/ASK or enable PAPER.
                fallback=self._prices_only_fallback(
                    client,remote,epic,moment)
                if fallback is not None:
                    return fallback
                raise
            if quote.environment!="DEMO" or quote.epic!="US500":
                raise ValueError("Quote source mismatch")
            bid,ask=float(quote.bid),float(quote.ask)
            if not isfinite(bid) or not isfinite(ask) or bid<=0 or ask<bid:
                raise ValueError("Untrusted BID/ASK")
            # Provisional M15 wick samples use ONLY genuine, fresh vendor
            # quotes from this SAME Northflank client session. They do NOT
            # enter any trading lifecycle or confirmed-candle archive.
            self.sampled_m15=update_sampled_m15(
                self.sampled_m15,quote) if quote.fresh else None
            # Optional actual provider M15 partial OHLC for chart-only
            # comparison. The MID-sampled candle keeps moving with fresh
            # quotes between broker /prices calls (~30 seconds).
            if (quote.status=="TRADEABLE" and
                    moment>=self.forming_m15_next_due and
                    os.getenv("FOKUS_CLOUD_FORMING_M15_ENABLED","true")
                    .strip().lower() in ("true","1","yes","on")):
                self.forming_m15_next_due=moment+M15_FORMING_INTERVAL
                try:
                    method=getattr(client,"forming_candle",None)
                    if not callable(method):
                        self.forming_m15_status="UNSUPPORTED_CLIENT"
                        self.forming_m15=None
                    else:
                        raw_m15=method(epic,"MINUTE_15")
                        self.forming_m15=broker_forming_m15(
                            raw_m15,now=datetime.now(timezone.utc))
                        self.forming_m15_status="M15_BROKER_PREVIEW_SAVED"
                except (FeedError,RemoteError,ValueError,TypeError,KeyError,
                        AttributeError,OverflowError,OSError):
                    self.forming_m15=None
                    self.forming_m15_status="M15_WAIT_INVALID_OR_API"
                    self.forming_m15_next_due=moment+M15_FORMING_ERROR_INTERVAL
            elif quote.status!="TRADEABLE":
                self.forming_m15=None
                self.forming_m15_status="MARKET_NOT_TRADEABLE"
            # Actual M5/H1 OHLC from the SAME Capital DEMO session. This
            # reader is deliberately independent of the quote.fresh flag;
            # old /markets timestamps must not suppress display-only OHLC.
            if quote.status=="TRADEABLE":
                self._collect_extra_forming(client,epic,moment)
            else:
                self.extra_forming.clear()
            # Only this same authenticated worker may request incomplete M1.
            # /prices is throttled to ~15s independently of 5s MID polls.
            # An error has no effect on the quote write or PAPER lifecycle.
            if (quote.status=="TRADEABLE" and
                    moment>=self.forming_m1_next_due and
                    os.getenv("FOKUS_CLOUD_FORMING_M1_ENABLED","true")
                      .strip().lower() in ("true","1","yes","on")):
                self.forming_m1_next_due=moment+FORMING_INTERVAL
                try:
                    method=getattr(client,"forming_candle",None)
                    if not callable(method):
                        self.forming_m1_status="UNSUPPORTED_CLIENT"
                        self.forming_m1=None
                    else:
                        raw=method(epic,"MINUTE")
                        self.forming_m1=serialize_forming_m1(
                            raw,collected_utc=datetime.now(timezone.utc))
                        self.forming_m1_status="M1_PREVIEW_SAVED"
                except (FeedError,RemoteError,ValueError,TypeError,KeyError,
                        AttributeError,OverflowError,OSError) as exc:
                    self.forming_m1=None
                    self.forming_m1_status="M1_WAIT_"+type(exc).__name__
                    self.forming_m1_next_due=moment+(
                        RATE_LIMIT_RETRY_INTERVAL if "HTTP 429" in str(exc)
                        else FORMING_ERROR_INTERVAL)
            elif quote.status!="TRADEABLE":
                # Invalidate the in-progress preview on broker close.
                self.forming_m1=None
                self.forming_m1_status="MARKET_NOT_TRADEABLE"
            # Samples are observations, NOT guaranteed individual market ticks.
            if quote.fresh:
                self.samples.append({
                    "utc":quote.received_utc.astimezone(timezone.utc).isoformat(),
                    "bid":round(bid,5),"ask":round(ask,5)})
            # Attach broker M1 only to the LATEST REST sample. Existing
            # fokus_live_quotes.samples JSONB permits additional optional
            # keys; all legacy readers still consume just utc/bid/ask.
            # The queue remains pure; no new DB table/column or writer.
            samples=list(self.samples)
            if samples and quote.fresh and self.forming_m1 is not None:
                try:
                    captured=datetime.fromisoformat(
                        self.forming_m1["collected_utc"])
                    close=datetime.fromisoformat(
                        self.forming_m1["close_utc"])
                    now_utc=datetime.now(timezone.utc)
                    if (0 <= (now_utc-captured).total_seconds() <= 28
                            and now_utc < close):
                        samples[-1]={**samples[-1],
                                     "forming_m1":self.forming_m1}
                except (KeyError,TypeError,ValueError,OverflowError):
                    pass
            # Separate optional, non-trading M15 observations are attached
            # to the EXISTING latest quote sample JSONB. No new table,
            # column, writer or API credentials in the frontend.
            # Never forward stale in-progress M15 data.
            if samples and quote.fresh:
                extra=self._recent_extra(datetime.now(timezone.utc))
                if extra:
                    samples[-1]={**samples[-1],**extra}
                now_m15=datetime.now(timezone.utc)
                sampled=self.sampled_m15
                if isinstance(sampled,dict):
                    try:
                        at=datetime.fromisoformat(sampled["collected_utc"])
                        end=datetime.fromisoformat(sampled["bar_close_utc"])
                        if 0<=(now_m15-at).total_seconds()<=12 and now_m15<end:
                            samples[-1]={**samples[-1],"sampled_m15":sampled}
                    except (KeyError,ValueError,TypeError,OverflowError):
                        pass
                broker_m15=self.forming_m15
                if isinstance(broker_m15,dict):
                    try:
                        at=datetime.fromisoformat(broker_m15["collected_utc"])
                        end=datetime.fromisoformat(broker_m15["bar_close_utc"])
                        if 0<=(now_m15-at).total_seconds()<=35 and now_m15<end:
                            samples[-1]={**samples[-1],"forming_m15":broker_m15}
                    except (KeyError,ValueError,TypeError,OverflowError):
                        pass
            # When the /markets UTC timestamp is missing, a separate
            # CURRENT /prices M1 or M15 may still be available from THIS same
            # account/session. Preserve it as an explicitly UNVERIFIED
            # quote-status visual preview (fresh=False). Never add that
            # fallback as a genuine 5-second BID/ASK sample or a PAPER bar.
            if not quote.fresh and quote.status=="TRADEABLE":
                m1=self.forming_m1
                m15=self.forming_m15
                now_fallback=datetime.now(timezone.utc)
                attached={}
                for name,item,max_age in (
                        ("forming_m1",m1,12),("forming_m15",m15,35)):
                    if not isinstance(item,dict):
                        continue
                    try:
                        captured=datetime.fromisoformat(item["collected_utc"])
                        end=datetime.fromisoformat(item.get(
                            "close_utc",item.get("bar_close_utc")))
                        if 0<=(now_fallback-captured).total_seconds()<=max_age and now_fallback<end:
                            attached[name]=item
                    except (KeyError,ValueError,TypeError,OverflowError):
                        continue
                attached.update(self._recent_extra(now_fallback))
                if attached and float(quote.delay_seconds)==0.0:
                    selected=(attached.get("forming_m1") or
                              attached.get("forming_m15") or
                              attached.get("forming_m5") or
                              attached.get("forming_h1"))
                    bid=float(selected["bid"])
                    ask=float(selected["ask"])
                    samples=(list(self.samples)[-23:]+[{
                        "utc":now_fallback.isoformat(),"bid":bid,"ask":ask,
                        **attached,"fallback_only":True,
                        "source_delay_unknown":True}])
            using_prices_only=bool(samples and isinstance(samples[-1],dict)
                                   and samples[-1].get("fallback_only") is True)
            record={
                "epic":"US500","source":SOURCE,
                "bid":bid,"ask":ask,
                "mid":((bid+ask)/2 if using_prices_only else float(quote.mid)),
                "spread":((ask-bid) if using_prices_only else float(quote.spread)),
                "broker_status":str(quote.status)[:32],
                "broker_update_utc":(
                    quote.update_utc.astimezone(timezone.utc).isoformat()
                    if quote.update_utc is not None and not using_prices_only else None),
                "received_utc":(now_fallback.isoformat()
                    if using_prices_only else quote.received_utc.astimezone(timezone.utc).isoformat()),
                "delay_seconds":(9999.0 if using_prices_only else float(quote.delay_seconds)),
                "fresh":bool(quote.fresh),
                "samples":samples,
            }
            remote.upsert_live_quote(record)
            self.last_status=(
                "LIVE_QUOTE_SAVED" if quote.fresh else
                ("BROKER_M1_ONLY_UNVERIFIED_QUOTE"
                 if samples[-1].get("forming_m1") else
                 "BROKER_M15_ONLY_UNVERIFIED_QUOTE")
                if using_prices_only
                else "BROKER_NOT_FRESH")
            self.next_due=moment+(LIVE_INTERVAL if quote.status=="TRADEABLE"
                                  else CLOSED_INTERVAL)
            return self.last_status
        except (FeedError, RemoteError, ValueError, TypeError,
                OverflowError, AttributeError, OSError) as exc:
            # A missing migration, expired session, REST outage or 429 never
            # crashes the accounting worker and never reveals credentials.
            self.last_status="QUOTE_WAIT_"+type(exc).__name__
            # Normal transient REST read failures should be retried after
            # 30s, not leave the chart abandoned for 5 minutes. HTTP 429
            # uses longer backoff to respect broker limits; DB writes keep
            # the historical 5-minute recovery to avoid hammering RLS.
            if isinstance(exc,FeedError):
                wait=(RATE_LIMIT_RETRY_INTERVAL if "HTTP 429" in str(exc)
                      else FEED_RETRY_INTERVAL)
            else:
                wait=ERROR_INTERVAL
            self.next_due=moment+wait
            return self.last_status


def idle_quote_pulses(client,remote,epic,seconds,sampler, *,
                      monotonic=time.monotonic,sleep=time.sleep):
    """Collect on a ~5-second cadence while the minute scanner is sleeping.

    A slow minute scan, broker network latency, inactive API or scheduler
    jitter can skip pulses. Never advertise guaranteed ticks or 5s orders.
    """
    duration=max(0.,float(seconds))
    stop_at=monotonic()+duration
    while monotonic()<stop_at:
        if monotonic()>=sampler.next_due:
            sampler.pulse(client,remote,epic,monotonic=monotonic())
        remaining=stop_at-monotonic()
        if remaining<=0:
            break
        sleep(max(0.001,min(remaining,max(0.05,sampler.next_due-monotonic()))))
