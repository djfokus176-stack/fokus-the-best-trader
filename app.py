"""FOKU$ THE BEST TRADER v0.2 — wholly new Streamlit research dashboard."""
from __future__ import annotations
import hashlib
import sqlite3
import os
import time
from datetime import datetime, timezone
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from trader.market import CapitalReadOnly, FeedError, evaluate_snapshot, PERIOD
from trader.strategy import indicators, backtest
from trader.strategies_pro import decide_any, ALL_STRATEGIES
from trader.mtf import TIMEFRAMES, LABELS, evaluate_timeframes, filter_mtf_decision
from trader.research import chronological_report, rolling_oos, replay, stats
from trader.news_radar import fetch_headlines, fetch_bls_schedule, macro_blackout
from trader.storage import connect, archive, recent, recent_scan_decisions, audit_prior_paper_signals, paper_report, legacy_outcomes_count
from trader.assistant import numeric_context, answer_ai
from trader.visuals import historical_marks
from trader.runtime import current_feed_status, scan_delay_seconds
from trader.scan_monitor import scan_event, append_scan_log
from trader.auth import capital_credentials, active_credential, test_capital_login, test_openai_model, test_telegram_token
from trader.access import access_configured, password_matches
from trader.owner_auth import auth_mode, owner_email_configured, google_identity_matches, google_oidc_ready
from trader.market_dna import analyze_market

st.set_page_config(page_title='FOKU$ THE BEST TRADER',page_icon='📈',layout='wide')

# Security gate BEFORE any market scan, API test or paid OpenAI request.
# Community Cloud Sharing can be public even if the user is the only editor.
def _owner_password():
    if os.getenv('APP_ACCESS_PASSWORD'):
        return os.environ['APP_ACCESS_PASSWORD']
    try:
        return str(st.secrets.get('APP_ACCESS_PASSWORD',''))
    except (FileNotFoundError,KeyError):
        return ''

# Two owner-only modes:
# - google: Streamlit-native OIDC; browser remembers identity for ~30 days.
# - password: existing session-only password flow as safe fallback.
def _early_secret(name: str, default: str = '') -> str:
    if os.getenv(name) is not None:
        return os.environ[name].strip()
    try:
        return str(st.secrets.get(name, default)).strip()
    except (FileNotFoundError, KeyError):
        return default

try:
    _mode = auth_mode(_early_secret('APP_AUTH_MODE', 'password'))
except ValueError:
    st.error('Nieprawidłowy APP_AUTH_MODE. Dostęp zablokowany; wybierz password albo google w Secrets.')
    st.stop()

_owner_authorized = False
if _mode == 'google':
    _required_email = _early_secret('OWNER_EMAIL').lower()
    if not owner_email_configured(_required_email):
        st.error('Tryb Google zablokowany: podaj OWNER_EMAIL w Streamlit Secrets.')
        st.stop()
    try:
        _auth_settings = st.secrets.get('auth', {})
    except (FileNotFoundError,KeyError):
        _auth_settings = {}
    if not google_oidc_ready(_auth_settings):
        st.error('Google OIDC wymaga kompletu danych [auth] w Streamlit Secrets. Bez nich dostęp jest zablokowany.')
        st.stop()
    try:
        _is_google_logged_in = bool(st.user.is_logged_in)
    except (AttributeError, RuntimeError):
        st.error('Google OIDC niedostępne. Skonfiguruj sekcję [auth] w Streamlit Secrets.')
        st.stop()
    if _is_google_logged_in:
        _owner_authorized = google_identity_matches(st.user, _required_email)
        if not _owner_authorized:
            st.error('To konto Google nie jest zweryfikowanym właścicielem tej aplikacji.')
            if st.button('Wyloguj nieautoryzowane konto'):
                st.logout()
            st.stop()
    else:
        st.title('🔐 FOKU$ THE BEST TRADER')
        st.info('Zaloguj się raz przez Google. Streamlit może zapamiętać sesję w tej przeglądarce do 30 dni.')
        if st.button('🔓 Wejdź przez Google', type='primary'):
            st.login()
        st.stop()
