"""Tests for transparent PAPER events, adaptive exit and event sound safety."""
from datetime import datetime,timezone
import io
import sqlite3
import wave
import pandas as pd
import plotly.graph_objects as go

from trader.paper_lifecycle import queue_paper,progress_paper,recent_positions,recent_events
from trader.strategy import Decision
from trader.storage import connect
from trader.paper_display import annotate_paper_history
from trader.paper_sounds import unseen_paper_event,wav_notice
from trader.candidate_radar import append_candidate

T0=pd.Timestamp("2026-11-05T13:00:00Z")
SRC="Capital.com DEMO REST"


def _frame(rows):
    index=pd.date_range(T0+pd.Timedelta(minutes=1),periods=len(rows),freq="min",tz="UTC")
    return pd.DataFrame(rows,index=index,columns=["Open","High","Low","Close"])


def _open(db,side="LONG",policy="adaptive",target=104):
    if side=="LONG":
        d=Decision("LONG","EMA TREND","synthetic candidate",100,98,target,2)
    else:
        d=Decision("SHORT","EMA TREND","synthetic candidate",100,102,96,2)
    tid=queue_paper(db,"US500",SRC,"MINUTE",d,T0,.6,slippage=0,exit_policy=policy)
    assert tid
    return tid


def test_adaptive_extends_target_only_after_closed_bar_and_protects_profit(tmp_path):
    db=connect(tmp_path/"adaptive.sqlite")
    _open(db)
    b1=_frame([[100,100.5,99.5,100.2]])
    assert progress_paper(db,b1,"US500",SRC,"MINUTE")==["PAPER_OPEN"]
    rows=_frame([[100,100.5,99.5,100.2],
                 [100.2,103.6,100,103.2]])
    events=progress_paper(db,rows,"US500",SRC,"MINUTE")
    assert events==["PAPER_TRAIL_SL","PAPER_EXTEND_TP"]
    pos=recent_positions(db)[0]
    assert pos["target_mid"]>pos["original_target_mid"]==104
    assert pos["stop_mid"]>98
    assert pos["model_version"]=="v3_adaptive_close_only"
    assert pos["target_extended"]==1
    assert pos["status"]=="OPEN"
    # A new bar sees newly protected SL and extended target.
    rows=_frame([[100,100.5,99.5,100.2],
                 [100.2,103.2,100,102.8],
                 [103.2,104.2,101.0,101.2]])
    events=progress_paper(db,rows,"US500",SRC,"MINUTE")
    assert events==["PAPER_CLOSE_SL"]
    pos=recent_positions(db)[0]
    assert pos["pnl_pts"]>0  # Trailing stop can exit with profit
    assert pos["status"]=="CLOSED_SL"  # Status describes exit mechanism, not P&L
    assert progress_paper(db,rows,"US500",SRC,"MINUTE")==[]
    kinds=[e["kind"] for e in recent_events(db)]
    assert kinds.count("PAPER_EXTEND_TP")==1
    assert kinds.count("PAPER_TRAIL_SL")==1
    assert kinds.count("PAPER_CLOSE_SL")==1


def test_intra_bar_old_tp_cannot_be_retroactively_extended(tmp_path):
    db=connect(tmp_path/"tp.sqlite")
    _open(db)
    rows=_frame([[100,100.5,99.5,100],
                 [100,104.3,99.9,103.2]])
    events=progress_paper(db,rows,"US500",SRC,"MINUTE")
    assert "PAPER_CLOSE_TP" in events
    assert "PAPER_EXTEND_TP" not in events
    assert recent_positions(db)[0]["target_mid"]==104


def test_fixed_policy_keeps_target_and_never_trails(tmp_path):
    db=connect(tmp_path/"fixed.sqlite")
    _open(db,policy="fixed")
    bars=_frame([[100,100.5,99.5,100],[100,103,99.9,102.8]])
    events=progress_paper(db,bars,"US500",SRC,"MINUTE")
    assert "PAPER_TRAIL_SL" not in events
    assert "PAPER_EXTEND_TP" not in events
    pos=recent_positions(db)[0]
    assert pos["stop_mid"]==98 and pos["target_mid"]==104
    assert pos["model_version"]=="v3_paper_close_only"


