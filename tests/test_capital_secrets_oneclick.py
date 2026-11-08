"""Regression checks: Streamlit must not mistake saved API fields for valid login."""
from types import SimpleNamespace
from pathlib import Path

from trader.auth import (capital_credentials, capital_credential_sources,
                         capital_client_matches, drop_capital_session_overrides)


def test_existing_secret_is_detected_but_not_marked_authenticated():
    values={"CAPITAL_API_KEY":"secret-api","CAPITAL_IDENTIFIER":"owner@example.invalid",
            "CAPITAL_PASSWORD":"secret-password"}
    origins=capital_credential_sources(lambda k: values.get(k, ""), {})
    assert origins=={"CAPITAL_API_KEY":"SECRETS",
                     "CAPITAL_IDENTIFIER":"SECRETS",
                     "CAPITAL_PASSWORD":"SECRETS"}
    assert "secret-api" not in str(origins)
    assert "secret-password" not in str(origins)


def test_reset_restores_saved_capital_credentials_without_erasing_other_overrides():
    secrets={"CAPITAL_API_KEY":"good", "CAPITAL_IDENTIFIER":"owner@example.invalid",
             "CAPITAL_PASSWORD":"good-pass"}
    overrides={"CAPITAL_API_KEY":"expired", "CAPITAL_IDENTIFIER":"wrong-login",
               "CAPITAL_PASSWORD":"bad-pass", "OPENAI_API_KEY":"other-provider",
               "TELEGRAM_CHAT_ID":"chat-id"}
    clean=drop_capital_session_overrides(overrides)
    assert clean=={"OPENAI_API_KEY":"other-provider","TELEGRAM_CHAT_ID":"chat-id"}
    assert capital_credentials(lambda k:secrets.get(k,""),clean)==(
        "good","owner@example.invalid","good-pass")


def test_ui_reports_session_override_instead_of_claiming_secrets_are_active():
    values={"CAPITAL_API_KEY":"valid","CAPITAL_IDENTIFIER":"owner@example.invalid",
            "CAPITAL_PASSWORD":"password"}
    origins=capital_credential_sources(lambda k:values.get(k,""),
        {"CAPITAL_API_KEY":"stale"})
    assert origins["CAPITAL_API_KEY"]=="SESJA"
    assert origins["CAPITAL_IDENTIFIER"]=="SECRETS"


def test_client_recreated_when_secret_env_or_password_changes():
    cached=SimpleNamespace(api_key="api",identifier="login",password="old",
                           environment="DEMO")
    assert capital_client_matches(cached,"api","login","old","DEMO")
    assert not capital_client_matches(cached,"api","login","new","DEMO")
    assert not capital_client_matches(cached,"api","login","old","LIVE")
    assert not capital_client_matches(None,"api","login","old","DEMO")


def test_ui_has_explicit_secret_only_test_and_no_false_saved_label():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text("utf-8")
    assert "TESTUJ ZAPISANE SECRETS (BEZ WPISYWANIA)" in app
    assert "drop_capital_session_overrides(existing)" in app
    assert "saved_api,saved_login,saved_password=capital_credentials(secret,{})" in app
    assert "to NIE jest zamknięty rynek (CLOSED)" in app
    assert "KLUCZE API — TESTY / ZMIANY (już zapisane w Secrets)" not in app
