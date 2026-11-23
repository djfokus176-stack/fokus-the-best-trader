"""Optional auto AI is disabled by default and bounded, with no real API calls."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pandas as pd
from trader.auto_ai import review_closed_candle


def snapshot(minute=0):
    at=datetime(2026,11,5,12,0,tzinfo=timezone.utc)+timedelta(minutes=minute)
    frame=pd.DataFrame({
        "Open":[99.,100.], "High":[101.,102.],
        "Low":[98.,99.], "Close":[100.,101.]
    },index=pd.date_range(end=pd.Timestamp(at),periods=2,freq="min"))
    return SimpleNamespace(source="Capital.com DEMO REST",epic="US500",
        resolution="MINUTE",confirmed_utc=at,frame=frame,spread=.5)


def verdict(direction="LONG"):
    return SimpleNamespace(action=direction,strategy="EMA TREND",
        reason="Synthetic reason",entry=100,stop=99,target=102,rr=2)


def answer(**kwargs):
    return SimpleNamespace(output_text="Rozważ scenariusz WAIT i ryzyka.",
        usage=SimpleNamespace(input_tokens=450,output_tokens=115))


def test_no_opt_in_never_calls_paid_api():
    count=[]
    def bad(**kwargs):
        count.append(1)
        raise AssertionError("paid API must not run")
    result=review_closed_candle({},snapshot(),verdict(),[],[],[],
        env={"OPENAI_API_KEY":"abc"},call=bad)
    assert not result and not count


def test_enabled_deduplicates_closed_candle_and_logs_usage():
    seen=[]
    def fake(**kwargs):
        seen.append(kwargs)
        return answer()
    env={"FOKUS_AUTO_AI_ENABLED":"true","OPENAI_API_KEY":"testing",
         "FOKUS_AUTO_AI_DAILY_LIMIT":"2",
         "FOKUS_AUTO_AI_MONTHLY_LIMIT":"2"}
    state=review_closed_candle({},snapshot(),verdict(),[],[],[],
        env=env,call=fake)
    state=review_closed_candle(state,snapshot(),verdict(),[],[],[],
        env=env,call=fake)
    assert len(seen)==1
    assert seen[0]["max_output_tokens"]==900
    assert state["status"]=="SUCCESS"
    assert state["last_input_tokens"]==450
    assert state["daily_calls"]==1
    state=review_closed_candle(state,snapshot(5),verdict(),[],[],[],
        env=env,call=fake)
    assert len(seen)==2
    state=review_closed_candle(state,snapshot(10),verdict(),[],[],[],
        env=env,call=fake)
    assert len(seen)==2 and state["status"]=="CALL_CAP_REACHED"


def test_wait_skip_without_explicit_opt_in():
    seen=[]
    env={"FOKUS_AUTO_AI_ENABLED":"true","OPENAI_API_KEY":"testing"}
    state=review_closed_candle({},snapshot(),verdict("WAIT"),[],[],[],
        env=env,call=lambda **kw: seen.append(kw))
    assert state["status"]=="SKIP_WAIT"
    assert not seen


def test_failed_call_counts_against_call_cap_and_does_not_crash():
    def fail(**kwargs):
        raise TimeoutError("redacted secret?")
    env={"FOKUS_AUTO_AI_ENABLED":"true","OPENAI_API_KEY":"testing",
         "FOKUS_AUTO_AI_DAILY_LIMIT":"1"}
    state=review_closed_candle({},snapshot(),verdict(),[],[],[],
        env=env,call=fail)
    assert state["daily_calls"]==1
    assert state["status"]=="API_ERROR_TimeoutError"
    assert "redacted" not in str(state)
    state=review_closed_candle(state,snapshot(5),verdict(),[],[],[],
        env=env,call=fail)
    assert state["status"]=="CALL_CAP_REACHED"


def test_non_demo_is_never_sent_to_ai():
    snap=snapshot()
    snap.source="Capital.com LIVE REST"
    state=review_closed_candle({},snap,verdict(),[],[],[],
        env={"FOKUS_AUTO_AI_ENABLED":"true","OPENAI_API_KEY":"testing"},
        call=lambda **kw: (_ for _ in ()).throw(AssertionError("non DEMO")))
    assert state["status"]=="SKIP_NON_DEMO_FEED"


def test_raw_long_candidate_in_wait_gets_bounded_paid_research_review():
    seen=[]
    def fake(**kwargs):
        seen.append(kwargs)
        return answer()
    env={"FOKUS_AUTO_AI_ENABLED":"true","OPENAI_API_KEY":"test",
         "FOKUS_AUTO_AI_DAILY_LIMIT":"1",
         "FOKUS_AUTO_AI_MONTHLY_LIMIT":"1"}
    raw=[{"Strategia":"EMA TREND","Setup OHLC":"LONG",
          "Po filtrze MTF":"WAIT","RR":1.7,"Powód":"MTF not ready"}]
    state=review_closed_candle({},snapshot(),verdict("WAIT"),raw,[],
        ["INCOMPLETE_MTF"],env=env,call=fake)
    assert state["status"]=="SUCCESS"
    assert len(seen)==1
    assert '"unapproved_research_candidate_only": true' in seen[0]["input"]
    assert seen[0]["model"]=="gpt-5.4-mini"
    state=review_closed_candle(state,snapshot(5),verdict("WAIT"),raw,[],
        ["INCOMPLETE_MTF"],env=env,call=fake)
    assert state["status"]=="CALL_CAP_REACHED"
    assert len(seen)==1
