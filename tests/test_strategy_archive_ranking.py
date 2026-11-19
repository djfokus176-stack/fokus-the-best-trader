"""Regression: trustworthy Polish OPEN times and durable strategy ranking."""
from datetime import date, datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
import pytest

from trader.trade_time_labels import in_poland,open_time_details
from trader.paper_display import annotate_paper_history
from trader.periodic_archive_audit import (
    advance_periodic_archive,archive_day_trades,automatic_audit_report,
)
from trader.strategy_archive_ranking import strategy_ranking
from trader.strategy_ranking_ui import ranking_data_frame

NOW=datetime(2026,11,19,14,0,tzinfo=timezone.utc)
SOURCE="Capital.com DEMO REST"


def paper(key,strategy="EMA PULLBACK",side="LONG",pts=8.5,
          close="2026-11-19T12:01:00+00:00",
          opened="2026-11-19T11:48:00+00:00",
          assumed="2026-11-19T11:47:00+00:00",
          setup="2026-11-19T11:47:00+00:00",auto=True):
    return {
        "trade_id":key,"source":SOURCE,"epic":"US500","timeframe":"MINUTE",
        "strategy":strategy,"side":side,
        "setup_utc":setup,"entry_assumed_utc":assumed,
        "opened_utc":opened,"entry_detected_utc":"2026-11-19T11:48:08+00:00",
        "closed_utc":close,"status":"CLOSED_TP" if pts>0 else "CLOSED_SL",
        "entry_mid":7416.6,"exit_mid":7425.3,"pnl_pts":pts,
        "setup_reason":("AUTO PAPER (eksperyment 1 sygnału) | other verified reason"
                        if auto else "ONLY SINGLE STRATEGY"),
    }


def test_screen_time_is_exact_warsaw_and_distinguishes_model_and_confirmation():
    row=paper("screen")
    x=open_time_details(row)
    assert x["model_pl"]=="19.11.2026 12:47"
    assert x["confirmed_pl"]=="19.11.2026 12:48"
    assert x["detected_pl"]=="19.11.2026 12:48"
    assert in_poland("2026-11-19T11:48:00+00:00")=="19.11.2026 12:48"


def test_missing_and_naive_times_stay_missing_not_guessed():
    no=open_time_details({"opened_utc":"2026-11-19T11:48:00"})
    assert no["confirmed_utc"] is None
    assert no["model_pl"]=="BRAK ZAPISANEJ GODZINY"
    assert in_poland("wrong")=="BRAK ZAPISANEJ GODZINY"


def test_paper_chart_no_longer_says_paper_open_and_has_real_pl_timestamps():
    trade=paper("abc")
    figure=go.Figure()
    annotate_paper_history(figure,[trade],"US500",SOURCE,None)
    assert len(figure.data)==2
    open_hover=" ".join(str(x) for trace in figure.data
                        for x in trace.text if "OTWARCIE" in str(x))
    assert "OTWARCIE LONG" in open_hover
    assert "AUTO → EMA PULLBACK" in open_hover
    assert "12:47" in open_hover
    assert "12:48" in open_hover
    assert "11:48:08" not in open_hover  # reported in Poland, not UTC
    assert "SYMoULACJA" not in open_hover
    assert "SYMULACJA" in open_hover
    assert "nie zlecenie" in open_hover


def payload(*positions,raw=None,momentum=None):
    return {"tables":{"paper_positions_v3":list(positions)},
            "raw_m1_forward_paper":{"closed":list(raw or [])},
            "momentum_paper_test":{"closed":list(momentum or [])}}


def test_archive_enriches_existing_trade_with_verified_times_not_pnl_rewrites():
    p=paper("a")
    first=advance_periodic_archive({},payload(p),now=NOW)
    record=next(iter(first["trades"].values()))
    assert record["m"]=="EMA PULLBACK"
    assert record["a"]=="AUTO ZWERYFIKOWANE"
    assert record["v"]=="2026-11-19T11:47:00+00:00"
    assert record["d"]=="2026-11-19T11:48:08+00:00"
    old=first.copy()
    old["trades"]={key:{k:v for k,v in row.items()
                        if k not in ("v","d","a")}
                   for key,row in first["trades"].items()}
    newer=advance_periodic_archive(old,payload(p),now=NOW)
    enriched=next(iter(newer["trades"].values()))
    assert enriched["p"]==8.5
    assert enriched["m"]=="EMA PULLBACK"
    assert enriched["v"]==record["v"]
    assert enriched["d"]==record["d"]
    assert len(newer["trades"])==1
    day=archive_day_trades(newer,date(2026,11,19))
    assert day[0]["OPEN modelowe (Polska)"]=="19.11.2026 12:47:00"
    assert day[0]["Potwierdzenie OPEN (Polska)"]=="19.11.2026 12:48:00"
    assert day[0]["Wykrycie przez worker (Polska)"]=="19.11.2026 12:48:08"


