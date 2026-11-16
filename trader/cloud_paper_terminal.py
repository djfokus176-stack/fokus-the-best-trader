"""Read-only cloud terminal from worker's persisted M15 and checkpoint.

This module NEVER authenticates against Capital.com directly. The service's
permanent, private credentials belong to the Northflank worker. Streamlit
requires only its own server-side Supabase read credentials to show results.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    st.markdown("#### ☁️ US500 — RUCHOME ŚWIECE M1 / M2 / M5 / M15 / H1")
    labels={"MINUTE":"M1","MINUTE_5":"M5",
            "MINUTE_15":"M15","HOUR":"H1"}
    choices=("M1","M2","M5","M15","H1")
    choice=st.selectbox(
        "Interwał WYKRESU CLOUD (nie zmienia strategii AUTO/PAPER)",
        options=choices,index=choices.index(labels.get(default_tf,"M1")),
        key="cloud_price_chart_interval")
    resolution=source_resolution(choice)
    st.caption(
        "Zamknięte świece wybranego interwału = zielone/czerwone. "
        "M2 powstaje WYŁĄCZNIE z dwóch kompletnych, kolejnych M1. "
        "OSTATNIA świeca w trakcie = dane MID z rzeczywistych próbek "
        "BID/ASK workera co ~5s, z ruchomymi knotami, wyraźnie NIEPEŁNA. "
        "Żółty ślad: osobne odczyty BID/ASK z REST, odświeżane ok. 5 s "
        "gdy strona jest otwarta. NIE są to ticki ani świece 5S. "
        "Nieukończona M1 (gdy dostępna) pochodzi wyłącznie od Northflank "
        "z /prices co ~15s, nie jest świecą M15 ani sygnałem. "
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
                or m15_cache_due(cache)):
            version,payload=remote.fetch()
            original=remote.fetch_candles("US500",resolution,limit=180)
            frame=closed_chart_frame(original,choice)
            audit=cloud_terminal_summary(version,payload,frame)
            # Per-BROWSER session cache only; never put credentials in it.
            st.session_state["_fokus_cloud_chart_cache_v3"]={
                "url":url,"resolution":resolution,
                "version":version,"payload":payload,"frame":frame,
                "fetched_utc":pd.Timestamp.now(tz="UTC").isoformat()}
        else:
            version,payload,frame=(cache["version"],cache["payload"],cache["frame"])
            audit=cloud_terminal_summary(version,payload,frame)
    except (RemoteError,ValueError,TypeError,KeyError,OverflowError,OSError):
        st.session_state.pop("_fokus_cloud_chart_cache_v3",None)
        st.error("Nie udało się odczytać checkpointu lub archiwum M15. "
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
        if choice=="M15":
            moving_chart=assess_moving_m15(
                quote_record,now=quote_now,
                last_closed_utc=frame.index[-1] if not frame.empty else None)
        else:
            moving_chart=sampled_chart_bar(
                quote_record,choice,now=quote_now,
                last_closed_utc=frame.index[-1] if not frame.empty else None)
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
    if isinstance(pump,dict) and pump.get("mode")=="BACKGROUND_SAME_CAPITAL_LOGIN":
        last_try=_parse_utc(pump.get("last_attempt_utc"))
        last_write=_parse_utc(pump.get("last_write_utc"))
        last_fresh=_parse_utc(pump.get("last_fresh_utc"))
        now_diag=pd.Timestamp.now(tz="UTC")
        def _minutes(ts):
            return (f"{(now_diag-ts).total_seconds()/60:.1f} min"
                    if ts is not None else "NIGDY")
        health=str(pump.get("status","UNKNOWN"))[:48]
        message=(f"📡 NIEZALEŻNY KOLEKTOR 5S | stan: {health} | "
                 f"próby: {pump.get('attempts',0)} | "
                 f"ostatnia próba: {_minutes(last_try)} | "
                 f"ostatni zapis: {_minutes(last_write)} | "
                 f"ostatnia ŚWIEŻA cena: {_minutes(last_fresh)}. "
                 "Ten sam login DEMO; dane osobne od PAPER.")
        if (health=="LIVE_QUOTE_SAVED" and last_fresh is not None and
                0 <= (now_diag-last_fresh).total_seconds()<=30):
            st.success(message)
        else:
            st.warning(message)
    else:
        st.warning("📡 KOLEKTOR 5S: BRAK POTWIERDZENIA NOWEGO WORKERA "
                   "BACKGROUND_SAME_CAPITAL_LOGIN w checkpointcie. "
                   "Możliwe, że Northflank nadal korzysta ze starego "
                   "commita, wyłączono FOKUS_SCALP_5S_ENABLED albo "
                   "checkpoint zapisuje inny proces.")
    if audit["cloud_online_confirmed"]:
        st.caption("Checkpoint zapisano niedawno. Nie dowodzi to otwarcia "
                   "rynku ani poprawności każdej świecy M15.")
    else:
        st.warning("Checkpoint nie jest świeży lub jego daty nie potwierdzono. "
                   "Sprawdź Northflank; nie twierdzę, że worker teraz działa.")
    if overlay["visible"]:
        st.metric("🟡 BIEŻĄCY MID BID/ASK (REST)",f'{overlay["mid"]:.2f} pkt')
        st.caption(
            f'BID {overlay["bid"]:.2f} | ASK {overlay["ask"]:.2f} | '
            f'Spread {overlay["spread"]:.2f} pkt | '
            f'Broker {overlay["broker_status"]} | '
            f'Wiek odczytu {overlay["age_seconds"]} s. '
            "To próbki API, nie ticki ani cena wykonanego zlecenia.")
    else:
        st.warning("⚪ BRAK AKTUALNEJ CENY 5S: "+overlay["reason"]+
                   " | Broker: "+str(overlay["broker_status"])+
                   " | Wiek: "+str(overlay["age_seconds"])+
                   " s. Ostatnie M15 to wyłącznie historia.")
    if forming["visible"]:
        m=forming["preview"]
        st.caption(
            f'🕯️ CLOUD /prices M1 W TRAKCIE — MID: {m["close"]:.2f} | '
            f'OHLC: {m["open"]:.2f} / {m["high"]:.2f} / '
            f'{m["low"]:.2f} / {m["close"]:.2f} | '
            f'Wiek pobrania: {m["age_seconds"]} s | '
            f'Otwarta: {m["open_utc"]}, koniec minuty: {m["close_utc"]}. '
            'To nieukończony bar, bez wpływu na PAPER.')
    else:
        st.caption('🕯️ Podgląd M1 /prices: '+forming["reason"]+
                   '. Nie ma drugiego logowania Capital w Streamlit; '
                   'dane wymagają odświeżonego workera Northflank.')
    if moving_chart["visible"]:
        live=moving_chart["bar"]
        live_message=(
            "🕯️ "+choice+" W TRAKCIE — RUCHOME KNOTY (NIE SYGNAŁ) | "
            + ("MID z próbek REST" if moving_chart["missing_extremes_possible"]
               else "nieukończona OHLC brokera /prices")
            + f' | O={live["open"]:.2f}, H={live["high"]:.2f}, '
              f'L={live["low"]:.2f}, C={live["close"]:.2f}'
            + f' | aktualizacja {live["capture_age_seconds"]} s temu.')
        if moving_chart.get("quote_verified") is False:
            st.warning(live_message+
                       " | UWAGA: /markets nie potwierdził czasu BID/ASK; "
                       "to wyłącznie aktualny odczyt /prices, "
                       "NIE potwierdzenie możliwości handlu.")
        else:
            st.success(live_message)
        if moving_m15["missing_extremes_possible"]:
            st.caption(
                "Uwaga: knoty HIGH/LOW obejmują wyłącznie ZAOBSERWOWANE "
                "próbki REST od " + str(live.get("first_vendor_utc","BRAK"))+
                "; nie muszą odzwierciedlać ekstremów całych 15 minut. "
                "Nie wpływają na SL/TP ani AUTO.")
    else:
        st.warning(
            "🟠 "+choice+" W TRAKCIE NIEAKTYWNA: "+moving_chart["reason"]+
            ". Wykres pokazuje wtedy wyłącznie ZAMKNIĘTE świece; "
            "nie tworzę sztucznych knotów. Sprawdź stan "
            "NIEZALEŻNEGO KOLEKTORA 5S powyżej.")
    st.caption("Wersja podglądu: WICK-M15-v1 / CLOUD-TF-v1 | "
               "odświeżenie przeglądarki ~5s | "
               "nie jest to zlecenie ani świeca dla strategii.")
    st.caption("Ostatni zapis skanera UTC: "+
               str(audit["last_scan_utc"] or "BRAK")+
               " | Ostatnia "+choice+" w archiwum UTC: "+
               str(audit["last_m15_utc"] or "BRAK"))
    st.caption("Ostatnia informacja workera (nie tej przeglądarki): "+
               audit["worker_summary"])
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
        st.info("W Supabase nie ma jeszcze kompletnych świec "+choice+
                " do wyświetlenia. Nie uzupełniam luk.")
        return
    candles=go.Figure(go.Candlestick(
        x=frame.index,open=frame.Open,high=frame.High,
        low=frame.Low,close=frame.Close,
        name="US500 "+choice+" CLOSED CLOUD"))
    # IMPORTANT: this is a separate, visibly named, INCOMPLETE bar.
    # It uses REAL observed MID samples for both moving body and wicks.
    # The original closed M15 OHLC and PAPER annotations remain immutable.
    if moving_chart["visible"]:
        live=moving_chart["bar"]
        explanation=(choice+" — tylko ZAOBSERWOWANE próbki MID; "
                     "może brakować rzeczywistych ekstremów."
                     if moving_m15["missing_extremes_possible"]
                     else "M15 w trakcie: niezamknięty OHLC Capital /prices.")
        candles.add_trace(go.Candlestick(
            x=[live["at"]],
            open=[live["open"]],high=[live["high"]],
            low=[live["low"]],close=[live["close"]],
            name=("🕯️ "+choice+" • MID Z PRÓBEK (KNOTY W RUCHU)"
                  if moving_m15["missing_extremes_possible"]
                  else "🕯️ M15 /prices • NIEPEŁNA / QUOTE NIEZWERYFIKOWANY"
                  if moving_m15.get("quote_verified") is False
                  else "🕯️ M15 LIVE /prices • NIEPEŁNA"),
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
        # Keep the moving candle in viewport as each new quarter begins.
        # No future data or fake calendar gap may be interpolated.
        left=max(frame.index[0],live["at"]-pd.Timedelta(hours=8))
        candles.update_xaxes(range=[
            left,live["at"]+pd.Timedelta(seconds=(
                2*{"M1":60,"M2":120,"M5":300,"M15":900,"H1":3600}[choice]))])
    # Only validated fresh DEMO quote points, never synthetic candles.
    if overlay["visible"]:
        points=overlay["points"]
        if points:
            candles.add_trace(go.Scatter(
                x=[p["time"] for p in points],
                y=[p["mid"] for p in points],
                mode="lines+markers" if len(points)>1 else "markers",
                name="🟡 MID BID/ASK ~5S (REST)",
                line={"color":"#f5c24b","width":2.6},
                marker={"size":7,"color":"#f5c24b"},
                hovertemplate="REST %{x}<br>MID: %{y:.2f}<extra></extra>"))
        candles.add_hline(
            y=float(overlay["mid"]),line_color="#f5c24b",
            line_dash="dot",opacity=.65,
            annotation_text=f'BID/ASK MID {overlay["mid"]:.2f}',
            annotation_position="top left")
    # Separate broker /prices M1 PREVIEW marker; not a closed M15 candle.
    if forming["visible"]:
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
    candles.update_layout(
        height=410,xaxis_rangeslider_visible=False,template="plotly_dark",
        uirevision="fokus_cloud_"+choice+"_v1",
        paper_bgcolor="#111a2d",plot_bgcolor="#111a2d",
        margin={"l":10,"r":10,"t":15,"b":10})
    st.plotly_chart(candles,use_container_width=True,
                    key="cloud_worker_chart_"+choice+"_v1")
    if overlay["visible"]:
        lag=closed_m15_lag(frame)
        if lag is not None and lag>35:
            st.warning(
                f'⚠️ Bieżące ceny są dostępne, ale ostatnia archiwalna '
                f'M15 ma {lag:.1f} min. Sprawdź zapis zamkniętych świec '
                'w Northflank/Supabase; checkpoint nie gwarantuje OHLC.')
    st.caption("Zielone/czerwone świece: HISTORYCZNE, ZAMKNIĘTE "+choice+". "
               "Jasnoniebieska/pomarańczowa OSTATNIA świeca: "
               "ruchoma, NIEPEŁNA "+choice+" z obserwacji MID REST, "
               "wysokie/niskie knoty mogą być niekompletne. "
               "Niebieski pusty romb: M1 /prices W TRAKCIE, tylko do "
               "podglądu (jeśli świeży). Żółta linia i "
               "punkty: jedynie ŚWIEŻE obserwacje BID/ASK REST (~5 s, "
               "do 24 punktów), a nie ticki/świece. Trójkąty i kwadraty: "
               "WYŁĄCZNIE zapisane PAPER OPEN/CLOSED z checkpointu "
               "(także M1), po najechaniu AUTO → metoda, TF, ID, wynik. "
               "Wykres nie tworzy nowych transakcji ani brokerowych filli.")
