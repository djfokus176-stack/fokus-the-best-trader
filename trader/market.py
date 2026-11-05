"""Capital.com READ-ONLY market data. Never sends trading instructions."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import time
import requests
import pandas as pd

PERIOD = {'MINUTE': 60, 'MINUTE_5': 300, 'MINUTE_15': 900, 'HOUR': 3600}
API_BASE = {
    'DEMO': 'https://demo-api-capital.backend-capital.com',
    'LIVE': 'https://api-capital.backend-capital.com',
}

class FeedError(RuntimeError):
    pass


def http_error_message(exc, stage, epic=''):
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    if not status:
        return f'{stage}: błąd połączenia ({type(exc).__name__}). Sprawdź sieć i serwer API.'
    if status in (401, 403):
        return f'{stage}: HTTP {status} — sprawdź środowisko DEMO/LIVE, login i hasło API. Sam klucz może działać w innej aplikacji.'
    if status == 404:
        return f'{stage}: HTTP 404 — nie znaleziono instrumentu {epic}. Zweryfikuj EPIC przez wyszukiwarkę rynków Capital.com.'
    if status == 429:
        return f'{stage}: HTTP 429 — przekroczony limit zapytań Capital.com. Ogranicz częstotliwość.'
    return f'{stage}: HTTP {status}. Odczyt danych nie powiódł się.'

@dataclass
class Snapshot:
    frame: pd.DataFrame
    source: str
    epic: str
    resolution: str
    spread: float
    confirmed_utc: datetime | None
    age_seconds: float | None
    good: bool
    reason: str
    quote_spread: float | None = None  # latest forming bar: for tradeability only

def parse_prices(payload: dict) -> pd.DataFrame:
    rows = []
    for item in payload.get('prices', []):
        try:
            t = pd.to_datetime(item['snapshotTimeUTC'], utc=True)
            row = {'time': t}
            for field, val in [('Open', 'openPrice'), ('High', 'highPrice'),
                               ('Low', 'lowPrice'), ('Close', 'closePrice')]:
                b, a = float(item[val]['bid']), float(item[val]['ask'])
                if b > a:
                    raise ValueError('bid > ask')
                row[field] = (b + a) / 2
                if field == 'Close':
                    row['Bid'] = b
                    row['Ask'] = a
                    row['Spread'] = a - b
            rows.append(row)
        except (KeyError, TypeError, ValueError) as ex:
            raise FeedError(f'Nieprawidłowy rekord danych Capital: {ex}') from ex
    if not rows:
        raise FeedError('Brak świec z API Capital.com')
    df = pd.DataFrame(rows).set_index('time').sort_index()
    if df.index.has_duplicates:
        raise FeedError('Duplikaty timestampów OHLC')
    if not ((df.High >= df[['Open','Close','Low']].max(axis=1)) &
            (df.Low <= df[['Open','Close','High']].min(axis=1)) &
            (df.Spread >= 0)).all():
        raise FeedError('Niespójne OHLC lub ujemny spread')
    return df

def capital_prices_as_close_times(raw: pd.DataFrame, resolution: str) -> pd.DataFrame:
    """Translate presumed Capital OPEN labels to our internal CLOSE-time format.

    On 2026-11-05 at 20:24:17 UTC, the DEMO M1 latest label was 20:24:00.
    This suggests OPEN labels, but the broker clock convention still requires
    final confirmation. New PAPER positions are blocked until owner confirms.
    Apply exactly once to original API prices, never to a CSV or Snapshot.
    """
    if resolution not in PERIOD:
        raise FeedError("Nieznany interwal danych Capital")
    if raw is None or raw.empty or raw.index.tz is None:
        raise FeedError("Niepoprawne czasy UTC danych Capital")
    if raw.attrs.get("capital_clock_basis")=="close_shifted":
        raise FeedError("Nie wolno dwukrotnie przesuwac oznaczen swiec")
    seconds=PERIOD[resolution]
    if any(int(ts.value//1_000_000_000)%seconds for ts in raw.index):
        raise FeedError("Nieprawidlowe wyrownanie czasu swiec API do UTC")
    result=raw.copy()
    result.index=raw.index+pd.Timedelta(seconds=seconds)
    result.index.name="time"
    result.attrs["capital_clock_basis"]="close_shifted"
    return result


def evaluate_snapshot(raw: pd.DataFrame, epic: str, resolution: str,
                      now: datetime | None = None, max_spread: float = 2.0,
                      source: str = 'Capital.com DEMO REST') -> Snapshot:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now musi mieć strefę czasową')
    if resolution not in PERIOD:
        raise ValueError('Nieznany interwał')
    if raw.empty or len(raw) < 70:
        return Snapshot(raw.iloc[0:0], source, epic, resolution, 0, None, None, False,
                        'Za mało świec (wymagane minimum 70)')
    # The newest candle could still be forming; use the preceding closed candle.
    confirmed = raw.iloc[:-1].copy()
    confirmed_time = confirmed.index[-1].to_pydatetime()
    age = (now - confirmed_time).total_seconds()
    step = PERIOD[resolution]
    spread = float(confirmed.iloc[-1]['Spread'])  # strategy's CLOSED signal candle
    quote_spread = float(raw.iloc[-1]['Spread'])  # newest/forming bar, never model history
    if raw.index[-1] <= confirmed.index[-1]:
        reason = 'Brak świecy następującej po świecy sygnałowej'
    elif age < -step:
        reason = 'Świece z przyszłości / błędna strefa czasu'
    elif age > step * 3 + 60:
        reason = f'Dane przestarzałe ({age:.0f} s)'
    elif spread > max_spread:
        reason = f'Spread zamkniętej świecy: {spread:.2f} > {max_spread:.2f}'
    elif quote_spread > max_spread:
        reason = f'Bieżący spread: {quote_spread:.2f} > {max_spread:.2f}'
    elif confirmed[['Open','High','Low','Close']].tail(25).isna().any().any():
        reason = 'Puste OHLC'
    elif (confirmed.index[-20:].to_series().diff().dt.total_seconds().dropna() > step * 4).any():
        reason = 'Wykryto duże luki w świecach'
    else:
        reason = 'OK: poprzednia świeca ma nowszego następcę (nie potwierdza ticków ani jakości feedu)'
    return Snapshot(confirmed, source, epic, resolution,
                    spread, confirmed_time, age, reason.startswith('OK:'), reason, quote_spread)

class CapitalReadOnly:
    def __init__(self, api_key: str, identifier: str, password: str, environment: str = 'DEMO'):
        if not (api_key and identifier and password):
            raise FeedError('Brak kluczy CAPITAL_API_KEY / CAPITAL_IDENTIFIER / CAPITAL_PASSWORD')
        self.environment = str(environment).upper().strip()
        if self.environment not in API_BASE:
            raise FeedError('Nieznane środowisko API: wybierz DEMO albo LIVE.')
        self.base_url = API_BASE[self.environment]
        self.api_key, self.identifier, self.password = api_key.strip(), identifier.strip(), password
        self.session = requests.Session()
        self.cst = self.token = None
        self.session_started = 0

    def headers(self):
        if not self.cst or time.time() - self.session_started >= 480:
            # POST below is session authentication only, NEVER a trading order.
            try:
                r = self.session.post(f'{self.base_url}/api/v1/session',
                    headers={'X-CAP-API-KEY':self.api_key, 'Content-Type':'application/json'},
                    json={'identifier':self.identifier, 'password':self.password,
                          'encryptedPassword':False}, timeout=10)
                r.raise_for_status()
                self.cst = r.headers.get('CST')
                self.token = r.headers.get('X-SECURITY-TOKEN')
                if not self.cst or not self.token:
                    raise FeedError('Brak tokenów sesji')
                self.session_started = time.time()
            except requests.RequestException as ex:
                raise FeedError(http_error_message(ex, f'Logowanie Capital.com {self.environment}')) from ex
        return {'X-CAP-API-KEY': self.api_key, 'CST': self.cst,
                'X-SECURITY-TOKEN': self.token}

    def candles(self, epic='US500', resolution='MINUTE', count=300, max_spread=2.0):
        if resolution not in PERIOD:
            raise FeedError('Nieobsługiwany interwał')
        if not epic.replace('_','').isalnum():
            raise FeedError('Niepoprawny EPIC')
        try:
            r = self.session.get(f'{self.base_url}/api/v1/prices/{epic}',
                params={'resolution':resolution, 'max':min(int(count), 1000)},
                headers=self.headers(), timeout=12)
            r.raise_for_status()
            # API label is presumed OPEN; trading engine expects CLOSE-time.
            # The newest possibly forming candle is still excluded downstream.
            raw=capital_prices_as_close_times(parse_prices(r.json()),resolution)
            return evaluate_snapshot(raw, epic, resolution, max_spread=max_spread,
                                     source=f'Capital.com {self.environment} REST')
        except requests.RequestException as ex:
            raise FeedError(http_error_message(ex,'Pobieranie świec',epic=epic)) from ex
        except ValueError as ex:
            raise FeedError(f'Niepoprawny JSON API: {ex}') from ex

    def raw_candle_time_diagnostic(self, epic='US500', resolution='MINUTE', count=8):
        """Owner-triggered read-only diagnostic: INCLUDE latest possibly forming bar.

        Does not send orders, does not store authentication headers and
        does not modify candle closed/open assumptions in the trading engine.
        """
        if resolution not in PERIOD or not epic.replace('_','').isalnum():
            raise FeedError('Niepoprawny interwał/instrument diagnostyki')
        try:
            r=self.session.get(f'{self.base_url}/api/v1/prices/{epic}',
                params={'resolution':resolution,'max':min(20,max(4,int(count)))},
                headers=self.headers(),timeout=12)
            r.raise_for_status()
            return parse_prices(r.json())
        except requests.RequestException as ex:
            raise FeedError(http_error_message(ex,'Diagnostyka timestampów',epic)) from ex

    def market_state(self, epic: str = 'US500') -> str:
        """Read-only instrument status; do not infer trading hours from the clock."""
        if not epic.replace('_','').isalnum():
            raise FeedError('Niepoprawny EPIC')
        try:
            r = self.session.get(f'{self.base_url}/api/v1/markets/{epic}',
                headers=self.headers(),timeout=12)
            r.raise_for_status()
            payload = r.json()
            snapshot = payload.get('snapshot') or {}
            instrument = payload.get('instrument') or {}
            raw = snapshot.get('marketStatus') or instrument.get('marketStatus')
            if raw is None:
                return 'UNKNOWN'
            return str(raw).upper()
        except requests.RequestException as ex:
            raise FeedError(http_error_message(ex,'Status instrumentu',epic=epic)) from ex
        except (ValueError,TypeError,AttributeError) as ex:
            raise FeedError('Błędny JSON statusu rynku Capital.com') from ex

    def search_markets(self, term='US500'):
        """Find the actual EPIC in the selected account (READ-ONLY GET)."""
        try:
            r = self.session.get(f'{self.base_url}/api/v1/markets',
                params={'searchTerm':str(term).strip()[:60]},headers=self.headers(),timeout=12)
            r.raise_for_status()
            markets = r.json().get('markets',[])
            return [{'EPIC':m.get('epic',''), 'Nazwa':m.get('instrumentName',''),
                     'Status':m.get('marketStatus','')} for m in markets[:30]]
        except requests.RequestException as ex:
            raise FeedError(http_error_message(ex,'Wyszukiwanie instrumentów')) from ex
        except ValueError as ex:
            raise FeedError('Nieprawidłowa odpowiedź JSON wyszukiwarki instrumentów') from ex
