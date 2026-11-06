"""Official-source news radar: FED, BLS, BEA RSS + BLS calendar.

Fixed allowlist, read-only HTTP. Headlines are untrusted facts, NOT automated
buy/sell signals. Headlines NEVER generate an automatic GPT API request.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
import re
from xml.etree import ElementTree as ET
from urllib.parse import urlparse
import requests

FEEDS = {
    "FED — decyzje i komunikaty": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    "FED — wszystkie komunikaty": "https://www.federalreserve.gov/feeds/press_all.xml",
    "BLS — zatrudnienie": "https://www.bls.gov/feed/empsit.rss",
    "BLS — inflacja CPI": "https://www.bls.gov/feed/cpi.rss",
    "BEA — publikacje": "https://apps.bea.gov/rss/rss.xml",
}
BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
SAFE_HOSTS = {"www.federalreserve.gov","www.bls.gov","apps.bea.gov"}
EVENT_TERMS=("consumer price", "employment situation", "producer price",
             "job openings", "nonfarm", "cpi", "ppi", "jolts")


def allowed_url(url: str) -> bool:
    p=urlparse(str(url))
    return p.scheme=="https" and p.hostname in SAFE_HOSTS and not p.username and not p.password


def parse_rss(xml: bytes|str, source: str, limit=15) -> list[dict]:
    content=xml.encode("utf-8") if isinstance(xml,str) else xml
    root=ET.fromstring(content)
    records=[]
    nodes=root.findall(".//item")
    if not nodes:
        ns={"a":"http://www.w3.org/2005/Atom"}
        nodes=root.findall(".//a:entry",ns)
    for node in nodes[:int(limit)]:
        title=(node.findtext("title") or node.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()[:240]
        link=(node.findtext("link") or "").strip()
        if not link:
            entry_link=node.find("{http://www.w3.org/2005/Atom}link")
            if entry_link is not None:link=entry_link.get("href","")
        if not allowed_url(link) or not title:
            continue
        raw_date=node.findtext("pubDate") or node.findtext("{http://www.w3.org/2005/Atom}updated") or ""
        when=None
        if raw_date:
            try:
                when=parsedate_to_datetime(raw_date)
                if when.tzinfo is None:when=when.replace(tzinfo=timezone.utc)
                when=when.astimezone(timezone.utc)
            except (ValueError,TypeError,IndexError,OverflowError):
                when=None
        records.append({"źródło":source,"data_utc":when.isoformat() if when else "NIEZNANA",
                        "tytuł":title,"url":link})
    return records


def fetch_headlines(get=requests.get, timeout=10) -> tuple[list[dict],dict]:
    """Do not silently mark failed feeds as success."""
    output=[];errors={}
    for source,url in FEEDS.items():
        try:
            resp=get(url,timeout=timeout,headers={"User-Agent":"FokusTraderResearch/1.0"})
            resp.raise_for_status()
            if len(resp.content)>1_500_000:raise ValueError("Zbyt duży plik RSS")
            output.extend(parse_rss(resp.content,source))
        except (requests.RequestException,ValueError,ET.ParseError) as ex:
            errors[source]=type(ex).__name__
    unique={x["url"]:x for x in output}
    records=list(unique.values())
    # Unknown publication dates must NEVER outrank dated releases.
    # Sorting by the original text put "NIEZNANA" above ISO dates.
    def publication_time(row):
        try:
            value=datetime.fromisoformat(row["data_utc"])
            return value.astimezone(timezone.utc) if value.tzinfo else datetime.min.replace(tzinfo=timezone.utc)
        except (ValueError,TypeError,KeyError):
            return datetime.min.replace(tzinfo=timezone.utc)
    records.sort(key=publication_time,reverse=True)
    return records,errors


def parse_bls_calendar(ics: str, limit=40) -> list[dict]:
    """BLS schedule, America/New_York timestamps; no FOMC inference."""
    unfolded=ics.replace("\r\n","\n").split("\n")
    lines=[]
    for line in unfolded:
        if line.startswith((" ","\t")) and lines:
            lines[-1]+=line[1:]
        else:lines.append(line)
    result=[];event={}
    for line in lines:
        if line=="BEGIN:VEVENT":event={}
        elif line=="END:VEVENT":
            name=event.get("SUMMARY","").strip()
            dt=event.get("START")
            if name and dt:
                result.append({"wydarzenie":name[:200],"data_utc":dt.astimezone(timezone.utc)})
        elif line.startswith("SUMMARY:"):
            event["SUMMARY"]=line.split(":",1)[1].replace("\\, ",", ").strip()
        elif line.startswith("DTSTART"):
            try:
                left,raw=line.split(":",1)
                if "VALUE=DATE" in left or len(raw)==8:continue
                if raw.endswith("Z"):
                    dt=datetime.strptime(raw,"%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                else:
                    zone=left.split("TZID=",1)[1].split(";",1)[0] if "TZID=" in left else "America/New_York"
                    dt=datetime.strptime(raw,"%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo(zone))
                event["START"]=dt
            except (ValueError,KeyError,IndexError):
                pass
    result.sort(key=lambda x:x["data_utc"])
    return result[:limit] if limit else result


class _BlsTableParser(HTMLParser):
    """Collect literal table cells; no scripts, links or untrusted instructions."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_row=False
        self.cell_depth=0
        self.cell=[]
        self.cells=[]
        self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag=="tr":
            self.in_row=True;self.cells=[]
        elif self.in_row and tag in ("td","th"):
            self.cell_depth+=1
            if self.cell_depth==1:self.cell=[]
    def handle_data(self,data):
        if self.cell_depth:self.cell.append(data)
    def handle_endtag(self,tag):
        if self.in_row and tag in ("td","th") and self.cell_depth:
            self.cell_depth-=1
            if not self.cell_depth:
                self.cells.append(re.sub(r"\s+"," "," ".join(self.cell)).strip())
        elif tag=="tr" and self.in_row:
            if len(self.cells)>=3:self.rows.append(self.cells)
            self.in_row=False


