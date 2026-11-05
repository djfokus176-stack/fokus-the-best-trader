"""PAPER settlement: mid barriers, executable bid/ask and adverse slippage."""
import pandas as pd
import pytest
from trader.strategy import simulate_outcome


def bars(open_price,high,low,n=3):
    idx=pd.date_range('2026-11-04',periods=n,freq='min',tz='UTC')
    return pd.DataFrame({
        'Open':[float(open_price)]*n,'High':[float(high)]*n,'Low':[float(low)]*n,
        'Close':[float(open_price)]*n},index=idx)

@pytest.mark.parametrize('side,stop,target,high,low,expected',[
    ('LONG',98,102,102.1,99,1.40),
    ('SHORT',102,98,101,97.9,1.40),
    ('LONG',98,102,101,97.9,-2.60),
    ('SHORT',102,98,102.1,99,-2.60),
])
def test_bid_ask_both_sides_no_slippage(side,stop,target,high,low,expected):
    state,pnl=simulate_outcome(bars(100,high,low),side,100,stop,target,.6,0)
    assert state==('WIN' if expected>0 else 'LOSS')
    assert pnl==expected

@pytest.mark.parametrize('side,stop,target', [('LONG',98,102),('SHORT',102,98)])
def test_intrabar_stop_is_worst_case(side,stop,target):
    state,_=simulate_outcome(bars(100,104,96),side,100,stop,target,.6,0)
    assert state=='LOSS'

@pytest.mark.parametrize('side,stop,target,expected',[
    ('LONG',98,102,0.90),('SHORT',102,98,0.90)])
def test_slippage_on_both_legs(side,stop,target,expected):
    high,low=(103,99) if side=='LONG' else (101,97)
    status,pnl=simulate_outcome(bars(100,high,low),side,100,stop,target,.6,.25)
    assert status=='WIN' and pnl==expected

@pytest.mark.parametrize('side,open_price,stop,target',[
    ('LONG',100,98,102),('SHORT',100,102,98)])
def test_pending_if_no_barrier_touched(side,open_price,stop,target):
    status,pnl=simulate_outcome(bars(open_price,101,99),side,open_price,stop,target,.6,0)
    assert status=='PENDING' and pnl==0

def test_gap_stop_worse_than_target_fill():
    b=bars(100,102,97)
    b.loc[b.index[1],'Open']=97.5
    # A gap on a later bar must not improve an adverse stop fill.
    b.loc[b.index[0],'Low']=99
    b.loc[b.index[0],'High']=101
    status,pnl=simulate_outcome(b,'LONG',100,98,102,.6,0)
    assert status=='LOSS' and pnl==-3.1
