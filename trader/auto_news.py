"""Bounded, explicit automatic official-source market news refresh.

Headlines alone NEVER create trade orders. This helper is safe to run on
a Streamlit full rerun: no new HTTP requests until the respective interval.
Use injected fetchers in tests. Failures stay visible (no fabricated news).
"""
from __future__ import annotations
from datetime import datetime,timezone
import time

NEWS_PERIOD=15*60
CALENDAR_PERIOD=60*60


def refresh_news_state(state, *, now_mono=None, now_utc=None,
                       fetch_news=None, fetch_calendar=None, force=False):
    from .news_radar import fetch_headlines,fetch_bls_schedule
    at=time.monotonic() if now_mono is None else float(now_mono)
    utc=now_utc or datetime.now(timezone.utc)
    get_news=fetch_news or fetch_headlines
    get_calendar=fetch_calendar or fetch_bls_schedule
    news_due=force or "_auto_news_next" not in state or at>=state["_auto_news_next"]
    cal_due=force or "_auto_calendar_next" not in state or at>=state["_auto_calendar_next"]

    if news_due:
        state["_auto_news_next"]=at+NEWS_PERIOD   # no network retry storm
        state["_news_read_utc"]=utc.isoformat()
        try:
            records, errors=get_news()
            state["_news_feed_errors"]=dict(errors or {})
            # A failed request is not evidence that old news ceased to exist.
            if records:
                state["_headlines"]=records[:45]
                state["_news_last_success_utc"]=utc.isoformat()
            state["_news_status"]=("OK" if records and not errors else
                "PARTIAL" if records else "NO_DATA")
        except Exception as exc:
            state["_news_status"]="ERROR_"+type(exc).__name__
            state["_news_feed_errors"]={"auto_fetch":type(exc).__name__}
    if cal_due:
        state["_auto_calendar_next"]=at+CALENDAR_PERIOD
        state["_calendar_read_utc"]=utc.isoformat()
        try:
            events=get_calendar()
            if not events:
                raise ValueError("Brak wydarzeń w kalendarzu")
            state["_macro_calendar"]=events
            state["_calendar_error"]=None
            state["_calendar_success_utc"]=utc.isoformat()
            state["_calendar_source"]=getattr(events,"source","BLS_OFFICIAL_LIVE")
            state["_calendar_expires_utc"]=getattr(events,"expires_utc",None)
        except Exception as exc:
            # An older/stale calendar cannot certify that a new entry is safe.
            state["_macro_calendar"]=[]
            state["_calendar_source"]="UNAVAILABLE"
            state["_calendar_expires_utc"]=None
            state["_calendar_error"]=type(exc).__name__
    return {"news_refreshed":news_due,"calendar_refreshed":cal_due,
            "news_status":state.get("_news_status","NOT_RUN"),
            "calendar_ok":bool(state.get("_macro_calendar"))}


def calendar_is_current(state,now=None,max_age_seconds=60*60+120):
    if state.get("_calendar_error") or not state.get("_macro_calendar"):
        return False
    last=state.get("_calendar_success_utc")
    if not last:
        return False
    try:
        check=now or datetime.now(timezone.utc)
        age=(check-datetime.fromisoformat(last)).total_seconds()
        expiry=state.get("_calendar_expires_utc")
        if expiry:
            until=datetime.fromisoformat(expiry)
            if until.tzinfo is None or check>=until:
                return False
        return 0<=age<=max_age_seconds
    except (TypeError,ValueError):
        return False
