"""Optional Supabase durable PAPER v4 checkpoint — single active writer.

Remote checkpoint is the SOURCE OF TRUTH in worker mode, not a cache.
Optimistic version compare-and-swap prevents accidental stale overwrites.
A REST request failure makes the worker report UNSAVED and stops new trades.
Never read service keys into client-side UI; Streamlit Python runs server-side.

Explicit limits: one writer, no guaranteed 24/7 host, not an exchange ledger.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
from urllib.parse import urlparse
import requests

STATE_TABLES=("paper_positions_v3","paper_events_v3",
              "telegram_attempts_v3","paper_system_events_v3")
MAX_BYTES=2_500_000
SCHEMA=1

class RemoteError(RuntimeError):
    pass

class RemoteConflict(RemoteError):
    pass

def configured(env=None):
    e=env if env is not None else os.environ
    return bool(e.get("FOKUS_SUPABASE_URL") and e.get("FOKUS_SUPABASE_SECRET_KEY"))

def _validate_url(url):
    u=urlparse(url.strip())
    if (u.scheme!="https" or not u.hostname or not
        re.fullmatch(r"[a-z0-9-]+\.supabase\.co",u.hostname) or u.port or u.username):
        raise RemoteError("Zła domena Supabase. Wymagany HTTPS <project>.supabase.co")

class RemoteCheckpoint:
    def __init__(self,url,key,session=None,timeout=12):
        _validate_url(url)
        if not key or len(key)<24:
            raise RemoteError("Brak prywatnego klucza Supabase")
        self.url=url.rstrip("/")
        self.key=key.strip()
        self.http=session or requests.Session()
        self.timeout=timeout

    @classmethod
    def from_env(cls,env=None,session=None):
        e=env if env is not None else os.environ
        if not configured(e):
            raise RemoteError("Brak FOKUS_SUPABASE_URL/FOKUS_SUPABASE_SECRET_KEY")
        return cls(e["FOKUS_SUPABASE_URL"],e["FOKUS_SUPABASE_SECRET_KEY"],session=session)

    def headers(self,prefer=""):
        hdr={"apikey":self.key,"Content-Type":"application/json",
             "Accept":"application/json"}
        # Legacy service-role JWT needs Authorization; modern sb_secret_*
        # keys authenticate with apikey and should never be logged.
        if self.key.count(".")==2:
            hdr["Authorization"]="Bearer "+self.key
        if prefer:
            hdr["Prefer"]=prefer
        return hdr

    def _call(self,method,path,**kw):
        try:
            rsp=self.http.request(method,self.url+"/rest/v1/"+path,
                timeout=self.timeout,headers=self.headers(kw.pop("prefer","")),**kw)
        except requests.RequestException as exc:
            raise RemoteError("Supabase niedostępny: "+type(exc).__name__) from None
        if rsp.status_code not in (200,201,204,206):
            raise RemoteError("Supabase HTTP "+str(rsp.status_code)+
                " (sprawdź tabelę, RLS, Secret Key; bez logowania odpowiedzi)")
        return rsp

    def fetch(self):
        rsp=self._call("GET","fokus_paper_checkpoint",
            params={"id":"eq.main","select":"version,payload"},)
        try: data=rsp.json()
        except (ValueError,TypeError):raise RemoteError("Błędny JSON z Supabase") from None
        if not isinstance(data,list) or len(data)!=1:
            raise RemoteError("Brak wiersza main — najpierw zastosuj SQL")
        obj=data[0]
        payload=obj.get("payload")
        if not isinstance(payload,dict) or payload.get("schema")!=SCHEMA:
            raise RemoteError("Nieznana wersja schematu; blokada zmian")
        version=obj.get("version")
        if not isinstance(version,int) or version<0:
            raise RemoteError("Niepoprawna wersja rekordu")
        return version,payload

    def save(self,expected_version,payload):
        raw=json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)
        if len(raw.encode("utf-8"))>MAX_BYTES:
            raise RemoteError("Checkpoint przekracza limit 2.5 MB; nie nadpisuję bazy")
        if payload.get("schema")!=SCHEMA:
            raise RemoteError("Nieznany format zapisu")
        try:
            rsp=self._call("PATCH","fokus_paper_checkpoint",
                params={"id":"eq.main","version":f"eq.{int(expected_version)}",
                        "select":"version"},
                json={"version":int(expected_version)+1,"payload":payload,
                      "updated_at":datetime.now(timezone.utc).isoformat()},
                prefer="return=representation")
            data=rsp.json()
        except (ValueError,TypeError):
            raise RemoteError("Brak potwierdzenia zapisu Supabase") from None
        if not isinstance(data,list) or len(data)!=1:
            raise RemoteConflict("Wersja remote uległa zmianie / blokada CAS, odmawiam nadpisania")
        if data[0].get("version")!=int(expected_version)+1:
            raise RemoteError("Supabase potwierdził inną wersję checkpointu")
        return int(expected_version)+1

    def fetch_candles(self,epic,timeframe,source="Capital.com DEMO REST",
                      limit=5000):
        """Owner-side read-only durable OHLC, page through 1000-row API limits."""
        import pandas as pd
        if source!="Capital.com DEMO REST" or timeframe not in (
                "MINUTE","MINUTE_5","MINUTE_15","HOUR"):
            raise RemoteError("Cloud research supports Capital DEMO OHLC only")
        limit=min(5000,max(1,int(limit)))
        all_rows=[]
        for offset in range(0,limit,1000):
            batch_size=min(1000,limit-offset)
            r=self._call("GET","fokus_closed_candles",
                params={"source":"eq."+source,"epic":"eq."+epic,
                    "timeframe":"eq."+timeframe,
                    "select":"candle_utc,open,high,low,close,spread",
                    "order":"candle_utc.desc","limit":batch_size,"offset":offset})
            try:batch=r.json()
            except (ValueError,TypeError):
                raise RemoteError("Błędny cloud OHLC JSON") from None
            if not isinstance(batch,list):
                raise RemoteError("Nieoczekiwane OHLC z bazy")
            all_rows+=batch
            if len(batch)<batch_size:
                break
        if not all_rows:
            return pd.DataFrame()
        frame=pd.DataFrame(all_rows)
        frame["Time"]=pd.to_datetime(frame.pop("candle_utc"),utc=True)
        frame=frame.rename(columns={"open":"Open","high":"High","low":"Low",
                      "close":"Close","spread":"Spread"}).set_index("Time").sort_index()
        for col in ("Open","High","Low","Close","Spread"):
            frame[col]=pd.to_numeric(frame[col],errors="raise")
        if frame.index.has_duplicates or frame[["Open","High","Low","Close","Spread"]].isna().any().any():
            raise RemoteError("Niespójne lub zduplikowane świece w cloud")
        return frame

    def upsert_candles(self,snapshots,epic,max_per_tf=350):
        # Backfill the most recent closed bars; primary key guarantees
        # deduplication when worker repeats the same candle.
        records=[]
        for tf,sn in snapshots.items():
            if sn is None or not sn.good or sn.source!="Capital.com DEMO REST" or sn.epic!=epic:
                continue
            for at,row in sn.frame.tail(max_per_tf).iterrows():
                records.append({"source":sn.source,"epic":epic,"timeframe":tf,
                    "candle_utc":at.isoformat(),
                    "open":float(row.Open),"high":float(row.High),
                    "low":float(row.Low),"close":float(row.Close),
                    "spread":float(row.Spread)})
        # Send in small batches to limit PostgREST request size; upsert
        # historical OHLC by compound key. Failure NEVER silently passes.
        for i in range(0,len(records),200):
            self._call("POST","fokus_closed_candles",
                params={"on_conflict":"source,epic,timeframe,candle_utc"},
                json=records[i:i+200],
                prefer="resolution=merge-duplicates,return=minimal")
        return len(records)

def dump_state(db):
    """Capture PAPER-only SQLite tables. Secrets and API credentials excluded."""
    from .paper_lifecycle import ensure_tables
    from .telegram_alerts import ensure_outbox
    ensure_tables(db)
    ensure_outbox(db)
    db.row_factory=sqlite3.Row
    tables={}
    for table in STATE_TABLES:
        tables[table]=[dict(row) for row in db.execute("SELECT * FROM "+table)]
    return {"schema":SCHEMA,"tables":tables}

def restore_state(db,payload,*,only_empty=True):
    """Restore only into an EMPTY worker-local DB; never delete local history."""
    if payload.get("schema")!=SCHEMA or not isinstance(payload.get("tables"),dict):
        raise RemoteError("Błędny schemat backupu")
    if any(table not in STATE_TABLES for table in payload["tables"]):
        raise RemoteError("Nieoczekiwane tabele checkpointu")
    from .paper_lifecycle import ensure_tables
    from .telegram_alerts import ensure_outbox
    ensure_tables(db)
    ensure_outbox(db)
    existing=sum(db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
                 for table in STATE_TABLES)
    if only_empty and existing:
        raise RemoteError("Nie przywracam zdalnego snapshotu do niepustej lokalnej bazy")
    db.execute("BEGIN IMMEDIATE")
    try:
        for table in STATE_TABLES:
            rows=payload["tables"].get(table,[])
            if not isinstance(rows,list):
                raise RemoteError("Niepoprawne wiersze checkpointu")
            cols={c[1] for c in db.execute("PRAGMA table_info("+table+")")}
            for row in rows:
                if not isinstance(row,dict) or not set(row).issubset(cols):
                    raise RemoteError("Nieznana kolumna w backupie "+table)
                keys=list(row)
                if not keys:
                    continue
                placeholders=",".join("?" for _ in keys)
                names=",".join('"'+k+'"' for k in keys)
                db.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
                           tuple(row[k] for k in keys))
        db.commit()
    except BaseException:
        db.rollback()
        raise

def remote_view_db(remote):
    """New, temporary in-memory SQLite for a Streamlit READ-ONLY cloud view."""
    from .paper_lifecycle import ensure_tables
    from .telegram_alerts import ensure_outbox
    version,payload=remote.fetch()
    db=sqlite3.connect(":memory:")
    restore_state(db,payload)
    return db,version
