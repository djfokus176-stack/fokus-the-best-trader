"""Owner identity must be exact, verified and never anonymously accepted."""
from trader.owner_auth import auth_mode, owner_email_configured, google_identity_matches, google_oidc_ready
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


def test_oidc_config_requires_all_values():
    full={"redirect_uri":"https://example.streamlit.app/oauth2callback",
          "cookie_secret":"some-random-secret",
          "client_id":"client","client_secret":"secret",
          "server_metadata_url":"https://accounts.google.com/.well-known/openid-configuration"}
    assert google_oidc_ready(full)
    for key in full:
        changed=dict(full); changed[key]=''
        assert not google_oidc_ready(changed)
    assert not google_oidc_ready(None)


def test_user_like_object_with_verified_claim():
    class User(dict):
        is_logged_in=True
    u=User(email="owner@example.com",email_verified="true")
    assert google_identity_matches(u,"owner@example.com")
