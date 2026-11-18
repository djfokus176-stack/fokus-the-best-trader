"""Read-only cloud terminal from worker's persisted M15 and checkpoint.

This module NEVER authenticates against Capital.com directly. The service's
permanent, private credentials belong to the Northflank worker. Streamlit
requires only its own server-side Supabase read credentials to show results.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .remote_checkpoint import RemoteCheckpoint, RemoteError
from .paper_method_labels import method_attribution
from .paper_display import annotate_open_paper, annotate_paper_history
from .cloud_m15_live_overlay import (cloud_quote_overlay,m15_cache_due,
                                     closed_m15_lag)
from .cloud_forming_m1 import assess_cloud_forming_m1
from .cloud_moving_m15 import assess_moving_m15
from .cloud_chart_timeframes import (
    closed_chart_frame,source_resolution,sampled_chart_bar)
from .cloud_ws_prices import assess_streaming_candle
from .cloud_signal_radar import worker_signal_radar
from .cloud_paper_audio import cloud_paper_audio_events, advance_cloud_audio
from .paper_sounds import alert_audio, SOUND_EVENTS
from .cloud_candle_clock import render_candle_clock
from .cloud_paper_visibility import cloud_paper_visibility, cloud_chart_gaps
from .cloud_paper_test_status import status_for_owner
from .raw_paper_chart import annotate_raw_forward, rows_for_journal
from .periodic_archive_ui import render_periodic_archive_ui


def _parse_utc(value):
    if not value:
        return None
    try:
        ts=pd.Timestamp(value)
        if pd.isna(ts) or ts.tzinfo is None:
            return None
        return ts.tz_convert("UTC")
    except (ValueError,TypeError,OverflowError):
        return None


def cloud_terminal_summary(version, payload, frame, *, now=None):
    """Pure summary. A checkpoint is not proof of valid broker quotes."""
    if not isinstance(payload,dict) or not isinstance(frame,pd.DataFrame):
        raise ValueError("Nieprawidlowy cloud checkpoint lub OHLC.")
    meta=payload.get("meta") or {}
    if not isinstance(meta,dict):
        raise ValueError("Nieprawidlowe cloud meta.")
    if meta.get("epic") not in (None,"US500"):
        raise ValueError("Inny instrument w cloud checkpoint.")
    source=meta.get("source","BRAK")
    if source not in ("Capital.com DEMO REST","BRAK"):
        raise ValueError("Oczekiwano danych Capital.com DEMO REST.")
    if not frame.empty:
        needed=("Open","High","Low","Close","Spread")
        if (not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None
                or frame.index.has_duplicates or not frame.index.is_monotonic_increasing
                or not set(needed).issubset(frame.columns)):
            raise ValueError("Cloud M15 wymaga unikalnych UTC i OHLC+Spread.")
        vals=frame.loc[:,needed].apply(pd.to_numeric,errors="coerce")
        if (vals.isna().any().any() or not vals.map(
                lambda x: pd.notna(x) and float("-inf")<x<float("inf")
                ).all().all()):
            raise ValueError("Niefinitywne OHLC/Spread w archiwum.")
        if (vals["Low"].le(0).any() or
                vals["High"].lt(vals[["Open","Low","Close"]].max(axis=1)).any() or
                vals["Low"].gt(vals[["Open","High","Close"]].min(axis=1)).any()
                or vals["Spread"].lt(0).any()):
            raise ValueError("Niespojny OHLC/Spread w archiwum.")
    current=_parse_utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if current is None:
        raise ValueError("Nieprawidlowy czas inspekcji.")
    last_scan=_parse_utc(meta.get("last_scan_utc"))
    last_m15=frame.index[-1].tz_convert("UTC") if len(frame) else None
    age=(round((current-last_scan).total_seconds()/60,1)
         if last_scan is not None else None)
    return {
        "version":version,
        "last_scan_utc":last_scan.isoformat() if last_scan is not None else None,
        "last_m15_utc":last_m15.isoformat() if last_m15 is not None else None,
        "age_minutes":age,
        "worker_summary":str(meta.get("last_scan_summary","BRAK"))[:300],
        "bars":len(frame),
        "backfill_enabled":meta.get("candle_backfill_enabled") is True,
        "cloud_online_confirmed":bool(age is not None and 0<=age<=10),
        "trade_permission":"WAIT",
        "no_direct_capital_login":True,
    }


def cloud_paper_decision(meta, *, now=None):
    """Read-only interpretation of the worker's committed scan, never an order.

    No inference from chart prices. A direction is shown only if the worker
    explicitly logged it; even LONG/SHORT is NOT an opened PAPER position.
    """
    raw=str(meta.get("last_scan_summary") or "")
    current=_parse_utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    stamp=_parse_utc(meta.get("last_scan_utc"))
    age=(current-stamp).total_seconds() if stamp is not None else None
    fresh=bool(age is not None and 0<=age<=180)
    action=re.search(r"\s/\s(LONG|SHORT|WAIT)\s/",raw)
    queued=re.search(r"(?:^|\s/\s)QUEUE=(YES|NO)(?:\s/|$)",raw)
    gates=re.search(r"(?:^|\s/\s)GATES=([A-Z0-9_,]+)(?:\s/|$)",raw)
    method=re.search(r"(?:^|\s/\s)CANDIDATE_METHOD=([^/]{1,100})",raw)
    candidate=action.group(1) if action else "UNKNOWN"
    queue=queued.group(1) if queued else "UNKNOWN"
    blocking=gates.group(1) if gates else "UNKNOWN"
    method_name=method.group(1).strip() if method else "BRAK"
    if not fresh:
        headline="BRAK BIEŻĄCEJ DECYZJI — ostatni zapis historyczny"
    elif candidate=="WAIT":
        headline="WAIT — bot nie zatwierdził nowego wejścia PAPER"
    elif candidate in ("LONG","SHORT") and queue=="YES":
        headline=candidate+" — setup PAPER zakolejkowany, nie oznacza OPEN"
    elif candidate in ("LONG","SHORT"):
        headline=candidate+" — kandydat, BEZ wejścia PAPER"
    else:
        headline="BRAK POTWIERDZONEJ DECYZJI PAPER"
    return {
        "headline":headline,"candidate":candidate,"queue":queue,
        "gates":blocking,"method":method_name,"fresh":fresh,
        "scan_utc":stamp.isoformat() if stamp is not None else "BRAK",
        "age_seconds":age,
        "is_trade_instruction":False,
    }


def cloud_chart_view_range(frame, choice, *, moving=None, visible_count=None,
                           focus_utc=None):
    """Zoom around *real* recent candles; no synthetic price or candle data."""
    if choice not in ("M1","M2","M5","M15","H1"):
        raise ValueError("Unsupported UI chart timeframe")
    if frame.empty and moving is None:
        return None
    seconds={"M1":60,"M2":120,"M5":300,"M15":900,"H1":3600}[choice]
    defaults={"M1":65,"M2":60,"M5":55,"M15":45,"H1":45}
    count=defaults[choice] if visible_count is None else int(visible_count)
    if not 15<=count<=300:
        raise ValueError("Invalid CLOUD chart zoom")
    last=(_parse_utc(moving["at"]) if moving is not None
          else frame.index[-1])
    if last is None:
        return None
    if len(frame) and focus_utc is not None:
        focus=_parse_utc(focus_utc)
        if focus is not None and frame.index[0]<=focus<=frame.index[-1]:
            # Center the selected *recorded* trade using available real OHLC
            # index labels. No historical candles are invented to fill gaps.
            index=frame.index
            center=max(0,min(len(index)-1,int(index.searchsorted(focus))-1))
            left_idx=max(0,center-count//2)
            right_idx=min(len(index)-1,left_idx+count-1)
            left_idx=max(0,right_idx-count+1)
            return [index[left_idx]-pd.Timedelta(seconds=seconds*.5),
                    index[right_idx]+pd.Timedelta(seconds=seconds*1.5)]
    if len(frame):
        left=frame.index[max(0,len(frame)-count)]
    else:
        left=last-pd.Timedelta(seconds=seconds*35)
    if left>=last:
        left=last-pd.Timedelta(seconds=seconds*2)
    return [left,last+pd.Timedelta(seconds=seconds*2)]

def render_cloud_paper_voice(remote, *, url):
    """Owner-browser audio from CLOUD checkpoint, independent of chart cache.

    Works only while the page is open and the owner has opted in via the
    existing sidebar. No browser broker session and no additional trade scan.
    """
    st.markdown("##### 🔊 GŁOSY CLOUD PAPER — OTWARCIA I ZAMKNIĘCIA")
    enabled=bool(st.session_state.get("paper_audio_enabled",False))
    if not enabled:
        st.session_state["_fokus_cloud_voice_was_enabled"]=False
        st.session_state.pop("_fokus_cloud_voice_pending",None)
        st.session_state.pop("_fokus_cloud_voice_cursor",None)
        st.caption("Dźwięki wyłączone. W lewym panelu włącz "
                   "🔔 DŹWIĘKI PAPER, wybierz Głos ElevenLabs i użyj "
                   "PRZETESTUJ DŹWIĘK. Historia nie będzie odgrywana.")
        return
    if not st.session_state.get("_fokus_cloud_voice_was_enabled"):
        st.session_state["_fokus_cloud_voice_was_enabled"]=True
        st.session_state["_fokus_cloud_voice_cursor"]=None
        st.session_state["_fokus_cloud_voice_pending"]=[]
        st.session_state.pop("_fokus_cloud_voice_cache",None)
    now=pd.Timestamp.now(tz="UTC")
    cache=st.session_state.get("_fokus_cloud_voice_cache")
    if (not isinstance(cache,dict) or cache.get("url")!=url
            or _parse_utc(cache.get("read_utc")) is None
            or (now-_parse_utc(cache["read_utc"])).total_seconds()>=8):
        try:
            _,fresh_payload=remote.fetch()
        except (RemoteError,ValueError,TypeError,KeyError,OverflowError,OSError):
            st.warning("Głos CLOUD: chwilowo brak odczytu rejestru zdarzeń. "
                       "Nie odtwarzam niepotwierdzonych alertów.")
            return
        cache={"url":url,"read_utc":now.isoformat(),"payload":fresh_payload}
        st.session_state["_fokus_cloud_voice_cache"]=cache
    events=cloud_paper_audio_events(cache["payload"],now=now.isoformat())
    cursor=st.session_state.get("_fokus_cloud_voice_cursor")
    pending=st.session_state.get("_fokus_cloud_voice_pending") or []
    cursor,pending,audio_event=advance_cloud_audio(
        events,cursor,pending,enabled=True)
    st.session_state["_fokus_cloud_voice_cursor"]=cursor
    st.session_state["_fokus_cloud_voice_pending"]=pending
    st.caption("Nasłuch aktywny • wyłącznie nowe zdarzenia OPEN / "
               "CLOSED_TP / CLOSED_SL / TIMEOUT z PAPER v3. "
               "Nie nadaję alarmu otwarcia dla OBSERWUJ LONG/SHORT. "
               "Odczyt rejestru co ~10 s; Chrome może blokować autoplay.")
    # A PENDING line with SL and TP may look like an open trade on the
    # chart. Spell out why it has no OPEN voice, rather than playing a
    # deceptive alert for a pending setup.
    tables=(cache["payload"].get("tables") or {})
    positions=tables.get("paper_positions_v3")
    if isinstance(positions,list) and any(
            isinstance(pos,dict) and pos.get("status")=="PENDING"
            and pos.get("epic")=="US500"
            and pos.get("source")=="Capital.com DEMO REST"
            for pos in positions):
        st.info("⏳ PAPER PENDING: poziomy wejścia / SL / TP są wyłącznie "
                "planem. Głos LONG/SHORT zabrzmi dopiero po nowym "
                "potwierdzonym zdarzeniu PAPER_OPEN w archiwum.")
    if audio_event is not None:
        st.session_state["_fokus_cloud_voice_last"]=audio_event
        st.success("🔔 "+SOUND_EVENTS[audio_event["kind"]]+
                   " • "+audio_event["side"]+
                   " • PAPER, nie rzeczywista transakcja.")
    last=st.session_state.get("_fokus_cloud_voice_last")
    if last is not None and last.get("kind") in SOUND_EVENTS:
        voice=st.session_state.get("paper_audio_mode")=="Głos ElevenLabs (nagrania MP3)"
        content,mime,used=alert_audio(last["kind"],last["side"],
                                     voice_enabled=voice)
        st.audio(content,format=mime,autoplay=audio_event is not None)
        if used!="VOICE" and voice:
            st.caption("Brak odpowiedniego nagrania MP3: odtwarzam ton zastępczy.")
        st.caption("Jeśli nic nie słychać, kliknij ▶ w odtwarzaczu powyżej "
                   "i zezwól Chrome na dźwięk tej witryny. "
                   "Alert jest jednorazowy; przy kolejnych odświeżeniach "
                   "można go odtworzyć ręcznie.")
    elif cursor=="__EMPTY__":
        st.caption("Nasłuch uzbrojony. Czekam na pierwsze NOWE "
                   "zdarzenie PAPER (nie odtwarzam historii).")
    else:
        st.caption("Nasłuch uzbrojony. Wcześniejsze pozycje celowo pominięte; "
                   "kolejny nowy OPEN lub CLOSE wywoła dźwięk.")


def cloud_paper_positions(payload, frame):
    """Read-only rows from one checkpoint; never infer unrecorded signals.

    The cloud M15 chart may show M1/M5/H1 actual PAPER markers on its time
    axis. Exclude off-chart events to prevent Plotly from re-scaling across
    months of old ledger history.
    """
    tables=payload.get("tables") if isinstance(payload,dict) else None
    raw=tables.get("paper_positions_v3") if isinstance(tables,dict) else None
    if not isinstance(raw,list):
        return [], []
    valid=[]
    for pos in raw:
        if (not isinstance(pos,dict) or
                pos.get("source")!="Capital.com DEMO REST" or
                pos.get("epic")!="US500" or
                pos.get("side") not in ("LONG","SHORT") or
                pos.get("status") not in
                    ("PENDING","OPEN","CLOSED_SL","CLOSED_TP",
                     "CLOSED_TIMEOUT","INVALIDATED")):
            continue
        valid.append(pos)
    valid.sort(key=lambda p: str(p.get("created_utc") or ""),reverse=True)
    if frame.empty:
        return valid[:25], []
    start,end=frame.index[0],frame.index[-1]+pd.Timedelta(minutes=15)
    chart_rows=[]
    for pos in valid[:80]:
        opened=_parse_utc(pos.get("opened_utc"))
        closed=_parse_utc(pos.get("closed_utc"))
        if ((opened is not None and start<=opened<=end) or
                (closed is not None and start<=closed<=end)):
            chart_rows.append(pos)
    return valid[:25],chart_rows


@st.fragment(run_every="5s")
def render_cloud_terminal(secret_fn,default_tf="MINUTE"):
    """Owner-only M15 archive + live REST BID/ASK overlay; no Capital auth.

    Fragment updates the PRICE OVERLAY about every five seconds only while
    browser is open. Closed M15 and checkpoint load about every 60 seconds.
    Worker clocks, AUTO and PAPER remain completely independent.
    """
    st.markdown("#### ☁️ US500 — STREAMING WS • M1 / M2 / M5 / M15 / H1")
    labels={"MINUTE":"M1","MINUTE_5":"M5",
            "MINUTE_15":"M15","HOUR":"H1"}
    choices=("M1","M2","M5","M15","H1")
    # Match sidebar on its CHANGE; keep standalone M2 possible in the
    # chart-only selector between sidebar changes. Never mutate AUTO TF.
    if st.session_state.get("_cloud_chart_sidebar_tf")!=default_tf:
        st.session_state["_cloud_chart_sidebar_tf"]=default_tf
        st.session_state["cloud_price_chart_interval"]=labels.get(
            default_tf,"M1")
    choice=st.selectbox(
        "Interwał WYKRESU CLOUD (nie zmienia strategii AUTO/PAPER)",
        options=choices,index=choices.index(labels.get(default_tf,"M1")),
        key="cloud_price_chart_interval")
    zoom=st.select_slider(
        "🔍 ZOOM WYKRESU — ostatnie świece (tylko wygląd)",
        options=[20,30,45,65,90,180,300],value=45,
        key="cloud_price_chart_zoom_"+choice)
    chart_mode=st.selectbox(
        "🎯 CO POKAZAĆ NA WYKRESIE? (zapisane wejścia z historii)",
        options=["BIEŻĄCE ŚWIECE","OSTATNIE OPEN RAW","OSTATNIE CLOSE RAW",
                 "OSTATNIE OPEN PAPER v3"],
        key="cloud_price_chart_focus_"+choice,
        help="Wybierz historyczną transakcję, żeby wykres przesunął się na "
             "prawdziwą świecę otwarcia/zamknięcia. To nie tworzy zleceń.")
    resolution=source_resolution(choice)
    render_candle_clock(choice)
    st.caption(
        "Zamknięte świece wybranego interwału = zielone/czerwone. "
        "M2 powstaje WYŁĄCZNIE z dwóch kompletnych, kolejnych M1. "
        "OSTATNIA świeca w trakcie = strumień Capital WebSocket, "
        "z rzeczywistymi BID/ASK i OHLC, jeśli są dostępne. "
        "Dla natywnej OHLC BID knoty przedstawiają BID; dla M2 i "
        "awaryjnych danych z quote — tylko zaobserwowane MID. "
        "Panel odświeża Supabase co ~5 s, NIE wysyła zapytań REST "
        "do brokera. Bez fikcyjnych świec, bez wpływu na PAPER. "
        "Streamlit NIE loguje się do brokera, tylko czyta chmurę.")
    url=secret_fn("FOKUS_SUPABASE_URL")
    key=secret_fn("FOKUS_SUPABASE_SECRET_KEY")
    if not url or not key:
        st.warning("Brak prywatnych Secrets Supabase w Streamlit. "
                   "Nie oznacza to awarii niezależnego workera Northflank.")
        return
    try:
        remote=RemoteCheckpoint(url,key)
        cache=st.session_state.get("_fokus_cloud_chart_cache_v3")
        if (not isinstance(cache,dict) or cache.get("url")!=url
                or cache.get("resolution")!=resolution
                or cache.get("choice")!=choice
                or m15_cache_due(
                    cache,ttl_seconds=35 if choice in ("M1","M2") else 60)):
            version,payload=remote.fetch()
            # 1500 closed M1 bars give context for overnight positions,
            # without requesting tick history or changing the worker.
            # More-than-300 chart zoom must have >300 REAL archived candles.
            candle_limit=1500 if resolution=="MINUTE" else 520
            original=remote.fetch_candles("US500",resolution,limit=candle_limit)
            frame=closed_chart_frame(original,choice)
            audit=cloud_terminal_summary(version,payload,frame)
            # Per-BROWSER session cache only; never put credentials in it.
            st.session_state["_fokus_cloud_chart_cache_v3"]={
                "url":url,"resolution":resolution,"choice":choice,
                "version":version,"payload":payload,"frame":frame,
                "fetched_utc":pd.Timestamp.now(tz="UTC").isoformat()}
        else:
            version,payload,frame=(cache["version"],cache["payload"],cache["frame"])
            audit=cloud_terminal_summary(version,payload,frame)
    except (RemoteError,ValueError,TypeError,KeyError,OverflowError,OSError):
        st.session_state.pop("_fokus_cloud_chart_cache_v3",None)
        st.error("Nie udało się odczytać checkpointu lub archiwum "+choice+". "
                 "Nie przedstawiam niezweryfikowanego cache jako aktualnego. "
                 "Sprawdź STATUS/API i Northflank.")
        return
    # Price polling is intentionally independent of a healthy M15 archive.
    # A broken/stale quote must NEVER erase the historical chart or be
    # drawn as if the price were tradable.
    try:
        quote_record=remote.fetch_live_quote("US500")
        quote_now=pd.Timestamp.now(tz="UTC")
        overlay=cloud_quote_overlay(quote_record,now=quote_now)
        forming=assess_cloud_forming_m1(quote_record,now=quote_now)
        last_closed=frame.index[-1] if not frame.empty else None
        latest_sample=(quote_record or {}).get("samples") or []
        ws_transport=(bool(latest_sample) and
            isinstance(latest_sample[-1],dict) and
            latest_sample[-1].get("transport")=="CAPITAL_WS_V1")
        if ws_transport:
            moving_chart=assess_streaming_candle(
                quote_record,choice,now=quote_now,last_closed_utc=last_closed)
        elif choice=="M15":
            moving_chart=assess_moving_m15(
                quote_record,now=quote_now,last_closed_utc=last_closed)
        else:
            moving_chart=sampled_chart_bar(
                quote_record,choice,now=quote_now,last_closed_utc=last_closed)
    except (RemoteError,ValueError,TypeError,KeyError,OverflowError,OSError):
        overlay={"visible":False,"broker_status":"UNKNOWN","age_seconds":None,
                 "reason":"Nie udało się odczytać aktualnego BID/ASK.",
                 "points":[]}
        forming={"visible":False,
                 "reason":"BRAK_ODCZYTU_NIEPELNEJ_M1","preview":None}
        moving_chart={"visible":False,
                    "reason":"BŁĄD_ODCZYTU_WYKRESU","bar":None,
                    "quote_verified":False,
                    "missing_extremes_possible":True}
    x,y,z=st.columns(3)
    x.metric("Checkpoint",str(audit["version"]))
    y.metric("Zapisane "+choice,str(audit["bars"]))
    z.metric("Wiek checkpointu",str(audit["age_minutes"])+" min"
             if audit["age_minutes"] is not None else "BRAK")
    # Show status of the independent PAPER TEST near the very TOP of TERMINAL.
    # A browser user no longer has to scroll past charts and brokerage DEMO
    # instructions to learn whether the worker has actually opened anything.
    owner_test=status_for_owner(payload)
    st.markdown("##### 🧪 AUTOMATYCZNY PAPER TEST — CZY BOT COŚ OTWORZYŁ?")
    summary=(owner_test["title"]+" | "+
             "SETUPY="+str(owner_test["started"] if owner_test["started"] is not None else "BRAK")+
             " | OPEN="+str(owner_test["opened"] if owner_test["opened"] is not None else "BRAK")+
             " | CLOSED="+str(owner_test["closed"] if owner_test["closed"] is not None else "BRAK")+
             " | ostatnia M1 UTC="+str(owner_test["last_candle_utc"] or "BRAK"))
    if owner_test["kind"]=="OPEN":
        st.success(summary)
    elif owner_test["kind"] in ("NO_APPROVAL","STALE","NOT_STARTED"):
        st.warning(summary)
    else:
        st.info(summary)
    st.caption("Dlaczego teraz nie ma nowego wejścia: "+owner_test["detail"]+
               ". TEST to wirtualne wejścia zapisane przez worker, "
               "NIE Capital.com DEMO i NIE wczesny znacznik OBSERWUJ.")
    raw_trial=payload.get("raw_m1_forward_paper_report") or {}
    st.markdown("##### ⚡ AUTO RAW PAPER — TESTOWE WEJŚCIA LONG/SHORT BEZ KIERUNKOWEGO VETO MTF")
    if raw_trial.get("status")=="FORWARD_ONLY_RAW_M1_SIMULATION":
        ra,rb,rc,rd=st.columns(4)
        ra.metric("RAW: zatwierdzone",raw_trial.get("started",0))
        rb.metric("RAW: OPEN",raw_trial.get("opened",0))
        rc.metric("RAW: CLOSED",raw_trial.get("closed",0))
        rd.metric("RAW: wynik netto",str(raw_trial.get("pnl_pts",0))+" pkt")
        # Historical total OPEN is NOT the number of simultaneous positions.
        in_market=int(raw_trial.get("active_open_now",0) or 0)
        last_at=_parse_utc(raw_trial.get("last_documented_open_utc"))
        last_side=str(raw_trial.get("last_documented_open_side") or "BRAK")
        last_local=(last_at.tz_convert("Europe/Warsaw").strftime(
            "%d.%m.%Y %H:%M") if last_at is not None else "BRAK")
        if in_market:
            st.success("🟢 AKTYWNA TERAZ: "+str(in_market)+
                       " wirtualna pozycja RAW. Ostatnie potwierdzone OPEN: "+
                       last_side+" o "+last_local+" (Polska).")
        else:
            st.warning("⚪ AKTYWNE TERAZ: 0 | ostatnie UDOKUMENTOWANE OPEN: "+
                       last_side+" o "+last_local+" (Polska). "+
                       "Historyczny licznik OPEN="+str(raw_trial.get("opened",0))+
                       " nie oznacza aktywnego handlu w tej chwili.")
        gaps_open=int(raw_trial.get("invalidated_after_open",0) or 0)
        gaps_pending=int(raw_trial.get("invalidated_before_open",0) or 0)
        unknown=int(raw_trial.get("unreconciled_historical_open",0) or 0)
        if gaps_open or gaps_pending:
            st.warning("⚠️ RAW: unieważnione po OPEN: "+str(gaps_open)+
                       " | unieważnione przed OPEN: "+str(gaps_pending)+
                       ". Przyczyny i godziny są w dzienniku niżej. "+
                       "Brak wiarygodnego wyjścia = brak P&L, nigdy zero.")
        if unknown:
            st.error("⚠️ RAW: "+str(unknown)+
                     " wcześniejszych otwarć nie ma udokumentowanego "+
                     "zamknięcia ani historii unieważnienia. Mogły zniknąć "+
                     "przez luki M1 w starszym kodzie. Nie wliczam ich "+
                     "do wyniku, nie udaję, że zakończyły się TP/SL.")
        rp=raw_trial.get("active")
        if isinstance(rp,dict):
            direction=str(rp.get("side","?"))
            state=str(rp.get("status","?"))
            txt=("🧪 RAW "+state+" "+direction+" | sygnał UTC "+
                 str(rp.get("setup_utc"))+" | cena planu "+
                 str(rp.get("entry_signal"))+" | SL "+str(rp.get("stop"))+
                 " | TP "+str(rp.get("target"))+
                 " | strategie "+", ".join(rp.get("methods") or [])+
                 " | OPEN potwierdzony dopiero na kolejnej zamkniętej świecy.")
            if state=="OPEN":
                st.success(txt)
            else:
                st.info(txt+" PENDING nie oznacza wejścia.")
        else:
            why=str(raw_trial.get("last_reason","BRAK"))
            explanation=(
                "Przerwa w kolejności świec M1 — nie wolno "
                "odtwarzać wejścia ani wyniku z niepełnych danych."
                if why=="LUKA_SWIEC_RAW_BEZ_FILL" else
                "Nie ma nowego surowego sygnału LONG/SHORT."
                if why=="BRAK_SUROWEGO_LONG_SHORT" else
                "Limit dzienny: maksymalnie 12 testowych setupów RAW."
                if why=="MAX_12_RAW_DZIENNIE" else
                "Oczekiwanie 2 min po ostatnim zamknięciu/utracie danych."
                if why=="COOLDOWN_RAW_2_MIN" else why
            )
            st.info("RAW: obecnie BRAK otwartej pozycji. "+
                    "Dlaczego nie ma wejścia: "+explanation+
                    " | ostatnia zamknięta M1 UTC "+
                    str(raw_trial.get("last_candle_utc","BRAK")))
        st.caption("RAW = prawdziwy surowy sygnał strategii M1, "+
                   "osobna symulacja forward, bez kierunkowego filtra MTF. "+
                   "Wymagane globalne GATES, świeże dane, spread i limity. "+
                   "Nie jest to prawdziwe zlecenie; wyników nie mieszam "+
                   "z oryginalnym AUTO PAPER.")
    else:
        st.warning("RAW PAPER TEST nie ma jeszcze raportu z pracującego "+
                   "workera M1 AUTO. Dopóki nie zapisze nowego checkpointu, "+
                   "nie deklaruję otwarcia żadnej transakcji.")
    # Keep the real candle chart and trade journal ABOVE strategy radar.
    # They are populated below using the same verified cloud checkpoint;
    # the placeholders preserve their visual location in Streamlit.
    live_chart_slot=st.empty()
    raw_journal_slot=st.empty()
    # Audit is also in the top viewport, after live chart/journal placeholders.
    # The worker has already computed and stored it in Supabase; the browser
    # never creates artificial entries or alters a trading decision.
    render_periodic_archive_ui(payload)
    pump=payload.get("meta",{}).get("quote_pump")
    if isinstance(pump,dict) and pump.get("mode") in (
            "BACKGROUND_SAME_CAPITAL_LOGIN","CAPITAL_WS_STREAMING"):
        last_try=_parse_utc(pump.get("last_attempt_utc"))
        last_write=_parse_utc(pump.get("last_write_utc"))
        last_fresh=_parse_utc(pump.get("last_fresh_utc"))
        now_diag=pd.Timestamp.now(tz="UTC")
        def _minutes(ts):
            return (f"{(now_diag-ts).total_seconds()/60:.1f} min"
                    if ts is not None else "NIGDY")
        health=str(pump.get("status","UNKNOWN"))[:48]
        is_ws=pump.get("mode")=="CAPITAL_WS_STREAMING"
        message=(f"📡 {'WEBSOCKET' if is_ws else 'KOLEKTOR REST'} | "
                 f"stan: {health} | "
                 f"próby: {pump.get('attempts',0)} | "
                 f"ostatnia próba: {_minutes(last_try)} | "
                 f"ostatni zapis: {_minutes(last_write)} | "
                 f"ostatnia ŚWIEŻA cena: {_minutes(last_fresh)}. "
                 "Ten sam login DEMO; dane osobne od PAPER.")
        if (health in ("LIVE_QUOTE_SAVED","WS_QUOTE_SAVED") and
                last_fresh is not None and
                0 <= (now_diag-last_fresh).total_seconds()<=30):
            st.success(message)
        else:
            st.warning(message)
    else:
        st.warning("📡 BRAK POTWIERDZENIA AKTYWNEGO TRANSPORTU "
                   "Capital WebSocket / REST w checkpointcie. "
                   "Możliwe, że Northflank nadal korzysta ze starego "
                   "commita, wyłączono FOKUS_SCALP_5S_ENABLED albo "
                   "checkpoint zapisuje inny proces.")
    if audit["cloud_online_confirmed"]:
        st.caption("Checkpoint zapisano niedawno. Nie dowodzi to otwarcia "
                   "rynku ani poprawności każdej świecy "+choice+".")
    else:
        st.warning("Checkpoint nie jest świeży lub jego daty nie potwierdzono. "
                   "Sprawdź Northflank; nie twierdzę, że worker teraz działa.")
    if overlay["visible"]:
        transport=("WebSocket" if ws_transport else "REST") if (
            "ws_transport" in locals()) else "REST"
        st.metric("🟡 BIEŻĄCY MID BID/ASK ("+transport+")",
                  f'{overlay["mid"]:.2f} pkt')
        st.caption(
            f'BID {overlay["bid"]:.2f} | ASK {overlay["ask"]:.2f} | '
            f'Spread {overlay["spread"]:.2f} pkt | '
            f'Broker {overlay["broker_status"]} | '
            f'Wiek odczytu {overlay["age_seconds"]} s. '
            "To obserwacje dostawcy, NIE cena zrealizowanej transakcji.")
    else:
        st.warning("⚪ BRAK AKTUALNEJ CENY 5S: "+overlay["reason"]+
                   " | Broker: "+str(overlay["broker_status"])+
                   " | Wiek: "+str(overlay["age_seconds"])+
                   " s. Ostatnie "+choice+" to wyłącznie historia.")
    if forming["visible"] and not (ws_transport if
            "ws_transport" in locals() else False):
        m=forming["preview"]
        st.caption(
            f'🕯️ CLOUD /prices M1 W TRAKCIE — MID: {m["close"]:.2f} | '
            f'OHLC: {m["open"]:.2f} / {m["high"]:.2f} / '
            f'{m["low"]:.2f} / {m["close"]:.2f} | '
            f'Wiek pobrania: {m["age_seconds"]} s | '
            f'Otwarta: {m["open_utc"]}, koniec minuty: {m["close_utc"]}. '
            'To nieukończony bar, bez wpływu na PAPER.')
    elif not (ws_transport if "ws_transport" in locals() else False):
        st.caption('🕯️ Podgląd M1 /prices: '+forming["reason"]+
                   '. Nie ma drugiego logowania Capital w Streamlit; '
                   'dane wymagają odświeżonego workera Northflank.')
    if moving_chart["visible"]:
        live=moving_chart["bar"]
        live_message=(
            "🕯️ "+choice+" W TRAKCIE — RUCHOME KNOTY (NIE SYGNAŁ) | "
            + ("TYLKO aktualna M1 /prices (częściowy "+choice+")"
               if moving_chart.get("broker_m1_only") else
               "MID z obserwacji WebSocket"
               if moving_chart.get("basis")=="MID_OBSERVED"
               else "natywna OHLC BID WebSocket"
               if moving_chart.get("basis")=="BID"
               else "MID z próbek REST"
               if moving_chart["missing_extremes_possible"]
               else "nieukończona OHLC brokera /prices")
            + f' | O={live["open"]:.2f}, H={live["high"]:.2f}, '
              f'L={live["low"]:.2f}, C={live["close"]:.2f}'
            + f' | aktualizacja {live["capture_age_seconds"]} s temu.')
        if moving_chart.get("quote_verified") is False:
            st.warning(live_message+
                       " | UWAGA: brak zweryfikowanej ceny handlowej; "
                       "to wyłącznie aktualny podgląd, "
                       "NIE potwierdzenie możliwości handlu.")
        else:
            st.success(live_message)
        if moving_chart["missing_extremes_possible"]:
            st.caption(
                "Uwaga: HIGH/LOW obejmują tylko dostępny fragment "
                "interwału, od "+str(live.get("first_vendor_utc","BRAK"))+
                ". Nie muszą odzwierciedlać ekstremów całej "+choice+
                ". Bez wpływu na SL/TP ani AUTO.")
    else:
        st.warning(
            "🟠 "+choice+" W TRAKCIE NIEAKTYWNA: "+moving_chart["reason"]+
            ". Wykres pokazuje wtedy wyłącznie ZAMKNIĘTE świece; "
            "nie tworzę sztucznych knotów. Sprawdź stan "
            "NIEZALEŻNEGO KOLEKTORA 5S powyżej.")
    st.caption("Wersja podglądu: WICK-M15-v1 / CLOUD-TF-v1 / WS-STREAM-v1 | "
               "odświeżenie przeglądarki ~5s | "
               "nie jest to zlecenie ani świeca dla strategii.")
    st.caption("Ostatni zapis skanera UTC: "+
               str(audit["last_scan_utc"] or "BRAK")+
               " | Ostatnia "+choice+" w archiwum UTC: "+
               str(audit["last_m15_utc"] or "BRAK"))
    st.caption("Ostatnia informacja workera (nie tej przeglądarki): "+
               audit["worker_summary"])
    # Only the signed worker checkpoint may tell us what it analysed.
    # This DISPLAY does not issue a LONG/SHORT recommendation or order.
    decision=cloud_paper_decision(payload.get("meta") or {})
    st.markdown("##### 🎯 CO WSKAZUJE BOT — OSTATNIA DECYZJA PAPER")
    details=("Metoda: "+decision["method"]+
             " | GATES="+decision["gates"]+
             " | QUEUE="+decision["queue"]+
             " | skan UTC: "+decision["scan_utc"])
    if not decision["fresh"]:
        st.warning(decision["headline"]+" | "+details)
    elif decision["candidate"]=="WAIT":
        st.info(decision["headline"]+" | "+details)
    elif decision["queue"]=="YES":
        st.success(decision["headline"]+" | "+details)
    else:
        st.warning(decision["headline"]+" | "+details)
    st.caption("LONG/SHORT to wynik analizy, a nie zlecenie. OPEN i CLOSED "
               "pokazuję tylko z zapisanego rejestru PAPER.")
    render_cloud_paper_voice(remote,url=url)
    # Real broker DEMO is a third distinct lane: broker-confirmed virtual
    # positions, not the existing OHLC PAPER simulation and never LIVE cash.
    st.markdown("##### 🏦 CAPITAL.COM DEMO — POZYCJE NA KONCIE TESTOWYM")
    demo=payload.get("capital_demo_broker")
    if not isinstance(demo,dict):
        st.caption("Wysyłanie zleceń na Capital.com DEMO jest domyślnie "
                   "WYŁĄCZONE. Wewnętrzny PAPER TEST działa oddzielnie. "
                   "Aby uzbroić zlecenia BROKERA DEMO, właściciel musi "
                   "najpierw ustawić w Northflank trzy wartości: "
                   "FOKUS_DEMO_BROKER_MODE=DEMO_ONLY_CONFIRMED, "
                   "FOKUS_DEMO_BROKER_ACCOUNT_ID (identyfikator konta DEMO) "
                   "oraz FOKUS_DEMO_BROKER_SIZE (wielkość pozycji). "
                   "Nie wpisuj numeru konta ani kluczy API w czacie.")
    else:
        state=str(demo.get("status","UNKNOWN"))
        if state=="ACCEPTED":
            st.success("🏦 BROKER DEMO: zlecenie potwierdzone przez "
                       "Capital.com — pozycja na koncie WIRTUALNYM.")
        elif state in ("ATTEMPTED","UNRESOLVED","CONFIRM_PENDING"):
            st.warning("🏦 BROKER DEMO: "+state+
                       ". Status wymaga rozliczenia po stronie brokera. "
                       "Nie wolno ponawiać zlecenia automatycznie.")
        else:
            st.info("🏦 BROKER DEMO: "+state+
                    ". Sam setup PAPER/OBSERWUJ nie oznacza zlecenia.")
        st.caption("Ostatni sygnał DEMO UTC: "+
                   str(demo.get("last_setup_utc") or "BRAK")+
                   " | kierunek: "+str(demo.get("side") or "BRAK")+
                   " | wielkość: "+str(demo.get("size") or "BRAK")+
                   " | stop: "+str(demo.get("stop") or "BRAK")+
                   " | target: "+str(demo.get("target") or "BRAK")+
                   ". U brokerów SL/TP mogą zostać zrealizowane inaczej "
                   "niż w symulacji świec. Zlecenia LIVE są zabronione.")
    st.caption("Ważne: CAPITAL.COM DEMO = zlecenia brokera za WIRTUALNE "
               "środki po zatwierdzeniu, PAPER = lokalna symulacja. "
               "Nigdy nie interpretuj statusu ATTEMPTED jako OPEN.")
    # Explicit second lane: REAL tracked, but SIMULATED test fills; never
    # mutate the production v3 position ledger or claim broker execution.
    st.markdown("##### 🧪 PAPER TEST — WCZEŚNIEJSZE LONG / SHORT (OSOBNY REJESTR)")
    trial=payload.get("momentum_paper_test_report") or {}
    if trial.get("status")!="FORWARD_PAPER_TEST_NOT_LIVE":
        st.warning("Nowy test LONG/SHORT jeszcze nie rozpoczął skanowania "
                   "na Northflank. Sprawdź aktualny commit i checkpoint workera. "
                   "Nie wyświetlam fikcyjnych wejść.")
    else:
        ca,cb,cc,cd=st.columns(4)
        ca.metric("TEST: zatwierdzone setupy",trial.get("started",0))
        cb.metric("TEST: otwarcia OPEN",trial.get("opened",0))
        cc.metric("TEST: zamknięte",trial.get("closed",0))
        cd.metric("TEST: wynik po kosztach",
                  str(trial.get("pnl_pts",0))+" pkt")
        pos=trial.get("active")
        if isinstance(pos,dict) and pos.get("status") in ("PENDING","OPEN"):
            status=pos.get("status")
            title=("TEST "+status+" "+str(pos.get("side","WAIT")))
            details=(" • sygnał UTC "+str(pos.get("setup_utc"))+
                     " • STOP "+str(pos.get("stop"))+
                     " • CEL "+str(pos.get("target"))+
                     " • M1 momentum "+str(pos.get("score"))+"/6"+
                     " • EMA: "+str(pos.get("confirmation")))
            if status=="OPEN":
                st.success("🧪 "+title+details)
            else:
                st.info("🧪 "+title+details+
                        ". PENDING = jeszcze nie otwarta pozycja TEST.")
        else:
            st.caption("🧪 TEST: brak aktywnej pozycji. Ostatnia ocena: "+
                       str(trial.get("last_reason","BRAK"))+
                       " | ostatnia zamknięta M1 UTC "+
                       str(trial.get("last_candle_utc","BRAK"))+
                       ". Ostatni kandydat: "+
                       str(trial.get("last_candidate","WAIT")))
        st.caption("Próby z M1 momentum co najmniej 5/6, zgodnej obserwacji "
                   "EMA od 2/3, M5 zgodny, M15 nieprzeciwny; "
                   "SL/TP oparte na ATR, RR po spreadzie i poślizgu. "
                   "Globalne bramki bezpieczeństwa pozostają. "
                   "Zamknięte: trafność "+
                   str(trial.get("win_rate_pct")
                       if trial.get("win_rate_pct") is not None else "BRAK")+
                   "% • unieważnione "+str(trial.get("invalidated",0))+
                   " • luki M1 "+str(trial.get("gaps",0))+
                   ". Test działa na workerze bez otwartej przeglądarki.")
        st.caption("UWAGA: to **oddzielny eksperyment PAPER**, "
                   "NIE zatwierdzony sygnał AUTO 3/3 i NIE prawdziwe "
                   "zlecenie Capital.com. Głosy otwarcia/TP/SL "
                   "głównego PAPER nie są dźwiękami tego testu.")
        if trial.get("recent"):
            with st.expander("🧪 Ostatnie rozliczone LONG/SHORT — wyłącznie PAPER TEST"):
                st.dataframe(pd.DataFrame(trial["recent"]),
                             hide_index=True,use_container_width=True)
    st.markdown("##### 📡 RADAR 6 STRATEGII — DLACZEGO LONG / SHORT / WAIT?")
    radar=worker_signal_radar(payload)
    if not radar["current"]:
        st.warning("Nie ma zweryfikowanego audytu SZÓSTKI z bieżącego skanu: "
                   +radar["reason"]+". Nie pokazuję starych kierunków "
                   "jako aktualnych sygnałów.")
    else:
        a,b,c,d=st.columns(4)
        a.metric("LONG po MTF",str(radar["mtf_long"])+"/6")
        b.metric("SHORT po MTF",str(radar["mtf_short"])+"/6")
        c.metric("Odrzucone przez MTF",str(radar["veto"]))
        watch=radar["watch"]
        d.metric("Obserwacja M1 (NIE PAPER)",
                 watch["side"]+((" "+str(watch["score"])+"/6")
                                if watch["score"] is not None else ""))
        if radar["conflict"]:
            st.warning("Konflikt surowych LONG i SHORT. "
                       "Nie łączę sprzecznych kandydatów.")
        if watch["side"] in ("LONG","SHORT"):
            st.info("👀 OBSERWUJ "+watch["side"]+" — "+
                    watch["reason"]+" Nie jest to wejście PAPER, "
                    "poziom transakcji ani potwierdzenie MTF.")
        else:
            st.caption("👀 Wczesna obserwacja M1: "+watch["reason"])
        st.caption("Surowe setupy: LONG "+str(radar["raw_long"])+
                   ", SHORT "+str(radar["raw_short"])+
                   ". Ocena zakończonej świecy UTC: "+radar["candle_utc"]+
                   ". Etapy 0/3–3/3 oznaczają spełnione warunki, "
                   "NIE prawdopodobieństwo zysku.")
        watch_2of3=[r for r in radar["rows"]
                    if r["Etap"]=="2/3" and r["Obserwuj"] in ("LONG","SHORT")
                    and r["Setup OHLC"]=="WAIT"]
        if watch_2of3:
            report=", ".join(r["Strategia"]+" "+r["Obserwuj"]
                             for r in watch_2of3)
            st.info("🔬 ETAP 2/3 — WCZESNA OBSERWACJA (SHADOW): "+report+
                    ". To kontekst i wstępny układ, BEZ kompletnego "
                    "setupu i potwierdzenia MTF/bramek. "
                    "Nie otwieram PAPER wyłącznie na 2/3. "
                    "Weryfikacja skuteczności wymaga nowych danych.")
        else:
            st.caption("Etap 2/3: brak obecnie wstępnych układów "
                       "z jednostronnym kierunkiem. "
                       "Próg PAPER pozostaje 3/3.")
        st.dataframe(pd.DataFrame(radar["rows"]),
                     hide_index=True,use_container_width=True)
        st.caption("Kolumna Brakuje oznacza pierwszy niezrealizowany etap. "
                   "Nawet zatwierdzony setup wymaga GATES=OK, "
                   "QUEUE=YES i późniejszego faktycznego PAPER OPEN. "
                   "Radar nie wysyła zleceń i nie zmienia strategii.")
        ab=(payload.get("last_vote_audit") or {}).get("obstacle_ab") or {}
        if (ab.get("status")=="OK" and ab.get("source")=="Capital.com DEMO REST"
                and ab.get("epic")=="US500"
                and ab.get("candle_utc")==radar["candle_utc"]):
            st.markdown("##### 🔬 FILTR OPORU: STARY vs POTWIERDZONE SWINGI (SHADOW)")
            st.caption("Dwie strategie EMA na TEJ SAMEJ zamkniętej świecy i "
                       "tym samym spreadzie. Wariant SWING nie wpływa na "
                       "wejścia PAPER; przejście MTF też nie zastępuje "
                       "bramek bezpieczeństwa.")
            records=[]
            for v in ab.get("rows",[]):
                if not isinstance(v,dict):
                    continue
                records.append({
                    "Strategia":v.get("strategy"),
                    "Obecny filtr":v.get("legacy"),
                    "Powód obecnego":v.get("legacy_reason"),
                    "Filtr SWING":v.get("swing"),
                    "SWING po MTF":v.get("swing_after_mtf"),
                    "Bramki":("OK" if v.get("all_worker_gates_clear")
                              else "ZABLOKOWANE"),
                    "RR SWING":v.get("swing_rr"),
                })
            if records:
                st.dataframe(pd.DataFrame(records),hide_index=True,
                             use_container_width=True)
            unlocked=[v for v in ab.get("rows",[])
                      if isinstance(v,dict) and v.get("swing_unlocked") is True]
            if unlocked:
                st.info("Alternatywa SWING znalazła "+
                        str(len(unlocked))+" surowych setupów, "
                        "które odrzucił obecny filtr poziomów. "
                        "To NIE znaczy, że byłyby zyskowne. "
                        "Nie zmieniam PAPER bez ich rozliczenia po kosztach.")
            else:
                st.caption("Na tej świecy alternatywa SWING nie odblokowała "
                           "układu odrzuconego przez bieżący filtr poziomów.")

    recent_paper,chart_paper=cloud_paper_positions(payload,frame)
    focus_utc=None
    raw_rows=list(raw_trial.get("recent") or []) if isinstance(raw_trial,dict) else []
    active_raw=raw_trial.get("active") if isinstance(raw_trial,dict) else None
    if isinstance(active_raw,dict):
        raw_rows.append(active_raw)
    if chart_mode=="OSTATNIE OPEN RAW":
        known=[r for r in raw_rows if isinstance(r,dict)
               and _parse_utc(r.get("entry_bar_open_utc")) is not None]
        if known:
            latest=max(known,key=lambda r:_parse_utc(r["entry_bar_open_utc"]))
            focus_utc=latest["entry_bar_open_utc"]
    elif chart_mode=="OSTATNIE CLOSE RAW":
        known=[r for r in raw_rows if isinstance(r,dict)
               and _parse_utc(r.get("closed_utc")) is not None]
        if known:
            latest=max(known,key=lambda r:_parse_utc(r["closed_utc"]))
            focus_utc=latest["closed_utc"]
    elif chart_mode=="OSTATNIE OPEN PAPER v3":
        known=[r for r in recent_paper if _parse_utc(r.get("opened_utc")) is not None]
        if known:
            latest=max(known,key=lambda r:_parse_utc(r["opened_utc"]))
            focus_utc=latest["opened_utc"]
    if chart_mode!="BIEŻĄCE ŚWIECE":
        if focus_utc is None:
            st.warning("W tym rejestrze nie ma jeszcze udokumentowanej "
                       "transakcji do pokazania na wykresie.")
        elif frame.empty or not(frame.index[0]<=_parse_utc(focus_utc)<=frame.index[-1]):
            st.warning("Ostatnia transakcja jest starsza niż dostępny "
                       "zakres świec "+choice+". Czas: "+str(focus_utc)+
                       ". Nie przesuwam znacznika na fikcyjne świece.")
    viewport=cloud_chart_view_range(
        frame,choice,moving=moving_chart["bar"]
        if moving_chart["visible"] and chart_mode=="BIEŻĄCE ŚWIECE"
        else None,visible_count=zoom,focus_utc=focus_utc)
    counts=cloud_paper_visibility(payload,viewport=viewport)
    st.markdown("##### 📊 ILE NAPRAWDĘ OTWORZYŁ BOT PAPER?")
    if counts["known"]:
        ca,cb,cc,cd=st.columns(4)
        ca.metric("OPEN w całym PAPER",counts["total_open"])
        cb.metric("CLOSED w całym PAPER",counts["total_closed"])
        cc.metric("PENDING (to NIE OPEN)",counts["pending"])
        cd.metric("OPEN w oknie wykresu",counts["visible_open"])
        st.caption("W widocznym oknie: "+str(counts["visible_open"])+
                   " otwarć i "+str(counts["visible_closed"])+
                   " zamknięć. Mniej trójkątów na wykresie NIE oznacza "
                   "mniejszej liczby transakcji w archiwum. "
                   "Ostatnie OPEN UTC: "+
                   str(counts["last_open_utc"] or "BRAK")+
                   " | CLOSE UTC: "+str(counts["last_close_utc"] or "BRAK")+
                   ". Wszystkie to symulacje bez zleceń brokera.")
        if counts["invalid_rows"]:
            st.warning("Nieprawidłowe wpisy PAPER: "+
                       str(counts["invalid_rows"])+
                       ". Nie liczę ich jako transakcji.")
    else:
        st.warning("BRAK ZWERYFIKOWANEGO REJESTRU PAPER. "
                   "Znaczniki na wykresie nie potwierdzają liczby transakcji.")
    gap=cloud_chart_gaps(frame,choice,visible_count=zoom)
    if gap["known"]:
        st.caption("📅 Ostatnie zamknięte "+choice+": "+str(gap["bars"])+
                   " świec • przerwy dłuższe niż interwał: "+
                   str(gap["gaps"])+
                   " • ostatnia świeca UTC: "+str(gap["last_closed_utc"]))
        if gap["gaps"]:
            st.warning("LUKI W ARCHIWUM: "+str(gap["gaps"])+
                       " przerw, około "+str(gap["missing_slots"])+
                       " brakujących okresów, największa przerwa "+
                       str(gap["largest_gap_minutes"])+" min. "
                       "Przyczyną może być pauza rynku — sprawdź godzinę "
                       "notowań i STATUS/API. Nie tworzę fikcyjnych świec.")
    if recent_paper:
        active=next((p for p in recent_paper
                     if p.get("status") in ("OPEN","PENDING")),None)
        if active:
            origin=method_attribution(active)
            st.info(
                "🧪 POZYCJA PAPER "+str(active["status"])+" | "+
                str(active["side"])+" | "+origin["label"]+
                " | TF="+str(active.get("timeframe","BRAK"))+
                " | ID="+str(active.get("trade_id","BRAK"))[:10]+
                " — symulacja odtwarzana ze świec, bez zlecenia Capital.com.")
        st.markdown("##### 📋 OSTATNIE POZYCJE PAPER — TRYB I METODA")
        st.dataframe(pd.DataFrame([{
            "Kierunek":p["side"],"Status":p["status"],
            "Tryb":method_attribution(p)["mode"],
            "Metoda":method_attribution(p)["method"],
            "Interwał":str(p.get("timeframe","BRAK")),
            "Czas OPEN UTC":str(p.get("opened_utc") or "BRAK"),
            "Wynik pkt":p.get("pnl_pts"),
            "ID":str(p.get("trade_id","BRAK"))[:12],
        } for p in recent_paper[:12]]),
        hide_index=True,use_container_width=True)
        st.caption("AUTO oznaczam tylko wtedy, gdy pochodzi z powodu sygnału "
                   "zapisanym przy tej pozycji. Starszy wpis bez dowodu "
                   "pozostaje jako NIEUSTALONY / POJEDYNCZY.")
    else:
        st.caption("W checkpointcie brak zarejestrowanych pozycji PAPER US500; "
                   "nie wyświetlam wymyślonych LONG/SHORT.")
    # Render only the requested x-range (up to 300 real candles), not the
    # entire 1500-record cache. EMA is still warmed up on FULL history.
    timepad={"M1":60,"M2":120,"M5":300,"M15":900,"H1":3600}[choice]
    display_frame=(frame.loc[
        (frame.index>=viewport[0]-pd.Timedelta(seconds=timepad*4))&
        (frame.index<=viewport[1]+pd.Timedelta(seconds=timepad*2))]
        if not frame.empty and viewport is not None else frame)
    if frame.empty:
        st.info("Brak zamkniętych świec "+choice+" w archiwum. "
                "Bieżąca OHLC może być pokazana osobno, bez fikcyjnej historii.")
        if not moving_chart["visible"]:
            return
        candles=go.Figure()
    else:
        candles=go.Figure(go.Candlestick(
            x=display_frame.index,open=display_frame.Open,high=display_frame.High,
            low=display_frame.Low,close=display_frame.Close,
            increasing={"line":{"color":"#27cf94","width":1.5},
                        "fillcolor":"#27cf94"},
            decreasing={"line":{"color":"#ff5b6d","width":1.5},
                        "fillcolor":"#ff5b6d"},
            name="US500 "+choice+" — ZAMKNIĘTE"))
        # Read-only visual indicators from CLOSED candles only. They are
        # NOT read by any strategy and never create an entry signal.
        for period,color in ((9,"#ffd447"),(21,"#57b4ff"),(50,"#bd82f7")):
            ema=frame["Close"].ewm(span=period,adjust=False,
                                     min_periods=period).mean()
            candles.add_trace(go.Scatter(
                x=display_frame.index,y=ema.reindex(display_frame.index),mode="lines",
                name=f"EMA {period} • tylko podgląd",
                line={"color":color,"width":1.5},
                hovertemplate=f"EMA {period}: %{{y:.2f}}<extra></extra>"))
    # IMPORTANT: this is a separate, visibly named, INCOMPLETE bar.
    # It uses REAL observed MID samples for both moving body and wicks.
    # The original closed M15 OHLC and PAPER annotations remain immutable.
    if moving_chart["visible"]:
        live=moving_chart["bar"]
        explanation=(choice+" — tylko ZAOBSERWOWANE próbki MID; "
                     "może brakować rzeczywistych ekstremów."
                     if moving_chart["missing_extremes_possible"]
                     else choice+" w trakcie: niezamknięty OHLC Capital /prices.")
        candles.add_trace(go.Candlestick(
            x=[live["at"]],
            open=[live["open"]],high=[live["high"]],
            low=[live["low"]],close=[live["close"]],
            name=("🕯️ "+choice+" • OBSERWOWANE MID (KNOTY W RUCHU)"
                  if moving_chart["missing_extremes_possible"]
                  else "🕯️ "+choice+" • OHLC BID WebSocket"
                  if moving_chart.get("basis")=="BID"
                  else "🕯️ "+choice+" /prices • NIEPEŁNA / QUOTE NIEZWERYFIKOWANY"
                  if moving_chart.get("quote_verified") is False
                  else "🕯️ "+choice+" LIVE /prices • NIEPEŁNA"),
            increasing={"line":{"color":"#34e8f2","width":3},
                        "fillcolor":"rgba(52,232,242,0.48)"},
            decreasing={"line":{"color":"#ffad4e","width":3},
                        "fillcolor":"rgba(255,173,78,0.48)"},
            hovertext=[explanation+
                "<br>O: "+str(round(live["open"],2))+
                " H: "+str(round(live["high"],2))+
                " L: "+str(round(live["low"],2))+
                " C: "+str(round(live["close"],2))+
                "<br>Odebrano: "+str(live["collected_utc"])],
            hoverinfo="text"))
        # A visible 45-65 candle window replaces the former fixed
        # eight-hour range (which made M1 candles nearly invisible).
    # Only validated fresh DEMO quote points, never synthetic candles.
    if overlay["visible"]:
        # The former cloud of 5-second yellow sample dots obscured candles
        # (especially the M1 currently forming bar). Show ONE price line.
        # The points remain available in quote diagnostics, not mistaken
        # for LONG/SHORT entries or 5-second candles.
        candles.add_hline(
            y=float(overlay["mid"]),line_color="#f5c24b",
            line_dash="dot",opacity=.65,
            annotation_text=f'BID/ASK MID {overlay["mid"]:.2f}',
            annotation_position="top left")
    # Separate broker /prices M1 PREVIEW marker; not a closed M15 candle.
    if forming["visible"] and choice=="M15":
        m=forming["preview"]
        candles.add_trace(go.Scatter(
            x=[m["captured_time"]],y=[m["close"]],
            mode="markers",name="🕯️ Nieukończona M1 /prices (CLOUD)",
            marker={"symbol":"diamond-open","size":13,
                    "color":"#51bcff","line":{"width":2}},
            hovertemplate=(
                f'M1 W TRAKCIE /prices UTC {m["open_utc"]}'
                f'<br>O: {m["open"]:.2f} H: {m["high"]:.2f}'
                f'<br>L: {m["low"]:.2f} C: {m["close"]:.2f}'
                f'<br>Odczyt: {m["age_seconds"]} s'
                '<extra></extra>')))
    # Exact OPEN/CLOSE PAPER from the checkpoint, NEVER watch markers or
    # signals inferred from OHLC. M1 PAPER may appear on the M15 time axis.
    annotate_paper_history(candles,chart_paper,
                           "US500","Capital.com DEMO REST",None)
    # This additional lane NEVER creates entries from chart candles or
    # OBSERWUJ signals: markers are from the durable worker RAW ledger.
    annotate_raw_forward(candles,raw_trial,
                         start=viewport[0],end=viewport[1])
    open_row=next((p for p in recent_paper if p.get("status")=="OPEN"),None)
    if open_row is not None:
        annotate_open_paper(candles,open_row)
    candles.update_layout(
        height=720,xaxis_rangeslider_visible=False,template="plotly_dark",
        uirevision="fokus_cloud_"+choice+"_view_"+chart_mode+"_zoom_"+str(zoom),
        paper_bgcolor="#101928",plot_bgcolor="#101928",
        font={"size":13,"color":"#e8eef8"},
        legend={"orientation":"h","y":1.15,"x":0,"font":{"size":11}},
        hovermode="x unified",
        xaxis={"showgrid":True,"gridcolor":"#23354a","showspikes":True,
               "spikecolor":"#e8eef8","range":viewport},
        yaxis={"showgrid":True,"gridcolor":"#23354a","tickformat":".2f",
               "side":"right","fixedrange":False},
        margin={"l":12,"r":36,"t":66,"b":28})
    with live_chart_slot.container():
        st.markdown("### 🕯️ US500 — PRAWDZIWE ŚWIECE + LONG / SHORT / CLOSE / WYNIK")
        if focus_utc is not None and viewport is not None and (
                viewport[0]<=_parse_utc(focus_utc)<=viewport[1]):
            when=_parse_utc(focus_utc).tz_convert("Europe/Warsaw").strftime(
                "%d.%m.%Y %H:%M")
            st.success("🎯 Wykres przesunięty na zapisaną transakcję: "+when+
                       " (czas polski). Najedź na zielony/czerwony trójkąt "
                       "lub romb, aby sprawdzić cenę i wynik.")
        st.caption("Zielone/czerwone = autentyczne zamknięte OHLC. "+
                   "Trójkąty 🟢/🔴 = otwarcia z ARCHIWUM PAPER; "+
                   "romb ✅/❌ = rozliczony wynik RAW po kosztach. "+
                   "Najedź na marker, aby zobaczyć dokładną godzinę, "+
                   "strategię, wejście, SL, TP i liczbę punktów. "+
                   "Dla RAW OPEN są trzy przerywane linie wejście/SL/TP.")
        st.plotly_chart(candles,use_container_width=True,
                        key="cloud_worker_chart_"+choice+"_v1")
    with raw_journal_slot.container():
        st.markdown("##### 📓 DZIENNIK AUTO RAW PAPER — OPEN / CLOSED / UNIEWAŻNIONE")
        history=rows_for_journal(raw_trial,limit=60)
        if history:
            st.dataframe(pd.DataFrame(history),hide_index=True,
                         use_container_width=True)
            st.caption("Czasy w tabeli: Europe/Warsaw. "+
                       "Unieważnienie po OPEN oznacza przerwę w zweryfikowanych "+
                       "świecach, a nie wynik 0 pkt. "+
                       "OPEN świecy = symulowana cena otwarcia kolejnej M1. "+
                       "Potwierdzenie OPEN = czas, gdy worker znał "+
                       "już zamknięcie tej świecy. Wynik po kosztach "+
                       "jest podany w PUNKTACH US500, nie złotówkach.")
        else:
            st.caption("BRAK ZAMKNIĘTYCH ANI OTWARTYCH transakcji RAW "+
                       "w rejestrze. Nie rysuję fikcyjnych strzałek. "+
                       "Powód: "+str(raw_trial.get("last_reason","BRAK SKANU")))
    if overlay["visible"]:
        lag=closed_m15_lag(frame)
        limits={"M1":5,"M2":8,"M5":16,"M15":35,"H1":125}
        if lag is not None and lag>limits[choice]:
            st.warning(
                f'⚠️ Bieżące ceny są dostępne, ale ostatnia zamknięta '
                f'{choice} ma {lag:.1f} min. Sprawdź zapis świec '
                'w Northflank/Supabase; checkpoint nie gwarantuje OHLC.')
    st.caption("Przybliżenie: "+str(zoom)+
               " ostatnich świec; zmiana zoomu nie zmienia strategii. "
               "BIEŻĄCA cena może być odświeżana co ~5 s, "
               "ZAMKNIĘTE M1/M2 są pobierane z chmury co ~35 s, "
               "M5/M15/H1 co ~60 s. Nową świecę widać dopiero po "
               "jej zapisaniu przez Northflank.")
    st.caption("Zielone/czerwone świece: HISTORYCZNE, ZAMKNIĘTE "+choice+". "
               "Dla M2: pary pełnych M1, bez wypełniania braków. "
               "Jasnoniebieska/pomarańczowa OSTATNIA świeca: "
               "ruchoma, NIEPEŁNA "+choice+" ze strumienia WS lub "
               "awaryjnego /prices. BID to BID, MID to MID; "
               "knoty z próbek mogą być niekompletne. "
               "Niebieski pusty romb: M1 /prices W TRAKCIE, tylko do "
               "podglądu (jeśli świeży). Żółta linia i "
               "punkty: jedynie ŚWIEŻE obserwacje BID/ASK REST (~5 s, "
               "do 24 punktów), a nie ticki/świece. Trójkąty i kwadraty: "
               "WYŁĄCZNIE zapisane PAPER OPEN/CLOSED z checkpointu "
               "(także M1), po najechaniu AUTO → metoda, TF, ID, wynik. "
               "Wykres nie tworzy nowych transakcji ani brokerowych filli.")
