"""Dukascopy five-year BID+ASK raw M15 import keeps timestamps and provenance."""
import pandas as pd
import pytest
from scripts.prepare_wave_m15 import merge_bid_ask


PERIODS=(
    ("2021-11-11","2022-11-11"),
    ("2022-11-11","2023-11-11"),
    ("2023-11-11","2024-11-11"),
    ("2024-11-11","2025-11-11"),
    ("2025-11-11","2026-11-11"),
)


def sample_files(tmp_path, mismatch=False):
    for i,(start,end) in enumerate(PERIODS):
        stamp=int(pd.Timestamp(start+"T14:30:00Z").timestamp()*1000)
        for side in ("bid","ask"):
            if mismatch and i==4 and side=="ask":
                stamp2=stamp+15*60*1000
            else:
                stamp2=stamp
            price=4200+100*i+(0.6 if side=="ask" else 0.)
            frame=pd.DataFrame({
                "timestamp":[stamp2],
                "open":[price],"high":[price+2],
                "low":[price-1],"close":[price+1],
                "volume":[100.+i]})
            frame.to_csv(tmp_path/
                f"usa500_m15_{side}_{start}_{end}.csv",index=False)


def test_combines_bidask_without_interpolation_and_shifts_open_to_close(tmp_path):
    sample_files(tmp_path)
    df,meta=merge_bid_ask(tmp_path)
    assert len(df)==5 and len(meta["bid_sha256"])==5
    assert df.Time.iloc[0]==pd.Timestamp("2021-11-11T14:45:00Z")
    assert df.Open.iloc[0]==4200.3
    assert df.BidOpen.iloc[0]==4200.
    assert df.AskOpen.iloc[0]==4200.6
    assert abs(df.Spread.iloc[0]-.6)<1e-8
    assert df.Volume.iloc[0]==100.
    assert meta["n_timestamp_mismatches"]==0
    assert not meta["holidays_verified"]
    assert meta["source_timestamp"].endswith("OPEN UTC")
    assert meta["no_gap_filling"]


def test_reject_missing_ask_or_missing_year(tmp_path):
    sample_files(tmp_path,mismatch=True)
    with pytest.raises(ValueError,match="nie zgadzają"):
        merge_bid_ask(tmp_path)
    (tmp_path/"usa500_m15_ask_2025-11-11_2026-11-11.csv").unlink()
    with pytest.raises(ValueError,match="5 rocznych"):
        merge_bid_ask(tmp_path)


def test_reject_corrupted_quotes_or_duplicate_times(tmp_path):
    sample_files(tmp_path)
    ask=tmp_path/"usa500_m15_ask_2021-11-11_2022-11-11.csv"
    frame=pd.read_csv(ask)
    frame.loc[0,"open"]=100.
    frame.to_csv(ask,index=False)
    with pytest.raises(ValueError,match="ASK < BID"):
        merge_bid_ask(tmp_path)
    sample_files(tmp_path)
    bid=tmp_path/"usa500_m15_bid_2021-11-11_2022-11-11.csv"
    frame=pd.read_csv(bid)
    pd.concat([frame,frame]).to_csv(bid,index=False)
    with pytest.raises(ValueError,match="zduplikowane"):
        merge_bid_ask(tmp_path)
