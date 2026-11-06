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


@dataclass(frozen=True)
class MarketQuote:
    """Read-only Capital.com snapshot. Never a closed candle or broker fill."""
    epic: str
    environment: str
    bid: float
    ask: float
    mid: float
    spread: float
    status: str
    update_utc: datetime | None
    received_utc: datetime
    delay_seconds: float
    fresh: bool


def parse_market_quote(payload: dict, epic: str, environment: str,
                       now: datetime | None = None) -> MarketQuote:
    """Validate one live-market quote independently of OHLC strategy data."""
    import math
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timestamp cytatu bez strefy")
    if not isinstance(payload,dict):
        raise FeedError("Zły format odpowiedzi /markets")
    snap=payload.get("snapshot") or {}
    instrument=payload.get("instrument") or {}
    if not isinstance(snap,dict) or not isinstance(instrument,dict):
        raise FeedError("Błędny JSON snapshot /markets")
    try:
        bid=float(snap["bid"])
        ask=float(snap["offer"])
    except (KeyError,ValueError,TypeError) as ex:
        raise FeedError("Brak poprawnych BID/OFFER w /markets") from ex
    if not all(math.isfinite(x) for x in (bid,ask)) or bid<=0 or ask<bid:
        raise FeedError("Wadliwy bieżący BID/OFFER (bid > ask lub NaN)")
    status=str(snap.get("marketStatus") or instrument.get("marketStatus")
               or "UNKNOWN").upper()
    update_utc=None
    timestamp=snap.get("updateTimeUTC")
    if timestamp:
        try:
            stamp=pd.Timestamp(timestamp)
            if not pd.isna(stamp):
                update_utc=(stamp.tz_localize("UTC") if stamp.tzinfo is None
                            else stamp.tz_convert("UTC")).to_pydatetime()
        except (ValueError,TypeError,OverflowError):
            update_utc=None
    try:
        delay_seconds=float(snap.get("delayTime") or 0)
    except (ValueError,TypeError):
        delay_seconds=-1
    # No vendor timestamp or delayed quote is NEVER shown as fresh LIVE.
    age=(now-update_utc).total_seconds() if update_utc is not None else None
    fresh=(status=="TRADEABLE" and delay_seconds==0 and age is not None
           and -10<=age<=30)
    return MarketQuote(str(epic),str(environment).upper(),bid,ask,
                       (bid+ask)/2,ask-bid,status,update_utc,now,
                       delay_seconds,fresh)



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

def parse_prices(payload: dict, *, quarantine_bad: bool = False) -> pd.DataFrame:
    """Parse Capital quotes; optional quarantine NEVER authorizes trading.

    A crossed bid/ask quote can occur in a broker response. In chart mode,
    skip the malformed BAR (not a price field), remember its UTC label and
    return only structurally valid bars. A snapshot containing any quarantined
    bar is marked NOT GOOD by evaluate_snapshot and cannot create signals.
    Diagnostic raw-label reads stay strict by default.
    """
    rows = []
    quarantined = []
    prices = payload.get('prices', [])
    if not isinstance(prices, list):
        raise FeedError('Nieprawidłowa lista świec Capital.com')
    for item in prices:
        label = str(item.get('snapshotTimeUTC', 'BRAK'))[:36] if isinstance(item, dict) else 'BRAK'
        try:
            t = pd.to_datetime(item['snapshotTimeUTC'], utc=True)
            if pd.isna(t):
                raise ValueError('Brak timestamp UTC')
            row = {'time': t}
            for field, val in [('Open', 'openPrice'), ('High', 'highPrice'),
                               ('Low', 'lowPrice'), ('Close', 'closePrice')]:
                b, a = float(item[val]['bid']), float(item[val]['ask'])
                import math
                if not (math.isfinite(b) and math.isfinite(a) and b>0 and a>0):
                    raise ValueError(f'{field}: NaN/Infinity/ujemna cena BID/ASK')
                if b > a:
                    raise ValueError(f'{field}: bid > ask')
                row[field] = (b + a) / 2
                if field == 'Close':
                    row['Bid'] = b
                    row['Ask'] = a
                    row['Spread'] = a - b
            if (row['High'] < max(row['Open'], row['Close'], row['Low']) or
                row['Low'] > min(row['Open'], row['Close'], row['High'])):
                raise ValueError('Niespójne OHLC')
            rows.append(row)
        except (KeyError, TypeError, ValueError, OverflowError) as ex:
            if not quarantine_bad:
                raise FeedError(f'Nieprawidłowy rekord danych Capital: {ex}') from ex
            quarantined.append({'candle_utc': label, 'issue': str(ex)[:60]})
    if not rows:
        raise FeedError(f'Brak poprawnych świec z API Capital.com; odrzucono {len(quarantined)}')
    df = pd.DataFrame(rows).set_index('time').sort_index()
    if df.index.has_duplicates:
        # Duplicate UTC labels cannot be reconciled safely by choosing one.
        raise FeedError('Duplikaty timestampów OHLC')
    df.attrs['quarantined_candles'] = tuple(quarantined)
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
    result.attrs["quarantined_candles"]=raw.attrs.get("quarantined_candles",())
    return result


