"""Date-scoped, deduplicated audits without hindsight or invented gains."""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

import pytest

from trader.periodic_archive_audit import (
    LANES,advance_periodic_archive,automatic_audit_report,
    period_comparison,archive_day_trades,_at_midnight,empty,
    MAX_ROWS,SCHEMA,
)


NOW=datetime(2026,11,18,12,0,tzinfo=timezone.utc)


def trade(key="a", *, status="CLOSED_TP",
          setup="2026-11-17T11:30:00+00:00",
          opened="2026-11-17T11:31:00+00:00",
          closed="2026-11-17T12:10:00+00:00", pnl=4.0,side="LONG"):
    return {"trade_id":key,"epic":"US500","source":"Capital.com DEMO REST",
            "status":status,"side":side,
            "setup_utc":setup,"opened_utc":opened,
            "closed_utc":closed,"pnl_pts":pnl,
            "strategy":"EMA TREND"}


def payload(*v3,raw=None,momentum=None):
    return {"tables":{"paper_positions_v3":list(v3)},
            "momentum_paper_test":{"closed":momentum or []},
            "raw_m1_forward_paper":{"closed":raw or []}}


def closed_from(t,side="LONG",pnl=1.2):
    return {"setup_utc":t["setup_utc"],"opened_utc":t["opened_utc"],
            "closed_utc":t["closed_utc"],"pnl_pts":pnl,
            "status":t["status"],"side":side,
            "methods":["EMA TREND"]}


def test_archives_three_lanes_separately_and_is_idempotent():
    a=trade()
    p=payload(a,raw=[closed_from(a,pnl=-3.5)],
              momentum=[closed_from(a,pnl=1.5)])
    archive=advance_periodic_archive({},p,now=NOW)
    assert len(archive["trades"])==3
    assert set(row["l"] for row in archive["trades"].values())==set(LANES)
    twice=advance_periodic_archive(archive,p,now=NOW+timedelta(minutes=1))
    assert len(twice["trades"])==3
    assert twice["seen_scans"]==2
    date_current=date(2026,11,17)
    v3=period_comparison(twice,"PAPER v3","day",
                          reference=date_current,now=NOW)
    raw=period_comparison(twice,"RAW M1 TEST","day",
                           reference=date_current,now=NOW)
    momentum=period_comparison(twice,"MOMENTUM TEST","day",
                                reference=date_current,now=NOW)
    assert v3["current"]["net_pts"]==4
    assert raw["current"]["net_pts"]==-3.5
    assert momentum["current"]["net_pts"]==1.5
    assert v3["current"]["long"]==1
    assert v3["current"]["tp"]==1


def test_pending_open_invalidated_stale_live_malformed_never_count():
    pending=trade(status="PENDING")
    open_=trade(key="open",status="OPEN")
    invalid=trade(key="inv",status="INVALIDATED")
    live=trade(key="live")
    live["source"]="Capital.com LIVE REST"
    future=trade(key="future",closed="2026-12-17T10:00:00+00:00")
    no_open=trade(key="missing")
    no_open["opened_utc"]=None
    invalid_pnl=trade(key="nan",pnl=float("nan"))
    order_invalid=trade(key="order",opened="2026-11-18T14:00:00+00:00")
    output=advance_periodic_archive({},payload(
        pending,open_,invalid,live,future,no_open,invalid_pnl,order_invalid
    ),now=NOW)
    assert output["trades"]=={}


def test_day_uses_polish_local_close_date_not_utc_or_setup_date():
    t=trade(closed="2026-11-17T23:30:00+00:00",
            setup="2026-11-17T22:50:00+00:00",
            opened="2026-11-17T23:00:00+00:00")
    now=datetime(2026,11,18,1,tzinfo=timezone.utc)
    archive=advance_periodic_archive({},payload(t),now=now)
    assert period_comparison(archive,"PAPER v3","day",
                             reference=date(2026,11,17),now=now)["current"]["closed"]==0
    assert period_comparison(archive,"PAPER v3","day",
                             reference=date(2026,11,18),now=now)["current"]["closed"]==1
    rows=archive_day_trades(archive,date(2026,11,18))
    assert len(rows)==1
    assert rows[0]["CLOSE (Polska)"]=="18.11 00:30"


