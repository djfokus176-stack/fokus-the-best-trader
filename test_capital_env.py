"""DEMO and LIVE must have different endpoints without any order endpoints."""
import pytest
from trader.market import CapitalReadOnly, API_BASE, FeedError

class FakeResponse:
    headers = {"CST": "test-session", "X-SECURITY-TOKEN": "test-token"}
    def raise_for_status(self):
        return None

@pytest.mark.parametrize("environment,url", [
    ("DEMO", "https://demo-api-capital.backend-capital.com/api/v1/session"),
    ("LIVE", "https://api-capital.backend-capital.com/api/v1/session"),
])
def test_read_only_session_endpoint(monkeypatch, environment, url):
    client = CapitalReadOnly(" key ", " login@example.test ", "custom_api_password", environment)
    calls = []
    def fake_post(address, **kwargs):
        calls.append((address, kwargs))
        return FakeResponse()
    monkeypatch.setattr(client.session, "post", fake_post)
    h = client.headers()
    assert len(calls) == 1
    assert calls[0][0] == url
    assert calls[0][1]["json"]["encryptedPassword"] is False
    assert calls[0][1]["json"]["identifier"] == "login@example.test"
    assert calls[0][1]["json"]["password"] == "custom_api_password"
    assert calls[0][1]["headers"]["X-CAP-API-KEY"] == "key"
    assert h["CST"] == "test-session"
    assert "/positions" not in calls[0][0]

def test_unknown_environment_rejected():
    with pytest.raises(FeedError):
        CapitalReadOnly("key", "login", "pass", "OTHER")

def test_distinct_environment_labels():
    assert API_BASE["DEMO"] != API_BASE["LIVE"]
