"""Deterministic educational strategies; only pre-existing closed bars are used."""
from dataclasses import dataclass
import pandas as pd
import numpy as np

@dataclass
class Decision:
    action: str
    strategy: str
    reason: str
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    rr: float | None = None
    atr: float | None = None
    bias: str = 'NEUTRAL'

def indicators(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()
    for n in (9,21,50):
        df[f'EMA{n}'] = df.Close.ewm(span=n,adjust=False).mean()
    prev = df.Close.shift(1)
    tr = pd.concat([(df.High-df.Low).abs(), (df.High-prev).abs(),
                    (df.Low-prev).abs()],axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14,min_periods=14).mean()
    delta = df.Close.diff()
    up = delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    df['RSI'] = np.where(down==0,100,100-100/(1+up/down))
    return df

def _trend(df):
    a=df.iloc[-1]
    if a.EMA9>a.EMA21>a.EMA50:return 'UP'
    if a.EMA9<a.EMA21<a.EMA50:return 'DOWN'
    return 'NEUTRAL'

def decide(frame: pd.DataFrame,strategy='DRUGA FALA',htf=None,spread=.6,min_rr=1.5, *, obstacle_mode='legacy')->Decision:
    if obstacle_mode not in ('legacy','confirmed_swings'):
        raise ValueError('Nieznany model oporów/wsparć (research).')
    if len(frame)<70 or spread<0:
        return Decision('WAIT',strategy,'Brak świec lub ujemny spread')
    df=indicators(frame)
    a=df.iloc[-1]
    atr=float(a.ATR)
    if not np.isfinite(atr) or atr<=0:
        return Decision('WAIT',strategy,'ATR niedostępny')
    bias=_trend(df)
    htf_bias=_trend(indicators(htf)) if htf is not None and len(htf)>=70 else None
    if htf is not None and htf_bias is None:
        return Decision('WAIT',strategy,'Brak 70 świec HTF',atr=atr,bias=bias)
    if spread>max(1.2,.4*atr):
        return Decision('WAIT',strategy,'Spread zbyt wysoki wobec ATR',atr=atr,bias=bias)
    if strategy=='EMA TREND':
        direction='LONG' if bias=='UP' and a.Close>a.EMA9 and 47<=a.RSI<=70 else (
                  'SHORT' if bias=='DOWN' and a.Close<a.EMA9 and 30<=a.RSI<=53 else 'WAIT')
        if direction=='WAIT':
            return Decision('WAIT',strategy,'Brak potwierdzonego trendu EMA/RSI',atr=atr,bias=bias)
    elif strategy=='DRUGA FALA':
        prior=df.iloc[-22:-9]
        impulse=float(prior.Close.iloc[-1]-prior.Close.iloc[0])
        correction=df.iloc[-9:-2]
        lower_break=a.Close<df.Low.iloc[-5:-1].min() and a.Close<a.EMA9
        upper_break=a.Close>df.High.iloc[-5:-1].max() and a.Close>a.EMA9
        pullback_short=correction.High.max()>=correction.EMA9.max()-.3*atr
        pullback_long=correction.Low.min()<=correction.EMA9.min()+.3*atr
        if bias=='DOWN' and impulse<=-1.5*atr and pullback_short and lower_break:
            direction='SHORT'
        elif bias=='UP' and impulse>=1.5*atr and pullback_long and upper_break:
            direction='LONG'
        else:
            return Decision('WAIT',strategy,'Brak sekwencji impuls → korekta → wybicie',atr=atr,bias=bias)
    else:
        return Decision('WAIT',strategy,'Strategia niezaimplementowana',atr=atr,bias=bias)
    if htf_bias and (direction=='LONG' and htf_bias!='UP' or direction=='SHORT' and htf_bias!='DOWN'):
        return Decision('WAIT',strategy,'Niepotwierdzony trend HTF',atr=atr,bias=bias)
    entry=float(a.Close)
    swing=df.iloc[-9:-1]
    if direction=='LONG':
        stop=float(min(swing.Low.min()-.15*atr,entry-1.15*atr))
        risk=entry-stop
        target=entry+2*risk
        if obstacle_mode=='confirmed_swings':
            from .structure_levels import structural_room
            blocked=structural_room(frame,'LONG',entry,risk,min_rr).blocked
        else:
            resistance=df.High.iloc[-60:-10]
            obstacles=resistance[resistance>entry]
            blocked=bool(len(obstacles) and obstacles.min()-entry<min_rr*risk)
        if blocked:
            return Decision('WAIT',strategy,'Zbyt bliski opór'+
                            (' (potwierdzony swing)' if obstacle_mode=='confirmed_swings' else ''),atr=atr,bias=bias)
    else:
        stop=float(max(swing.High.max()+.15*atr,entry+1.15*atr))
        risk=stop-entry
        target=entry-2*risk
        if obstacle_mode=='confirmed_swings':
            from .structure_levels import structural_room
            blocked=structural_room(frame,'SHORT',entry,risk,min_rr).blocked
        else:
            support=df.Low.iloc[-60:-10]
            obstacles=support[support<entry]
            blocked=bool(len(obstacles) and entry-obstacles.max()<min_rr*risk)
        if blocked:
            return Decision('WAIT',strategy,'Zbyt bliskie wsparcie'+
                            (' (potwierdzony swing)' if obstacle_mode=='confirmed_swings' else ''),atr=atr,bias=bias)
    if risk<=spread*1.5 or not np.isfinite(target):
        return Decision('WAIT',strategy,'Geometria ryzyka niepoprawna',atr=atr,bias=bias)
    rr=(abs(target-entry)-spread)/(risk+spread)
    if rr<min_rr:
        return Decision('WAIT',strategy,'RR po spreadzie poniżej minimum',atr=atr,bias=bias)
    return Decision(direction,strategy,'Wykryty sygnał PAPER (nie zlecenie)',
                    round(entry,2),round(stop,2),round(target,2),
                    round(rr,2),round(atr,2),bias)

def simulate_outcome(bars,direction,entry,stop,target,spread,slippage=.25, *, exit_spreads=None):
    """PAPER: entry, SL and TP are MID price *levels*, not executable quotes.

    Fill a new trade at next bar OPEN ask (LONG) / bid (SHORT), with adverse
    slippage. Stop has priority if both MID barriers touch in one OHLC bar.
    Exit LONG at bid / SHORT at ask, again with adverse slippage. A stop
    gap is filled at the worse of stop or bar opening MID. Optional exit_spreads
    must represent the LAST KNOWN closed-bar spread before each exit candle;
    never use that candle's future close spread for an intrabar TP/SL.
    This is NOT broker execution or tick replay.
    """
    if direction not in ('LONG','SHORT') or not np.isfinite(spread) or spread<0 or not np.isfinite(slippage) or slippage<0:
        raise ValueError('Nieprawidłowy kierunek, spread lub poślizg.')
    if exit_spreads is None:
        exit_values=[float(spread)]*len(bars)
    else:
        exit_values=[float(v) for v in exit_spreads]
        if len(exit_values)!=len(bars) or any(not np.isfinite(v) or v<0 for v in exit_values):
            raise ValueError('Historyczne spready wyjścia są niekompletne lub ujemne.')
    if len(bars)<1:
        return 'PENDING',0.0
    first_mid=float(bars.iloc[0].Open)
    entry_fill=(first_mid+spread/2+slippage if direction=='LONG'
                else first_mid-spread/2-slippage)
    if (direction=='LONG' and not stop<first_mid<target) or (
        direction=='SHORT' and not target<first_mid<stop):
        return 'SKIPPED_GAP',0.0
    for k,(_,r) in enumerate(bars.iterrows()):
        exit_spread=exit_values[k]
        if direction=='LONG':
            if float(r.Low)<=stop:
                exit_mid=min(float(stop),float(r.Open))
                exit_bid=exit_mid-exit_spread/2-slippage
                return 'LOSS',round(exit_bid-entry_fill,2)
            if float(r.High)>=target:
                exit_bid=float(target)-exit_spread/2-slippage
                return 'WIN',round(exit_bid-entry_fill,2)
        else:
            if float(r.High)>=stop:
                exit_mid=max(float(stop),float(r.Open))
                exit_ask=exit_mid+exit_spread/2+slippage
                return 'LOSS',round(entry_fill-exit_ask,2)
            if float(r.Low)<=target:
                exit_ask=float(target)+exit_spread/2+slippage
                return 'WIN',round(entry_fill-exit_ask,2)
    return 'PENDING',0.0

def backtest(frame,strategy='DRUGA FALA',spread=.6,slippage=.25,max_holding=24,min_rr=1.5):
    """Exploratory replay; not a verified out-of-sample profitability test."""
    if len(frame)<85:
        return pd.DataFrame()
    trades=[]
    i=70
    while i<len(frame)-2:
        d=decide(frame.iloc[:i],strategy,spread=spread,min_rr=min_rr)
        if d.action=='WAIT':
            i+=1
            continue
        future=frame.iloc[i:min(i+max_holding+1,len(frame))]
        status,pnl=simulate_outcome(future,d.action,d.entry,d.stop,d.target,spread,slippage)
        trades.append({'bar_utc':frame.index[i-1],'side':d.action,'status':status,
                       'pnl_pts':pnl,'entry':d.entry,'sl':d.stop,'tp':d.target,'rr_est':d.rr})
        i+=max_holding+1
    return pd.DataFrame(trades)
