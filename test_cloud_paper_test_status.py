"""No invented LONG/SHORT when the real worker has logged no TEST OPEN."""
from pathlib import Path
from trader.cloud_paper_test_status import status_for_owner

NOW="2026-11-17T21:20:00+00:00"
CANDLE="2026-11-17T21:19:00+00:00"


def report(started=0,opened=0,closed=0,reason="BRAK_MOMENTUM_MINIMUM_5_6",active=None,candle=CANDLE):
    return {"momentum_paper_test_report":{
        "status":"FORWARD_PAPER_TEST_NOT_LIVE",
        "started":started,"opened":opened,"closed":closed,
        "last_reason":reason,"last_candle_utc":candle,
        "active":active,
    }}


def test_missing_worker_report_is_not_a_fake_trade():
    result=status_for_owner({},now=NOW)
    assert result["kind"]=="NOT_STARTED"
    assert result["opened"] is None
    assert result["fresh"] is False


def test_zero_setup_is_explained_and_never_claims_open():
    result=status_for_owner(report(),now=NOW)
    assert result["kind"]=="NO_APPROVAL"
    assert result["opened"]==0
    assert "5/6" in result["detail"]
    assert result["fresh"]


def test_paper_pending_is_not_counted_as_open():
    pos={"side":"SHORT","status":"PENDING"}
    result=status_for_owner(report(1,0,0,active=pos),now=NOW)
    assert result["kind"]=="PENDING"
    assert result["opened"]==0
    assert "SHORT" in result["title"]


def test_real_simulated_open_is_highlighted():
    pos={"side":"LONG","status":"OPEN"}
    result=status_for_owner(report(1,1,0,active=pos),now=NOW)
    assert result["kind"]=="OPEN"
    assert result["opened"]==1


def test_completed_trade_is_history_not_current_open():
    result=status_for_owner(report(2,2,2),now=NOW)
    assert result["kind"]=="HISTORY" and result["opened"]==2


def test_stale_candle_is_not_live_trade_even_when_checkpoint_has_open():
    old="2026-11-17T20:00:00+00:00"
    result=status_for_owner(report(1,1,0,
        active={"status":"OPEN","side":"SHORT"},candle=old),now=NOW)
    assert result["kind"]=="STALE"
    assert result["fresh"] is False
    assert result["opened"]==1


def test_global_blocker_exposes_real_reason_not_random_advice():
    result=status_for_owner(
        report(reason="GLOBAL_GATES_INCOMPLETE_MTF,DATA_STALE"),now=NOW)
    assert result["kind"]=="NO_APPROVAL"
    assert "INCOMPLETE_MTF" in result["detail"]
    assert "DATA_STALE" in result["detail"]


def test_bad_counters_cannot_masquerade_as_valid_paper():
    for p in (report(0,1,0),report(1,0,1),report(-1,0,0)):
        result=status_for_owner(p,now=NOW)
        assert result["kind"]=="NOT_STARTED"


def test_ui_reads_same_checkpoint_and_does_not_create_orders():
    src=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf8")
    module=Path("trader/cloud_paper_test_status.py").read_text(encoding="utf8")
    assert "owner_test=status_for_owner(payload)" in src
    assert "AUTOMATYCZNY PAPER TEST — CZY BOT COŚ OTWORZYŁ?" in src
    assert "queue_paper(" not in module
    assert "CapitalReadOnly(" not in module
    assert "POST /positions" not in module
