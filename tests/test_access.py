"""Owner gateway must reject missing, weak and incorrect credentials."""
from trader.access import password_matches, access_configured


def test_no_password_fail_closed():
    assert not access_configured("")
    assert not access_configured("simple")
    assert not password_matches("", "")
    assert not password_matches("anything", "")


def test_only_exact_secret_works():
    expected = "my-private-dashboard-2026-secret"
    assert access_configured(expected)
    assert password_matches(expected,expected)
    assert not password_matches(expected+" ",expected)
    assert not password_matches("incorrect-password",expected)
    assert not access_configured(" "+expected)
