"""External foreground PAPER v3 scanner — never sends any broker order.

Run on an independently provisioned persistent host to scan while no browser
is open. Merely storing this file on GitHub does not schedule it 24/7.

Important: broker candle timestamp convention is UNVERIFIED by documentation.
We do not backfill fictitious real fills. The lifecycle remains hypothetical.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import os
import sqlite3
import time
from .market import CapitalReadOnly,FeedError,PERIOD
from .mtf import fetch_all_timeframes,filter_mtf_decision,TIMEFRAMES
from .news_radar import fetch_bls_schedule,macro_blackout,fetch_headlines
from .runtime import current_feed_status
from .storage import connect,archive_candles
from .strategies_pro import ALL_STRATEGIES,decide_any
from .auto_strategy import AUTO_MODE,evaluate_auto
from .ema50_wave import STRATEGY_NAME as WAVE_NAME
from .paper_lifecycle import ensure_tables,progress_paper,queue_paper,active_position
from .telegram_alerts import dispatch_alerts,record_stale_event
from .remote_checkpoint import (RemoteCheckpoint, configured, dump_state,
                                restore_state, RemoteError)


def scan_once(client,epic,tf,strategy,max_spread,db, *,
              slippage=.25,enable_setups=True,strict_macro=True,
              calendar_fetch=fetch_bls_schedule,telegram_token="",
              telegram_chat_id="",telegram_enabled=False,remote=None,
              reviewer=None):
    """One accountable v3 scan, using Capital DEMO + closed bars only.

    Existing PAPER can progress independently of new-signal permissions;
    new setups require all four MTFs, broker TRADEABLE and a verified BLS
    calendar. This is NOT guaranteed full FOMC/macro blackout coverage.
    """
    ensure_tables(db)
    if client.environment!="DEMO" or tf not in TIMEFRAMES:
        return "WAIT / PAPER v3 is DEMO-only"
    snapshots,errors=fetch_all_timeframes(client,epic,max_spread=max_spread,count=350)
    main=snapshots.get(tf)
    status="UNKNOWN"
    try:
        status=client.market_state(epic)
    except (FeedError,ValueError):
        pass
    if status in ("CLOSED","OFFLINE","EDIT","EDITS_ONLY","EDIT_ONLY"):
        # Market closure is NOT the same as a broken feed. Never create PAPER
        # setups against a dormant CFD and do not invent weekend candles.
        return (f"WAIT / MARKET_CLOSED / BROKER_STATUS={status} / "
                f"Latest={getattr(main,'confirmed_utc',None)} / "
                "NO_NEW_PAPER_SETUP")
    if main is None:
        return f"WAIT / NO_FEED / BROKER_STATUS={status} / {tf}: {str(errors.get(tf,'missing'))[:150]}"
    if not main.good:
        if telegram_enabled:
            record_stale_event(db,main.source,epic,tf,main.reason)
            dispatch_alerts(db,telegram_token,telegram_chat_id,enabled=True)
        return (f"WAIT / DATA_STALE / BROKER_STATUS={status} / "
                f"{main.reason}")
    # Progress any existing positions on their original TF whenever
    # a new completed candle can be fetched from the DEMO feed.
    archived=0
    transitions=[]
    for resolution,snapshot in snapshots.items():
        if snapshot.good:
            # Local PAPER uses SQLite candle_history; remote PAPER has a
            # dedicated Supabase OHLC table, not this ephemeral SQLite table.
            if remote is None:
                archived+=archive_candles(db,snapshot.frame,epic,snapshot.source,resolution)
            transitions.extend(progress_paper(db,snapshot.frame,epic,snapshot.source,
                                              resolution,max_holding=20))
    if remote is not None:
        # Persist OHLC before optional billable commentary. A failed cloud
        # write aborts the scan instead of charging for an unsaved analysis.
        archived=remote.upsert_candles(snapshots,epic)
    if strategy==AUTO_MODE:
        verdict,auto_votes=evaluate_auto(main.frame,main.spread,snapshots,
                                          asof=main.confirmed_utc,use_mtf=True)
        # Keep explicit readiness checks even if AUTO returns WAIT.
        _,views=filter_mtf_decision(
            decide_any(main.frame,ALL_STRATEGIES[0],spread=main.spread),
            snapshots,asof=main.confirmed_utc)
    else:
        candidate=decide_any(main.frame,strategy,spread=main.spread)
        verdict,views=filter_mtf_decision(candidate,snapshots,asof=main.confirmed_utc)
        auto_votes=[{"Strategia":strategy,"Setup OHLC":candidate.action,
                     "Po filtrze MTF":verdict.action,"RR":candidate.rr,
                     "Powód":verdict.reason if verdict.action!=candidate.action else candidate.reason}]
    fresh,why,_=current_feed_status(main,main.source)
    reasons=[]
    # Report WHY a gate blocked the scan. Never log credentials or tokens.
    diagnostics=[]
    if "POMINIĘTO_STARE_BŁĘDY=" in main.reason:
        diagnostics.append("DATA_WARN:"+main.reason.split("POMINIĘTO_STARE_BŁĘDY=",1)[1][:100])
    for resolution in TIMEFRAMES:
        if resolution in errors:
            diagnostics.append(f"{resolution}:FETCH_ERROR:{str(errors[resolution])[:100]}")
        elif resolution in snapshots and not snapshots[resolution].good:
            diagnostics.append(f"{resolution}:BAD_SNAPSHOT:{str(snapshots[resolution].reason)[:100]}")
    if not enable_setups:
        reasons.append("SETUPS_DISABLED")
    if status!="TRADEABLE":
        reasons.append("MARKET_NOT_TRADEABLE")
    if not fresh:
        reasons.append("DATA_STALE")
    if errors or not all(v.ready for v in views):
        reasons.append("INCOMPLETE_MTF")
        for view in views:
            if not view.ready:
                diagnostics.append(f"{view.timeframe}:MTF_NOT_READY:{str(view.reason)[:90]}")
    if strict_macro:
        try:
            calendar=calendar_fetch()
            if not calendar:
                reasons.append("MACRO_CALENDAR_UNKNOWN")
            else:
                calendar_source=getattr(calendar,"source","BLS_OFFICIAL_LIVE")
                if calendar_source in ("BLS_VERIFIED_SNAPSHOT_NOT_LIVE","BLS_VERIFIED_MANUAL_NOT_LIVE"):
                    # Explicit in every audit log: a short-lived manually
                    # verified schedule is NOT continuously refreshed.
                    diagnostics.append(
                        "MACRO_SOURCE="+calendar_source+
                        ";EXPIRES_UTC="+str(getattr(calendar,"expires_utc","UNKNOWN")))
                else:
                    diagnostics.append("MACRO_SOURCE=BLS_OFFICIAL_LIVE")
                blackout,_=macro_blackout(calendar)
                if blackout:
                    reasons.append("MACRO_BLACKOUT")
        except (OSError,ValueError,TimeoutError,FeedError,TypeError) as exc:
            reasons.append("MACRO_CALENDAR_UNAVAILABLE")
            code=getattr(getattr(exc,"response",None),"status_code",None)
            diagnostics.append("BLS_CALENDAR:"+type(exc).__name__+
                               (f":HTTP{code}" if code else ""))
    # Optional AI is commentary only. It cannot change verdict, gates or orders.
    if reviewer is not None:
        try:
            reviewer(main,verdict,auto_votes,views,reasons)
        except Exception:
            pass  # A paid commentary failure must not alter PAPER accounting.
    queued=None
    if not reasons and verdict.action in ("LONG","SHORT"):
        policy=os.getenv("FOKUS_PAPER_EXIT_POLICY","fixed").strip().lower()
        if policy not in ("fixed","adaptive"):
            policy="fixed"  # reject unknown policies rather than guessing
        queued=queue_paper(db,epic,main.source,tf,verdict,main.confirmed_utc,
                           main.spread,slippage=slippage,market_status=status,
                           exit_policy=policy)
    if telegram_enabled:
        dispatch_alerts(db,telegram_token,telegram_chat_id,enabled=True)
    active=active_position(db,epic,main.source,tf)
    state=active["status"] if active else "NONE"
    return (f"{main.confirmed_utc.isoformat()} / {verdict.action} / "
            f"QUEUE={'YES' if queued else 'NO'} / ACTIVE={state} / "
            f"EVENTS={','.join(transitions) or '-'} / CANDLES={archived} / "
            f"GATES={','.join(reasons) or 'OK'} / "
            f"DIAGNOSTICS={' | '.join(diagnostics)[:700] or '-'} / "
            f"{verdict.reason}")


def remote_scan_once(remote,client,epic,tf,strategy,max_spread, *,
                     enable_setups=True,strict_macro=True,
                     calendar_fetch=fetch_bls_schedule,
                     clock_confirmed_open=None):
    """Single-worker cloud cycle; fail closed on missing/changed checkpoint.

    Cloud checkpoint is loaded before the scan and CAS-saved after.
    Telegram delivery disabled in this cloud route until atomic cloud
    outbox claiming is available (local at-most-once cannot protect a
    job that crashes after sending but before checkpointing).
    """
    version,payload=remote.fetch()
    browser_clock_override=(clock_confirmed_open is not None)
    if clock_confirmed_open is None:
        # Existing CLI/GitHub path keeps its original gate and metadata.
        clock_confirmed_open=(os.getenv("FOKUS_CANDLE_TIME_CONFIRMED","").strip().lower()=="open")
    if browser_clock_override and not clock_confirmed_open:
        # Fail closed for the new owner-dashboard entry point only.
        enable_setups=False
    auto_state=payload.get("auto_ai",{})
    candidates=payload.get("candidate_feed",[])
    forecast_state=payload.get("forecast_research",{})
    vote_audit=payload.get("last_vote_audit") or {}
    news_feed=dict(payload.get("news_radar") or {})
    macro_watch=dict(payload.get("macro_watch") or {})
    utc=datetime.now(timezone.utc)
    last=news_feed.get("last_fetch_utc")
    try:
        elapsed=(utc-datetime.fromisoformat(last)).total_seconds() if last else 1e20
    except (ValueError,TypeError):
        elapsed=1e20
    if elapsed>=900 or elapsed<0:
        news_feed["last_fetch_utc"]=utc.isoformat()
        try:
            headlines,source_errors=fetch_headlines(timeout=3)
            news_feed["headlines"]=headlines[:30]
            news_feed["errors"]=dict(source_errors)
            news_feed["status"]=("OK" if headlines and not source_errors
                  else "PARTIAL" if headlines else "NO_DATA")
        except (OSError,ValueError,TypeError) as exc:
            news_feed["status"]="ERROR_"+type(exc).__name__
            news_feed["errors"]={"worker":type(exc).__name__}
            news_feed["headlines"]=[]
    # Independent, read-only official FED/BEA calendar watcher once per hour
    # when job runs. It never substitutes unknown BLS dates for "no events".
    watch_last=macro_watch.get("asof_utc")
    try:
        watch_age=(utc-datetime.fromisoformat(watch_last)).total_seconds() if watch_last else 1e20
    except (ValueError,TypeError):
        watch_age=1e20
    if watch_age>=3600 or watch_age<0:
        try:
            from .macro_calendar_plus import fetch_macro_watch
            macro_watch=fetch_macro_watch(timeout=4,now=utc)
        except (OSError,ValueError,TypeError,RuntimeError) as exc:
            macro_watch={"asof_utc":utc.isoformat(),"coverage":"UNAVAILABLE",
                         "events":[],"errors":{"worker":type(exc).__name__},
                         "sources":{}}
    def review_snapshot(snapshot,decision,votes,views,blockers):
        nonlocal auto_state,candidates,forecast_state,vote_audit
        # Only a read-only audit. These results were ALREADY computed by
        # evaluate_auto / filter_mtf_decision. Never alter trade decisions.
        vote_audit={
            "candle_utc":snapshot.confirmed_utc.isoformat(),
            "epic":epic,"source":snapshot.source,
            "mode":strategy,
            "decision":decision.action,
            "rows":[{
                "strategy":str(v.get("Strategia",""))[:75],
                "raw":str(v.get("Setup OHLC","WAIT"))[:10],
                "after_mtf":str(v.get("Po filtrze MTF","WAIT"))[:10],
                "reason":str(v.get("Powód",""))[:240]
            } for v in list(votes or [])[:6]],
            "mtf":[{
                "timeframe":str(v.timeframe),
                "ready":bool(v.ready),
                "trend":str(v.trend)[:20],
                "reason":str(v.reason)[:150],
                "candle_utc":str(getattr(v,"candle_utc",""))
            } for v in list(views or [])[:4]],
            "blockers":list(blockers or [])[:10],
        }
        # Informational M1 bias from completed candles only, never a PAPER
        # entry, MTF override or broker order. Persist beside the six votes.
        from .early_watch import evaluate_early_watch
        watch=evaluate_early_watch(snapshot.frame)
        vote_audit["watch"]={
            "side":watch.side,"score":int(watch.score),
            "countertrend":bool(watch.countertrend),
            "reason":str(watch.reason)[:240],
        }
        from .forecast_audit import update_forecast
        # Only fresh, verified closed bars can enter future-price SHADOW audit.
        # The resulting predictions are not inputs to PAPER or risk gates.
        forecast_state=update_forecast(forecast_state,snapshot)
        from .auto_ai import review_closed_candle
        from .candidate_radar import append_candidate
        # Keep the original 6-vote AUTO consensus unchanged; evaluate an
        # independent legacy-inspired comparator for transparent research.
        research_votes=list(votes)
        if strategy==AUTO_MODE:
            wave=decide_any(snapshot.frame,WAVE_NAME,spread=snapshot.spread)
            research_votes.append({"Strategia":WAVE_NAME+" • SHADOW",
                "Setup OHLC":wave.action,"Po filtrze MTF":"NIE WYLICZANO (SHADOW)",
                "RR":wave.rr,"Powód":wave.reason})
        candidates=append_candidate(candidates,snapshot,decision,research_votes,blockers)
        auto_state=review_closed_candle(auto_state,snapshot,decision,votes,views,
                                      blockers,news_context=news_feed,
                                      macro_context=macro_watch)
    db=sqlite3.connect(":memory:")
    try:
        restore_state(db,payload)
        status=scan_once(client,epic,tf,strategy,max_spread,db,
                         enable_setups=enable_setups,strict_macro=strict_macro,
                         calendar_fetch=calendar_fetch,telegram_enabled=False,
                         remote=remote,reviewer=review_snapshot)
        payload=dump_state(db)
        if isinstance(auto_state,dict):
            payload["auto_ai"]=auto_state
        if isinstance(candidates,list):
            payload["candidate_feed"]=candidates[-120:]
        payload["news_radar"]=news_feed
        payload["macro_watch"]=macro_watch
        if isinstance(forecast_state,dict):
            payload["forecast_research"]=forecast_state
        if isinstance(vote_audit,dict):
            payload["last_vote_audit"]=vote_audit
        from .paper_learning import strategy_scorecard
        payload["learning_report"]=strategy_scorecard(db,epic=epic)
        payload["meta"]={
            "last_scan_utc":datetime.now(timezone.utc).isoformat(),
            "last_scan_summary":status[:350],
            "source":"Capital.com DEMO REST",
            "timeframe":tf,"epic":epic,
            "strategy":strategy,
            "clock_confirmed_open":bool(clock_confirmed_open),
            "setups_enabled":bool(enable_setups),
            "news_status":news_feed.get("status","NO_DATA"),
            "news_last_fetch_utc":news_feed.get("last_fetch_utc"),
            "macro_fed_status":(macro_watch.get("sources") or {}).get("FED_FOMC",{}).get("status","UNKNOWN"),
            "macro_bea_status":(macro_watch.get("sources") or {}).get("BEA",{}).get("status","UNKNOWN"),
            "auto_gpt_enabled":os.getenv("FOKUS_AUTO_AI_ENABLED","false").strip().lower() in ("true","1","yes","on"),
            "auto_gpt_configured":bool(os.getenv("OPENAI_API_KEY","")),
            "auto_gpt_last_status":auto_state.get("status","NOT_YET_EXECUTED") if isinstance(auto_state,dict) else "NOT_YET_EXECUTED",
            "worker":"GitHub Actions or foreground process",
            "telegram_remote":"DISABLED"}
        new_version=remote.save(version,payload)
        audit_line=""
        if (isinstance(vote_audit,dict) and vote_audit.get("rows")
                and vote_audit.get("candle_utc")
                and status.startswith(vote_audit["candle_utc"])):
            # Exact six votes are printed for FUTURE scans, never backfilled.
            # If market data is stale, do not reprint old vote snapshots.
            import json
            compact=[str(v.get("strategy",""))+":"+
                     str(v.get("raw","WAIT"))+">"+
                     str(v.get("after_mtf","WAIT"))
                     for v in vote_audit["rows"]]
            audit_line=" / SIX_VOTES="+json.dumps(compact,ensure_ascii=False)
            blocked=[str(v.get("strategy",""))+":"+
                     str(v.get("reason",""))[:125]
                     for v in vote_audit["rows"]
                     if v.get("raw") in ("LONG","SHORT") and v.get("after_mtf")=="WAIT"]
            if blocked:
                audit_line+=" / MTF_VETO="+json.dumps(blocked,ensure_ascii=False)
            # The critical 0/0 case still needs explanations: WAIT was
            # produced by the raw setup itself (e.g. RR or nearby obstacle),
            # so there was no MTF veto to report.
            no_setups=[str(v.get("strategy",""))+":"+
                str(v.get("reason",""))[:115] for v in vote_audit["rows"]
                if v.get("raw")=="WAIT"]
            if no_setups:
                audit_line+=" / WAIT_REASONS="+json.dumps(no_setups,ensure_ascii=False)
            watch=vote_audit.get("watch") or {}
            if watch.get("side") in ("LONG","SHORT","WAIT"):
                audit_line+=(" / OBSERVE_M1="+str(watch["side"])+
                            "(score="+str(watch.get("score",0))+"/6;NOT_PAPER)")
            audit_line+=" / MTF_STATES="+json.dumps([
                str(v.get("timeframe"))+":"+str(v.get("trend"))+
                (":READY" if v.get("ready") else ":NOT_READY")
                for v in vote_audit.get("mtf",[])],ensure_ascii=False)
        return status+f" / CLOUD_CHECKPOINT_VERSION={new_version} / TELEGRAM_REMOTE=DISABLED"+audit_line
    finally:
        db.close()


def seconds_until_next_m1_scan(now=None,grace_seconds=8):
    """Next UTC minute boundary + grace, no sub-minute speculative strategy.

    A positive delay is always returned, even when called at the boundary.
    If a scan overruns the next minute, skip the missed invocation instead
    of creating duplicate overlapping cloud writers.
    """
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("UTC-aware time required")
    grace=max(3,min(20,int(grace_seconds)))
    seconds=now.timestamp()
    next_tick=(int((seconds-grace)//60)+1)*60+grace
    return max(0.001,next_tick-seconds)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Foreground Capital DEMO PAPER v3 scanner, no live trades")
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval",type=int,default=65)
    parser.add_argument("--align-minute",action="store_true",
        help="Scan just after each UTC M1 close (foreground PAPER only).")
    parser.add_argument("--epic",default=os.getenv("CAPITAL_EPIC","US500"))
    parser.add_argument("--tf",choices=list(TIMEFRAMES),default="MINUTE")
    parser.add_argument("--strategy",choices=[AUTO_MODE,*ALL_STRATEGIES,WAVE_NAME],
                        default=os.getenv("FOKUS_PAPER_STRATEGY",AUTO_MODE))
    parser.add_argument("--disable-new-setups",action="store_true")
    parser.add_argument("--skip-macro-calendar",action="store_true",
                        help="Research only! Removes BLS blackout veto, not recommended.")
    args=parser.parse_args(argv)
    if args.interval<60:
        parser.error("Minimum scan interval is 60 seconds")
    # Strict v4 safety: until the owner verifies Capital's UTC candle
    # labeling on DEMO, collect candles and monitor existing PAPER ONLY.
    # No new PENDING state may be created from an assumed bar clock.
    # Capital REST raw candles look OPEN-labelled; market.candles shifts to
    # CLOSE-time internally. Require explicit owner confirmation of "open".
    # The old "close" value must NEVER enable new PAPER entries.
    candle_time_ok=os.getenv("FOKUS_CANDLE_TIME_CONFIRMED","").strip().lower()=="open"
    use_remote=configured()
    remote=RemoteCheckpoint.from_env() if use_remote else None
    db=connect() if not use_remote else None
    client=CapitalReadOnly(os.getenv("CAPITAL_API_KEY",""),
        os.getenv("CAPITAL_IDENTIFIER",os.getenv("CAPITAL_LOGIN","")),
        os.getenv("CAPITAL_PASSWORD",""),environment="DEMO")
    if not candle_time_ok:
        print("WAIT / CANDLE_TIME_UNVERIFIED: collecting DEMO candles, NEW PAPER SETUPS BLOCKED.",flush=True)
    while True:
        try:
            if use_remote:
                message=remote_scan_once(remote,client,args.epic,args.tf,
                    args.strategy,2.0,enable_setups=(not args.disable_new_setups and candle_time_ok),
                    strict_macro=not args.skip_macro_calendar)
            else:
                message=scan_once(client,args.epic,args.tf,args.strategy,2.0,db,
                    enable_setups=(not args.disable_new_setups and candle_time_ok),
                    strict_macro=not args.skip_macro_calendar,
                    telegram_token=os.getenv("TELEGRAM_BOT_TOKEN",""),
                    telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID",""),
                    telegram_enabled=os.getenv("PAPER_TELEGRAM_ALERTS_ENABLED","").lower()
                        in ("true","1","yes"))
            print(datetime.now(timezone.utc).isoformat(),message,flush=True)
        except (FeedError,ValueError,OSError,RuntimeError) as exc:
            print(datetime.now(timezone.utc).isoformat(),
                "WAIT / WORKER ERROR:",type(exc).__name__,flush=True)
            if use_remote:
                # Fail the scheduled job, never claim successful durable progress.
                raise SystemExit(1) from None
        if args.once:
            break
        time.sleep(seconds_until_next_m1_scan() if args.align_minute
                   else args.interval)

if __name__=="__main__":
    main()
