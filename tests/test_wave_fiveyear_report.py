"""Five-year WAVE report is genuine and never promotes research to trading."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import zipfile

import pandas as pd
import pytest

import trader.wave_fiveyear_report as wave
from trader.wave_fiveyear_report import (
    REFERENCE_ANCHORS,REFERENCE_BARS,load_reference_ranking,
    load_wave_fiveyear_bundle,
)


def _zip_parts(*, source=b"synthetic-candle-source",corrupt=False,
               bad_status=False,omit=None,duplicate=False):
    frame=load_reference_ranking()
    if corrupt:
        frame.loc[0,"NETTO_OOS"]=-1.
    if bad_status:
        frame.loc[0,"STATUS"]="ZWERYFIKOWANA LIVE"
    meta={
        "input_sha256":hashlib.sha256(source).hexdigest(),
        "input_rows":REFERENCE_BARS,
        "waves_meta":{"anchors":REFERENCE_ANCHORS},
        "verified_positive_out_of_sample_edge":False,
        "trading_permission":"WAIT",
    }
    quality={
        "crossed_rows":0,"quarantined_rows":0,
        "retained_rows":REFERENCE_BARS,"no_price_correction":True,
    }
    pieces={
        "FOKUS_WAVE_M15_5_LAT_BID_ASK.csv":source,
        "FOKUS_WAVE_M15_5_LAT_BID_ASK.quality.json":
            json.dumps(quality).encode(),
        "WAVE_5Y_RESULTS/WAVE_5Y_MANIFEST.json":
            json.dumps(meta).encode(),
        "WAVE_5Y_RESULTS/WAVE_5Y_RANKING.csv":
            frame.to_csv(index=False).encode(),
        "WAVE_5Y_RESULTS/WAVE_5Y_YEARS.csv":
            b"year,net_pts\n2022,-10\n",
        "WAVE_5Y_RESULTS/WAVE_5Y_HOURS.csv":
            b"hour_et,n,net_pts\n14,2,-4\n",
    }
    if omit:
        pieces.pop(omit)
    out=BytesIO()
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in pieces.items():
            z.writestr(name,data)
        if duplicate:
            z.writestr("WAVE_5Y_RESULTS/WAVE_5Y_RANKING.csv",
                       frame.to_csv(index=False).encode())
    return out.getvalue(),source


def test_frozen_reference_is_real_ten_rows_and_not_verified():
    r=load_reference_ranking()
    assert len(r)==10
    assert set(r.INTERWAL)=={"M15"}
    assert set(r.LONG_SHORT)=={"SHORT","LONG"}
    assert set(r.FORMACJA)=={
        "A_RAW","B_BOS","C_BOS_RETEST","D_BREAKOUT_HOLD","E_WAIT"}
    winners=r[(r.PROBY_OOS>0)]
    assert len(winners)==7
    assert (winners.NETTO_OOS<0).all()
    assert (winners.PF_OOS<1).all()
    assert (r.loc[r.FORMACJA=="E_WAIT","PROBY_OOS"]==0).all()
    assert "ZWERYFIKOWANA" not in " ".join(r.STATUS.astype(str))


def test_zip_verifies_real_candle_digest_and_audit_manifest(monkeypatch):
    blob,source=_zip_parts()
    monkeypatch.setattr(
        wave,"REFERENCE_SOURCE_SHA256",hashlib.sha256(source).hexdigest())
    result=load_wave_fiveyear_bundle(blob)
    assert result["sha256"]==hashlib.sha256(source).hexdigest()
    assert len(result["ranking"])==10
    assert set(result["tables"])=={"years","hours"}
    assert result["verified_alpha"] is False
    assert result["trade_permission"]=="WAIT"


def test_bundle_rejects_unexpected_or_changed_source_sha():
    blob,_=_zip_parts()
    with pytest.raises(ValueError,match="zatwierdzony"):
        load_wave_fiveyear_bundle(blob)


def test_zip_rejects_changed_performance_and_auto_promotion(monkeypatch):
    good,source=_zip_parts()
    monkeypatch.setattr(
        wave,"REFERENCE_SOURCE_SHA256",hashlib.sha256(source).hexdigest())
    modified,_=_zip_parts(corrupt=True)
    with pytest.raises(ValueError,match="nie zgadza"):
        load_wave_fiveyear_bundle(modified)
    invalid,_=_zip_parts(bad_status=True)
    with pytest.raises(ValueError,match="LIVE"):
        load_wave_fiveyear_bundle(invalid)


def test_missing_files_or_duplicate_zip_path_rejected(monkeypatch):
    good,source=_zip_parts()
    monkeypatch.setattr(
        wave,"REFERENCE_SOURCE_SHA256",hashlib.sha256(source).hexdigest())
    missing,_=_zip_parts(omit="WAVE_5Y_RESULTS/WAVE_5Y_MANIFEST.json")
    with pytest.raises(ValueError,match="Niekompletny"):
        load_wave_fiveyear_bundle(missing)
    duplicate,_=_zip_parts(duplicate=True)
    with pytest.raises(ValueError,match="duplikat"):
        load_wave_fiveyear_bundle(duplicate)
    with pytest.raises(ValueError,match="prawidłowym"):
        load_wave_fiveyear_bundle(b"not-zip")


def test_wave_ui_is_separate_from_worker_and_auto_sources():
    root=Path(__file__).resolve().parents[1]
    app=(root/"app.py").read_text(encoding="utf-8")
    assert "render_wave_fiveyear_report()" in app
    source=(root/"trader/wave_fiveyear_ui.py").read_text(encoding="utf-8")
    assert "load_wave_fiveyear_bundle" in source
    assert "st.dataframe" in source
    assert "WAIT" in source
