"""Repository upload safety regressions.

Prevent accidentally uploading hundreds of tests to repository root or
committing private configuration/local SQLite checkpoints. These checks
do not access customer data, secrets or Capital.com.
"""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_test_modules_live_only_under_tests_directory():
    root_tests=sorted(p.name for p in ROOT.glob("test_*.py") if p.is_file())
    assert not root_tests, (
        "Unexpected duplicate tests at repository root: "+", ".join(root_tests[:12]))


def test_private_runtime_files_are_not_in_source_checkout():
    # README examples and the verified, public macro-calendar JSON are fine.
    forbidden=[
        ROOT/".env",
        ROOT/".streamlit"/"secrets.toml",
        ROOT/"data"/"fokus_paper.sqlite3",
        ROOT/"data"/"fokus_paper.db",
    ]
    assert not [str(p.relative_to(ROOT)) for p in forbidden if p.exists()]
    leaked=[str(p.relative_to(ROOT)) for p in ROOT.rglob("*.sqlite3")
            if ".git" not in p.parts and p.is_file()]
    assert not leaked, "Local SQLite databases must not be committed"
