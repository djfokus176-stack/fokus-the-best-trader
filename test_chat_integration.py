"""Regression: GPT reply is retained after Streamlit app rerun, no real paid API."""
from pathlib import Path
from streamlit.testing.v1 import AppTest
from trader.market import CapitalReadOnly
from tests.test_master_integration import fake_candles

APP=str(Path(__file__).resolve().parents[1]/"app.py")

def test_ai_chat_reply_survives_full_rerun(monkeypatch,tmp_path):
    monkeypatch.setenv("APP_AUTH_MODE","password")
    monkeypatch.setenv("APP_ACCESS_PASSWORD","isolated-ai-test-password-2026")
    monkeypatch.setenv("CAPITAL_API_KEY","mock-demo")
    monkeypatch.setenv("CAPITAL_IDENTIFIER","mock@invalid.test")
    monkeypatch.setenv("CAPITAL_PASSWORD","mock-password")
    monkeypatch.setenv("OPENAI_API_KEY","mock-not-billed")
    monkeypatch.setattr(CapitalReadOnly,"candles",fake_candles)
    monkeypatch.setattr(CapitalReadOnly,"market_state",lambda self,epic:"TRADEABLE")
    import trader.storage as storage
    import trader.assistant as assistant
    monkeypatch.setattr(storage,"DB_PATH",tmp_path/"chat-paper.sqlite3")
    monkeypatch.setattr(assistant,"answer_ai",
        lambda *args,**kwargs:"TEST AI: Rynek został odczytany, to odpowiedź mock.")
    app=AppTest.from_file(APP,default_timeout=55).run()
    app.text_input[0].set_value("isolated-ai-test-password-2026")
    app.button[0].click()
    app.run()
    assert len(app.tabs)==10 and not app.exception
    areas=[a for a in app.text_area if "Napisz pytanie" in a.label]
    assert areas, [a.label for a in app.text_area]
    areas[0].set_value("Co mówi ostatnia świeca?")
    send=[b for b in app.button if "WYŚLIJ PYTANIE" in b.label]
    assert send, [b.label for b in app.button]
    send[0].click()
    app.run()
    assert not app.exception,[str(e.message) for e in app.exception]
    messages=list(app.session_state["_ai_messages"])
    assert len(messages)==2
    assert messages[0]["role"]=="user"
    assert "TEST AI:" in messages[-1]["content"]
    app.run()  # simulates arbitrary UI AUTO-SCAN rerun
    assert len(app.session_state["_ai_messages"])==2
    assert "TEST AI:" in app.session_state["_ai_messages"][-1]["content"]
