"""Owner-only authentication policy for FOKU$.

Password mode is the legacy fallback. Preferred OIDC mode uses Streamlit's
native Google sign-in and its persistent, HTTP-only identity cookie.
Do NOT make the dashboard anonymously accessible merely to avoid re-login.
"""
from __future__ import annotations
import re

def auth_mode(raw: str | None) -> str:
    mode = str(raw or "password").strip().lower()
    if mode not in ("password", "google"):
        raise ValueError("APP_AUTH_MODE musi mieć wartość 'password' albo 'google'.")
    return mode


def owner_email_configured(email: str) -> bool:
    value = str(email or "").strip()
    return bool(value and value == value.lower() and
                re.fullmatch(r"[a-z0-9][a-z0-9._%+\-]*@[a-z0-9][a-z0-9.\-]*\.[a-z]{2,63}", value))


def google_identity_matches(user, required_email: str) -> bool:
    """Fail closed unless the exact owner email is verified by the IdP."""
    if not owner_email_configured(required_email):
        return False
    try:
        is_logged_in = bool(user.get("is_logged_in", False))
        # st.user exposes is_logged_in as an attribute instead of a dict key.
        is_logged_in = is_logged_in or bool(getattr(user, "is_logged_in", False))
        given = str(user.get("email", "")).strip().lower()
        verified = user.get("email_verified", False)
    except (TypeError, AttributeError):
        return False
    return bool(
        is_logged_in and given == required_email.strip().lower() and
        (verified is True or str(verified).strip().lower() == "true")
    )
