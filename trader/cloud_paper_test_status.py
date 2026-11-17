"""Owner-visible health of the *independent* momentum PAPER TEST.

Read-only. Never converts OBSERWUJ into OPEN and never calls the broker.
"""
from __future__ import annotations

from datetime import datetime, timezone

KNOWN = {
    "BRAK_MOMENTUM_MINIMUM_5_6": "Momentum M1 za słabe (wymagane minimum 5/6).",
    "MOMENTUM_PRZECIW_EMA9_21": "Momentum przeciwne układowi EMA9/21.",
    "BRAK_ETAPOW_STRATEGII": "Brak zapisanych etapów strategii.",
    "BRAK_EMA_ETAPU_2_3_Z_TYM_KIERUNKIEM": "Brak zgodnego EMA TREND/PULLBACK na etapie 2/3.",
    "BRAK_MTF": "Brak potwierdzenia MTF.",
    "BRAK_ZWERYFIKOWANYCH_M5_M15": "Niekompletne potwierdzenia M5/M15.",
    "SPREAD_NIEDOSTEPNY": "Brak zweryfikowanego spreadu.",
    "SPREAD_ZBYT_DUZY_WOBEC_ATR": "Spread za wysoki wobec zmienności ATR.",
    "RYZYKO_NIEPROPORCJONALNE_DO_SPREAD_ATR": "Stop względem spreadu/ATR nie przeszedł kontroli.",
    "RR_PO_KOSZTACH_PONIZEJ_1_20": "Za mały potencjalny RR po kosztach.",
    "NIEWIARYGODNE_ZAMKNIETE_M1": "Brak dostatecznie spójnych, zamkniętych świec M1.",
    "LUKA_M1_POMIJAM_NOWE_WEJSCIE": "Wypadła co najmniej jedna świeca M1; nie odtwarzam hipotetycznego wejścia.",
    "NIEWAZNY_FILL_LUB_GEOMETRIA": "Planowana pozycja nie miała wiarygodnego wejścia i została unieważniona.",
    "TEST_WYLACZONY": "Eksperymentalny PAPER TEST wyłączono w ustawieniach workera.",
    "DZIENNY_LIMIT_TEST_8": "Osiągnięto limit ośmiu setupów testowych na dobę UTC.",
    "DZIENNY_STOP_TEST_15_PKT": "Osiągnięto dzienny stop strat w PAPER TEST.",
    "NIE URUCHOMIONO SKANU": "Worker nie wykonał jeszcze poprawnego skanu PAPER TEST.",
}
MAX_STALE_SECONDS = 180


def _utc(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    return stamp.astimezone(timezone.utc) if stamp.tzinfo else None


def status_for_owner(payload, *, now=None):
    """Summarise exactly what's in Supabase checkpoint. No invented trades."""
    defaults = {
        "kind": "NOT_STARTED",
        "title": "BRAK POTWIERDZONEGO STARTU PAPER TEST",
        "detail": "W checkpointcie nie ma raportu nowego PAPER TEST.",
        "started": None, "opened": None, "closed": None,
        "pending": False, "last_candle_utc": None, "last_reason": None,
        "fresh": False,
    }
    report = payload.get("momentum_paper_test_report") if isinstance(payload, dict) else None
    if not isinstance(report, dict) or report.get("status") != "FORWARD_PAPER_TEST_NOT_LIVE":
        return defaults

    try:
        started, opened, closed = (
            int(report[k]) for k in ("started", "opened", "closed")
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**defaults, "detail": "Raport PAPER TEST ma błędne liczniki."}
    if min(started, opened, closed) < 0 or opened > started or closed > opened:
        return {**defaults, "detail": "Raport PAPER TEST ma sprzeczne liczniki."}

    moment = _utc(now) if now is not None else datetime.now(timezone.utc)
    candle = _utc(report.get("last_candle_utc"))
    fresh = bool(moment is not None and candle is not None
                 and 0 <= (moment - candle).total_seconds() <= MAX_STALE_SECONDS)
    raw_reason = str(report.get("last_reason") or "BRAK")[:140]
    explanation = KNOWN.get(raw_reason)
    if explanation is None and raw_reason.startswith("GLOBAL_GATES_"):
        explanation = "Bramki workera blokują nowe wejście: " + raw_reason[13:110]
    elif explanation is None and raw_reason.startswith("M5_NIE_POTWIERDZA_"):
        explanation = "M5 nie potwierdza kierunku " + raw_reason[17:]
    elif explanation is None and raw_reason.startswith("M15_PRZECIWNY_"):
        explanation = "M15 pokazuje przeciwny trend niż " + raw_reason[15:]
    elif explanation is None:
        explanation = raw_reason
    position = report.get("active")
    active = position if isinstance(position, dict) else None
    pending = bool(active and active.get("status") == "PENDING")
    is_open = bool(active and active.get("status") == "OPEN")
    vals = {"started": started, "opened": opened, "closed": closed,
            "pending": pending,
            "last_candle_utc": candle.isoformat() if candle else None,
            "last_reason": raw_reason, "fresh": fresh}
    if not fresh:
        return {**defaults, **vals,
                "kind": "STALE",
                "title": "PAPER TEST — BRAK ŚWIEŻEGO SKANU",
                "detail": "Ostatnia analizowana zamknięta świeca jest starsza niż 3 min lub ma nieprawidłowy czas. " + explanation}
    if is_open:
        return {**defaults, **vals, "kind": "OPEN",
                "title": "TEST OPEN " + str(active.get("side","?")),
                "detail": "Aktywna, symulowana pozycja. " + explanation}
    if pending:
        return {**defaults, **vals, "kind": "PENDING",
                "title": "TEST PENDING " + str(active.get("side","?")),
                "detail": "Setup czeka na ocenę otwarcia kolejnej zamkniętej M1. " + explanation}
    if started == 0:
        return {**defaults, **vals, "kind": "NO_APPROVAL",
                "title": "PAPER TEST — 0 ZATWIERDZONYCH WEJŚĆ",
                "detail": explanation}
    return {**defaults, **vals, "kind": "HISTORY",
            "title": "PAPER TEST — MA ZAPISANE PRÓBY",
            "detail": explanation}
