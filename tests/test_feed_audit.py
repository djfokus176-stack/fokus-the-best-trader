import pandas as pd
from trader.feed_audit import inspect_labels

def test_label_open_hypothesis_is_not_verification():
    now=pd.Timestamp("2026-11-05T13:03:35Z")
    ix=pd.date_range("2026-11-05T13:01:00Z",periods=3,freq="min")
    f=pd.DataFrame({"Close":[1,2,3]},index=ix)
    result=inspect_labels(f,"MINUTE",observed_at=now)
    assert result["age_seconds"]==35
    assert "NIE POTWIERDZONE" in result["time_hypothesis"]
    assert "NIEZWERYFIKOWANE" in result["verification"]

def test_old_last_bar_unknown_not_falsely_verified():
    now=pd.Timestamp("2026-11-05T15:00:00Z")
    ix=pd.date_range("2026-11-05T13:01:00Z",periods=3,freq="min")
    f=pd.DataFrame({"Close":[1,2,3]},index=ix)
    assert "NIEROZSTRZYGNIĘTE" in inspect_labels(f,"MINUTE",now)["time_hypothesis"]
