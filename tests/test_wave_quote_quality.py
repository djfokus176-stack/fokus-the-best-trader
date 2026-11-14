"""Dukascopy quote-cross forensics: never replace bad prices with guesses."""
import json
import sys

import pandas as pd
import pytest

from scripts.wave_quote_qc import (
    CrossedQuoteError, inspect_and_quarantine_crossed,
)
from scripts.prepare_wave_m15 import merge_bid_ask, main as merge_main

PERIODS=(
    ("2021-11-11","2022-11-11"),
    ("2022-11-11","2023-11-11"),
    ("2023-11-11","2024-11-11"),
    ("2024-11-11","2025-11-11"),
    ("2025-11-11","2026-11-11"),
)


def fixture_folder(folder, *, n_per_period=300, bad=False, big=False,
                   extra_crosses=0):
    for y,(start,end) in enumerate(PERIODS):
        times=pd.date_range(start+"T14:30:00Z",
                            periods=n_per_period,freq="15min")
        for side in ("bid","ask"):
            base=4000.+y*400.+(.6 if side=="ask" else 0.)
            rows=pd.DataFrame({
                "timestamp":times.astype("int64")//1_000_000,
                "open":base,"high":base+2.,"low":base-1.,
                "close":base+1.,
            })
            if y==2 and side=="ask" and bad:
                # This is an entire OHLC quote from the wrong side,
                # internally valid and therefore caught by CROSS-QC,
                # not by per-side OHLC quality checks.
                rows.loc[55,["open","high","low","close"]]=(
                    [base-5. if big else base-.8,
                     base-3. if big else base+1.2,
                     base-6. if big else base-1.8,
                     base-4. if big else base+.2])
                for k in range(extra_crosses):
                    z=56+k
                    rows.loc[z,["open","high","low","close"]]=(
                        [base-1.2,base+.8,base-2.2,base-.2])
            rows.to_csv(folder/
               f"usa500_m15_{side}_{start}_{end}.csv",index=False)


def test_strict_default_rejects_and_has_counts_by_year(tmp_path):
    fixture_folder(tmp_path,bad=True)
    with pytest.raises(CrossedQuoteError,match="ASK < BID") as caught:
        merge_bid_ask(tmp_path)
    q=caught.value.report
    assert q["input_rows"]==1500
    assert q["crossed_rows"]==1
    assert q["crossed_by_year"]=={"2023":1}
    assert q["crossed_by_field"]["close"]==1
    assert q["decision"]=="REJECT_ALL_INPUT_UNTIL_REVIEWED"
    assert "2023" in q["examples_first_30"][0]["candle_open_utc"]


def test_explicit_small_cross_quarantine_creates_missing_15min_not_synthetic(tmp_path):
    fixture_folder(tmp_path,bad=True)
    merged,meta=merge_bid_ask(
        tmp_path,crossed_max_fraction=.001,crossed_max_points=2.)
    qc=meta["quote_quality"]
    assert len(merged)==1499
    assert qc["crossed_rows"]==1
    assert qc["quarantined_rows"]==1
    assert qc["retained_rows"]==1499
    assert qc["decision"]=="QUARANTINE_EXPLICIT_SMALL_FRACTION"
    assert qc["no_forward_fill"]
    assert (merged[["AskOpen","AskHigh","AskLow","AskClose"]].to_numpy()>=
            merged[["BidOpen","BidHigh","BidLow","BidClose"]].to_numpy()).all()
    # The omitted bad quote must create a REAL missing 15min slot.
    times=merged.Time
    assert (times.diff()==pd.Timedelta(minutes=30)).sum()==1


def test_over_budget_or_large_cross_aborts_even_with_opt_in(tmp_path):
    fixture_folder(tmp_path,bad=True,extra_crosses=7)
    with pytest.raises(CrossedQuoteError) as caught:
        merge_bid_ask(
            tmp_path,crossed_max_fraction=.001,crossed_max_points=2.)
    assert caught.value.report["crossed_rows"]>=8
    assert caught.value.report["decision"]=="REJECT_ALL_INPUT_UNTIL_REVIEWED"
    fixture_folder(tmp_path,bad=True,big=True)
    with pytest.raises(CrossedQuoteError) as caught:
        merge_bid_ask(
            tmp_path,crossed_max_fraction=.001,crossed_max_points=2.)
    assert caught.value.report["worst_cross_points"]>2.


def test_qc_rejects_unreasonable_policy_even_with_clean_quotes(tmp_path):
    fixture_folder(tmp_path)
    clean,_=merge_bid_ask(tmp_path)
    assert len(clean)==1500
    with pytest.raises(ValueError,match="0..1%"):
        merge_bid_ask(tmp_path,crossed_max_fraction=.05)
    with pytest.raises(ValueError,match="0..5"):
        merge_bid_ask(tmp_path,crossed_max_points=20.)


def test_cli_writes_quality_json_before_failing_on_real_integrity(tmp_path,monkeypatch):
    fixture_folder(tmp_path,bad=True)
    out=tmp_path/"full.csv"
    monkeypatch.setattr(sys,"argv",[
        "prepare_wave_m15.py","--folder",str(tmp_path),
        "--out",str(out)])
    with pytest.raises(SystemExit) as ex:
        merge_main()
    assert ex.value.code==2
    qc=json.loads((tmp_path/"full.quality.json").read_text("utf-8"))
    assert qc["crossed_rows"]==1
    assert not out.exists()


def test_cli_success_writes_provenance_and_qc(tmp_path,monkeypatch):
    fixture_folder(tmp_path,bad=True)
    out=tmp_path/"full.csv"
    monkeypatch.setattr(sys,"argv",[
        "prepare_wave_m15.py","--folder",str(tmp_path),
        "--out",str(out),
        "--crossed-max-fraction","0.001",
        "--crossed-max-points","2"])
    merge_main()
    assert out.exists()
    assert json.loads((tmp_path/"full.quality.json").read_text("utf-8"))["quarantined_rows"]==1
    assert json.loads((tmp_path/"full.audit.json").read_text("utf-8"))["quote_quality"]["crossed_rows"]==1