def parse_bls_month_html(raw, *, year, month):
    """Parse BLS's own published Date/Time/Release schedule, fail closed.

    Only official www.bls.gov list pages are accepted by the caller.
    Dates stay America/New_York and are validated against page month/year.
    Unknown or irregular rows are ignored, NEVER assumed to be no releases.
    """
    if isinstance(raw,bytes):raw=raw.decode("utf-8-sig",errors="replace")
    if not isinstance(raw,str) or len(raw)>2_000_000:
        raise ValueError("Nieprawidłowy lub zbyt duży HTML BLS")
    parser=_BlsTableParser();parser.feed(raw)
    events=[]
    for row in parser.rows:
        date_cell,time_cell,name=row[:3]
        date_cell=re.sub(r"\s+"," ",date_cell.strip())
        time_cell=re.sub(r"\s+"," ",time_cell.strip())
        try:
            date_part=date_cell.split(",",1)[-1].strip()
            date=datetime.strptime(date_part,"%B %d, %Y")
            clock=datetime.strptime(time_cell,"%I:%M %p").time()
        except ValueError:
            continue
        if date.year!=year or date.month!=month or not name.strip():
            continue
        eastern=datetime(date.year,date.month,date.day,clock.hour,clock.minute,
                         tzinfo=ZoneInfo("America/New_York"))
        events.append({"wydarzenie":name.strip()[:200],
                       "data_utc":eastern.astimezone(timezone.utc)})
    if not events:
        raise ValueError("Oficjalna strona kalendarza BLS nie zawiera rozpoznanych dat")
    return events


