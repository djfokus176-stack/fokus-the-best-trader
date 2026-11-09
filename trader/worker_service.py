"""Opt-in, long-running DEMO PAPER process for a dedicated host.

There are NO broker order methods here. This wrapper refuses an unconfigured
deployment and enforces durable Supabase checkpointing; never silently falls
back to ephemeral local SQLite on a platform restarting containers.
"""
from __future__ import annotations
import os
import sys
from .remote_checkpoint import configured
from . import worker


def validated_worker_args(environ=None):
    env=os.environ if environ is None else environ
    if str(env.get("FOKUS_PAPER_WORKER_ENABLED","")).lower()!="true":
        raise ValueError("FOKUS_PAPER_WORKER_ENABLED must be true (opt-in).")
    if str(env.get("FOKUS_CANDLE_TIME_CONFIRMED","")).lower()!="open":
        raise ValueError("FOKUS_CANDLE_TIME_CONFIRMED must be open (verified).")
    # Durable state is a requirement for a background container.
    if not configured(env):
        raise ValueError("Missing FOKUS_SUPABASE_URL / FOKUS_SUPABASE_SECRET_KEY; durable state required.")
    required=("CAPITAL_API_KEY","CAPITAL_IDENTIFIER","CAPITAL_PASSWORD")
    if any(not env.get(k) for k in required):
        raise ValueError("Capital.com DEMO API credentials missing.")
    if str(env.get("CAPITAL_ENV","DEMO")).upper()!="DEMO":
        raise ValueError("Only Capital.com DEMO supported; LIVE disabled.")
    raw=str(env.get("FOKUS_PAPER_SCAN_INTERVAL_SECONDS","65"))
    try:
        interval=int(raw)
    except ValueError as exc:
        raise ValueError("Scan interval must be an integer.") from exc
    if not 60<=interval<=600:
        raise ValueError("Scan interval must be 60..600 seconds.")
    epic=str(env.get("CAPITAL_EPIC","US500")).strip()
    if not epic.replace("_","").isalnum():
        raise ValueError("Invalid instrument EPIC.")
    args=["--interval",str(interval),"--epic",epic,"--tf","MINUTE"]
    if str(env.get("FOKUS_PAPER_ALIGN_MINUTE","false")).lower() in ("true","1","yes"):
        args.append("--align-minute")
    return args


def main():
    try:
        args=validated_worker_args()
    except ValueError as exc:
        # Never log credentials or environment values.
        print("PAPER HOST: setup refused: "+str(exc),file=sys.stderr,flush=True)
        return 2
    print("PAPER HOST: DEMO READ-ONLY, durable remote checkpoint; scan loop active.",
          flush=True)
    worker.main(args)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
