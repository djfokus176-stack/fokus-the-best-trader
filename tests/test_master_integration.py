"""Integration smoke: synthetic closed Capital-like snapshots, no network or AI."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
from trader.market import Snapshot, PERIOD, CapitalReadOnly

APP=str(Path(__file__).resolve().parents[1]/"app.py")


def fake_candles(self,epic="US500",resolution="MINUTE",count=300,max_spread=2.0):
    from trader.market import PERIOD
    now=datetime.now(timezone.utc)
    seconds=PERIOD[resolution]
    ts=datetime.fromtimestamp((int(now.timestamp())//seconds)*seconds,tz=timezone.utc)-timedelta(seconds=seconds)
    idx=pd.date_range(end=ts,periods=155,freq=f"{seconds}s",tz="UTC")
    p=np.array([5000+i*.12+2*np.sin(i/7) for i in range(155)])
    frame=pd.DataFrame({
      "Open":p-.2,"High":p+1.2,"Low":p-1.2,"Close":p,
      "Spread":np.full(len(p),.6),"Bid":p-.3,"Ask":p+.3},index=idx)
    return Snapshot(frame,f"Capital.com {self.environment} REST",epic,resolution,
                    .6,ts,(now-ts).total_seconds(),True,"OK mock",quote_spread=.6)


def test_full_master_dashboard_with_four_realistic_synthetic_timeframes(monkeypatch,tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("APP_ACCESS_PASSWORD","integration-password-not-in-github")
    monkeypatch.setenv("CAPITAL_API_KEY","DEMO-MOCK")
    monkeypatch.setenv("CAPITAL_IDENTIFIER","mock@example.test")
    monkeypatch.setenv("CAPITAL_PASSWORD","secret-mock")
    monkeypatch.setenv("APP_AUTH_MODE","password")
    monkeypatch.setattr(CapitalReadOnly,"candles",fake_candles)
    monkeypatch.setattr(CapitalReadOnly,"market_state",lambda self,epic: "TRADEABLE")
    import trader.storage as storage
    monkeypatch.setattr(storage,"DB_PATH",tmp_path/"paper.sqlite3")
    app=AppTest.from_file(APP,default_timeout=55).run()
    assert len(app.tabs)==0
    app.text_input[0].set_value("integration-password-not-in-github")
    app.button[0].click()
    app.run()
    assert len(app.tabs)==9
    assert not app.exception,[str(x.message) for x in app.exception]