else:
    _owner_secret = _owner_password()
    _owner_digest = hashlib.sha256(_owner_secret.encode('utf-8')).hexdigest()
    _owner_authorized = bool(
        access_configured(_owner_secret) and
        st.session_state.get('_owner_access_digest') == _owner_digest
    )
    if not _owner_authorized:
        st.title('🔐 FOKU$ THE BEST TRADER — dostęp właściciela')
        if not access_configured(_owner_secret):
            st.error('Brak APP_ACCESS_PASSWORD. Ustaw własne hasło w Streamlit Secrets.')
        else:
            st.caption('Tryb hasła: działa w sesji przeglądarki. Aby logować się rzadziej, skonfiguruj bezpieczniejszy tryb Google w Secrets.')
            with st.form('owner_access_form'):
                candidate = st.text_input('Hasło właściciela',type='password')
                submitted = st.form_submit_button('🔓 Otwórz terminal')
            if submitted:
                if password_matches(candidate,_owner_secret):
                    st.session_state['_owner_access_digest'] = _owner_digest
                    st.session_state.pop('_owner_bad_attempts',None)
                    st.rerun()
                else:
                    fails = int(st.session_state.get('_owner_bad_attempts',0))+1
                    st.session_state['_owner_bad_attempts'] = fails
                    st.error('Niepoprawne hasło.' if fails < 5 else 'Niepoprawne hasło (wiele prób).')
        st.stop()

st.markdown('''<style>
.stApp {background: #0c1020; color: #e7edf9;}
[data-testid="stMetric"] {background: #171f35; padding: 16px; border: 1px solid #2f3c5c; border-radius: 10px;}
.fokus {font-size: 2.0rem; font-weight: 800; color: #87c9ff; letter-spacing: 1px;}
.tag {background:#21304b;color:#c8defd;padding:5px 12px;border-radius:20px;font-weight:bold;}
</style>''',unsafe_allow_html=True)
st.markdown('<div class="fokus">⚡ FOKU$ THE BEST TRADER</div>',unsafe_allow_html=True)
st.markdown('<span class="tag">v0.3 MASTER RESEARCH</span> &nbsp; <span class="tag">PAPER / READ-ONLY</span> &nbsp; <span class="tag">BRAK AUTO TRADE</span>',unsafe_allow_html=True)
st.caption('Nowy program napisany od zera. Analiza świec, nie wizja AI i nie gwarancja zysku. Bez połączeń ze starym repozytorium.')


def secret(name,default=''):
    if os.getenv(name):return os.getenv(name).strip()
    try: return str(st.secrets.get(name,default)).strip()
    except (FileNotFoundError,KeyError):return default

