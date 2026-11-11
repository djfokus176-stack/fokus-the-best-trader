"""Plotly PAPER ledger events must not drown live chart in a 40-row legend."""
import plotly.graph_objects as go
from trader.paper_display import annotate_paper_history


def trade(n, status="CLOSED_SL", pnl=-3.25, side="LONG", **updates):
    pos={
        "trade_id":f"paper-{n:03d}",
        "strategy":"EMA PULLBACK" if n%2 else "EMA TREND",
        "epic":"US500","source":"Capital.com DEMO REST",
        "timeframe":"MINUTE","side":side,
        "opened_utc":"2026-11-11T14:00:00+00:00",
        "entry_mid":7500+n,
        "closed_utc":"2026-11-11T14:12:00+00:00",
        "exit_mid":7495+n,"pnl_pts":pnl,"status":status
    }
    pos.update(updates)
    return pos


def test_many_paper_trades_have_only_compact_group_legend():
    positions=[trade(i,side=("SHORT" if i%2 else "LONG"),
                     pnl=(-2.35 if i%3 else 4.15)) for i in range(40)]
    fig=annotate_paper_history(go.Figure(),positions,"US500",
                               "Capital.com DEMO REST","MINUTE")
    assert len(fig.data)==4
    assert all(x.showlegend for x in fig.data)
    assert len({x.name for x in fig.data})==4
    assert sum(len(x.x) for x in fig.data)==80
    assert all(x.mode=="markers" for x in fig.data)
    assert all(x.hovertemplate=="%{text}<extra></extra>" for x in fig.data)
    flattened=" ".join(value for trace in fig.data for value in trace.text)
    assert "paper-000" in flattened and "paper-039" in flattened
    assert "EMA PULLBACK" in flattened and "EMA TREND" in flattened
    assert "-2.35 pkt" in flattened and "+4.15 pkt" in flattened


def test_paper_marker_loss_is_red_and_win_green():
    fig=annotate_paper_history(go.Figure(),
        [trade(1,pnl=-1.25),trade(2,pnl=3.4,status="CLOSED_TIMEOUT")],
        "US500","Capital.com DEMO REST","MINUTE")
    m={t.name:t for t in fig.data}
    assert m["PAPER: zamknięcie −"].marker.color=="#ff6575"
    assert m["PAPER: zamknięcie +"].marker.color=="#3de59a"
    assert all("CLOSED_" in "".join(t.text) for name,t in m.items()
               if "zamknięcie" in name)


def test_other_source_pending_and_invalidated_never_fabricate_closure():
    positions=[trade(1,status="PENDING",closed_utc=None,exit_mid=None),
               trade(2,status="INVALIDATED"),
               trade(3,source="CSV"),
               trade(4,epic="NAS100"),
               trade(5,timeframe="HOUR"),
               trade(6,status="CLOSED_TP",pnl=0.0)]
    fig=annotate_paper_history(go.Figure(),positions,"US500",
                              "Capital.com DEMO REST","MINUTE")
    m={t.name:t for t in fig.data}
    assert "PAPER: zamknięcie +" not in m
    assert "PAPER: zamknięcie −" not in m
    assert len(m["PAPER: otwarcie LONG"].x)==3
    assert len(m["PAPER: zamknięcie 0 / brak wyniku"].x)==1


def test_bad_row_does_not_break_chart_and_missing_id_not_fabricated():
    positions=[trade(1,opened_utc="broken",entry_mid=None),
               trade(2,pnl=None)]
    fig=annotate_paper_history(go.Figure(),positions,"US500",
                              "Capital.com DEMO REST","MINUTE")
    assert len(fig.data)==3  # 1 valid open, 2 valid closes in two groups
    assert "BRAK P&L" in " ".join(str(t.text) for t in fig.data)
