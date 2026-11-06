"""Separate current UI errors from historical worker flags; display MTF causes."""
from datetime import datetime,timezone
from pathlib import Path
from trader.paper_health import readiness_report

def test_historical_setups_and_macro_flags_are_not_two_extra_current_blockers():
    report=readiness_report(
        clock_verified=False,data_ready=True,market_status="TRADEABLE",
        mtf_ready=False,calendar_current=False,remote_view=True,worker_age=1200,
        last_worker_summary=("2026-11-06T11:30Z / WAIT / "
            "GATES=SETUPS_DISABLED,MACRO_CALENDAR_UNAVAILABLE / ..."),
        ui_strategy="AUTO — 6 STRATEGII",worker_strategy="AUTO — 6 STRATEGII")
    assert len(report["blockers"])==4  # clock, browser MTF, browser BLS, worker age
    assert len(report["historical_worker_flags"])==2
    assert "SETUPS_DISABLED" in report["historical_worker_flags"]
    assert "MACRO_CALENDAR_UNAVAILABLE" in report["historical_worker_flags"]
    assert all("Ostatni skan workera" not in x for x in report["blockers"])


def test_no_worker_history_is_not_invented():
    report=readiness_report(clock_verified=True,data_ready=True,
      market_status="TRADEABLE",mtf_ready=True,calendar_current=True,
      remote_view=False,last_worker_summary="GATES=SETUPS_DISABLED")
    assert report["ready_to_consider_setup"]
    assert not report["historical_worker_flags"]


def test_app_shows_per_timeframe_error_and_historical_status():
    code=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf8")
    assert "'Interwał':label" in code
    assert "mtf_errors=st.session_state.get('mtf_errors',{})" in code
    assert "not all(v.ready for v in tf_views)" in code
    assert "HISTORYCZNY" in code
    assert "DWA niezależne systemy" in code
