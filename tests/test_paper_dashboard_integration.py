"""End-to-end simulated dashboard PAPER PENDING -> OPEN via two actual scans.
No Capital.com and no OpenAI network access. This cannot validate deployment.
"""
import pandas as pd
import numpy as np
from datetime import datetime,timezone,timedelta
from pathlib import Path
from streamlit.testing.v1 import AppTest
from trader.market import Snapshot,PERIOD,CapitalReadOnly
from trader.strategy import Decision
from trader.storage import connect
from trader.paper_lifecycle import recent_positions

APP=str(Path(__file__).resolve().parents[1]/"app.py")


def test_dashboard_v3_queue_then_simulated_open_on_next_closed_candle(monkeypatch,tmp_path):
    monkeypatch.setenv("APP_AUTH_MODE","password")
    monkeypatch.setenv("APP_ACCESS_PASSWORD","paper-dashboard-integration-secret")
    monkeypatch.setenv("CAPITAL_API_KEY","mock-api")
    monkeypatch.setenv("CAPITAL_IDENTIFIER","mock@example.invalid")
    monkeypatch.setenv("CAPITAL_PASSWORD","mock-password")
    # Synthetic fixtures below already carry CLOSE-time timestamps.
    # Owner explicitly confirmed raw API labels are OPEN to enable PAPER.
    monkeypatch.setenv("FOKUS_CANDLE_TIME_CONFIRMED","open")
    monkeypatch.setenv("PAPER_TELEGRAM_ALERTS_ENABLED","false")
    import trader.storage as storage
    monkeypatch.setattr(storage,"DB_PATH",tmp_path/"v3.sqlite3")
    calls={"m1":0}
    def mocked_candles(self,epic="US500",resolution="MINUTE",count=350,max_spread=2):
        step=PERIOD[resolution]
        now=datetime.now(timezone.utc)
        end=datetime.fromtimestamp((int(now.timestamp())//step)*step,
            tz=timezone.utc)-timedelta(seconds=step)
        if resolution=="MINUTE":
            end=end+timedelta(seconds=step*calls["m1"])
            calls["m1"]+=1
        idx=pd.date_range(end=end,periods=155,freq=f"{step}s",tz="UTC")
        # Fixed prices -> no automatic SL/TP.
        o=np.full(155,100.0)
        df=pd.DataFrame({"Open":o,"High":o+1,"Low":o-1,
                         "Close":o,"Spread":np.full(155,.6)},index=idx)
        return Snapshot(df,"Capital.com DEMO REST",epic,resolution,.6,end,
             (now-end).total_seconds(),True,"OK mock",quote_spread=.6)
    monkeypatch.setattr(CapitalReadOnly,"candles",mocked_candles)
    monkeypatch.setattr(CapitalReadOnly,"market_state",lambda self,epic:"TRADEABLE")
    # The UI now gets the same status from an authenticated market quote.
    # No network calls in this controlled PAPER integration fixture.
    from trader.market import MarketQuote
    monkeypatch.setattr(CapitalReadOnly,"market_quote",
        lambda self,epic: MarketQuote(epic,"DEMO",100.0,100.6,100.3,.6,
            "TRADEABLE",datetime.now(timezone.utc),datetime.now(timezone.utc),0,True))
    import trader.strategies_pro as pro
    def mocked_decision(frame,strategy,spread):
        return Decision("LONG",strategy,"controlled test only",100,98,102,1.5,1.0,"UP")
    monkeypatch.setattr(pro,"decide_any",mocked_decision)
    import trader.mtf as mtf
    monkeypatch.setattr(mtf,"filter_mtf_decision",
        lambda decision,snapshots,**kw:(decision,[]))
    app=AppTest.from_file(APP,default_timeout=50).run()
    app.text_input[0].set_value("paper-dashboard-integration-secret")
    app.button[0].click()
    app.run()
    assert not app.exception,[str(x.message) for x in app.exception]
    # This scenario tests the legacy one-strategy PAPER setup specifically;
    # AUTO mode has intentionally stricter two-strategy consensus gating.
    manual=[x for x in app.selectbox if "Tryb analizy / strategia" in x.label]
    assert len(manual)==1
    manual[0].set_value("DRUGA FALA")
    app.run()
    assert not app.exception,[str(x.message) for x in app.exception]
    # Changing a selector does not fetch new market data; only an actual
    # scheduled/manual scan is permitted to queue a PAPER candidate.
    reload_buttons=[x for x in app.button if "SKANUJ ŚWIECE" in x.label]
    assert reload_buttons
    reload_buttons[0].click()
    app.run()
    assert not app.exception,[str(x.message) for x in app.exception]
    db=connect(tmp_path/"v3.sqlite3")
    recorded=recent_positions(db)
    assert len(recorded)==1 and recorded[0]["status"]=="PENDING"
    buttons=[b for b in app.button if "SKANUJ ŚWIECE" in b.label]
    assert buttons
    buttons[0].click()
    app.run()
    assert not app.exception,[str(x.message) for x in app.exception]
    after=recent_positions(db)
    assert len(after)==1 and after[0]["status"]=="OPEN"
    assert after[0]["entry_executable"]==100.55  # 100 + 0.3 spread + 0.25 slip
