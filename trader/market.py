"""Capital.com READ-ONLY market data. Never sends trading instructions."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import time
import requests
import pandas as pd

PERIOD = {'MINUTE': 60, 'MINUTE_5': 300, 'MINUTE_15': 900, 'HOUR': 3600}
BASE = 'https://demo-api-capital.backend-capital.com'

class FeedError(RuntimeError):
    pass

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

def evaluate_snapshot(raw: pd.DataFrame, epic: str, resolution: str,
                      now: datetime | None = None, max_spread: float = 2.0) -> Snapshot:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now musi mieć strefę czasową')
    if resolution not in PERIOD:
        raise ValueError('Nieznany interwał')
    if raw.empty or len(raw) < 70:
        return Snapshot(raw.iloc[0:0], 'Capital.com DEMO REST', epic, resolution, 0, None, None, False,
                        'Za mało świec (wymagane minimum 70)')
    # The newest candle could still be forming; use the preceding closed candle.
    confirmed = raw.iloc[:-1].copy()
    confirmed_time = confirmed.index[-1].to_pydatetime()
    age = (now - confirmed_time).total_seconds()
    step = PERIOD[resolution]
    spread = float(raw.iloc[-1]['Spread'])
    if raw.index[-1] <= confirmed.index[-1]:
        reason = 'Brak świecy następującej po świecy sygnałowej'
    elif age < -step:
        reason = 'Świece z przyszłości / błędna strefa czasu'
    elif age > step * 3 + 60:
        reason = f'Dane przestarzałe ({age:.0f} s)'
    elif spread > max_spread:
        reason = f'Za duży spread: {spread:.2f} > {max_spread:.2f}'
    elif confirmed[['Open','High','Low','Close']].tail(25).isna().any().any():
        reason = 'Puste OHLC'
    elif (confirmed.index[-20:].to_series().diff().dt.total_seconds().dropna() > step * 4).any():
        reason = 'Wykryto duże luki w świecach'
    else:
        reason = 'OK: poprzednia świeca ma nowszego następcę (nie potwierdza ticków ani jakości feedu)'
    return Snapshot(confirmed, 'Capital.com DEMO REST', epic, resolution,
                    spread, confirmed_time, age, reason.startswith('OK:'), reason)

class CapitalReadOnly:
    def __init__(self, api_key: str, identifier: str, password: str):
        if not (api_key and identifier and password):
            raise FeedError('Brak kluczy CAPITAL_API_KEY / CAPITAL_IDENTIFIER / CAPITAL_PASSWORD')
        self.api_key, self.identifier, self.password = api_key, identifier, password
        self.session = requests.Session()
        self.cst = self.token = None
        self.session_started = 0

    def headers(self):
        if not self.cst or time.time() - self.session_started >= 480:
            # POST below is session authentication only, NEVER a trading order.
            try:
                r = self.session.post(f'{BASE}/api/v1/session',
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
                raise FeedError(f'Błąd logowania Capital.com: {type(ex).__name__}') from ex
        return {'X-CAP-API-KEY': self.api_key, 'CST': self.cst,
                'X-SECURITY-TOKEN': self.token}

    def candles(self, epic='US500', resolution='MINUTE', count=300, max_spread=2.0):
        if resolution not in PERIOD:
            raise FeedError('Nieobsługiwany interwał')
        if not epic.replace('_','').isalnum():
            raise FeedError('Niepoprawny EPIC')
        try:
            r = self.session.get(f'{BASE}/api/v1/prices/{epic}',
                params={'resolution':resolution, 'max':min(int(count), 1000)},
                headers=self.headers(), timeout=12)
            r.raise_for_status()
            return evaluate_snapshot(parse_prices(r.json()), epic, resolution, max_spread=max_spread)
        except requests.RequestException as ex:
            raise FeedError(f'Pobieranie świec nieudane: {type(ex).__name__}') from ex
        except ValueError as ex:
            raise FeedError(f'Niepoprawny JSON API: {ex}') from ex
