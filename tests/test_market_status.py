"""Verify Capital.com status is fetched from instrument GET and parsed safely."""
from trader.market import CapitalReadOnly, FeedError
import pytest


class FakeResponse:
    def __init__(self, payload):
        self.payload=payload
    def raise_for_status(self):
        pass
    def json(self):
        return self.payload


@pytest.mark.parametrize("payload,expected",[
    ({"snapshot":{"marketStatus":"CLOSED"}},"CLOSED"),
    ({"snapshot":{"marketStatus":"TRADEABLE"}},"TRADEABLE"),
    ({"instrument":{"marketStatus":"EDITs_ONLY"}},"EDITS_ONLY"),
    ({}, "UNKNOWN"),
])
def test_market_state_reads_only_snapshot_or_instrument(monkeypatch,payload,expected):
    client=CapitalReadOnly('key','identifier','password',environment='DEMO')
    calls=[]
    monkeypatch.setattr(client,'headers',lambda: {'CST':'stub','X-SECURITY-TOKEN':'stub'})
    def fake_get(url,**kwargs):
        calls.append(url)
        return FakeResponse(payload)
    monkeypatch.setattr(client.session,'get',fake_get)
    assert client.market_state('US500')==expected
    assert calls==['https://demo-api-capital.backend-capital.com/api/v1/markets/US500']
    assert '/positions' not in calls[0]


def test_wrong_epic_rejected_without_network():
    client=CapitalReadOnly('key','identifier','password')
    with pytest.raises(FeedError):
        client.market_state('US500/positions')
