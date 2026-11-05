"""Bounded Streamlit cache for CLOSED historic PAPER arrow detection.

Pandas input is hashed by Streamlit along with the source, instrument, TF,
strategy and chart window. A revised value at the same timestamp invalidates
the result: last timestamp ALONE is not a valid cache key.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
from . import visuals

@st.cache_data(show_spinner=False, ttl=1800, max_entries=40)
def cached_historical_marks(frame: pd.DataFrame, instrument: str,
                             timeframe: str, source: str, strategy: str,
                             visible_bars: int) -> pd.DataFrame:
    return visuals.historical_marks(frame,strategy,max_bars=visible_bars)