def test_week_is_monday_first_and_iso_year_boundary():
    tm=trade(closed="2026-12-31T13:00:00+00:00",
             opened="2026-12-31T12:00:00+00:00",
             setup="2026-12-31T11:59:00+00:00")
    current=datetime(2027,1,2,13,tzinfo=timezone.utc)
    archive=advance_periodic_archive({},payload(tm),now=current)
    comp=period_comparison(archive,"PAPER v3","week",now=current)
    assert comp["period"]=="2026-12-28"
    assert comp["current"]["closed"]==1
    assert comp["current_partial"]


def test_previous_period_unobserved_never_assumed_zero():
    a=advance_periodic_archive({},payload(trade()),now=NOW)
    c=period_comparison(a,"PAPER v3","day",now=NOW)
    assert c["comparison_ready"] is False
    assert c["delta_net_pts"] is None
    assert c["current"]["closed"]==0
    assert c["previous_full"]["closed"]==1


def test_matches_elapsed_time_not_full_previous_day():
    a=trade(key="early",setup="2026-11-17T08:58:00+00:00",
            opened="2026-11-17T09:00:00+00:00",
            closed="2026-11-17T09:10:00+00:00",pnl=3)
    b=trade(key="late",setup="2026-11-17T19:58:00+00:00",
            opened="2026-11-17T20:00:00+00:00",
            closed="2026-11-17T20:10:00+00:00",pnl=-6)
    c=trade(key="today",setup="2026-11-18T08:58:00+00:00",
            opened="2026-11-18T09:00:00+00:00",
            closed="2026-11-18T09:10:00+00:00",pnl=5)
    archive=advance_periodic_archive({},payload(a,b,c),now=NOW)
    # Synthetic verified coverage before previous day, so delta meaningful.
    archive["first_collected_utc"]="2026-11-16T22:00:00+00:00"
    comp=period_comparison(archive,"PAPER v3","day",now=NOW)
    # At 12:00 UTC Nov18 (13:00 Poland), comparison with yesterday up
    # through 13:00 local: only +3, not the late -6 after 21:00.
    assert comp["current"]["net_pts"]==5
    assert comp["previous_matched"]["net_pts"]==3
    assert comp["previous_full"]["net_pts"]==-3
    assert comp["delta_net_pts"]==2
    assert comp["comparison_ready"]
    assert comp["matching"]=="SAME_ELAPSED_UTC_DURATION"


def test_non_current_selected_day_uses_full_prior_day():
    a=trade(key="a",pnl=2)
    b=trade(key="b",setup="2026-11-16T10:00:00+00:00",
            opened="2026-11-16T10:01:00+00:00",
            closed="2026-11-16T10:20:00+00:00",pnl=-3)
    archive=advance_periodic_archive({},payload(a,b),now=NOW)
    archive["first_collected_utc"]="2026-11-14T00:00:00+00:00"
    cmp=period_comparison(archive,"PAPER v3","day",
                          reference=date(2026,11,17),now=NOW)
    assert cmp["comparison_ready"]
    assert cmp["current_partial"] is False
    assert cmp["previous_matched"]["net_pts"]==-3
    assert cmp["delta_net_pts"]==5
    assert cmp["matching"]=="FULL_PREVIOUS_PERIOD"


