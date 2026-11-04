"""FOKU$ MARKET DNA v0.2 — deterministic OHLC-only research context.

Requires CLOSED bars. Confirmed pivots use two older and two newer closed
bars (never future data relative to the analysis time). Not trading advice.
No order flow, real volume profile, or calibrated probabilities are inferred.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
import pandas as pd
from .strategy import indicators


@dataclass(frozen=True)
class MarketDNA:
    structure: str
    regime: str
    event: str
    last_close: float
    swing_high: float | None
    swing_low: float | None
    atr: float
    efficiency: float
    volatility_ratio: float
    explanation: str


def confirmed_pivots(frame: pd.DataFrame, left: int = 2, right: int = 2):
    """Pivots become known only after *right* subsequent closed bars."""
    if left < 1 or right < 1:
        raise ValueError('Potwierdzenie swingu wymaga co najmniej 1 świecy po obu stronach.')
    highs, lows = [], []
    h = frame['High'].to_numpy()
    l = frame['Low'].to_numpy()
    for i in range(left, len(frame)-right):
        hs=h[i-left:i+right+1]
        ls=l[i-left:i+right+1]
        if h[i] > max(hs[:left].max(),hs[left+1:].max()):
            highs.append((i,float(h[i])))
        if l[i] < min(ls[:left].min(),ls[left+1:].min()):
            lows.append((i,float(l[i])))
    return highs,lows


def analyze_market(frame: pd.DataFrame) -> MarketDNA:
    if frame is None or len(frame) < 70:
        raise ValueError('MARKET DNA wymaga co najmniej 70 zamkniętych świec.')
    df = indicators(frame)
    a = df.iloc[-1]
    atr = float(a['ATR'])
    if not isfinite(atr) or atr <= 0:
        raise ValueError('ATR niedostępny — analiza MARKET DNA zatrzymana.')

    # Last candle is the evaluation bar. Levels known before it are immutable.
    past_highs,past_lows = confirmed_pivots(frame.iloc[:-1])
    sh=past_highs[-1][1] if past_highs else None
    sl=past_lows[-1][1] if past_lows else None
    eps=0.05*atr

    if len(past_highs) >= 2 and len(past_lows) >= 2:
        high_rising=past_highs[-1][1] > past_highs[-2][1]
        low_rising=past_lows[-1][1] > past_lows[-2][1]
        high_falling=past_highs[-1][1] < past_highs[-2][1]
        low_falling=past_lows[-1][1] < past_lows[-2][1]
        structure='HH/HL' if high_rising and low_rising else (
                  'LH/LL' if high_falling and low_falling else 'MIESZANA')
    else:
        structure='BRAK POTWIERDZONYCH SWINGÓW'

    close=float(a['Close'])
    prev_close=float(df.Close.iloc[-2])
    event='BRAK'
    if sh is not None and float(a['High'])>sh+eps and close<sh:
        event='SWEEP HIGH — hipoteza odrzucenia wybicia'
    elif sl is not None and float(a['Low'])<sl-eps and close>sl:
        event='SWEEP LOW — hipoteza odrzucenia wybicia'
    elif sh is not None and prev_close<=sh and close>sh+eps:
        event='BOS UP — wybicie poprzedniego swingu'
    elif sl is not None and prev_close>=sl and close<sl-eps:
        event='BOS DOWN — wybicie poprzedniego swingu'

    changes=df.Close.tail(26).diff().abs().dropna()
    direction=abs(float(df.Close.iloc[-1]-df.Close.iloc[-26]))
    traveled=float(changes.sum())
    efficiency=max(0.0,min(1.0,direction/traveled)) if traveled>0 else 0.0
    atr_history=df.ATR.dropna().tail(50)
    median_atr=float(atr_history.median()) if not atr_history.empty else atr
    volatility_ratio=atr/median_atr if median_atr>0 else 1.0

    if volatility_ratio >= 1.65:
        regime='EKSPANSJA ZMIENNOŚCI'
    elif volatility_ratio <= 0.58:
        regime='KOMPRESJA ZMIENNOŚCI'
    elif structure=='HH/HL' and efficiency>=0.33:
        regime='TREND WZROSTOWY'
    elif structure=='LH/LL' and efficiency>=0.33:
        regime='TREND SPADKOWY'
    elif efficiency<=0.17:
        regime='KONSOLIDACJA / MAŁA EFEKTYWNOŚĆ'
    else:
        regime='MIESZANY / PRZEJŚCIOWY'

    explanation=(
        f'Struktura: {structure}. Reżim: {regime}. '
        f'Bieżące zdarzenie: {event}. '
        'Poziomy to potwierdzone swingi, nie wykryte zlecenia. '
        'Moduł nie tworzy samodzielnych sygnałów ani prawdopodobieństw.')
    return MarketDNA(structure,regime,event,close,sh,sl,
                     round(atr,3),round(efficiency,3),
                     round(volatility_ratio,3),explanation)
