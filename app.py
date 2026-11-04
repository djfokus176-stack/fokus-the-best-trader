"""FOKU$ THE BEST TRADER v0.1 — wholly new Streamlit research dashboard."""
from __future__ import annotations
import hashlib
import sqlite3
import os
from datetime import datetime, timezone
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from trader.market import CapitalReadOnly, FeedError, evaluate_snapshot, PERIOD
from trader.strategy import indicators, decide, backtest
from trader.storage import connect, archive, recent, audit_prior_paper_signals, paper_report
from trader.assistant import numeric_context, answer_ai
from trader.visuals import historical_marks

st.set_page_config(page_title='FOKU$ THE BEST TRADER',page_icon='📈',layout='wide')
st.markdown('''<style>
.stApp {background: #0c1020; color: #e7edf9;}
[data-testid="stMetric"] {background: #171f35; padding: 16px; border: 1px solid #2f3c5c; border-radius: 10px;}
.fokus {font-size: 2.0rem; font-weight: 800; color: #87c9ff; letter-spacing: 1px;}
.tag {background:#21304b;color:#c8defd;padding:5px 12px;border-radius:20px;font-weight:bold;}
</style>''',unsafe_allow_html=True)
st.markdown('<div class="fokus">⚡ FOKU$ THE BEST TRADER</div>',unsafe_allow_html=True)
st.markdown('<span class="tag">v0.1 NOWY PROJEKT</span> &nbsp; <span class="tag">PAPER / READ-ONLY</span> &nbsp; <span class="tag">BRAK AUTO TRADE</span>',unsafe_allow_html=True)
st.caption('Nowy program napisany od zera. Analiza świec, nie wizja AI i nie gwarancja zysku. Bez połączeń ze starym repozytorium.')


def secret(name,default=''):
    if os.getenv(name):return os.getenv(name)
    try: return str(st.secrets.get(name,default))
    except (FileNotFoundError,KeyError):return default

with st.sidebar:
    st.header('⚙️ NOWE USTAWIENIA')
    instrument=st.text_input('Instrument / EPIC Capital.com',value=secret('CAPITAL_EPIC','US500'))
    tf=st.selectbox('Interwał',['MINUTE','MINUTE_5','MINUTE_15','HOUR'],format_func=lambda x:{'MINUTE':'M1','MINUTE_5':'M5','MINUTE_15':'M15','HOUR':'H1'}[x])
    strategy=st.radio('Strategia',['DRUGA FALA','EMA TREND'])
    max_spread=st.slider('Maksymalny spread (pkt)',.2,5.0,2.0,.1)
    st.markdown('---')
    st.write('🔐 Klucze API: tylko Streamlit Secrets / ENV. Nie są zapisywane do historii, ZIP ani GitHuba.')
    has_cap=all(secret(n) for n in ['CAPITAL_API_KEY','CAPITAL_IDENTIFIER','CAPITAL_PASSWORD'])
    if has_cap:
        st.success('✅ Capital.com skonfigurowany')
    else:
        st.warning('⚠️ Brak API Capital.com. Możesz analizować własny CSV.')
    st.info('Streamlit Cloud nie gwarantuje skanera działającego 24/7. Do tego potrzebny osobny worker na stale działającym hoście.')

market_tab,lab_tab,archive_tab,settings_tab=st.tabs(['📊 WYKRES I SYGNAŁ','🧪 TESTY I NAUKA','📚 ARCHIWUM','🔐 STATUS SYSTEMU'])

def read_csv(file):
    data=pd.read_csv(file)
    expected={'Time','Open','High','Low','Close'}
    if not expected.issubset(data.columns):raise ValueError('CSV wymaga kolumn Time,Open,High,Low,Close')
    times=pd.to_datetime(data.Time,utc=True,errors='raise')
    data=data.set_index(times).drop(columns=['Time']).sort_index()
    for c in ['Open','High','Low','Close']:
        data[c]=pd.to_numeric(data[c],errors='raise')
    if len(data)<72 or data.index.has_duplicates:raise ValueError('Wymagane >=72 świeczki bez duplikatów')
    if (data.High<data[['Open','Low','Close']].max(axis=1)).any() or (data.Low>data[['Open','High','Close']].min(axis=1)).any():
        raise ValueError('Niespójne OHLC')
    data['Spread']=0.6
    return data

