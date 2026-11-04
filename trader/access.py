"""Simple owner access gate for a personally hosted Streamlit dashboard.

This is *not* a substitute for provider-managed authentication or rate limiting.
Without APP_ACCESS_PASSWORD the application must remain locked.
"""
from __future__ import annotations
import hmac
import hashlib


def access_configured(password: str) -> bool:
    """Reject accidental empty/weak configuration (avoid public API access)."""
    return isinstance(password, str) and len(password) >= 12 and password.strip() == password


def password_matches(candidate: str, expected: str) -> bool:
    if not access_configured(expected) or not isinstance(candidate, str):
        return False
    # Consistent fixed-length comparison without printing credentials.
    return hmac.compare_digest(
        hashlib.sha256(candidate.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )
