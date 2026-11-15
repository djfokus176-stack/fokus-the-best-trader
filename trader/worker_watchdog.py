"""Independent, READ-ONLY freshness check for the FOKU$ cloud worker.

Designed for an OPTIONAL GitHub Actions watchdog running separately from
the dedicated Northflank writer. The watchdog never scans Capital, places
orders, reads secrets into stdout, or modifies Supabase checkpoints.

A passing status confirms only a RECENT persisted checkpoint; it does NOT
validate broker quote quality, candle completeness or trading performance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .remote_checkpoint import RemoteCheckpoint, RemoteError

DEFAULT_MAX_AGE_MINUTES=8
ALLOWED_FUTURE_SECONDS=120


def _as_utc(value):
    if not isinstance(value,(str,datetime)):
        raise ValueError("Missing timestamp")
    if isinstance(value,datetime):
        stamp=value
    else:
        try:
            stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
        except ValueError:
            raise ValueError("Malformed timestamp") from None
    if stamp.tzinfo is None:
        raise ValueError("Naive timestamp")
    return stamp.astimezone(timezone.utc)


def check_checkpoint_freshness(version,payload,*,now=None,max_age_minutes=DEFAULT_MAX_AGE_MINUTES):
    """Pure fail-closed checker; does not imply a trading green light."""
    if type(version) is not int or version<0:
        raise ValueError("Invalid checkpoint version")
    if not isinstance(payload,dict):
        raise ValueError("Missing cloud payload")
    if (not isinstance(max_age_minutes,(float,int))
            or type(max_age_minutes) is bool or
            not 3<=float(max_age_minutes)<=60):
        raise ValueError("Invalid watchdog threshold")
    meta=payload.get("meta")
    if not isinstance(meta,dict):
        raise ValueError("Missing checkpoint meta")
    current=_as_utc(now) if now is not None else datetime.now(timezone.utc)
    last=_as_utc(meta.get("last_scan_utc"))
    age_s=(current-last).total_seconds()
    if age_s<-ALLOWED_FUTURE_SECONDS:
        status="CLOCK_SKEW"
    elif age_s>float(max_age_minutes)*60:
        status="STALE_CHECKPOINT"
    else:
        status="RECENT_CHECKPOINT"
    # Not a claim that broker is operational or a candle is valid.
    return {
        "status":status,
        "healthy":status=="RECENT_CHECKPOINT",
        "checkpoint_version":version,
        "last_scan_utc":last.isoformat(),
        "age_seconds":round(age_s,1),
        "market_data_validated":False,
        "paper_entries_authorized":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description="FOKU$ checkpoint watchdog (read-only)")
    parser.add_argument("--max-age-minutes",type=float,
                        default=DEFAULT_MAX_AGE_MINUTES)
    args=parser.parse_args(argv)
    try:
        remote=RemoteCheckpoint.from_env()
        version,payload=remote.fetch()
        result=check_checkpoint_freshness(version,payload,
                                          max_age_minutes=args.max_age_minutes)
    except (RemoteError,ValueError,TypeError,OverflowError,OSError) as exc:
        print("FOKUS_WATCHDOG=ERROR; "+
              "TYPE="+type(exc).__name__+
              "; no market/order operations; no credentials printed.",flush=True)
        return 2
    print("FOKUS_WATCHDOG="+result["status"]+
          " / VERSION="+str(result["checkpoint_version"])+
          " / AGE_SECONDS="+str(result["age_seconds"])+
          " / LAST_SCAN_UTC="+result["last_scan_utc"]+
          " / MARKET_DATA_VALIDATED=false / PAPER_ENTRIES_AUTHORIZED=false",
          flush=True)
    return 0 if result["healthy"] else 1


if __name__=="__main__":
    raise SystemExit(main())
