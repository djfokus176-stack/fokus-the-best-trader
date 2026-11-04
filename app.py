"""FOKU$ THE BEST TRADER — niezależny start Streamlit, tylko analiza i PAPER."""
from __future__ import annotations
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="FOKU$ THE BEST TRADER", page_icon="📈", layout="wide")
st.title("⚡ FOKU$ THE BEST TRADER")
st.caption("NOWY PROJEKT · S&P 500 CFD · READ ONLY · PAPER · BRAK AUTO-TRADE")

def secret(name, default=""):
    value = os.getenv(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, default))
    except (FileNotFoundError, KeyError):
        return default

def get_capital_bars(epic, resolution):
    key = secret("CAPITAL_API_KEY")
    user = secret("CAPITAL_IDENTIFIER")
    password = secret("CAPITAL_PASSWORD")
    if not all([key, user, password]):
        raise ValueError("Brak CAPITAL_API_KEY / CAPITAL_IDENTIFIER / CAPITAL_PASSWORD w Secrets.")
    base = "https://demo-api-capital.backend-capital.com"
    session = requests.post(
        base + "/api/v1/session",
        headers={"X-CAP-API-KEY": key, "Content-Type": "application/json"},
        json={"identifier": user, "password": password, "encryptedPassword": False}, timeout=12)
    session.raise_for_status()
    headers = {"X-CAP-API-KEY": key, "CST": session.headers["CST"],
               "X-SECURITY-TOKEN": session.headers["X-SECURITY-TOKEN"]}
    r = requests.get(base + "/api/v1/prices/" + epic,
                     params={"resolution": resolution, "max": 350}, headers=headers, timeout=12)
    r.raise_for_status()
    rows = []
    for item in r.json().get("prices", []):
        d = {"ts": pd.to_datetime(item["snapshotTimeUTC"], utc=True)}
        for label, name in (("Open","openPrice"),("High","highPrice"),
                            ("Low","lowPrice"),("Close","closePrice")):
            p = item[name]
            d[label] = (float(p["bid"]) + float(p["ask"])) / 2
        p = item["closePrice"]
        d["Spread"] = float(p["ask"]) - float(p["bid"])
        rows.append(d)
    if len(rows) < 75:
        raise ValueError("Z API otrzymano mniej niż 75 świec.")
    df = pd.DataFrame(rows).set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    # Bieżący bar może nadal powstawać. Odrzucamy go konserwatywnie.
    return df.iloc[:-1].copy()

def get_csv(file):
    df = pd.read_csv(file)
    if not {"Time","Open","High","Low","Close"}.issubset(df.columns):
        raise ValueError("CSV wymaga: Time, Open, High, Low, Close")
    df["ts"] = pd.to_datetime(df["Time"], utc=True)
    for c in ["Open","High","Low","Close"]:
        df[c] = pd.to_numeric(df[c], errors="raise")
    if len(df) < 75:
        raise ValueError("CSV wymaga minimum 75 świec.")
    df = df.set_index("ts").sort_index()
    if df.index.has_duplicates:
        raise ValueError("CSV zawiera zduplikowane czasy.")
    if (df["High"] < df[["Open","Close","Low"]].max(axis=1)).any() or (df["Low"] > df[["Open","Close","High"]].min(axis=1)).any():
        raise ValueError("Niespójne OHLC w CSV.")
    df["Spread"] = float("nan") # brak realnych kosztów transakcji
    return df

def indicators(df):
    x = df.copy()
    for n in (9,21,50):
        x["EMA"+str(n)] = x.Close.ewm(span=n, adjust=False).mean()
    delta = x.Close.diff()
    up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    x["RSI"] = 100 - 100 / (1 + up / down.replace(0, np.nan))
    tr = pd.concat([x.High-x.Low, (x.High-x.Close.shift()).abs(),
                    (x.Low-x.Close.shift()).abs()], axis=1).max(axis=1)
    x["ATR"] = tr.rolling(14, min_periods=14).mean()
    return x

