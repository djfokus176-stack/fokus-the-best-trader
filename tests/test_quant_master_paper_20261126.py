"""Quant Master 26.11.2026: no hindsight, no auto-trading, no double fee.

Tests use invented synthetic PAPER rows, not broker or research returns.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import math

from trader.quant_master_paper import (
    paper_ev_metrics, quant_master_report, verified_auto_closed,
)


def trade(i, pnl, *, side="LONG", date=None, strategy="EMA TREND",
          status=None, auto=True, spread=.6, slip=.2, policy="fixed"):
    if date is None:
        date=datetime(2026,11,1,tzinfo=timezone.utc)+timedelta(days=i)
    open_time=date.replace(hour=14,minute=0,second=0)
    close_time=open_time+timedelta(minutes=20)
    return {
        "trade_id":f"synthetic-{i}", "source":"Capital.com DEMO REST",
        "epic":"US500", "side":side, "strategy":strategy,
        "status":status or ("CLOSED_TP" if pnl>0 else "CLOSED_SL"),
        "setup_reason":("AUTO PAPER (eksperyment 1 sygnału): syntetyczny"
                        if auto else "Ręczna hipoteza, nie AUTO"),
        "opened_utc":open_time.isoformat(),
        "closed_utc":close_time.isoformat(),
        "entry_mid":7000.0, "exit_mid":7010.0,
        "pnl_pts":pnl, "setup_spread":spread,
        "slippage":slip, "exit_policy":policy,
    }


def test_net_expectancy_is_not_charged_the_spread_twice():
    rows=[trade(0,4),trade(1,-8,side="SHORT")]
    report=quant_master_report(rows)
    overall=report["overall"]
    assert overall["n"]==2
    assert overall["sessions"]==2
    assert overall["mean_net_pts"]==-2.0  # 4 - 8 over 2
    assert overall["sum_net_pts"]==-4.0
    assert overall["win_rate_pct"]==50.0
    assert overall["net_breakeven_winrate_pct"]==66.67
    assert overall["stress_1_5_net_pts"]==-2.5  # additional .5*1.0
    assert overall["stress_2_net_pts"]==-3.0
    assert overall["status"]=="INSUFFICIENT_DATA"
    assert overall["ci95_mean_net_pts"] is None
    assert report["per_side"]["LONG"]["sum_net_pts"]==4
    assert report["per_side"]["SHORT"]["sum_net_pts"]==-8


def test_never_count_manual_raw_wait_open_pending_or_duplicate():
    valid=trade(0,2)
    rows=[
        valid,valid.copy(),trade(1,50,auto=False),
        trade(2,100,status="OPEN"),trade(3,100,status="PENDING"),
        trade(4,100,status="INVALIDATED"),trade(5,100,side="SHORT",auto=False),
    ]
    results,diag=verified_auto_closed(rows)
    assert len(results)==1 and results[0]["pnl"]==2.0
    assert diag["duplicates"]==1
    assert diag["not_auto"]==2
    assert diag["closed"]==1


def test_fail_closed_invalid_missing_prices_and_bad_cost_proxy():
    invalid=[
        {**trade(0,5),"closed_utc":None},
        {**trade(1,5),"pnl_pts":float("nan")},
        {**trade(2,5),"entry_mid":float("inf")},
        {**trade(3,5),"opened_utc":"2026-11-25T10:00:00"},
        {**trade(4,5),"trade_id":""},
    ]
    result,diag=verified_auto_closed(invalid)
    assert result==[]
    assert diag["excluded"]==5
    valid=trade(6,2,spread=None)
    rows,_=verified_auto_closed([valid])
    m=paper_ev_metrics(rows)
    assert m["mean_net_pts"]==2
    assert m["stress_1_5_net_pts"] is None
    assert m["stress_2_net_pts"] is None


def test_session_bootstrap_is_repeatable_and_never_mislabels_confidence():
    dataset=[trade(i,1 if i%3 else -2,side="LONG" if i%2 else "SHORT")
             for i in range(40)]
    one=quant_master_report(dataset)
    two=quant_master_report(list(reversed(dataset)))
    assert one["overall"]==two["overall"]
    assert one["overall"]["sessions"]==40
    assert one["overall"]["n"]==40
    assert one["overall"]["status"]=="RESEARCH_ONLY"
    assert one["overall"]["ci95_mean_net_pts"]==two["overall"]["ci95_mean_net_pts"]
    assert one["overall"]["ci95_mean_net_pts"] is not None
    assert one["last_sessions"][20]["sessions"]==20
    assert one["last_sessions"][60]["n"]==40
    assert one["last_sessions"][120]["n"]==40
    assert one["calibrated_p_long_short"].startswith("NOT_AVAILABLE")
    assert one["challenger"].startswith("NOT_STARTED")
    assert one["automatic_strategy_changes"] is False


def test_same_day_cluster_does_not_claim_many_independent_sessions():
    date=datetime(2026,11,25,tzinfo=timezone.utc)
    rows=[trade(i,1 if i%2 else -1,date=date) for i in range(100)]
    report=quant_master_report(rows)
    assert report["overall"]["n"]==100
    assert report["overall"]["sessions"]==1
    assert report["overall"]["status"]=="INSUFFICIENT_DATA"
    assert report["overall"]["ci95_mean_net_pts"] is None


def test_quant_report_does_not_modify_worker_live_trade_or_chart():
    for module in ("trader/quant_master_paper.py","trader/quant_master_ui.py"):
        text=Path(module).read_text(encoding="utf8")
        assert all(f not in text for f in (
            "queue_paper(", "progress_paper(", "remote.save(",
            "CapitalReadOnly(", "session.post(", "FOKUS_DEMO_BROKER_MODE"))
    app=Path("app.py").read_text(encoding="utf8")
    assert "render_quant_master_research(paper_db, epic=instrument)" in app
    assert "render_cloud_terminal(secret,tf)" in app


def test_differing_exit_policies_are_not_mixed():
    rows=[trade(1,2,policy="fixed"),
          trade(2,-3,policy="adaptive",side="SHORT"),
          trade(3,-5,policy="fixed",side="LONG")]
    report=quant_master_report(rows)
    keys={(x["strategy"],x["policy"],x["side"])
          for x in report["per_strategy"]}
    assert keys=={("EMA TREND","fixed","LONG"),
                  ("EMA TREND","adaptive","SHORT")}
    assert math.isclose(report["overall"]["mean_net_pts"],-2)
