from datetime import datetime, timezone, timedelta
from trader.news_radar import parse_rss,parse_bls_calendar,macro_blackout,allowed_url


def test_rss_whitelisted_https_and_no_js():
    xml='''<rss><channel><item><title>FOMC statement</title><link>https://www.federalreserve.gov/newsevents/pressreleases/a.htm</link><pubDate>Wed, 04 Nov 2026 18:00:00 GMT</pubDate></item>
    <item><title>BAD</title><link>javascript:alert(1)</link></item></channel></rss>'''
    rows=parse_rss(xml,"FED")
    assert len(rows)==1
    assert rows[0]["tytuł"]=="FOMC statement"
    assert not allowed_url("http://www.bls.gov/foo")
    assert not allowed_url("https://evil.com/page")


def test_calendar_parsing_and_precise_blackout():
    cal="""BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Consumer Price Index
DTSTART;TZID=America/New_York:20261105T083000
END:VEVENT
END:VCALENDAR"""
    events=parse_bls_calendar(cal)
    assert len(events)==1
    hit,text=macro_blackout(events,datetime(2026,11,5,13,25,tzinfo=timezone.utc))
    assert hit
    no,_=macro_blackout(events,datetime(2026,11,5,16,0,tzinfo=timezone.utc))
    assert not no


def test_missing_calendar_does_not_claim_clear():
    yes,msg=macro_blackout([])
    assert yes is False
    assert "Brak" in msg
