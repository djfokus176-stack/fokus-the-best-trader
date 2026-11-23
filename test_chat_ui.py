from trader.chat_ui import append_message,renderable_history,preview_context
import pytest

def test_ai_response_survives_reruns():
    history=[]
    history=append_message(history,"user","Sprawdź M1")
    history=append_message(history,"assistant","Rynek konsoliduje się.","2026-11-05T01:00:00Z")
    for _ in range(3):
        rendered=renderable_history(history)
        assert len(rendered)==2
        assert rendered[-1]["content"]=="Rynek konsoliduje się."

def test_bounds_and_roles():
    h=[]
    for i in range(50):
        h=append_message(h,"assistant",str(i),max_messages=16)
    assert len(h)==16
    with pytest.raises(ValueError):
        append_message(h,"system","internal")
    with pytest.raises(ValueError):
        append_message(h,"assistant","   ")

def test_context_preview_never_contains_secret():
    p={"instrument":"US500","last_closed_utc":"2026-11-05Z",
       "decision":"WAIT","last_12_closed_candles":[1],
       "OPENAI_API_KEY":"PRIVATE-KEY"}
    x=preview_context(p)
    assert x["n_candles"]==1
    assert "PRIVATE-KEY" not in str(x)
