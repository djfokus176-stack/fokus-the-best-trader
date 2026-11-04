"""Guard against accidental Streamlit magic rendering in UI sidebar."""
from pathlib import Path
import ast
import tomllib

ROOT = Path(__file__).resolve().parents[1]

def test_streamlit_magic_is_disabled():
    with (ROOT / ".streamlit" / "config.toml").open("rb") as f:
        config = tomllib.load(f)
    assert config["runner"]["magicEnabled"] is False

def test_no_ternary_expression_with_streamlit_ui_calls():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.IfExp):
            assert not any(
                isinstance(x, ast.Call)
                and isinstance(x.func, ast.Attribute)
                and isinstance(x.func.value, ast.Name)
                and x.func.value.id == "st"
                for x in ast.walk(node.value)
            ), "Avoid st.success(...) if condition else st.warning(...) expression"
