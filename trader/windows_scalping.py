"""Windows one-click FOREGROUND M1 PAPER launcher.

Loads a local, Git-ignored Streamlit secrets.toml so the owner need not type
API keys every start. Cloud-hosted Secrets cannot be downloaded by this script.
Requires explicit owner-set PAPER + verified candle clock gates; no LIVE orders.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tomllib


LOCAL_SECRET_KEYS = (
    "CAPITAL_API_KEY",
    "CAPITAL_IDENTIFIER",
    "CAPITAL_PASSWORD",
    "CAPITAL_ENV",
    "FOKUS_SUPABASE_URL",
    "FOKUS_SUPABASE_SECRET_KEY",
    "OPENAI_API_KEY",
    "FOKUS_PAPER_WORKER_ENABLED",
    "FOKUS_CANDLE_TIME_CONFIRMED",
    "FOKUS_PAPER_EXIT_POLICY",
    "FOKUS_AUTO_AI_ENABLED",
    "FOKUS_AUTO_AI_DAILY_LIMIT",
    "FOKUS_AUTO_AI_MONTHLY_LIMIT",
    "FOKUS_AUTO_AI_MODEL",
    "FOKUS_AUTO_AI_INCLUDE_WAIT",
)


def prepare_pc_environment(folder=None, environ=None):
    """Validate secret presence, never return or display private values."""
    from .worker_service import validated_worker_args

    directory = Path(folder) if folder is not None else Path(__file__).resolve().parents[1]
    env = dict(os.environ if environ is None else environ)
    settings = directory / ".streamlit" / "secrets.toml"
    if settings.exists():
        try:
            with settings.open("rb") as fh:
                saved = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            raise ValueError("Nie mozna odczytac lokalnego .streamlit/secrets.toml") from None
        if not isinstance(saved, dict):
            raise ValueError("Niepoprawny lokalny plik Streamlit Secrets")
        for key in LOCAL_SECRET_KEYS:
            if key not in env and isinstance(saved.get(key), (str, int, bool)):
                env[key] = str(saved[key]).lower() if isinstance(saved[key], bool) else str(saved[key])
    missing = [key for key in (
        "CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_PASSWORD",
        "FOKUS_SUPABASE_URL", "FOKUS_SUPABASE_SECRET_KEY",
        "FOKUS_PAPER_WORKER_ENABLED", "FOKUS_CANDLE_TIME_CONFIRMED",
    ) if not env.get(key)]
    if missing:
        raise ValueError("Brakuje lokalnych ustawien: " + ", ".join(missing) +
            ". Klucze z GitHub/Streamlit Cloud nie sa automatycznie dostepne na PC.")
    env.setdefault("FOKUS_PAPER_SCAN_INTERVAL_SECONDS", "60")
    env.setdefault("FOKUS_PAPER_ALIGN_MINUTE", "true")
    validated_worker_args(env)
    return env


def main():
    try:
        env = prepare_pc_environment()
    except ValueError as exc:
        print("PAPER M1 NIE URUCHOMIONY: " + str(exc), file=sys.stderr, flush=True)
        return 2
    for key, value in env.items():
        if key in LOCAL_SECRET_KEYS or key in ("FOKUS_PAPER_SCAN_INTERVAL_SECONDS",
                                              "FOKUS_PAPER_ALIGN_MINUTE"):
            os.environ[key] = value
    from .worker_service import main as start
    print("FOKU$ M1 PAPER — swiece co minute, zapis Supabase, DEMO. "
          "Zamknij to okno, aby zatrzymac. Nie sklada zlecen REAL.", flush=True)
    return start()


if __name__ == "__main__":
    raise SystemExit(main())
