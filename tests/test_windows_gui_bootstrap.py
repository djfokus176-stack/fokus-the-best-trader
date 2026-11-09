"""Windows GUI launcher must install its OWN GUI dependencies on a fresh ZIP.

Static batch invariants (GitHub CI runs on Linux and cannot execute .bat).
"""
from pathlib import Path


def test_gui_windows_launcher_fresh_zip_and_worker_only_venv():
    root=Path(__file__).resolve().parents[1]
    script=(root/"start_windows.bat").read_text("utf-8")
    assert 'if not exist ".venv\\Scripts\\python.exe"' in script
    assert '-m venv ".venv"' in script
    assert "import streamlit,pandas,numpy,plotly,requests,openai" in script
    assert "-m pip install -r requirements.txt" in script
    assert "pip install -r requirements-worker.txt" not in script
    assert "-m streamlit run app.py" in script
    assert "--server.port 8501" in script


def test_gui_launcher_does_not_override_paper_gates_or_echo_secrets():
    root=Path(__file__).resolve().parents[1]
    script=(root/"start_windows.bat").read_text("utf-8")
    assert "FOKUS_CANDLE_TIME_CONFIRMED" not in script
    assert "FOKUS_PAPER_WORKER_ENABLED" not in script
    assert "--skip-macro-calendar" not in script
    assert "CAPITAL_PASSWORD" not in script
    assert "Missing" not in script or "APP_ACCESS_PASSWORD" not in script
    assert "pause" in script
    assert "BLAD" in script
