"""Guard against a second Capital.com login from the owner CLOUD display.

The Northflank worker owns DEMO price ingestion and PAPER writes. Streamlit
reads Supabase; a local manual click, a stale scheduled heartbeat or a
leftover session must not reauthenticate the broker in CLOUD mode.
"""


def local_scan_permitted(*, cloud_mode, manual=False, initial=False, scheduled=False):
    """True only for an intentionally active *local* data scan.

    This function is intentionally independent of strategy, exchange state,
    API credentials, and cloud event records.
    """
    return bool(not cloud_mode and (manual or initial or scheduled))
