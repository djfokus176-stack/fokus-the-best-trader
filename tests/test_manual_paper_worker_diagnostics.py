"""Owner manual trial diagnostic, no fake fills on dead or stale worker."""
from datetime import timedelta
from pathlib import Path
import pandas as pd
import pytest

from trader.manual_paper_test import (
    blank,note_worker_cycle,expire_request_only,manual_report,
)
from trader.manual_paper_status_ui import _time,_local,_status,_explain

NOW=pd.Timestamp("2026-11-18T13:45:00Z")


def armed():
    state=blank()
    state["request"]={
        "id":"test-1","side":"LONG","status":"QUEUED",
        "requested_utc":(NOW-pd.Timedelta(seconds=15)).isoformat(),
        "waiting_reason":"WAIT_NEXT_VERIFIED_M1",
    }
    state["last_reason"]="QUEUED_LONG"
    state["requested_count"]=1
    return state


@pytest.mark.parametrize(("worker_msg","reason"),[
    ("WAIT / DATA_STALE / BROKER_STATUS=TRADEABLE","WORKER_DATA_STALE"),
    ("WAIT / NO_FEED / BROKER_STATUS=TRADEABLE","WORKER_NO_M1_FEED"),
    ("WAIT / MARKET_CLOSED / BROKER_STATUS=CLOSED","WORKER_MARKET_CLOSED"),
    ("WAIT / PAPER v3 is DEMO-only","WORKER_NOT_DEMO"),
])
def test_worker_early_return_does_not_silently_leave_queued(worker_msg,reason):
    original=armed()
    after=note_worker_cycle(original,worker_msg,now=NOW)
    assert original["last_reason"]=="QUEUED_LONG"
    assert after["last_reason"]==reason
    assert after["request"]["status"]=="WAIT_DATA"
    assert after["active"] is None
    assert after["opened"]==0
    assert after["closed"]==[]
    assert after["last_worker_attempt_utc"]==NOW.isoformat()
    assert manual_report(after)["last_worker_diagnosis"]==reason
    assert manual_report(after)["last_worker_attempt_utc"]==NOW.isoformat()


def test_worker_alive_with_same_candle_still_diagnosed_no_new_m1():
    before=armed()
    result=note_worker_cycle(before,
        "2026-11-18T13:43:00Z / WAIT / QUEUE=NO / "
        "ACTIVE=NONE / GATES=OK",now=NOW)
    assert result["last_worker_diagnosis"]=="WORKER_SCAN_DONE"
    assert result["last_reason"]=="WAIT_WORKER_NO_NEW_M1"
    assert result["request"]["status"]=="WAIT_DATA"
    assert result["opened"]==0


def test_actual_pending_or_open_not_overridden_by_worker_heartbeat():
    state=armed()
    state["request"]["status"]="ACCEPTED"
    state["active"]={
        "status":"PENDING","side":"LONG",
        "setup_utc":"2026-11-18T13:43:00+00:00",
    }
    state["last_reason"]="PENDING_NEXT_VERIFIED_M1"
    actual=note_worker_cycle(state,"WAIT / NO_FEED",now=NOW)
    assert actual["active"]["status"]=="PENDING"
    assert actual["last_reason"]=="PENDING_NEXT_VERIFIED_M1"
    assert actual["last_worker_diagnosis"]=="WORKER_NO_M1_FEED"


def test_request_expires_without_changing_existing_auto_positions():
    state=armed()
    expired=expire_request_only(state,now=NOW+pd.Timedelta(minutes=16))
    assert expired["request"]["status"]=="EXPIRED"
    assert expired["opened"]==0 and expired["closed_total"]==0


def test_polish_ui_distinguishes_waiting_from_real_open():
    state=armed()
    report=manual_report(state)
    assert _status(report)==("QUEUED","LONG")
    assert "STALE" in _explain("WORKER_DATA_STALE") or "STARE" in _explain("WORKER_DATA_STALE")
    assert "kolejna" in _explain("WAIT_NEXT_M1_AFTER_CLICK")
    assert _local(_time("2026-11-18T13:40:00Z"))=="18.11.2026 14:40:00"
    assert _time("bogus") is None


def test_owner_widget_refresh_does_not_send_broker_order_or_write_supabase():
    widget=Path("trader/manual_paper_status_ui.py").read_text("utf8")
    cloud=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    worker=Path("trader/worker.py").read_text("utf8")
    assert '@st.fragment(run_every="12s")' in widget
    assert "remote.fetch()" in widget
    assert "remote.save(" not in widget
    assert "session.post(" not in widget
    assert "queue_paper(" not in widget
    assert 'st.rerun(scope="app")' in widget
    assert "manual_status_panel(remote)" in cloud
    assert "ODŚWIEŻ CAŁY WYKRES I STATUS TESTU" in cloud
    assert "manual_test_state=note_worker_cycle(" in worker
    assert "manual_paper_test_report" in worker
    assert "queue_manual_request(remote,clicked_side)" in cloud
    assert "annotate_manual_test(candles,manual_trial," in cloud
