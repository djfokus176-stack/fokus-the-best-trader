"""Candle motion diagnostics and honest independent PAPER readiness audit."""
from datetime import datetime,timedelta,timezone
from trader.live_chart_fragment import live_chart_refresh_state,motion_state
from trader.paper_health import worker_age_seconds,readiness_report

NOW=datetime(2026,11,6,0,15,tzinfo=timezone.utc)


class FakeClient:
    def __init__(self):
        self.next_price=7331.0
        self.calls=0
    def forming_candle(self,epic,tf,now=None):
        self.calls+=1
        price=self.next_price
        return dict(epic=epic,timeframe=tf,environment="DEMO",
            time=NOW+timedelta(minutes=1),last_tick=NOW,
            Open=7330.,High=max(7332.,price),Low=7329.,Close=price,
            bid=price-.3,ask=price+.3,spread=.6,
            source="Capital.com /prices • bieżąca OHLC")


def update(state,c,t):
    return live_chart_refresh_state(state,client=c,instrument="US500",
        timeframe="MINUTE",environment="DEMO",period=5,tick=t,
        utc=NOW+timedelta(seconds=t-100))


def test_clock_and_actual_price_changes_are_separate():
    state={};c=FakeClient()
    assert update(state,c,100)
    assert motion_state(state)=="FIRST_SAMPLE"
    assert not update(state,c,101)  # avoids fake 5s rerun/API request
    assert update(state,c,105)
    assert motion_state(state)=="UNCHANGED"
    assert state["_live_chart_success_count"]==2
    assert state["_live_chart_attempts"]==2
    assert len(state["_live_chart_price_tape"])==2
    c.next_price=7331.5
    assert update(state,c,110)
    assert motion_state(state)=="CHANGED"
    assert state["_live_chart_price_tape"][-1]["mid"]==7331.5
    assert state["_live_chart_last_move_utc"]==(NOW+timedelta(seconds=10)).isoformat()
    assert len(state["_live_chart_price_tape"])==3


def test_tape_is_bounded_and_cleared_on_instrument_change():
    s={};c=FakeClient()
    for i in range(115):
        update(s,c,100+i*5)
    assert len(s["_live_chart_price_tape"])==90
    assert s["_live_chart_success_count"]==115
    live_chart_refresh_state(s,client=c,instrument="NAS100",
        timeframe="MINUTE",environment="DEMO",period=5,tick=1000,utc=NOW)
    assert s["_live_chart_success_count"]==1
    assert len(s["_live_chart_price_tape"])==1


def test_worker_age_and_all_technical_blockers_are_explicit():
    assert worker_age_seconds({"last_scan_utc":NOW.isoformat()},NOW)==0
    assert worker_age_seconds({"last_scan_utc":"garbage"},NOW) is None
    assert worker_age_seconds({"last_scan_utc":NOW.isoformat()},
                              NOW+timedelta(minutes=17))>900
    report=readiness_report(clock_verified=False,data_ready=False,
        market_status="UNKNOWN",mtf_ready=False,calendar_current=False,
        remote_view=True,worker_age=1100,
        last_worker_summary="WAIT / DATA_STALE / CANDLE_TIME_UNVERIFIED",
        ui_strategy="AUTO",worker_strategy="EMA50 WAVE")
    assert not report["ready_to_consider_setup"]
    assert len(report["blockers"])>=6
    assert "Zmiana w Streamlit" in report["worker_strategy_note"]


def test_no_blockers_does_not_mean_mandatory_long_or_short():
    out=readiness_report(clock_verified=True,data_ready=True,
        market_status="TRADEABLE",mtf_ready=True,
        calendar_current=True,remote_view=False)
    assert out["ready_to_consider_setup"]
    assert "NIE oznacza sygnału LONG/SHORT" in out["note"]
