"""End-to-end fail-closed host and independent RAW research gate regression.

No Capital.com API, no Supabase secrets, no broker orders.
"""
import pytest

from trader import worker
from trader.market import FeedError
from trader.remote_checkpoint import RemoteError, RemoteConflict


def test_raw_is_independent_of_auto_mtf_only():
    blockers=[
        "INCOMPLETE_MTF","SETUPS_DISABLED","MARKET_NOT_TRADEABLE",
        "DATA_STALE","MACRO_BLACKOUT","MACRO_CALENDAR_UNKNOWN",
        "MACRO_CALENDAR_UNAVAILABLE","PAPER_DAILY_DRAWDOWN_LIMIT",
    ]
    assert worker.raw_research_blockers(blockers)==tuple(blockers[1:])
    assert worker.raw_research_blockers(["INCOMPLETE_MTF"])==()
    assert worker.raw_research_blockers([])==()


@pytest.mark.parametrize("error",[
    FeedError("HTTP 429"),
    RemoteError("Supabase transient 503"),
    OSError("socket timeout"),
])
def test_host_retries_one_transient_error_on_next_scan_not_immediately(error):
    assert worker.retryable_host_error_action(
        error,once=False,failures=1)=="RETRY_NEXT_MINUTE"
    assert worker.retryable_host_error_action(
        error,once=False,failures=5)=="RETRY_NEXT_MINUTE"
    assert worker.retryable_host_error_action(
        error,once=False,failures=6)=="EXIT"


def test_once_is_fail_fast_and_still_returns_nonzero():
    assert worker.retryable_host_error_action(
        FeedError("network"),once=True,failures=1)=="EXIT"
    assert worker.retryable_host_error_action(
        RemoteError("Supabase"),once=True,failures=1)=="EXIT"


def test_two_writer_cas_conflict_never_retries_on_persistent_host():
    assert worker.retryable_host_error_action(
        RemoteConflict("different writer"),once=False,failures=1)=="EXIT"


@pytest.mark.parametrize("message",[
    "HTTP 401", "HTTP403", "Remote request HTTP 403 unauthorized",
])
def test_remote_auth_denial_fails_fast(message):
    assert worker.retryable_host_error_action(
        RemoteError(message),once=False,failures=1)=="EXIT"


def test_persistent_worker_continues_to_next_scan_after_one_feed_failure(monkeypatch,capsys):
    # The first cloud cycle fails before committing. The next is a fresh
    # remote_scan_once invocation; no failed-cycle state is ever retained.
    monkeypatch.setenv("FOKUS_CANDLE_TIME_CONFIRMED","open")
    monkeypatch.setenv("FOKUS_SCALP_5S_ENABLED","false")
    monkeypatch.setattr(worker,"configured",lambda:True)
    monkeypatch.setattr(worker.RemoteCheckpoint,"from_env",lambda *a,**kw:object())
    monkeypatch.setattr(worker,"CapitalReadOnly",lambda *a,**kw:object())
    attempts=[]
    def fake_remote_scan(*args,**kwargs):
        attempts.append(True)
        if len(attempts)==1:
            raise FeedError("synthetic HTTP 429")
        return "WAIT / synthetic OK / GATES=OK"
    monkeypatch.setattr(worker,"remote_scan_once",fake_remote_scan)
    monkeypatch.setattr(worker,"seconds_until_next_m1_scan",lambda:0.0)
    sleeps=[]
    def stop_after_second_cycle(seconds):
        sleeps.append(seconds)
        if len(sleeps)==2:
            raise StopIteration("end synthetic worker loop")
    monkeypatch.setattr(worker.time,"sleep",stop_after_second_cycle)
    with pytest.raises(StopIteration, match="end synthetic"):
        worker.main(["--interval","65","--epic","US500",
                     "--tf","MINUTE","--align-minute"])
    assert len(attempts)==2
    out=capsys.readouterr().out
    assert "RECOVERY=RETRY_NEXT_MINUTE" in out
    assert "synthetic HTTP 429" not in out
    assert "WAIT / synthetic OK" in out


def test_running_source_fingerprint_is_stable_nonsecret_12_hex():
    import re
    first=worker.source_fingerprint()
    second=worker.source_fingerprint()
    assert re.fullmatch(r"[0-9a-f]{12}",first)
    assert first==second


def test_watchdog_filters_malformed_source_digests(monkeypatch):
    from trader import worker_trade_audit as audit
    monkeypatch.setattr(audit,"auto_sim_journal",lambda payload:{
        "known":True,"opened":0,"closed":0,"pending":None,
        "active":None,"invalidated":0,"incomplete":0})
    payload={"schema":1,"tables":{"paper_positions_v3":[]},
             "meta":{"worker_source_fingerprint":"bad-token-with-secret"}}
    report=audit.read_only_archive_counts(payload)
    assert report["worker_code"]=="UNKNOWN"
    payload["meta"]["worker_source_fingerprint"]=worker.source_fingerprint()
    report=audit.read_only_archive_counts(payload)
    assert report["worker_code"]==worker.source_fingerprint()
    assert "WORKER_CODE="+worker.source_fingerprint() in audit.redacted_archive_log_line(payload)
