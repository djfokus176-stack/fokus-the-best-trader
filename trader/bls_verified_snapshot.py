"""Very short-lived, publicly verified BLS release schedule fallback.

PAPER/DEMO research only. This is NOT a live data feed. Use only when BOTH
official BLS endpoints reject GitHub Actions and this curated source is
inside its explicit expiry window. Never roll expiry forward automatically.

Initially verified on 2026-11-06 and rechecked on 2026-11-08 against:
https://www.bls.gov/schedule/2026/11_sched_list.htm
November section last modified by BLS on 2026-11-03.
"""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SOURCE_URL="https://www.bls.gov/schedule/2026/"
SOURCE_LAST_MODIFIED="2026-11-03"
RESEARCH_VERIFIED_DATE="2026-11-08"
VALID_UNTIL_UTC=datetime(2026,11,10,0,0,tzinfo=timezone.utc)

# All times are from official BLS schedule, in US/Eastern local time.
# No fabricated dates; all entries for November 2026 verified on the
# published November schedule (rechecked 2026-11-08). This is a temporary
# emergency snapshot through Monday only, NOT a live calendar.
# Include enough events to assess blackout.
_RELEASES=(
    (6,8,30,"Employment Situation for October 2026"),
    (10,8,30,"Consumer Price Index for October 2026"),
    (10,8,30,"Real Earnings for October 2026"),
    (13,8,30,"Producer Price Index for October 2026"),
    (17,8,30,"U.S. Import and Export Price Indexes for October 2026"),
    (20,10,0,"State Employment and Unemployment (Monthly) for October 2026"),
)


class VerifiedBlsSchedule(list):
    """Preserve source metadata for explicit logging in worker."""
    def __init__(self, events):
        super().__init__(events)
        self.source="BLS_VERIFIED_SNAPSHOT_NOT_LIVE"
        self.source_url=SOURCE_URL
        self.verified_date=RESEARCH_VERIFIED_DATE
        self.expires_utc=VALID_UNTIL_UTC.isoformat()


def verified_schedule(*, now=None):
    """Fail closed when the checked source is expired, or before verification.

    No implicit extension, trading in REAL mode, or bypassing other gates.
    """
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("BLS snapshot requires timezone-aware UTC")
    now=now.astimezone(timezone.utc)
    if now<datetime(2026,11,6,0,0,tzinfo=timezone.utc) or now>=VALID_UNTIL_UTC:
        raise ValueError("BLS_VERIFIED_SNAPSHOT_EXPIRED")
    et=ZoneInfo("America/New_York")
    releases=[]
    for day,hour,minute,title in _RELEASES:
        stamp=datetime(2026,11,day,hour,minute,tzinfo=et).astimezone(timezone.utc)
        releases.append({"wydarzenie":title,"data_utc":stamp})
    major_future=[r for r in releases
                  if r["data_utc"]>now and any(w in r["wydarzenie"].lower()
                  for w in ("consumer price","producer price","employment situation"))]
    if len(major_future)<2:
        raise ValueError("BLS_VERIFIED_SNAPSHOT_INCOMPLETE")
    return VerifiedBlsSchedule(releases)
