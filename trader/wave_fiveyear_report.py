"""Read-only 2021–2026 WAVE research results, never a strategy approver.

The built-in 10-row report is a frozen, source-attributed snapshot from
GitHub Actions run #43575844127. A user may upload that actual ZIP to
inspect yearly, hour-by-hour and excursion tables. The 70/30 "later"
segment has already been seen; this is NOT independent forward validation.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

import pandas as pd

ROOT=Path(__file__).resolve().parent.parent
REFERENCE=ROOT/"research"/"wave5y_20261114_reference_ranking.csv"
REFERENCE_SOURCE_SHA256="91b8cd6c93f591a008f78bfb71da43fcac12ca07f78289b8715bd3a97e1cb920"
REFERENCE_RUN_ID=43575844127
REFERENCE_BARS=114121
REFERENCE_ANCHORS=1065
REFERENCE_CUTOFF="2025-05-13 15:45:00+00:00"
REQUIRED_RANKING=(
    "FORMACJA","LONG_SHORT","INTERWAL","PROBY_TRAIN","NETTO_TRAIN",
    "PF_TRAIN","PROBY_OOS","NETTO_OOS","PF_OOS","STATUS",
)
BUNDLE_PREFIX="WAVE_5Y_RESULTS/"
EXTRA_CSV={
    "years":"WAVE_5Y_YEARS.csv",
    "hours":"WAVE_5Y_HOURS.csv",
    "probabilities":"WAVE_5Y_PROBABILITIES.csv",
    "features":"WAVE_5Y_FEATURES.csv",
    "exit_grid":"WAVE_5Y_EXIT_GRID.csv",
    "trades":"WAVE_5Y_TRADES_ABCD_WAIT.csv",
}
MAX_ZIP_BYTES=25*1024*1024
MAX_UNCOMPRESSED_BYTES=75*1024*1024


def _validate_ranking(rank:pd.DataFrame) -> pd.DataFrame:
    if rank is None or rank.empty or not set(REQUIRED_RANKING).issubset(rank.columns):
        raise ValueError("Niekompletny ranking WAVE 2021–2026.")
    if len(rank)!=10 or set(rank.LONG_SHORT)!={"LONG","SHORT"}:
        raise ValueError("Ranking WAVE wymaga 10 wierszy LONG i SHORT.")
    for side in ("LONG","SHORT"):
        if set(rank.loc[rank.LONG_SHORT==side,"FORMACJA"])!={
            "A_RAW","B_BOS","C_BOS_RETEST","D_BREAKOUT_HOLD","E_WAIT"}:
            raise ValueError("Zły skład formacji A–E w wynikach.")
    if set(rank.INTERWAL)!={"M15"}:
        raise ValueError("Ranking pięcioletni dotyczy tylko M15.")
    for col in ("PROBY_TRAIN","PROBY_OOS"):
        values=pd.to_numeric(rank[col],errors="coerce")
        if values.isna().any() or (values<0).any():
            raise ValueError("Niepoprawna liczba transakcji WAVE.")
    for col in ("NETTO_TRAIN","NETTO_OOS"):
        values=pd.to_numeric(rank[col],errors="coerce")
        nonwait=rank.FORMACJA!="E_WAIT"
        if values[nonwait & rank["PROBY_"+("TRAIN" if col.endswith("TRAIN") else "OOS")].gt(0)].isna().any():
            raise ValueError("Brakuje netto dla rozliczonych transakcji.")
    # Fail closed if the external bundle tries to promote research to LIVE.
    if rank.STATUS.astype(str).str.contains("ZWERYFIKOWANA|LIVE|AKTYWNA",case=False).any():
        raise ValueError("Historyczne WAVE nie może otrzymać statusu LIVE.")
    return rank


def load_reference_ranking() -> pd.DataFrame:
    return _validate_ranking(pd.read_csv(REFERENCE))


def _guard_archive(z:zipfile.ZipFile) -> set[str]:
    infos=z.infolist()
    if len(infos)>100:
        raise ValueError("Zbyt wiele plików w archiwum WAVE.")
    seen=set()
    cumulative=0
    for info in infos:
        name=info.filename
        if (name.startswith("/") or "\\" in name or
                ".." in Path(name).parts or name in seen):
            raise ValueError("Niebezpieczna nazwa pliku lub duplikat ZIP.")
        seen.add(name)
        cumulative+=info.file_size
        if info.file_size>35*1024*1024 or cumulative>MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Archiwum WAVE przekracza bezpieczny limit rozmiaru.")
    return seen


def _load_csv(z:zipfile.ZipFile,path:str) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(z.read(path)))


def load_wave_fiveyear_bundle(blob:bytes) -> dict:
    """Inspect a user-provided ZIP from GitHub run with exact source hash.

    The ZIP's OHLC CSV is hashed but never loaded into a DataFrame in
    Streamlit. No HTTP calls, database writes, strategy updates or AUTO.
    """
    if not isinstance(blob,bytes) or len(blob)>MAX_ZIP_BYTES:
        raise ValueError("Wgraj ZIP WAVE poniżej 25 MB.")
    try:
        z=zipfile.ZipFile(io.BytesIO(blob))
    except (zipfile.BadZipFile,ValueError) as e:
        raise ValueError("Plik nie jest prawidłowym archiwum ZIP.") from e
    with z:
        names=_guard_archive(z)
        needed={BUNDLE_PREFIX+"WAVE_5Y_RANKING.csv",
                BUNDLE_PREFIX+"WAVE_5Y_MANIFEST.json",
                "FOKUS_WAVE_M15_5_LAT_BID_ASK.csv",
                "FOKUS_WAVE_M15_5_LAT_BID_ASK.quality.json"}
        if not needed.issubset(names):
            raise ValueError("Niekompletny pakiet źródłowych wyników WAVE.")
        meta=json.loads(z.read(BUNDLE_PREFIX+"WAVE_5Y_MANIFEST.json"))
        quality=json.loads(z.read("FOKUS_WAVE_M15_5_LAT_BID_ASK.quality.json"))
        if (meta.get("input_sha256")!=REFERENCE_SOURCE_SHA256 or
                meta.get("input_rows")!=REFERENCE_BARS or
                int((meta.get("waves_meta") or {}).get("anchors",0))!=REFERENCE_ANCHORS or
                meta.get("verified_positive_out_of_sample_edge") is not False or
                meta.get("trading_permission")!="WAIT"):
            raise ValueError("To nie jest zatwierdzony badawczy pakiet WAVE #43575844127.")
        raw_ohlc=z.read("FOKUS_WAVE_M15_5_LAT_BID_ASK.csv")
        if hashlib.sha256(raw_ohlc).hexdigest()!=REFERENCE_SOURCE_SHA256:
            raise ValueError("SHA256 świec nie zgadza się z manifestem badania.")
        if (quality.get("crossed_rows")!=0 or
                quality.get("retained_rows")!=REFERENCE_BARS or
                quality.get("no_price_correction") is not True or
                quality.get("quarantined_rows")!=0):
            raise ValueError("Raport BID/ASK wskazuje niezatwierdzone anomalie.")
        rank=_validate_ranking(_load_csv(z,BUNDLE_PREFIX+"WAVE_5Y_RANKING.csv"))
        reference=load_reference_ranking()
        # Built-in frozen snapshot and imported ZIP must describe exactly
        # the same ten performance observations, ignoring column dtype.
        check=("FORMACJA","LONG_SHORT","PROBY_TRAIN","PROBY_OOS","NETTO_TRAIN","NETTO_OOS")
        if (rank[list(check)].fillna("BRAK").astype(str).to_numpy()!=
                reference[list(check)].fillna("BRAK").astype(str).to_numpy()).any():
            raise ValueError("Ranking ZIP nie zgadza się z opublikowanym badaniem.")
        extras={}
        for key,file in EXTRA_CSV.items():
            path=BUNDLE_PREFIX+file
            if path in names:
                extras[key]=_load_csv(z,path)
        return {
            "ranking":rank,"tables":extras,"manifest":meta,
            "quality":quality,"sha256":REFERENCE_SOURCE_SHA256,
            "source_run_id":REFERENCE_RUN_ID,
            "verified_alpha":False,"trade_permission":"WAIT",
        }
