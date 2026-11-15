"""Pure diagnostics of cloud research freshness; NOT a trading green light.

No credentials, network access, order routing, strategy updates or DB writes.
A checkpoint timestamp is evidence of a persisted write, not proof that
broker quotes and all expected candles are present.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
HEARTBEAT_WARN_MIN = 10
HEARTBEAT_OLD_MIN = 30
WAVE_DELAY_WARN_MIN = 45


def _utc(value):
    """Parse an aware datetime, or return None for missing/unusable timestamp."""
    if not value:
        return None
    try:
        dt = (value if isinstance(value, datetime) else
              datetime.fromisoformat(str(value).replace("Z", "+00:00")))
        if not isinstance(dt, datetime) or dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _elapsed(now, timestamp):
    if timestamp is None:
        return None
    return round((now - timestamp).total_seconds() / 60.0, 1)


def assess_research_readiness(meta, wave_state, backfill_state, *, now=None):
    """Return advisory diagnostics, deliberately never approval to trade.

    The WAVE research engine uses the NY cash session; other US500 CFD
    hours differ. Outside that session no new WAVE candle is *required*,
    but this never proves the broker itself is closed.
    """
    meta = meta if isinstance(meta, dict) else {}
    wave_state = wave_state if isinstance(wave_state, dict) else {}
    backfill_state = backfill_state if isinstance(backfill_state, dict) else {}
    current = _utc(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError("WAVE QA requires a timezone-aware observation time.")
    scan = _utc(meta.get("last_scan_utc"))
    scan_age = _elapsed(current, scan)
    if scan_age is None:
        checkpoint = "BRAK POTWIERDZONEGO CHECKPOINTU"
    elif scan_age < -2:
        checkpoint = "NIEZGODNOSC ZEGAROW"
    elif scan_age <= HEARTBEAT_WARN_MIN:
        checkpoint = "SWIEZY CHECKPOINT"
    elif scan_age <= HEARTBEAT_OLD_MIN:
        checkpoint = "OPÓŹNIONY CHECKPOINT"
    else:
        checkpoint = "STARY CHECKPOINT — SPRAWDZ WORKER"
    # Wave observation freshness is meaningful in the same RTH window
    # used by the Wave pattern engine, not in all Capital.com hours.
    ny = current.astimezone(NY)
    minute_of_day = ny.hour * 60 + ny.minute
    during_wave_session = ny.weekday() < 5 and 9*60+45 <= minute_of_day <= 16*60
    wave_last = _utc(wave_state.get("last_closed_utc"))
    wave_age = _elapsed(current, wave_last)
    if wave_last is None:
        wave = "BRAK ZAPISANEJ M15"
    elif wave_age < -2:
        wave = "NIEZGODNOSC ZEGAROW M15"
    elif not during_wave_session:
        wave = "POZA SESJA NY DLA WAVE — KONTROLA WARUNKOWA"
    elif wave_age <= WAVE_DELAY_WARN_MIN:
        wave = "OSTATNIA M15 W ZAKRESIE KONTROLNYM"
    else:
        wave = "STARA M15 W SESJI NY — DO WERYFIKACJI"
    # bool strings must not be implicitly truthy (e.g. "false").
    enabled_raw = meta.get("candle_backfill_enabled", False)
    enabled = (enabled_raw is True or
               isinstance(enabled_raw, str) and enabled_raw.lower().strip()
               in ("true", "1", "yes", "on"))
    last_attempt = _utc(backfill_state.get("last_attempt_utc"))
    if not enabled:
        backfill = "WYLACZONY W CHECKPOINCIE"
    elif last_attempt is None:
        backfill = "WLACZONY — BRAK POTWIERDZONEJ PROBY"
    else:
        backfill = str(backfill_state.get("status") or "STATUS NIEZNANY")
    return {
        "checkpoint_status": checkpoint,
        "checkpoint_minutes": scan_age,
        "last_checkpoint_utc": scan.isoformat() if scan else None,
        "wave_status": wave,
        "wave_minutes": wave_age,
        "last_m15_utc": wave_last.isoformat() if wave_last else None,
        "wave_ny_session": bool(during_wave_session),
        "backfill_status": backfill,
        "backfill_enabled": bool(enabled),
        "backfill_attempt_utc": last_attempt.isoformat() if last_attempt else None,
        "quality_is_proven": False,
        "trade_permission": "WAIT",
    }
