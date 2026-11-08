"""Owner activation on GitHub: paid GPT opt-in is bounded and DEMO-only."""
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
from trader.auto_ai import review_closed_candle


def _snapshot():
    at=datetime(2026,11,9,13,0,tzinfo=timezone.utc)
    frame=pd.DataFrame({"Open":[100,100.1],"High":[100.2,100.3],
                        "Low":[99.8,99.9],"Close":[100.1,100.2]},
                       index=pd.date_range(end=at,periods=2,freq="min",tz="UTC"))
    return SimpleNamespace(source="Capital.com DEMO REST",epic="US500",
                           resolution="MINUTE",confirmed_utc=at,frame=frame,spread=.5)


def _decision():
    return SimpleNamespace(action="WAIT",strategy="AUTO — 6 STRATEGII",
                           reason="No consensus",entry=None,stop=None,target=None,rr=None)


def test_paid_gpt_wait_receives_only_official_fed_bea_dates_and_coverage_status():
    calls=[]
    def fake(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text="WAIT, kalendarz może być niepełny.",
                               usage=SimpleNamespace(input_tokens=1000,output_tokens=240))
    watch={"asof_utc":"2026-11-09T12:00:00+00:00",
           "coverage":"PARTIAL_OFFICIAL_CORE",
           "sources":{"FED_FOMC":{"status":"LIVE_OFFICIAL"},
                      "BEA":{"status":"UNAVAILABLE"}},
           "events":[
                {"data_utc":"2026-11-09T19:00:00+00:00",
                 "wydarzenie":"FED: FOMC","source":"FED_OFFICIAL_LIVE"},
                {"data_utc":"2026-11-12T13:30:00+00:00",
                 "wydarzenie":"BEA: GDP","source":"BEA_OFFICIAL_LIVE"},
                {"data_utc":"2026-11-12T15:00:00+00:00",
                 "wydarzenie":"MALICIOUS","source":"UNTRUSTED"}]}
    state=review_closed_candle({},_snapshot(),_decision(),[],[],[],
        env={"FOKUS_AUTO_AI_ENABLED":"true","OPENAI_API_KEY":"dummy",
             "FOKUS_AUTO_AI_INCLUDE_WAIT":"true","FOKUS_AUTO_AI_DAILY_LIMIT":"6",
             "FOKUS_AUTO_AI_MONTHLY_LIMIT":"60"},
        now=datetime(2026,11,9,13,0,tzinfo=timezone.utc),
        macro_context=watch,call=fake)
    assert state["status"]=="SUCCESS"
    assert len(calls)==1
    data=json.loads(calls[0]["input"])
    calendar=data["official_macro_calendar"]
    assert calendar["coverage"]=="PARTIAL_OFFICIAL_CORE"
    assert calendar["source_status"]["BEA"]=="UNAVAILABLE"
    assert len(calendar["events_next_14_days"])==2
    assert "MALICIOUS" not in str(calendar)
    assert "kalendarz" in calls[0]["instructions"].lower()
    assert calls[0]["model"]=="gpt-5.4-mini"


def test_paid_gpt_deduplicates_and_respects_zero_daily_budget():
    calls=[]
    e={"FOKUS_AUTO_AI_ENABLED":"true","OPENAI_API_KEY":"dummy",
       "FOKUS_AUTO_AI_INCLUDE_WAIT":"true","FOKUS_AUTO_AI_DAILY_LIMIT":"0",
       "FOKUS_AUTO_AI_MONTHLY_LIMIT":"60"}
    state=review_closed_candle({},_snapshot(),_decision(),[],[],[],
        env=e,call=lambda **kwargs: calls.append(kwargs))
    assert state["status"]=="CALL_CAP_REACHED" and calls==[]


def test_worker_optin_and_defaults_require_server_secret():
    workflow=(Path(__file__).resolve().parents[1]/
              ".github/workflows/paper-v4-scan.yml").read_text("utf-8")
    assert "FOKUS_AUTO_AI_ENABLED: ${{ vars.FOKUS_AUTO_AI_ENABLED || 'true' }}" in workflow
    assert "FOKUS_AUTO_AI_DAILY_LIMIT: ${{ vars.FOKUS_AUTO_AI_DAILY_LIMIT || '6' }}" in workflow
    assert "FOKUS_AUTO_AI_MONTHLY_LIMIT: ${{ vars.FOKUS_AUTO_AI_MONTHLY_LIMIT || '60' }}" in workflow
    assert "FOKUS_AUTO_AI_INCLUDE_WAIT: ${{ vars.FOKUS_AUTO_AI_INCLUDE_WAIT || 'true' }}" in workflow
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in workflow
    assert "CAPITAL_PASSWORD: ${{ secrets.CAPITAL_PASSWORD }}" in workflow
    assert "AUTO_GPT=NOT_READY" in workflow
    assert "python -m trader.paper_proof" in workflow


def test_automated_gpt_stays_read_only():
    code=(Path(__file__).resolve().parents[1]/"trader/auto_ai.py").read_text("utf-8")
    assert "client.responses.create" in code
    assert "/positions" not in code
    assert "place_order" not in code