with market_tab:
    col1,col2=st.columns([1,2])
    with col1:
        csv=st.file_uploader('Opcjonalnie własne dane OHLC CSV (wyłącznie do nauki / replay)',type=['csv'])
        load=st.button('🔄 SKANUJ ŚWIECE',type='primary',use_container_width=True)
        st.caption('Po otwarciu strony wykonuję jedną automatyczną próbę pobrania, jeśli API jest zapisane. Ten przycisk pobiera ponownie.')
    with col2:
        st.info('Dane źródłowe = te same świece, które czyta strategia i wyświetla wykres. AI nie widzi obrazu ekranu; dostaje numeryczne OHLC i wskaźniki.')
    auto_scan = bool(has_cap and csv is None and not st.session_state.get('initial_scan_attempted') and st.session_state.get('market_snap') is None)
    if auto_scan:
        st.session_state['initial_scan_attempted'] = True
        st.info('🔄 Pierwsza próba pobrania świec z Capital.com DEMO...')
    if load or auto_scan:
        try:
            st.session_state.pop('last_feed_error', None)
            if csv is not None:
                raw=read_csv(csv)
                st.session_state['market_snap']=evaluate_snapshot(raw,instrument,tf,max_spread=max_spread)
                st.session_state['source_override']='CSV NAUKA (NIE LIVE)'
            elif has_cap:
                client=CapitalReadOnly(secret('CAPITAL_API_KEY'),secret('CAPITAL_IDENTIFIER'),secret('CAPITAL_PASSWORD'))
                st.session_state['market_snap']=client.candles(instrument,tf,count=350,max_spread=max_spread)
                st.session_state['source_override']='Capital.com DEMO REST'
            else:
                st.error('Brak Capital.com API lub CSV. NIE generuję sztucznych cen.')
        except (FeedError,ValueError) as ex:
            st.session_state['last_feed_error'] = str(ex)
            st.error('❌ Nie udało się pobrać świec: '+str(ex))
        except Exception as ex:
            st.session_state['last_feed_error'] = f'Błąd aplikacji: {type(ex).__name__}'
            st.error('❌ Błąd pobierania danych: '+type(ex).__name__)
    elif st.session_state.get('last_feed_error'):
        st.error('❌ Ostatnia próba skanowania: '+st.session_state['last_feed_error'])
    snap=st.session_state.get('market_snap')
    src=st.session_state.get('source_override','BRAK')
    if snap is not None:
        if snap.epic!=instrument or snap.resolution!=tf:
            st.warning('Zmieniono instrument lub interwał: wykonaj NOWY SKAN przed decyzją.')
        else:
            c1,c2,c3,c4=st.columns(4)
            c1.metric('ŹRÓDŁO',src)
            c2.metric('OSTATNIA ZAMKNIĘTA',snap.confirmed_utc.strftime('%H:%M:%S UTC') if snap.confirmed_utc else 'BRAK')
            c3.metric('WIEK DANYCH',f'{snap.age_seconds:.0f} s' if snap.age_seconds is not None else 'BRAK')
            c4.metric('SPREAD',f'{snap.spread:.2f} pkt')
            df=indicators(snap.frame) if len(snap.frame)>=14 else snap.frame
            fig=go.Figure()
            fig.add_trace(go.Candlestick(x=df.index,yaxis='y',open=df.Open,high=df.High,low=df.Low,close=df.Close,name='Świece (MID)'))
            for col,color in [('EMA9','#e8c44f'),('EMA21','#6aa8ff'),('EMA50','#da77f2')]:
                if col in df:fig.add_trace(go.Scatter(x=df.index,y=df[col],name=col,line={'color':color,'width':1.4}))
            marks=historical_marks(snap.frame,strategy,max_bars=110)
            for direction,symbol,color,yshift in [('LONG','triangle-up','#48db98',-1),('SHORT','triangle-down','#ff6e79',1)]:
                match=marks[marks.action==direction]
                if not match.empty:
                    fig.add_trace(go.Scatter(x=match.time,y=match.price,mode='markers',
                        marker={'symbol':symbol,'size':15,'color':color},
                        name=f'{direction} • historyczny PAPER',
                        hovertemplate=f'{direction} • historyczny setup<extra></extra>'))
            fig.update_layout(height=570,xaxis_rangeslider_visible=False,template='plotly_dark',
                              paper_bgcolor='#111a2d',plot_bgcolor='#111a2d',legend_orientation='h',
                              margin={'l':15,'r':15,'t':30,'b':10})
            chart_slot=st.empty()
            st.caption(f'Historyczne strzałki PAPER (hipotetyczne setupy): {len(marks)}. Brak strzałek oznacza brak pełnego sygnału w testowanym fragmencie. Strzałki NIE oznaczają zrealizowanych transakcji.')
            st.caption('Wykres ze świec MID, nie cena wykonalna BID/ASK. Najnowsza świeca API została wykluczona z oceny strategii.')
            if snap.good:
                st.success(snap.reason)
            else:
                st.error('WAIT / FEED: '+snap.reason)
            ready=snap.good and src=='Capital.com DEMO REST'
            if src.startswith('CSV'):
                st.warning('CSV: wyłącznie symulacja edukacyjna. Nie ma sygnału do egzekucji live.')
            if snap.frame is not None and len(snap.frame)>=70:
                decision=decide(snap.frame,strategy,spread=snap.spread)
                if not ready: decision.action='WAIT';decision.reason='Brak zweryfikowanego, świeżego feedu LIVE/DEMO — tylko analiza historyczna'
                st.markdown(f'### {"🟢" if decision.action=="LONG" else "🔴" if decision.action=="SHORT" else "🟡"} {decision.action} — {strategy}')
                st.write(f'**Powód:** {decision.reason} | **Trend:** {decision.bias} | **ATR:** {decision.atr}')
                if decision.action!='WAIT':
                    m1,m2,m3,m4=st.columns(4)
                    m1.metric('Wejście (orientacyjne)',f'{decision.entry:.2f}')
                    m2.metric('Stop (symulacja)',f'{decision.stop:.2f}')
                    m3.metric('Cel (symulacja)',f'{decision.target:.2f}')
                    m4.metric('RR szac. netto',f'{decision.rr:.2f}')
                    # Lines belong to the CURRENT evaluated decision, not last archived trade.
                    for name,value in [('Wejście',decision.entry),('SL',decision.stop),('TP',decision.target)]:
                        fig.add_hline(y=value,annotation_text=name)
                chart_slot.plotly_chart(fig,use_container_width=True)
                if ready:
                    payload=numeric_context(snap.frame,decision,instrument,tf,snap.spread)
                    st.session_state['ai_context']=payload
                    key=hashlib.sha256(f'{instrument}|{tf}|{strategy}|{snap.confirmed_utc.isoformat()}|{decision.action}'.encode()).hexdigest()
                    try:
                        db=connect()
                        new=archive(db,key,snap.confirmed_utc.isoformat(),instrument,src,tf,decision)
                        reviewed=audit_prior_paper_signals(db,snap.frame,instrument,src,tf,snap.spread)
                        if new:st.caption('Nową decyzję PAPER zapisano do osobnego archiwum.')
                        if reviewed:st.caption(f'Audyt zakończył {len(reviewed)} wcześniejszych symulacji PAPER.')
                    except (OSError, sqlite3.Error) as ex:
                        st.error('Nie zapisano archiwum PAPER: '+type(ex).__name__)
                else:st.session_state.pop('ai_context',None)
                with st.expander('🧠 ASYSTENT AI — PRZECZYTAJ LICZBOWY WYKRES'):
                    question=st.text_input('Co chcesz wyjaśnić?',value='Dlaczego WAIT/LONG/SHORT i co unieważniłoby setup?')
                    if st.button('Zapytaj AI o te świece'):
                        if st.session_state.get('ai_context'):
                            st.write(answer_ai(secret('OPENAI_API_KEY'),secret('OPENAI_MODEL','gpt-5.4'),question,st.session_state['ai_context'], effort=secret('OPENAI_REASONING_EFFORT','high')))
                        else:st.warning('AI wymaga wiarygodnego, aktualnego zestawu zamkniętych świec Capital.com.')
            else:
                chart_slot.plotly_chart(fig,use_container_width=True)
                st.warning('Wykres dostępny, ale jest mniej niż 70 zamkniętych świec — brak sygnału.')
    else:st.warning('Nie ma danych. Włącz odczyt Capital.com lub dodaj własny CSV edukacyjny. Nie pokazuję fikcyjnych sygnałów.')

