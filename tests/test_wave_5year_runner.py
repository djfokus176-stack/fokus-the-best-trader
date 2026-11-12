"""Five-year pipeline never invents a completed backtest from missing source."""
import pandas as pd
import pytest
from scripts.run_wave_5year import run


def test_fiveyear_requires_actual_source_csv(tmp_path):
    with pytest.raises(FileNotFoundError,match="BRAK DANYCH"):
        run(tmp_path/"missing.csv",tmp_path/"results")
    assert not (tmp_path/"results").exists()


def test_fiveyear_rejects_shortened_input_instead_of_fiveyear_label(tmp_path):
    frame=pd.DataFrame({
        "Time":pd.date_range("2026-11-09T00:15:00Z",periods=100,
                             freq="15min"),
        "Open":[100.]*100,"High":[101.]*100,
        "Low":[99.]*100,"Close":[100.]*100})
    path=tmp_path/"short.csv"
    frame.to_csv(path,index=False)
    with pytest.raises(ValueError,match="mniej niż 40000"):
        run(path,tmp_path/"results")
    assert not (tmp_path/"results").exists()