def test_rehydration_preserves_exit_policy(tmp_path):
    from trader.remote_checkpoint import dump_state,restore_state
    db=connect(tmp_path/"save.sqlite")
    _open(db)
    progress_paper(db,_frame([[100,100.5,99.5,100.2],
        [100.2,103,99.9,102.7]]),"US500",SRC,"MINUTE")
    state=dump_state(db)
    fresh=sqlite3.connect(":memory:")
    restore_state(fresh,state)
    restored=recent_positions(fresh)[0]
    assert restored["exit_policy"]=="adaptive"
    assert restored["target_extended"]==1
    assert restored["initial_risk_mid"]==2


def test_visible_chart_has_entry_and_exit_pnl_from_positions():
    fig=go.Figure()
    positions=[{"trade_id":"paper-123456789","epic":"US500",
      "source":SRC,"timeframe":"MINUTE","side":"SHORT",
      "status":"CLOSED_TP","setup_utc":T0.isoformat(),
      "opened_utc":(T0+pd.Timedelta(minutes=1)).isoformat(),"entry_mid":100,
      "closed_utc":(T0+pd.Timedelta(minutes=2)).isoformat(),"exit_mid":97,
      "pnl_pts":2.4}]
    annotate_paper_history(fig,positions,"US500",SRC,"MINUTE")
    assert len(fig.data)==2
    assert any("PAPER SHORT" in (t.name or "") for t in fig.data)
    assert any("2.40 pkt" in str(t.text) for t in fig.data)
    assert len(go.Figure().data)==0


def test_alerts_are_deduplicated_and_not_replayed_at_first_open():
    newest={"event_id":"b","kind":"PAPER_CLOSE_SL","trade_id":"2"}
    old={"event_id":"a","kind":"PAPER_OPEN","trade_id":"1"}
    assert unseen_paper_event([newest,old],None)==("b",None)
    assert unseen_paper_event([newest,old],"a")==("b",newest)
    assert unseen_paper_event([newest,old],"b")==("b",None)
    # Browser sound can be rendered as valid WAV only for allowed event types.
    sound=wav_notice("PAPER_CLOSE_SL")
    with wave.open(io.BytesIO(sound)) as stream:
        assert stream.getnchannels()==1 and stream.getnframes()>1000


def test_raw_candidate_is_archived_but_never_equated_to_trade():
    from types import SimpleNamespace
    snap=SimpleNamespace(confirmed_utc=T0.to_pydatetime(),epic="US500",
        source=SRC,resolution="MINUTE")
    decision=SimpleNamespace(action="WAIT")
    vote=[{"Strategia":"EMA TREND","Setup OHLC":"LONG",
           "Po filtrze MTF":"WAIT","RR":1.6,"Powód":"MTF blocked"}]
    one=append_candidate([],snap,decision,vote,["INCOMPLETE_MTF"])
    two=append_candidate(one,snap,decision,vote,["INCOMPLETE_MTF"])
    assert len(one)==len(two)==1
    assert two[0]["raw_candidates"][0]["direction"]=="LONG"
    assert two[0]["decision"]=="WAIT"
    assert "trade_id" not in two[0]


def test_policy_reports_do_not_merge_adaptive_with_fixed(tmp_path):
    from trader.paper_reporting import performance_by_policy
    db=connect(tmp_path/"policy.sqlite")
    _open(db,policy="fixed")
    progress_paper(db,_frame([[100,100.5,99.5,100],[100,104.2,99.5,104]]),
                   "US500",SRC,"MINUTE")
    # Distinct candle timestamp and strategy used for a new PAPER trade.
    t2=T0+pd.Timedelta(minutes=3)
    d=Decision("LONG","EMA TREND","another signal",100,98,104,2)
    tid=queue_paper(db,"US500",SRC,"MINUTE",d,t2,.6,slippage=0,
                    exit_policy="adaptive")
    assert tid
    second=pd.DataFrame([[100,100.5,99.5,100],
                         [100,104.2,99.5,104]],
        index=pd.date_range(t2+pd.Timedelta(minutes=1),periods=2,freq="min",tz="UTC"),
        columns=["Open","High","Low","Close"])
    progress_paper(db,second,"US500",SRC,"MINUTE")
    result=performance_by_policy(db,"US500")
    assert len(result)==2
    assert {r["Wariant"] for r in result}=={"fixed","adaptive"}
    assert sum(r["Zamknięte"] for r in result)==2
