"""Testy raportu zegara świec (tylko odczyt, dane SYNTETYCZNE)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from trader import candle_clock_check as cc


def _bar(stamp, bid_o=7330.0, ask_o=7330.6, crossed=False):
    b_o, a_o = (bid_o, ask_o) if not crossed else (ask_o, bid_o)  # crossed -> bid > ask
    def blk(b, a):
        return {"bid": b, "ask": a}
    return {
        "snapshotTimeUTC": stamp,
        "openPrice": blk(b_o, a_o + 0.0),
        "highPrice": blk(b_o + 1, a_o + 1),
        "lowPrice": blk(b_o - 1, a_o - 1),
        "closePrice": blk(b_o + 0.5, a_o + 0.5),
    }


def test_crossed_bar_is_flagged_not_dropped():
    payload = {"prices": [_bar("2026-11-06T15:23:00", crossed=True), _bar("2026-11-06T15:24:00")]}
    recs = cc.build_records(payload, now_utc=pd.Timestamp("2026-11-06T15:30:00Z"))
    assert len(recs) == 2
    crossed = [r for r in recs if r["crossed_bid_gt_ask"]]
    assert len(crossed) == 1 and crossed[0]["stamp_utc"].startswith("2026-11-06T15:23")


def test_bid_ask_mid_are_reported_separately():
    payload = {"prices": [_bar("2026-11-06T15:24:00", bid_o=7330.0, ask_o=7331.0)]}
    rec = cc.build_records(payload, now_utc=pd.Timestamp("2026-11-06T15:30:00Z"))[0]
    assert rec["BID"]["open"] == 7330.0 and rec["ASK"]["open"] == 7331.0
    assert rec["MID"]["open"] == pytest.approx(7330.5)


def test_in_progress_and_finished_are_distinguished():
    payload = {"prices": [_bar("2026-11-06T15:23:00"), _bar("2026-11-06T15:24:00"), _bar("2026-11-06T15:25:00")]}
    recs = cc.build_records(payload, now_utc=pd.Timestamp("2026-11-06T15:25:30Z"))
    by = {r["stamp_utc"][11:16]: r for r in recs}
    assert by["15:23"]["finished"] and not by["15:23"]["in_progress"]
    assert by["15:24"]["finished"]
    assert by["15:25"]["in_progress"] and not by["15:25"]["finished"]


def test_warsaw_time_is_dst_aware():
    summer = {"prices": [_bar("2026-07-01T10:00:00")]}
    winter = {"prices": [_bar("2026-11-06T15:24:00")]}
    s = cc.build_records(summer, now_utc=pd.Timestamp("2026-12-01T00:00:00Z"))[0]
    w = cc.build_records(winter, now_utc=pd.Timestamp("2026-12-01T00:00:00Z"))[0]
    assert s["stamp_warsaw"].startswith("2026-07-01 12:00:00") and "CEST" in s["stamp_warsaw"]
    assert w["stamp_warsaw"].startswith("2026-11-06 16:24:00") and "CET" in w["stamp_warsaw"]


def test_invalid_stamp_is_kept_as_error_record():
    payload = {"prices": [{"snapshotTimeUTC": "nie-data"}, _bar("2026-11-06T15:24:00")]}
    recs = cc.build_records(payload, now_utc=pd.Timestamp("2026-11-06T15:30:00Z"))
    assert len(recs) == 2  # malformed date must remain as an error record
    assert cc.summarize(recs)["liczba_etykiet"] == 1
    assert cc.summarize(recs)["bledne_rekordy"] == 1


def test_report_writes_json_and_txt_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPITAL_API_KEY", "SEKRET-KLUCZ-123")
    monkeypatch.setenv("CAPITAL_PASSWORD", "SEKRET-HASLO-456")
    recs = cc.build_records({"prices": [_bar("2026-11-06T15:24:00")]}, now_utc=pd.Timestamp("2026-11-06T15:30:00Z"))
    jp, tp = cc.write_report(tmp_path, epic="US500", resolution="MINUTE",
                             observations=None, payload_records_by_sample=[recs])
    text = Path(jp).read_text(encoding="utf-8") + Path(tp).read_text(encoding="utf-8")
    assert "SEKRET" not in text
    doc = json.loads(Path(jp).read_text(encoding="utf-8"))
    assert doc["read_only"] is True and "Etykiety NIE są przesunięte" in doc["uwaga"]


class _FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def raw_candle_payload(self, epic="US500", resolution="MINUTE", count=8):
        self.calls += 1
        return self.payloads.pop(0)


def test_two_samples_are_about_65_seconds_apart(tmp_path):
    sleeps = []
    client = _FakeClient([{"prices": [_bar("2026-11-06T15:23:00")]}, {"prices": [_bar("2026-11-06T15:24:00")]}])
    out = cc.run_report(client, epic="US500", samples=2, report_dir=str(tmp_path),
                        sleep=lambda s: sleeps.append(s), emit=lambda *_: None)
    assert sleeps == [65] and client.calls == 2 and len(out) == 2


def test_cli_accepts_report_dir():
    parser_src = Path(cc.__file__).read_text(encoding="utf-8")
    assert "--report-dir" in parser_src


def test_missing_prices_not_crossed_and_nan_json_is_standard(tmp_path):
    bar = _bar("2026-11-06T15:24:00")
    del bar["lowPrice"]["ask"]
    bar["highPrice"]["bid"] = float("inf")
    rec = cc.build_records({"prices":[bar]},now_utc=pd.Timestamp("2026-11-06T15:30:00Z"))[0]
    assert rec["crossed_bid_gt_ask"] is False
    assert set(rec["invalid_price_fields"]) == {"high","low"}
    assert rec["MID"]["high"] is None
    jp,tp=cc.write_report(tmp_path,epic="US500",resolution="MINUTE",
        observations=["2026-11-06T15:30:00+00:00"],payload_records_by_sample=[[rec]])
    body=jp.read_text(encoding="utf8")
    assert "NaN" not in body and "Infinity" not in body
    assert "NIEPOPRAWNA CENA" in tp.read_text(encoding="utf8")


def test_report_bid_ask_mid_full_ohlc_and_unconfirmed_open(tmp_path):
    recs=cc.build_records({"prices":[_bar("2026-11-06T15:24:00")]},
        now_utc=pd.Timestamp("2026-11-06T15:30:00Z"))
    jp,tp=cc.write_report(tmp_path,epic="US500",resolution="MINUTE",
        observations=["2026-11-06T15:30:00+00:00"],payload_records_by_sample=[recs])
    report=tp.read_text(encoding="utf8")
    assert all(f"{side}: O=" in report for side in ("BID","ASK","MID"))
    assert "ZAKOŃCZONA JEŚLI OPEN" in report
    assert "nie potwierdza" in report
    assert "MOMENT ODCZYTU UTC" in report
    assert json.loads(jp.read_text(encoding="utf8"))["clock_confirmed"] is False


def test_invalid_timestamp_retained_in_report(tmp_path):
    recs=cc.build_records({"prices":[{"snapshotTimeUTC":"invalid"},
        _bar("2026-11-06T15:24:00")]},
        now_utc=pd.Timestamp("2026-11-06T15:30:00Z"))
    assert len(recs)==2
    assert cc.summarize(recs)["bledne_rekordy"]==1
    jp,tp=cc.write_report(tmp_path,epic="US500",resolution="MINUTE",
        observations=None,payload_records_by_sample=[recs])
    assert "NIEPRAWIDLOWY_CZAS" in tp.read_text(encoding="utf8")
    assert len(json.loads(jp.read_text(encoding="utf8"))["proby"][0])==2


def test_naive_timestamp_fails_explicitly():
    with pytest.raises(ValueError,match="strefy"):
        cc.build_records({"prices":[_bar("2026-11-06T15:24:00")]},
            now_utc=pd.Timestamp("2026-11-06T15:30:00"))
