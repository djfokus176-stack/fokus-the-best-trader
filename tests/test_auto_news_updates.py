"""Automatic official news cache cadence, freshness and fail-closed behavior."""
from datetime import datetime,timedelta,timezone
from trader.auto_news import refresh_news_state,calendar_is_current

NOW=datetime(2026,11,6,12,0,tzinfo=timezone.utc)
EVENT=[{"wydarzenie":"CPI","data_utc":NOW+timedelta(hours=3)}]
HEAD=[{"źródło":"FED — press","data_utc":NOW.isoformat(),
       "tytuł":"Fed policy release","url":"https://www.federalreserve.gov/"}]


def test_auto_news_is_15_min_calendar_is_60_min_even_with_5_second_reruns():
    calls=[]
    def rss():
        calls.append("rss")
        return HEAD,{}
    def ics():
        calls.append("ics")
        return EVENT
    s={}
    out=refresh_news_state(s,now_mono=1000,now_utc=NOW,
                           fetch_news=rss,fetch_calendar=ics)
    assert out["news_status"]=="OK" and out["calendar_ok"]
    for tick in range(1005,1860,5):
        refresh_news_state(s,now_mono=tick,now_utc=NOW+timedelta(seconds=tick-1000),
                           fetch_news=rss,fetch_calendar=ics)
    assert calls==["rss","ics"]
    refresh_news_state(s,now_mono=1900,now_utc=NOW+timedelta(minutes=15),
                       fetch_news=rss,fetch_calendar=ics)
    assert calls==["rss","ics","rss"]
    refresh_news_state(s,now_mono=4600,now_utc=NOW+timedelta(minutes=60),
                       fetch_news=rss,fetch_calendar=ics)
    assert calls.count("ics")==2
    assert calendar_is_current(s,NOW+timedelta(minutes=60))
    assert not calendar_is_current(s,NOW+timedelta(minutes=122))


def test_missing_or_broken_calendar_never_looks_like_clear_market():
    s={}
    refresh_news_state(s,now_mono=0,now_utc=NOW,
        fetch_news=lambda:([],{"BLS":"HTTP403"}),
        fetch_calendar=lambda: [])
    assert not calendar_is_current(s,NOW)
    assert s["_calendar_error"]=="ValueError"
    assert s["_news_status"]=="NO_DATA"
    def fail():raise OSError("network down")
    refresh_news_state(s,now_mono=4000,now_utc=NOW+timedelta(seconds=4000),
                       fetch_news=fail,fetch_calendar=fail)
    assert s["_news_status"]=="ERROR_OSError"
    assert s["_calendar_error"]=="OSError"
    assert not calendar_is_current(s,NOW+timedelta(seconds=4000))


def test_refresh_can_force_without_waiting_for_expiry():
    state={}
    calls=[]
    fn=lambda:(calls.append(1) or HEAD, {})
    refresh_news_state(state,now_mono=0,now_utc=NOW,
                       fetch_news=fn,fetch_calendar=lambda:EVENT)
    refresh_news_state(state,now_mono=1,now_utc=NOW,
                       fetch_news=fn,fetch_calendar=lambda:EVENT,force=True)
    assert len(calls)==2
