"""The cloud UI must not present a missing local snapshot as a cloud failure."""
from pathlib import Path


def test_cloud_mode_explains_empty_local_chart_without_false_no_data():
    app=Path("app.py").read_text(encoding="utf-8")
    assert "if remote_paper_view_enabled():" in app
    assert "TRYB CLOUD: ten STARY wykres lokalny jest celowo" in app
    assert "To NIE oznacza braku świec z Northflank." in app
    assert "Aktualny CLOUD M15 i osobny podgląd BID/ASK ~5S" in app
    # Direct browser Capital authentication must stay disabled in remote.
    assert "st.session_state['auto_scan_active']=False" in app


def test_documented_quote_source_is_readonly_and_not_paper_executor():
    market=Path("trader/market.py").read_text(encoding="utf-8")
    assert "params={'epics':epic}" in market
    assert "raise FeedError('Bieżąca cena: brak jednoznacznego rynku EPIC')" in market
    worker=Path("trader/cloud_scalp_quotes.py").read_text(encoding="utf-8")
    assert "client.market_quote(epic)" in worker
    assert "remote.upsert_live_quote(record)" in worker
    assert "queue_paper(" not in worker