with lab_tab:
    st.subheader('🧪 TEST HISTORYCZNY — WERSJA EKSPERYMENTALNA')
    st.write('Porównaj dwie strategie na świecach z bieżącego źródła. Wynik NIE jest walk-forward / OOS i nie oznacza przewagi.')
    if snap is None or len(snap.frame)<85:
        st.warning('Potrzeba co najmniej 85 świec historycznych. Wczytaj dane.')
    else:
        slippage=st.slider('Poślizg na jedną stronę (pkt)',0.0,3.0,.25,.05)
        if st.button('▶️ PRZELICZ OBIE STRATEGIE'):
            for name in ['DRUGA FALA','EMA TREND']:
                trades=backtest(snap.frame,name,snap.spread,slippage)
                st.markdown('#### '+name)
                if trades.empty:st.info('Brak sygnałów w tej próbce.');continue
                finished=trades[trades.status.isin(['WIN','LOSS'])]
                st.metric('Wykonane symulacje z rozstrzygnięciem',len(finished))
                if not finished.empty:
                    cc1,cc2,cc3=st.columns(3)
                    cc1.metric('Win rate (mała próba!)',f'{(finished.status=="WIN").mean()*100:.1f}%')
                    cc2.metric('Suma punktów po kosztach',f'{finished.pnl_pts.sum():.2f}')
                    cc3.metric('Średnia pkt / trade',f'{finished.pnl_pts.mean():.2f}')
                st.dataframe(trades,use_container_width=True,hide_index=True)
            st.caption('Konserwatywnie: gdy SL i TP naruszone w jednej świecy, SL wygrywa; wejście po następnej świecy, z kosztem spreadu i poślizgu.')
    st.markdown('#### Nauka bota — kontrola jakości')
    try:
        report=paper_report(connect())
    except (OSError, sqlite3.Error) as ex:
        st.warning('Baza PAPER niedostępna: '+type(ex).__name__)
        report=[]
    if report:
        resolved=pd.DataFrame(report)
        active=resolved[resolved.status.isin(['WIN','LOSS','TIMEOUT'])]
        st.metric('Rozliczone forward PAPER (hipotetyczne)',len(active))
        if not active.empty:
            st.metric('Łączne pkt forward PAPER, po kosztach',f'{active.pnl_pts.sum():.2f}')
        st.dataframe(resolved,use_container_width=True,hide_index=True)
    else:st.info('Brak rozliczonych forward PAPER. Audyt działa przy kolejnym skanowaniu świec.')
    st.write('Tryb v0.1 zapisuje decyzje i rozlicza je po pojawieniu się kolejnych zamkniętych świec. **Nie optymalizuje automatycznie parametrów po 2–3 stratach**, bo to grozi przeuczeniem. Następny etap: walk-forward OOS i audyt niezależnych transakcji PAPER.')

