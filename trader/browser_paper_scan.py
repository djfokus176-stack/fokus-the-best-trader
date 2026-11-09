"""Owner-triggered CLOUD PAPER scans from the authenticated Streamlit dashboard.

No GitHub token, cron-job.org, LIVE trading or reduced worker gates.
One browser session is NOT a persistent worker; existing checkpoint CAS
prevents overwriting a concurrent writer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

from .market import CapitalReadOnly
from .remote_checkpoint import RemoteCheckpoint
from .auto_strategy import AUTO_MODE
from .worker import remote_scan_once


def confirmed_clock_for_browser(secret_value, checkpoint_meta, *, epic="US500"):
    """Accept only an explicit owner 'open' or an earlier DEMO worker proof.

    Never interpret an arbitrary browser toggle as confirmation, and never
    trust CSV, LIVE, another EPIC or an absent cloud checkpoint.
    """
    if str(secret_value or "").strip().lower()=="open":
        return True
    meta=checkpoint_meta if isinstance(checkpoint_meta,dict) else {}
    return (meta.get("clock_confirmed_open") is True
            and meta.get("source")=="Capital.com DEMO REST"
            and meta.get("epic")==epic
            and meta.get("timeframe")=="MINUTE")


def run_browser_paper_scan(*, cloud_url, cloud_key, api_key, identifier,
                           password, environment, epic, clock_secret="",
                           max_spread=2.0, remote_cls=RemoteCheckpoint,
                           client_cls=CapitalReadOnly,
                           scanner=remote_scan_once):
    """One strict DEMO scan, preserving all broker, BLS and MTF validation.

    Fails closed when candle time is not previously verified. No real orders
    and no artificial success even if remote checkpoint is saved.
    """
    if str(environment).strip().upper()!="DEMO":
        raise ValueError("Tylko Capital.com DEMO; LIVE jest zablokowane.")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,40}",str(epic)):
        raise ValueError("Niepoprawny instrument/EPIC.")
    if not all((cloud_url,cloud_key,api_key,identifier,password)):
        raise ValueError("Brakuje kluczy Capital.com lub Supabase w Secrets/sesji.")
    remote=remote_cls(cloud_url,cloud_key)
    _,previous=remote.fetch()
    meta=previous.get("meta") or {}
    # Avoid launching two writers against the same checkpoint in normal use.
    # Supabase compare-and-swap remains the final concurrency safeguard.
    try:
        prior_stamp=datetime.fromisoformat(str(meta.get("last_scan_utc","")))
        age=(datetime.now(timezone.utc)-prior_stamp).total_seconds()
        if prior_stamp.tzinfo is not None and 0 <= age < 50:
            return {"saved":False,"result":"SKIP / ostatni worker zapisal dane mniej niz 50 sekund temu",
                    "clock_verified":bool(meta.get("clock_confirmed_open")),
                    "entry_gates_open":False,
                    "scanned_utc":datetime.now(timezone.utc).isoformat()}
    except (TypeError,ValueError,OverflowError):
        pass
    clock=confirmed_clock_for_browser(clock_secret,meta,epic=epic)
    client=client_cls(api_key,identifier,password,environment="DEMO")
    result=scanner(remote,client,epic,"MINUTE",AUTO_MODE,max_spread,
                   enable_setups=clock,strict_macro=True,
                   clock_confirmed_open=clock)
    if "CLOUD_CHECKPOINT_VERSION=" not in result:
        raise RuntimeError("Brak potwierdzenia zapisu skanu w Supabase.")
    return {"saved":True,"result":result,"clock_verified":clock,
            "entry_gates_open":"GATES=OK" in result,
            "scanned_utc":datetime.now(timezone.utc).isoformat()}
