"""Official source parser tests; no real network and no fake all-clear."""
from datetime import datetime,timezone
import requests
from trader.macro_calendar_plus import parse_fomc_schedule,parse_bea_schedule,fetch_macro_watch

NOW=datetime(2026,11,8,20,0,tzinfo=timezone.utc)

FED="""<html><h3>2026 FOMC Meetings</h3>
<p>October</p><p>27-28</p><p>December</p><p>8-9*</p>
<h3>2025 FOMC Meetings</h3><p>January</p><p>28-29</p>
<h3>2027 FOMC Meetings</h3><p>January</p><p>26-27</p>
<p>March</p><p>16-17</p><p>Note: A two-day meeting</p></html>"""

BEA="""<html><h2>Release Schedule</h2><div>Year 2026</div><table>
<tr><th>Date and Time</th><th>Type</th><th>Release</th></tr>
<tr><td>November 18 10:00 AM</td><td>News</td><td>Outdoor recreation</td></tr>
<tr><td>November 25 8:30 AM</td><td>News</td>
<td>GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026</td></tr>
<tr><td>November 25 8:30 AM</td><td>News</td>
<td>Personal Income and Outlays, October 2026</td></tr>
</table></html>"""


def test_fed_december_9_fomc_and_january_2027():
    r=parse_fomc_schedule(FED,now=NOW)
    assert r[0]["data_utc"]=="2026-12-09T19:00:00+00:00"
    assert r[1]["data_utc"]=="2027-01-27T19:00:00+00:00"
    assert all(x["source"]=="FED_OFFICIAL_LIVE" for x in r)


def test_bea_release_dates_are_et_to_utc_and_only_important_rows():
    r=parse_bea_schedule(BEA,year=2026,now=NOW)
    assert len(r)==2
    assert all(x["data_utc"]=="2026-11-25T13:30:00+00:00" for x in r)
    assert all("Outdoor" not in x["wydarzenie"] for x in r)


def test_bea_wrong_year_is_not_silently_accepted():
    import pytest
    with pytest.raises(ValueError,match="year not verified"):
        parse_bea_schedule(BEA,year=2027,now=NOW)


def test_watch_reports_source_failures_and_never_claims_complete():
    class R:
        content=b""
        def __init__(self,url):
            self.url=url
            self.content=(FED if "federalreserve.gov" in url else BEA).encode()
        def raise_for_status(self):
            if "federalreserve.gov" in self.url:
                raise requests.HTTPError("403")
    r=fetch_macro_watch(get=lambda url,**kw:R(url),now=NOW)
    assert r["coverage"]=="PARTIAL_OFFICIAL_CORE"
    assert r["sources"]["FED_FOMC"]["status"]=="UNAVAILABLE"
    assert r["errors"]["FED_FOMC"]=="HTTPError"
    assert len(r["events"])==2
