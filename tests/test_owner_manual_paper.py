"""Owner-button virtual long/short: no broker POST, real future closed M1.

Checks CAS, one-click intent, stale price fail closed, open/SL/TP/timeout,
restart idempotence, separate journal and visible chart markers.
"""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest

from trader.manual_paper_test import (
    blank, queue_manual_request, advance_manual_test, expire_request_only,
    manual_report, MAX_HOLD_M1,
)
from trader.manual_paper_chart import annotate_manual_test
from trader.paper_trade_trails import annotate_position_trails, recorded_positions
from trader.remote_checkpoint import RemoteConflict

BASE=pd.Timestamp("2026-11-18T11:00:00Z")
SOURCE="Capital.com DEMO REST"


def frame(n=95,side="LONG"):
    idx=pd.date_range(BASE,periods=n,freq="min")
    # Mild alternating price movement; valid OHLC with positive ATR.
    mid=[7360.+i*.04+(i%4-2)*.28 for i in range(n)]
    return pd.DataFrame({
        "Open":mid,
        "High":[p+1.8 for p in mid],
        "Low":[p-1.8 for p in mid],
        "Close":[p+.07 for p in mid],
        "Spread":[.6]*n},index=idx)


def stamp(n):
    return (BASE+pd.Timedelta(minutes=n)).isoformat()


def created(n):
    return (BASE+pd.Timedelta(minutes=n,seconds=12)).isoformat()


def future(state, n, *, blockers=(),market="TRADEABLE",spread=.6):
    c=frame(n)
    return advance_manual_test(
        state,c,blockers,spread=spread,source=SOURCE,epic="US500",
        market_status=market,now=c.index[-1]+pd.Timedelta(seconds=15))


class Remote:
    def __init__(self):
        self.version=100
        self.payload={
            "schema":1,"tables":{"paper_positions_v3":[{"trade_id":"legacy-auto","side":"LONG"}]},
            "meta":{"source":SOURCE,"epic":"US500",
                    "strategy":"AUTO — 6 STRATEGII","timeframe":"MINUTE",
                    "last_scan_utc":created(94)},
            "raw_m1_forward_paper":{"closed":["DO_NOT_CHANGE"]},
        }
        self.saves=0
        self.conflict_once=False
    def fetch(self):
        return self.version,copy.deepcopy(self.payload)
    def save(self,expected_version,payload):
        if self.conflict_once:
            self.conflict_once=False
            raise RemoteConflict("worker won")
        if expected_version!=self.version:
            raise RemoteConflict("CAS mismatch")
        self.saves+=1
        self.version+=1
        self.payload=copy.deepcopy(payload)
        return self.version


def clicked(side="LONG"):
    remote=Remote()
    result=queue_manual_request(remote,side,now=created(94))
    assert result["status"]=="QUEUED"
    assert remote.saves==1
    assert remote.payload["tables"]["paper_positions_v3"][0]["trade_id"]=="legacy-auto"
    assert remote.payload["raw_m1_forward_paper"]["closed"]==["DO_NOT_CHANGE"]
    return remote,remote.payload["manual_paper_test"]


def test_click_is_intent_not_fake_immediate_open():
    r,state=clicked()
    assert state["active"] is None
    assert state["request"]["side"]=="LONG"
    assert state["request"]["status"]=="QUEUED"
    report=manual_report(state)
    assert report["opened"]==0 and report["closed"]==0
    assert report["no_broker_orders"] is True
    assert recorded_positions({"manual_paper_test_report":report})==[]


def test_manual_long_opens_after_two_real_closed_bars_then_timeout():
    remote,state=clicked("LONG")
    # no retroactive fill on old (already closed when owner clicked)
    before=future(state,95)
    assert before["opened"]==0 and before["active"] is None
    assert "WAIT_NEXT" in before["last_reason"]
    setup=future(before,96)
    assert setup["active"]["status"]=="PENDING"
    assert setup["opened"]==0
    assert setup["active"]["side"]=="LONG"
    opened=future(setup,97)
    assert opened["opened"]==1
    assert opened["active"]["status"]=="OPEN"
    assert opened["active"]["entry_bar_open_utc"]==stamp(96)
    assert opened["active"]["opened_utc"]==stamp(96)
    # TIMEOUT after at most 5 consecutive correctly completed M1.
    result=opened
    for n in (98,99,100,101):
        if result["active"] is None:
            break
        result=future(result,n)
    assert result["active"] is None
    assert result["closed_total"]==1
    assert result["closed"][0]["status"] in (
        "CLOSED_TP","CLOSED_SL","CLOSED_TIMEOUT")
    assert result["closed"][0]["bars_held"]<=MAX_HOLD_M1
    assert result["closed"][0]["pnl_pts"] is not None
    assert manual_report(result)["closed"]==1
    assert manual_report(result)["opened"]==1
    # Replay/restart on same final timestamp won't generate another OPEN.
    idempotent=future(result,101)
    assert idempotent["closed_total"]==1
    assert idempotent["opened"]==1


def test_manual_short_is_independent_of_auto_and_model_stop_has_priority():
    _,state=clicked("SHORT")
    queued=future(state,96)
    pos=queued["active"]
    assert pos["side"]=="SHORT"
    assert pos["target"]<pos["entry_signal"]<pos["stop"]
    nxt=frame(97)
    nxt.iloc[-1,nxt.columns.get_loc("Open")]=pos["entry_signal"]
    nxt.iloc[-1,nxt.columns.get_loc("High")]=pos["stop"]+1.0
    nxt.iloc[-1,nxt.columns.get_loc("Low")]=pos["target"]-1.0
    nxt.iloc[-1,nxt.columns.get_loc("Close")]=pos["entry_signal"]
    out=advance_manual_test(queued,nxt,spread=.6,
                            now=nxt.index[-1]+pd.Timedelta(seconds=15))
    assert out["opened"]==1 and out["closed_total"]==1
    assert out["closed"][0]["status"]=="CLOSED_SL"
    assert out["closed"][0]["pnl_pts"]<0


