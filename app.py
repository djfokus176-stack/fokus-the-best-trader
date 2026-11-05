"""FOKU$ THE BEST TRADER — owner-only PAPER market research terminal."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import os
import time
from datetime import datetime, timezone
from dataclasses import replace as dataclass_replace
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from trader.market import CapitalReadOnly, FeedError, evaluate_snapshot, PERIOD
from trader.strategy import indicators, backtest
from trader.strategies_pro import decide_any, ALL_STRATEGIES
from trader.auto_strategy import AUTO_MODE, evaluate_auto
from trader.mtf import TIMEFRAMES, LABELS, evaluate_timeframes, filter_mtf_decision
from trader.research import chronological_report, rolling_oos, replay, stats
from trader.mtf_replay import compare_mtf_on_m1_csv
from trader.news_radar import fetch_headlines, fetch_bls_schedule, macro_blackout
from trader.storage import connect, archive, recent, recent_scan_decisions, audit_prior_paper_signals, paper_report, legacy_outcomes_count, archive_candles, load_candles
from trader.assistant import numeric_context, answer_ai
from trader.csv_data import read_ohlc_csv
from trader.runtime import current_feed_status, scan_delay_seconds
from trader.scan_monitor import scan_event, append_scan_log
from trader.chat_ui import append_message, renderable_history, preview_context
from trader.paper_lifecycle import (
    ensure_tables as ensure_paper_v3, queue_paper, progress_paper,
    active_position, recent_positions, recent_events)
from trader.paper_display import annotate_open_paper,annotate_paper_history
from trader.paper_sounds import new_paper_events,wav_notice,SOUND_EVENTS,alert_audio
from trader.paper_reporting import daily_weekly,performance_by_policy
from trader.remote_checkpoint import RemoteCheckpoint,remote_view_db,RemoteError,dump_state
from trader.telegram_alerts import dispatch_alerts, record_stale_event
from trader.auth import capital_credentials, active_credential, test_capital_login, test_openai_model, test_telegram_token
from trader.access import access_configured, password_matches
from trader.owner_auth import auth_mode, owner_email_configured, google_identity_matches, google_oidc_ready
from trader.market_dna import analyze_market
from trader.feed_audit import inspect_labels,compare_clock_observations

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

# Drop pre-deploy market client/snapshot objects; their candle clock may be
# OPEN-labelled instead of the new internal CLOSE-labelled convention.
_CLOCK_SCHEMA='capital-open-to-close-2026-11-v1'
if st.session_state.get('_capital_clock_schema')!=_CLOCK_SCHEMA:
    for k in ('_capital_client','market_snap','mtf_snapshots','_mtf_due',
              'mtf_errors','initial_scan_attempted','source_override',
              'ai_context','_last_raw_time_audit','_scan_last_result'):
        st.session_state.pop(k,None)
    st.session_state['_capital_clock_schema']=_CLOCK_SCHEMA

st.markdown('''<style>
.stApp {background: #0c1020; color: #e7edf9;}
[data-testid="stMetric"] {background: #171f35; padding: 16px; border: 1px solid #2f3c5c; border-radius: 10px;}
.fokus {font-size: 2.4rem; font-weight: 850; color: #88d9ff; letter-spacing: .7px; text-shadow: 0 0 20px #09608077;}
div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {border-color:#273857;}
div[data-testid="stTabs"] button {font-weight:650; padding:13px 17px; border-radius:10px 10px 0 0;}
div[data-testid="stButton"] button[kind="primary"] {background:#1558aa;border:1px solid #56bcff;color:white;font-weight:750;border-radius:11px;}
section[data-testid="stSidebar"] {background:#0b162b;}
[data-testid="stMetricValue"] {color:#9fe3ff;}
div[data-testid="stAlert"] {border-radius:11px;}
.tag {background:#21304b;color:#c8defd;padding:5px 12px;border-radius:20px;font-weight:bold;}
</style>''',unsafe_allow_html=True)
st.markdown('<div class="fokus">⚡ FOKU$ THE BEST TRADER</div>',unsafe_allow_html=True)
st.markdown('<span class="tag">v0.3 MASTER RESEARCH</span> &nbsp; <span class="tag">PAPER / READ-ONLY</span> &nbsp; <span class="tag">BRAK AUTO TRADE</span>',unsafe_allow_html=True)
st.caption('Nowy program napisany od zera. Analiza świec, nie wizja AI i nie gwarancja zysku. Bez połączeń ze starym repozytorium.')


def secret(name,default=''):
    if os.getenv(name):return os.getenv(name).strip()
    try: return str(st.secrets.get(name,default)).strip()
    except (FileNotFoundError,KeyError):return default


def remote_paper_view_enabled():
    return secret('FOKUS_REMOTE_VIEW_ENABLED','false').lower() in ('true','1','yes')


def paper_view_db():
    if remote_paper_view_enabled():
        # Uses only Streamlit SERVER Secrets, after owner login.
        # Remote database is read-only for the dashboard; worker is
        # the one authoritative writer. Never fallback to local silently.
        remote=RemoteCheckpoint(secret('FOKUS_SUPABASE_URL'),
                                secret('FOKUS_SUPABASE_SECRET_KEY'))
        version,payload=remote.fetch()
        db=sqlite3.connect(':memory:')
        from trader.remote_checkpoint import restore_state
        restore_state(db,payload)
        st.session_state['_paper_remote_version']=version
        st.session_state['_paper_remote_meta']=payload.get('meta') or {}
        st.session_state['_paper_remote_auto_ai']=payload.get('auto_ai') or {}
        st.session_state['_paper_remote_candidates']=payload.get('candidate_feed') or []
        return db
    return connect()


def manual_ai_request(question, payload, effort=None):
    # Per-browser session cost limiter, NOT a global API expenditure cap.
    if len(str(question).strip()) > 800:
        return '⚠️ Pytanie przekracza limit 800 znaków. Skróć je. Zapytanie NIE zostało wysłane.'
    selected_effort=effort or st.session_state.get('ai_effort_choice','medium')
    if selected_effort not in ('medium','high'):
        return 'Niepoprawny wysiłek AI (dozwolone medium/high). Zapytanie NIE zostało wysłane.'
    try:
        limit=min(40,max(1,int(secret('OPENAI_MAX_CALLS_PER_SESSION','12'))))
    except ValueError:
        limit=12
    count=int(st.session_state.get('_paid_ai_requests',0))
    if count>=limit:
        return f'LIMIT: wykorzystano {count}/{limit} ręcznych zapytań AI w tej sesji. Żadne kolejne zapytanie nie zostało wysłane.'
    st.session_state['_paid_ai_requests']=count+1
    return answer_ai(openai_api_key,secret('OPENAI_MODEL','gpt-5.4'),question,
                     payload,effort=selected_effort)

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
    strategy=st.selectbox('Tryb analizy / strategia', (AUTO_MODE,)+ALL_STRATEGIES, index=0,
        help='AUTO ocenia sześć hipotez na tym samym wykresie. Wymaga min. dwóch zgodnych i kompletnych M1/M5/M15/H1; konflikt = WAIT. Nie jest to model uczący się ani zlecenie.')
    if strategy==AUTO_MODE:
        st.caption('🤖 AUTO: 6 strategii, minimum 2 zgodne, brak przeciwnego LONG/SHORT, obowiązkowy filtr MTF. Własna ocena PAPER, nie autotrading.')
    st.toggle('🧭 Potwierdzenie M1/M5/M15/H1 (veto)',value=True,key='mtf_enabled',
        help='Bot nie pokaże nowego LONG/SHORT gdy nie ma 4 zgodnych i świeżych odczytów.')
    st.caption('Każda strategia jest HIPOTEZĄ PAPER, nie potwierdzonym systemem zarobkowym.')
    max_spread=st.slider('Maksymalny spread (pkt)',.2,5.0,2.0,.1)
    st.toggle('🔄 AUTO-SKAN — tylko gdy aplikacja otwarta',value=_early_secret('AUTO_SCAN_DEFAULT','true').lower() in ('true','1','yes'),key='auto_scan_active',
        help='Ocenia zamknięte świece co najmniej co 60 sekund. Nie jest usługą działającą 24/7.')
    st.selectbox('⏱️ Częstotliwość AUTO-SKAN (aktywna strona)',
        options=(5,15,30,60,120,300),index=3,
        format_func=lambda secs: f'co {secs} sekund' if secs < 60 else f'co {secs // 60} min',
        key='auto_scan_period',
        help='Ręcznie wybierasz jak często odpytywać Capital.com DEMO i oceniać 6 strategii. '
             '5 s zwiększa ruch REST/API oraz obciążenie Streamlit. Zamknięta świeca M1 '
             'pojawia się zwykle raz na minutę; to nie jest streaming ticków ani nowe świece co 5 s.')
    st.caption('⏲️ AUTO-SKAN co '+str(st.session_state['auto_scan_period'])+
               ' s, tylko przy otwartej stronie. GitHub worker niezależnie co około 5 minut.')
    if st.session_state['auto_scan_period'] < 60:
        st.caption('⚠️ Tryb szybki odpytuje Capital.com częściej. W przypadku HTTP 429 '
                   'wybierz 60 s; M1 nadal ma nowe zamknięcie najwyżej raz na minutę.')
    st.toggle('🔔 DŹWIĘKI PAPER: otwarcie / TP / SL / timeout',
        value=False,key='paper_audio_enabled',
        help='Wymaga interakcji z przeglądarką. Dźwięk dotyczy tylko nowych '
             'zdarzeń potwierdzonych w archiwum PAPER; przeglądarka może go zablokować. '
             'Nie oznacza rzeczywistych transakcji.')
    st.radio('🎙️ Rodzaj alertów PAPER',('Głos ElevenLabs (nagrania MP3)','Tony'),
        horizontal=True,key='paper_audio_mode',
        help='Własne krótkie pliki MP3 z assets/voices w repozytorium. '
             'Bez dodatkowych zapytań do ElevenLabs; brakujący klip zastępuje ton.')
    sound_preview={
        'Otwarcie LONG':('PAPER_OPEN','LONG'),
        'Otwarcie SHORT':('PAPER_OPEN','SHORT'),
        'Zamknij — głos ogólny':('PAPER_CLOSE_TP',None),
        'Stop loss / Zamknij':('PAPER_CLOSE_SL',None),
        'Zamknięcie po czasie':('PAPER_TIMEOUT',None),
        'Przesunięcie SL':('PAPER_TRAIL_SL',None),
        'Wydłużenie TP':('PAPER_EXTEND_TP',None),
    }
    test_choice=st.selectbox('🎧 Sprawdź nagranie',tuple(sound_preview),key='paper_sound_preview')
    if st.button('🔊 PRZETESTUJ DŹWIĘK (bez pozycji)',key='test_paper_sound'):
        sound_kind,sound_side=sound_preview[test_choice]
        audio,mime,used=alert_audio(sound_kind,sound_side,
            voice_enabled=st.session_state.get('paper_audio_mode')=='Głos ElevenLabs (nagrania MP3)')
        st.caption('Test '+('GŁOSU ELEVENLABS' if used=='VOICE' else 'TONU')+
                   ', NIE otwiera PAPER ani zlecenia. '
                   'Jeśli nie ma pliku MP3, odtwarzam ton zastępczy.')
        st.audio(audio,format=mime,autoplay=True)
    st.caption('AUTO-SKAN nie wykonuje zleceń. Płatne AI jest ręczne w CZAT AI; osobny worker może opcjonalnie uruchamiać limitowane komentarze GPT po włączeniu w GitHub.')
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
    st.caption(f"🧠 AI: {st.session_state.get('_paid_ai_requests',0)} ręcznych zapytań w sesji. Opcjonalne automatyczne analizy workera są rozliczane i limitowane osobno.")
    st.info('Streamlit Cloud nie gwarantuje skanera działającego 24/7. Do tego potrzebny osobny worker na stale działającym hoście.')

market_tab,chat_tab,dna_tab,mtf_tab,strategies_tab,lab_tab,news_tab,reports_tab,archive_tab,settings_tab=st.tabs([
    '📊 TERMINAL','🤖 CZAT AI','🧬 MARKET DNA','🧭 M1–H1','🎯 STRATEGIE',
    '🧪 LABORATORIUM','📰 NEWS / MAKRO','📈 RAPORTY',
    '📚 ARCHIWUM','⚙️ STATUS / API'])

@st.fragment(run_every="5s")
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
        if st.session_state.get('_ai_busy',False):
            return  # Never interrupt the current manually paid AI request.
        st.session_state['_last_auto_pulse']=tick
        st.session_state['_scheduled_scan']=True
        st.rerun(scope='app')

auto_scan_heartbeat()

def read_csv(file):
    return read_ohlc_csv(file)

with market_tab:
    col1,col2=st.columns([1,2])
    with col1:
        csv=st.file_uploader('Opcjonalnie własne dane OHLC CSV (wyłącznie do nauki / replay)',type=['csv'])
        load=st.button('🔄 SKANUJ ŚWIECE',type='primary',use_container_width=True)
        st.caption('AUTO-SKAN: odświeżanie według wybranej częstotliwości 5–300 s, gdy strona jest otwarta. GitHub Actions: osobno, około co 5 min.')
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
    actual_scan_this_rerun=bool(load or auto_scan or scheduled_scan)
    if actual_scan_this_rerun:
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
                st.session_state['market_snap']=evaluate_snapshot(raw,instrument,tf,max_spread=max_spread,source='CSV NAUKA (NIE LIVE)')
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
            if obtained is not None and has_cap and csv is None:
                try:
                    market_status=st.session_state['_capital_client'].market_state(instrument)
                except (FeedError,ValueError):
                    market_status='UNKNOWN (status API niedostępny)'
            st.session_state['_market_status']=market_status
            # Save each CLOSED Capital series without mixing EPIC, source or TF.
            try:
                history_db=connect()
                candidates=(st.session_state.get('mtf_snapshots',{})
                    if st.session_state.get('mtf_enabled',False) and csv is None
                    else {tf:st.session_state.get('market_snap')})
                saved=0
                for saved_tf,saved_snap in candidates.items():
                    if (saved_snap is not None and saved_snap.good
                            and saved_snap.epic==instrument):
                        saved+=archive_candles(history_db,saved_snap.frame,
                            instrument,saved_snap.source,saved_tf)
                st.session_state['_last_candles_saved']=saved
                st.session_state.pop('_history_write_error',None)
            except (OSError,sqlite3.Error,ValueError) as ex:
                st.session_state['_history_write_error']=type(ex).__name__
            record=scan_event(scan_trigger,previous_snap,obtained,
                              market_status=market_status,requested_utc=scan_requested)
            st.session_state['_scan_log']=append_scan_log(st.session_state.get('_scan_log'),record)
            st.session_state['_scan_last_result']=record
        except (FeedError,ValueError) as ex:
            record=scan_event(scan_trigger,previous_snap,None,
                error=f'{type(ex).__name__}: {str(ex)}',requested_utc=scan_requested)
            st.session_state['_scan_log']=append_scan_log(st.session_state.get('_scan_log'),record)
            st.session_state['_scan_last_result']=record
            if previous_snap is not None:
                st.session_state['market_snap']=dataclass_replace(previous_snap,
                    good=False,reason='POPRZEDNI ODCZYT / NIEAKTUALNE: '+str(ex)[:160])
                st.warning('Pokazuję ostatni wykres, ale dane NIE są aktualne. '
                           'Nowe sygnały i wejścia PAPER są zablokowane.')
            else:
                st.session_state.pop('market_snap', None)
            st.session_state.pop('ai_context', None)
            st.session_state['last_feed_error'] = str(ex)
            st.error('❌ Nie udało się pobrać poprawnych świec: '+str(ex))
        except Exception as ex:
            record=scan_event(scan_trigger,previous_snap,None,
                error=f'Błąd aplikacji: {type(ex).__name__}',requested_utc=scan_requested)
            st.session_state['_scan_log']=append_scan_log(st.session_state.get('_scan_log'),record)
            st.session_state['_scan_last_result']=record
            if previous_snap is not None:
                st.session_state['market_snap']=dataclass_replace(previous_snap,
                    good=False,reason='POPRZEDNI ODCZYT / BŁĄD APLIKACJI')
                st.warning('Pozostawiono ostatni wykres — dane NIE są aktualne, '
                           'nowe sygnały są zablokowane.')
            else:
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
        if last_record['api_result'] in ('OK','PARTIAL_DATA'):
            status_description='NOWA ŚWIECA' if last_record['new_candle'] else 'BRAK NOWEJ ŚWIECY'
            if last_record['bar_result']=='STALE_OR_BLOCKED':
                status_description='DANE NIEAKTUALNE / BLOKADA SYGNAŁÓW'
            elif last_record['bar_result']=='DATA_QUARANTINED':
                status_description='ODRZUCONO WADLIWĄ ŚWIECĘ / WAIT'
            st.info(f"🛰️ SKAN #{st.session_state.get('_scan_attempt_count',0)} | "
                f"wyzwalacz: {last_record['trigger']} | "
                f"dane: {'CZĘŚCIOWO WADLIWE' if last_record['api_result']=='PARTIAL_DATA' else 'OK'} | "
                f"wynik: {status_description} | rynek: {last_record['market_status']}")
            if last_record['market_status']=='CLOSED':
                st.warning('Capital.com zgłasza CLOSED: prawdopodobnie przerwa lub zamknięty instrument. Skaner może działać poprawnie, ale nie ma nowych zamkniętych świec. Pozostaje WAIT.')
            elif last_record['bar_result']=='STALE_OR_BLOCKED':
                st.warning('Odczyt nie spełnia wymagań świeżości. Bez sygnału LONG/SHORT.')
            elif last_record['bar_result']=='DATA_QUARANTINED':
                st.warning('API odpowiedziało, ale zawierało wadliwe rekordy BID/ASK lub OHLC. '
                           'Wykres z poprawnych świec pozostaje widoczny; nowe sygnały zablokowane.')
        else:
            st.error('🛰️ SKAN: nieudany odczyt lub błędne dane; '
                     'to nie musi być problem komunikacji. Sprawdź dziennik prób.')
    if actual_scan_this_rerun and last_record and (
            last_record.get('bar_result')=='STALE_OR_BLOCKED'
            or last_record.get('api_result')=='ERROR'):
        # DATA_STALE is a THROTTLED system notification, not a trade signal.
        if capital_env=='DEMO' and secret('PAPER_TELEGRAM_ALERTS_ENABLED','false').lower() in ('true','1','yes'):
            try:
                system_db=connect()
                record_stale_event(system_db,'Capital.com DEMO REST',
                    instrument,tf,last_record.get('error') or last_record.get('bar_result','DATA_STALE'))
                dispatch_alerts(system_db,active_credential('TELEGRAM_BOT_TOKEN',secret,overrides),
                    active_credential('TELEGRAM_CHAT_ID',secret,overrides),enabled=True)
            except (OSError,sqlite3.Error,ValueError,TypeError):
                st.warning('DATA_STALE: nie udało się zapisać/obsłużyć alertu Telegram.')
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
        if not snap.good:
            st.warning('⚠️ WYKRES ARCHIWALNY / WAIT: '+str(snap.reason)[:280]+
                       ' Nie używaj tych danych do nowej decyzji.')
        else:
            st.select_slider('🔎 Powiększenie wykresu — liczba ostatnich świec',
                options=[60,90,120,180,240,350],value=120,key='chart_window_size')
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
            # No historical backfilled arrows. Only actual archived PAPER
            # OPEN/CLOSED positions are allowed to draw trade markers.
            fig.update_layout(height=570,xaxis_rangeslider_visible=False,template='plotly_dark',
                              paper_bgcolor='#111a2d',plot_bgcolor='#111a2d',legend_orientation='h',
                              margin={'l':15,'r':15,'t':30,'b':10})
            chart_slot=st.empty()
            st.caption('⬆️ Zielona strzałka = bot otworzył PAPER LONG; '
                       '⬇️ czerwona = PAPER SHORT; 🟩 kwadrat = bot zamknął PAPER. '
                       'NIE pokazuję strzałek historycznych formacji. '
                       'Bez zatwierdzonej pozycji PAPER nie ma strzałki.')
            st.caption('Wykres ze świec MID, nie cena wykonalna BID/ASK. Najnowsza świeca API została wykluczona z oceny strategii.')
            if current_ready:
                st.success('✅ FEED AKTUALNY: '+current_reason)
            else:
                st.warning('🟡 WAIT / DANE: '+current_reason)
            market_status=st.session_state.get('_market_status','UNKNOWN')
            status_ready=(src.startswith('Capital.com ') and market_status=='TRADEABLE')
            if current_ready and not status_ready:
                st.warning(f'🟡 WAIT / STATUS BROKERA: {market_status}. Bez potwierdzenia TRADEABLE brak nowych sygnałów.')
            ready=current_ready and status_ready
            if src.startswith('CSV'):
                st.warning('CSV: wyłącznie symulacja edukacyjna. Nie ma sygnału do egzekucji live.')
            if snap.frame is not None and len(snap.frame)>=70:
                if strategy==AUTO_MODE:
                    decision,auto_audit=evaluate_auto(
                        snap.frame,snap.spread,st.session_state.get('mtf_snapshots',{}),
                        asof=snap.confirmed_utc,use_mtf=True)
                    st.caption('🤖 AUTO analizuje wszystkie 6 strategii. MINIMUM 2 zgodne po MTF i żadnego przeciwnego sygnału. To filtr badawczy, nie miara skuteczności.')
                    raw_candidates=[r for r in auto_audit if r.get('Setup OHLC') in ('LONG','SHORT')]
                    if raw_candidates:
                        st.markdown('#### 🔎 RADAR KANDYDATÓW (PRZED WERYFIKACJĄ MTF)')
                        st.caption('To wykryte układy 6 strategii, NIE otwarte pozycje. '
                                   'Po filtrach MTF mogą być odrzucone; nie liczę ich do skuteczności.')
                        st.dataframe(pd.DataFrame(raw_candidates),hide_index=True,use_container_width=True)
                    else:
                        st.info('🔎 Radar sześciu strategii: brak surowego LONG/SHORT '
                                'na tej zamkniętej świecy — nie generuję fikcyjnego typu.')
                    with st.expander('📊 AUTO — WSZYSTKIE 6 STRATEGII I BLOKADY'):
                        st.dataframe(pd.DataFrame(auto_audit),hide_index=True,use_container_width=True)
                else:
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
                    st.caption('To kandydat SETUP. Linie zarezerwowane są dla pozycji, która naprawdę przeszła w OPEN w silniku PAPER v3.')
                current_paper=None
                try:
                    db_v3=paper_view_db()
                    ensure_paper_v3(db_v3)
                    if remote_paper_view_enabled():
                        st.caption('☁️ PAPER REMOTE VIEW: pozycje z trwałego checkpointu workera. Ten terminal nie zapisuje nowych pozycji PAPER — jeden writer w GitHub Actions.')
                    if (not remote_paper_view_enabled() and actual_scan_this_rerun
                            and snap.good and src=='Capital.com DEMO REST'):
                        # Process all available broker TFs so switching M1/M5/H1
                        # cannot silently strand an older OPEN position.
                        available={tf:snap}
                        if st.session_state.get('mtf_enabled',False):
                            available.update({k:v for k,v in
                                st.session_state.get('mtf_snapshots',{}).items()
                                if v is not None and v.epic==instrument and
                                v.source==src and v.good})
                        changes=[]
                        for scan_tf,scan_snap in available.items():
                            changes.extend(progress_paper(db_v3,scan_snap.frame,
                                instrument,src,scan_tf,max_holding=20))
                        candle_clock_confirmed=secret(
                            'FOKUS_CANDLE_TIME_CONFIRMED','').strip().lower()=='open'
                        if ready and decision.action in ('LONG','SHORT') and not candle_clock_confirmed:
                            st.warning('🕒 PAPER: nowy setup zablokowany. Czas świecy API wygląda na OPEN, ale wymaga potwierdzenia. Nie ustawiaj close.')
                        if ready and decision.action in ('LONG','SHORT') and candle_clock_confirmed:
                            paper_id=queue_paper(db_v3,instrument,src,tf,decision,
                                snap.confirmed_utc,snap.spread,slippage=.25,
                                market_status=market_status)
                            if paper_id:
                                st.caption(f'🧪 Nowy PENDING PAPER v3: {paper_id[:10]} — wejście dopiero na OPEN kolejnej zamkniętej świecy.')
                        if changes:
                            st.caption('PAPER v3: '+', '.join(changes))
                        if secret('PAPER_TELEGRAM_ALERTS_ENABLED','false').lower() in ('true','1','yes'):
                            token=active_credential('TELEGRAM_BOT_TOKEN',secret,overrides)
                            chat_id=active_credential('TELEGRAM_CHAT_ID',secret,overrides)
                            alert_result=dispatch_alerts(db_v3,token,chat_id,enabled=True)
                            if alert_result.get('failed'):
                                st.warning(f"Telegram: {alert_result['failed']} alertów miało błąd dostarczenia i nie będzie automatycznie ponawianych.")
                    paper_rows=[x for x in recent_positions(db_v3,limit=80)
                                if x.get('epic')==instrument and x.get('source')==src]
                    paper_ids={x['trade_id'] for x in paper_rows}
                    paper_events=[e for e in recent_events(db_v3,limit=150)
                                  if e.get('trade_id') in paper_ids]
                    if paper_rows:
                        with st.expander('📋 DZIENNIK WEJŚĆ I WYJŚĆ PAPER — GODZINA / PUNKTY'):
                            columns=['setup_utc','opened_utc','closed_utc','side',
                                     'status','entry_mid','stop_mid','target_mid',
                                     'exit_mid','pnl_pts','close_reason','exit_policy']
                            st.dataframe(pd.DataFrame([
                                {key:r.get(key) for key in columns} for r in paper_rows[:35]
                            ]),hide_index=True,use_container_width=True)
                            st.caption('Punkty netto po modelowanym spreadzie i poślizgu; '
                                       'PAPER_OPEN odtworzony dopiero po zamknięciu świecy.')
                    active_audio=bool(st.session_state.get('paper_audio_enabled',False))
                    # Establish a baseline, NOT a playback of old ledger events.
                    # '__EMPTY__' makes a first future OPEN audible when archive
                    # was empty at initial page load.
                    if '_last_paper_audio_event' not in st.session_state:
                        st.session_state['_last_paper_audio_event']=(
                            paper_events[0].get('event_id') if paper_events else '__EMPTY__')
                    prev_audio=st.session_state['_last_paper_audio_event']
                    latest_audio,new_audio=new_paper_events(paper_events,prev_audio)
                    st.session_state['_last_paper_audio_event']=latest_audio
                    queued_audio=list(st.session_state.get('_paper_audio_pending',[]))
                    if active_audio:
                        queued_audio.extend(new_audio)
                    else:
                        queued_audio=[]
                    # Events in one scan may be OPEN and CLOSE together: play
                    # one alert per UI refresh, oldest first, never overlap.
                    audio_event=queued_audio.pop(0) if active_audio and queued_audio else None
                    st.session_state['_paper_audio_pending']=queued_audio[-30:]
                    if audio_event:
                        kind=audio_event['kind']
                        st.info('🔔 '+SOUND_EVENTS[kind]+
                                ' — zdarzenie PAPER, nie zlecenie rzeczywiste.')
                        side=next((row.get('side') for row in paper_rows
                            if row.get('trade_id')==audio_event.get('trade_id')),None)
                        audio,mime,used=alert_audio(kind,side,
                            voice_enabled=st.session_state.get('paper_audio_mode')==
                                           'Głos ElevenLabs (nagrania MP3)')
                        if used=='TONE' and st.session_state.get('paper_audio_mode')==\
                                'Głos ElevenLabs (nagrania MP3)':
                            st.caption('🔉 Nie znaleziono przypisanego MP3 — odtwarzam ton.')
                        st.audio(audio,format=mime,autoplay=True)
                    current_paper=active_position(db_v3,instrument,src,tf)
                except (OSError, sqlite3.Error,ValueError,RemoteError) as ex:
                    st.error('❌ Silnik PAPER/REMOTE: '+type(ex).__name__+'; brak zdalnego odczytu, nie wyświetlam starej pozycji jako aktualnej.')
                if current_paper:
                    st.markdown('### 🧪 AKTYWNA SYMULACJA PAPER v3')
                    st.caption('Zarządzanie wyjściem: '+('ADAPTIVE — eksperymentalny trailing SL/runner TP'
                         if current_paper.get('exit_policy')=='adaptive' else 'FIXED SL/TP')+
                        '. Zmiany stopa obowiązują od następnej świecy, nie wstecz.')
                    st.info(
                        f"Status: **{current_paper['status']}** | {current_paper['side']} "
                        f"| {current_paper['strategy']} | ID: {current_paper['trade_id'][:10]} "
                        f"| SL MID {current_paper['stop_mid']:.2f} | TP MID {current_paper['target_mid']:.2f}. "
                        +('Wejście dopiero po następnej ZAMKNIĘTEJ świecy — nie było jeszcze wykonania.'
                          if current_paper['status']=='PENDING'
                          else (f"MID z następnej świecy (historyczny): {current_paper['entry_mid']:.2f} | "
                                f"modelowany fill BID/ASK + poślizg: {current_paper['entry_executable']:.2f}. "
                                f"Założony czas OPEN: {current_paper.get('entry_assumed_utc') or 'BRAK / STARY ZAPIS'}; "
                                f"wykryte przez skaner: {current_paper.get('entry_detected_utc') or 'BRAK / STARY ZAPIS'}. "
                                "Nie było rzeczywistego wykonania zlecenia.")))
                else:
                    st.caption('🧪 Brak aktywnej pozycji PAPER. Nie rysuję historycznych LONG/SHORT jako wejść.')
                if current_paper and current_paper['timeframe']!=tf:
                    st.warning(f"Pozycja PAPER v3 działa na {current_paper['timeframe']}, nie na aktualnym {tf}. Linie poziomów są ukryte, żeby nie mieszać interwałów. Włącz MTF i AUTO-SKAN, aby odświeżać również pierwotny interwał.")
                annotate_open_paper(fig,current_paper if current_paper and current_paper['timeframe']==tf else None)
                annotate_paper_history(fig,locals().get('paper_rows',[]),
                    instrument,src,tf)
                # No BUY/SELL-looking historical scan markers. Trade chart is
                # restricted to verified PAPER OPEN/CLOSED ledger events.
                chart_slot.plotly_chart(fig,use_container_width=True)
                st.caption('🤖 BOT ocenia zamknięte świece z wykresu według wybranego interwału odświeżania (5–300 s), tylko gdy strona jest otwarta. Bez streamingu ticków i zleceń.')
                if ready:
                    payload=numeric_context(snap.frame,decision,instrument,tf,snap.spread)
                    st.session_state['ai_context']=payload
                    st.session_state['_last_ai_context']=dict(payload)
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
                else:
                    # Do not use stale data for a new trade signal, but keep the
                    # last numerical snapshot available for labeled historical AI.
                    if st.session_state.get('ai_context'):
                        st.session_state['_last_ai_context']=dict(st.session_state['ai_context'])
                    st.session_state.pop('ai_context',None)
                st.info('🤖 Rozmowa z AI jest teraz w osobnej zakładce **CZAT AI**. Odpowiedzi pozostają widoczne po kolejnym automatycznym skanie.')
            else:
                chart_slot.plotly_chart(fig,use_container_width=True)
                st.warning('Wykres dostępny, ale jest mniej niż 70 zamkniętych świec — brak sygnału.')
    else:
        st.warning('Nie ma danych. Włącz odczyt Capital.com lub dodaj własny CSV edukacyjny. Nie pokazuję fikcyjnych sygnałów.')


with chat_tab:
    st.subheader('🤖 FOKU$ AI — ROZMOWA O WYKRESIE')
    st.caption('Model OpenAI analizuje ostatnie ZAMKNIĘTE świece i ich wskaźniki. Odpowiedzi zapamiętywane są w tej sesji i nie znikają przy AUTO-SKANIE.')
    chat_payload=st.session_state.get('ai_context') or st.session_state.get('_last_ai_context')
    if chat_payload:
        context_info=preview_context(chat_payload)
        st.info(f"Źródło do rozmowy: {context_info['instrument']} | "
                f"świeca: {context_info['candle']} | "
                f"decyzja: {context_info['decision']} | "
                f"liczba przekazanych świec: {context_info['n_candles']}.")
        if not st.session_state.get('ai_context'):
            st.warning('To OSTATNI ZAPISANY KONTEKST, a nie bieżąca analiza LIVE. AI powinno traktować go jako historię.')
    else:
        st.warning('Brak zebranych danych OHLC. Możesz pytać ogólnie, lecz AI nie powinno wtedy udawać analizy wykresu.')
    if not openai_api_key:
        st.error('Brak OPENAI_API_KEY w Secrets — nie mogę uruchomić modelu.')
    ai_effort=st.radio('🧠 Tryb analizy GPT-5.4',options=['medium','high'],
        index=0,horizontal=True,key='ai_effort_choice',
        help='medium = zwykle szybciej i mniej tokenów; high = głębsze rozumowanie, zwykle dłużej i drożej.')
    st.caption('Domyślnie medium. Wyższy wysiłek kosztuje więcej tokenów. Rzeczywista cena zależy od aktualnej taryfy API; pokazujemy liczbę zużytych tokenów, a nie wymyśloną kwotę.')
    if st.button('🗑️ Wyczyść tę rozmowę',key='clear_fokus_ai_history'):
        st.session_state['_ai_messages']=[]
        st.rerun()
    for turn in renderable_history(st.session_state.get('_ai_messages')):
        with st.chat_message(turn['role']):
            st.markdown(turn['content'])
            st.caption('Kontekst świecy: '+turn.get('market_candle_utc','BRAK')+
                       ' · zapis: '+turn.get('time_utc','BRAK'))
    with st.form('fokus_ai_chat_form',clear_on_submit=True):
        user_query=st.text_area('Napisz pytanie do bota:',
            placeholder='Dlaczego WAIT? Jak wygląda trend, EMA, SL/TP? Jakie są ryzyka?',
            height=95,max_chars=800)
        sent=st.form_submit_button('🧠 WYŚLIJ PYTANIE DO GPT-5.4',
            type='primary',use_container_width=True)
    if sent:
        question=user_query.strip()
        if not question:
            st.warning('Najpierw wpisz pytanie.')
        elif not openai_api_key:
            st.error('Najpierw skonfiguruj OpenAI API w Streamlit Secrets.')
        else:
            with st.spinner('🧠 GPT analizuje liczby — odpowiedź zostanie zapisana w historii...'):
                st.session_state['_ai_busy']=True
                try:
                    result=manual_ai_request(question,dict(chat_payload or {
                        'instrument':instrument,
                        'resolution':tf,
                        'last_closed_utc':'BRAK — brak danych',
                        'last_12_closed_candles':[],
                        'note':'Brak danych live. Nie wolno wnioskować o bieżącym kierunku.'
                    }))
                finally:
                    st.session_state['_ai_busy']=False
            candle_id=(chat_payload or {}).get('last_closed_utc','BRAK')
            st.session_state['_ai_messages']=append_message(
                st.session_state.get('_ai_messages'),"user",question,candle_id)
            st.session_state['_ai_messages']=append_message(
                st.session_state['_ai_messages'],"assistant",result,candle_id)
            with st.chat_message('assistant'):
                st.markdown(result)
                st.caption('Odpowiedź została zachowana w historii sesji.')
    st.caption('Zapytania OpenAI tylko po kliknięciu; dane o zużytych tokenach pojawiają się przy odpowiedzi, jeśli API je zwróci. Historia nie jest trwała — zwykły rerun zachowuje sesję, ale odświeżenie strony, nowe logowanie lub restart serwera mogą ją wyczyścić.')


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
    st.write('v0.3 zapisuje decyzje PAPER i rozlicza późniejsze zamknięte świece. Raporty holdout/rolling są w zakładce RAPORTY. **Nie ma automatycznego dostrajania parametrów** — mała próbka grozi przeuczeniem.')

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
      (f'Capital.com {capital_env} REST / OHLC','Klucze dostępne' if has_cap else 'Brak kluczy',f'Status instrumentu: {st.session_state.get("_market_status","UNKNOWN")}'),
      ('OpenAI GPT','Klucz dostępny' if openai_api_key else 'Brak klucza','Czat: ręcznie. Worker GitHub: osobny opt-in i limity płatnych komentarzy; bez zleceń'),
      ('Telegram','Klucze dostępne' if secret('TELEGRAM_BOT_TOKEN') and secret('TELEGRAM_CHAT_ID') else 'Nieskonfigurowany','Lokalny PAPER: opt-in, remote worker: brak wysyłki do czasu trwałego outboxu'),
      ('Niezależny worker','Kod v4 przygotowany','GitHub Actions co ~5 min po włączeniu; brak gwarantowanego hosta 24/7'),
      ('Uczenie strategii','CZĘŚCIOWO','Replay, holdout i rolling — BEZ samodzielnej zmiany progów i bez ML'),
      ('Wiadomości i kalendarz makro','CZĘŚCIOWO','FED/BLS/BEA RSS + kalendarz BLS, brak pełnego harmonogramu FOMC'),
      ('Trading DEMO/REAL','BLOKADA','Żadnych zleceń brokerskich, tylko odczyt i PAPER'),
      ('MTF M1/M5/M15/H1','AKTYWNY' if st.session_state.get('mtf_snapshots') else 'CZEKA','4 osobne serie, brak potwierdzenia = WAIT'),
      ('Historia świec','REMOTE OPTIONAL' if remote_paper_view_enabled() else 'LOKALNA','Dedykowany Supabase po konfiguracji; lokalny SQLite inaczej może zniknąć'),
      ('PAPER remote','TRYB PODGLĄDU' if remote_paper_view_enabled() else 'WYŁĄCZONY','PAPER v4 remote jest TYLKO czytnikiem w tym panelu; zapisuje wyłącznie worker'),
    ],columns=['Element','Stan','Wyjaśnienie']))
    st.caption('Klucze podawaj w Secrets aplikacji, nigdy w publicznym GitHubie. API tutaj nie są trwale zapisywane w bazie.')
    with st.expander('☁️ PAPER v4 — SPRAWDŹ POŁĄCZENIE Z OSOBNĄ BAZĄ SUPABASE'):
        st.caption('Tylko odczyt konfiguracji i zdalnej wersji. Ta kontrola NIE zapisuje danych i NIE składa zleceń Capital.com.')
        has_cloud_url=bool(secret('FOKUS_SUPABASE_URL'))
        has_cloud_secret=bool(secret('FOKUS_SUPABASE_SECRET_KEY'))
        st.table(pd.DataFrame([
            ('URL osobnego Supabase','JEST' if has_cloud_url else 'BRAK'),
            ('Klucz backendowy Supabase','JEST' if has_cloud_secret else 'BRAK'),
            ('Podgląd CLOUD','WŁĄCZONY' if remote_paper_view_enabled() else 'WYŁĄCZONY'),
        ],columns=['Element','Status']))
        st.info('Aby korzystać z PAPER cloud, trzeba utworzyć osobny projekt Supabase, zastosować plik SQL i ustawić te same sekrety w GitHub Actions oraz Streamlit Secrets. Zobacz dokumentacja/PAPER_V4_SETUP.md.')
        if st.button('📡 TEST ODCZYTU CHECKPOINTU SUPABASE',key='cloud_v4_test_read'):
            if not (has_cloud_url and has_cloud_secret):
                st.warning('Brakuje URL lub serwerowego sekretu Supabase w Streamlit Secrets.')
            else:
                try:
                    conn=RemoteCheckpoint(secret('FOKUS_SUPABASE_URL'),
                                         secret('FOKUS_SUPABASE_SECRET_KEY'))
                    version,payload=conn.fetch()
                    st.success(f'✅ Połączenie READ-ONLY OK. Wersja remote: {version}.')
                    meta=payload.get('meta') or {}
                    if meta.get('last_scan_utc'):
                        st.caption('Ostatni zapis workera UTC: '+meta['last_scan_utc'])
                    else:
                        st.warning('Baza odpowiada, ale brak zapisu potwierdzonego skanu workera.')
                except (RemoteError,ValueError,TypeError) as ex:
                    st.error('❌ Połączenie z Supabase niepotwierdzone: '+type(ex).__name__)
    with st.expander('🕒 AUDYT SNAPSHOTTIMEUTC — kiedy naprawdę zaczyna się świeca?'):
        st.warning('Konwencja OPEN/CLOSE z API Capital.com nadal NIE jest zweryfikowana. Diagnostyka pokazuje hipotezę opartą na czasach — nie certyfikuje prawdziwego wykonania.')
        if st.button('📡 PORÓWNAJ SUROWE OZNACZENIA CZASU (DEMO, GET ONLY)',key='raw_time_audit'):
            st.session_state.pop('_last_raw_time_audit',None)
            if capital_env!='DEMO' or not has_cap:
                st.error('Wybierz Capital.com DEMO i upewnij się, że klucze API są dostępne. Diagnostyka nie odczytuje LIVE.')
            else:
                try:
                    # A new client avoids AttributeError caused by an old client
                    # instance retained in Streamlit session_state after redeploy.
                    fresh_demo=CapitalReadOnly(cap_api_key,cap_identifier,cap_password,environment='DEMO')
                    raw=fresh_demo.raw_candle_time_diagnostic(instrument,'MINUTE')
                    result=inspect_labels(raw,'MINUTE')
                    prior=st.session_state.get('_last_raw_time_audit')
                    st.session_state['_clock_pair_verdict']=(
                        compare_clock_observations(prior,result) if prior else None)
                    st.session_state['_last_raw_time_audit']=result
                except (FeedError,ValueError,TypeError,AttributeError) as ex:
                    st.error('Diagnostyka API DEMO nie zakończyła się poprawnie: '+type(ex).__name__+
                             '. Szczegóły możesz sprawdzić w logach Streamlit; nie publikuj kluczy.')
        if st.session_state.get('_last_raw_time_audit'):
            st.json(st.session_state['_last_raw_time_audit'])
            pair=st.session_state.get('_clock_pair_verdict')
            if pair:
                st.info('🕒 Porównanie dwóch odczytów: '+pair.get('status','BRAK'))
                st.json(pair)
            else:
                st.caption('Pierwszy odczyt zarejestrowany. Kliknij ponownie po pojawieniu się kolejnej świecy M1, żeby porównać oba oznaczenia.')
            if secret('FOKUS_CANDLE_TIME_CONFIRMED','').lower()!='open':
                st.warning('NOWE WEJŚCIA PAPER: ZABLOKOWANE do niezależnego potwierdzenia, że API oznacza czas OTWARCIA. Nie używaj ustawienia close.')
            st.caption('Porównaj wynik z czasem świec w terminalu Capital.com. Surowe oznaczenia pozostają bez przesunięcia; OHLC w strategiach przeliczane są na czas zamknięcia.')



with mtf_tab:
    st.subheader('🧭 M1 + M5 + M15 + H1 — JEDEN OBRAZ RYNKU')
    st.caption('4 osobne serie z Capital.com. Brak danych, inne źródło lub brak świeżości = WAIT. MTF nie tworzy nowego sygnału, tylko może odrzucić już wykryty.')
    snapshots=st.session_state.get('mtf_snapshots',{})
    if not st.session_state.get('mtf_enabled',False):
        st.warning('Włącz MTF w lewym panelu, aby 4 interwały uczestniczyły w ocenie.')
    if not snapshots:
        st.info('Brak zestawu MTF. Wykonaj SKANUJ ŚWIECE przy włączonym MTF.')
    else:
        rows,consensus=evaluate_timeframes(snapshots)
        table=[]
        for row in rows:
            table.append({'Interwał':LABELS[row.timeframe],
                'Trend EMA':row.trend,'Cena':row.close,'ATR':row.atr,'RSI':row.rsi,
                'Status':'AKTUALNY' if row.ready else 'BRAK/WAIT',
                'Zamknięta świeca UTC':str(row.candle_utc) if row.candle_utc else 'BRAK',
                'Wyjaśnienie':row.reason})
        st.dataframe(pd.DataFrame(table),hide_index=True,use_container_width=True)
        if consensus in ('UP','DOWN'):
            st.success(f'KONTEKST MTF: {consensus} (hipoteza, bez gwarancji kierunku)')
        else:
            st.warning('KONTEKST MTF: WAIT / NEUTRAL — nie ma pełnej zgodności czterech interwałów.')
        errors=st.session_state.get('mtf_errors',{})
        if errors:
            with st.expander('Błędy pobrania poszczególnych interwałów'):
                st.json({LABELS.get(k,k):v for k,v in errors.items()})
        cols=st.columns(2)
        for i,horizon in enumerate(TIMEFRAMES):
            sn=snapshots.get(horizon)
            if sn is not None and len(sn.frame)>10:
                with cols[i%2]:
                    st.caption(f'{LABELS[horizon]} • {sn.source} • {len(sn.frame)} zamkniętych świec')
                    st.line_chart(sn.frame.Close.tail(100),height=190)


with strategies_tab:
    st.subheader('🎯 SZÓSTKA STRATEGII PAPER — NIEZALEŻNE OCENY')
    st.caption('Każdy algorytm analizuje te same zamknięte świece. LONG/SHORT to jedynie setup badawczy. Reguły nie są skalibrowane na historyczny zysk.')
    if snap is None or len(snap.frame)<85:
        st.info('Pobierz co najmniej 85 zamkniętych świec, aby ocenić strategie.')
    else:
        all_rows=[]
        for name in ALL_STRATEGIES:
            d=decide_any(snap.frame,name,spread=snap.spread)
            filtered,_=filter_mtf_decision(
                d,st.session_state.get('mtf_snapshots',{}),
                asof=snap.confirmed_utc) if st.session_state.get('mtf_enabled') else (d,[])
            if not current_feed_status(snap,src)[0]:
                filtered_action='WAIT / STALE'
            elif st.session_state.get('_market_status','UNKNOWN')!='TRADEABLE':
                filtered_action='WAIT / RYNEK'
            elif src.startswith('CSV'):
                filtered_action='WAIT / CSV'
            else:
                filtered_action=filtered.action
            all_rows.append({'Strategia':name,'Setup (OHLC)':d.action,
                'Po filtrze MTF / feed':filtered_action,
                'Wejście MID':d.entry,'SL MID':d.stop,'TP MID':d.target,
                'RR':d.rr,'Powód':d.reason if filtered_action==d.action else filtered.reason})
        st.dataframe(pd.DataFrame(all_rows),hide_index=True,use_container_width=True)
        st.info('Jednoczesne różne sygnały NIE oznaczają, że należy je sumować. Każda strategia wymaga oddzielnego, rozliczonego testu.')


with news_tab:
    st.subheader('📰 RADAR MAKRO — OFICJALNE ŹRÓDŁA FED / BLS / BEA')
    st.caption('Nagłówki RSS i kalendarz publikacji BLS. Bez scrapingowania kont osobistych i bez automatycznych płatnych zapytań GPT.')
    if st.button('🌐 POBIERZ WIADOMOŚCI I KALENDARZ BLS',type='primary',key='fetch_official_news'):
        headlines,feed_errors=fetch_headlines()
        st.session_state['_headlines']=headlines
        st.session_state['_news_feed_errors']=feed_errors
        st.session_state['_news_read_utc']=datetime.now(timezone.utc).isoformat()
        try:
            st.session_state['_macro_calendar']=fetch_bls_schedule()
            st.session_state['_calendar_error']=None
        except Exception as ex:
            st.session_state['_macro_calendar']=[]
            st.session_state['_calendar_error']=type(ex).__name__
    if st.session_state.get('_news_read_utc'):
        st.caption('Ostatni udany/podjęty skan źródeł (UTC): '+st.session_state['_news_read_utc'])
    events=st.session_state.get('_macro_calendar',[])
    is_blocked,notice=macro_blackout(events)
    (st.error if is_blocked else st.info)(notice)
    if st.session_state.get('_calendar_error'):
        st.warning('Kalendarz BLS niedostępny: '+st.session_state['_calendar_error']+'. Nie potwierdzamy braku ważnych publikacji.')
    if events:
        upcoming=[{'Data UTC':e['data_utc'].isoformat(),'Wydarzenie':e['wydarzenie']}
            for e in events if e['data_utc']>=datetime.now(timezone.utc)-pd.Timedelta(hours=2)]
        st.markdown('#### Kalendarz BLS — najbliższe wydarzenia')
        st.dataframe(pd.DataFrame(upcoming[:20]),use_container_width=True,hide_index=True)
    news=st.session_state.get('_headlines',[])
    if news:
        st.markdown('#### Najnowsze nagłówki')
        st.dataframe(pd.DataFrame(news[:45]),use_container_width=True,hide_index=True,
            column_config={'url':st.column_config.LinkColumn('Oficjalny link')})
    else:
        st.info('Brak pobranych wiadomości — kliknij przycisk. Nie pokazuję fikcyjnych nagłówków.')
    if st.session_state.get('_news_feed_errors'):
        with st.expander('Niedostępne źródła RSS (uczciwy status)'):
            st.json(st.session_state['_news_feed_errors'])
    with st.expander('🤖 GPT-5.4 HIGH — wyjaśnij dane + oficjalne nagłówki (płatne, ręcznie)'):
        st.caption('Nagłówki to niezweryfikowane przez GPT dane z zewnętrznych stron; mogą zawierać błędy. AI nie zna niepodanych wyników publikacji.')
        q=st.text_area('Pytanie badawcze',value='Jakie ryzyka makro i warunki WAIT wynikają z DOSTARCZONYCH wiadomości i świec?',key='macro_ai_question')
        if st.button('🧠 ANALIZUJ NEWS + WYKRES — OPENAI',key='macro_ai_button'):
            if not openai_api_key:st.error('Brak klucza OpenAI API w Secrets.')
            else:
                context=dict(st.session_state.get('ai_context') or {})
                context['news_untrusted_external']=[{'title':x['tytuł'],'published_utc':x['data_utc'],
                    'source':x['źródło'],'url':x['url']} for x in news[:12]]
                context['calendar_BLS']=[{'event':x['wydarzenie'],'datetime_utc':x['data_utc'].isoformat()} for x in events[:12]]
                context['not_live_when_missing']=not bool(st.session_state.get('ai_context'))
                st.session_state['_ai_busy']=True
                with st.spinner('🧠 OpenAI analizuje dostarczone wiadomości i świece...'):
                    try:
                        reply=manual_ai_request(q,context)
                    finally:
                        st.session_state['_ai_busy']=False
                st.session_state['_ai_messages']=append_message(
                    st.session_state.get('_ai_messages'),"user",q,
                    context.get('last_closed_utc'))
                st.session_state['_ai_messages']=append_message(
                    st.session_state['_ai_messages'],"assistant",reply,
                    context.get('last_closed_utc'))
                st.write(reply)
                st.caption('Pełna historia tej rozmowy pozostaje w zakładce 🤖 CZAT AI.')


with reports_tab:
    st.subheader('📈 FOKU$ LAB — PORÓWNAJ 6 STRATEGII PO KOSZTACH')
    st.caption('Rejestr badań PAPER. Chronologiczny holdout 70/30 + kroczące przedziały. Żaden wynik nie jest obietnicą zysku.')
    with st.expander('🧪 PAPER v3 — POZYCJE DEMO, ZDARZENIA I RAPORT DZIENNY/TYGODNIOWY',expanded=True):
        st.info('To wyłącznie symulowane pozycje PAPER v3 z Capital.com DEMO. PENDING nie jest wejściem; OPEN to wejście odtworzone z OPEN następnej ZAMKNIĘTEJ świecy. Starsze v2 i CSV są oddzielne. Brak prawdziwych zleceń.')
        try:
            paper_db=paper_view_db()
            ensure_paper_v3(paper_db)
            if remote_paper_view_enabled():
                st.success(f"☁️ REMOTE PAPER: checkpoint worker version {st.session_state.get('_paper_remote_version','BRAK')}. Statystyki pochodzą z bazy workera, nie z lokalnego SQLite.")
                meta=st.session_state.get('_paper_remote_meta') or {}
                latest=meta.get('last_scan_utc')
                if latest:
                    st.caption(f"Ostatnie zakończone uruchomienie workera UTC: {latest}. Źródło {meta.get('source','BRAK')}; TF {meta.get('timeframe','BRAK')}.")
                    try:
                        lag=(pd.Timestamp.now(tz='UTC')-pd.Timestamp(latest)).total_seconds()/60
                        if lag>15:
                            st.warning(f"⚠️ Ostatni checkpoint workera ma {lag:.0f} minut. Nie zakładam, że skaner teraz działa.")
                    except (ValueError,TypeError):
                        st.warning("Nieznany format czasu ostatniego skanu workera.")
                else:
                    st.warning("Brak potwierdzonego skanu workera w chmurze. Cloud jest skonfigurowany, ale skaner mógł jeszcze nigdy nie wystartować.")
                candidates=st.session_state.get('_paper_remote_candidates') or []
                with st.expander('🔎 ARCHIWUM RADARU — SUROWE SYGNAŁY I POWODY BLOKAD',expanded=True):
                    st.caption('Nie są to pozycje PAPER ani zweryfikowane typy. Zapis z workera '
                               'na kolejnych zamkniętych świecach, również gdy decyzją jest WAIT.')
                    if candidates:
                        rows=[]
                        for item in reversed(candidates[-30:]):
                            votes=item.get('raw_candidates') or []
                            rows.append({
                                'Świeca UTC':item.get('candle_utc'),
                                'Decyzja':item.get('decision'),
                                'Kandydaci surowi':', '.join(
                                    v.get('direction','')+' '+v.get('strategy','') for v in votes) or 'BRAK',
                                'Blokady':', '.join(item.get('blockers') or []) or 'BRAK',
                            })
                        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
                    else:
                        st.info('Brak zapisanej historii kandydatów — worker uzupełni ją przy następnym poprawnym skanie.')
                auto_ai=st.session_state.get('_paper_remote_auto_ai') or {}
                if auto_ai:
                    with st.expander('🤖 AUTOMATYCZNY GPT — OSTATNIA ANALIZA WORKERA (PAPER)'):
                        st.caption(f"Status: {auto_ai.get('status','BRAK')} | Model: {auto_ai.get('model','BRAK')} | Dzisiaj: {auto_ai.get('daily_calls',0)} wywołań | Miesiąc: {auto_ai.get('monthly_calls',0)} wywołań")
                        st.caption(f"Ostatnia analiza UTC: {auto_ai.get('last_report_utc','BRAK')} | Świeca: {auto_ai.get('last_report_candle','BRAK')} | Sygnał: {auto_ai.get('last_action','BRAK')}")
                        st.markdown(auto_ai.get('last_report') or 'Brak zapisanego komentarza GPT. Sprawdź opt-in, klucz workera i limity wywołań.')
                        st.caption('AI komentuje dane DEMO; nie widzi screenshotu, nie składa zleceń i nie omija blokad. Limity wywołań nie są limitem kwotowym faktury.')
                else:
                    st.caption('🤖 Automatyczny GPT: brak zapisanych analiz. Domyślnie wyłączony; wymaga osobnego klucza i opt-in w GitHub Actions.')
            else:
                st.caption('Lokalna historia PAPER v3; w Streamlit Cloud może zniknąć podczas redeploy.')
            all_positions=[p for p in recent_positions(paper_db,200)
                if p['source']=='Capital.com DEMO REST' and p['epic']==instrument]
            days,weeks,summary=daily_weekly(paper_db,epic=instrument)
            x1,x2,x3,x4=st.columns(4)
            x1.metric('Zamknięte PAPER v3',summary['liczba'])
            x2.metric('Skuteczność P&L > 0',
                f"{summary['win_rate_pct']:.1f}%" if summary['win_rate_pct'] is not None else 'BRAK')
            x3.metric('Suma po kosztach',f"{summary['suma_pkt']:+.2f} pkt")
            x4.metric('Max obsunięcie',f"{summary['max_drawdown_pkt']:.2f} pkt")
            if summary['liczba']:
                st.caption(
                    f"Średni wynik: {summary['expectancy_pkt']:+.3f} pkt | "
                    f"średnie R: {summary['avg_R']:+.3f} | "
                    f"Profit factor: {summary['profit_factor'] if summary['profit_factor'] is not None else 'BRAK MIARODAJNEJ STRATY'}")
            if summary['liczba']<30:
                st.warning('Mała próba (<30 zamkniętych PAPER v3) — NIE ma dowodu rentowności.')
            policy_stats=performance_by_policy(paper_db,epic=instrument)
            if policy_stats:
                st.markdown('**📊 WYNIKI WEDŁUG POLITYKI WYJŚCIA — FIXED / ADAPTIVE**')
                st.dataframe(pd.DataFrame(policy_stats),hide_index=True,use_container_width=True)
                st.caption('To odrębne zbiory transakcji; bez testu na identycznych '
                           'sygnałach nie porównuj ich jako dowodu przewagi ADAPTIVE.')
            st.download_button('💾 POBIERZ PEŁNY BACKUP PAPER v3 (JSON, bez sekretów)',
                data=json.dumps(dump_state(paper_db),ensure_ascii=False,
                    indent=2).encode('utf-8'),
                file_name='FOKUS_PAPER_V3_BACKUP.json',
                mime='application/json',key='paper_full_json_backup',
                help='Obejmuje pełne pozycje i zdarzenia z aktualnego źródła: remote albo lokalne. To kopia wrażliwej historii inwestycyjnej — przechowuj prywatnie.')
            if all_positions:
                st.markdown('**Pozycje PENDING / OPEN / CLOSED / INVALIDATED**')
                st.dataframe(pd.DataFrame(all_positions),hide_index=True,use_container_width=True)
                st.download_button('⬇️ Zapis pozycji PAPER v3 CSV',
                    data=pd.DataFrame(all_positions).to_csv(index=False).encode('utf-8-sig'),
                    file_name='FOKUS_PAPER_V3_POZYCJE.csv',mime='text/csv',key='paper_v3_export')
            else:
                st.caption('Brak pozycji v3 dla tego instrumentu. Po skanie dopiero pełny setup generuje PENDING.')
            rejected=([] if remote_paper_view_enabled() else
                [r for r in recent_scan_decisions(paper_db,200)
                 if r['source']=='Capital.com DEMO REST' and
                    r['epic']==instrument and r['action']=='WAIT'])
            if remote_paper_view_enabled():
                st.caption('Dziennik WAIT z archiwum v2 jest lokalny i nie jest częścią zdalnego checkpointu v3.')
            if rejected:
                with st.expander('⛔ Odrzucone setupy / WAIT — powody i godziny'):
                    st.dataframe(pd.DataFrame(rejected),hide_index=True,
                        use_container_width=True)
            all_events=[e for e in recent_events(paper_db,200)
                if any(p['trade_id']==e['trade_id'] for p in all_positions)]
            if all_events:
                with st.expander('📑 Dziennik zdarzeń OPEN / SL / TP / TIMEOUT / INVALIDATED'):
                    st.dataframe(pd.DataFrame(all_events),hide_index=True,use_container_width=True)
            left,right=st.columns(2)
            with left:
                st.markdown('**Raport dzienny (czas Polska)**')
                if not days.empty:st.dataframe(days,hide_index=True,use_container_width=True)
                else:st.caption('Brak zakończonych transakcji.')
            with right:
                st.markdown('**Raport tygodniowy (czas Polska)**')
                if not weeks.empty:st.dataframe(weeks,hide_index=True,use_container_width=True)
                else:st.caption('Brak zakończonych transakcji.')
        except (OSError,sqlite3.Error,ValueError,TypeError,RemoteError) as ex:
            st.error('Nie można wyświetlić raportu PAPER v3 / cloud: '+type(ex).__name__)
        alerts_enabled=secret('PAPER_TELEGRAM_ALERTS_ENABLED','false').lower() in ('true','1','yes')
        st.caption('📣 Alerty Telegram: '+('WŁĄCZONE w Secrets' if alerts_enabled else
            'WYŁĄCZONE (domyślnie). Włącz przez PAPER_TELEGRAM_ALERTS_ENABLED=true oraz ustaw token i chat ID w Secrets.'))
        st.caption('Telegram: jedna próba wysłania na event_id. Jeśli żądanie się nie powiedzie, alert może zostać utracony i NIE będzie ponawiany, aby nie tworzyć duplikatów.')

    with st.expander('🧪 CSV M1 — PORÓWNAJ 6 STRATEGII BEZ MTF I Z MTF (OFFLINE)',expanded=True):
        st.info('Reprodukowalny test OFFLINE: w CSV kolumna Time oznacza UTC CZAS ZAMKNIĘCIA świecy M1, nie czas otwarcia. M5/M15/H1 są agregowane z pełnych bloków M1 (nie z odrębnego feedu brokera).')
        offline_csv=st.file_uploader('📁 Wybierz historyczny CSV M1 (Time, Open, High, Low, Close, opcjonalnie Spread)',
            type=['csv'],key='offline_mtf_csv',help='Potrzeba 4600–6500 kolejnych minut, w tym >=70 pełnych godzin H1. Długie przerwy mogą wykluczyć raport.')
        c_a,c_b=st.columns(2)
        with c_a:
            offline_spread=st.number_input('Spread testowy, jeśli brak informacji w CSV (pkt)',
                min_value=0.0,max_value=10.0,value=0.6,step=0.1,key='offline_mtf_spread')
        with c_b:
            offline_slip=st.number_input('Poślizg na stronę (pkt)',
                min_value=0.0,max_value=5.0,value=0.25,step=0.05,key='offline_mtf_slip')
        st.caption('⚠️ Wyniki po kosztach są symulacją ze STAŁYM spreadem zadanym powyżej. CSV Spread może zawierać rzeczywiste obserwacje, ale ten wariant replay jeszcze nie symuluje zmian spreadu w czasie. Nie zakładaj, że wyniki to rzeczywiste transakcje.')
        if st.button('🔬 TEST OFFLINE: BEZ MTF vs Z MTF — 6 STRATEGII',
                     key='offline_mtf_start',type='primary',use_container_width=True):
            if offline_csv is None:
                st.warning('Wybierz CSV M1 z danymi historycznymi.')
            else:
                with st.spinner('Rekonstrukcja 4 interwałów z M1, chronologiczny test PAPER i koszty...'):
                    try:
                        file_bytes=offline_csv.getvalue()
                        file_hash=hashlib.sha256(file_bytes).hexdigest()
                        import io as _io
                        offline=read_ohlc_csv(_io.BytesIO(file_bytes),default_spread=offline_spread)
                        table,trade_table,counts=compare_mtf_on_m1_csv(
                            offline,spread=offline_spread,slippage=offline_slip,
                            holding=20,split=.70)
                        st.session_state['_csv_mtf_result']={
                            'table':table,'trades':trade_table,'counts':counts,
                            'sha256':file_hash,'size':len(offline),
                            'costs':(offline_spread,offline_slip)}
                    except (ValueError,TypeError,KeyError,OverflowError) as ex:
                        st.session_state.pop('_csv_mtf_result',None)
                        st.error('Nie wykonano raportu CSV MTF: '+str(ex))
        csv_result=st.session_state.get('_csv_mtf_result')
        if csv_result:
            current_file_sha=(hashlib.sha256(offline_csv.getvalue()).hexdigest()
                              if offline_csv is not None else None)
            if (current_file_sha!=csv_result['sha256'] or
                csv_result['costs']!=(offline_spread,offline_slip)):
                st.warning('⚠️ Plik CSV albo parametry kosztów zostały zmienione. Poprzedni raport ukryto — kliknij TEST OFFLINE ponownie, aby nie mieszać wyników różnych prób.')
                csv_result=None
        if csv_result:
            st.success(f"Raport offline: {csv_result['size']} świec M1; hash pliku SHA256: {csv_result['sha256'][:18]}…; agregaty pełne: {csv_result['counts']}.")
            st.caption('Podział 70/30 liczony PO rozgrzaniu 70 pełnych godzin H1. Reguły strategii identyczne; wariant Z MTF może odrzucać sygnały, ale nie otwiera ich sam. Każdy wariant ma własną, niepokrywającą się historię pozycji PAPER.')
            comp=csv_result['table']
            st.dataframe(comp,use_container_width=True,hide_index=True)
            st.download_button('⬇️ CSV: PORÓWNANIE 6 STRATEGII',
                data=comp.to_csv(index=False).encode('utf-8-sig'),
                mime='text/csv',file_name='FOKUS_CSV_MTF_POROWNANIE.csv',
                key='offline_mtf_export')
            trades=csv_result['trades']
            if not trades.empty:
                st.download_button('⬇️ CSV: ROZLICZENIA POSZCZEGÓLNYCH POZYCJI PAPER',
                    data=trades.to_csv(index=False).encode('utf-8-sig'),
                    mime='text/csv',file_name='FOKUS_CSV_MTF_TRADE_LOG.csv',
                    key='offline_mtf_trades_export')
            later=comp[comp['okres']=='PÓŹNIEJSZE / 30%']
            if len(later) and (later.n<30).any():
                st.warning('Część wyników późniejszego holdout ma mniej niż 30 zakończonych transakcji. NIE wyciągaj wniosku o skuteczności MTF na tak małej próbie.')
            st.warning('Wyniki OFFLINE nie obejmują rzeczywistych ticków, poślizgu dynamicznego, brokerowych blackoutów makro, prowizji i historycznej zmienności spreadu. Nie testują połączenia Capital.com LIVE.')
    st.markdown('### 📉 Podstawowy replay bieżącej serii')
    if snap is None or len(snap.frame)<125:
        st.warning('Do raportu potrzeba >=125 zamkniętych świec. Najlepiej kilkadziesiąt tysięcy świec z wiarygodnego archiwum, a nie tylko 350 z REST.')
    else:
        if remote_paper_view_enabled() and src=='Capital.com DEMO REST':
            key=f'{instrument}|{tf}|{src}'
            if st.button('☁️ POBIERZ DO 5000 ZAMKNIĘTYCH ŚWIEC Z TRWAŁEJ BAZY',
                         key='cloud_ohlc_fetch'):
                try:
                    remote=RemoteCheckpoint(secret('FOKUS_SUPABASE_URL'),
                                            secret('FOKUS_SUPABASE_SECRET_KEY'))
                    cloud_df=remote.fetch_candles(instrument,tf,source=src,limit=5000)
                    st.session_state['_cloud_ohlc']={'key':key,'frame':cloud_df}
                    st.success(f'Wczytano {len(cloud_df)} zamkniętych świec z Supabase.')
                except (RemoteError,ValueError,TypeError) as ex:
                    st.session_state.pop('_cloud_ohlc',None)
                    st.error('Nie udało się wczytać świec Cloud: '+type(ex).__name__)
            cloud_cached=st.session_state.get('_cloud_ohlc') or {}
            saved_candles=(cloud_cached.get('frame')
                if cloud_cached.get('key')==key else None)
            if saved_candles is None:
                saved_candles=pd.DataFrame()
            st.caption(f'Cloud OHLC: {len(saved_candles)} załadowanych świec; bez pobrania nadal testujemy tylko bieżący odczyt brokera.')
        elif remote_paper_view_enabled():
            saved_candles=pd.DataFrame()
            st.caption('Cloud history udostępniona tylko dla Capital DEMO. Nie mieszam z LIVE lub CSV.')
        else:
            try:
                saved_candles=load_candles(connect(),instrument,src,tf)
            except (OSError,sqlite3.Error,ValueError):
                saved_candles=pd.DataFrame()
            st.caption(f'Lokalnie zapisane OHLC dla {instrument}/{tf}: {len(saved_candles)} świec (niegwarantowana trwałość).')
        research_frame=saved_candles if len(saved_candles)>len(snap.frame) else snap.frame
        st.caption(f'Wersja raportu: {len(research_frame)} potwierdzonych świec. To test PAPER, nie zysk realny.')
        x,y=st.columns(2)
        with x:
            research_spread=st.number_input('Spread w teście (pkt)',value=float(snap.spread),min_value=0.,max_value=10.,step=.1,key='research_spread')
        with y:
            research_slip=st.number_input('Poślizg na stronę (pkt)',value=.25,min_value=0.,max_value=5.,step=.05,key='research_slip')
        st.caption(f'Badany zbiór: {len(research_frame)} świec {tf}. CSV nie jest ceną wykonalną. Limit przyczynowego replay: maksimum 1 pozycja na raz.')
        if st.button('🔬 PRZELICZ WSZYSTKIE 6 STRATEGII / HOLDOUT',type='primary',key='research_run'):
            with st.spinner('Liczenie formacji i symulacji z uwzględnieniem kosztów...'):
                try:
                    result=chronological_report(research_frame,ALL_STRATEGIES,
                        spread=research_spread,slippage=research_slip,holding=20)
                    st.session_state['_latest_research']={'table':result,
                        'signature':f'{src}|{instrument}|{tf}|{len(research_frame)}|{research_frame.index[-1]}'}
                except (ValueError,KeyError) as ex:
                    st.error('Błąd walidacji danych: '+str(ex))
        current_sig=f'{src}|{instrument}|{tf}|{len(research_frame)}|{research_frame.index[-1]}'
        research=st.session_state.get('_latest_research')
        if research and research['signature']==current_sig:
            table=research['table']
            st.dataframe(table,use_container_width=True,hide_index=True)
            st.download_button('⬇️ EKSPORT RAPORTU CSV',data=table.to_csv(index=False).encode('utf-8-sig'),
                file_name='FOKUS_RESEARCH_HOLDOUT.csv',mime='text/csv')
            if int(table.n.sum())<30:
                st.warning('Łącznie mniej niż 30 rozstrzygniętych transakcji w raportowanych sekcjach. To ZA MAŁO, by mówić o przewadze.')
            if st.button('🔁 KROCZĄCE OKNA OOS — WYBRANA STRATEGIA',key='rolling_run'):
                folds=rolling_oos(research_frame,('DRUGA FALA' if strategy==AUTO_MODE else strategy),spread=research_spread,slippage=research_slip)
                st.dataframe(folds,hide_index=True,use_container_width=True)
        else:
            st.info('Kliknij PRZELICZ. Wyniki nie są generowane automatycznie na każdej świecy.')
    st.markdown('#### Statystyki forward PAPER zapisane przez bota')
    try:
        historical=paper_report(connect())
        if historical:
            resolved=pd.DataFrame(historical)
            resolved=resolved[resolved.status.isin(['WIN','LOSS','TIMEOUT'])]
            if not resolved.empty:
                st.metric('Rozliczone v2 (bez legacy)',len(resolved))
                st.metric('Suma punktów po kosztach',f'{resolved.pnl_pts.sum():+.2f}')
                grp=resolved.groupby(['strategy','timeframe'],as_index=False).agg(
                    liczba=('pnl_pts','size'),suma_pkt=('pnl_pts','sum'),
                    srednia_pkt=('pnl_pts','mean'))
                st.dataframe(grp,hide_index=True,use_container_width=True)
            else:
                st.info('Jeszcze brak pełnych wyników v2 do statystyki.')
        else:
            st.info('Nie zapisano nowych rozliczonych transakcji PAPER v2.')
    except (OSError,sqlite3.Error) as ex:
        st.warning('Archiwum niedostępne: '+type(ex).__name__)
    if st.session_state.get('_history_write_error'):
        st.warning('Błąd zapisu lokalnego archiwum świec: '+st.session_state['_history_write_error'])
    st.warning('Ważne: lokalny SQLite w Streamlit Cloud nie jest trwałą bazą. Po ponownym wdrożeniu może zostać wyczyszczony. Do autentycznego gromadzenia historii latami potrzebna jest baza zewnętrzna.')