with st.sidebar:
    st.header('⚙️ NOWE USTAWIENIA')
    if st.button('🔒 WYLOGUJ Z TERMINALU',use_container_width=True):
        for key in ('_owner_access_digest','_api_session_overrides',
                    '_capital_client','_capital_test','market_snap',
                    'ai_context','source_override','initial_scan_attempted'):
            st.session_state.pop(key,None)
        if _mode == 'google':
            st.logout()
        else:
            st.rerun()
    instrument=st.text_input('Instrument / EPIC Capital.com',value=secret('CAPITAL_EPIC','US500'))
    allow_live = secret('CAPITAL_ALLOW_LIVE','false').lower() in ('true','1','yes','on')
    available_environments = ['DEMO','LIVE'] if allow_live else ['DEMO']
    preferred_env = secret('CAPITAL_ENV','DEMO').upper().strip()
    if preferred_env not in available_environments:
        preferred_env = 'DEMO'
    capital_env = st.radio('Środowisko API Capital.com', available_environments,
        index=available_environments.index(preferred_env),
        help='LIVE wyłącznie za zgodą właściciela poprzez CAPITAL_ALLOW_LIVE w Secrets; TYLKO odczyt.',
        horizontal=True)
    if not allow_live:
        st.caption('🔒 LIVE wyłączone. Odblokowanie: CAPITAL_ALLOW_LIVE = true w Secrets.')
    if st.session_state.get('_prev_capital_env', capital_env) != capital_env:
        for k in ('_capital_client','market_snap','ai_context','source_override',
                  'initial_scan_attempted','last_feed_error','epic_matches','_capital_test'):
            st.session_state.pop(k, None)
    st.session_state['_prev_capital_env'] = capital_env
    tf=st.selectbox('Interwał',['MINUTE','MINUTE_5','MINUTE_15','HOUR'],format_func=lambda x:{'MINUTE':'M1','MINUTE_5':'M5','MINUTE_15':'M15','HOUR':'H1'}[x])
    strategy=st.selectbox('Strategia badawcza',ALL_STRATEGIES)
    st.toggle('🧭 Potwierdzenie M1/M5/M15/H1 (veto)',value=True,key='mtf_enabled',
        help='Bot nie pokaże nowego LONG/SHORT gdy nie ma 4 zgodnych i świeżych odczytów.')
    st.caption('Każda strategia jest HIPOTEZĄ PAPER, nie potwierdzonym systemem zarobkowym.')
    max_spread=st.slider('Maksymalny spread (pkt)',.2,5.0,2.0,.1)
    st.toggle('🔄 AUTO-SKAN — tylko gdy aplikacja otwarta',value=_early_secret('AUTO_SCAN_DEFAULT','true').lower() in ('true','1','yes'),key='auto_scan_active',
        help='Ocenia zamknięte świece co najmniej co 60 sekund. Nie jest usługą działającą 24/7.')
    st.selectbox('Interwał skanowania (sekundy)',(60,120,300),key='auto_scan_period')
    st.caption('AUTO-SKAN nie wykonuje zleceń. GPT-5.4 HIGH uruchamiasz osobno — płatne zapytania nie są wysyłane automatycznie.')
    st.markdown('---')
    with st.expander('🔑 KLUCZE API — TESTY / ZMIANY (już zapisane w Secrets)', expanded=False):
        st.caption('Wpisz tylko pola, które chcesz zmienić. Puste pola korzystają z zapisanych Streamlit Secrets. Wpisane tutaj dane żyją wyłącznie w tej sesji przeglądarki.')
        with st.form('fokus_credentials_login', clear_on_submit=True):
            entered_key=st.text_input('Capital.com: API Key',type='password')
            entered_login=st.text_input('Capital.com: Login / e-mail')
            entered_password=st.text_input('Capital.com: Hasło API (nie hasło strony)',type='password')
            entered_openai=st.text_input('OpenAI: API Key',type='password')
            entered_telegram=st.text_input('Telegram: Bot Token',type='password')
            entered_chat_id=st.text_input('Telegram: Chat ID (opcjonalny)')
            save_session=st.form_submit_button('🔐 ZAPISZ W SESJI',use_container_width=True)
            check_capital=st.form_submit_button('🧪 ZAPISZ I TESTUJ CAPITAL.COM',use_container_width=True)
        if save_session or check_capital:
            mapping={'CAPITAL_API_KEY':entered_key,'CAPITAL_IDENTIFIER':entered_login,
                     'CAPITAL_PASSWORD':entered_password,'OPENAI_API_KEY':entered_openai,
                     'TELEGRAM_BOT_TOKEN':entered_telegram,'TELEGRAM_CHAT_ID':entered_chat_id}
            changes={k:v.strip() for k,v in mapping.items() if v and v.strip()}
            overrides=dict(st.session_state.get('_api_session_overrides',{}))
            overrides.update(changes)
            st.session_state['_api_session_overrides']=overrides
            for k in ('_capital_client','market_snap','ai_context','source_override',
                      'initial_scan_attempted','last_feed_error','epic_matches'):
                st.session_state.pop(k,None)
            if save_session:
                st.success('Zapisano tymczasowo w tej sesji — NIE na dysku ani w GitHubie.')
        overrides=st.session_state.get('_api_session_overrides',{})
        cap_api_key,cap_identifier,cap_password=capital_credentials(secret,overrides)
        openai_api_key=active_credential('OPENAI_API_KEY',secret,overrides)
        telegram_token=active_credential('TELEGRAM_BOT_TOKEN',secret,overrides)
        has_cap=bool(cap_api_key and cap_identifier and cap_password)
        st.caption('Capital.com: '+('pola dostępne' if has_cap else 'brak wymaganych pól')
            +' | OpenAI: '+('jest klucz' if openai_api_key else 'brak klucza')
            +' | Telegram: '+('jest token' if telegram_token else 'brak tokenu'))
        if check_capital:
            try:
                client=test_capital_login(cap_api_key,cap_identifier,cap_password,capital_env)
                st.session_state['_capital_client']=client
                st.session_state['_capital_test']={'env':capital_env,'ok':True,
                    'message':f'✅ Capital.com {capital_env}: logowanie HTTP 200, otrzymano CST i X-SECURITY-TOKEN.'}
            except (FeedError,RuntimeError) as ex:
                st.session_state['_capital_test']={'env':capital_env,'ok':False,
                    'message':'❌ '+str(ex)}
            except Exception as ex:
                st.session_state['_capital_test']={'env':capital_env,'ok':False,
                    'message':'❌ Test Capital.com: '+type(ex).__name__}
        if st.session_state.get('_capital_test',{}).get('env')==capital_env:
            result=st.session_state['_capital_test']
            if result['ok']:
                st.success(result['message'])
            else:
                st.error(result['message'])
        if st.button('🧪 TEST OPENAI — DOSTĘP DO MODELU (bez generowania)',use_container_width=True):
            ok,msg=test_openai_model(openai_api_key,secret('OPENAI_MODEL','gpt-5.4'))
            (st.success if ok else st.error)(msg)
        if st.button('🧪 TEST TELEGRAM — TOKEN (bez wysyłania)',use_container_width=True):
            ok,msg=test_telegram_token(telegram_token)
            (st.success if ok else st.error)(msg)
        if st.button('🗑️ USUŃ TYMCZASOWE DANE SESJI',use_container_width=True):
            for key in ('_api_session_overrides','_capital_client','_capital_test',
                        'market_snap','ai_context','source_override',
                        'initial_scan_attempted','last_feed_error','epic_matches'):
                st.session_state.pop(key,None)
            st.rerun()
        st.info('Na stałe: Streamlit Cloud → My apps → Settings → Secrets. Ta aplikacja nie ma uprawnień do zmiany Secrets.')
        st.caption('Formularz dostępny dopiero po autoryzacji właściciela. Zalecane ograniczenie dostępu również w ustawieniach Sharing Streamlit Cloud.')
    overrides=st.session_state.get('_api_session_overrides',{})
    cap_api_key,cap_identifier,cap_password=capital_credentials(secret,overrides)
    openai_api_key=active_credential('OPENAI_API_KEY',secret,overrides)
    has_cap=bool(cap_api_key and cap_identifier and cap_password)
    if has_cap:
        st.success('✅ Capital.com: klucze dostępne — status logowania pokazuje test API')
        if st.button(f'🔎 SPRAWDŹ EPIC NA KONCIE {capital_env}',use_container_width=True):
            try:
                if '_capital_client' not in st.session_state:
                    st.session_state['_capital_client']=CapitalReadOnly(
                        cap_api_key,cap_identifier,cap_password,environment=capital_env)
                st.session_state['epic_matches']=st.session_state['_capital_client'].search_markets(instrument)
                if not st.session_state['epic_matches']:
                    st.warning('Nie znaleziono tego symbolu. Spróbuj hasła S&P lub SP500.')
            except FeedError as ex:
                st.error(str(ex))
        if st.session_state.get('epic_matches'):
            st.caption('Wyniki z Capital.com — wpisz poprawny EPIC w polu wyżej.')
            st.dataframe(st.session_state['epic_matches'],hide_index=True,use_container_width=True)
    else:
        st.warning('⚠️ Brak API Capital.com. Możesz analizować własny CSV.')
    st.info('Streamlit Cloud nie gwarantuje skanera działającego 24/7. Do tego potrzebny osobny worker na stale działającym hoście.')

