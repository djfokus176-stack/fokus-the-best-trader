"""A–E cloud replay is research-only, after explicit local data validation."""
import pandas as pd
import pytest

from test_wave_intelligence2 import setup
from trader.cloud_wave_ae_replay import research_capital_ae, DECISION


def test_capital_replay_uses_existing_engine_without_trading():
    frame,_,_=setup()
    before=frame.copy(deep=True)
    result=research_capital_ae(frame)
    meta=result["meta"]
    assert meta["source"]=="Capital.com DEMO REST"
    assert meta["stored_candles"]==len(frame)
    assert meta["mode"]=="LAST_KNOWN_CLOSE_SPREAD_MODEL"
    assert meta["trade_permission"]=="WAIT"
    assert meta["calibrated_probability"] is False
    assert meta["new_independent_oos"] is False
    assert meta["fully_comparable_to_dukascopy"] is False
    assert meta["reason"]==DECISION
    assert set(result["summary"].variant)=={
        "A_RAW","B_BOS","C_BOS_RETEST","D_BREAKOUT_HOLD","E_WAIT"}
    assert len(result["summary"])==20  # 2 periods x 2 directions x A–E
    assert result["summary"]["year"].isna().all() is True
    assert result["summary"].loc[
        result["summary"].variant=="E_WAIT","net_pts"].isna().all()
    assert frame.equals(before)


def test_capital_replay_rejects_missing_spreads_broker_and_small_samples():
    frame,_,_=setup()
    with pytest.raises(ValueError,match="tylko archiwum"):
        research_capital_ae(frame,source="Unknown LIVE")
    with pytest.raises(ValueError,match="210"):
        research_capital_ae(frame.head(209))
    with pytest.raises(ValueError,match="spready"):
        research_capital_ae(frame.drop(columns=["Spread"]))
    negative=frame.copy()
    negative.iloc[-1,negative.columns.get_loc("Spread")]=-1
    with pytest.raises(ValueError,match="spready"):
        research_capital_ae(negative)
    duplicated=pd.concat([frame,frame.iloc[-1:]])
    with pytest.raises(ValueError,match="unikalne"):
        research_capital_ae(duplicated)
    with pytest.raises(ValueError,match="zalozenia"):
        research_capital_ae(frame,hold_minutes=10)


def test_capital_replay_does_not_claim_bidask_even_if_spreads_present():
    frame,_,_=setup()
    audit=research_capital_ae(frame,slippage=.25,rr=1.5)
    assert audit["meta"]["mode"]!="BID_ASK_OHLC_MODEL"
    assert audit["meta"]["slippage_per_side"]==.25
    assert audit["meta"]["rr"]==1.5
    assert audit["meta"]["trade_permission"]=="WAIT"
