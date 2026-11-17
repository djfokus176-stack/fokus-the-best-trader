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
from threading import Lock
from time import monotonic
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


# Cache only successful, source-validated schedules. A verified backup can
# NEVER survive its own hard expiry, even if the worker stays alive.
_BLS_CACHE_LOCK = Lock()
_BLS_CACHE = {"until": 0.0, "calendar": None, "hard_expiry": None}


def _validated_bls_ics(full, instant):
    """Prevent a 200 OK but incomplete/stale .ics from opening the PAPER gate."""
    active = [e for e in full if e["data_utc"] >= instant-timedelta(days=7)]
    future_major = {e["data_utc"] for e in active
        if instant < e["data_utc"] <= instant+timedelta(days=60)
        and any(term in e["wydarzenie"].lower() for term in EVENT_TERMS)}
    if len(future_major) < 2:
        raise ValueError("BLS_ICS_NO_UPCOMING_MAJOR_RELEASES")
    return active[:300]


def _bls_verified_backup(instant):
    """Short-lived, verifiable PAPER-only backup: expiry is mandatory."""
    try:
        from .bls_verified_snapshot import verified_schedule
        return verified_schedule(now=instant)
    except ValueError:
        pass
    from .manual_bls_calendar import load_verified_manual_bls
    try:
        return load_verified_manual_bls(now=instant)
    except ValueError as exc:
        # Only a finite internal diagnostic code, never raw HTTP errors,
        # credentials, response bodies, HTML, or user-provided messages.
        code = str(exc)
        if not re.fullmatch(r"BLS_[A-Z0-9_]{5,76}", code):
            code = "BLS_BACKUP_INVALID"
        raise ValueError("BLS_ALL_SOURCES_UNAVAILABLE__"+code) from None


def fetch_bls_schedule(get=requests.get, timeout=12, *, now=None):
    """Official ICS -> official two-month HTML -> strictly expiring backup.

    Each upstream can fail independently (403, 429, timeout, invalid 200).
    Only a *fresh, validated* calendar permits PAPER setups. Nothing is
    auto-extended or treated as a confirmed absence of macro releases.
    """
    instant = now if now is not None else datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("BLS_TIMEZONE_UNVERIFIED")
    instant = instant.astimezone(timezone.utc)
    cacheable = get is requests.get and now is None
    if cacheable:
        with _BLS_CACHE_LOCK:
            hard_expiry = _BLS_CACHE["hard_expiry"]
            if (monotonic() < _BLS_CACHE["until"]
                    and (hard_expiry is None or instant < hard_expiry)
                    and _BLS_CACHE["calendar"] is not None):
                return _BLS_CACHE["calendar"]

    # The ICS feed may be blocked to cloud providers. A failed or incomplete
    # ICS is not a reason to skip BLS's own monthly HTML pages.
    calendar = None
    headers = {
        "User-Agent": "FokusTraderResearch/1.1 (+https://github.com/djfokus176-stack/fokus-the-best-trader)",
        "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.5",
    }
    try:
        r = get(BLS_ICS, timeout=timeout, headers=headers)
        r.raise_for_status()
        if len(r.content) > 1_500_000:
            raise ValueError("BLS_ICS_TOO_LARGE")
        full = parse_bls_calendar(r.content.decode("utf-8-sig"), limit=0)
        calendar = _validated_bls_ics(full, instant)
    except requests.HTTPError as exc:
        # Explicit HTTP 403/429 are known cloud-host rejection/throttling.
        # A 500 or unexpected code must NOT silently unlock a backup.
        code = getattr(getattr(exc, "response", None), "status_code", None)
        if code not in (403, 429):
            raise
    except (requests.ConnectionError, requests.Timeout):
        pass
    except (ValueError, UnicodeError, ET.ParseError):
        # An incomplete or malformed HTTP 200 is NOT an approved calendar;
        # try the separate official HTML format instead.
        pass

    if calendar is None:
        try:
            calendar = fetch_bls_schedule_html(get=get, timeout=timeout, now=instant)
        except requests.HTTPError as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code not in (403, 429):
                raise
            calendar = _bls_verified_backup(instant)
        except (requests.ConnectionError, requests.Timeout):
            calendar = _bls_verified_backup(instant)
        # A parse/validation error on HTTP 200 is NOT network blocking.
        # Let it block PAPER: do not mask it with a potentially outdated copy.

    if cacheable:
        hard_expiry = None
        expiry_text = getattr(calendar, "expires_utc", None)
        if expiry_text:
            try:
                hard_expiry = datetime.fromisoformat(expiry_text).astimezone(timezone.utc)
            except (TypeError, ValueError):
                raise ValueError("BLS_BACKUP_MISSING_VALID_EXPIRY") from None
            if hard_expiry <= instant:
                raise ValueError("BLS_BACKUP_ALREADY_EXPIRED")
        ttl = 300.0
        if hard_expiry is not None:
            ttl = min(ttl, (hard_expiry-instant).total_seconds())
        with _BLS_CACHE_LOCK:
            _BLS_CACHE.update(until=monotonic()+max(0.0, ttl),
                              calendar=calendar, hard_expiry=hard_expiry)
    return calendar

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
