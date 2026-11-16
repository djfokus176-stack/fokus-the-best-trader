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

SOURCE="Capital.com DEMO REST"
MAX_SAMPLES=24
LIVE_INTERVAL=5.0
CLOSED_INTERVAL=60.0
ERROR_INTERVAL=300.0
FORMING_INTERVAL=15.0  # broker /prices less often than MID quote
FORMING_ERROR_INTERVAL=60.0


class Quote5sSampler:
    def __init__(self):
        self.next_due=0.
        self.samples=deque(maxlen=MAX_SAMPLES)
        self.last_status="NOT_STARTED"
        self.forming_m1_next_due=0.
        self.forming_m1=None
        self.forming_m1_status="NOT_STARTED"

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
            quote=client.market_quote(epic)
            if quote.environment!="DEMO" or quote.epic!="US500":
                raise ValueError("Quote source mismatch")
            bid,ask=float(quote.bid),float(quote.ask)
            if not isfinite(bid) or not isfinite(ask) or bid<=0 or ask<bid:
                raise ValueError("Untrusted BID/ASK")
            # Only this same authenticated worker may request incomplete M1.
            # /prices is throttled to ~15s independently of 5s MID polls.
            # An error has no effect on the quote write or PAPER lifecycle.
            if (quote.fresh and quote.status=="TRADEABLE" and
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
                    self.forming_m1_next_due=moment+FORMING_ERROR_INTERVAL
            elif not quote.fresh or quote.status!="TRADEABLE":
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
            record={
                "epic":"US500","source":SOURCE,
                "bid":bid,"ask":ask,"mid":float(quote.mid),
                "spread":float(quote.spread),
                "broker_status":str(quote.status)[:32],
                "broker_update_utc":(
                    quote.update_utc.astimezone(timezone.utc).isoformat()
                    if quote.update_utc is not None else None),
                "received_utc":quote.received_utc.astimezone(timezone.utc).isoformat(),
                "delay_seconds":float(quote.delay_seconds),
                "fresh":bool(quote.fresh),
                "samples":samples,
            }
            remote.upsert_live_quote(record)
            self.last_status=("LIVE_QUOTE_SAVED" if quote.fresh
                              else "BROKER_NOT_FRESH")
            self.next_due=moment+(LIVE_INTERVAL if quote.status=="TRADEABLE"
                                  else CLOSED_INTERVAL)
            return self.last_status
        except (FeedError, RemoteError, ValueError, TypeError,
                OverflowError, AttributeError, OSError) as exc:
            # A missing migration, expired session, REST outage or 429 never
            # crashes the accounting worker and never reveals credentials.
            self.last_status="QUOTE_WAIT_"+type(exc).__name__
            self.next_due=moment+ERROR_INTERVAL
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
