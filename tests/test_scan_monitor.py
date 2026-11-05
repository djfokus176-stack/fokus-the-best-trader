"""Scanner log: data freshness, API success, and new candles must not be confused."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from trader.scan_monitor import scan_event, append_scan_log


def snapshot(t,good=True):
    return SimpleNamespace(confirmed_utc=t,good=good)


def test_initial_scan_not_same_as_new_increment():
    now=datetime(2026,11,4,21,57,tzinfo=timezone.utc)
    e=scan_event('STARTUP',None,snapshot(now))
    assert e['api_result']=='OK'
    assert e['bar_result']=='INITIAL_DATA'


def test_successful_api_while_market_is_closed():
    now=datetime(2026,11,4,22,4,tzinfo=timezone.utc)
    earlier=now-timedelta(minutes=6)
    e=scan_event('AUTO',snapshot(earlier),snapshot(earlier,good=False),
        market_status='CLOSED',requested_utc=now)
    assert e['api_result']=='OK'
    assert e['new_candle'] is False
    assert e['market_status']=='CLOSED'
    assert e['bar_result']=='STALE_OR_BLOCKED'


def test_new_closed_candle_and_no_new_candle():
    now=datetime(2026,11,4,21,45,tzinfo=timezone.utc)
    old=snapshot(now)
    new=snapshot(now+timedelta(minutes=1))
    assert scan_event('AUTO',old,new)['new_candle']
    assert not scan_event('AUTO',old,old)['new_candle']


def test_error_does_not_mean_success():
    e=scan_event('AUTO',None,None,error='HTTP 429')
    assert e['api_result']=='ERROR'
    assert e['bar_result']=='ERROR'
    assert e['error']=='HTTP 429'


def test_scan_log_bounded():
    history=[]
    for k in range(80):
        history=append_scan_log(history,{'attempt':k},limit=30)
    assert len(history)==30
    assert history[0]['attempt']==50


def test_quarantined_snapshot_reports_partial_data_without_new_signal():
    from types import SimpleNamespace
    t=datetime(2026,11,5,21,10,tzinfo=timezone.utc)
    bad=SimpleNamespace(confirmed_utc=t,good=False,reason='DANE_WADLIWE: bid > ask')
    event=scan_event('AUTO',None,bad)
    assert event['api_result']=='PARTIAL_DATA'
    assert event['bar_result']=='DATA_QUARANTINED'
    assert event['new_candle'] is False


def test_repeated_poll_without_new_bar_compacts_diagnostic_history():
    t=datetime(2026,11,5,21,10,tzinfo=timezone.utc)
    old=snapshot(t)
    state=[]
    for n in range(20):
        state=append_scan_log(state,scan_event('AUTO',old,old,
            requested_utc=t+timedelta(seconds=n*5)))
    assert len(state)==1
    assert state[0]['repeats']==20
    failed=scan_event('AUTO',old,None,error='bad quote')
    state=append_scan_log(state,failed)
    assert len(state)==2 and state[-1]['api_result']=='ERROR'
