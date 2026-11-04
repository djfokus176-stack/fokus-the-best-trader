"""Read-only session login and safe precedence for temporary API overrides."""
from trader.auth import active_credential, capital_credentials, test_capital_login as probe_capital
from trader.market import CapitalReadOnly
import pytest


def test_secret_fallback_and_override():
    base={'CAPITAL_API_KEY':'stored-key','CAPITAL_IDENTIFIER':'stored@email.invalid',
          'CAPITAL_PASSWORD':'stored-password'}
    getter=lambda key: base.get(key,'')
    a=capital_credentials(getter,{})
    assert a==('stored-key','stored@email.invalid','stored-password')
    b=capital_credentials(getter,{'CAPITAL_API_KEY':' new-key ',
        'CAPITAL_PASSWORD':' new-pass '})
    assert b==('new-key','stored@email.invalid','new-pass')
    assert base['CAPITAL_API_KEY']=='stored-key'


def test_login_alias_when_identifier_missing():
    base={'CAPITAL_API_KEY':'key','CAPITAL_LOGIN':'login@example.invalid',
          'CAPITAL_PASSWORD':'pw'}
    assert capital_credentials(lambda k:base.get(k,''),{})[1]=='login@example.invalid'


def test_test_capital_login_only_requests_session(monkeypatch):
    calls=[]
    def fake_headers(self):
        calls.append((self.environment,self.api_key,self.identifier))
        return {'CST':'ok','X-SECURITY-TOKEN':'ok'}
    monkeypatch.setattr(CapitalReadOnly,'headers',fake_headers)
    client=probe_capital('key','login@example.invalid','password','LIVE')
    assert client.environment=='LIVE'
    assert calls==[('LIVE','key','login@example.invalid')]


def test_no_order_network_calls_in_probe(monkeypatch):
    def fake_headers(self):
        return {'CST':'ok','X-SECURITY-TOKEN':'ok'}
    def fail_post(*args,**kwargs):
        raise AssertionError('order request must not run')
    monkeypatch.setattr(CapitalReadOnly,'headers',fake_headers)
    monkeypatch.setattr('requests.Session.post',fail_post)
    assert probe_capital('key','login','pass','DEMO').environment=='DEMO'
