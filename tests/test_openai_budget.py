"""Check actual argument ceilings and token usage reporting without a paid API call."""
from types import ModuleType,SimpleNamespace
import sys
from trader.assistant import answer_ai

class FakeOpenAI:
    calls=[]
    def __init__(self, api_key,timeout):
        self.timeout=timeout
        self.responses=self
    def create(self,**kwargs):
        FakeOpenAI.calls.append((self.timeout,kwargs))
        return SimpleNamespace(output_text="Rynek konsoliduje.",
            usage=SimpleNamespace(input_tokens=310,output_tokens=120),
            status="completed")


def test_api_budget_medium_high_and_usage(monkeypatch):
    fake=ModuleType('openai')
    fake.OpenAI=FakeOpenAI
    monkeypatch.setitem(sys.modules,"openai",fake)
    FakeOpenAI.calls=[]
    medium=answer_ai("test-key","gpt-5.4","Test",{"OHLC":[]},effort="medium")
    high=answer_ai("test-key","gpt-5.4","Test",{"OHLC":[]},effort="high")
    assert len(FakeOpenAI.calls)==2
    assert FakeOpenAI.calls[0][0]==45
    assert FakeOpenAI.calls[0][1]["max_output_tokens"]==2400
    assert FakeOpenAI.calls[0][1]["reasoning"]["effort"]=="medium"
    assert FakeOpenAI.calls[1][0]==65
    assert FakeOpenAI.calls[1][1]["max_output_tokens"]==4200
    assert "310 tokenów wejścia" in medium
    assert "120 tokenów wyjścia" in high
    assert "nie jest wyliczenie kwoty" in high


def test_error_if_no_key_is_not_fake_response():
    result=answer_ai("","gpt-5.4","Test",{},effort="medium")
    assert "Brak OPENAI_API_KEY" in result
