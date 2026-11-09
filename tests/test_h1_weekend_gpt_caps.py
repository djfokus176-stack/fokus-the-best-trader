"""Regression: normal CFD weekend is not a broken H1 feed; bad bars remain blocked."""
from datetime import datetime, timezone
from types import SimpleNamespace
import pandas as pd

from trader.market import evaluate_snapshot
from trader.auto_ai import review_closed_candle


def make_market(tf, before="2026-11-06 21:00:00+00:00",
                after="2026-11-08 23:00:00+00:00", extra_gap=False):
    step={"HOUR":"h","MINUTE":"min"}[tf]
    first=pd.date_range(end=before,periods=80,freq=step,tz="UTC")
    last=pd.date_range(start=after,periods=10,freq=step,tz="UTC")
    dates=first.append(last)
    if extra_gap:
        # Add an anomalous midweek data gap INSIDE the last 20 H1 bars.
        # Missing market hour after Sunday reopening must still be caught.
        last=last.delete([3,4,5,6,7])  # six-hour unexplained interval
        dates=first.append(last)
    frame=pd.DataFrame({"Open":[100.0]*len(dates),
                        "High":[101.0]*len(dates),
                        "Low":[99.0]*len(dates),
                        "Close":[100.0]*len(dates),
                        "Spread":[0.5]*len(dates)},index=dates)
    current=dates[-1].to_pydatetime()
    return frame, current


def test_weekend_gap_is_valid_only_for_h1_and_no_fake_bar_is_inserted():
    frame,now=make_market("HOUR")
    result=evaluate_snapshot(frame,"US500","HOUR",now=now)
    assert result.good, result.reason
    assert len(result.frame)==len(frame)-1
    assert pd.Timestamp("2026-11-07 12:00:00+00:00") not in result.frame.index


def test_weekend_gap_never_unblocks_minute_candles():
    frame,now=make_market("MINUTE")
    result=evaluate_snapshot(frame,"US500","MINUTE",now=now)
    assert not result.good
    assert "duże luki" in result.reason


def test_bad_midweek_gap_remains_blocked_in_h1():
    frame,now=make_market("HOUR",extra_gap=True)
    result=evaluate_snapshot(frame,"US500","HOUR",now=now)
    assert not result.good
    assert "duże luki" in result.reason


def test_not_an_expected_weekend_gap_is_blocked():
    frame,now=make_market("HOUR",
        before="2026-11-05 21:00:00+00:00",
        after="2026-11-08 23:00:00+00:00")
    result=evaluate_snapshot(frame,"US500","HOUR",now=now)
    assert not result.good
    assert "duże luki" in result.reason


def test_broker_crossed_quotes_still_block_even_on_weekend_hour():
    frame,now=make_market("HOUR")
    frame.attrs["quarantined_candles"]=({
       "candle_utc":frame.index[-1].isoformat(),
       "issue":"Close: bid > ask"},)
    result=evaluate_snapshot(frame,"US500","HOUR",now=now)
    assert not result.good
    assert "DANE_WADLIWE" in result.reason


def test_preexisting_24_200_variables_cannot_exceed_hard_6_60():
    calls=[]
    def call(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text="Tylko komentarz PAPER.",
              usage=SimpleNamespace(input_tokens=80,output_tokens=20))
    env={"FOKUS_AUTO_AI_ENABLED":"true","OPENAI_API_KEY":"mock",
         "FOKUS_AUTO_AI_DAILY_LIMIT":"24",
         "FOKUS_AUTO_AI_MONTHLY_LIMIT":"200"}
    frame,_=make_market("MINUTE",before="2026-11-09 11:00:00+00:00",
                       after="2026-11-09 11:01:00+00:00")
    state={}
    for i in range(7):
        now=pd.Timestamp("2026-11-09 13:00:00+00:00")+pd.Timedelta(minutes=i)
        snap=SimpleNamespace(source="Capital.com DEMO REST",epic="US500",
            resolution="MINUTE",confirmed_utc=now.to_pydatetime(),
            frame=frame.tail(8),spread=0.5)
        dec=SimpleNamespace(action="LONG",strategy="EMA TREND",reason="test",
            entry=100.0,stop=99.0,target=102.0,rr=2.0)
        state=review_closed_candle(state,snap,dec,[],[],[],env=env,
                                   now=now.to_pydatetime(),call=call)
    assert len(calls)==6
    assert state["status"]=="CALL_CAP_REACHED"
    assert state["daily_calls"]==6
    assert state["monthly_calls"]==6
