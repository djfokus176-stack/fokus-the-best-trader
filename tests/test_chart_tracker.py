import pandas as pd
import plotly.graph_objects as go
from trader.chart_tracker import annotate_scan
from trader.strategy import Decision

def test_chart_bot_marks_actual_last_candle_and_status():
    idx=pd.date_range("2026-11-05",periods=200,freq="min",tz="UTC")
    frame=pd.DataFrame({"Close":[5000+i*.1 for i in range(200)]},index=idx)
    fig=annotate_scan(go.Figure(),frame,Decision("WAIT","DRUGA FALA","test"),
                      {"scan_no":3,"new_candle":True},bar_limit=80)
    assert len(fig.data)==1
    assert fig.data[0].x[0]==idx[-1]
    assert fig.data[0].y[0]==frame.Close.iloc[-1]
    assert "NOWA ŚWIECA" in fig.data[0].hovertemplate
    assert len(fig.layout.shapes)>=2
    assert fig.layout.xaxis.range[0]==idx[-80]

def test_chart_marker_stays_on_real_candle_not_future():
    idx=pd.date_range("2026-11-05",periods=10,freq="min",tz="UTC")
    frame=pd.DataFrame({"Close":[5000.0]*10},index=idx)
    fig=annotate_scan(go.Figure(),frame,Decision("SHORT","EMA TREND","test"),
                      {"scan_no":5,"new_candle":False})
    assert fig.data[0].x[0]==idx[-1]
    assert fig.data[0].text==("🤖 BOT",)
