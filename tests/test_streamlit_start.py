"""Cloud smoke tests with the owner access gate."""
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1] / 'app.py')


def test_main_app_is_locked_without_password(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv('APP_ACCESS_PASSWORD',raising=False)
    a = AppTest.from_file(APP, default_timeout=30).run()
    assert not a.exception, [str(x.message) for x in a.exception]
    assert len(a.tabs) == 0


def test_main_app_renders_after_owner_login(monkeypatch):
    from streamlit.testing.v1 import AppTest
    password='test-owner-only-password-2026'
    monkeypatch.setenv('APP_ACCESS_PASSWORD',password)
    a=AppTest.from_file(APP,default_timeout=30).run()
    assert not a.exception, [str(x.message) for x in a.exception]
    assert len(a.tabs) == 0
    assert len(a.text_input)>0
    assert len(a.button)>0
    a.text_input[0].set_value(password)
    a.button[0].click()
    a.run()
    assert not a.exception, [str(x.message) for x in a.exception]
    assert len(a.tabs) == 10


def test_independent_healthcheck_renders():
    from streamlit.testing.v1 import AppTest
    a = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'healthcheck.py'), default_timeout=30).run()
    assert not a.exception, [str(x.message) for x in a.exception]
    assert len(a.title) == 1


def test_auto_scan_toggle_does_not_crash_without_live_api(monkeypatch):
    """Smoke test only: AppTest does not simulate a real 60s browser timer."""
    from streamlit.testing.v1 import AppTest
    pw='isolated-owner-secret-2026'
    monkeypatch.setenv('APP_ACCESS_PASSWORD',pw)
    a=AppTest.from_file(APP,default_timeout=30).run()
    a.text_input[0].set_value(pw)
    a.button[0].click()
    a.run()
    assert len(a.tabs)==10
    assert len(a.toggle)>0
    a.toggle[0].set_value(True)
    a.run()
    assert not a.exception, [str(x.message) for x in a.exception]


def test_google_mode_without_oauth_secrets_is_locked(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('APP_AUTH_MODE','google')
    monkeypatch.setenv('OWNER_EMAIL','owner@example.com')
    app=AppTest.from_file(APP,default_timeout=30).run()
    assert not app.exception, [str(x.message) for x in app.exception]
    assert len(app.tabs)==0


def test_owner_defaults_to_auto_six_and_selectable_five_second_page_scan(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from trader.auto_strategy import AUTO_MODE
    pw="test-owner-auto-five-sec"
    monkeypatch.setenv("APP_ACCESS_PASSWORD",pw)
    monkeypatch.setenv("APP_AUTH_MODE","password")
    a=AppTest.from_file(APP,default_timeout=40).run()
    a.text_input[0].set_value(pw)
    a.button[0].click()
    a.run()
    assert not a.exception,[str(x.message) for x in a.exception]
    chosen=[x for x in a.selectbox if "Tryb analizy / strategia" in x.label]
    assert len(chosen)==1 and chosen[0].value==AUTO_MODE
    assert a.session_state["auto_scan_period"]==5
    refresh=[x for x in a.selectbox if "Częstotliwość AUTO-SKAN" in x.label]
    assert len(refresh)==1
    assert tuple(refresh[0].options)==tuple(f"co {i} sekund" if i<60 else f"co {i//60} min" for i in (5,15,30,60,120,300))
    refresh[0].set_value("co 1 min")
    a.run()
    assert a.session_state["auto_scan_period"]==60
