"""Observable PAPER readiness report. Does not alter strategy/ledger/gates."""
from __future__ import annotations
from datetime import datetime,timezone
import re


def worker_age_seconds(meta, now=None):
    now=now or datetime.now(timezone.utc)
    try:
        stamp=(meta or {}).get("last_scan_utc")
        if not stamp:
            return None
        received=datetime.fromisoformat(str(stamp))
        if received.tzinfo is None:
            return None
        return (now-received).total_seconds()
    except (TypeError,ValueError,OverflowError):
        return None


def worker_calendar_health(meta, now=None):
    """Report the last worker checkpoint's macro gate, not browser RSS.

    Read-only advisory display. Never overrides worker gate evaluation.
    Refuse stale, absent, ambiguous, or expired checkpoint data.
    """
    check=now or datetime.now(timezone.utc)
    if check.tzinfo is None:
        raise ValueError("worker_calendar_health requires timezone-aware now")
    age=worker_age_seconds(meta,now=check)
    if age is None or not 0<=age<=15*60:
        return {"ok":False,"source":"BRAK","expires":None,
                "reason":"Brak świeżego checkpointu workera (maksymalnie 15 minut)."}
    summary=str((meta or {}).get("last_scan_summary") or "")
    if re.search(r"(?:^|[ /])NO_FEED(?:[ /]|$)",summary):
        # Feed retrieval stopped the worker BEFORE the BLS test. It is not
        # evidence that BLS failed, nor grounds to mark calendar safe.
        excerpt=summary.split("NO_FEED",1)[-1].strip(" /")[:190]
        return {"ok":False,"source":"NOT_CHECKED","expires":None,
                "reason":"Worker nie pobrał świec M1 (NO_FEED), więc NIE sprawdził BLS."+
                         (" Szczegóły: "+excerpt if excerpt else "")}
    if re.search(r"(?:^|[ /])DATA_STALE(?:[ /]|$)",summary):
        return {"ok":False,"source":"NOT_CHECKED","expires":None,
                "reason":"Dane workera były nieaktualne (DATA_STALE); skan zakończył się przed kontrolą BLS."}
    if re.search(r"(?:^|[ /])MARKET_CLOSED(?:[ /]|$)",summary):
        return {"ok":False,"source":"NOT_CHECKED","expires":None,
                "reason":"Rynek był zamknięty w ostatnim skanie workera; BLS nie został oceniony."}
    if not re.search(r"(?:^|[ /])GATES=OK(?:[ /]|$)",summary):
        return {"ok":False,"source":"BRAK","expires":None,
                "reason":"Ostatni skan workera nie potwierdza GATES=OK."}
    match=re.search(r"MACRO_SOURCE=(BLS_OFFICIAL_LIVE|BLS_VERIFIED_SNAPSHOT_NOT_LIVE)(?:[ /;]|$)",
                    summary)
    if not match:
        return {"ok":False,"source":"BRAK","expires":None,
                "reason":"Ostatni skan nie podaje zweryfikowanego źródła kalendarza."}
    source=match.group(1)
    if source=="BLS_OFFICIAL_LIVE":
        return {"ok":True,"source":source,"expires":None,
                "reason":"Oficjalny kalendarz był dostępny podczas ostatniego skanu workera."}
    expiry_match=re.search(r"EXPIRES_UTC=([^\s/;]+)",summary)
    if not expiry_match:
        return {"ok":False,"source":source,"expires":None,
                "reason":"Kopia BLS bez daty ważności nie może potwierdzić gotowości."}
    expiry_text=expiry_match.group(1)
    try:
        expires=datetime.fromisoformat(expiry_text)
    except (ValueError,TypeError):
        expires=None
    if expires is None or expires.tzinfo is None or check>=expires:
        return {"ok":False,"source":source,"expires":expiry_text,
                "reason":"Weryfikowana kopia kalendarza BLS wygasła albo ma błędną datę."}
    return {"ok":True,"source":source,"expires":expiry_text,
            "reason":"Zweryfikowana kopia BLS z ograniczoną ważnością (NIE LIVE)."}


def readiness_report(*, clock_verified, data_ready, market_status,
                     mtf_ready, calendar_current, remote_view,
                     worker_age=None, last_worker_summary="", ui_strategy="",
                     worker_strategy="", calendar_scope="local",
                     calendar_reason=None):
    """Display all blockers separately; WAIT can still be a valid strategy result.

    This status list is advisory UI only. It must NEVER be used to override
    existing worker-side macro, clock, MTF, source or spread validations.
    """
    clock=bool(clock_verified)
    market=market_status=="TRADEABLE"
    remote_ok=(worker_age is not None and 0<=worker_age<=15*60)
    checks=[
        ("Dane potwierdzonych świec",bool(data_ready),
         "Brak poprawnych, świeżych zamkniętych OHLC."),
        ("Capital.com TRADEABLE",market,
         "Status brokera: "+str(market_status)+"."),
        ("Zegar świec Capital",clock,
         "Czas API nadal NIEZWERYFIKOWANY. Porównaj oznaczenia "
         "dwóch kolejnych świec M1 z terminalem brokera przed "
         "ustawieniem FOKUS_CANDLE_TIME_CONFIRMED=open."),
        ("MTF M1/M5/M15/H1",bool(mtf_ready),
         "Brakuje kompletnych, zweryfikowanych interwałów MTF."),
        ("Kalendarz BLS (worker — ostatni skan)" if calendar_scope=="worker"
         else "Kalendarz BLS (sesja Streamlit)",bool(calendar_current),
         calendar_reason or "Brak świeżego oficjalnego kalendarza — nie oznacza braku publikacji."),
    ]
    if remote_view:
        checks.append(("Worker PAPER (zapis w bazie)",remote_ok,
                       ("Brak zapisanej aktywności lub ostatni skan starszy "
                        "niż 15 minut. GitHub Actions nie gwarantuje 24/7.")))
    blockers=[name+": "+reason for name,ok,reason in checks if not ok]
    if remote_view and worker_strategy and ui_strategy and worker_strategy!=ui_strategy:
        # Display, do not mark as a trading veto: UI dropdown doesn't change
        # the separate GitHub Actions worker's configured strategy.
        mismatch=("Strategia strony: "+ui_strategy+"; strategia workera: "+
                  worker_strategy+". Zmiana w Streamlit NIE przełącza workera.")
    else:
        mismatch=None
    # Historical worker flags explain the *last* run, not the current UI
    # readiness status. Counting them as extra current blockers falsely
    # claimed six separate faults when two were duplicates.
    summary=str(last_worker_summary or "")
    historical_flags=[]
    if remote_view and summary:
        historical_flags=[flag for flag in (
            "CANDLE_TIME_UNVERIFIED","DATA_STALE","INCOMPLETE_MTF",
            "MACRO_CALENDAR_UNAVAILABLE","SETUPS_DISABLED",
            "MARKET_NOT_TRADEABLE","NO_FEED")
            if flag in summary]
    return {
        "checks":[{"kontrola":name,"status":"✅ OK" if ok else "🔴 BLOKADA",
                   "powód":"" if ok else reason} for name,ok,reason in checks],
        "blockers":blockers,
        "historical_worker_flags":historical_flags,
        "worker_strategy_note":mismatch,
        "ready_to_consider_setup":not blockers and (not remote_view or remote_ok),
        "note":"Brak blokad technicznych NIE oznacza sygnału LONG/SHORT ani zysku. "
               "O wejściu PAPER decyduje zamknięta świeca, koszt i wynik strategii."
    }
