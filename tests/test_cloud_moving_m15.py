"""M15 wicks MUST be from real quotes: never animated or fabricated."""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest

from trader.market import MarketQuote
from trader.cloud_moving_m15 import (
    SAMPLED_KIND, BROKER_KIND, FROM_PRICES,
    update_sampled_m15, broker_forming_m15,assess_moving_m15,
)

NOW=pd.Timestamp("2026-11-16T09:05:10Z")


def quote(when=NOW,mid=7535.0,*,fresh=True,status="TRADEABLE",
          updated=None):
    vendor=when if updated is None else updated
    return MarketQuote(
        epic="US500",environment="DEMO",bid=mid-.3,ask=mid+.3,
        mid=mid,spread=.6,status=status,
        update_utc=vendor.to_pydatetime(),
        received_utc=when.to_pydatetime(),
        delay_seconds=0.,fresh=fresh)


def broker_preview(at=NOW):
    start=at.floor("15min")
    return {"epic":"US500","environment":"DEMO",
            "timeframe":"MINUTE_15","source":FROM_PRICES,
            "time":start+pd.Timedelta(minutes=15),
            "last_tick":start,"Open":7530.,"High":7537.,
            "Low":7529.,"Close":7535.,"bid":7534.7,
            "ask":7535.3,"spread":.6}


def cloud_quote(when=NOW,*,sampled=None,broker=None,
                status="TRADEABLE",fresh=True):
    s={"utc":when.isoformat(),"bid":7534.7,"ask":7535.3}
    if sampled is not None:s["sampled_m15"]=sampled
    if broker is not None:s["forming_m15"]=broker
    return {"epic":"US500","source":"Capital.com DEMO REST",
            "bid":7534.7,"ask":7535.3,"mid":7535.,
            "spread":.6,"broker_status":status,
            "fresh":fresh,"delay_seconds":0.,
            "received_utc":when.isoformat(),
            "broker_update_utc":when.isoformat(),
            "samples":[s]}


def test_actual_quote_changes_extend_high_low_body_without_fake_ticks():
    a=update_sampled_m15(None,quote())
    assert a["kind"]==SAMPLED_KIND
    assert a["open"]==a["high"]==a["low"]==a["close"]==7535.
    b=update_sampled_m15(a,quote(NOW+pd.Timedelta(seconds=5),mid=7538))
    assert (b["open"],b["high"],b["low"],b["close"])==(
        7535.,7538.,7535.,7538.)
    c=update_sampled_m15(b,quote(NOW+pd.Timedelta(seconds=10),mid=7532))
    assert (c["open"],c["high"],c["low"],c["close"])==(
        7535.,7538.,7532.,7532.)
    assert c["samples"]==3
    repeated=update_sampled_m15(c,quote(NOW+pd.Timedelta(seconds=10),mid=7532))
    assert repeated==c
    assert repeated["samples"]==3


def test_new_quarter_resets_bar_and_never_invents_continuous_wick():
    old=update_sampled_m15(None,quote(NOW,7535))
    rolled=update_sampled_m15(old,quote(
        pd.Timestamp("2026-11-16T09:15:01Z"),7540))
    assert rolled["bar_open_utc"]=="2026-11-16T09:15:00+00:00"
    assert rolled["open"]==rolled["high"]==rolled["low"]==7540.
    assert rolled["samples"]==1


def test_stale_or_cross_quarter_market_quote_never_accepted():
    assert update_sampled_m15(None,quote(fresh=False)) is None
    assert update_sampled_m15(None,quote(status="CLOSED")) is None
    stale=quote(NOW,7535,updated=NOW-pd.Timedelta(seconds=40))
    assert update_sampled_m15(None,stale) is None
    old_quarter=quote(
        pd.Timestamp("2026-11-16T09:15:03Z"),7535,
        updated=pd.Timestamp("2026-11-16T09:14:59Z"))
    assert update_sampled_m15(None,old_quarter) is None


