"""Regression for real bug: old Streamlit session holds stale Capital client.

The raw candle audit must use a new DEMO client even when the older object
has no raw_candle_time_diagnostic method. No real API calls or credentials.
"""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pandas as pd
import numpy as np
from streamlit.testing.v1 import AppTest
from trader.market import CapitalReadOnly,Snapshot,PERIOD

APP=str(Path(__file__).resolve().parents[1]/"app.py")


def test_owner_raw_clock_audit_survives_predeploy_session_client(monkeypatch,tmp_path):
    monkeypatch.setenv("APP_AUTH_MODE","password")
    monkeypatch.setenv("APP_ACCESS_PASSWORD","candle-diagnostic-regression-password")
    monkeypatch.setenv("CAPITAL_API_KEY","test-only-not-real")
    monkeypatch.setenv("CAPITAL_IDENTIFIER","mock@example.invalid")
    monkeypatch.setenv("CAPITAL_PASSWORD","not-a-real-password")
    monkeypatch.setenv("FOKUS_REMOTE_VIEW_ENABLED","false")
    monkeypatch.setenv("AUTO_SCAN_DEFAULT","false")
    import trader.storage as storage
    monkeypatch.setattr(storage,"DB_PATH",tmp_path/"audit-paper.sqlite")
    last=datetime.now(timezone.utc).replace(second=0,microsecond=0)-timedelta(minutes=2)
    ix=pd.date_range(end=last,periods=160,freq="min",tz="UTC")
    p=np.full(len(ix),5000.)
    frame=pd.DataFrame({"Open":p,"High":p+1,"Low":p-1,
                        "Close":p,"Spread":np.full(len(ix),0.6)},index=ix)

    def synthetic_snapshot(self,epic="US500",resolution="MINUTE",count=350,max_spread=2):
        return Snapshot(frame,"Capital.com DEMO REST",epic,resolution,
                        0.6,last,120,True,"OK test",quote_spread=0.6)
    monkeypatch.setattr(CapitalReadOnly,"candles",synthetic_snapshot)
    monkeypatch.setattr(CapitalReadOnly,"market_state",lambda self,epic:"TRADEABLE")
    seen=[]
    def synthetic_raw(self,epic="US500",resolution="MINUTE",count=8):
        seen.append((self.environment,epic,resolution))
        return frame.tail(8)
    monkeypatch.setattr(CapitalReadOnly,"raw_candle_time_diagnostic",synthetic_raw)

    app=AppTest.from_file(APP,default_timeout=55).run()
    app.text_input[0].set_value("candle-diagnostic-regression-password")
    app.button[0].click()
    app.run()
    assert not app.exception,[str(x.message) for x in app.exception]

    class LegacyPredeployCapital:
        environment="DEMO"
        # Intentionally no raw_candle_time_diagnostic method.

    app.session_state["_capital_client"]=LegacyPredeployCapital()
    app.session_state["initial_scan_attempted"]=True
    audit_buttons=[b for b in app.button if "PORÓWNAJ SUROWE" in b.label]
    assert len(audit_buttons)==1
    audit_buttons[0].click()
    app.run()
    assert not app.exception,[str(x.message) for x in app.exception]
    assert seen==[("DEMO","US500","MINUTE")]
    result=app.session_state["_last_raw_time_audit"]
    assert result["resolution"]=="MINUTE"
    assert "NIEZWERYFIKOWANE" in result["verification"]