market_tab,dna_tab,mtf_tab,strategies_tab,lab_tab,news_tab,reports_tab,archive_tab,settings_tab=st.tabs([
    '📊 TERMINAL','🧬 MARKET DNA','🧭 M1–H1','🎯 STRATEGIE',
    '🧪 LABORATORIUM','📰 NEWS / MAKRO','📈 RAPORTY',
    '📚 ARCHIWUM','⚙️ STATUS / API'])

@st.fragment(run_every="60s")
def auto_scan_heartbeat():
    """A page-open-only timer that triggers a full rerun for scan & archiving."""
    if not st.session_state.get('auto_scan_active',False):
        return
    interval=scan_delay_seconds(st.session_state.get('auto_scan_period',60))
    tick=time.monotonic()
    previous=st.session_state.get('_last_auto_pulse')
    if previous is None:
        st.session_state['_last_auto_pulse']=tick
        return
    if tick-previous >= interval-2:
        st.session_state['_last_auto_pulse']=tick
        st.session_state['_scheduled_scan']=True
        st.rerun(scope='app')

auto_scan_heartbeat()

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
        st.caption('Przy otwarciu strony wykonuję jedną próbę pobrania. Jeśli włączysz AUTO-SKAN, program ponowi odczyt co 60/120/300 s podczas otwartej sesji.')
        if st.session_state.get('auto_scan_active'):
            st.success(f"🟢 AUTO-SKAN WŁĄCZONY: co {st.session_state.get('auto_scan_period',60)} s (tylko aktywna sesja przeglądarki)")
        else:
            st.info('⚪ TRYB RĘCZNY — nowe świece wymagają ponownego skanowania.')
    with col2:
        st.markdown('#### 🎯 FOKU$ MARKET TERMINAL')
        st.caption('Świece MID • EMA9/21/50 • SL/TP PAPER • potwierdzenie 4 interwałów • analiza bez zleceń')
        st.info('Dane wykresu i silnika są wspólne. GPT czyta dane liczbowe, a nie obraz wykresu.')
    auto_scan = bool(has_cap and csv is None and not st.session_state.get('initial_scan_attempted') and st.session_state.get('market_snap') is None)
    if auto_scan:
        st.session_state['initial_scan_attempted'] = True
        st.info(f'🔄 Pierwsza próba pobrania świec z Capital.com {capital_env}...')
    scheduled_scan = bool(st.session_state.pop('_scheduled_scan',False)
        and st.session_state.get('auto_scan_active',False) and has_cap and csv is None)
    if load or auto_scan or scheduled_scan:
        scan_trigger='MANUAL' if load else ('STARTUP' if auto_scan else 'AUTO')
        scan_requested=datetime.now(timezone.utc)
        previous_snap=st.session_state.get('market_snap')
        if previous_snap is not None and (
            previous_snap.epic != instrument or previous_snap.resolution != tf
            or previous_snap.source not in (
                'Capital.com '+capital_env+' REST',
                'CSV NAUKA (NIE LIVE)' if csv is not None else 'Capital.com '+capital_env+' REST')
        ):
            previous_snap=None
        st.session_state['last_scan_utc']=scan_requested.isoformat()
        st.session_state['_scan_attempt_count']=int(st.session_state.get('_scan_attempt_count',0))+1
        try:
            st.session_state.pop('last_feed_error', None)
            if csv is not None:
                raw=read_csv(csv)
                st.session_state['market_snap']=evaluate_snapshot(raw,instrument,tf,max_spread=max_spread)
                st.session_state['source_override']='CSV NAUKA (NIE LIVE)'
            elif has_cap:
                if '_capital_client' not in st.session_state:
                    st.session_state['_capital_client']=CapitalReadOnly(
                        cap_api_key,cap_identifier,cap_password,environment=capital_env)
                st.session_state['market_snap']=st.session_state['_capital_client'].candles(
                    instrument,tf,count=350,max_spread=max_spread)
                st.session_state['source_override']=f'Capital.com {capital_env} REST'
                if st.session_state.get('mtf_enabled',False):
                    import time as _clock
                    client=st.session_state['_capital_client']
                    cache_key=(instrument,capital_env)
                    if st.session_state.get('_mtf_cache_key')!=cache_key:
                        st.session_state['mtf_snapshots']={}
                        st.session_state['_mtf_due']={}
                        st.session_state['mtf_errors']={}
                    st.session_state['_mtf_cache_key']=cache_key
                    snapshots=dict(st.session_state.get('mtf_snapshots',{}))
                    due=dict(st.session_state.get('_mtf_due',{}))
                    errors=dict(st.session_state.get('mtf_errors',{}))
                    stamp=_clock.monotonic()
                    for horizon in TIMEFRAMES:
                        if horizon==tf:
                            snapshots[horizon]=st.session_state['market_snap']
                            due[horizon]=stamp
                            errors.pop(horizon,None)
                            continue
                        seconds=PERIOD[horizon]
                        if horizon not in snapshots or stamp-due.get(horizon,0)>=max(60,seconds)-2:
                            try:
                                snapshots[horizon]=client.candles(instrument,horizon,
                                    count=350,max_spread=max_spread)
                                due[horizon]=stamp
                                errors.pop(horizon,None)
                            except (FeedError,ValueError) as ex:
                                snapshots.pop(horizon,None)
                                errors[horizon]=str(ex)[:180]
                    st.session_state['mtf_snapshots']=snapshots
                    st.session_state['_mtf_due']=due
                    st.session_state['mtf_errors']=errors
            else:
                st.error('Brak Capital.com API lub CSV. NIE generuję sztucznych cen.')
            obtained=st.session_state.get('market_snap')
            market_status='UNKNOWN'
            if obtained is not None and not obtained.good and has_cap and csv is None:
                try:
                    market_status=st.session_state['_capital_client'].market_state(instrument)
                except (FeedError,ValueError):
                    market_status='UNKNOWN (status API niedostępny)'
            st.session_state['_market_status']=market_status
            record=scan_event(scan_trigger,previous_snap,obtained,
                              market_status=market_status,requested_utc=scan_requested)
            st.session_state['_scan_log']=append_scan_log(st.session_state.get('_scan_log'),record)
            st.session_state['_scan_last_result']=record
        except (FeedError,ValueError) as ex:
            record=scan_event(scan_trigger,previous_snap,None,
                error=f'{type(ex).__name__}: {str(ex)}',requested_utc=scan_requested)
            st.session_state['_scan_log']=append_scan_log(st.session_state.get('_scan_log'),record)
            st.session_state['_scan_last_result']=record
            st.session_state.pop('market_snap', None)
            st.session_state.pop('ai_context', None)
            st.session_state['last_feed_error'] = str(ex)
            st.error('❌ Nie udało się pobrać świec: '+str(ex))
        except Exception as ex:
            record=scan_event(scan_trigger,previous_snap,None,
                error=f'Błąd aplikacji: {type(ex).__name__}',requested_utc=scan_requested)
            st.session_state['_scan_log']=append_scan_log(st.session_state.get('_scan_log'),record)
            st.session_state['_scan_last_result']=record
            st.session_state.pop('market_snap', None)
            st.session_state.pop('ai_context', None)
            st.session_state['last_feed_error'] = f'Błąd aplikacji: {type(ex).__name__}'
            st.error('❌ Błąd pobierania danych: '+type(ex).__name__)
    elif st.session_state.get('last_feed_error'):
        st.error('❌ Ostatnia próba skanowania: '+st.session_state['last_feed_error'])
    snap=st.session_state.get('market_snap')
    src=st.session_state.get('source_override','BRAK')
    if st.session_state.get('last_scan_utc'):
        st.caption("Ostatnia próba odczytu (UTC): "+st.session_state['last_scan_utc'])
    last_record=st.session_state.get('_scan_last_result')
    if last_record:
        if last_record['api_result']=='OK':
            status_description='NOWA ŚWIECA' if last_record['new_candle'] else 'BRAK NOWEJ ŚWIECY'
            if last_record['bar_result']=='STALE_OR_BLOCKED':
                status_description='DANE NIEAKTUALNE / BLOKADA SYGNAŁÓW'
            st.info(f"🛰️ SKAN #{st.session_state.get('_scan_attempt_count',0)} | "
                f"wyzwalacz: {last_record['trigger']} | API: OK | "
                f"wynik: {status_description} | rynek: {last_record['market_status']}")
            if last_record['market_status']=='CLOSED':
                st.warning('Capital.com zgłasza CLOSED: prawdopodobnie przerwa lub zamknięty instrument. Skaner może działać poprawnie, ale nie ma nowych zamkniętych świec. Pozostaje WAIT.')
            elif last_record['bar_result']=='STALE_OR_BLOCKED':
                st.warning('API odpowiedziało, ale ostatnia zamknięta świeca nie spełnia wymagań świeżości. Nie wyświetlam sygnału LONG/SHORT.')
        else:
            st.error('🛰️ SKAN: problem komunikacji z API — sprawdź dziennik prób poniżej.')
    with st.expander('🛠️ DIAGNOSTYKA AUTO-SKAN — HISTORIA PRÓB'):
        st.caption('To historia TYLKO tej sesji przeglądarki. Każdy wpis oznacza faktyczną próbę, nie automatyczną deklarację. Nie zapisuję haseł ani kluczy.')
        st.metric('Próby pobrania w tej sesji',st.session_state.get('_scan_attempt_count',0))
        if st.session_state.get('_scan_log'):
            st.dataframe(pd.DataFrame(st.session_state['_scan_log'][::-1]),hide_index=True,
                use_container_width=True)
        else:
            st.info('Brak prób skanowania w tej sesji.')
    if snap is not None:
        if snap.epic!=instrument or snap.resolution!=tf:
            st.warning('Zmieniono instrument lub interwał: wykonaj NOWY SKAN przed decyzją.')
        else:
            c1,c2,c3,c4=st.columns(4)
            c1.metric('ŹRÓDŁO',src)
            c2.metric('OSTATNIA ZAMKNIĘTA',snap.confirmed_utc.strftime('%H:%M:%S UTC') if snap.confirmed_utc else 'BRAK')
            current_ready,current_reason,current_age=current_feed_status(snap,src)
            c3.metric('WIEK DANYCH (teraz)',f'{current_age:.0f} s' if current_age is not None else 'BRAK')
            signal_banner=st.empty()
            c4.metric('SPREAD zamkniętej świecy',f'{snap.spread:.2f} pkt')
            if snap.quote_spread is not None:
                st.caption(f'Spread najnowszej świecy (może być niezamknięta): {snap.quote_spread:.2f} pkt. Do logiki strategii używany jest spread świecy zamkniętej.')
            df=indicators(snap.frame) if len(snap.frame)>=14 else snap.frame
            fig=go.Figure()
            fig.add_trace(go.Candlestick(x=df.index,yaxis='y',open=df.Open,high=df.High,low=df.Low,close=df.Close,name='Świece (MID)'))
            for col,color in [('EMA9','#e8c44f'),('EMA21','#6aa8ff'),('EMA50','#da77f2')]:
                if col in df:fig.add_trace(go.Scatter(x=df.index,y=df[col],name=col,line={'color':color,'width':1.4}))
            dna = analyze_market(snap.frame) if len(snap.frame)>=70 else None
            if dna is not None:
                if dna.swing_high is not None:
                    fig.add_hline(y=dna.swing_high,line_color='#b68eff',line_dash='dot',
                        opacity=.55,annotation_text='Potwierdzony swing HIGH')
                if dna.swing_low is not None:
                    fig.add_hline(y=dna.swing_low,line_color='#7fbf98',line_dash='dot',
                        opacity=.55,annotation_text='Potwierdzony swing LOW')
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
            if current_ready:
                st.success('✅ FEED AKTUALNY: '+current_reason)
            else:
                st.warning('🟡 WAIT / DANE: '+current_reason)
            ready=current_ready
            if src.startswith('CSV'):
                st.warning('CSV: wyłącznie symulacja edukacyjna. Nie ma sygnału do egzekucji live.')
            if snap.frame is not None and len(snap.frame)>=70:
                decision=decide_any(snap.frame,strategy,spread=snap.spread)
                if ready and st.session_state.get('mtf_enabled',False):
                    decision,_mtf_rows=filter_mtf_decision(
                        decision,st.session_state.get('mtf_snapshots',{}),
                        asof=snap.confirmed_utc)
                if ready:
                    blackout,note=macro_blackout(st.session_state.get('_macro_calendar',[]))
                    if blackout:
                        from dataclasses import replace as _replace
                        decision=_replace(decision,action='WAIT',entry=None,
                            stop=None,target=None,rr=None,reason=note)
                if not ready: decision.action='WAIT';decision.reason='Brak zweryfikowanego, świeżego feedu LIVE/DEMO — tylko analiza historyczna'
                banner=f"{decision.action} | {strategy} | {decision.reason}"
                if decision.action=='LONG':
                    signal_banner.success('🟢 BIEŻĄCA OCENA PAPER: '+banner)
                elif decision.action=='SHORT':
                    signal_banner.error('🔴 BIEŻĄCA OCENA PAPER: '+banner)
                else:
                    signal_banner.warning('🟡 BIEŻĄCA OCENA: '+banner)
                st.markdown(f'### {"🟢" if decision.action=="LONG" else "🔴" if decision.action=="SHORT" else "🟡"} {decision.action} — {strategy}')
                st.write(f'**Powód:** {decision.reason} | **Trend:** {decision.bias} | **ATR:** {decision.atr:.2f}' if decision.atr is not None else f'**Powód:** {decision.reason} | **Trend:** {decision.bias} | **ATR:** BRAK')
                if dna is not None:
                    st.info(f'🧬 MARKET DNA (kontekst badawczy): {dna.structure} / {dna.regime} / {dna.event}. To NIE zmienia aktualnej decyzji strategii.')
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
                    key=hashlib.sha256(f'{src}|{instrument}|{tf}|{strategy}|{snap.confirmed_utc.isoformat()}|{decision.action}'.encode()).hexdigest()
                    try:
                        db=connect()
                        new=archive(db,key,snap.confirmed_utc.isoformat(),instrument,src,tf,decision,spread=snap.spread)
                        reviewed=audit_prior_paper_signals(db,snap.frame,instrument,src,tf,snap.spread)
                        if new:
                            st.caption('Zapisano kandydata PAPER LONG/SHORT.' if decision.action in ('LONG','SHORT') else 'Zapisano WAIT w oddzielnym dzienniku skanów (nie w transakcjach).')
                        if reviewed:st.caption(f'Audyt zakończył {len(reviewed)} wcześniejszych symulacji PAPER.')
                    except (OSError, sqlite3.Error) as ex:
                        st.error('Nie zapisano archiwum PAPER: '+type(ex).__name__)
                else:st.session_state.pop('ai_context',None)
                with st.expander('🧠 ASYSTENT AI — PRZECZYTAJ LICZBOWY WYKRES'):
                    question=st.text_input('Co chcesz wyjaśnić?',value='Dlaczego WAIT/LONG/SHORT i co unieważniłoby setup?')
                    if st.button('Zapytaj AI o te świece'):
                        if st.session_state.get('ai_context'):
                            st.write(answer_ai(openai_api_key,secret('OPENAI_MODEL','gpt-5.4'),question,st.session_state['ai_context'], effort=secret('OPENAI_REASONING_EFFORT','high')))
                        else:st.warning('AI wymaga wiarygodnego, aktualnego zestawu zamkniętych świec Capital.com.')
            else:
                chart_slot.plotly_chart(fig,use_container_width=True)
                st.warning('Wykres dostępny, ale jest mniej niż 70 zamkniętych świec — brak sygnału.')
    else:
        st.warning('Nie ma danych. Włącz odczyt Capital.com lub dodaj własny CSV edukacyjny. Nie pokazuję fikcyjnych sygnałów.')


