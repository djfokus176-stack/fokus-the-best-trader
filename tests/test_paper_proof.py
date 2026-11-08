"""Read-only cloud PAPER proof must not count synthetic code tests as evidence."""
from trader.paper_proof import paper_proof


def test_empty_ledger_explicitly_unproven():
    record=paper_proof({"tables":{"paper_positions_v3":[],
                                   "paper_events_v3":[]}})
    assert record["status"]=="NOT_PROVEN"
    assert record["verified_cycles"]==0


def test_one_real_sequence_verifies_event_timestamps():
    tid="test-only"
    pos={"trade_id":tid,"epic":"US500","source":"Capital.com DEMO REST",
         "side":"LONG","status":"CLOSED_TP","pnl_pts":2.5,
         "entry_detected_utc":"2026-11-09T20:02:05+00:00"}
    events=[{"trade_id":tid,"kind":k,"candle_utc":t} for k,t in [
        ("LONG_SETUP","2026-11-09T20:00:00+00:00"),
        ("PAPER_OPEN","2026-11-09T20:01:00+00:00"),
        ("PAPER_CLOSE_TP","2026-11-09T20:03:00+00:00")]]
    report=paper_proof({"tables":{"paper_positions_v3":[pos],
                                  "paper_events_v3":events}})
    assert report["verified_cycles"]==1
    assert report["status"]=="OBSERVED_COMPLETE_PAPER_CYCLE"
    report_without_open=paper_proof({"tables":{"paper_positions_v3":[pos],
                                              "paper_events_v3":[events[0],events[2]]}})
    assert report_without_open["verified_cycles"]==0
    assert report_without_open["incomplete_closed"]==1


def test_invalid_or_foreign_source_does_not_prove_cfd_cycle():
    d={"trade_id":"x","epic":"US500","source":"CSV NAUKA (NIE LIVE)",
       "side":"SHORT","status":"CLOSED_SL","pnl_pts":1.0}
    assert paper_proof({"tables":{"paper_positions_v3":[d],
                                  "paper_events_v3":[]}})["counts"]["CLOSED"]==0
