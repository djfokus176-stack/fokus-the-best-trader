"""MTF gate: no fake higher timeframe, no stale or future data, no new signals."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pandas as pd
from trader.mtf import TIMEFRAMES, trend_from_closed, evaluate_timeframes, filter_mtf_decision
from trader.strategy import Decision


def example(tf, anchor, price_up=True):
    steps={"MINUTE":60,"MINUTE_5":300,"MINUTE_15":900,"HOUR":3600}
    delta=steps[tf]
    # Include a confirmed bar timestamp that isn't ahead of the M1 anchor.
    epoch=int(anchor.timestamp())
    last=datetime.fromtimestamp((epoch//delta)*delta,tz=timezone.utc)
    idx=pd.date_range(end=last,periods=90,freq=f"{delta}s",tz="UTC")
    series=[5000+(i if price_up else -i)*.5 for i in range(90)]
    df=pd.DataFrame({"Open":series,"High":[v+2 for v in series],
       "Low":[v-2 for v in series],"Close":series},index=idx)
    return SimpleNamespace(frame=df,source="Capital.com DEMO REST",epic="US500",
        resolution=tf,confirmed_utc=last,good=True,reason="OK",age_seconds=1)


def test_trend_only_reads_closed_input():
    anchor=datetime(2026,11,4,21,00,tzinfo=timezone.utc)
    s=example("MINUTE",anchor)
    assert trend_from_closed(s.frame)=="UP"
    altered=s.frame.copy();altered.iloc[-1, altered.columns.get_loc("Close")]=9999
    assert trend_from_closed(s.frame.iloc[:-1])==trend_from_closed(altered.iloc[:-1])


def test_mtf_missing_or_stale_means_wait():
    anchor=datetime(2026,11,4,21,00,tzinfo=timezone.utc)
    all_frames={tf:example(tf,anchor) for tf in TIMEFRAMES}
    rows,signal=evaluate_timeframes(all_frames,now=anchor+timedelta(seconds=20))
    assert signal=="UP" and len(rows)==4
    all_frames.pop("HOUR")
    rows,signal=evaluate_timeframes(all_frames,now=anchor+timedelta(seconds=20))
    assert signal=="WAIT"
    d=Decision("LONG","EMA TREND","test",entry=5100,stop=5095,target=5110)
    gated,_=filter_mtf_decision(d,all_frames,now=anchor+timedelta(seconds=20))
    assert gated.action=="WAIT" and gated.entry is None


def test_mtf_never_changes_wait_to_long():
    anchor=datetime(2026,11,4,21,00,tzinfo=timezone.utc)
    snaps={tf:example(tf,anchor) for tf in TIMEFRAMES}
    w=Decision("WAIT","DRUGA FALA","no setup")
    result,_=filter_mtf_decision(w,snaps,now=anchor+timedelta(seconds=15))
    assert result.action=="WAIT"


def test_no_foreign_instrument():
    anchor=datetime(2026,11,4,21,00,tzinfo=timezone.utc)
    snaps={tf:example(tf,anchor) for tf in TIMEFRAMES}
    snaps["MINUTE_5"].epic="OTHER"
    rows,con=evaluate_timeframes(snaps,now=anchor+timedelta(seconds=10))
    assert con=="WAIT"
    assert not rows[1].ready
