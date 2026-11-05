"""CSV replay must mark last CLOSED candle, not a live or future bar."""
from io import StringIO
from datetime import timedelta
import pandas as pd
import plotly.graph_objects as go
from trader.csv_data import read_ohlc_csv
from trader.market import evaluate_snapshot
from trader.chart_tracker import annotate_scan
from trader.strategy import Decision


def test_real_csv_parsing_and_last_closed_bot_marker():
    idx=pd.date_range('2026-11-04T13:00:00Z',periods=90,freq='min')
    p=[5000+i*.12 for i in range(90)]
    df=pd.DataFrame({'Time':idx.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'Open':p,'High':[v+1 for v in p],'Low':[v-1 for v in p],
        'Close':p,'Spread':[.4]*90})
    csv=StringIO(df.to_csv(index=False))
    parsed=read_ohlc_csv(csv)
    assert len(parsed)==90
    assert parsed.Spread.iloc[-1]==.4
    now=idx[-1].to_pydatetime()+timedelta(seconds=15)
    snap=evaluate_snapshot(parsed,'US500','MINUTE',now=now,
        source='CSV NAUKA (NIE LIVE)')
    assert len(snap.frame)==89
    assert snap.frame.index[-1]==idx[-2]  # forming tail excluded
    fig=annotate_scan(go.Figure(),snap.frame,
        Decision('WAIT','EMA TREND','replay'),
        {'scan_no':2,'new_candle':False},
        source=snap.source,bar_limit=60)
    marker=fig.data[0]
    assert marker.x[0]==idx[-2]
    assert marker.y[0]==parsed.Close.iloc[-2]
    assert 'REPLAY' in marker.text[0]
    assert 'CSV' in marker.hovertemplate

def test_csv_uses_default_spread_only_when_missing():
    idx=pd.date_range('2026-11-04T13:00:00Z',periods=75,freq='min')
    frame=pd.DataFrame({'Time':idx.astype(str),
       'Open':[100.]*75,'High':[101.]*75,
       'Low':[99.]*75,'Close':[100.]*75})
    out=read_ohlc_csv(StringIO(frame.to_csv(index=False)))
    assert (out.Spread==.6).all()