def test_rank_only_closed_and_separate_lanes_and_do_not_double_count_raw_methods():
    a=paper("a",pts=8)
    b=paper("b","EMA TREND",pts=-3,side="SHORT",
            close="2026-11-19T12:12:00+00:00")
    c=paper("c",pts=1.25,close="2026-11-19T12:24:00+00:00")
    pending=paper("pending",pts=20,close="2026-11-19T12:26:00+00:00")
    pending["status"]="PENDING"
    raw={
        "status":"CLOSED_TP","side":"LONG",
        "setup_utc":a["setup_utc"],"opened_utc":a["opened_utc"],
        "closed_utc":a["closed_utc"],"pnl_pts":4.7,
        "methods":["EMA TREND","EMA PULLBACK"],
    }
    archive=advance_periodic_archive(
        {},payload(a,b,c,pending,raw=[raw]),now=NOW)
    main=strategy_ranking(archive,"PAPER v3","day",now=NOW)
    assert main["total_closed"]==3
    assert main["total_net_pts"]==6.25
    assert main["rows"][0]["strategy"]=="EMA PULLBACK"
    assert main["rows"][0]["count"]==2
    assert main["rows"][0]["net_pts"]==9.25
    assert main["rows"][0]["sample_sufficient"] is False
    assert main["rows"][1]["strategy"]=="EMA TREND"
    assert main["rows"][1]["net_pts"]==-3
    rawrank=strategy_ranking(archive,"RAW M1 TEST","day",now=NOW)
    assert rawrank["total_closed"]==1
    assert len(rawrank["rows"])==1
    assert rawrank["rows"][0]["strategy"]=="EMA TREND + EMA PULLBACK"
    assert rawrank["rows"][0]["combined_methods"] is True
    assert rawrank["rows"][0]["net_pts"]==4.7
    assert strategy_ranking(archive,"PAPER v3","day",
                            now=NOW,direction="LONG")["total_closed"]==2
    assert strategy_ranking(archive,"PAPER v3","day",
                            now=NOW,direction="SHORT")["total_closed"]==1


def test_warsaw_midnight_trade_in_right_day_and_ranking_week_and_month():
    p=paper("mid",close="2026-11-18T23:30:00+00:00",
            opened="2026-11-18T23:10:00+00:00",
            setup="2026-11-18T23:09:00+00:00",
            assumed="2026-11-18T23:09:00+00:00")
    a=advance_periodic_archive({},payload(p),now=NOW)
    assert strategy_ranking(a,"PAPER v3","day",
                            reference=date(2026,11,18),now=NOW)["total_closed"]==0
    assert strategy_ranking(a,"PAPER v3","day",
                            reference=date(2026,11,19),now=NOW)["total_closed"]==1
    assert strategy_ranking(a,"PAPER v3","week",now=NOW)["total_closed"]==1
    assert strategy_ranking(a,"PAPER v3","month",now=NOW)["total_closed"]==1
    assert strategy_ranking(a,"PAPER v3","all",now=NOW)["total_closed"]==1


def test_finite_metrics_drawdown_pf_and_min30_are_descriptive_not_proven():
    rows=[]
    for i in range(32):
        stamp=datetime(2026,11,19,12,1,tzinfo=timezone.utc)
        close=(stamp+__import__("datetime").timedelta(minutes=i)).isoformat()
        p=paper(str(i),pts=2 if i%2==0 else -1,close=close)
        rows.append(p)
    archive=advance_periodic_archive({},payload(*rows),now=NOW)
    ranked=strategy_ranking(archive,"PAPER v3","day",now=NOW)
    best=ranked["rows"][0]
    assert best["count"]==32 and best["wins"]==16
    assert best["win_rate_pct"]==50.
    assert best["net_pts"]==16.
    assert best["avg_pts"]==.5
    assert best["profit_factor"]==2.
    assert best["sample_sufficient"]
    assert "BEZ POTWIERDZONEJ PRZEWAGI" in best["evidence"]
    assert best["max_drawdown_pts"]>=1
    assert not ranking_data_frame(ranked).empty


def test_checkpoint_report_includes_small_current_rankings_from_same_saved_rows():
    a=paper("new")
    archive=advance_periodic_archive({},payload(a),now=NOW)
    r=automatic_audit_report(archive,now=NOW)
    for window in ("day","week","month"):
        a=r["strategy_rankings_top3"][window]["PAPER v3"][0]
        assert a["strategia"]=="EMA PULLBACK"
        assert a["n"]==1
        assert a["netto_pkt"]==8.5
        assert a["proba_wystarczajaca"] is False


def test_no_changes_to_original_trade_entry_exit_execution():
    worker=Path("trader/worker.py").read_text("utf8")
    ui=Path("trader/periodic_archive_ui.py").read_text("utf8")
    plot=Path("trader/paper_display.py").read_text("utf8")
    ranks=Path("trader/strategy_archive_ranking.py").read_text("utf8")
    assert "render_strategy_ranking(archive,selected," in ui
    assert "OTWARCIE {side} — SYMULACJA" in plot
    assert 'open_time_details(pos)' in plot
    assert "strategy_ranking(" in ranks
    assert "queue_paper(" not in ranks
    assert "session.post(" not in ranks
    assert "CapitalReadOnly(" not in ranks
    assert "advance_raw_paper(" in worker
