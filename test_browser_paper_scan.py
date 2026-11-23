"""Owner click scans really write a DEMO checkpoint, never bypass macro/clock.

No external network or secrets in tests; staleness is not made artificially green.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from trader.browser_paper_scan import confirmed_clock_for_browser, run_browser_paper_scan


def meta(clock=True, epic="US500", when=None):
    return {"clock_confirmed_open":clock, "epic":epic,
            "source":"Capital.com DEMO REST","timeframe":"MINUTE",
            "last_scan_utc":(when or datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}


def test_owner_cloud_scan_preserves_all_worker_gates_and_writes_real_checkpoint():
    calls=[]
    previous={"meta":meta()}
    class FakeRemote:
        def __init__(self,url,key):
            assert url=="https://demo.supabase.co"
            assert key=="test-only-secret"
        def fetch(self):
            return 23,previous
    def scan(*args,**kwargs):
        calls.append(kwargs)
        return "2026-11-09T17:59:00+00:00 / WAIT / QUEUE=NO / GATES=OK / CLOUD_CHECKPOINT_VERSION=24"
    result=run_browser_paper_scan(
        cloud_url="https://demo.supabase.co",cloud_key="test-only-secret",
        api_key="dummy-api",identifier="u@test.test",password="dummy-secret",
        environment="DEMO",epic="US500",remote_cls=FakeRemote,
        client_cls=lambda *a,**kw: SimpleNamespace(environment="DEMO"),
        scanner=scan)
    assert result["saved"] is True
    assert result["clock_verified"] is True
    assert result["entry_gates_open"] is True
    assert calls==[{"enable_setups":True, "strict_macro":True,
                    "clock_confirmed_open":True}]


def test_missing_clock_confirmation_forbids_new_paper_entries():
    class Remote:
        def __init__(self,*a):pass
        def fetch(self):return 23,{"meta":meta(clock=False)}
    received=[]
    def scan(*a,**kw):
        received.append(kw)
        return "WAIT / GATES=SETUPS_DISABLED / CLOUD_CHECKPOINT_VERSION=24"
    result=run_browser_paper_scan(cloud_url="u",cloud_key="k",
        api_key="a",identifier="b",password="c",environment="DEMO",
        epic="US500",remote_cls=Remote,
        client_cls=lambda *a,**kw: SimpleNamespace(environment="DEMO"),
        scanner=scan)
    assert result["clock_verified"] is False
    assert result["entry_gates_open"] is False
    assert received[0]["enable_setups"] is False
    assert received[0]["strict_macro"] is True


def test_clock_proof_never_comes_from_wrong_instrument_or_fake_csv():
    assert confirmed_clock_for_browser("",meta(),epic="US500")
    assert not confirmed_clock_for_browser("close",meta(epic="DE40"))
    assert not confirmed_clock_for_browser("",{"clock_confirmed_open":True,
          "source":"CSV NAUKA (NIE LIVE)","epic":"US500","timeframe":"MINUTE"})
    assert confirmed_clock_for_browser("open",{},epic="US500")


def test_recent_cloud_worker_is_not_competed_with():
    class Remote:
        def __init__(self,*a):pass
        def fetch(self):return 23,{"meta":meta(when=datetime.now(timezone.utc))}
    result=run_browser_paper_scan(cloud_url="u",cloud_key="k",
        api_key="a",identifier="b",password="c",environment="DEMO",
        epic="US500",remote_cls=Remote,client_cls=lambda *a,**kw:None,
        scanner=lambda *a,**kw:pytest.fail("No competing writer"))
    assert result["saved"] is False
    assert "SKIP" in result["result"]


def test_never_accept_live_or_fake_checkpoint_success():
    with pytest.raises(ValueError,match="LIVE"):
        run_browser_paper_scan(cloud_url="u",cloud_key="k",
            api_key="a",identifier="b",password="c",environment="LIVE",
            epic="US500")
    class Remote:
        def __init__(self,*a):pass
        def fetch(self):return 23,{"meta":meta()}
    with pytest.raises(RuntimeError,match="Brak potwierdzenia"):
        run_browser_paper_scan(cloud_url="u",cloud_key="k",
            api_key="a",identifier="b",password="c",environment="DEMO",
            epic="US500",remote_cls=Remote,
            client_cls=lambda *a,**kw:SimpleNamespace(environment="DEMO"),
            scanner=lambda *a,**kw:"WAIT / BRAK ZAPISU")


def test_cloud_button_displays_real_worker_blockers_and_no_always_on_claim():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    page=(root/"app.py").read_text("utf-8")
    assert "URUCHOM SKAN PAPER TERAZ (DEMO)" in page
    assert 'run_browser_paper_scan(' in page
    assert "run_every=\"65s\"" in page
    assert "tylko przy otwartej karcie" in page
    assert "MACRO_CALENDAR_UNAVAILABLE" in page
