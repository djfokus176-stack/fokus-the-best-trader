"""Additional official macro release calendars for research visibility.

FED FOMC + BEA GDP/PCE/Trade. Sources are public US government websites.
Each source may fail: UNKNOWN coverage never means 'no upcoming events'.
This is supplemental WATCH ONLY; the existing BLS trading veto is unchanged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
import re
import requests

FED_URL="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BEA_URL="https://www.bea.gov/news/schedule/"
BEA_NEXT_URL="https://www.bea.gov/news/schedule/next-year"
NY=ZoneInfo("America/New_York")
MONTHS={month:i for i,month in enumerate((
    "January","February","March","April","May","June","July","August",
    "September","October","November","December"),1)}
MONTH_RE="|".join(MONTHS)


class _VisibleTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text=[]
        self.in_cell=False
        self.in_row=False
        self.cell=[]
        self.cells=[]
        self.rows=[]
        self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style"):
            self.skip+=1
        if self.skip:
            return
        if tag=="tr":
            self.in_row=True
            self.cells=[]
        elif self.in_row and tag in ("td","th"):
            self.in_cell=True
            self.cell=[]
    def handle_data(self,data):
        if self.skip:
            return
        self.text.append(data)
        if self.in_cell:
            self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("script","style") and self.skip:
            self.skip-=1
            return
        if self.skip:
            return
        if tag in ("td","th") and self.in_cell:
            self.cells.append(re.sub(r"\s+"," "," ".join(self.cell)).strip())
            self.in_cell=False
        elif tag=="tr" and self.in_row:
            if self.cells:
                self.rows.append(list(self.cells))
            self.in_row=False


def _parse_time(year, month, day, hour, minute, ampm):
    h=int(hour)%12 + (12 if ampm.upper()=="PM" else 0)
    et=datetime(int(year),int(month),int(day),h,int(minute),tzinfo=NY)
    return et.astimezone(timezone.utc)


def parse_bea_schedule(html, *, year, now=None):
    """Only timestamped, relevant entries from explicitly year-labeled BEA."""
    parser=_VisibleTable()
    parser.feed(html.decode("utf-8",errors="replace") if isinstance(html,bytes) else html)
    text=" ".join(parser.text)
    if not re.search(r"\bYear\s+"+str(year)+r"\b",text):
        raise ValueError("BEA year not verified on official page")
    cutoff=now or datetime.now(timezone.utc)
    entries=[]
    for row in parser.rows:
        if len(row)<3:
            continue
        first=re.search(
            rf"\b({MONTH_RE})\s+(\d{{1,2}})\s+"
            r"(\d{1,2}):(\d\d)\s*(AM|PM)\b", row[0],flags=re.I)
        if not first:
            continue
        month=MONTHS.get(first.group(1).capitalize())
        name=row[2].strip()
        if not month or not name:
            continue
        lowered=name.lower()
        critical=any(word in lowered for word in (
            "gdp","gross domestic product","personal income and outlays",
            "international trade in goods and services",
            "personal consumption expenditures"))
        if not critical:
            continue
        stamp=_parse_time(year,month,first.group(2),
                          first.group(3),first.group(4),first.group(5))
        if cutoff-timedelta(days=1)<=stamp<=cutoff+timedelta(days=180):
            entries.append({"wydarzenie":"BEA: "+name[:170],
                            "data_utc":stamp.isoformat(),
                            "source":"BEA_OFFICIAL_LIVE","url":BEA_URL})
    if not entries:
        raise ValueError("BEA schedule has no validated upcoming high-impact dates")
    return sorted(entries,key=lambda r:r["data_utc"])


def parse_fomc_schedule(html, *, now=None):
    """Read FED's year-separated FOMC meeting calendar; decision at 14:00 ET."""
    parser=_VisibleTable()
    parser.feed(html.decode("utf-8",errors="replace") if isinstance(html,bytes) else html)
    text=re.sub(r"\s+"," "," ".join(parser.text))
    cutoff=now or datetime.now(timezone.utc)
    entries=[]
    for year in (cutoff.year,cutoff.year+1):
        title=f"{year} FOMC Meetings"
        start=text.find(title)
        if start<0:
            continue
        tail=text[start+len(title):]
        end=re.search(r"20\d{2} FOMC Meetings|Back to Top|Note: A two-day meeting",tail)
        if end:
            tail=tail[:end.start()]
        for match in re.finditer(rf"\b({MONTH_RE})\s+(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\b",tail,re.I):
            month=MONTHS.get(match.group(1).capitalize())
            if month is None:
                continue
            stamp=datetime(year,month,int(match.group(3)),14,0,
                           tzinfo=NY).astimezone(timezone.utc)
            if cutoff-timedelta(days=1)<=stamp<=cutoff+timedelta(days=180):
                entries.append({"wydarzenie":"FED: FOMC statement / rate decision",
                                "data_utc":stamp.isoformat(),
                                "source":"FED_OFFICIAL_LIVE","url":FED_URL})
    if not entries:
        raise ValueError("FED schedule has no validated upcoming FOMC dates")
    return sorted(entries,key=lambda r:r["data_utc"])


def _request(get,url,timeout):
    resp=get(url,timeout=timeout,headers={"User-Agent":"FokusTraderResearch/1.2",
                                            "Accept":"text/html"})
    resp.raise_for_status()
    if len(resp.content)>2_000_000:
        raise ValueError("Official macro page too large")
    return resp.content


def fetch_macro_watch(*, get=requests.get, timeout=5, now=None):
    """Never silently claim completeness; independently report source errors."""
    utc=now or datetime.now(timezone.utc)
    if utc.tzinfo is None:
        raise ValueError("Macro watch requires aware UTC time")
    source_events=[]
    errors={}
    sources={}
    for name,url,decoder in [
        ("FED_FOMC",FED_URL,lambda body:parse_fomc_schedule(body,now=utc)),
        ("BEA",BEA_URL,lambda body:parse_bea_schedule(body,year=utc.astimezone(NY).year,now=utc))]:
        try:
            rows=decoder(_request(get,url,timeout))
            source_events.extend(rows)
            sources[name]={"status":"LIVE_OFFICIAL", "count":len(rows)}
        except (requests.RequestException,ValueError,TypeError,OverflowError) as exc:
            sources[name]={"status":"UNAVAILABLE","count":0}
            errors[name]=type(exc).__name__
    # An explicit incomplete status is mandatory even when both sources work:
    # Census, Treasury, exchange holidays, ISM and unscheduled events NOT covered.
    return {"asof_utc":utc.isoformat(),"coverage":"PARTIAL_OFFICIAL_CORE",
            "sources":sources,"errors":errors,
            "events":sorted(source_events,key=lambda x:x["data_utc"])[:80],
            "note":"Additional FED/BEA watch, not the full economic calendar; BLS veto separate."}
