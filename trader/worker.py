"""Independent foreground PAPER scanner. Run on a persistent host for continuous monitoring."""
import os
import time
import hashlib
import argparse
from datetime import datetime, timezone
from .market import CapitalReadOnly, FeedError
from .strategy import decide
from .storage import connect, archive, audit_prior_paper_signals


def scan_once(client, epic, tf, strategy, max_spread, db):
    snap = client.candles(epic,tf,max_spread=max_spread)
    if not snap.good:
        return 'WAIT / DATA_STALE: '+snap.reason
    result = decide(snap.frame,strategy,spread=snap.spread)
    stamp = snap.confirmed_utc.isoformat()
    key = hashlib.sha256(f'{epic}|{tf}|{strategy}|{stamp}|{result.action}'.encode()).hexdigest()
    is_new = archive(db,key,stamp,epic,snap.source,tf,result)
    audit_prior_paper_signals(db,snap.frame,epic,snap.source,tf,snap.spread)
    return f'{stamp} {result.action} ({"NOWE" if is_new else "DUPLIKAT"}) {result.reason}'


def main():
    p=argparse.ArgumentParser(description='PAPER read-only scanner (not a background service by itself)')
    p.add_argument('--once',action='store_true')
    p.add_argument('--interval',type=int,default=65)
    p.add_argument('--epic',default=os.getenv('CAPITAL_EPIC','US500'))
    p.add_argument('--tf',choices=['MINUTE','MINUTE_5','MINUTE_15','HOUR'],default='MINUTE')
    p.add_argument('--strategy',choices=['DRUGA FALA','EMA TREND'],default='DRUGA FALA')
    opts=p.parse_args()
    db=connect()
    try:
        client=CapitalReadOnly(os.getenv('CAPITAL_API_KEY',''),os.getenv('CAPITAL_IDENTIFIER',''),
                               os.getenv('CAPITAL_PASSWORD',''))
    except FeedError as ex:
        p.error(str(ex))
    while True:
        try: print(datetime.now(timezone.utc).isoformat(),scan_once(client,opts.epic,opts.tf,opts.strategy,2.0,db),flush=True)
        except FeedError as ex: print('ERROR FEED:', ex,flush=True)
        except Exception as ex: print('ERROR:', type(ex).__name__,flush=True)
        if opts.once: break
        time.sleep(max(opts.interval,30))

if __name__=='__main__': main()
