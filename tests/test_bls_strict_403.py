"""BLS HTTP 403 stays a blocking macro-data failure."""
import requests
import pytest
from trader.news_radar import BLS_ICS,fetch_bls_schedule


def test_bls_calendar_request_identifies_client_and_only_uses_official_url():
    seen=[]
    sample=("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Consumer Price Index\n"
            "DTSTART;TZID=America/New_York:20261110T083000\n"
            "END:VEVENT\nEND:VCALENDAR").encode()
    class Response:
        content=sample
        def raise_for_status(self): pass
    def fetch(url,**kwargs):
        seen.append((url,kwargs))
        return Response()
    events=fetch_bls_schedule(get=fetch)
    assert seen[0][0]==BLS_ICS
    assert "github.com/djfokus176-stack/fokus-the-best-trader" in seen[0][1]["headers"]["User-Agent"]
    assert "text/calendar" in seen[0][1]["headers"]["Accept"]
    assert events and events[0]["wydarzenie"]=="Consumer Price Index"


def test_bls_403_is_not_reinterpreted_as_empty_safe_calendar():
    response=requests.Response()
    response.status_code=403
    response.url=BLS_ICS
    class Rejected:
        content=b"ACCESS DENIED"
        def raise_for_status(self):
            raise requests.HTTPError("403 Forbidden",response=response)
    with pytest.raises(requests.HTTPError) as ex:
        fetch_bls_schedule(get=lambda *a,**kw:Rejected())
    assert ex.value.response.status_code==403
