import pandas as pd
import numpy as np
from trader.wave_intelligence2 import (run_wave_abcd,_trade,_seek,_context,
                                        M15_UNSUPPORTED_MIN,VERSION)


def setup():
    ts=[]
    for d in pd.bdate_range('2026-09-01',periods=14):
        first=pd.Timestamp(str(d.date())+' 09:45',tz='America/New_York')
        ts.extend(pd.date_range(first,periods=26,freq='15min'))
    idx=pd.DatetimeIndex(ts).tz_convert('UTC')
    f=pd.DataFrame({'Open':100.,'High':101.,'Low':99.,'Close':100.,
                    'Spread':0.6},index=idx)
    base=len(f)-26
    # Pivot at 08, becomes known on closed 10; cannot be traded at 08.
    f.iloc[base+8,f.columns.get_loc('High')]=110.
    f.iloc[base+11,f.columns.get_loc('Close')]=97.
    f.iloc[base+11,f.columns.get_loc('Low')]=96.
    # A real OHLC bar must contain its OPEN, CLOSE and wick extremes.
    f.iloc[base+12,f.columns.get_loc('Open')]=97.5
    f.iloc[base+12,f.columns.get_loc('Low')]=96.8
    f.iloc[base+12,f.columns.get_loc('High')]=98.1
    f.iloc[base+12,f.columns.get_loc('Close')]=97.2
    f.iloc[base+13,f.columns.get_loc('Close')]=112.
    f.iloc[base+13,f.columns.get_loc('High')]=113.
    f.iloc[base+14,f.columns.get_loc('Close')]=113.
    f.iloc[base+14,f.columns.get_loc('High')]=114.
    anchors=pd.DataFrame([dict(event_id='third-peak-1',
        signal_utc=f.index[base+10], pivot_utc=f.index[base+8],
        wave_count=3,confirmation='RAW',direction='SHORT',
        bos_level=98.,wave_structure='RISING PEAKS',pattern='TRIPLE TOP',
        regime='RANGE')])
    return f,anchors,base


def test_funnel_asof_a_b_c_d_e_and_opposite_breakout_direction():
    f,anchors,base=setup()
    rank,details,meta=run_wave_abcd(f,anchors=anchors,split=.70)
    assert meta['anchors']==1 and meta['proven_edge'] is False
    d={r.variant:r for _,r in details.iterrows()}
    assert d['A_RAW'].signal_utc==f.index[base+10]
    assert d['B_BOS'].signal_utc==f.index[base+11]
    assert d['C_BOS_RETEST'].signal_utc==f.index[base+12]
    assert d['D_BREAKOUT_HOLD'].signal_utc==f.index[base+14]
    assert d['D_BREAKOUT_HOLD'].direction=='LONG'
    assert d['E_WAIT'].status=='WAIT'
    assert pd.isna(d['E_WAIT'].pnl_pts)
    assert d['A_RAW'].entry_utc==f.index[base+11]
    assert d['A_RAW'].anchor_id=='third-peak-1'
    assert d['A_RAW'].strategy_version==VERSION
    assert all(details.loc[details.variant!='E_WAIT','triggered'])
    assert len(rank)==2*2*5*(1+1) # 2 periods, 2 sides, 5 variants, 2026 + summary


def test_no_lookahead_bos_is_not_backdated():
    f,anchors,base=setup()
    sig=_seek(f,base+10,'SHORT',98.,110.,2.)
    assert sig['B_BOS']==base+11
    assert sig['C_BOS_RETEST']==base+12
    assert sig['D_BREAKOUT_HOLD']==base+14
    partial=f.iloc[:base+11].copy()
    assert _seek(partial,base+10,'SHORT',98.,110.,2.)['B_BOS'] is None
    partial=f.iloc[:base+13].copy()
    assert _seek(partial,base+10,'SHORT',98.,110.,2.)['C_BOS_RETEST']==base+12


def test_no_fake_10_20_minute_backtest_from_m15():
    f,anchors,base=setup()
    for m in M15_UNSUPPORTED_MIN:
        try:run_wave_abcd(f,anchors=anchors,hold_minutes=m)
        except ValueError:pass
        else:raise AssertionError('should refuse unsupported timeframe')


def test_gap_invalidates_future_exit_instead_of_pricing_unknown():
    f,anchors,base=setup()
    g=f.drop(f.index[base+13]); i=base+11
    result=_trade(g,i,'SHORT',2.,rr=1.5,minutes=120,spread=.6,slippage=.25)
    assert result['status'] in ('INVALIDATED_GAP','INCOMPLETE_HORIZON','SL','TP')
    # Make all future bars flat and remove one intervening candle.
    h=f.copy(); h.loc[h.index[base+13:base+20],['Open','High','Low','Close']]=[100,101,99,100]
    h=h.drop(h.index[base+14]); loc=base+12
    r=_trade(h,loc,'SHORT',2.,rr=1.5,minutes=120,spread=.6,slippage=.25)
    assert r['status']=='INVALIDATED_GAP' and r['pnl_pts'] is None


def test_quote_mode_and_explicit_spread_model():
    f,anchors,base=setup()
    r=_trade(f,base+10,'LONG',2.,rr=1.5,minutes=30,spread=2.,slippage=.25)
    assert r['execution']=='LAST_KNOWN_CLOSE_SPREAD_MODEL'
    for side,shift in [('Bid',-.3),('Ask',.3)]:
        for field in ['Open','High','Low','Close']:
            f[side+field]=f[field]+shift
    q=_trade(f,base+10,'LONG',2.,rr=1.5,minutes=30,spread=2.,slippage=.25)
    assert q['execution']=='BID_ASK_OHLC_MODEL'
    assert pd.notna(q['pnl_pts']) and pd.notna(q['entry_executable'])


def test_wait_never_claimed_winning_strategy():
    f,anchors,base=setup()
    rank,log,_=run_wave_abcd(f,anchors=anchors)
    rows=rank[(rank.variant=='E_WAIT')&(rank.year.isna())]
    assert (rows.closed==0).all()
    assert rows.net_pts.isna().all()
    assert (rows.status=='BRAK DANYCH').all()
