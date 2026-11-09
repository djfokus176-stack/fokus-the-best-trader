"""Causal 6-strategy M1 audit, not historical PAPER execution or fabricated fills."""
from datetime import datetime, timezone, timedelta
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from trader.signal_audit import audit_recent_closed_bars, rejection_stage
from trader.mtf import TIMEFRAMES, evaluate_timeframes
from trader.market import Snapshot, PERIOD


def sample_snapshots():
    anchor=pd.Timestamp.now(tz="UTC").floor("min")-pd.Timedelta(minutes=1)
    snapshots={}
    for tf in TIMEFRAMES:
        sec=PERIOD[tf]
        last=anchor.floor(f"{sec}s")
        ix=pd.date_range(end=last,periods=145 if tf=="MINUTE" else 95,
                         freq=f"{sec}s",tz="UTC")
        px=np.full(len(ix),100.0,dtype=float)
        frame=pd.DataFrame({
            "Open":px,"High":px+1,"Low":px-1,"Close":px,
            "Spread":np.full(len(ix),0.4)
        },index=ix)
        snapshots[tf]=Snapshot(frame,"Capital.com DEMO REST","US500",tf,
                               .4,last.to_pydatetime(),20,True,"OK")
    return snapshots


def test_flat_pattern_all_wait_even_when_mtf_ready_and_no_blocker():
    snaps=sample_snapshots()
    m1=snaps["MINUTE"].frame
    timeline,detail,summary=audit_recent_closed_bars(m1,snaps,lookback=12)
    assert len(timeline)==12
    assert len(detail)==72
    assert summary["fully_ready_mtf"]==12
    assert summary["historical_long_candidates"]==0
    assert summary["historical_short_candidates"]==0
    assert set(timeline["Po MTF / surowe"])=={"0/0"}
    assert set(timeline["Wynik"])=={"WAIT"}
    assert len(detail[detail["Przed MTF"]=="LONG"])==0
    assert all(ts.endswith("+00:00") for ts in timeline["Świeca UTC"])
    assert len(timeline["Świeca UTC"].unique())==12


def test_old_selected_end_can_be_reanalysed_without_future_closed_m1_leakage():
    snaps=sample_snapshots()
    latest=snaps["MINUTE"].frame
    early=latest.iloc[:-25]
    a,ad,sm=audit_recent_closed_bars(early,snaps,lookback=10)
    assert len(a)==10
    assert a.iloc[-1]["Świeca UTC"]==early.index[-1].isoformat()
    b,bd,_=audit_recent_closed_bars(latest,snaps,lookback=40)
    subset=b[b["Świeca UTC"].isin(a["Świeca UTC"])]
    assert list(subset["Wynik"])==list(a["Wynik"])
    assert list(subset["Po MTF / surowe"])==list(a["Po MTF / surowe"])
    assert not ad.empty and not bd.empty


def test_missing_mtf_is_not_misreported_as_tradable_signals():
    snaps=sample_snapshots()
    m1=snaps["MINUTE"].frame
    timeline,detail,stats=audit_recent_closed_bars(m1,{},lookback=5)
    assert stats["fully_ready_mtf"]==0
    assert set(timeline["Wynik"])=={"WAIT / MTF NIEZWERYFIKOWANE"}
    assert all(t=="BRAK" for t in timeline["MTF"])


def test_gapped_m1_fails_closed_for_affected_history():
    snaps=sample_snapshots()
    m1=snaps["MINUTE"].frame.drop(snaps["MINUTE"].frame.index[-3])
    timeline,_,summary=audit_recent_closed_bars(m1,snaps,lookback=5)
    assert any("BRAK DANYCH"==x for x in timeline["Wynik"])
    assert summary["historical_long_candidates"]==0


def test_audit_rejects_modified_history_and_invalid_spread():
    snaps=sample_snapshots()
    original=snaps["MINUTE"].frame
    different=original.copy()
    different.loc[different.index[-1],"Close"]=999.0
    with pytest.raises(ValueError):
        audit_recent_closed_bars(different,snaps)
    corrupted=original.copy()
    corrupted.loc[corrupted.index[-1],"Spread"]=-.5
    with pytest.raises(ValueError,match="geometria"):
        audit_recent_closed_bars(corrupted,snaps)
    with pytest.raises(ValueError,match="1–40"):
        audit_recent_closed_bars(original,snaps,lookback=99)


def test_stage_reasons_clear_about_raw_votes_already_filtered_by_risk():
    assert rejection_stage("Zbyt bliski opór")=="OPÓR / WSPARCIE"
    assert rejection_stage("RR po spreadzie poniżej minimum")=="RYZYKO / RR"
    assert rejection_stage("MTF: brak zgodności M5/M15/H1")=="MTF"
    assert rejection_stage("Brak pełnego układu; nie wymuszam wejścia.")=="BRAK FORMACJI / TRENDU"


def test_mtf_asof_shows_actual_closed_bar_and_rejects_old_gaps():
    snaps=sample_snapshots()
    m1=snaps["MINUTE"]
    t=pd.Timestamp(m1.confirmed_utc)-pd.Timedelta(minutes=3)
    views,con=evaluate_timeframes(snaps,asof=t.to_pydatetime())
    for view in views:
        assert view.candle_utc<=t
    assert views[0].candle_utc==t
    bad_snaps=dict(snaps)
    m5=bad_snaps["MINUTE_5"]
    # Still relatively fresh to "now" but too far from the selected
    # M1 candle after historical asof; no longer a valid M5 veto context.
    older=m5.frame.iloc[:-3].copy()
    bad_snaps["MINUTE_5"]=replace(m5,frame=older,
        confirmed_utc=older.index[-1].to_pydatetime())
    bad,consensus=evaluate_timeframes(bad_snaps,asof=m1.confirmed_utc)
    assert consensus=="WAIT"
    assert bad[1].ready is False
    assert "zamkniętej świecy M5" in bad[1].reason


def test_streamlit_exposes_selectable_candle_and_never_queues_historical_paper():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    app=(root/"app.py").read_text("utf-8")
    assert "DLACZEGO BRAK LONG/SHORT? — AUDYT OSTATNICH ŚWIEC M1" in app
    assert "SPRAWDŹ KAŻDĄ ŚWIECĘ I POWODY WAIT" in app
    assert "FOKUS_audyt_6_strategii_M1.csv" in app
    module=(root/"trader"/"signal_audit.py").read_text("utf-8")
    assert "queue_paper" not in module
    assert "broker" not in module.lower().split("from .auto_strategy")[1] or "calls" in module.lower()
