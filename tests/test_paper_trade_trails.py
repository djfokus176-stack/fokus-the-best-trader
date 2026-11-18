"""Forward-only PAPER trails on existing real archived OHLC, no fictitious ticks."""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest

from trader.paper_trade_trails import (
    annotate_position_trails, recorded_positions, _normalise,
)


BASE=pd.Timestamp("2026-11-18T12:00:00Z")


def frame(*, end=20, drop=()):
    idx=pd.date_range(BASE,periods=end+1,freq="min")
    idx=idx.delete(list(drop)) if drop else idx
    prices=[7360.+i*.45 for i in range(len(idx))]
    return pd.DataFrame({
        "Open":prices,
        "High":[p+.9 for p in prices],
        "Low":[p-.9 for p in prices],
        "Close":[p+.25 for p in prices],
        "Spread":[.5]*len(idx),
    },index=idx)


def ts(minutes):
    return (BASE+pd.Timedelta(minutes=minutes)).isoformat()


def raw(side="LONG",status="CLOSED_TP",start=2,end=12,pnl=5.6):
    return {
        "status":status,"side":side,"methods":["EMA TREND"],
        "setup_utc":ts(start),"entry_bar_open_utc":ts(start),
        "opened_utc":ts(start+1),
        "entry_mid":7363.1,"stop":7357.,"target":7380.,
        "closed_utc":ts(end) if status.startswith("CLOSED_") else None,
        "exit_mid":7370.1 if status.startswith("CLOSED_") else None,
        "pnl_pts":pnl if status.startswith("CLOSED_") else None,
    }


def checkpoint(*,raw_rows=(),raw_active=None,v3_rows=(),momentum_rows=()):
    return {
        "raw_m1_forward_paper_report":{
            "status":"FORWARD_ONLY_RAW_M1_SIMULATION",
            "recent":list(raw_rows),"active":raw_active,"invalidated_recent":[]},
        "tables":{"paper_positions_v3":list(v3_rows)},
        "momentum_paper_test":{
            "schema":1,"closed":list(momentum_rows),"active":None},
    }


def test_long_path_segments_stay_on_real_bar_closes_after_exit_and_show_net():
    df=frame()
    r=raw()
    fig=go.Figure()
    output=annotate_position_trails(
        fig,df,checkpoint(raw_rows=[r]),choice="M1",
        viewport=[ts(0),ts(20)])
    assert output["drawn"]==1
    assert output["samples"]>=7
    assert len(fig.data)>=5
    assert any("RUCH RAW M1 LONG" in t.name for t in fig.data)
    assert any("WYNIK NETTO: +5.60 pkt" in str(t.customdata)
               for t in fig.data if "MODEL WYJŚCIA" in t.name)
    # The final model-exit marker must not be silently substituted for
    # a bar Close (the SL/TP hit might have occurred intrabar).
    endpoints=[t for t in fig.data if "MODEL WYJŚCIA" in t.name]
    assert endpoints and endpoints[0].line.dash=="dash"
    assert endpoints[0].y[-1]==r["exit_mid"]
    assert any("RAW M1 ENTRY" in t.name for t in fig.data)
    assert any("RAW M1 SL" in t.name for t in fig.data)
    assert any("RAW M1 TP" in t.name for t in fig.data)
    assert any("Godzina polska:" in str(t.customdata)
               for t in fig.data if "RUCH RAW M1" in t.name)


def test_short_path_colors_good_move_differently_from_bad_without_cost_claims():
    df=frame()
    short=raw(side="SHORT",pnl=-5.4)
    fig=go.Figure()
    output=annotate_position_trails(
        fig,df,checkpoint(raw_rows=[short]),choice="M1")
    assert output["drawn"]==1
    # Prices increase and short loses; trail is red, even though the
    # underlying raw signal genuinely came from the ledger.
    segments=[t for t in fig.data if "RUCH RAW M1" in t.name]
    assert segments
    assert any(t.line.color=="#f04860" for t in segments)
    assert any("bez kosztów" in str(t.customdata) for t in segments)
    assert any("WYNIK NETTO: -5.40 pkt" in str(t.customdata)
               for t in fig.data if "MODEL WYJŚCIA" in t.name)


def test_pending_observation_unknown_and_non_demo_ignored():
    pending=raw(status="PENDING")
    invalid=raw(status="CLOSED_SL")
    invalid["entry_mid"]=None
    wrong_market={
        "epic":"US500","source":"Capital.com LIVE REST","trade_id":"x",
        "status":"OPEN","side":"LONG","opened_utc":ts(3),"entry_mid":7363,
    }
    report=checkpoint(raw_active=pending,raw_rows=[invalid],
                      v3_rows=[wrong_market])
    assert recorded_positions(report)==[]
    fig=go.Figure()
    result=annotate_position_trails(fig,frame(),report)
    assert result["drawn"]==0 and len(fig.data)==0


