"""Automatic virtual trading journal is backed solely by saved ledger rows."""
from pathlib import Path

from trader.auto_sim_journal import auto_sim_journal, _local, _price

AUTO="AUTO PAPER (eksperyment 1 sygnału): zatwierdzone: EMA TREND."


def row(key, status, **kwargs):
    return {
        "trade_id":key, "epic":"US500", "source":"Capital.com DEMO REST",
        "side":"LONG", "strategy":"EMA TREND", "setup_reason":AUTO,
        "setup_utc":"2026-11-19T18:59:00Z",
        "opened_utc":None, "closed_utc":None,
        "entry_mid":None, "exit_mid":None, "pnl_pts":None,
        "stop_mid":7370, "target_mid":7420,
        "status":status,
        **kwargs
    }


def packet(rows):
    return {"meta":{"epic":"US500","source":"Capital.com DEMO REST",
                    "last_scan_utc":"2026-11-19T19:05:00Z"},
            "tables":{"paper_positions_v3":rows}}


def test_pending_not_open_close_or_profits():
    j=auto_sim_journal(packet([row("pending","PENDING")]))
    assert j["known"]
    assert j["pending"]["Status"]=="OCZEKUJE NA POTWIERDZENIE"
    assert j["opened"]==0 and j["closed"]==0
    assert j["active"] is None
    assert j["rows"] == []
    assert j["net_pts"] == 0


def test_simulated_open_and_closed_and_polish_dates():
    opened=row("a","OPEN",opened_utc="2026-11-19T19:00:00Z",
               entry_mid=7390)
    closed=row("b","CLOSED_TP",opened_utc="2026-11-19T18:55:00Z",
               closed_utc="2026-11-19T19:02:00Z",
               entry_mid=7388,exit_mid=7408,pnl_pts=19.25)
    loss=row("c","CLOSED_SL",opened_utc="2026-11-19T18:40:00Z",
             closed_utc="2026-11-19T18:50:00Z",
             entry_mid=7390,exit_mid=7370,pnl_pts=-21.5)
    j=auto_sim_journal(packet([closed,loss,opened]))
    assert j["opened"]==3
    assert j["closed"]==2
    assert j["net_pts"]==-2.25
    assert j["active"]["Kierunek"]=="LONG"
    assert j["active"]["Otwarcie (Polska)"]=="19.11.2026 20:00"
    assert j["latest_closed"]["Status"]=="ZAMKNIĘTA • TP"
    assert [r["ID"] for r in j["rows"]]==["b","c"]
    assert all(r["Wynik (pkt)"] is not None for r in j["rows"])


def test_unverified_manual_and_other_instruments_never_count_as_auto():
    standalone=row("manual","OPEN",opened_utc="2026-11-19T19:00:00Z",
                   entry_mid=7390)
    standalone["setup_reason"]="Single explicit test, not AUTO"
    other=row("other","CLOSED_TP",opened_utc="2026-11-19T18:00:00Z",
              closed_utc="2026-11-19T18:20:00Z",
              entry_mid=7390,exit_mid=7410,pnl_pts=18)
    other["epic"]="GER40"
    unknown=row("old","CLOSED_TP",opened_utc="2026-11-19T18:00:00Z",
                closed_utc="2026-11-19T18:20:00Z",
                entry_mid=7390,exit_mid=7410,pnl_pts=18)
    unknown["setup_reason"]=""
    j=auto_sim_journal(packet([standalone,other,unknown]))
    assert j["known"] and j["opened"]==0 and j["closed"]==0
    assert j["net_pts"]==0


def test_invalidated_and_bad_ledger_records_do_not_create_fake_results():
    invalid=row("bad","INVALIDATED")
    corrupt=row("broken","CLOSED_TP",opened_utc="2026-11-19T18:30:00Z",
                closed_utc="2026-11-19T19:00:00Z",
                entry_mid=7390,exit_mid=7408,pnl_pts=None)
    j=auto_sim_journal(packet([invalid,corrupt]))
    assert j["invalidated"]==1
    assert j["incomplete"]==1
    assert j["closed"]==0 and j["opened"]==0
    assert not j["rows"]


def test_duplicate_row_cannot_double_count():
    completed=row("unique","CLOSED_TIMEOUT",opened_utc="2026-11-19T18:30:00Z",
                  closed_utc="2026-11-19T19:00:00Z",
                  entry_mid=7390,exit_mid=7392,pnl_pts=1.25)
    j=auto_sim_journal(packet([completed,completed]))
    assert j["opened"]==1 and j["closed"]==1
    assert j["net_pts"]==1.25 and j["incomplete"]==1


def test_missing_remote_checkpoint_never_invents_open_or_archive():
    for payload in (None, {}, {"meta":{}}, {"tables":{}}, packet([])):
        j=auto_sim_journal(payload)
        assert j["opened"]==0 and j["closed"]==0 and j["rows"]==[]
    assert not auto_sim_journal(None)["known"]


def test_date_prices_and_user_interface_are_broker_free():
    assert _local("2026-11-19T19:00:00Z")=="19.11.2026 20:00"
    assert _local("bad")=="—"
    assert _price(float("nan")) is None
    assert _price(True) is None
    ui=Path("trader/auto_sim_journal_ui.py").read_text("utf-8")
    engine=Path("trader/auto_sim_journal.py").read_text("utf-8")
    terminal=Path("trader/cloud_paper_terminal.py").read_text("utf-8")
    assert "render_auto_sim_journal(payload)" in terminal
    assert "BOT HANDLUJE AUTOMATYCZNIE" in ui
    assert "FOKUS_DEMO_BROKER_MODE" not in ui
    assert "client.session.post" not in ui+engine
    assert "queue_paper(" not in ui+engine
