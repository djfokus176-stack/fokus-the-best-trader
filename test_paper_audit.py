"""Regression: source strategy must survive owner-visible journal export.

Do not merge PENDING into losses or fabricate a strategy when field is absent.
"""
import pandas as pd
from trader.paper_audit import paper_export_table,paper_strategy_audit,EXPORT_COLUMNS


def rows():
    return [
        dict(trade_id="abcd1",strategy="EMA PULLBACK",epic="US500",
             source="Capital.com DEMO REST",timeframe="MINUTE",
             status="CLOSED_SL",side="LONG",pnl_pts=-6.45,
             entry_mid=7579.8,stop_mid=7574.45,target_mid=7589.89,
             close_reason="SL",opened_utc="2026-11-11T08:42:00+00:00",
             entry_assumed_utc="2026-11-11T08:41:00+00:00"),
        dict(trade_id="abcd2",strategy="EMA TREND",epic="US500",
             source="Capital.com DEMO REST",timeframe="MINUTE",
             status="CLOSED_TIMEOUT",side="LONG",pnl_pts=6.4,
             entry_mid=7573.6,stop_mid=7566.97,target_mid=7585.95),
        dict(trade_id="abcd3",strategy="EMA PULLBACK",
             status="CLOSED_TP",side="SHORT",pnl_pts=9.0),
        dict(trade_id="abcd4",strategy="EMA TREND",
             status="PENDING",side="LONG",pnl_pts=None),
        dict(trade_id="abcd5",strategy="EMA TREND",
             status="INVALIDATED",side="LONG",pnl_pts=None),
    ]


def test_full_export_keeps_strategy_ids_and_reconstruction_clock_without_secrets():
    result=paper_export_table(rows())
    assert set(("trade_id","strategy","entry_assumed_utc",
                "entry_detected_utc","exit_policy")).issubset(result.columns)
    assert all(c in EXPORT_COLUMNS for c in result.columns)
    assert result.loc[0,"strategy"]=="EMA PULLBACK"
    assert result.loc[0,"entry_assumed_utc"]!=result.loc[0,"opened_utc"]
    assert result.loc[0,"trade_id"]=="abcd1"
    assert not any(c in result.columns for c in
                   ("API_KEY","secret","token","password"))
    assert len(result)==5


def test_audit_groups_by_both_method_and_side_excludes_pending_invalidated():
    groups,overall=paper_strategy_audit(rows())
    assert overall=={"n":3,"sum_pts":8.95,"profitable":2,
                     "sl":1,"tp":1,"timeout":1,"named_positions":3}
    assert groups.liczba.sum()==3
    assert len(groups)==3
    assert bool(groups.przykladow_za_malo.all())
    trend=groups[(groups.strategy=="EMA TREND")&
                 (groups.side=="LONG")].iloc[0]
    assert trend.trafione_tp==0 and trend.zyskowne==1
    assert trend.skutecznosc_pnl_pct==100.0


def test_missing_strategy_is_explicitly_unknown_not_inferred():
    items=[dict(status="CLOSED_TIMEOUT",side="LONG",pnl_pts=-1.1)]
    groups,overall=paper_strategy_audit(items)
    assert groups.iloc[0].strategy=="NIEUSTALONA"
    assert overall["named_positions"]==0
    exported=paper_export_table(items)
    assert "strategy" in exported.columns
    assert pd.isna(exported.iloc[0].strategy)


def test_empty_or_only_open_rows_cannot_create_fake_losses():
    for dataset in ([],[dict(status="OPEN",side="SHORT",pnl_pts=None)]):
        groups,summary=paper_strategy_audit(dataset)
        assert groups.empty and summary["n"]==0
        assert summary["sum_pts"]==0
