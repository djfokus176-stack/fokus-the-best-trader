"""Prevent an app-level ImportError from shipping without CI detection.

Streamlit Cloud may run a stale deployed module. This smoke test validates
every import from trader.* at the module header without invoking Streamlit's
UI code or requiring broker credentials.
"""
from __future__ import annotations
import ast
import importlib
from pathlib import Path


def test_all_app_trader_imports_resolve_without_running_app():
    source=Path("app.py").read_text(encoding="utf-8")
    tree=ast.parse(source)
    checked=0
    for stmt in tree.body:
        if not isinstance(stmt, ast.ImportFrom):
            continue
        if not stmt.module or not stmt.module.startswith("trader."):
            continue
        module=importlib.import_module(stmt.module)
        for alias in stmt.names:
            assert hasattr(module,alias.name), (
                f"app.py wants {stmt.module}.{alias.name}, but export missing")
            checked+=1
    assert checked>=55


def test_early_watch_renderer_exists_on_current_main():
    from trader.early_watch import evaluate_early_watch,annotate_watch_markers
    assert callable(evaluate_early_watch)
    assert callable(annotate_watch_markers)
