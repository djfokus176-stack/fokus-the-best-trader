"""Safe market-data freshness and scan cadence. No broker orders."""
from __future__ import annotations
from datetime import datetime, timezone
from .market import PERIOD

ALLOWED_SOURCES = {'Capital.com DEMO REST', 'Capital.com LIVE REST'}

def scan_delay_seconds(seconds: int) -> int:
    """UI refresh interval; avoid requesting data every few seconds."""
    try:
        val = int(seconds)
    except (TypeError, ValueError):
        raise ValueError('Niepoprawny interwał odświeżania.')
    if val not in (5, 15, 30, 60, 120, 300):
        raise ValueError('Dozwolone odświeżanie: 5, 15, 30, 60, 120 lub 300 sekund.')
    return val

def current_feed_status(snap, source: str, now: datetime | None = None) -> tuple[bool, str, float | None]:
    """A snapshot that was valid when fetched is not necessarily valid now."""
    if snap is None:
        return False, 'BRAK_DANYCH', None
    if source not in ALLOWED_SOURCES:
        return False, 'Źródło historyczne / CSV: brak autoryzowanego sygnału.', None
    if snap.confirmed_utc is None or snap.resolution not in PERIOD:
        return False, 'Nieznany czas zamknięcia świecy.', None
    if not snap.good:
        return False, snap.reason, snap.age_seconds
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or snap.confirmed_utc.tzinfo is None:
        return False, 'Brak strefy czasowej.', None
    age = (now - snap.confirmed_utc).total_seconds()
    allowed = 3 * PERIOD[snap.resolution] + 60
    if age < -PERIOD[snap.resolution]:
        return False, 'Świeca z przyszłości / błąd zegara.', age
    if age > allowed:
        return False, f'WYGASŁY ODCZYT: {age:.0f} s od zamknięcia świecy (limit {allowed} s).', age
    return True, 'OK — dane nadal mieszczą się w limicie świeżości.', age
