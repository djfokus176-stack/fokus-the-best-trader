"""Manual GPT gets bounded, clearly labeled current headlines only."""
from datetime import datetime,timedelta,timezone
from trader.news_context import official_news_context
NOW=datetime(2026,11,6,1,1,tzinfo=timezone.utc)
GOOD={"źródło":"FED — decyzje i komunikaty",
      "data_utc":NOW.isoformat(),
      "tytuł":"Monetary policy release",
      "url":"https://www.federalreserve.gov/newsevents/pressreleases/"}
BAD={**GOOD,"url":"https://evil.invalid/fake"}


def state(last=NOW,status="OK",records=None):
    return {"_news_read_utc":NOW.isoformat(),
      "_news_last_success_utc":last.isoformat(),
      "_news_status":status,
      "_headlines":[GOOD] if records is None else records}


def test_fresh_official_rss_passes_with_timestamp_and_source():
    context=official_news_context(state(),now=NOW)
    assert context["status"]=="OK"
    assert context["headlines"][0]["source"].startswith("FED")
    assert context["headlines"][0]["title"]=="Monetary policy release"
    assert context["headlines"][0]["published_utc"]==NOW.isoformat()


def test_stale_or_unavailable_news_does_not_pretend_fresh():
    ctx=official_news_context(state(last=NOW-timedelta(hours=2)),now=NOW)
    assert ctx["status"]=="STALE_OR_UNAVAILABLE"
    assert ctx["headlines"]==[]
    ctx=official_news_context(state(status="NO_DATA"),now=NOW)
    assert ctx["headlines"]==[]


def test_external_hosts_rejected_and_text_bounded():
    many=[{**GOOD,"tytuł":"a"*999} for _ in range(18)]+[BAD]
    ctx=official_news_context(state(records=many),now=NOW,limit=3)
    assert len(ctx["headlines"])==3
    assert max(len(x["title"]) for x in ctx["headlines"])<=220
    ctx=official_news_context(state(records=[BAD]),now=NOW)
    assert ctx["headlines"]==[]


def test_manual_ai_receives_news_and_dashboard_displays_it():
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "news_untrusted_external" in app
    assert "NEWS / MAKRO OBOK WYKRESU" in app
    assert "result=manual_ai_request(question,context)" in app
    assert "render_independent_live_chart(" in app