def signal(x, kind, spread):
    z = x.iloc[-1]
    prev = x.iloc[-2]
    atr = float(z.ATR)
    if not np.isfinite(atr) or atr <= 0:
        return ("WAIT","Za mało wiarygodnych danych ATR",None,None,None)
    if not np.isfinite(spread) or spread > min(2.0, atr * 0.33):
        return ("WAIT","Brak wiarygodnego spreadu lub spread zbyt duży",None,None,None)
    bullish = z.EMA9 > z.EMA21 > z.EMA50 and z.Close > z.EMA9 and z.EMA21 > prev.EMA21
    bearish = z.EMA9 < z.EMA21 < z.EMA50 and z.Close < z.EMA9 and z.EMA21 < prev.EMA21
    if kind == "DRUGA FALA":
        # Wyraźny trend, wcześniejszy impuls, korekta do EMA21, potwierdzona świeca.
        window = x.iloc[-10:-2]
        impulse_up = (window.Close.max()-window.Close.min()) > 1.5*atr
        pull_long = prev.Low <= prev.EMA21 + atr*0.4 and z.Close > prev.High
        pull_short = prev.High >= prev.EMA21 - atr*0.4 and z.Close < prev.Low
        bullish = bullish and impulse_up and pull_long
        bearish = bearish and impulse_up and pull_short
    else:
        bullish = bullish and z.Close > z.Open and z.RSI < 72
        bearish = bearish and z.Close < z.Open and z.RSI > 28
    if not bullish and not bearish:
        return ("WAIT","Brak pełnego potwierdzenia strategii na zamkniętej świecy",None,None,None)
    direction = "LONG" if bullish else "SHORT"
    # Poziomy edukacyjne MID. Nie są wykonalnymi kwotowaniami brokera.
    entry = float(z.Close)
    if bullish:
        stop = float(min(x.Low.iloc[-6:].min(), entry-1.2*atr))
        target = entry + 1.8*(entry-stop)
    else:
        stop = float(max(x.High.iloc[-6:].max(), entry+1.2*atr))
        target = entry - 1.8*(stop-entry)
    net_rr = (abs(target-entry)-spread)/(abs(entry-stop)+spread)
    if net_rr < 1.4:
        return ("WAIT","Za słaby stosunek zysku do ryzyka po spreadzie",None,None,None)
    return (direction, "Warunki techniczne spełnione — SYGNAŁ PAPER, nie zlecenie",entry,stop,target)