with dna_tab:
    st.subheader('🧬 FOKU$ MARKET DNA — analiza struktury rynku')
    st.caption('Moduł wykorzystuje WYŁĄCZNIE OHLC ze świec zamkniętych. Nie analizuje arkusza zleceń, nie oblicza prawdopodobieństwa trafienia i nie zmienia strategii.')
    if snap is not None:
        context_is_current,context_note,_=current_feed_status(snap,src)
        if context_is_current:
            st.success('🟢 MARKET DNA: aktualny zbiór świec (nie prognoza).')
        else:
            st.warning('🟡 MARKET DNA — ANALIZA HISTORYCZNA, NIE LIVE: '+context_note)
    if snap is None:
        st.info('Zeskanuj świece Capital.com w pierwszej zakładce.')
    elif snap.epic != instrument or snap.resolution != tf:
        st.warning('Zmień z powrotem instrument i interwał lub wykonaj nowy skan.')
    elif len(snap.frame) < 70:
        st.warning('Wymagane minimum 70 zamkniętych świec.')
    else:
        try:
            context=analyze_market(snap.frame)
            st.caption('Analiza ostatniej ZAMKNIĘTEJ świecy: '+
                snap.frame.index[-1].strftime('%Y-%m-%d %H:%M UTC'))
            a,b,c=st.columns(3)
            a.metric('Struktura',context.structure)
            b.metric('Reżim rynku',context.regime)
            c.metric('Zdarzenie',context.event)
            m1,m2,m3,m4=st.columns(4)
            m1.metric('Potwierdzony swing HIGH',f'{context.swing_high:.2f}' if context.swing_high is not None else 'BRAK')
            m2.metric('Potwierdzony swing LOW',f'{context.swing_low:.2f}' if context.swing_low is not None else 'BRAK')
            m3.metric('Efektywność ruchu (0–1)',f'{context.efficiency:.2f}')
            m4.metric('ATR / mediana ATR',f'{context.volatility_ratio:.2f}')
            st.info(context.explanation)
            st.warning('SWEEP/BOS to zdarzenia cenowe do dalszej weryfikacji, a nie rekomendacja wejścia. Testy OOS i koszty transakcyjne dopiero przed nami.')
        except ValueError as ex:
            st.error(str(ex))

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
        db_for_report=connect()
        report=paper_report(db_for_report)
        legacy_count=legacy_outcomes_count(db_for_report)
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
    else:st.info('Brak NOWYCH rozliczeń forward PAPER v2. Audyt ruszy przy kolejnych świecach.')
    if 'legacy_count' in locals() and legacy_count:
        st.warning(f'Stare rozliczenia PAPER (wersja 1): {legacy_count} — zachowane, ale WYŁĄCZONE z nowych statystyk. Nie przeliczam ich bez oryginalnych danych.')
    st.write('Tryb v0.2 zapisuje decyzje i rozlicza je po pojawieniu się kolejnych zamkniętych świec. **Nie optymalizuje automatycznie parametrów po 2–3 stratach**, bo to grozi przeuczeniem. Następny etap: walk-forward OOS i audyt niezależnych transakcji PAPER.')

with archive_tab:
    st.subheader('📚 OSOBNE ARCHIWUM — TYLKO TEN PROGRAM')
    try:
        hist=recent(connect(),200)
    except (OSError, sqlite3.Error) as ex:
        st.warning('Nie udało się odczytać archiwum PAPER: '+type(ex).__name__)
        hist=[]
    if hist:st.dataframe(pd.DataFrame(hist),use_container_width=True,hide_index=True)
    else:st.info('Brak kandydatów LONG/SHORT PAPER.')
    with st.expander('🟡 Odrzucone sygnały / WAIT — osobny dziennik'):
        try:
            waits=recent_scan_decisions(connect(),100)
            if waits:st.dataframe(pd.DataFrame(waits),use_container_width=True,hide_index=True)
            else:st.info('Brak decyzji WAIT w odrębnym dzienniku.')
        except (OSError,sqlite3.Error) as ex:
            st.warning('Nie udało się odczytać dziennika WAIT: '+type(ex).__name__)
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
