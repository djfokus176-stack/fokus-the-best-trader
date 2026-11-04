"""Spread on the closed signal bar differs from the last forming quote."""
from datetime import timedelta
import pandas as pd
from trader.market import evaluate_snapshot
from trader.strategy import Decision
from trader.storage import archive, recent, recent_scan_decisions, connect


def prices(spread_at_last=2.5, spread_on_closed=0.6):
    idx=pd.date_range('2026-11-04T13:00:00Z', periods=80, freq='min')
    df=pd.DataFrame({
        'Open':[100.0]*80,'High':[101.0]*80,'Low':[99.0]*80,
        'Close':[100.0]*80, 'Spread':[0.6]*80},index=idx)
    df.iloc[-2,df.columns.get_loc('Spread')]=spread_on_closed
    df.iloc[-1,df.columns.get_loc('Spread')]=spread_at_last
    return df


def test_spread_associated_with_closed_candle_and_quote_guard():
    bars=prices()
    now=bars.index[-1].to_pydatetime()+timedelta(seconds=10)
    snap=evaluate_snapshot(bars,'US500','MINUTE',now,max_spread=3)
    assert snap.spread==0.6
    assert snap.quote_spread==2.5
    assert snap.good
    guarded=evaluate_snapshot(bars,'US500','MINUTE',now,max_spread=2)
    assert not guarded.good and 'Bieżący spread' in guarded.reason


def test_closed_signal_spread_exceeding_limit_blocks():
    bars=prices(0.4,2.5)
    now=bars.index[-1].to_pydatetime()+timedelta(seconds=10)
    guarded=evaluate_snapshot(bars,'US500','MINUTE',now,max_spread=2)
    assert guarded.spread==2.5
    assert guarded.quote_spread==0.4
    assert not guarded.good and 'Spread zamkniętej świecy' in guarded.reason


def test_wait_not_counted_in_trade_archive(tmp_path):
    con=connect(tmp_path/'paper.sqlite3')
    t='2026-11-04T13:00:00Z'
    args=('US500','Capital.com DEMO REST','MINUTE')
    for i in range(3):
        assert archive(con,str(i),t,*args,Decision('WAIT','DRUGA FALA','blocked'))
    assert len(recent(con))==0
    assert len(recent_scan_decisions(con))==3
    assert archive(con,'trade-1',t,*args,Decision('LONG','EMA TREND','paper',100,99,102,1.5),spread=.6)
    assert len(recent(con))==1
    assert len(recent_scan_decisions(con))==3
