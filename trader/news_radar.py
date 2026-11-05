"""Official-source news radar: FED, BLS, BEA RSS + BLS calendar.

Fixed allowlist, read-only HTTP. Headlines are untrusted facts, NOT automated
buy/sell signals. Headlines NEVER generate an automatic GPT API request.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
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
    records.sort(key=lambda r:r["data_utc"],reverse=True)
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


def fetch_bls_schedule(get=requests.get, timeout=12):
    r=get(BLS_ICS,timeout=timeout,headers={"User-Agent":"FokusTraderResearch/1.0"})
    r.raise_for_status()
    if len(r.content)>1_500_000:raise ValueError("Zbyt duży kalendarz")
    return parse_bls_calendar(r.content.decode("utf-8-sig",errors="replace"),limit=300)


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