with archive_tab:
    st.subheader('📚 OSOBNE ARCHIWUM — TYLKO TEN PROGRAM')
    try:
        hist=recent(connect(),200)
    except (OSError, sqlite3.Error) as ex:
        st.warning('Nie udało się odczytać archiwum PAPER: '+type(ex).__name__)
        hist=[]
    if hist:st.dataframe(pd.DataFrame(hist),use_container_width=True,hide_index=True)
    else:st.info('Brak zarejestrowanych decyzji PAPER.')
    st.caption('Zapis lokalny: data/fokus_paper.sqlite3. Streamlit Cloud może usuwać lokalne pliki po restarcie: do trwałej pracy 24/7 potrzebna zewnętrzna baza.')

with settings_tab:
    st.subheader('🔐 INTEGRACJE I PRAWDZIWY STAN')
    st.table(pd.DataFrame([
      ('Capital.com DEMO REST / OHLC','Skonfigurowano' if has_cap else 'Brak kluczy','Odczyt tylko po skanie'),
      ('OpenAI','Skonfigurowano' if secret('OPENAI_API_KEY') else 'Brak klucza','Tekstowa interpretacja tych samych świec'),
      ('Telegram','Klucze dostępne' if secret('TELEGRAM_BOT_TOKEN') and secret('TELEGRAM_CHAT_ID') else 'Nieskonfigurowany','Wysyłanie: jeszcze niezaimplementowane'),
      ('Niezależny worker','Kod dostępny','Wymaga uruchomienia na własnym hoście 24/7'),
      ('Bot sam się uczy','NIE','Tylko archiwum i odtwarzalny replay'),
      ('Wiadomości i kalendarz makro','NIE','Do wdrożenia; brak udawanego sentymentu'),
      ('Trading DEMO/REAL','BLOKADA','Brak endpointów POST /positions i DELETE /positions'),
    ],columns=['Element','Stan','Wyjaśnienie']))
    st.caption('Klucze podawaj w Secrets aplikacji, nigdy w publicznym GitHubie. API tutaj nie są trwale zapisywane w bazie.')
