"""A recent heartbeat must not turn stale votes or a WAIT into fake trading."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trader.worker_signal_diagnostics import verified_auto_wait_diagnosis
from trader.worker_trade_audit import redacted_archive_log_line, read_only_archive_counts
from trader.strategies_pro import ALL_STRATEGIES

NOW = datetime(2026,11,20,15,0,tzinfo=timezone.utc)
CANDLE = "2026-11-20T14:59:00+00:00"


def packet(votes, *, decision="WAIT", candle=CANDLE, gates="OK"):
    return {
        "schema":1,
        "meta":{
            "last_scan_utc":NOW.isoformat(),
            "last_scan_summary":f"{candle} / {decision} / "
                f"CANDIDATE_METHOD={decision} / QUEUE=NO / "
                f"ACTIVE=NONE / GATES={gates} / diagnostic",
            "source":"Capital.com DEMO REST",
            "epic":"US500", "strategy":"AUTO — 6 STRATEGII",
            "auto_virtual_daily_brake_enabled":False,
        },
        "last_vote_audit":{
            "candle_utc":candle,"source":"Capital.com DEMO REST",
            "epic":"US500","mode":"AUTO — 6 STRATEGII",
            "decision":decision,
            "rows":[{
                "strategy":s,
                "raw":votes.get(s,("WAIT","WAIT"))[0],
                "after_mtf":votes.get(s,("WAIT","WAIT"))[1],
                "reason":"test",
            } for s in ALL_STRATEGIES],
            "progress":[{
                "strategy":s,"stage":2,"progress":"2/3",
                "side":"LONG","criteria":[
                    {"ok":True,"name":"Trend"},
                    {"ok":True,"name":"Early"},
                    {"ok":False,"name":"Third"},
                ],
            } for s in ALL_STRATEGIES],
            "mtf":[{
                "timeframe":tf,"ready":True,"trend":"UP",
                "reason":"OK","candle_utc":candle
            } for tf in ("MINUTE","MINUTE_5","MINUTE_15","HOUR")],
        },
        "tables":{"paper_positions_v3":[]},
    }


def test_no_raw_setup_explains_healthy_but_inactive_bot():
    payload=packet({})
    d=verified_auto_wait_diagnosis(payload,now=NOW)
    assert d["vote_audit"]=="CURRENT"
    assert d["raw_long"]==0 and d["raw_short"]==0
    assert d["mtf_veto"]==0
    assert d["mtf_ready"]==4 and d["mtf_missing"]==0
    assert d["stage_2"]==6
    assert d["auto_wait_reason"]=="NO_RAW_SETUP"
    row=read_only_archive_counts(payload,now=NOW)
    assert row["auto_wait_reason"]=="NO_RAW_SETUP"
    assert row["auto_opened"]==0
    assert "AUTO_WAIT_REASON=NO_RAW_SETUP" in redacted_archive_log_line(payload,now=NOW)


def test_mtf_veto_is_not_labeled_no_signal():
    v={ALL_STRATEGIES[0]:("SHORT","WAIT")}
    result=verified_auto_wait_diagnosis(packet(v),now=NOW)
    assert result["raw_short"]==1 and result["mtf_short"]==0
    assert result["mtf_veto"]==1
    assert result["auto_wait_reason"]=="MTF_REJECTED_RAW"


def test_conflicting_long_short_is_explicit():
    votes={ALL_STRATEGIES[0]:("LONG","LONG"),
           ALL_STRATEGIES[1]:("SHORT","WAIT")}
    d=verified_auto_wait_diagnosis(packet(votes),now=NOW)
    assert d["raw_conflict"]=="YES"
    assert d["auto_wait_reason"]=="RAW_LONG_SHORT_CONFLICT"


def test_stale_earlier_vote_is_not_today_signal():
    p=packet({ALL_STRATEGIES[0]:("LONG","LONG")})
    p["last_vote_audit"]["candle_utc"]=(NOW-timedelta(minutes=20)).isoformat()
    d=verified_auto_wait_diagnosis(p,now=NOW)
    assert d["vote_audit"]=="UNVERIFIED"
    assert d["raw_long"]=="UNKNOWN"
    assert d["auto_wait_reason"]=="NO_CURRENT_VOTES"
    p=packet({ALL_STRATEGIES[0]:("LONG","LONG")})
    p["meta"]["last_scan_summary"]="WAIT / DATA_STALE / invalid quote"
    d=verified_auto_wait_diagnosis(p,now=NOW)
    assert d["vote_audit"]=="UNVERIFIED"
    assert d["raw_long"]=="UNKNOWN"


def test_audit_is_read_only_and_never_leaks_trade_details_or_secrets():
    p=packet({ALL_STRATEGIES[0]:("LONG","WAIT")})
    p["CAPITAL_API_KEY"]="not-a-real-key"
    out=redacted_archive_log_line(p,now=NOW)
    assert "not-a-real-key" not in out
    assert "AUTO_WAIT_REASON=MTF_REJECTED_RAW" in out
    source=Path("trader/worker_signal_diagnostics.py").read_text("utf8")
    assert "queue_paper" not in source
    assert "remote.save" not in source
    assert "CapitalReadOnly" not in source