@pytest.mark.parametrize("blocked",[
    ("DATA_STALE",),
    ("SETUPS_DISABLED",),
    ("MARKET_NOT_TRADEABLE",),
])
def test_real_data_protection_not_bypassed_by_owner_button(blocked):
    _,state=clicked()
    result=future(state,96,blockers=blocked)
    assert result["active"] is None
    assert result["opened"]==0
    assert result["request"]["status"]=="WAIT_DATA"


def test_stale_quote_and_stale_frame_never_open_on_past_price():
    _,state=clicked()
    old=advance_manual_test(state,frame(96),spread=.6,
                            now=BASE+pd.Timedelta(days=1))
    assert old["active"] is None
    assert old["opened"]==0
    assert old["last_reason"]=="WAIT_FRESH_M1_CLOSE"
    assert advance_manual_test(state,frame(96),spread=.6,
        market_status="OFFLINE",now=BASE+pd.Timedelta(minutes=96,seconds=15))["opened"]==0
    assert advance_manual_test(state,frame(96),spread=.6,
        source="Capital.com LIVE REST",now=BASE+pd.Timedelta(minutes=96,seconds=15))["opened"]==0


def test_request_expires_if_feed_not_recovered_15_minutes():
    _,state=clicked()
    expired=expire_request_only(state,now=BASE+pd.Timedelta(minutes=111))
    assert expired["request"]["status"]=="EXPIRED"
    assert expired["active"] is None
    assert expired["opened"]==0


def test_on_gap_after_model_open_is_invalidated_without_fake_profit():
    _,state=clicked()
    p=future(state,96)
    op=future(p,97)
    assert op["active"]["status"]=="OPEN"
    gap=future(op,99)
    assert gap["active"] is None
    assert gap["invalidated_total"]==1
    assert gap["closed_total"]==0
    assert gap["invalidated_rows"][0]["previous_status"]=="OPEN"
    assert gap["invalidated_rows"][0]["pnl_pts"] is None


def test_spread_must_be_valid_before_pending_and_no_duplicate_user_clicks():
    remote,state=clicked()
    assert queue_manual_request(remote,"SHORT",now=created(94))["status"]==(
        "TEST_ALREADY_QUEUED_OR_ACTIVE")
    bad=future(state,96,spread=9)
    assert bad["active"] is None and bad["opened"]==0
    assert bad["last_reason"]=="WAIT_SPREAD_TOO_HIGH"


def test_cas_retry_does_not_overwrite_existing_auto_paper():
    remote=Remote()
    remote.conflict_once=True
    res=queue_manual_request(remote,"LONG",now=created(94))
    assert res["status"]=="QUEUED"
    assert remote.saves==1
    assert remote.payload["tables"]["paper_positions_v3"][0]["trade_id"]=="legacy-auto"


def test_daily_limit_exact_and_no_broker_orders_possible():
    remote=Remote()
    obj=blank()
    obj["attempted_days"]={"2026-11-18":3}
    remote.payload["manual_paper_test"]=obj
    assert queue_manual_request(remote,"LONG",now=created(94))["status"]==(
        "MANUAL_TEST_DAILY_LIMIT_3")
    assert remote.saves==0
    src=Path("trader/manual_paper_test.py").read_text("utf8")
    assert "queue_paper(" not in src
    assert "session.post(" not in src
    assert "POST /positions" not in src
    assert "advance_demo_broker(" not in src


def test_manual_trade_markers_and_existing_movement_path_reuse_archived_candles():
    _,state=clicked()
    setup=future(state,96)
    opened=future(setup,97)
    closed=opened
    for n in (98,99,100,101):
        if closed["active"] is None:
            break
        closed=future(closed,n)
    report=manual_report(closed)
    fig=go.Figure()
    annotate_manual_test(fig,report,
                         viewport=[stamp(95),stamp(105)])
    assert len(fig.data)>=2
    assert any("RĘCZNY LONG" in "".join(t.text) for t in fig.data)
    assert any("TEST CLOSE" in "".join(t.text) for t in fig.data)
    assert all(not t.showlegend for t in fig.data)
    fig2=go.Figure()
    metrics=annotate_position_trails(
        fig2,frame(108),{"manual_paper_test_report":report},choice="M1",
        viewport=[stamp(94),stamp(108)])
    assert metrics["drawn"]==1
    assert any("RUCH MANUAL TEST LONG" in trace.name for trace in fig2.data)


def test_worker_ui_and_chart_integrate_manual_via_same_checkpoint():
    worker=Path("trader/worker.py").read_text("utf8")
    ui=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    chart=Path("trader/paper_trade_trails.py").read_text("utf8")
    assert 'payload["manual_paper_test"]' in worker
    assert 'payload["manual_paper_test_report"]' in worker
    assert "advance_manual_test(" in worker
    assert "queue_manual_request(remote,clicked_side)" in ui
    assert "TESTUJ LONG" in ui and "TESTUJ SHORT" in ui
    assert "annotate_manual_test(" in ui
    assert "MANUAL TEST" in chart
    assert "queue_paper(" not in ui
