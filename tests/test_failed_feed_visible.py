"""Visible fail-closed diagnostics even when the chart cannot render."""
from pathlib import Path


def test_bad_ohlc_displays_reason_and_worker_status():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "if not snap.good:" in app
    assert "SZCZEGÓŁY BŁĘDU DANYCH I WORKERA" in app
    assert "Capital.com nie dostarczył pełnego, zweryfikowanego" in app
    assert "Nie twierdzę, że worker działa." in app
    assert "st.write('Powód odmowy danych:',snap.reason)" in app


def test_never_relax_real_market_safety_to_satisfy_ui():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    worker=(Path(__file__).resolve().parents[1]/"trader"/"worker.py").read_text(encoding="utf-8")
    assert "FOKUS_CANDLE_TIME_CONFIRMED" in app
    assert "candle_time_ok=os.getenv(" in worker
    assert "if not main.good:" in worker
    assert "status!=\"TRADEABLE\"" in worker
    assert 'if errors or not all(v.ready for v in views):' in worker
