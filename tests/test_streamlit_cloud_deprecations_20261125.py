"""Cloud compatibility smoke: deprecation cleanup is UI-only.

This project runs on Streamlit Community Cloud; its runtime currently
uses Python 3.14 even though earlier CI only exercised 3.11 and 3.12.
The warnings below were logged thousands of times, obscuring real errors.
"""
from pathlib import Path
import re


ROOT=Path(__file__).resolve().parents[1]


def test_no_deprecated_use_container_width_in_runtime_ui():
    modules=[ROOT/"app.py",*(ROOT/"trader").glob("*.py")]
    found=[]
    for path in modules:
        data=path.read_text(encoding="utf-8")
        if re.search(r"\buse_container_width\s*=",data):
            found.append(str(path.relative_to(ROOT)))
    assert not found, "Legacy Streamlit width args: "+", ".join(found)


def test_candle_clock_retains_browser_only_js_and_uses_native_iframe():
    data=(ROOT/"trader"/"cloud_candle_clock.py").read_text(encoding="utf-8")
    assert "st.iframe(html,height=49)" in data
    assert "Date.now()" in data
    assert "Europe/Warsaw" in data
    assert "setInterval(update,500)" in data
    assert "components.html(" not in data
    assert "CapitalReadOnly(" not in data
    assert "queue_paper(" not in data


def test_live_chart_markers_and_trade_strategy_are_not_rewritten():
    cloud=(ROOT/"trader"/"cloud_paper_terminal.py").read_text(encoding="utf-8")
    assert "annotate_paper_history(candles,chart_paper," in cloud
    assert 'show_labels=True' in cloud
    assert 'chart_mode=="OSTATNIE CLOSE PAPER v3"' in cloud
    assert "queue_paper(" not in cloud
    assert "evaluate_auto(" not in cloud
