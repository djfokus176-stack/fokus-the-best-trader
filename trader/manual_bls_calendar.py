"""Fail-closed, time-limited, human-verified BLS calendar backup for PAPER.

Read ONLY committed data/macro_calendar_manual.json and only after both
official BLS URLs have returned HTTP 403. This is NOT live BLS data.
Official sources and a real verification timestamp are mandatory.
Never modify the expiry, make up events, or bypass macro blackouts.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

MANUAL_SOURCE = "BLS_VERIFIED_MANUAL_NOT_LIVE"
EXPECTED_URLS = (
    "https://www.bls.gov/schedule/2026/11_sched_list.htm",
    "https://www.bls.gov/schedule/2026/12_sched_list.htm",
)
DEFAULT_CALENDAR_FILE = Path(__file__).resolve().parents[1] / "data" / "macro_calendar_manual.json"
HIGH_IMPACT = ("consumer price index", "producer price index", "employment situation")


class VerifiedManualBlsSchedule(list):
    def __init__(self, events, verified, expires):
        super().__init__(events)
        self.source = MANUAL_SOURCE
        self.source_url = "; ".join(EXPECTED_URLS)
        self.verified_date = verified.isoformat()
        self.expires_utc = expires.isoformat()


def load_verified_manual_bls(*, now=None, path=None):
    """Read a checked snapshot; absence, ambiguity or expiry always vetoes."""
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("BLS_MANUAL_TIMEZONE_UNVERIFIED")
    current = current.astimezone(timezone.utc)
    filepath = Path(path) if path is not None else DEFAULT_CALENDAR_FILE
    try:
        if filepath.stat().st_size > 100_000:
            raise ValueError("BLS_MANUAL_FILE_TOO_LARGE")
        doc = json.loads(filepath.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("BLS_MANUAL_FILE_MISSING_OR_INVALID") from exc
    if not isinstance(doc, dict) or doc.get("source") != MANUAL_SOURCE:
        raise ValueError("BLS_MANUAL_UNVERIFIED_SOURCE")
    if tuple(doc.get("source_urls") or ()) != EXPECTED_URLS:
        raise ValueError("BLS_MANUAL_UNVERIFIED_URLS")
    if doc.get("timezone") != "America/New_York":
        raise ValueError("BLS_MANUAL_UNKNOWN_TIMEZONE")
    try:
        verified = datetime.fromisoformat(doc["verified_at_utc"])
        expires = datetime.fromisoformat(doc["valid_until_utc"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("BLS_MANUAL_INVALID_EXPIRY") from exc
    if verified.tzinfo is None or expires.tzinfo is None:
        raise ValueError("BLS_MANUAL_INVALID_EXPIRY")
    verified = verified.astimezone(timezone.utc)
    expires = expires.astimezone(timezone.utc)
    if expires <= verified or expires - verified > timedelta(days=8):
        raise ValueError("BLS_MANUAL_EXPIRY_TOO_LONG")
    if current < verified or current >= expires:
        raise ValueError("BLS_MANUAL_VERIFICATION_EXPIRED")
    supplied = doc.get("events")
    if not isinstance(supplied, list) or not 12 <= len(supplied) <= 120:
        raise ValueError("BLS_MANUAL_INCOMPLETE_RELEASES")
    events, seen = [], set()
    for item in supplied:
        if not isinstance(item, dict):
            raise ValueError("BLS_MANUAL_INVALID_EVENT")
        try:
            title = item["wydarzenie"]
            stamp = datetime.fromisoformat(item["data_utc"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("BLS_MANUAL_INVALID_EVENT") from exc
        if (not isinstance(title,str) or not 5 <= len(title) <= 190
                or stamp.tzinfo is None):
            raise ValueError("BLS_MANUAL_INVALID_EVENT")
        stamp = stamp.astimezone(timezone.utc)
        if not datetime(2026,11,1,tzinfo=timezone.utc) <= stamp < datetime(2027,1,1,tzinfo=timezone.utc):
            raise ValueError("BLS_MANUAL_WRONG_SCHEDULE_PERIOD")
        if (stamp,title) in seen:
            raise ValueError("BLS_MANUAL_DUPLICATE")
        seen.add((stamp,title))
        events.append({"wydarzenie":title,"data_utc":stamp})
    months = {x["data_utc"].month for x in events}
    if months != {11,12}:
        raise ValueError("BLS_MANUAL_MISSING_MONTH")
    upcoming_major = [x for x in events
        if x["data_utc"] > current and any(term in x["wydarzenie"].lower()
                                           for term in HIGH_IMPACT)]
    if len(upcoming_major) < 2:
        raise ValueError("BLS_MANUAL_NO_UPCOMING_MAJOR_RELEASES")
    events.sort(key=lambda x:x["data_utc"])
    return VerifiedManualBlsSchedule(events, verified, expires)
