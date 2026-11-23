"""Verify frequency audit never confuses a raw vote with a PAPER OPEN."""
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
from pathlib import Path

from trader.auto_strategy import AUTO_MODE
from trader.candidate_radar import append_candidate
from trader.entry_frequency_audit import summarize_entry_frequency
from trader.strategies_pro import ALL_STRATEGIES
from trader.strategy import Decision


START=datetime(2026,11,17,14,0,tzinfo=timezone.utc)


def snapshot(n):
    return SimpleNamespace(epic="US500",resolution="MINUTE",
                           source="Capital.com DEMO REST",
                           confirmed_utc=START+timedelta(minutes=n))


def votes(raw_name=None,side="LONG",after=None):
    rows=[]
    for name in ALL_STRATEGIES:
        raw=side if name==raw_name else "WAIT"
        rows.append({"Strategia":name,"Setup OHLC":raw,
                     "Po filtrze MTF":after if raw!="WAIT" else "WAIT",
                     "Powód":"MTF veto" if raw!="WAIT" and after=="WAIT"
                             else "Brak pełnego układu"})
    # Research-only comparison must not change six-AUTO statistics.
    rows.append({"Strategia":"RANGE REJECTION • SHADOW",
                 "Setup OHLC":"SHORT",
                 "Po filtrze MTF":"NIE WYLICZANO (SHADOW)",
                 "Powód":"research"})
    return rows


def stages(side="BRAK",number=0):
    return [{"strategy":name,"stage":number if name==ALL_STRATEGIES[0] else 0,
             "side":side if name==ALL_STRATEGIES[0] else "BRAK"}
            for name in ALL_STRATEGIES]


def test_archive_adds_full_six_wait_reasons_but_never_research_seventh():
    result=append_candidate([],snapshot(0),Decision("WAIT",AUTO_MODE,"none"),
                            votes(),[],progress=stages("LONG",2))
    assert len(result)==1
    audit=result[0]["strategy_audit"]
    assert len(audit)==6
    assert audit[0]["stage"]==2 and audit[0]["stage_side"]=="LONG"
    assert all(r["raw"]=="WAIT" for r in audit)
    assert "RANGE REJECTION" not in [r["strategy"] for r in audit]


def test_funnel_counts_real_raw_mtf_global_and_no_trades():
    history=[]
    history=append_candidate(history,snapshot(0),Decision("WAIT",AUTO_MODE,"wait"),
                             votes(),[],progress=stages())
    history=append_candidate(history,snapshot(1),Decision("WAIT",AUTO_MODE,"mtf"),
                             votes(ALL_STRATEGIES[0],"SHORT","WAIT"),[],
                             progress=stages("SHORT",2))
    history=append_candidate(history,snapshot(2),Decision("LONG",AUTO_MODE,"ready"),
                             votes(ALL_STRATEGIES[1],"LONG","LONG"),[],
                             progress=stages())
    history=append_candidate(history,snapshot(3),Decision("LONG",AUTO_MODE,"macro"),
                             votes(ALL_STRATEGIES[1],"LONG","LONG"),
                             ["MACRO_BLACKOUT"],progress=stages())
    stats=summarize_entry_frequency(history)
    assert stats["scans"]==4
    assert stats["raw_scans"]==3
    assert stats["approved_scans"]==2
    assert stats["decision_scans"]==2
    assert stats["unblocked_decision_scans"]==1
    assert stats["gated_decision_scans"]==1
    assert stats["vetoed_signal_scans"]==1
    assert stats["raw_wait_scans"]==1
    assert stats["conflict_scans"]==0
    assert stats["audit_complete_scans"]==4
    assert stats["stage_complete_scans"]==4
    assert ("MACRO_BLACKOUT",1) in stats["global_gate_reasons"]
    sweep=next(x for x in stats["by_strategy"] if x["Strategia"]==ALL_STRATEGIES[0])
    assert sweep["Surowe LONG/SHORT"]==1
    assert sweep["Po MTF"]==0
    assert sweep["Veto MTF"]==1
    assert sweep["Etap 2/3"]==1
    trend=next(x for x in stats["by_strategy"] if x["Strategia"]==ALL_STRATEGIES[1])
    assert trend["Po MTF"]==2


def test_legacy_archive_still_counts_raw_without_inventing_wait_reasons():
    row=append_candidate([],snapshot(0),Decision("WAIT",AUTO_MODE,"mtf"),
                         votes(ALL_STRATEGIES[0],"LONG","WAIT"),[])[0]
    row.pop("strategy_audit",None)
    stats=summarize_entry_frequency([row])
    assert stats["scans"]==1
    assert stats["raw_scans"]==1
    assert stats["approved_scans"]==0
    assert stats["audit_complete_scans"]==0
    assert stats["stage_complete_scans"]==0
    assert stats["waiting_reasons"]==[]
    assert all(x["Etap 2/3"] is None for x in stats["by_strategy"])


def test_duplicate_scan_is_not_counted_twice_and_invalid_market_rejected():
    row=append_candidate([],snapshot(0),Decision("WAIT",AUTO_MODE,"wait"),
                         votes(),[])[0]
    bad=dict(row);bad["epic"]="GER40"
    extra=dict(row);extra["key"]="arbitrary"
    stats=summarize_entry_frequency([row,dict(row),bad,extra])
    assert stats["scans"]==1
    assert summarize_entry_frequency([])["scans"]==0
    assert summarize_entry_frequency(None)["scans"]==0


def test_global_gate_is_distinct_from_strategy_formation_and_mtf():
    row=append_candidate([],snapshot(0),Decision("LONG",AUTO_MODE,"ready"),
                         votes(ALL_STRATEGIES[1],"LONG","LONG"),
                         ["MARKET_NOT_TRADEABLE","MACRO_BLACKOUT"])[0]
    stats=summarize_entry_frequency([row])
    assert stats["approved_scans"]==1
    assert stats["unblocked_decision_scans"]==0
    assert stats["gated_decision_scans"]==1
    assert stats["global_gate_reasons"]==[
        ("MARKET_NOT_TRADEABLE",1),("MACRO_BLACKOUT",1)
    ] or set(stats["global_gate_reasons"])=={
        ("MARKET_NOT_TRADEABLE",1),("MACRO_BLACKOUT",1)
    }


def test_no_broker_order_or_strategy_threshold_changes():
    src=Path("trader/entry_frequency_audit.py").read_text("utf8")
    archive=Path("trader/candidate_radar.py").read_text("utf8")
    worker=Path("trader/worker.py").read_text("utf8")
    ui=Path("app.py").read_text("utf8")
    assert "summarize_entry_frequency(candidates)" in ui
    assert "progress=vote_audit" in worker
    assert "queue_paper(" not in src+archive
    assert "CapitalReadOnly(" not in src+archive
    assert "send_order" not in src+archive
