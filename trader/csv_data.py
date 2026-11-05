"""Strict offline OHLC CSV loader used by PAPER replay, never a live feed."""
from __future__ import annotations
import pandas as pd


def read_ohlc_csv(file, default_spread=0.6):
    data=pd.read_csv(file)
    expected={'Time','Open','High','Low','Close'}
    if not expected.issubset(data.columns):
        raise ValueError('CSV wymaga kolumn Time,Open,High,Low,Close')
    times=pd.to_datetime(data.Time,utc=True,errors='raise')
    data=data.set_index(times).drop(columns=['Time']).sort_index()
    for c in ['Open','High','Low','Close']:
        data[c]=pd.to_numeric(data[c],errors='raise')
    if len(data)<72 or data.index.has_duplicates:
        raise ValueError('Wymagane >=72 świeczki bez duplikatów')
    if (data.High<data[['Open','Low','Close']].max(axis=1)).any() or (data.Low>data[['Open','High','Close']].min(axis=1)).any():
        raise ValueError('Niespójne OHLC')
    if 'Spread' in data:
        data['Spread']=pd.to_numeric(data['Spread'],errors='raise')
        if (data.Spread<0).any() or data.Spread.isna().any():
            raise ValueError('Ujemny lub pusty spread w CSV')
    else:
        if not (0<=default_spread<=20):
            raise ValueError('Niepoprawny spread zastępczy')
        data['Spread']=float(default_spread)
    return data
