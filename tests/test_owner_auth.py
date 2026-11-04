"""Owner identity must be exact, verified and never anonymously accepted."""
from trader.owner_auth import auth_mode, owner_email_configured, google_identity_matches
import pytest

def test_mode_fails_closed():
    assert auth_mode(None)=="password"
    assert auth_mode("Google")=="google"
    with pytest.raises(ValueError):auth_mode("off")
    with pytest.raises(ValueError):auth_mode("anonymous")

@pytest.mark.parametrize("mail",["","alice","admin@example"," A@example.com ","alice@example.com,other@example.com"])
def test_bad_email_config(mail):
    assert not owner_email_configured(mail)

def test_good_identity_owner_only_and_verified():
    trusted="owner@example.com"
    who={"email":"owner@example.com","email_verified":True,"is_logged_in":True}
    assert google_identity_matches(who,trusted)
    assert not google_identity_matches({**who,"email":"other@example.com"},trusted)
    assert not google_identity_matches({**who,"email_verified":False},trusted)
    assert not google_identity_matches({**who,"is_logged_in":False},trusted)
    assert not google_identity_matches({**who,"email_verified":"false"},trusted)
    assert not google_identity_matches(who,"")
