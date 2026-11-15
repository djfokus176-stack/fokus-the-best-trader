"""The host and GitHub schedule cannot both opt in from one legacy flag."""
from pathlib import Path

import pytest

from trader.worker_service import validated_worker_args
from trader.bls_verified_snapshot import verified_schedule

BASE={
    "FOKUS_PAPER_WORKER_ENABLED":"true",
    "FOKUS_CANDLE_TIME_CONFIRMED":"open",
    "FOKUS_SUPABASE_URL":"https://project.supabase.co",
    "FOKUS_SUPABASE_SECRET_KEY":"super-secret-not-for-logs",
    "CAPITAL_API_KEY":"example-key",
    "CAPITAL_IDENTIFIER":"example-identifier",
    "CAPITAL_PASSWORD":"example-password",
    "CAPITAL_ENV":"DEMO",
}


def test_northflank_remains_default_after_executor_guard():
    assert "--align-minute" in validated_worker_args(dict(BASE))
    env={**BASE,"FOKUS_PAPER_EXECUTOR":"northflank"}
    assert "--epic" in validated_worker_args(env)


@pytest.mark.parametrize("executor",[
    "github_actions","another_host","", "GITHUB_ACTIONS"
])
def test_dedicated_host_rejects_other_executor(executor):
    env={**BASE,"FOKUS_PAPER_EXECUTOR":executor}
    with pytest.raises(ValueError,match="FOKUS_PAPER_EXECUTOR=northflank"):
        validated_worker_args(env)


def test_gh_scheduler_requires_distinct_optin_and_cannot_use_legacy_only():
    path=Path(__file__).resolve().parents[1]/".github/workflows/paper-v4-scan.yml"
    text=path.read_text(encoding="utf-8")
    assert "vars.FOKUS_PAPER_EXECUTOR == 'github_actions'" in text
    assert "vars.FOKUS_PAPER_WORKER_ENABLED == 'true'" in text
    assert 'if [[ "$FOKUS_PAPER_EXECUTOR" != "github_actions" ]]' in text
    assert "FOKUS_PAPER_EXECUTOR: ${{ vars.FOKUS_PAPER_EXECUTOR }}" in text
    assert "cancel-in-progress: false" in text


def test_bls_verified_fallback_is_expired_and_never_autoextended():
    # The real expiry is Nov 10, NOT Nov 16 as one review suggested.
    from datetime import datetime,timezone
    with pytest.raises(ValueError,match="EXPIRED"):
        verified_schedule(now=datetime(2026,11,15,12,0,
                                        tzinfo=timezone.utc))