def test_paper_v3_stays_in_separate_ledger_and_has_known_open_time():
    v3={
        "trade_id":"real-paper-v3-id","epic":"US500",
        "source":"Capital.com DEMO REST","timeframe":"MINUTE",
        "strategy":"AUTO EMA","status":"CLOSED_TIMEOUT",
        "side":"LONG","entry_assumed_utc":ts(2),
        "opened_utc":ts(3),"closed_utc":ts(15),
        "entry_mid":7361.2,"exit_mid":7367.2,
        "stop_mid":7354.0,"target_mid":7380.0,
        "pnl_pts":5.5,
    }
    payload=checkpoint(v3_rows=[v3])
    normalized=recorded_positions(payload)
    assert len(normalized)==1
    assert normalized[0]["lane"]=="PAPER v3"
    assert normalized[0]["start"]==pd.Timestamp(ts(2))
    fig=go.Figure()
    x=annotate_position_trails(fig,frame(),payload,choice="M1")
    assert x["drawn"]==1
    assert any("RUCH PAPER v3 LONG" in t.name for t in fig.data)
    assert any(t.name=="PAPER v3 SL" for t in fig.data)


def test_momentum_reuses_existing_full_ledger_without_changes_to_worker():
    momentum=raw()
    momentum["strategy"]="MOMENTUM_M1_TEST"
    p=checkpoint(momentum_rows=[momentum])
    rows=recorded_positions(p)
    assert len(rows)==1 and rows[0]["lane"]=="MOMENTUM"
    fig=go.Figure()
    assert annotate_position_trails(fig,frame(),p)["drawn"]==1


def test_gap_breaks_line_no_interpolation_over_unknown_m1_candle():
    candles=frame(drop=(5,))
    fig=go.Figure()
    status=annotate_position_trails(
        fig,candles,checkpoint(raw_rows=[raw()]))
    assert status["drawn"]==1
    assert status["gaps"]>=1
    traces=[x for x in fig.data if "RUCH RAW M1" in x.name]
    for t in traces:
        # Plotly uses None as a deliberate break. Removing it would
        # falsely make distinct, disconnected segments look contiguous.
        pairs=list(zip(t.x,t.y))
        assert not any((a[0]==pd.Timestamp(ts(4)) and
                        b[0]==pd.Timestamp(ts(6)))
                       for a,b in zip(pairs,pairs[1:]))
        assert t.connectgaps is False
        assert None in t.x


def test_invalidated_open_shows_only_earlier_real_bars_no_fake_close_pnl():
    p=raw(status="OPEN")
    p["status"]="INVALIDATED"
    p["invalidated_utc"]=ts(10)
    p["previous_status"]="OPEN"
    p["invalidation_reason"]="MISSING_M1_BAR"
    payload=checkpoint()
    payload["raw_m1_forward_paper_report"]["invalidated_recent"]=[p]
    fig=go.Figure()
    stat=annotate_position_trails(fig,frame(),payload)
    assert stat["drawn"]==1
    assert not any("MODEL WYJŚCIA" in t.name for t in fig.data)
    assert not any("WYNIK NETTO" in str(t.customdata) for t in fig.data)


def test_just_one_bar_tp_sl_has_no_invented_intrabar_rally_path():
    p=raw(start=2,end=3)
    fig=go.Figure()
    out=annotate_position_trails(fig,frame(),checkpoint(raw_rows=[p]))
    assert out["drawn"]==0 and not fig.data


def test_active_trade_live_quote_is_real_mid_preview_not_paper_profit():
    active=raw(status="OPEN")
    active["closed_utc"]=None
    active["pnl_pts"]=None
    candles=frame(end=20)
    quote_times=[ts(20), (BASE+pd.Timedelta(minutes=20,seconds=5)).isoformat(),
                 (BASE+pd.Timedelta(minutes=20,seconds=10)).isoformat()]
    overlay=[{"time":t,"mid":7369.5+i*.1}
             for i,t in enumerate(quote_times)]
    fig=go.Figure()
    out=annotate_position_trails(
        fig,candles,checkpoint(raw_active=active),choice="M1",
        viewport=[ts(0),ts(21)],live_quotes=overlay)
    assert out["drawn"]==1
    lines=[t for t in fig.data if t.name=="BIEŻĄCY MID (PODGLĄD)"]
    assert len(lines)==1
    assert lines[0].line.dash=="dot"
    assert "nie fill" in lines[0].hovertemplate
    assert not any("MODEL WYJŚCIA" in t.name for t in fig.data)
    assert recorded_positions(checkpoint(raw_active=active))[0]["status"]=="OPEN"


def test_history_scope_and_capped_number_of_paths_protect_chart():
    positions=[raw(start=i,end=i+4) for i in (1,4,7,10,13)]
    f=frame(end=25)
    view=[ts(10),ts(22)]
    fig=go.Figure()
    out=annotate_position_trails(fig,f,checkpoint(raw_rows=positions),
                                 viewport=view,max_positions=2)
    assert out["available"]>=2
    assert out["drawn"]<=2
    outside=annotate_position_trails(go.Figure(),f,checkpoint(raw_rows=positions),
                                     viewport=[ts(23),ts(25)])
    assert outside["drawn"]==0


def test_terminal_reads_trails_after_candles_but_before_existing_markers():
    text=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    chart=Path("trader/paper_trade_trails.py").read_text("utf8")
    assert "show_trade_trails=st.checkbox(" in text
    assert "annotate_position_trails(" in text
    assert (text.index("annotate_position_trails(") <
            text.index("annotate_paper_history(candles,chart_paper,"))
    assert "annotate_raw_forward(candles,raw_trial," in text
    assert "candle_price_window(" in text
    assert "queue_paper(" not in chart
    assert "capital_demo_broker" not in chart
    assert "RemoteCheckpoint(" not in chart
    assert "session.post(" not in chart