def fetch_bls_schedule_html(get=requests.get, timeout=12, *, now=None):
    """Alternate official BLS **public** schedule (not a proxy).

    Fetch current AND next month to avoid missing releases across midnight
    at the end of a month. A missing page, unavailable BLS server, or
    unparsable HTML remains an error and keeps PAPER stopped.
    """
    now=now or datetime.now(timezone.utc)
    eastern=now.astimezone(ZoneInfo("America/New_York"))
    y,m=eastern.year,eastern.month
    next_y,next_m=(y+1,1) if m==12 else (y,m+1)
    events=[]
    for yy,mm in [(y,m),(next_y,next_m)]:
        url=f"https://www.bls.gov/schedule/{yy}/{mm:02d}_sched_list.htm"
        r=get(url,timeout=timeout,headers={
            "User-Agent":"FokusTraderResearch/1.1 (+https://github.com/djfokus176-stack/fokus-the-best-trader)",
            "Accept":"text/html,application/xhtml+xml;q=0.9"})
        r.raise_for_status()
        if len(r.content)>2_000_000:raise ValueError("Zbyt duży HTML BLS")
        events.extend(parse_bls_month_html(r.content,year=yy,month=mm))
    # Require not just any holiday/old information, but actual upcoming
    # high-impact employment/inflation dates from a freshly retrieved page.
    future=[event for event in events
            if now-timedelta(days=2)<=event["data_utc"]<=now+timedelta(days=60)]
    major=[event for event in future
           if any(term in event["wydarzenie"].lower() for term in EVENT_TERMS)]
    if len(major)<2:
        raise ValueError("Niepełny aktualny kalendarz BLS — za mało publikacji makro")
    return sorted(future,key=lambda x:x["data_utc"])


def fetch_bls_schedule(get=requests.get, timeout=12, *, now=None):
    # Identify client and use official sources only. If the .ics is
    # forbidden, try BLS's own current monthly HTML calendar; fail closed
    # when neither can be validated.
    headers={
        "User-Agent":"FokusTraderResearch/1.1 (+https://github.com/djfokus176-stack/fokus-the-best-trader)",
        "Accept":"text/calendar, text/plain;q=0.9, */*;q=0.5",
    }
    try:
        r=get(BLS_ICS,timeout=timeout,headers=headers)
        r.raise_for_status()
    except requests.HTTPError as exc:
        # Some network environments reject .ics while allowing BLS's own
        # published HTML schedule. Never use third-party mirrors or stale
        # bundled dates; if official HTML is also unavailable, fail closed.
        if getattr(getattr(exc,"response",None),"status_code",None)!=403:
            raise
        return fetch_bls_schedule_html(get=get,timeout=timeout,now=now)
    if len(r.content)>1_500_000:raise ValueError("Zbyt duży kalendarz")
    full=parse_bls_calendar(r.content.decode("utf-8-sig",errors="replace"),limit=0)
    cutoff=(now or datetime.now(timezone.utc))-timedelta(days=7)
    active=[e for e in full if e["data_utc"]>=cutoff]
    if not active:
        raise ValueError("Kalendarz BLS nie zawiera aktualnych dat — nie wyświetlam fałszywego braku publikacji.")
    return active[:300]


def macro_blackout(events, now=None, minutes_before=20,minutes_after=20):
    """Only confirmed scheduled high-impact BLS events; UNKNOWN != clear."""
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("UTC aware datetime required")
    if not events:return False,"Brak zweryfikowanego kalendarza: nie można potwierdzić braku publikacji."
    for e in events:
        when=e["data_utc"]
        if isinstance(when,str):
            when=datetime.fromisoformat(when)
        title=e["wydarzenie"].lower()
        if any(term in title for term in EVENT_TERMS):
            delta=(now-when).total_seconds()/60
            if -minutes_before<=delta<=minutes_after:
                return True,f"BLACKOUT: {e['wydarzenie']} ({when.isoformat()})"
    return False,"Brak potwierdzonej publikacji BLS w wybranym oknie; FOMC/BEA poza tym filtrem."
