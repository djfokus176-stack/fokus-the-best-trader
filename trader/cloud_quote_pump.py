"""Independent best-effort ~5s DEMO quote sampler within ONE PAPER worker.

The M1 scanner can take longer than 60s. Historically, quote sampling happened
ONLY during its idle sleep, so the 5s cache could remain stale for tens of
minutes while PAPER checkpoint and M15 candles continued to advance.

This background THREAD uses the current Northflank worker's EXISTING Capital
DEMO login tokens with its OWN requests.Session, never POST /session, never
POST /positions, and never shares requests.Session across threads. Its own
RemoteCheckpoint HTTP session writes ONLY the dedicated focus_live_quotes
cache. The main PAPER CAS checkpoint remains single-writer.

This does NOT guarantee exchange ticks, a 5-second SLA, or profitable signals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Lock, Thread
import time

import requests

from .market import CapitalReadOnly, FeedError
from .cloud_scalp_quotes import Quote5sSampler
from .remote_checkpoint import RemoteCheckpoint


class BorrowedDemoQuoteClient(CapitalReadOnly):
    """Read-only Capital REST adapter borrowing the scanner's live CST/token.

    No second Capital *login*; no shared HTTP session. Scanner refreshes
    tokens on its ordinary authenticated calls. The observer must never
    refresh or create sessions by itself.
    """

    def __init__(self, scanner):
        if getattr(scanner, "environment", None) != "DEMO":
            raise ValueError("Quote pump requires Capital.com DEMO")
        self._scanner = scanner
        self.environment = "DEMO"
        self.base_url = scanner.base_url
        self.session = requests.Session()

    def headers(self):
        parent = self._scanner
        cst = getattr(parent, "cst", None)
        token = getattr(parent, "token", None)
        api_key = getattr(parent, "api_key", None)
        started = float(getattr(parent, "session_started", 0))
        age = time.time() - started
        if (not cst or not token or not api_key or not 0 <= age < 595):
            raise FeedError("PAPER_BROKER_SESSION_NOT_READY")
        return {"X-CAP-API-KEY": api_key, "CST": cst,
                "X-SECURITY-TOKEN": token}

    def close(self):
        self.session.close()


class CloudQuotePump:
    """Non-overlapping dedicated quote writer; no 2nd PAPER process."""

    def __init__(self, scanner, remote, epic="US500", *,
                 sampler=None, clock=time.monotonic):
        if epic != "US500":
            raise ValueError("Only US500 DEMO supported for quote pump")
        self.client = BorrowedDemoQuoteClient(scanner)
        self.remote = remote
        self.epic = epic
        self.sampler = sampler if sampler is not None else Quote5sSampler()
        self.clock = clock
        self._stop = Event()
        self._lock = Lock()
        self._thread = None
        self._state = {
            "mode": "BACKGROUND_SAME_CAPITAL_LOGIN",
            "status": "STARTING",
            "last_attempt_utc": None,
            "last_write_utc": None,
            "last_fresh_utc": None,
            "attempts": 0,
            "trade_permission": "WAIT",
        }

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def _note(self, status, *, attempted=False, written=False, fresh=False):
        stamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._state["status"] = str(status)[:48]
            if attempted:
                self._state["last_attempt_utc"] = stamp
                self._state["attempts"] += 1
            if written:
                self._state["last_write_utc"] = stamp
            if fresh:
                self._state["last_fresh_utc"] = stamp

    def tick(self):
        """One deterministic iteration; scan can run independently."""
        parent = self.client._scanner
        if (not getattr(parent, "cst", None)
                or not getattr(parent, "token", None)):
            self._note("WAIT_BROKER_SESSION")
            return "WAIT_BROKER_SESSION"
        if self.clock() < self.sampler.next_due:
            return None
        try:
            status = self.sampler.pulse(
                self.client, self.remote, self.epic, monotonic=self.clock())
        except Exception as exc:
            # Never print REST body, credentials, request URLs or raw error.
            status = "QUOTE_PUMP_ERROR_" + type(exc).__name__
            self.sampler.next_due = self.clock() + 60
        if status is not None:
            wrote = status in ("LIVE_QUOTE_SAVED", "BROKER_NOT_FRESH",
                               "BROKER_M15_ONLY_UNVERIFIED_QUOTE")
            self._note(status, attempted=True, written=wrote,
                       fresh=status == "LIVE_QUOTE_SAVED")
        return status

    def _loop(self):
        while not self._stop.is_set():
            self.tick()
            # Short periodic wake-ups detect changes of token availability.
            # Actual broker read interval remains controlled by sampler.
            self._stop.wait(1.0)

    def start(self):
        if self._thread is not None:
            raise ValueError("Quote pump already started")
        self._thread = Thread(target=self._loop,
                              name="fokus-quote-pump", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout=3.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        # Do not close a session while a long-running poll is still using it.
        if self._thread is None or not self._thread.is_alive():
            self.client.close()
            http = getattr(self.remote, "http", None)
            if http is not None and hasattr(http, "close"):
                http.close()


def build_quote_pump(scanner, *, epic="US500", sampler=None):
    """Dedicated Supabase HTTP session; never shares main PAPER session."""
    return CloudQuotePump(scanner, RemoteCheckpoint.from_env(), epic,
                          sampler=sampler)
