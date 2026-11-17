"""Regression: CLOUD owner display must not create a second Capital login."""
from pathlib import Path

import pytest

from trader.cloud_mode_safety import local_scan_permitted


@pytest.mark.parametrize("manual,initial,scheduled",[
    (False,False,False), (True,False,False),
    (False,True,False), (False,False,True),
    (True,True,True),
])
def test_cloud_mode_never_allows_legacy_broker_scan(manual,initial,scheduled):
    assert local_scan_permitted(
        cloud_mode=True,manual=manual,initial=initial,
        scheduled=scheduled) is False


@pytest.mark.parametrize("manual,initial,scheduled,expected",[
    (False,False,False,False),
    (True,False,False,True),
    (False,True,False,True),
    (False,False,True,True),
])
def test_local_replay_still_permitted_outside_cloud(manual,initial,scheduled,expected):
    assert local_scan_permitted(
        cloud_mode=False,manual=manual,initial=initial,
        scheduled=scheduled) is expected


def test_streamlit_uses_guard_and_disables_ui_sources_of_http_401():
    code=Path("app.py").read_text(encoding="utf-8")
    assert "local_scan_permitted(" in code
    assert "cloud_mode=remote_paper_view_enabled(),manual=load" in code
    assert "disabled=cloud_owner_display" in code
    assert "disabled=cloud_read_only_mode" in code
    assert "st.session_state.pop(key,None)" in code
    assert "Lokalne logowanie Capital.com jest wyłączone." in code
    assert "render_cloud_terminal(secret,tf)" in code
    assert "render_cloud_scalp_5s(secret)" in code


def test_pending_setup_is_not_sounded_as_open_and_cloud_voice_kept():
    code=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf-8")
    assert "render_cloud_paper_voice(remote,url=url)" in code
    assert 'pos.get("status")=="PENDING"' in code
    assert "Głos LONG/SHORT zabrzmi dopiero po nowym" in code
    assert 'annotate_paper_history(candles,chart_paper' in code
    assert "queue_paper(" not in code
