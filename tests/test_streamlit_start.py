"""Cloud smoke tests, using real Streamlit runtime but no user API credentials."""
from pathlib import Path

def test_main_app_renders_without_api_keys():
    from streamlit.testing.v1 import AppTest
    a = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30).run()
    assert not a.exception, [str(x.message) for x in a.exception]
    assert len(a.tabs) == 4

def test_independent_healthcheck_renders():
    from streamlit.testing.v1 import AppTest
    a = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'healthcheck.py'), default_timeout=30).run()
    assert not a.exception, [str(x.message) for x in a.exception]
    assert len(a.title) == 1
