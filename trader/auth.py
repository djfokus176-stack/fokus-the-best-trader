"""Credential selection and provider probes; never persist or print credentials."""
from __future__ import annotations
from typing import Callable


def active_credential(name: str, read_secret: Callable[[str], str], overrides: dict | None = None) -> str:
    override = (overrides or {}).get(name)
    if override is not None and str(override).strip():
        return str(override).strip()
    return str(read_secret(name) or '').strip()


def capital_credentials(read_secret, overrides):
    api_key = active_credential('CAPITAL_API_KEY', read_secret, overrides)
    identifier = active_credential('CAPITAL_IDENTIFIER', read_secret, overrides)
    if not identifier:
        identifier = active_credential('CAPITAL_LOGIN', read_secret, overrides)
    password = active_credential('CAPITAL_PASSWORD', read_secret, overrides)
    return api_key, identifier, password


def test_capital_login(api_key: str, identifier: str, password: str, environment: str):
    """Authentication only, no trade; returns a reusable READ-ONLY client."""
    from .market import CapitalReadOnly
    client = CapitalReadOnly(api_key, identifier, password, environment=environment)
    headers = client.headers()
    if not headers.get('CST') or not headers.get('X-SECURITY-TOKEN'):
        raise RuntimeError('Capital.com nie zwrócił tokenów sesji.')
    return client


def test_openai_model(api_key: str, model: str):
    """Read-only model metadata check, without generating tokens."""
    if not api_key:
        return False, 'Brak OPENAI_API_KEY.'
    try:
        from openai import OpenAI
        obj = OpenAI(api_key=api_key, timeout=12, max_retries=0).models.retrieve(model)
        return True, f'API działa, model widoczny: {obj.id}. Tryb HIGH wymaga osobnego wywołania.'
    except Exception as ex:
        code = getattr(ex, 'status_code', None)
        return False, f'OpenAI: {type(ex).__name__}' + (f' (HTTP {code})' if code else '')


def test_telegram_token(token: str):
    """Read-only Telegram getMe; never send user messages."""
    if not token:
        return False, 'Brak TELEGRAM_BOT_TOKEN.'
    try:
        import requests
        r = requests.get('https://api.telegram.org/bot' + token + '/getMe', timeout=10)
        if r.status_code != 200:
            return False, f'Telegram: HTTP {r.status_code}'
        obj = r.json()
        return (True, 'Telegram: autoryzacja prawidłowa (getMe).') if obj.get('ok') else (False, 'Telegram nie potwierdził tokenu.')
    except Exception as ex:
        return False, 'Telegram: brak połączenia (' + type(ex).__name__ + ').'


CAPITAL_SECRET_FIELDS = ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_PASSWORD")


def drop_capital_session_overrides(overrides: dict | None) -> dict:
    """Discard only temporary broker credentials; preserve unrelated settings."""
    return {key: value for key, value in dict(overrides or {}).items()
            if key not in (*CAPITAL_SECRET_FIELDS, "CAPITAL_LOGIN")}


def capital_credential_sources(read_secret, overrides: dict | None = None) -> dict:
    """Report origins, never values, so a populated field is not called verified."""
    sources = {}
    session = overrides or {}
    for name in CAPITAL_SECRET_FIELDS:
        temporary = session.get(name)
        if name == "CAPITAL_IDENTIFIER" and not temporary:
            temporary = session.get("CAPITAL_LOGIN")
        stored = read_secret(name)
        if name == "CAPITAL_IDENTIFIER" and not stored:
            stored = read_secret("CAPITAL_LOGIN")
        sources[name] = ("SESJA" if temporary is not None and str(temporary).strip()
                         else "SECRETS" if stored else "BRAK")
    return sources


def capital_client_matches(client, api_key, identifier, password, environment):
    """Never reuse a broker session if its environment or credentials differ."""
    return (client is not None
            and getattr(client, "environment", None) == environment
            and getattr(client, "api_key", None) == api_key
            and getattr(client, "identifier", None) == identifier
            and getattr(client, "password", None) == password)
