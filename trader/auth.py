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
