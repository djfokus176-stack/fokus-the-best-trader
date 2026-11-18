"""The owner terminal reads Supabase without requiring Capital auth."""
import pandas as pd
import pytest

from trader.cloud_paper_terminal import (
    cloud_terminal_summary, cloud_paper_decision, cloud_chart_view_range,
)


def frame():
    idx=pd.date_range("2026-11-13T20:45:00Z",periods=5,freq="15min")
    return pd.DataFrame({
        "Open":[5000.]*5,"High":[5003.]*5,"Low":[4997.]*5,
        "Close":[5001.]*5,"Spread":[0.9]*5},index=idx)


def test_worker_checkpoint_view_does_not_require_capital_login():
    payload={"meta":{"source":"Capital.com DEMO REST","epic":"US500",
           "last_scan_utc":"2026-11-15T15:00:00Z",
           "last_scan_summary":"WAIT / MARKET_CLOSED",
           "candle_backfill_enabled":True}}
    r=cloud_terminal_summary(7430,payload,frame(),
                             now="2026-11-15T15:03:00Z")
    assert r["version"]==7430
    assert r["bars"]==5
    assert r["cloud_online_confirmed"] is True
    assert r["age_minutes"]==3
    assert r["trade_permission"]=="WAIT"
    assert r["no_direct_capital_login"] is True
    assert "MARKET_CLOSED" in r["worker_summary"]


def test_stale_worker_checkpoint_is_explicitly_unknown():
    r=cloud_terminal_summary(7000,{
        "meta":{"last_scan_utc":"2026-11-13T14:00:00Z",
                "source":"Capital.com DEMO REST"}},
        frame(),now="2026-11-15T15:00:00Z")
    assert r["cloud_online_confirmed"] is False
    assert r["last_m15_utc"]=="2026-11-13T21:45:00+00:00"


def test_empty_archive_does_not_forge_candles_or_signals():
    r=cloud_terminal_summary(1,{"meta":{}},pd.DataFrame(),
                             now="2026-11-15T16:00:00Z")
    assert r["bars"]==0
    assert r["last_scan_utc"] is None
    assert r["last_m15_utc"] is None
    assert r["cloud_online_confirmed"] is False
    assert r["trade_permission"]=="WAIT"


def test_corrupted_candles_are_refused():
    f=frame()
    f.loc[f.index[-1],"High"]=4999.
    with pytest.raises(ValueError,match="OHLC"):
        cloud_terminal_summary(3,{"meta":{}},f)
    with pytest.raises(ValueError,match="instrument"):
        cloud_terminal_summary(3,{"meta":{"epic":"BTCUSD"}},frame())
    dup=pd.concat([frame(),frame().iloc[-1:]])
    with pytest.raises(ValueError,match="UTC"):
        cloud_terminal_summary(3,{"meta":{}},dup)


def test_unverified_future_checkpoint_not_marked_online():
    r=cloud_terminal_summary(2,{"meta":{
        "last_scan_utc":"2026-11-15T19:00:00Z"}},
        frame(),now="2026-11-15T15:00:00Z")
    assert r["age_minutes"]<0
    assert r["cloud_online_confirmed"] is False



def test_paper_status_is_worker_backed_not_made_up_from_candles():
    meta={
        "last_scan_utc":"2026-11-17T13:50:00Z",
        "last_scan_summary":(
            "2026-11-17T13:50:00+00:00 / SHORT / "
            "CANDIDATE_METHOD=AUTO → LIQUIDITY SWEEP / QUEUE=NO / "
            "ACTIVE=NONE / CANDLES=1396 / GATES=INCOMPLETE_MTF")
    }
    info=cloud_paper_decision(meta,now="2026-11-17T13:50:20Z")
    assert info["candidate"]=="SHORT"
    assert info["queue"]=="NO"
    assert info["gates"]=="INCOMPLETE_MTF"
    assert info["method"]=="AUTO → LIQUIDITY SWEEP"
    assert "BEZ wejścia" in info["headline"]
    assert not info["is_trade_instruction"]


def test_paper_status_wait_is_not_a_trading_tip():
    meta={
        "last_scan_utc":"2026-11-17T13:50:00Z",
        "last_scan_summary":(
            "2026-11-17T13:50:00+00:00 / WAIT / "
            "CANDIDATE_METHOD=WAIT — BRAK ZATWIERDZONEJ METODY / "
            "QUEUE=NO / ACTIVE=NONE / GATES=OK")
    }
    info=cloud_paper_decision(meta,now="2026-11-17T13:50:20Z")
    assert info["candidate"]=="WAIT" and info["gates"]=="OK"
    assert info["queue"]=="NO"
    assert "WAIT" in info["headline"]


def test_stale_or_missing_checkpoint_never_becomes_current_signal():
    meta={
        "last_scan_utc":"2026-11-17T13:50:00Z",
        "last_scan_summary":"2026-11-17T13:50:00Z / LONG / QUEUE=YES / GATES=OK"
    }
    info=cloud_paper_decision(meta,now="2026-11-17T14:00:00Z")
    assert not info["fresh"]
    assert "HISTORYCZNY" not in info["headline"] or "historyczny" in info["headline"]
    assert "BRAK BIEŻĄCEJ" in info["headline"]
    info=cloud_paper_decision({},now="2026-11-17T14:00:00Z")
    assert info["candidate"]=="UNKNOWN" and not info["fresh"]


def test_recent_candle_window_is_relative_to_archive_not_fixed_eight_hours():
    idx=pd.date_range("2026-11-17T12:00:00Z",periods=180,freq="min")
    f=pd.DataFrame({"Close":[7400.]*180},index=idx)
    lo,hi=cloud_chart_view_range(f,"M1")
    assert lo==idx[-65]
    assert hi==idx[-1]+pd.Timedelta(minutes=2)
    assert hi-lo<pd.Timedelta(minutes=70)
    moving={"at":idx[-1]+pd.Timedelta(minutes=1)}
    lo,hi=cloud_chart_view_range(f,"M1",moving=moving)
    assert lo==idx[-65] and hi==moving["at"]+pd.Timedelta(minutes=2)
    assert cloud_chart_view_range(pd.DataFrame(),"M1") is None
    with pytest.raises(ValueError):
        cloud_chart_view_range(f,"INVALID")


def test_chart_improvement_does_not_change_strategies_or_expose_fake_signals():
    from pathlib import Path
    src=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf8")
    assert "for period,color in ((9," in src
    assert 'min_periods=period' in src
    assert 'cloud_paper_decision(payload.get("meta") or {})' in src
    assert "height=720" in src
    assert "queue_paper(" not in src
    assert "CapitalReadOnly(" not in src