def test_broker_ohlc_is_real_only_if_current_m15_and_source_valid():
    b=broker_forming_m15(broker_preview(),now=NOW)
    assert b["kind"]==BROKER_KIND
    assert b["high"]==7537.
    assert b["bar_close_utc"]=="2026-11-16T09:15:00+00:00"
    with pytest.raises(ValueError):
        broker_forming_m15(broker_preview(),
                           now=NOW+pd.Timedelta(minutes=15))
    fake=broker_preview();fake["epic"]="GER40"
    with pytest.raises(ValueError):broker_forming_m15(fake,now=NOW)
    corrupted=broker_preview();corrupted["High"]=7520.
    with pytest.raises(ValueError):broker_forming_m15(corrupted,now=NOW)


def test_ui_prefers_real_sampled_wicks_and_never_touches_closed_bars():
    samples=update_sampled_m15(None,quote(NOW,7535))
    samples=update_sampled_m15(
        samples,quote(NOW+pd.Timedelta(seconds=5),7538))
    sample_time=NOW+pd.Timedelta(seconds=5)
    broker=broker_forming_m15(broker_preview(),now=NOW)
    row=cloud_quote(sample_time,sampled=samples,broker=broker)
    visible=assess_moving_m15(
        row,now=sample_time,last_closed_utc=NOW.floor("15min"))
    assert visible["visible"] is True
    assert visible["kind"]==SAMPLED_KIND
    assert visible["bar"]["high"]==7538.
    assert visible["bar"]["at"]==pd.Timestamp("2026-11-16T09:15:00Z")
    assert visible["broker_bar"]["kind"]==BROKER_KIND
    assert visible["incomplete"] is True
    assert visible["trade_permission"]=="WAIT"
    assert visible["missing_extremes_possible"] is True
    assert not assess_moving_m15(
        row,now=sample_time,
        last_closed_utc=pd.Timestamp("2026-11-16T09:15:00Z"))["visible"]


def test_quoted_market_closed_or_stale_no_moving_candle():
    sample=update_sampled_m15(None,quote())
    row=cloud_quote(sampled=sample)
    assert assess_moving_m15(
        row,now=NOW+pd.Timedelta(seconds=13))["visible"] is False
    closed=cloud_quote(sampled=sample,status="CLOSED",fresh=False)
    assert not assess_moving_m15(closed,now=NOW)["visible"]
    missing=cloud_quote()
    assert not assess_moving_m15(missing,now=NOW)["visible"]


def test_broker_m15_fallback_when_no_sampled_bar():
    broker=broker_forming_m15(broker_preview(),now=NOW)
    row=cloud_quote(broker=broker)
    out=assess_moving_m15(row,now=NOW)
    assert out["visible"] is True
    assert out["kind"]==BROKER_KIND
    assert out["missing_extremes_possible"] is False


def test_ui_draws_actual_provisional_candlestick_not_only_a_diamond():
    code=Path("trader/cloud_paper_terminal.py").read_text()
    assert "assess_moving_m15(" in code
    assert "x=[live[\"at\"]]" in code
    assert "high=[live[\"high\"]]" in code
    assert "low=[live[\"low\"]]" in code
    assert "name=(\"🕯️ M15 LIVE" in code
    assert 'WICK-M15-v1' in code
    assert '@st.fragment(run_every="5s")' in code
    assert "queue_paper(" not in code
    assert "CapitalReadOnly(" not in code


def test_sampler_and_ui_have_no_broker_orders_or_3f_paper_input():
    worker=Path("trader/cloud_scalp_quotes.py").read_text()
    ui=Path("trader/cloud_paper_terminal.py").read_text()
    wicks=Path("trader/cloud_moving_m15.py").read_text()
    assert "update_sampled_m15(" in worker
    assert 'forming_m15' in worker
    assert "queue_paper(" not in worker
    assert "queue_paper(" not in wicks
    assert "queue_paper(" not in ui
    assert "read" in wicks.lower()