def connect_db():
    # Lokalny plik w Streamlit Cloud jest nietrwały po restarcie/deploy.
    data = Path(__file__).resolve().parent / "data"
    data.mkdir(parents=True,exist_ok=True)
    db = sqlite3.connect(data/"paper_decisions.sqlite3",timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS paper_decisions (event_id TEXT PRIMARY KEY, utc TEXT, instrument TEXT, tf TEXT, strategy TEXT, source TEXT, action TEXT, entry REAL, stop REAL, target REAL, reason TEXT)")
    db.commit()
    return db

with st.sidebar:
    st.header("⚙️ USTAWIENIA")
    epic = st.text_input("Capital.com EPIC", secret("CAPITAL_EPIC","US500"))
    tf = st.selectbox("Interwał", ["MINUTE","MINUTE_5","MINUTE_15","HOUR"], format_func=lambda t: {"MINUTE":"M1","MINUTE_5":"M5","MINUTE_15":"M15","HOUR":"H1"}[t])
    strategy = st.radio("Strategia", ["DRUGA FALA","EMA TREND"])
    st.info("Odczyt API tylko na żądanie. Brak automatycznego handlu i skanowania 24/7.")

tab1, tab2, tab3 = st.tabs(["📊 WYKRES I DECYZJA","📚 ARCHIWUM PAPER","🔐 STATUS / AI"])
with tab1:
    upload = st.file_uploader("Opcjonalnie CSV historyczne (wyłącznie nauka)",type="csv")
    if st.button("🔄 SKANUJ NOWE DANE",type="primary"):
        try:
            if upload:
                df = get_csv(upload); src = "CSV HISTORYCZNE — NIE LIVE"
            else:
                df = get_capital_bars(epic,tf); src = "CAPITAL.COM DEMO — MID"
            st.session_state["snapshot"] = (df,src,epic,tf)
        except Exception as e:
            st.error("Błąd odczytu: " + str(e)[:350])
    snap = st.session_state.get("snapshot")
    if snap:
        df,src,old_epic,old_tf = snap
        if (epic,tf) != (old_epic,old_tf):
            st.warning("Zmieniono EPIC lub interwał. Kliknij SKANUJ NOWE DANE.")
        else:
            x=indicators(df)
            stamp=x.index[-1]
            age=(datetime.now(timezone.utc)-stamp.to_pydatetime()).total_seconds()
            spread=float(x.Spread.iloc[-1])
            maxage={"MINUTE":180,"MINUTE_5":600,"MINUTE_15":1800,"HOUR":7200}[tf]
            valid=src.startswith("CAPITAL") and -30<=age<=maxage and np.isfinite(spread)
            st.caption("Źródło: "+src+" | Ostatnia świeca: "+stamp.strftime("%Y-%m-%d %H:%M UTC")+" | Wiek: "+str(round(age))+" s | Spread: "+str(round(spread,3)))
            fig=go.Figure(go.Candlestick(x=x.index,open=x.Open,high=x.High,low=x.Low,close=x.Close,name="MID"))
            for c,color in (("EMA9","#d9ba4c"),("EMA21","#6da9ff"),("EMA50","#bb85e9")):
                fig.add_trace(go.Scatter(x=x.index,y=x[c],name=c,line=dict(color=color,width=1.5)))
            fig.update_layout(template="plotly_dark",height=530,xaxis_rangeslider_visible=False)
            st.plotly_chart(fig,use_container_width=True)
            direction,reason,entry,stop,target=signal(x,strategy,spread) if valid else ("WAIT","Dane CSV lub nieświeże / niesprawdzone kwotowanie",None,None,None)
            st.subheader(("🟢 " if direction=="LONG" else "🔴 " if direction=="SHORT" else "🟡 ")+direction)
            st.write(reason)
            if direction!="WAIT":
                a,b,c=st.columns(3)
                a.metric("Wejście MID",round(entry,2));b.metric("SL papierowy",round(stop,2));c.metric("TP papierowy",round(target,2))
            st.caption("PAPER oznacza ocenę hipotetyczną, nie wykonaną transakcję. Nie pokazujemy zysku bez prawdziwego rozliczenia.")
            if valid:
                try:
                    eid=hashlib.sha256(f"{epic}|{tf}|{strategy}|{stamp.isoformat()}|{direction}".encode()).hexdigest()
                    with connect_db() as db:
                        db.execute("INSERT OR IGNORE INTO paper_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                  (eid,stamp.isoformat(),epic,tf,strategy,src,direction,entry,stop,target,reason))
                except Exception as e:
                    st.warning("Nie zapisano decyzji PAPER: "+str(e)[:120])
            st.session_state["ai_snapshot"]={"instrument":epic,"tf":tf,"source":src,"timestamp":stamp.isoformat(),
              "action":direction,"reason":reason,"spread":spread,"last_10_candles":x[["Open","High","Low","Close","EMA9","EMA21","EMA50","RSI","ATR"]].tail(10).round(3).reset_index().astype(str).to_dict(orient="records")}
    else:
        st.warning("Brak danych. Wprowadź klucze Capital.com do Streamlit Secrets lub wczytaj CSV.")
with tab2:
    st.subheader("📚 Historia decyzji PAPER — osobna dla nowego projektu")
    with connect_db() as db:
        data=pd.read_sql_query("SELECT utc,instrument,tf,strategy,source,action,entry,stop,target,reason FROM paper_decisions ORDER BY utc DESC LIMIT 300",db)
    st.dataframe(data,use_container_width=True,hide_index=True)
    st.warning("Streamlit Cloud nie gwarantuje trwałości lokalnego SQLite. Do 24/7 potrzebna baza zewnętrzna i osobny worker.")
with tab3:
    st.subheader("🔐 Konfiguracja i weryfikacja")
    for name in ["CAPITAL_API_KEY","CAPITAL_IDENTIFIER","CAPITAL_PASSWORD","OPENAI_API_KEY"]:
        st.write(("✅ " if secret(name) else "❌ ")+name+" — "+("ustawiono" if secret(name) else "brak"))
    st.write("✅ Brak brokerowych zleceń POST/DELETE; ❌ brak 24/7; ❌ brak potwierdzonego samouczenia; ❌ brak zweryfikowanego backtestu OOS.")
    question=st.text_input("Pytanie do AI o aktualny odczyt świec")
    if st.button("🧠 ANALIZUJ LICZBOWY WYKRES"):
        if not secret("OPENAI_API_KEY") or not st.session_state.get("ai_snapshot"):
            st.warning("Wymagany OPENAI_API_KEY oraz wykonany skan.")
        else:
            try:
                from openai import OpenAI
                import json
                client=OpenAI(api_key=secret("OPENAI_API_KEY"))
                result=client.chat.completions.create(model=secret("OPENAI_MODEL","gpt-4.1-mini"),
                    messages=[{"role":"system","content":"Jesteś krytycznym audytorem PAPER, bez obietnic zysku. Wyjaśnij dane świec, ryzyko, cenę unieważnienia; nie udawaj widzenia ekranu."},
                              {"role":"user","content":json.dumps(st.session_state["ai_snapshot"],ensure_ascii=False,default=str)+"\nPytanie: "+question}],
                    max_tokens=600)
                st.write(result.choices[0].message.content)
            except Exception as e:
                st.error("Błąd OpenAI: "+str(e)[:180])
