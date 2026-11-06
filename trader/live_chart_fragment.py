"""Independent five-second live chart fragment (UI only, never a PAPER writer).

Main app rerenders + strategies are expensive and should run every ~60s.
This fragment renders one view, fetching only Capital /prices max=2
at the selected cadence. If API is broken/closed, it shows diagnostics,
NEVER draws a fabricated realtime candle.
"""
from __future__ import annotations

import copy
import time
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from .live_chart import show_quote_preview
from .market import FeedError


def preview_is_usable(preview, *, instrument, timeframe, environment,
                      last_closed, fetched_at, monotonic_now, max_age):
    """Refuse cross-market, old or fake 'live' data."""
    if not isinstance(preview,dict):
        return False
    if any(preview.get(key)!=val for key,val in (
        ("epic",instrument),("timeframe",timeframe),("environment",environment))):
        return False
    if fetched_at is None or not 0<=monotonic_now-fetched_at<=max_age:
        return False
    try:
        return (pd.Timestamp(preview["time"])>pd.Timestamp(last_closed)
                and all(pd.notna(preview[k]) for k in ("Open","High","Low","Close")))
    except (KeyError,ValueError,TypeError):
        return False


def live_chart_refresh_state(state, *, client, instrument, timeframe,
                             environment, period, tick, utc=None):
    """Read at most one new /prices snapshot when due, with explicit telemetry.

    One invalid response invalidates the visible live candle. Previous valid
    observations remain in diagnostics only; they do NOT count as live data.
    """
    utc=utc or datetime.now(timezone.utc)
    ident=(instrument,timeframe,environment)
    if state.get("_live_chart_scope")!=ident:
        for key in ("_live_chart_last_fetch","_live_chart_preview",
                    "_live_chart_success","_live_chart_error",
                    "_live_chart_unchanged","_live_chart_prev_close",
                    "_live_chart_prev_bar","_live_chart_attempts"):
            state.pop(key,None)
        state["_live_chart_scope"]=ident
    last=state.get("_live_chart_last_fetch")
    if last is not None and tick-last<max(5,int(period))-1:
        return False
    retry_until=state.get("_live_chart_backoff",0)
    if tick<retry_until:
        state["_live_chart_error"]="Ograniczenie zapytań API — ponawiam po przerwie (HTTP 429)."
        state["_live_chart_preview"]=None
        return False
    state["_live_chart_last_fetch"]=tick
    state["_live_chart_last_attempt_utc"]=utc.isoformat()
    state["_live_chart_attempts"]=int(state.get("_live_chart_attempts",0))+1
    try:
        snap=client.forming_candle(instrument,timeframe,now=utc)
        if snap.get("environment")!=environment or snap.get("epic")!=instrument:
            raise FeedError("Otrzymano świecę z innego rynku/środowiska")
        price=snap["Close"]
        bar_id=str(snap["time"])
        unchanged=(state.get("_live_chart_prev_close")==price
                   and state.get("_live_chart_prev_bar")==bar_id)
        state["_live_chart_unchanged"]=(int(state.get("_live_chart_unchanged",0))+1
                                         if unchanged else 0)
        state["_live_chart_prev_close"]=price
        state["_live_chart_prev_bar"]=bar_id
        state["_live_chart_preview"]=snap
        state["_live_chart_success"]=tick
        state["_live_chart_success_utc"]=utc.isoformat()
        state["_live_chart_error"]=None
    except (FeedError,ValueError,TypeError,KeyError) as exc:
        state["_live_chart_preview"]=None
        state["_live_chart_error"]=str(exc)[:200]
        if "429" in str(exc):
            state["_live_chart_backoff"]=tick+60
    return True


@st.fragment(run_every="5s")
def render_independent_live_chart(base_fig, closed_bars, instrument, timeframe,
                                  environment, source, auto_enabled, refresh_seconds,
                                  visible_bars=30, auto_zoom=True):
    """A fragment rerun updates just this chart, never the full Streamlit app."""
    from .market import PERIOD
    tick=time.monotonic()
    enabled=bool(
        auto_enabled and timeframe in PERIOD
        and source==f"Capital.com {environment} REST")
    client=st.session_state.get("_capital_client")
    if enabled and client is not None:
        live_chart_refresh_state(st.session_state,client=client,
            instrument=instrument,timeframe=timeframe,
            environment=environment,period=refresh_seconds,tick=tick)
    # Never show a cached current candle after an API failure or timeout.
    candidate=st.session_state.get("_live_chart_preview") if enabled else None
    forming=candidate if preview_is_usable(candidate,
        instrument=instrument,timeframe=timeframe,
        environment=environment,last_closed=closed_bars.index[-1],
        fetched_at=st.session_state.get("_live_chart_success"),
        monotonic_now=tick,max_age=max(12,refresh_seconds+8)) else None
    fig=copy.deepcopy(base_fig)
    show_quote_preview(fig,forming,bars=closed_bars,
        visible_bars=visible_bars,auto_zoom=auto_zoom)
    fig.update_layout(uirevision=f"fokus-live-{instrument}-{timeframe}")
    st.plotly_chart(fig,use_container_width=True,key="fokus-live-market-chart")
    if enabled:
        last=st.session_state.get("_live_chart_last_attempt_utc","BRAK")
        success=st.session_state.get("_live_chart_success_utc","BRAK")
        attempts=st.session_state.get("_live_chart_attempts",0)
        st.caption(f"📡 LIVE /prices | próby pobrania: {attempts} "
                   f"| ostatnia próba: {last} | ostatnie udane: {success}")
        if forming is not None:
            same=st.session_state.get("_live_chart_unchanged",0)
            st.caption(f"🕯️ Świeca w trakcie: MID {forming['Close']:.2f}, "
                       f"BID {forming['bid']:.2f}, ASK {forming['ask']:.2f}, "
                       f"w czasie UTC {forming['last_tick']}. "
                       + (f"API zwróciło tę samą cenę {same+1} razy."
                          if same else "Nowa cena lub nowa świeca.")
                       + " Podgląd bez wpływu na PAPER.")
        else:
            st.warning("⚠️ Brak aktualnej świecy z Capital.com. "
                +str(st.session_state.get("_live_chart_error")
                     or "Czekam na świeży odczyt /prices."))
    else:
        st.caption("Wykres statyczny (CSV lub wyłączony AUTO-SKAN). "
                   "Nie wykonuję nowych zapytań LIVE.")
