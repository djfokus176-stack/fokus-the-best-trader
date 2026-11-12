"""Research only. Synthetic CLOSED M15 NY sessions, DST and no lookahead."""
import numpy as np
import pandas as pd
import pytest

from trader.wave_reversal import detect_waves,validate_closed_m15
from trader.wave_reversal_eval import (analyze_wave_m15,_probes,
                                        _filter_ok,_net_result,read_wave_m15_csv)


def history(days=12, patterned_last=True):
    dates=pd.bdate_range("2026-10-23",periods=days)
    index=[]
    for day in dates:
        first=pd.Timestamp(str(day.date())+" 09:45",tz="America/New_York")
        index.extend(pd.date_range(first,periods=26,freq="15min"))
    idx=pd.DatetimeIndex(index).tz_convert("UTC")
    df=pd.DataFrame({
        "Open":np.full(len(idx),100.),
        "High":np.full(len(idx),102.),
        "Low":np.full(len(idx),99.),
        "Close":np.full(len(idx),100.),
    },index=idx)
    if patterned_last:
        b=len(df)-26
        for i,price in ((3,110.),(11,110.2),(19,110.1)):
            df.iloc[b+i,df.columns.get_loc("High")]=price
        for i,price in ((7,95.),(15,96.)):
            df.iloc[b+i,df.columns.get_loc("Low")]=price
        df.iloc[b+22,df.columns.get_loc("Close")]=95.5
        df.iloc[b+22,df.columns.get_loc("Low")]=94.5
    return df


def test_peak3_is_only_known_after_right_confirming_closes():
    df=history()
    until=history().iloc[:-5]  # last session through index 20, peak3 + 1 only
    earlier=detect_waves(until)
    assert not ((earlier.wave_count==3)&(earlier.direction=="SHORT")).any()
    confirmed=detect_waves(df.iloc[:-4])  # through index 21, peak3 confirmed
    found=confirmed[(confirmed.wave_count==3)&
                    (confirmed.direction=="SHORT") &
                    (confirmed.confirmation=="RAW")]
    assert len(found)==1
    assert found.iloc[0].pattern=="TRIPLE TOP"
    assert found.iloc[0].signal_utc==df.index[-5]
    assert found.iloc[0].pivot_utc==df.index[-7]
    # A later bar cannot rewrite or erase the past RAW event.
    changed=df.copy()
    changed.loc[changed.index[-1],"High"]=999
    a=detect_waves(changed)
    assert (a.loc[a.signal_utc<=df.index[-5],"event_id"].tolist()
            ==confirmed.event_id.tolist())


def test_bos_is_only_after_actual_closed_support_break():
    df=history()
    before=detect_waves(df.iloc[:-4])
    assert not ((before.confirmation=="BOS")&
                (before.wave_count==3)).any()
    after=detect_waves(df.iloc[:-3])
    bos=after[(after.wave_count==3)&
              (after.confirmation=="BOS") &
              (after.direction=="SHORT")]
    assert len(bos)==1
    assert bos.iloc[0].signal_utc==df.index[-4]
    assert bos.iloc[0].bos_level==96.
    assert not (after.loc[after.confirmation=="BOS"].signal_utc>
                df.index[-4]).any()


def test_missing_volume_does_not_fabricate_vwap_or_filter():
    df=history()
    out=detect_waves(df)
    assert not out.empty
    assert not out.volume_available.any()
    assert not out.vwap_available.any()
    assert out.vwap_filter.isna().all()
    assert out.volume_filter.isna().all()
    example=out.iloc[-1].to_dict()
    assert not _filter_ok(example,"VWAP")
    assert not _filter_ok(example,"VOLUME")
    assert not _filter_ok(example,"EMA+RSI+ATR+VWAP+VOLUME")
    assert _filter_ok(example,"BASE")


def test_with_declared_volume_vwap_is_allowed_but_not_claimed_real():
    df=history()
    df["Volume"]=np.arange(len(df))+100
    out=detect_waves(df)
    assert out.vwap_available.any()
    assert out.volume_available.all()
    assert out.vwap_filter.dropna().isin([True,False]).all()


def test_dst_session_is_ny_local_not_hardcoded_utc():
    assert pd.Timestamp("2026-01-12 09:45",
            tz="America/New_York").tz_convert("UTC").strftime("%H:%M")=="14:45"
    assert pd.Timestamp("2026-07-13 09:45",
            tz="America/New_York").tz_convert("UTC").strftime("%H:%M")=="13:45"
    df=history()
    assert validate_closed_m15(df) is None
    bad=df.copy()
    bad.index=bad.index+pd.Timedelta(minutes=1)
    with pytest.raises(ValueError,match="siatce"):
        validate_closed_m15(bad)


