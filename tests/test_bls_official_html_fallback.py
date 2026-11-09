"""Official BLS .ics 403 -> own current/next monthly HTML, fail closed."""
from datetime import datetime,timezone
import requests
import pytest
from trader.news_radar import (
    fetch_bls_schedule,fetch_bls_schedule_html,parse_bls_month_html,
    macro_blackout,
)

NOW=datetime(2026,11,6,17,0,tzinfo=timezone.utc)
NOV="""<!DOCTYPE html><html><head><title>BLS Economic News Schedule</title></head>
<body><h1>November 2026</h1><table><thead><tr>
<th>Date</th><th>Time</th><th>Release</th></tr></thead><tbody>
<tr><td>Tuesday, November 03, 2026</td><td>10:00 AM</td>
<td>Job Openings and Labor Turnover Survey for September 2026</td></tr>
<tr><td>Tuesday, November 10, 2026</td><td>08:30 AM</td>
<td><a href="/schedule/news_release/cpi.htm">Consumer Price Index</a> for October 2026</td></tr>
<tr><td>Friday, November 13, 2026</td><td>08:30 AM</td>
<td>Producer Price Index for October 2026</td></tr>
<tr><td>Thursday, November 26, 2026</td><td> </td>
<td>Thanksgiving Day</td></tr></tbody></table></body></html>"""
DEC="""<html><table><tr><th>Date</th><th>Time</th><th>Release</th></tr>
<tr><td>Friday, December 04, 2026</td><td>08:30 AM</td>
<td>Employment Situation for November 2026</td></tr>
<tr><td>Thursday, December 10, 2026</td><td>08:30 AM</td>
<td>Consumer Price Index for November 2026</td></tr></table></html>"""


class Response:
    def __init__(self,status,body,url):
        self.status_code=status
        self.content=body.encode()
        self.url=url
    def raise_for_status(self):
        if self.status_code>=400:
            raise requests.HTTPError(f"HTTP {self.status_code}",response=self)


def mocked_get(url,**kwargs):
    if url.endswith("/bls.ics"):return Response(403,"forbidden",url)
    if url.endswith("/11_sched_list.htm"):return Response(200,NOV,url)
    if url.endswith("/12_sched_list.htm"):return Response(200,DEC,url)
    raise ValueError("unexpected URL "+url)


def test_monthly_schedule_has_correct_new_york_dst_and_ignores_holidays():
    ev=parse_bls_month_html(NOV,year=2026,month=11)
    assert len(ev)==3
    cpi=next(e for e in ev if e["wydarzenie"].startswith("Consumer Price"))
    assert cpi["data_utc"].isoformat()=="2026-11-10T13:30:00+00:00"
    assert parse_bls_month_html(DEC,year=2026,month=12)[0]["data_utc"].hour==13


def test_official_html_recovery_when_ics_is_forbidden():
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        return mocked_get(url,**kwargs)
    events=fetch_bls_schedule(get=get,now=NOW)
    assert len(calls)==3
    assert calls[0].endswith("/bls.ics")
    assert calls[1].startswith("https://www.bls.gov/schedule/2026/11_")
    assert calls[2].startswith("https://www.bls.gov/schedule/2026/12_")
    assert len(events)==4
    is_blackout,detail=macro_blackout(events,
       datetime(2026,11,10,13,20,tzinfo=timezone.utc))
    assert is_blackout and "Consumer Price Index" in detail


def test_http403_on_both_official_sources_uses_verified_temporary_snapshot():
    def get(url,**kwargs):return Response(403,"Forbidden",url)
    events=fetch_bls_schedule(get=get,now=NOW)
    assert events.source=="BLS_VERIFIED_SNAPSHOT_NOT_LIVE"
    assert events.expires_utc=="2026-11-10T00:00:00+00:00"
    assert len(events)>=3


def test_http403_after_old_snapshot_expiry_requires_checked_manual_expiry():
    def get(url,**kwargs):return Response(403,"Forbidden",url)
    cal=fetch_bls_schedule(get=get,now=datetime(2026,11,10,0,0,tzinfo=timezone.utc))
    assert cal.source=="BLS_VERIFIED_MANUAL_NOT_LIVE"
    with pytest.raises(ValueError,match="BLS_MANUAL_VERIFICATION_EXPIRED"):
        fetch_bls_schedule(get=get,now=datetime(2026,11,17,0,0,tzinfo=timezone.utc))


def test_html_without_valid_calendar_does_not_enable_paper():
    def get(url,**kwargs):
        if url.endswith(".ics"):return Response(403,"Forbidden",url)
        return Response(200,"<html><div>calendar access denied</div></html>",url)
    with pytest.raises(ValueError,match="nie zawiera rozpoznanych dat"):
        fetch_bls_schedule(get=get,now=NOW)


def test_html_cannot_use_mismatched_month_or_past_only_as_safe():
    assert len(parse_bls_month_html(DEC,year=2026,month=12))==2
    with pytest.raises(ValueError):
        parse_bls_month_html(NOV,year=2026,month=12)


def test_fallback_requires_two_major_releases_and_two_months():
    def get(url,**kwargs):
        if url.endswith(".ics"):return Response(403,"Forbidden",url)
        if url.endswith("/11_sched_list.htm"):
            return Response(200,NOV.replace("Producer Price Index","Irrelevant Report")
                .replace("Consumer Price Index","Irrelevant Other"),url)
        return Response(200,DEC.replace("Employment Situation","Irrelevant Data")
             .replace("Consumer Price Index","Irrelevant Extra"),url)
    with pytest.raises(ValueError,match="Niepełny aktualny kalendarz"):
        fetch_bls_schedule(get=get,now=NOW)
