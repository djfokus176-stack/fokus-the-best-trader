"""Fail-closed broker values + real publication recency rather than RSS fetch time."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import json
import pandas as pd
import pytest
from trader.market import parse_prices,FeedError
from trader.news_context import verified_recent_headlines,official_news_context
from trader.news_radar import fetch_headlines
from trader.auto_ai import review_closed_candle

NOW=datetime(2026,11,6,1,15,tzinfo=timezone.utc)
NEWS={"źródło":"FED", "data_utc":NOW.isoformat(),
      "tytuł":"FED rate decision", "url":"https://www.federalreserve.gov/foo"}


@pytest.mark.parametrize("invalid",["NaN","Infinity","-Infinity",-5,0])
def test_nonfinite_and_nonpositive_ohlc_rejected_for_paper(invalid):
    bar={"snapshotTimeUTC":NOW.isoformat(),
         "openPrice":{"bid":100,"ask":101},
         "highPrice":{"bid":102,"ask":103},
         "lowPrice":{"bid":99,"ask":100},
         "closePrice":{"bid":100,"ask":101}}
    bad=dict(bar)
    bad["closePrice"]={"bid":invalid,"ask":101}
    with pytest.raises(FeedError,match="NaN/Infinity/ujemna"):
        parse_prices({"prices":[bad]})
    with pytest.raises(FeedError,match="Brak poprawnych"):
        parse_prices({"prices":[bad]},quarantine_bad=True)


def test_recent_dated_news_only_and_allowlist():
    old={**NEWS,"data_utc":(NOW-timedelta(days=5)).isoformat()}
    undated={**NEWS,"data_utc":"NIEZNANA"}
    future={**NEWS,"data_utc":(NOW+timedelta(hours=2)).isoformat()}
    badhost={**NEWS,"url":"https://evil.invalid/trade"}
    rows=verified_recent_headlines([old,undated,future,badhost,NEWS],now=NOW)
    assert len(rows)==1
    assert rows[0]["title"]=="FED rate decision"
    ctx=official_news_context({"_news_last_success_utc":NOW.isoformat(),
       "_news_status":"OK","_headlines":[old,undated]},now=NOW)
    assert ctx["headlines"]==[]


def test_undated_rss_never_outranks_valid_timed_release():
    class Resp:
        content=("""<rss><channel>
<item><title>Unknown date</title><link>https://www.federalreserve.gov/a</link></item>
<item><title>Dated</title><link>https://www.federalreserve.gov/b</link>
<pubDate>Fri, 06 Nov 2026 00:00:00 GMT</pubDate></item>
</channel></rss>""").encode()
        def raise_for_status(self):pass
    result,errors=fetch_headlines(get=lambda *a,**kw:Resp(),timeout=1)
    assert result and result[0]["tytuł"]=="Dated"


def test_automatic_paid_commentary_filters_untrusted_old_headlines():
    at=NOW
    frame=pd.DataFrame({"Open":[100.]*8,"High":[101.]*8,
        "Low":[99.]*8,"Close":[100.]*8},
        index=pd.date_range(end=at,periods=8,freq="min"))
    snap=SimpleNamespace(source="Capital.com DEMO REST",epic="US500",
          resolution="MINUTE",confirmed_utc=at,frame=frame,spread=.6)
    decision=SimpleNamespace(action="LONG",strategy="EMA TREND",
         reason="Candidate",entry=100,stop=99,target=102,rr=2)
    payloads=[]
    def call(**kwargs):
        payloads.append(json.loads(kwargs["input"]))
        return SimpleNamespace(output_text="Analiza badawcza",usage=None)
    s=review_closed_candle({},snap,decision,[],[],[],now=at,
         news_context={"status":"OK","last_fetch_utc":at.isoformat(),
                       "headlines":[{**NEWS,"data_utc":(NOW-timedelta(days=4)).isoformat()},
                                    {**NEWS,"url":"https://evil.invalid"}, NEWS]},
         env={"FOKUS_AUTO_AI_ENABLED":"true","OPENAI_API_KEY":"mock"},call=call)
    assert s["status"]=="SUCCESS"
    assert len(payloads[0]["official_headline_context"]["headlines"])==1
    assert payloads[0]["official_headline_context"]["headlines"][0]["title"]=="FED rate decision"
