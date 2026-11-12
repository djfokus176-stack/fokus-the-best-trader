import pandas as pd
import pytest
from trader.wave_intelligence2 import run_wave_abcd
from trader.wave_intelligence2_stats import (wave_excursion_audit,feature_audit,
    hour_ranking,wilson_95,timeframe_coverage)
from test_wave_intelligence2 import setup


def test_no_spurious_probabilities_on_short_future():
    frame,anchors,base=setup()
    _,log,_=run_wave_abcd(frame,anchors=anchors)
    rank,detail=wave_excursion_audit(frame,log)
    assert len(detail)==15
    assert set(detail.threshold_pct)=={.25,.5,1.,1.5,2.}
    assert set(detail.horizon_min)=={60,120,240}
    assert all(~detail.valid[detail.horizon_min==240])
    assert all(detail.loc[~detail.valid,'flat'].isna())
    assert all(r.n==r.up+r.down-r.both+r.flat for r in rank.itertuples() if r.n)
    assert all(0<=x<=100 for x in rank.up_pct.dropna())


def test_factual_feature_and_hour_ranking_only_closed_trades():
    frame,anchors,base=setup()
    _,log,_=run_wave_abcd(frame,anchors=anchors)
    features=feature_audit(log)
    assert not features.empty
    assert set(features.period)=={'POZNIEJSZE'}
    assert 'false_break_at_pivot' in set(features.feature)
    h=hour_ranking(log)
    assert set(h.direction)=={'SHORT','LONG'}
    assert h.n.sum() <= 4  # only four candidate variant trades
    cov=timeframe_coverage()
    assert 'BRAK DANYCH' in cov[cov.interwal=='M1'].status.iloc[0]
    assert 'BADANIE' in cov[cov.interwal=='M15'].status.iloc[0]


def test_wilson_is_bounded_and_unseen_variants_missing():
    assert wilson_95(0,0)==(None,None)
    assert wilson_95(0,10)[0]==0
    assert wilson_95(10,10)[1]==100
    frame,anchors,base=setup()
    rank,log,_=run_wave_abcd(frame,anchors=anchors)
    assert rank[(rank.variant=='E_WAIT')&(rank.year.isna())].net_pts.isna().all()


def test_grid_does_not_invent_m15_10min_or_20min_outcomes():
    from trader.wave_intelligence2_stats import same_entries_exit_grid
    frame,anchors,base=setup()
    _,log,meta=run_wave_abcd(frame,anchors=anchors)
    rank,events=same_entries_exit_grid(frame,log,split_cutoff=meta["oos_cutoff"])
    assert set(events.rr_tp)=={1.,1.5,2.,3.}
    assert set(events.holding_min)=={10,20,30,45,60,120}
    assert (events.loc[events.holding_min.isin([10,20]),"status"]==
            "BRAK DANYCH M15").all()
    for variant,g in events.groupby("variant"):
        assert g.groupby(["rr_tp","holding_min"]).anchor_id.apply(tuple).nunique()==1
    assert (rank[rank.holding_min.isin([10,20])].scored==0).all()
