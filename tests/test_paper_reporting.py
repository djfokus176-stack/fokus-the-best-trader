from trader.paper_reporting import daily_weekly
from trader.paper_lifecycle import queue_paper,progress_paper,ensure_tables
from trader.storage import connect
from trader.strategy import Decision
import pandas as pd


def test_daily_weekly_separate_demo_and_open(tmp_path):
    con=connect(tmp_path/"report.sqlite3")
    ensure_tables(con)
    when=pd.Timestamp("2026-11-05T13:00:00Z")
    signal=Decision("LONG","EMA TREND","test",100,98,102)
    tid=queue_paper(con,"US500","Capital.com DEMO REST","MINUTE",
                    signal,when,.6,slippage=0)
    day,week,summary=daily_weekly(con,epic="US500")
    assert day.empty and week.empty and summary["liczba"]==0
    idx=[when+pd.Timedelta(minutes=1)]
    candle=pd.DataFrame({"Open":[100.],"High":[103.],"Low":[99.],"Close":[102.]},index=idx)
    progress_paper(con,candle,"US500","Capital.com DEMO REST","MINUTE")
    day,week,summary=daily_weekly(con,epic="US500")
    assert summary["liczba"]==1
    assert summary["suma_pkt"]==1.4
    assert summary["TP"]==1
    assert summary["win_rate_pct"]==100.
    assert day.iloc[0]["okres"]=="2026-11-05"
    assert "W" in week.iloc[0]["okres"]
    assert daily_weekly(con,source="Capital.com LIVE REST")[2]["liczba"]==0


def test_drawdown_includes_zero_and_negative_results(tmp_path):
    from trader.paper_reporting import _metrics
    frame=pd.DataFrame([
      dict(trade_id="A",closed_utc="2026-11-05T11:00:00Z",status="CLOSED_SL",pnl_pts=-2.6,
           entry_mid=100.,stop_mid=98.,setup_spread=.6,slippage=0.),
      dict(trade_id="B",closed_utc="2026-11-05T12:00:00Z",status="CLOSED_TP",pnl_pts=1.4,
           entry_mid=100.,stop_mid=98.,setup_spread=.6,slippage=0.)])
    m=_metrics(frame)
    assert m["liczba"]==2
    assert m["max_drawdown_pkt"]==2.6
    assert m["suma_pkt"]==-1.2
