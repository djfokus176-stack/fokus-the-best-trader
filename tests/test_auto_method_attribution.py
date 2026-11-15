"""AUTO labeling is read-only, ledger-grounded and must never change orders."""
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go

from trader.auto_strategy import AUTO_MODE
from trader.strategies_pro import ALL_STRATEGIES
from trader.ema50_wave import STRATEGY_NAME as WAVE_NAME
from trader.fokus_3f import NAME as THREEF_NAME
from trader.paper_method_labels import (
    RESEARCH_DISPLAY_ORDER, display_choice, method_attribution,
    decision_attribution,
)
from trader.paper_display import annotate_paper_history
from trader.paper_audit import paper_export_table, paper_labeled_export_table
from trader.cloud_paper_terminal import cloud_paper_positions
from trader.strategy import Decision


def pos(*, strategy="EMA PULLBACK", reason=None, status="OPEN",
        timeframe="MINUTE", trade_id="abc123"):
    return {
        "trade_id":trade_id, "epic":"US500", "source":"Capital.com DEMO REST",
        "timeframe":timeframe,"strategy":strategy,"side":"LONG","status":status,
        "setup_reason":reason,
        "created_utc":"2026-11-15T19:00:00+00:00",
        "opened_utc":"2026-11-15T19:01:00+00:00",
        "entry_mid":7500.0,
        "closed_utc":None,
    }


AUTO_REASON=("GŁOSY MTF 1/1 (LONG:1, SHORT:0, veto MTF:0). "
             "AUTO PAPER (eksperyment 1 sygnału): zatwierdzone: EMA PULLBACK.")


def test_presentation_ranking_auto_is_first_and_original_six_preserved():
    assert RESEARCH_DISPLAY_ORDER[0]==AUTO_MODE
    assert set(RESEARCH_DISPLAY_ORDER)=={AUTO_MODE,*ALL_STRATEGIES,WAVE_NAME,THREEF_NAME}
    assert len(RESEARCH_DISPLAY_ORDER)==9
    assert RESEARCH_DISPLAY_ORDER[-1]==THREEF_NAME
    assert display_choice(THREEF_NAME).startswith('9. ')
    assert display_choice(AUTO_MODE).startswith("1. ")
    assert all(display_choice(name).startswith(str(i)+". ")
               for i,name in enumerate(RESEARCH_DISPLAY_ORDER,1))


def test_auto_position_is_explicitly_attributed_to_selected_underlying_method():
    result=method_attribution(pos(reason=AUTO_REASON))
    assert result["mode"]==AUTO_MODE
    assert result["method"]=="EMA PULLBACK"
    assert result["label"]=="AUTO → EMA PULLBACK"


def test_manual_and_unknown_historical_origin_never_mislabelled_auto():
    direct=method_attribution(pos(reason="Pojedynczy setup EMA PULLBACK"))
    assert direct["mode"]!="AUTO — 6 STRATEGII"
    assert direct["method"]=="EMA PULLBACK"
    assert direct["label"]=="METODA: EMA PULLBACK"
    assert method_attribution(pos(strategy="NIEZNANA",reason=AUTO_REASON))["method"]=="BRAK"
    assert method_attribution(None)["label"]=="METODA NIEUSTALONA"


def test_decision_label_is_not_position_fill():
    d=Decision("LONG","BREAKOUT RETEST","as-of setup")
    assert decision_attribution(AUTO_MODE,d)=="AUTO → BREAKOUT RETEST"
    assert decision_attribution("BREAKOUT RETEST",d)=="METODA: BREAKOUT RETEST"
    assert "WAIT" in decision_attribution(AUTO_MODE,Decision("WAIT","EMA TREND","brak"))
    assert "BEZ POTWIERDZONEJ" in decision_attribution(AUTO_MODE,Decision("LONG","MISSING","brak"))


def test_csv_journal_preserves_method_and_auto_origin():
    rows=[pos(reason=AUTO_REASON),pos(strategy="EMA TREND",reason="manual",trade_id="def")]
    assert list(paper_export_table(rows).columns).count('opis_sygnalu')==0
    report=paper_labeled_export_table(rows)
    assert list(report["tryb_sygnalu"])==[AUTO_MODE,"NIEUSTALONY / POJEDYNCZY"]
    assert list(report["wybrana_metoda"])==["EMA PULLBACK","EMA TREND"]
    assert list(report["opis_sygnalu"])==["AUTO → EMA PULLBACK","METODA: EMA TREND"]
    assert report.iloc[0]["trade_id"]=="abc123"
    assert "setup_reason" in report.columns


def test_chart_only_marks_saved_open_close_with_exact_method():
    a=pos(reason=AUTO_REASON)
    b=pos(strategy="BREAKOUT RETEST",reason="manual",
          timeframe="MINUTE_15",trade_id="def")
    b.update(status="CLOSED_TP",closed_utc="2026-11-15T19:15:00+00:00",
             exit_mid=7510.0,pnl_pts=9.4)
    c=pos(strategy="EMA TREND",reason=AUTO_REASON,status="PENDING",trade_id="ghi")
    c.pop("opened_utc")
    wrong=pos(strategy="EMA PULLBACK",reason=AUTO_REASON,trade_id="wrong")
    wrong["source"]="Capital.com LIVE REST"
    fig=annotate_paper_history(go.Figure(),[a,b,c,wrong],
                               "US500","Capital.com DEMO REST",None)
    points=[text for trace in fig.data for text in trace.text]
    assert len(points)==3  # two OPEN + one CLOSED, no PENDING/wrong source
    assert any("AUTO → EMA PULLBACK" in txt for txt in points)
    assert any("METODA: BREAKOUT RETEST" in txt for txt in points)
    assert any("Interwał pozycji: MINUTE" in txt for txt in points)
    fig_tf=annotate_paper_history(go.Figure(),[a,b],
                                  "US500","Capital.com DEMO REST","MINUTE")
    assert sum(len(tr.x) for tr in fig_tf.data)==1


def test_cloud_readonly_filters_other_epics_and_offchart_markers():
    idx=pd.date_range("2026-11-15T19:00:00Z",periods=4,freq="15min")
    candles=pd.DataFrame({"Open":[7500]*4,"High":[7501]*4,
        "Low":[7499]*4,"Close":[7500]*4,"Spread":[0.6]*4},index=idx)
    a=pos(reason=AUTO_REASON)
    b=pos(strategy="EMA TREND",reason="old",trade_id="old")
    b.update(opened_utc="2025-01-01T00:00:00+00:00")
    wrong=pos(trade_id="bad")
    wrong["epic"]="GER40"
    payload={"tables":{"paper_positions_v3":[a,b,wrong]}}
    latest,chart=cloud_paper_positions(payload,candles)
    assert len(latest)==2  # wrong epic omitted
    assert len(chart)==1
    assert chart[0]["trade_id"]=="abc123"
    assert payload["tables"]["paper_positions_v3"][0]["setup_reason"]==AUTO_REASON
    assert cloud_paper_positions({},candles)==([],[])
