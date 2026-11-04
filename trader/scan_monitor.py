"""Scan diagnostics for Streamlit; no credentials or requests recorded.
Data freshness and scanner activity are distinct concepts.
"""
from __future__ import annotations
from datetime import datetime, timezone


def scan_event(kind: str, previous, current=None, error: str = "",
               market_status: str | None = None, requested_utc=None) -> dict:
    """Describe one attempt. A successful HTTP request need not return a new bar."""
    timestamp = requested_utc or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError('Datetime must be aware.')
    result = 'ERROR' if error else 'NO_NEW_BAR'
    current_time = getattr(current, 'confirmed_utc', None)
    previous_time = getattr(previous, 'confirmed_utc', None)
    if current is not None:
        if previous_time is None:
            result = 'INITIAL_DATA'
        elif current_time is not None and current_time > previous_time:
            result = 'NEW_BAR'
        elif current_time is not None and current_time < previous_time:
            result = 'OLDER_THAN_PREVIOUS'
        if not getattr(current, 'good', False):
            result = 'STALE_OR_BLOCKED' if result != 'ERROR' else result
    return {
        'utc': timestamp.isoformat(timespec='seconds'),
        'trigger': str(kind),
        'api_result': 'ERROR' if error else ('OK' if current is not None else 'NO_DATA'),
        'bar_result': result,
        'last_bar_utc': current_time.isoformat() if current_time else None,
        'new_candle': bool(current_time is not None and (
            previous_time is None or current_time > previous_time)),
        'market_status': market_status or 'UNKNOWN',
        'error': str(error)[:160] if error else '',
    }


def append_scan_log(history, event: dict, limit: int = 30) -> list[dict]:
    """Session-only last N attempts, not an external always-on log."""
    return (list(history or []) + [dict(event)])[-max(1,int(limit)):]
