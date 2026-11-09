"""Foreground Windows M1 launch must be 60s, safe and no-secret-output."""
from datetime import datetime, timezone
from pathlib import Path
import pytest
from trader.worker import seconds_until_next_m1_scan
from trader.worker_service import validated_worker_args
from trader.windows_scalping import prepare_pc_environment


def _env():
    return {
        "FOKUS_PAPER_WORKER_ENABLED": "true",
        "FOKUS_CANDLE_TIME_CONFIRMED": "open",
        "CAPITAL_API_KEY": "TEST_API_SECRET",
        "CAPITAL_IDENTIFIER": "example@example.test",
        "CAPITAL_PASSWORD": "TEST_PASSWORD_SECRET",
        "CAPITAL_ENV": "DEMO",
        "FOKUS_SUPABASE_URL": "https://fake.supabase.co",
        "FOKUS_SUPABASE_SECRET_KEY": "SYNTHETIC_NOT_REAL_SECRET",
    }


def test_next_minute_scan_is_scheduled_after_close_and_does_not_overlap():
    assert seconds_until_next_m1_scan(
        datetime(2026,11,9,16,25,4,tzinfo=timezone.utc))==4.0
    assert seconds_until_next_m1_scan(
        datetime(2026,11,9,16,25,9,tzinfo=timezone.utc))==59.0
    assert seconds_until_next_m1_scan(
        datetime(2026,11,9,16,25,8,tzinfo=timezone.utc))==60.0
    with pytest.raises(ValueError):
        seconds_until_next_m1_scan(datetime(2026,11,9,16,25,8))


def test_pc_launcher_requires_owner_clock_confirmation_not_fake_default(tmp_path):
    env=_env()
    del env["FOKUS_CANDLE_TIME_CONFIRMED"]
    with pytest.raises(ValueError,match="FOKUS_CANDLE_TIME_CONFIRMED"):
        prepare_pc_environment(folder=tmp_path,environ=env)


def test_pc_launcher_only_demo_and_uses_existing_cloud_checkpoint(tmp_path):
    env=_env()
    result=prepare_pc_environment(folder=tmp_path,environ=env)
    assert result["FOKUS_PAPER_ALIGN_MINUTE"]=="true"
    assert result["FOKUS_PAPER_SCAN_INTERVAL_SECONDS"]=="60"
    assert validated_worker_args(result)[-1]=="--align-minute"
    assert result["FOKUS_SUPABASE_SECRET_KEY"]==env["FOKUS_SUPABASE_SECRET_KEY"]
    env["CAPITAL_ENV"]="LIVE"
    with pytest.raises(ValueError,match="LIVE disabled"):
        prepare_pc_environment(folder=tmp_path,environ=env)


def test_local_toml_is_read_once_without_echoing_password(tmp_path):
    folder=tmp_path/".streamlit"
    folder.mkdir()
    (folder/"secrets.toml").write_text('''
CAPITAL_API_KEY = "VERY_PRIVATE_KEY"
CAPITAL_IDENTIFIER = "user@example.test"
CAPITAL_PASSWORD = "VERY_PRIVATE_PASSWORD"
CAPITAL_ENV = "DEMO"
FOKUS_SUPABASE_URL = "https://fake.supabase.co"
FOKUS_SUPABASE_SECRET_KEY = "PRIVATE_SUPABASE_KEY_TOO"
FOKUS_PAPER_WORKER_ENABLED = true
FOKUS_CANDLE_TIME_CONFIRMED = "open"
''',encoding="utf-8")
    values=prepare_pc_environment(folder=tmp_path,environ={})
    assert values["CAPITAL_API_KEY"]=="VERY_PRIVATE_KEY"
    assert values["FOKUS_PAPER_WORKER_ENABLED"]=="true"
    assert values["FOKUS_PAPER_ALIGN_MINUTE"]=="true"
    assert "VERY_PRIVATE" not in str(validated_worker_args(values))


def test_bat_does_not_include_secrets_or_disable_bls():
    root=Path(__file__).resolve().parents[1]
    bat=(root/"URUCHOM_SCALPING_M1_PAPER.bat").read_text(encoding="utf-8")
    code=(root/"trader/windows_scalping.py").read_text(encoding="utf-8")
    assert "trader.windows_scalping" in bat
    assert "--skip-macro-calendar" not in bat
    assert "--skip-macro-calendar" not in code
    assert "FOKUS_CANDLE_TIME_CONFIRMED" in code
    assert ".streamlit/secrets.toml" in (root/".gitignore").read_text(encoding="utf-8")
