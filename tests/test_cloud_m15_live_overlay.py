"""Cloud M15 may overlay ONLY fresh REST MID, without new candles or fills."""
from pathlib import Path
import pandas as pd
import pytest
from trader.cloud_m15_live_overlay import (
    cloud_quote_overlay, m15_cache_due,closed_m15_lag,
)

NOW=pd.Timestamp("2026-11-16T08:25:00Z")
SOURCE="Capital.com DEMO REST"


def record(status="TRADEABLE",fresh=True,delay=0.0,at=NOW):
    return {"epic":"US500","source":SOURCE,"bid":7539.10,"ask":7539.70,
            "mid":7539.40,"spread":.60,"broker_status":status,
            "fresh":fresh,"delay_seconds":delay,
            "received_utc":at.isoformat(),"broker_update_utc":at.isoformat(),
            "samples":[
               {"utc":(at-pd.Timedelta(seconds=10)).isoformat(),
                "bid":7539.0,"ask":7539.6},
               {"utc":at.isoformat(),"bid":7539.1,"ask":7539.7}]}


def test_new_tradeable_quote_is_visible_on_m15_overlay_not_a_tick():
    info=cloud_quote_overlay(record(),now=NOW)
    assert info["visible"] is True
    assert info["mid"]==7539.4
    assert info["bid"]==7539.1
    assert info["ask"]==7539.7
    assert len(info["points"])==2
    assert info["points"][-1]["time"]==NOW
    assert info["not_tick_data"] is True
    assert info["trade_permission"]=="WAIT"


@pytest.mark.parametrize("kwargs",[
    {"at":NOW-pd.Timedelta(seconds=13)},
    {"status":"CLOSED"},
    {"status":"TRADEABLE","fresh":False},
    {"status":"TRADEABLE","delay":4.0},
])
def test_never_draw_aged_closed_or_delayed_quote(kwargs):
    info=cloud_quote_overlay(record(**kwargs),now=NOW)
    assert info["visible"] is False
    assert info["points"]==[]
    assert "mid" not in info


def test_missing_record_and_bad_quote_are_explicitly_unknown():
    missing=cloud_quote_overlay(None,now=NOW)
    assert missing["visible"] is False
    assert missing["broker_status"]=="UNKNOWN"
    damaged=record()
    damaged["ask"]=7538.
    with pytest.raises(ValueError,match="inconsistent"):
        cloud_quote_overlay(damaged,now=NOW)


def test_old_future_duplicate_samples_removed_not_synthetic_candles():
    quote=record()
    quote["samples"]=[
        {"utc":(NOW-pd.Timedelta(seconds=121)).isoformat(),"bid":1.,"ask":2.},
        {"utc":(NOW-pd.Timedelta(seconds=5)).isoformat(),"bid":7539.1,"ask":7539.7},
        {"utc":(NOW-pd.Timedelta(seconds=5)).isoformat(),"bid":7539.1,"ask":7539.7},
        {"utc":(NOW+pd.Timedelta(seconds=6)).isoformat(),"bid":7539.1,"ask":7539.7},
    ]
    result=cloud_quote_overlay(quote,now=NOW)
    assert result["visible"]
    assert len(result["points"])==2  # one old-enough sample + current
    assert result["points"][-1]["time"]==NOW


def test_m15_archive_fetched_at_most_once_per_minute_per_browser():
    frame=pd.DataFrame()
    cache={"url":"https://project.supabase.co","fetched_utc":NOW.isoformat(),
           "frame":frame,"payload":{},"version":55}
    assert m15_cache_due(None,now=NOW)
    assert not m15_cache_due(cache,now=NOW+pd.Timedelta(seconds=5))
    assert not m15_cache_due(cache,now=NOW+pd.Timedelta(seconds=59))
    assert m15_cache_due(cache,now=NOW+pd.Timedelta(seconds=60))
    assert m15_cache_due(cache,now=NOW-pd.Timedelta(seconds=1))
    with pytest.raises(ValueError):
        m15_cache_due(cache,now="2026-11-16T08:25:00")


def test_age_of_m15_is_not_necessarily_worker_failure():
    idx=pd.date_range("2026-11-16T08:00:00Z",periods=2,freq="15min")
    df=pd.DataFrame({"Close":[100,101]},index=idx)
    assert closed_m15_lag(df,now=NOW)==10
    assert closed_m15_lag(pd.DataFrame(),now=NOW) is None


def test_owner_chart_has_independent_quote_poll_and_close_only_candles():
    code=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf-8")
    assert '@st.fragment(run_every="5s")' in code
    assert 'remote.fetch_live_quote("US500")' in code
    assert 'remote.fetch_candles("US500",resolution,limit=180)' in code
    assert 'frame=closed_chart_frame(original,choice)' in code
    assert 'cache.get("choice")!=choice' in code
    # Quote fetched ONCE then shared by both the 5s MID overlay and the
    # separate broker M1 preview; a second request is not necessary.
    assert 'quote_record=remote.fetch_live_quote("US500")' in code
    assert 'cloud_quote_overlay(quote_record,now=quote_now)' in code
    assert 'assess_cloud_forming_m1(quote_record,now=quote_now)' in code
    assert '"_fokus_cloud_chart_cache_v3"' in code
    assert "if overlay[\"visible\"]:" in code
    assert "annotate_paper_history(candles,chart_paper" in code
    assert "queue_paper(" not in code
    assert "CapitalReadOnly(" not in code