def evaluate_snapshot(raw: pd.DataFrame, epic: str, resolution: str,
                      now: datetime | None = None, max_spread: float = 2.0,
                      source: str = 'Capital.com DEMO REST') -> Snapshot:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now musi mieć strefę czasową')
    if resolution not in PERIOD:
        raise ValueError('Nieznany interwał')
    quarantined=raw.attrs.get('quarantined_candles',())
    if raw.empty or len(raw) < 70:
        reason='Za mało poprawnych świec (wymagane minimum 70)'
        if quarantined:
            reason+=f'; odrzucono wadliwych rekordów: {len(quarantined)}'
        return Snapshot(raw.iloc[0:0], source, epic, resolution, 0, None, None, False,
                        reason)
    # The newest candle could still be forming; use the preceding closed candle.
    confirmed = raw.iloc[:-1].copy()
    confirmed_time = confirmed.index[-1].to_pydatetime()
    age = (now - confirmed_time).total_seconds()
    step = PERIOD[resolution]
    spread = float(confirmed.iloc[-1]['Spread'])  # strategy's CLOSED signal candle
    quote_spread = float(raw.iloc[-1]['Spread'])  # newest/forming bar, never model history
    if quarantined:
        first=quarantined[0]
        from collections import Counter
        counts=Counter(x["issue"] for x in quarantined)
        categories=", ".join(f"{k}={v}" for k,v in counts.most_common(4))
        reason=(f'DANE_WADLIWE: odrzucono {len(quarantined)} rekordów, '
                f'przyczyny {categories}; '
                f'np. {first["candle_utc"]}: {first["issue"]}. '
                'Wykres tylko historyczny; LONG/SHORT zablokowane do czystego odczytu.')
    elif raw.index[-1] <= confirmed.index[-1]:
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
            raw=capital_prices_as_close_times(
                parse_prices(r.json(),quarantine_bad=True),resolution)
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

    def forming_candle(self, epic='US500', resolution='MINUTE', *,
                       now=None):
        """Optional UI-only INCOMPLETE OHLC from Capital /prices, max=2.

        Same endpoint as older SP500 v7, but NO historical arrows, no PAPER
        signals, no stored strategy candles. A current OPEN-labelled last bar
        must be fresh: an old bar is NEVER portrayed as a live moving candle.
        """
        if resolution not in PERIOD or not epic.replace('_','').isalnum():
            raise FeedError('Niepoprawny EPIC lub interwał świecy w trakcie')
        try:
            r=self.session.get(f'{self.base_url}/api/v1/prices/{epic}',
                params={'resolution':resolution,'max':2},
                headers=self.headers(),timeout=8)
            r.raise_for_status()
            payload=r.json()
            items=payload.get("prices") if isinstance(payload,dict) else None
            if not isinstance(items,list) or not items:
                raise FeedError("Brak świec API do podglądu LIVE")
            # The previous bar may be corrupt while the latest is valid.
            # Never let a bad PREVIOUS bar suppress the actual live preview.
            # But if the latest is bad, do not use an older bar as LIVE.
            latest=max(items,key=lambda it:pd.Timestamp(it["snapshotTimeUTC"]))
            raw=parse_prices({"prices":[latest]})
        except requests.RequestException as exc:
            raise FeedError(http_error_message(exc,'Świeca bieżąca',epic)) from exc
        if raw.empty:
            raise FeedError('Brak świecy bieżącej w /prices')
        now=now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('Wymagany UTC datetime z tzinfo')
        open_time=raw.index[-1]
        delta=(pd.Timestamp(now)-open_time).total_seconds()
        if not (-5<=delta<=PERIOD[resolution]+5):
            raise FeedError(f'Bieżąca świeca /prices jest nieaktualna: {delta:.0f}s')
        row=raw.iloc[-1]
        close_time=open_time+pd.Timedelta(seconds=PERIOD[resolution])
        return {
            "time":close_time,
            "Open":float(row["Open"]),"High":float(row["High"]),
            "Low":float(row["Low"]),"Close":float(row["Close"]),
            "bid":float(row["Bid"]),"ask":float(row["Ask"]),
            "spread":float(row["Spread"]),
            "epic":epic,"environment":self.environment,
            "timeframe":resolution,"last_tick":open_time,
            "source":"Capital.com /prices • bieżąca OHLC",
            "samples":0,
        }

    def market_quote(self, epic: str = 'US500') -> MarketQuote:
        """Fast read-only GET: current bid/offer, status and provider timestamp."""
        if not epic.replace('_','').isalnum():
            raise FeedError('Niepoprawny EPIC')
        try:
            r=self.session.get(f'{self.base_url}/api/v1/markets/{epic}',
                headers=self.headers(),timeout=8)
            r.raise_for_status()
            return parse_market_quote(r.json(),epic,self.environment)
        except requests.RequestException as ex:
            raise FeedError(http_error_message(ex,'Bieżąca cena',epic)) from ex
        except (ValueError,TypeError,AttributeError) as ex:
            raise FeedError('Błędny JSON bieżącej ceny Capital.com') from ex

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
