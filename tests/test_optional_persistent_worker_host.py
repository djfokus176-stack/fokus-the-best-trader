"""Unconfigured always-on worker must NEVER start trading or leak secrets."""
import pytest
from trader.worker_service import validated_worker_args, main


def configured():
    return {
        "FOKUS_PAPER_WORKER_ENABLED":"true",
        "FOKUS_CANDLE_TIME_CONFIRMED":"open",
        "FOKUS_SUPABASE_URL":"https://fake.supabase.co",
        "FOKUS_SUPABASE_SECRET_KEY":"synthetic-not-a-real-key",
        "CAPITAL_API_KEY":"synthetic",
        "CAPITAL_IDENTIFIER":"synthetic",
        "CAPITAL_PASSWORD":"synthetic",
        "CAPITAL_ENV":"DEMO",
    }


def test_missing_optin_fails_closed():
    env=configured();env["FOKUS_PAPER_WORKER_ENABLED"]="false"
    with pytest.raises(ValueError,match="opt-in"):
        validated_worker_args(env)


def test_missing_durable_db_fails_closed():
    env=configured();env.pop("FOKUS_SUPABASE_SECRET_KEY")
    with pytest.raises(ValueError,match="durable"):
        validated_worker_args(env)


def test_no_real_trading_environment():
    env=configured();env["CAPITAL_ENV"]="LIVE"
    with pytest.raises(ValueError,match="LIVE disabled"):
        validated_worker_args(env)


def test_clock_gate_cannot_be_bypassed():
    env=configured();env.pop("FOKUS_CANDLE_TIME_CONFIRMED")
    with pytest.raises(ValueError,match="verified"):
        validated_worker_args(env)


@pytest.mark.parametrize("interval",["0","5","59","601","abc"])
def test_interval_boundaries_fail_closed(interval):
    env=configured();env["FOKUS_PAPER_SCAN_INTERVAL_SECONDS"]=interval
    with pytest.raises(ValueError):
        validated_worker_args(env)


def test_deployment_args_are_bounded():
    env=configured();env["FOKUS_PAPER_SCAN_INTERVAL_SECONDS"]="65"
    assert validated_worker_args(env)==[
        "--interval","65","--epic","US500","--tf","MINUTE"]


def test_no_credentials_exposed_on_startup_refusal(monkeypatch,capsys):
    monkeypatch.setenv("CAPITAL_PASSWORD","TOP_SECRET_NOT_IN_OUTPUT")
    monkeypatch.delenv("FOKUS_PAPER_WORKER_ENABLED",raising=False)
    assert main()==2
    assert "TOP_SECRET_NOT_IN_OUTPUT" not in capsys.readouterr().err


def test_host_uses_exact_same_worker_strategy_loop(monkeypatch,capsys):
    from trader import worker_service
    env=configured()
    for k,v in env.items():monkeypatch.setenv(k,v)
    actual=[]
    monkeypatch.setattr(worker_service.worker,"main",lambda args:actual.append(args))
    assert main()==0
    assert actual and actual[0][:2]==["--interval","65"]
    assert "DEMO" in capsys.readouterr().out