def test_gap_invalidates_horizon_not_fabricate_hit():
    df=history()
    i=len(df)-12  # only 11 M15 bars remain in this NY session
    probes=_probes(df,i,"SHORT")
    assert len(probes)==9
    # At this time 4h cannot fit before 16 ET; must be missing.
    assert all(hit is None for hours,pct,hit,base in probes if hours==4)
    dropped=df.drop(df.index[i+2])
    probes2=_probes(dropped,i,"SHORT")
    assert all(hit is None for _,_,hit,_ in probes2)


def test_bidask_is_consumed_and_price_only_is_explicit_model():
    df=history()
    loc=len(df)-20
    raw=_net_result(df,loc,"LONG",3,assumed_spread=1.5,slippage=.25)
    assert raw["execution"]=="SPREAD_FIXED_ASSUMPTION"
    df["Spread"]=.7
    hist=_net_result(df,loc,"SHORT",3,assumed_spread=1.5,slippage=.25)
    assert hist["execution"]=="SPREAD_M15_CLOSE_MODEL"
    df["BidOpen"]=df.Open-.3
    df["BidHigh"]=df.High-.3
    df["BidLow"]=df.Low-.3
    df["BidClose"]=df.Close-.3
    df["AskOpen"]=df.Open+.3
    df["AskHigh"]=df.High+.3
    df["AskLow"]=df.Low+.3
    df["AskClose"]=df.Close+.3
    quote=_net_result(df,loc,"SHORT",3,assumed_spread=1.5,slippage=.25)
    assert quote["execution"]=="BID_ASK_OHLC"
    assert quote["net"] is not None
    df.iloc[loc+1,df.columns.get_loc("AskOpen")]=0
    bad=_net_result(df,loc,"SHORT",3,assumed_spread=1.5,slippage=.25)
    assert bad["status"]=="INVALIDATED_QUOTES"


def test_reports_contain_all_untested_variants_with_explicit_no_data():
    df=history()
    ranking,events,annual,meta=analyze_wave_m15(df)
    assert set(ranking.okres)=={"WCZESNIEJSZE","POZNIEJSZE"}
    assert set(ranking.direction)=={"LONG","SHORT"}
    assert set(ranking.wave_count)=={2,3,4,5}
    assert set(ranking.horizon_h)=={1,2,4}
    assert set(ranking.target_pct)=={.25,.5,1.}
    assert (ranking.loc[ranking.n==0,"status"]=="BRAK DANYCH").all()
    assert meta["research_only"] is True
    assert meta["verified_edge"] is False
    assert not (ranking.status=="ZWERYFIKOWANA").any()
    assert (events["strategy_version"]=="wave_reversal_research_v1").all()


def test_late_future_change_cannot_change_earlier_signal_or_filters():
    df=history()
    old=detect_waves(df.iloc[:-4]).iloc[-1]
    later=df.copy()
    later.iloc[-1,later.columns.get_loc("Close")]=101
    later.iloc[-1,later.columns.get_loc("High")]=999
    events=detect_waves(later)
    same=events.loc[events.event_id==old.event_id].iloc[0]
    for key in ("pattern","wave_count","direction","bos_level",
                "ema_filter","rsi_filter","atr_filter","vwap_filter"):
        if pd.isna(old[key]):
            assert pd.isna(same[key])
        else:
            assert old[key]==same[key]


def test_csv_open_clock_is_explicitly_shifted_and_never_silently_assumed():
    import io
    frame=history()
    raw=frame.reset_index().rename(columns={"index":"Time"})
    raw["Time"]=raw["Time"]-pd.Timedelta(minutes=15)
    binary=raw.to_csv(index=False).encode()
    shifted=read_wave_m15_csv(io.BytesIO(binary),timestamp_convention="open")
    assert shifted.index.equals(frame.index)
    with pytest.raises(ValueError,match="konwencj"):
        read_wave_m15_csv(io.BytesIO(binary),timestamp_convention="unknown")


def test_partial_bidask_rejected_without_replacing_it_with_fake_spread():
    import io
    frame=history()
    frame["BidOpen"]=frame.Open-0.3
    rows=frame.reset_index().rename(columns={"index":"Time"})
    with pytest.raises(ValueError,match="pełne 8"):
        read_wave_m15_csv(io.BytesIO(
            rows.to_csv(index=False).encode()))


def test_wave_structure_is_present_in_every_closed_bar_signal():
    df=history()
    events=detect_waves(df)
    assert set(events.wave_structure).issubset({
        "RISING PEAKS","FALLING PEAKS","RISING TROUGHS",
        "FALLING TROUGHS","FLAT PEAKS","FLAT TROUGHS","MIXED WAVES"})
