"""No secrets, prices or forged fills in public watchdog archive counters."""
from datetime import datetime, timezone
from pathlib import Path

from trader.worker_trade_audit import read_only_archive_counts, redacted_archive_log_line


SETUP="AUTO PAPER (eksperyment 1 sygnału): zatwierdzone: EMA TREND."
NOW=datetime(2026,11,20,12,30,tzinfo=timezone.utc)


def p(i,status,side="LONG",setup_reason=SETUP,
      opened="2026-11-20T10:01:00Z",closed=None,pnl=None):
    return {"trade_id":str(i),"epic":"US500","source":"Capital.com DEMO REST",
            "side":side,"strategy":"EMA TREND","setup_reason":setup_reason,
            "setup_utc":"2026-11-20T10:00:00Z",
            "status":status,"opened_utc":opened,
            "closed_utc":closed,"entry_mid":7400 if opened else None,
            "exit_mid":7410 if closed else None,"pnl_pts":pnl,
            "stop_mid":7390,"target_mid":7420}


def pkt(rows):
    return {"meta":{"epic":"US500","source":"Capital.com DEMO REST"},
            "tables":{"paper_positions_v3":rows},
            "momentum_paper_test_report":{"started":7,"opened":5,"closed":4},
            "raw_m1_forward_paper_report":{"started":3,"opened":2,"closed":1},
            "periodic_audit_report":{"status":"ARCHIVE_AUDIT_PAPER_ONLY",
                                     "stored_trades":7}}


def test_read_only_auto_archive_counts_and_daily_activity():
    rows=[
        p("open","OPEN","LONG"),
        p("tp","CLOSED_TP","SHORT",closed="2026-11-20T10:02:00Z",pnl=8),
        p("sl","CLOSED_SL","LONG",closed="2026-11-20T10:03:00Z",pnl=-5),
        p("timeout","CLOSED_TIMEOUT","SHORT",
          opened="2026-11-19T14:00:00Z",
          closed="2026-11-19T14:20:00Z",pnl=-2),
        p("pending","PENDING",opened=None),
        p("invalid","INVALIDATED",opened=None),
        p("manual","OPEN",setup_reason="RĘCZNE")
    ]
    data=read_only_archive_counts(pkt(rows),now=NOW)
    assert data["status"]=="VERIFIED_LEDGER"
    assert data["ledger_rows"]==7
    assert data["auto_opened"]==4 and data["auto_closed"]==3
    assert data["auto_long_opened"]==2 and data["auto_short_opened"]==2
    assert data["auto_opened_today_utc"]==3 and data["auto_closed_today_utc"]==2
    assert data["auto_closed_tp"]==1 and data["auto_closed_sl"]==1
    assert data["auto_closed_timeout"]==1
    assert data["auto_pending"]==1 and data["auto_invalidated"]==1
    assert data["auto_active"]==1
    assert data["last_auto_close_side"]=="LONG"
    assert data["last_auto_close_utc"]=="2026-11-20T10:03:00+00:00"
    assert data["periodic_archive_stored"]==7
    assert (data["momentum_started"],data["momentum_opened"],data["momentum_closed"])==(7,5,4)
    assert (data["raw_started"],data["raw_opened"],data["raw_closed"])==(3,2,1)


def test_no_pending_signal_or_duplicate_or_manual_trade_counts():
    rows=[p("pending","PENDING",opened=None),
          p("duplicate","CLOSED_TP",closed="2026-11-20T10:04:00Z",pnl=3),
          p("duplicate","CLOSED_TP",closed="2026-11-20T10:04:00Z",pnl=3),
          p("manual","OPEN",setup_reason="RĘCZNE")]
    d=read_only_archive_counts(pkt(rows),now=NOW)
    assert d["auto_opened"]==1 and d["auto_closed"]==1
    assert d["auto_long_opened"]==1
    assert d["auto_pending"]==1
    assert d["auto_incomplete"]==1


def test_no_ledger_cannot_be_reported_as_zero_confirmed_trades():
    assert read_only_archive_counts(None)["status"]=="NO_CHECKPOINT"
    assert read_only_archive_counts({"tables":{}})["status"]=="NO_LEDGER"
    result=read_only_archive_counts(pkt([]),now=NOW)
    assert result["status"]=="VERIFIED_LEDGER"
    assert result["auto_opened"]==0


def test_public_line_never_prints_prices_ids_profit_or_credentials():
    payload=pkt([p("secret_trade_id","CLOSED_TP",closed="2026-11-20T10:04:00Z",pnl=5)])
    payload["CAPITAL_PASSWORD"]="myprivatepassword"
    out=redacted_archive_log_line(payload,now=NOW)
    assert "FOKUS_ARCHIVE / STATUS=VERIFIED_LEDGER" in out
    assert "AUTO_OPENED=1" in out and "AUTO_CLOSED=1" in out
    assert "myprivatepassword" not in out and "secret_trade_id" not in out
    assert "7400" not in out and "7410" not in out
    assert "PAPER_ENTRIES_AUTHORIZED" not in out


def test_no_trade_or_broker_posts_in_watchdog_module():
    source=Path("trader/worker_trade_audit.py").read_text("utf-8")
    assert "session.post" not in source
    assert "remote.save(" not in source
    watchdog=Path("trader/worker_watchdog.py").read_text("utf-8")
    assert "redacted_archive_log_line(payload)" in watchdog