def test_months_correct_length_and_dst_day_boundaries():
    # Oct 25, 2026 had Warsaw clock rollback: 25-hour local day.
    oct25=_at_midnight(date(2026,10,25))
    oct26=_at_midnight(date(2026,10,26))
    assert (oct26-oct25).total_seconds()==25*3600
    # Previous month can have fewer days; equal elapsed comparison is capped.
    at=datetime(2027,3,31,22,0,tzinfo=timezone.utc)
    archive=advance_periodic_archive({},payload(),now=at)
    archive["first_collected_utc"]="2027-01-01T00:00:00+00:00"
    cmp=period_comparison(archive,"PAPER v3","month",now=at)
    assert cmp["period"]=="2027-04-01"  # Warsaw midnight March 31 22 UTC
    assert cmp["current_partial"]


def test_win_loss_pf_drawdown_and_methods_net_after_costs():
    a=trade(key="one",pnl=10)
    b=trade(key="two",pnl=-6,side="SHORT",
            setup="2026-11-17T12:10:00+00:00",
            opened="2026-11-17T12:11:00+00:00",
            closed="2026-11-17T12:30:00+00:00",status="CLOSED_SL")
    archive=advance_periodic_archive({},payload(a,b),now=NOW)
    cmp=period_comparison(archive,"PAPER v3","day",
                          reference=date(2026,11,17),now=NOW)
    m=cmp["current"]
    assert m["closed"]==2 and m["wins"]==1 and m["win_rate_pct"]==50
    assert m["net_pts"]==4
    assert m["profit_factor"]==round(10/6,3)
    assert m["max_drawdown_pts"]==6
    assert m["max_losing_streak"]==1
    assert m["sl"]==1 and m["tp"]==1
    assert m["long"]==1 and m["short"]==1
    assert m["methods"]["EMA TREND"]["net_pts"]==4


def test_stable_archive_limits_and_retention_prevent_reimporting_pruned_history():
    a=trade(key="old",setup="2025-01-01T01:00:00+00:00",
            opened="2025-01-01T01:01:00+00:00",
            closed="2025-01-01T01:30:00+00:00")
    b=trade(key="new")
    first=advance_periodic_archive({},payload(a,b),now=NOW)
    assert len(first["trades"])==1
    assert first["removed_count"]>=1
    same=advance_periodic_archive(first,payload(a,b),now=NOW)
    assert len(same["trades"])==1
    assert same["removed_count"]==first["removed_count"]
    assert same["seen_scans"]==2


def test_bounded_number_of_persisted_unique_trade_rows():
    many=[]
    start=datetime(2026,11,9,0,0,tzinfo=timezone.utc)
    for i in range(MAX_ROWS+20):
        moment=start+timedelta(minutes=i)
        many.append(trade(
            key=f"test-{i}",
            setup=(moment-timedelta(minutes=3)).isoformat(),
            opened=(moment-timedelta(minutes=1)).isoformat(),
            closed=moment.isoformat(),pnl=.2))
    archive=advance_periodic_archive({},payload(*many),now=NOW)
    assert len(archive["trades"])==MAX_ROWS
    assert archive["removed_count"]==20
    second=advance_periodic_archive(archive,payload(*many),now=NOW)
    assert len(second["trades"])==MAX_ROWS
    assert second["removed_count"]==20


def test_worker_and_ui_both_use_same_archive_without_extra_db_or_broker_orders():
    worker=Path("trader/worker.py").read_text("utf8")
    terminal=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    engine=Path("trader/periodic_archive_audit.py").read_text("utf8")
    ui=Path("trader/periodic_archive_ui.py").read_text("utf8")
    assert 'payload["periodic_audit_archive"]' in worker
    assert 'payload["periodic_audit_report"]' in worker
    assert "render_periodic_archive_ui(payload)" in terminal
    assert "FOKUS_AUDYT_" in ui and "date_input(" in ui
    assert "queue_paper(" not in engine and "session.post(" not in engine
    assert "CapitalReadOnly(" not in engine
    assert "CREATE TABLE" not in engine
    assert "ARCHIVE_AUDIT_PAPER_ONLY" in engine
