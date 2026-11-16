"""CLOUD M1/M2/M5/M15/H1: chart-only and explicitly never trading input."""
from pathlib import Path
import pandas as pd
import pytest

from trader.cloud_chart_timeframes import (
    CHART_RESOLUTIONS, source_resolution,
    closed_chart_frame, sampled_chart_bar,
)

NOW=pd.Timestamp("2026-11-16T09:05:15Z")


def minute_frame(stamps):
    idx=pd.DatetimeIndex(pd.to_datetime(stamps,utc=True))
    opens=[7500.+i for i in range(len(idx))]
    return pd.DataFrame({
        "Open":opens,
        "High":[x+1 for x in opens],
        "Low":[x-1 for x in opens],
        "Close":[x+.5 for x in opens],
        "Spread":[.6]*len(idx),
    },index=idx)


def quote_record(now=NOW, mids=None, *,status="TRADEABLE",fresh=True):
    mids=mids if mids is not None else [
        (now-pd.Timedelta(seconds=10),7500.),
        (now-pd.Timedelta(seconds=5),7503.),
        (now,7501.),
    ]
    return {"epic":"US500","source":"Capital.com DEMO REST",
            "bid":mids[-1][1]-.3,"ask":mids[-1][1]+.3,
            "mid":mids[-1][1],"spread":.6,
            "broker_status":status,"fresh":fresh,
            "delay_seconds":0,
            "received_utc":now.isoformat(),
            "broker_update_utc":now.isoformat(),
            "samples":[{"utc":stamp.isoformat(),
                        "bid":m-.3,"ask":m+.3} for stamp,m in mids]}


def test_resolution_catalog_only_chart_m2_is_synthetic_from_m1():
    assert tuple(CHART_RESOLUTIONS)==("M1","M2","M5","M15","H1")
    assert source_resolution("M2")=="MINUTE"
    assert source_resolution("M1")=="MINUTE"
    assert source_resolution("M5")=="MINUTE_5"
    assert source_resolution("M15")=="MINUTE_15"
    assert source_resolution("H1")=="HOUR"
    with pytest.raises(ValueError):
        source_resolution("MINUTE_2")


def test_closed_m2_from_exact_two_consecutive_utc_close_labeled_m1():
    data=minute_frame(["2026-11-16 09:00:00+00:00",
                       "2026-11-16 09:01:00+00:00",
                       "2026-11-16 09:02:00+00:00",
                       "2026-11-16 09:03:00+00:00",
                       "2026-11-16 09:04:00+00:00"])
    result=closed_chart_frame(data,"M2")
    assert list(result.index)==[
        pd.Timestamp("2026-11-16T09:02:00Z"),
        pd.Timestamp("2026-11-16T09:04:00Z")]
    assert result.iloc[0]["Open"]==data.iloc[1]["Open"]
    assert result.iloc[0]["High"]==data.iloc[1:3]["High"].max()
    assert result.iloc[0]["Low"]==data.iloc[1:3]["Low"].min()
    assert result.iloc[0]["Close"]==data.iloc[2]["Close"]
    assert result.iloc[-1]["Spread"]==.6


def test_missing_m1_or_one_m1_never_fabricates_closed_m2():
    data=minute_frame(["2026-11-16 09:01:00+00:00",
                       "2026-11-16 09:04:00+00:00"])
    result=closed_chart_frame(data,"M2")
    assert result.empty
    lone=minute_frame(["2026-11-16 09:01:00+00:00"])
    assert closed_chart_frame(lone,"M2").empty


@pytest.mark.parametrize("tf",["M1","M2","M5","H1"])
def test_real_observed_quote_samples_move_wicks_and_close(tf):
    row=quote_record()
    result=sampled_chart_bar(row,tf,now=NOW)
    assert result["visible"] is True
    bar=result["bar"]
    assert bar["open"]==7500.
    assert bar["high"]==7503.
    assert bar["low"]==7500.
    assert bar["close"]==7501.
    assert result["incomplete"] is True
    assert result["trade_permission"]=="WAIT"
    assert result["missing_extremes_possible"] is True
    # Future isn't used for any forecast or PAPER execution.
    assert "order" not in str(result).lower()


def test_m1_rollover_clears_prior_minute_samples():
    now=pd.Timestamp("2026-11-16T09:06:01Z")
    old=[(pd.Timestamp("2026-11-16T09:05:50Z"),7501.),
         (pd.Timestamp("2026-11-16T09:06:01Z"),7504.)]
    row=quote_record(now,mids=old)
    out=sampled_chart_bar(row,"M1",now=now)
    assert out["visible"]
    assert out["bar"]["samples"]==1
    assert out["bar"]["open"]==out["bar"]["close"]==7504.
    assert out["bar"]["bar_close_utc"]=="2026-11-16T09:07:00+00:00"


@pytest.mark.parametrize("status,fresh,advance",[
    ("CLOSED",False,0),("TRADEABLE",False,0),
    ("TRADEABLE",True,25),
])
def test_old_market_data_does_not_animate_bar(status,fresh,advance):
    row=quote_record(status=status,fresh=fresh)
    out=sampled_chart_bar(
        row,"M5",now=NOW+pd.Timedelta(seconds=advance))
    assert not out["visible"]


def test_duplicate_timestamp_does_not_create_fake_new_wick():
    mids=[(NOW-pd.Timedelta(seconds=5),7500.),
          (NOW-pd.Timedelta(seconds=5),7507.),
          (NOW,7501.)]
    row=quote_record(mids=mids)
    out=sampled_chart_bar(row,"M5",now=NOW)
    assert out["bar"]["samples"]==2
    assert out["bar"]["high"]==7507.  # Same timestamp replaces old quote.


def test_no_chart_preview_on_already_archived_close():
    row=quote_record()
    until=pd.Timestamp("2026-11-16T09:10:00Z")
    assert not sampled_chart_bar(
        row,"M5",now=NOW,last_closed_utc=until)["visible"]


def test_cloud_selection_cannot_change_auto_or_paper_scan_config():
    app=Path("app.py").read_text(encoding="utf-8")
    chart=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf-8")
    assert "render_cloud_terminal(secret,tf)" in app
    assert 'key="cloud_price_chart_interval"' in chart
    assert 'choice=st.selectbox(' in chart
    assert 'source_resolution(choice)' in chart
    assert 'cache.get("choice")!=choice' in chart
    assert "queue_paper(" not in chart
    assert "evaluate_auto(" not in chart
    assert "client.market_quote(" not in chart
