"""Research-only historical Capital.com DEMO M1 backfill.

The persistent worker remains the only PAPER writer. Owner-triggered action
reads broker historical BID/ASK OHLC in small UTC date windows BEFORE the
earliest durable Supabase M1. Broker OPEN labels are shifted exactly once
to our validated UTC CLOSE convention. No synthetic/interpolated candles,
no writes to Supabase, no order endpoints, no credential exports.
"""
from __future__ import annotations

import pandas as pd
import requests

from .market import (
    CapitalReadOnly, FeedError, capital_prices_as_close_times,
    http_error_message, parse_prices,
)
from .mtf_replay import build_higher_closed_bars, validate_close_time_m1


def backfill_before_archive(
    client: CapitalReadOnly, archive: pd.DataFrame, epic: str = "US500",
    *, max_batches: int = 6, minutes_per_batch: int = 840,
    target: int = 4600, max_candles: int = 5000,
) -> dict:
    """Return strictly verified research-only combined M1 DataFrame.

    Broker /prices supports max 1000 values and filters on snapshotTimeUTC.
    Request <=840 minutes per range. Read one overlapping oldest archived
    candle for an exact consistency check before accepting older prices.
    """
    if client.environment != "DEMO":
        raise ValueError("Backfill jest dozwolony wyłącznie na Capital DEMO.")
    if not epic.replace("_", "").isalnum():
        raise ValueError("Niepoprawny EPIC.")
    if not (1 <= max_batches <= 12 and
            2 <= minutes_per_batch <= 900 and
            4600 <= target <= max_candles <= 5000):
        raise ValueError("Niepoprawne limity pobrania historii.")
    validate_close_time_m1(archive)
    if len(archive) > max_candles:
        raise ValueError("Najpierw ogranicz bazę do 5000 ostatnich M1.")

    accepted = archive[["Open", "High", "Low", "Close", "Spread"]].copy()
    count_before = len(accepted)
    requests_done = 0
    rows_added = 0
    # First requested raw OPEN timestamp exactly matches oldest stored
    # CLOSE timestamp -1 minute; overlap must agree to prevent clock shifts.
    upper_open = archive.index[0].tz_convert("UTC") - pd.Timedelta(minutes=1)
    overlap_verified = False

    for _ in range(max_batches):
        if len(accepted) >= target and len(build_higher_closed_bars(accepted)["HOUR"]) >= 70:
            break
        lower_open = upper_open - pd.Timedelta(minutes=minutes_per_batch-1)
        params = {
            "resolution": "MINUTE", "max": 1000,
            "from": lower_open.strftime("%Y-%m-%dT%H:%M:%S"),
            "to": upper_open.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        try:
            response = client.session.get(
                f"{client.base_url}/api/v1/prices/{epic}",
                params=params, headers=client.headers(), timeout=12,
            )
            response.raise_for_status()
        except requests.RequestException as ex:
            raise FeedError(http_error_message(ex,"Historyczne świece DEMO",epic)) from None
        requests_done += 1
        try:
            payload = response.json()
        except (ValueError,TypeError):
            raise FeedError("Broker zwrócił niepoprawny historyczny JSON.") from None
        prices = payload.get("prices") if isinstance(payload,dict) else None
        if not isinstance(prices,list):
            raise FeedError("Broker nie zwrócił tablicy świec dla przedziału czasu.")
        if not prices:
            upper_open = lower_open - pd.Timedelta(minutes=1)
            continue
        if len(prices)>1000:
            raise FeedError("Broker przekroczył limit 1000 świec w odpowiedzi.")
        raw = parse_prices(payload)
        if (raw.index.min() < lower_open or raw.index.max() > upper_open):
            raise FeedError("Broker zwrócił świece spoza żądanego przedziału UTC.")
        shifted = capital_prices_as_close_times(raw,"MINUTE")
        keep = shifted[["Open", "High", "Low", "Close", "Spread"]]
        overlap = accepted.index.intersection(keep.index)
        if len(overlap):
            delta = (keep.loc[overlap]-accepted.loc[overlap]).abs()
            if (delta>0.0001).any().any():
                raise FeedError("Niezgodność OHLC archiwum i API: przerwano łączenie historii.")
            if archive.index[0] in overlap:
                overlap_verified = True
        missing = keep.loc[~keep.index.isin(accepted.index)]
        if not missing.empty:
            accepted = pd.concat([accepted,missing]).sort_index()
            if len(accepted)>max_candles:
                accepted = accepted.tail(max_candles)
            rows_added += len(missing)
        upper_open = lower_open - pd.Timedelta(minutes=1)

    # We may have no overlap if the broker omits that specific minute.
    # That is not evidence of a confirmed clock convention: don't promote
    # it to the PAPER clock gate. Retain exact unmodified timestamps.
    validate_close_time_m1(accepted)
    h1 = len(build_higher_closed_bars(accepted)["HOUR"])
    return {
        "frame": accepted,
        "requests": requests_done,
        "additional": len(accepted)-min(count_before,max_candles),
        "returned_older_rows": rows_added,
        "full_h1": h1,
        "overlap_verified": overlap_verified,
        "preflight_mtf": len(accepted)>=target and h1>=70,
    }
