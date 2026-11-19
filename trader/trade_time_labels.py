"""Human-readable time and entry provenance for archived virtual trades.

Never substitute setup_time for OPEN. Modelled bar OPEN, closed-bar
confirmation and worker-detection times are distinct; missing stays missing.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

WARSAW=ZoneInfo("Europe/Warsaw")


def aware(value):
    if isinstance(value,datetime):
        stamp=value
    elif isinstance(value,str):
        try:
            stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
        except (TypeError,ValueError,OverflowError):
            return None
    else:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp


def in_poland(value,*,seconds=False):
    stamp=aware(value)
    if stamp is None:
        return "BRAK ZAPISANEJ GODZINY"
    return stamp.astimezone(WARSAW).strftime(
        "%d.%m.%Y %H:%M:%S" if seconds else "%d.%m.%Y %H:%M")


def open_time_details(position):
    """Return provenance-backed model OPEN and detection timestamps."""
    if not isinstance(position,dict):
        return {"model_utc":None,"confirmed_utc":None,"detected_utc":None,
                "model_pl":"BRAK ZAPISANEJ GODZINY",
                "confirmed_pl":"BRAK ZAPISANEJ GODZINY",
                "detected_pl":"BRAK ZAPISANEJ GODZINY"}
    model=(position.get("entry_assumed_utc")
           or position.get("entry_bar_open_utc"))
    confirmed=position.get("opened_utc")
    detected=position.get("entry_detected_utc")
    return {
        "model_utc":model if aware(model) is not None else None,
        "confirmed_utc":confirmed if aware(confirmed) is not None else None,
        "detected_utc":detected if aware(detected) is not None else None,
        "model_pl":in_poland(model),
        "confirmed_pl":in_poland(confirmed),
        "detected_pl":in_poland(detected),
    }
