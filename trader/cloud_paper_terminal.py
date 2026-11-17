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
from .cloud_candle_clock import render_candle_clock


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


def cloud_chart_view_range(frame, choice, *, moving=None):
    """Zoom around *real* recent candles; no synthetic price or candle data."""
    if choice not in ("M1","M2","M5","M15","H1"):
        raise ValueError("Unsupported UI chart timeframe")
    if frame.empty and moving is None:
        return None
    seconds={"M1":60,"M2":120,"M5":300,"M15":900,"H1":3600}[choice]
    count={"M1":65,"M2":60,"M5":55,"M15":45,"H1":45}[choice]
    last=(_parse_utc(moving["at"]) if moving is not None
          else frame.index[-1])
    if last is None:
        return None
    if len(frame):
        left=frame.index[max(0,len(frame)-count)]
    else:
        left=last-pd.Timedelta(seconds=seconds*35)
    if left>=last:
        left=last-pd.Timedelta(seconds=seconds*2)
    return [left,last+pd.Timedelta(seconds=seconds*2)]

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
                or m15_cache_due(cache)):
            version,payload=remote.fetch()
            original=remote.fetch_candles("US500",resolution,limit=180)
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
    recent_paper,chart_paper=cloud_paper_positions(payload,frame)
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
    if frame.empty:
        st.info("Brak zamkniętych świec "+choice+" w archiwum. "
                "Bieżąca OHLC może być pokazana osobno, bez fikcyjnej historii.")
        if not moving_chart["visible"]:
            return
        candles=go.Figure()
    else:
        candles=go.Figure(go.Candlestick(
            x=frame.index,open=frame.Open,high=frame.High,
            low=frame.Low,close=frame.Close,
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
                x=frame.index,y=ema,mode="lines",
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
        points=overlay["points"]
        if points:
            candles.add_trace(go.Scatter(
                x=[p["time"] for p in points],
                y=[p["mid"] for p in points],
                mode="lines+markers" if len(points)>1 else "markers",
                name="🟡 MID BID/ASK — "+("WS" if ws_transport else "REST"),
                line={"color":"#f5c24b","width":2.6},
                marker={"size":7,"color":"#f5c24b"},
                hovertemplate="Odczyt %{x}<br>MID: %{y:.2f}<extra></extra>"))
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
    open_row=next((p for p in recent_paper if p.get("status")=="OPEN"),None)
    if open_row is not None:
        annotate_open_paper(candles,open_row)
    viewport=cloud_chart_view_range(
        frame,choice,moving=moving_chart["bar"] if moving_chart["visible"] else None)
    candles.update_layout(
        height=570,xaxis_rangeslider_visible=False,template="plotly_dark",
        uirevision="fokus_cloud_"+choice+"_readable_v2",
        paper_bgcolor="#101928",plot_bgcolor="#101928",
        font={"size":13,"color":"#e8eef8"},
        legend={"orientation":"h","y":1.15,"x":0,"font":{"size":11}},
        hovermode="x unified",
        xaxis={"showgrid":True,"gridcolor":"#23354a","showspikes":True,
               "spikecolor":"#e8eef8","range":viewport},
        yaxis={"showgrid":True,"gridcolor":"#23354a","tickformat":".2f",
               "side":"right","fixedrange":False},
        margin={"l":12,"r":36,"t":66,"b":28})
    st.plotly_chart(candles,use_container_width=True,
                    key="cloud_worker_chart_"+choice+"_v1")
    if overlay["visible"]:
        lag=closed_m15_lag(frame)
        limits={"M1":5,"M2":8,"M5":16,"M15":35,"H1":125}
        if lag is not None and lag>limits[choice]:
            st.warning(
                f'⚠️ Bieżące ceny są dostępne, ale ostatnia zamknięta '
                f'{choice} ma {lag:.1f} min. Sprawdź zapis świec '
                'w Northflank/Supabase; checkpoint nie gwarantuje OHLC.')
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
