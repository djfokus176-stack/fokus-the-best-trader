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
import re
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
from .range_rejection import NAME as RANGE_NAME
from .paper_lifecycle import ensure_tables,progress_paper,queue_paper,active_position
from .telegram_alerts import dispatch_alerts,record_stale_event
from .remote_checkpoint import (RemoteCheckpoint, configured, dump_state,
                                restore_state, RemoteError, RemoteConflict)
from .strategy_progress import progress_for_votes
from .obstacle_ab import obstacle_ab_snapshot
from .shadow_learning import advance_shadow, shadow_scorecard
from .mtf_veto_forward import advance_mtf_comparison, mtf_comparison_report
from .momentum_paper_test import advance_momentum_paper_test, momentum_paper_test_report
from .raw_m1_forward_paper import advance_raw_paper, raw_paper_report
from .manual_paper_test import advance_manual_test, expire_request_only, manual_report, note_worker_cycle
from .periodic_archive_audit import attach_periodic_audit
from .capital_demo_broker import advance_demo_broker, config as demo_broker_config, DemoExecutionError
from .paper_daily_risk import paper_daily_risk, DEFAULT_DAILY_STOP_PTS
from .wave_shadow_archive import advance_wave_shadow, wave_shadow_scorecard
from .wave_ae_forward_auto import advance_wave_ae_forward, wave_ae_forward_scorecard
from .cloud_scalp_quotes import Quote5sSampler, idle_quote_pulses
from .cloud_quote_pump import build_quote_pump
from .paper_method_labels import decision_attribution, method_attribution
from .fokus_3f_forward import advance_3f_forward, forward_3f_scorecard
from .worker_scan_health import advance_scan_quality


# RAW uses its own verified M1 OHLC. The directional/availability MTF gate
# belongs to AUTO; all other broker/macro/risk blockers still apply to RAW.
def raw_research_blockers(blockers):
    return tuple(x for x in blockers if x != "INCOMPLETE_MTF")


MAX_CONSECUTIVE_WORKER_ERRORS = 6


def retryable_host_error_action(exc, *, once, failures):
    """Select a safe action after a failed worker cycle, never retry a trade.

    The next cycle fetches a NEW checkpoint and recomputes decisions. A CAS
    writer conflict or credential denial must stop the service immediately.
    No unchecked state from the failed cycle is reused.
    """
    if once or isinstance(exc, RemoteConflict):
        return "EXIT"
    if isinstance(exc, RemoteError):
        label=str(exc)
        if re.search(r"(?:HTTP\s*)?(?:401|403)(?![0-9])",label):
            return "EXIT"
    return "EXIT" if failures>=MAX_CONSECUTIVE_WORKER_ERRORS else "RETRY_NEXT_MINUTE"


def scan_once(client,epic,tf,strategy,max_spread,db, *,
              slippage=.25,enable_setups=True,strict_macro=True,
              calendar_fetch=fetch_bls_schedule,telegram_token="",
              telegram_chat_id="",telegram_enabled=False,remote=None,
              reviewer=None,learning=None,wave_audit=None):
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
    wave_status="NOT_CONFIGURED"
    if wave_audit is not None:
        m15=snapshots.get("MINUTE_15")
        if m15 is None or not m15.good:
            wave_status="WAIT_NO_VALID_M15"
        else:
            try:
                wave_status=str(wave_audit(m15))[:90]
            except (ValueError,TypeError,KeyError,OverflowError,
                    IndexError,RuntimeError) as exc:
                # WAVE SHADOW failure is reported, never changes broker/PAPER
                # entry permissions. No secrets or external exception text.
                wave_status="ERROR_"+type(exc).__name__
    if strategy==AUTO_MODE:
        verdict,auto_votes=evaluate_auto(main.frame,main.spread,snapshots,
                                          asof=main.confirmed_utc,use_mtf=True,
                                          learning=learning)
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
    diagnostics=(["WAVE_SHADOW="+wave_status] if wave_audit is not None else [])
    if "POMINIĘTO_STARE_BŁĘDY=" in main.reason:
        diagnostics.append("DATA_WARN:"+main.reason.split("POMINIĘTO_STARE_BŁĘDY=",1)[1][:100])
    for resolution in TIMEFRAMES:
        if resolution in errors:
            diagnostics.append(f"{resolution}:FETCH_ERROR:{str(errors[resolution])[:100]}")
        elif resolution in snapshots and not snapshots[resolution].good:
            diagnostics.append(f"{resolution}:BAD_SNAPSHOT:{str(snapshots[resolution].reason)[:100]}")
        elif (resolution in snapshots and
              "RECHECK_CLEAN_TAIL=96_AFTER_CORRUPT_HISTORY"
              in str(snapshots[resolution].reason)):
            diagnostics.append(f"{resolution}:CLEAN_TAIL_RECHECK=VERIFIED_96")
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
            # Expose only known internal BLS reason identifiers. Raw
            # network errors may contain sensitive URLs or response bodies.
            detail=str(exc) if isinstance(exc,ValueError) else ""
            if not re.fullmatch(r"BLS_[A-Z0-9_]{5,120}",detail):
                detail=""
            diagnostics.append("BLS_CALENDAR:"+type(exc).__name__+
                               (":"+detail if detail else "")+
                               (f":HTTP{code}" if code else ""))
    # AUTO is an owner-observed VIRTUAL simulation with no broker orders.
    # Do not throttle research after a modeled 20-point loss by default:
    # the legacy PAPER daily brake is opt-in for AUTO only. Keep ALL actual
    # MTF, feed freshness, spread, market and macro gates unchanged.
    # An explicit opt-in re-enables the original loss brake.
    auto_virtual_brake_enabled=(os.getenv(
        "FOKUS_AUTO_VIRTUAL_DAILY_BRAKE_ENABLED","false").strip().lower()
        in ("true","1","yes","on"))
    if verdict.action in ("LONG","SHORT") and (
            strategy!=AUTO_MODE or auto_virtual_brake_enabled):
        try:
            daily_limit=float(os.getenv("FOKUS_PAPER_DAILY_STOP_PTS",
                                        str(DEFAULT_DAILY_STOP_PTS)))
            daily=paper_daily_risk(db,epic=epic,source=main.source,
                asof=main.confirmed_utc,max_drawdown_pts=daily_limit)
            if daily.blocked:
                reasons.append("PAPER_DAILY_DRAWDOWN_LIMIT")
                diagnostics.append(
                    f"PAPER_DAILY_STOP:{daily.day}:"
                    f"REALIZED={daily.realized_pts:+.2f}pkt:"
                    f"MAX_DD={daily.max_drawdown_pts:.2f}pkt:"
                    f"LIMIT={daily.limit_pts:.2f}pkt:"
                    "NEW_PAPER_PAUSED_ONLY")
        except (ValueError,TypeError,OverflowError):
            # Invalid config must never silently remove the safety gate.
            reasons.append("PAPER_DAILY_STOP_CONFIG_INVALID")
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
    # The current candidate may DIFFER from a position opened earlier.
    # Keep these two labels distinct to avoid false AUTO attribution.
    candidate_method=decision_attribution(strategy,verdict)
    active_method=(method_attribution(dict(active))["label"]
                   if active else "BRAK")
    return (f"{main.confirmed_utc.isoformat()} / {verdict.action} / "
            f"CANDIDATE_METHOD={candidate_method} / "
            f"QUEUE={'YES' if queued else 'NO'} / ACTIVE={state} / "
            f"ACTIVE_METHOD={active_method} / "
            f"EVENTS={','.join(transitions) or '-'} / CANDLES={archived} / "
            f"GATES={','.join(reasons) or 'OK'} / "
            f"DIAGNOSTICS={' | '.join(diagnostics)[:700] or '-'} / "
            f"{verdict.reason}")


def remote_scan_once(remote,client,epic,tf,strategy,max_spread, *,
                     enable_setups=True,strict_macro=True,
                     calendar_fetch=fetch_bls_schedule,
                     clock_confirmed_open=None,quote_health=None):
    """Single-worker cloud cycle; fail closed on missing/changed checkpoint.

    Cloud checkpoint is loaded before the scan and CAS-saved after.
    Telegram delivery disabled in this cloud route until atomic cloud
    outbox claiming is available (local at-most-once cannot protect a
    job that crashes after sending but before checkpointing).
    """
    version,payload=remote.fetch()
    old_meta=payload.get("meta")
    old_quality=(old_meta.get("scan_quality") if isinstance(old_meta,dict) else None)
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
    shadow_state=payload.get("shadow_per_strategy") or {}
    mtf_veto_state=payload.get("mtf_veto_forward") or {}
    momentum_test_state=payload.get("momentum_paper_test") or {}
    raw_test_state=payload.get("raw_m1_forward_paper") or {}
    manual_test_state=payload.get("manual_paper_test") or {}
    periodic_archive_before=payload.get("periodic_audit_archive") or {}
    wave_state=payload.get("wave_shadow") or {}
    ae_state=payload.get("wave_ae_forward") or {}
    threef_state=payload.get("fokus_3f_forward") or {}
    threef_enabled=os.getenv("FOKUS_3F_SHADOW_ENABLED","true").strip().lower() in ("true","1","yes","on")
    threef_status=("NOT_YET_PRIMED" if threef_enabled and not threef_state else
                   "DISABLED" if not threef_enabled else
                   str(threef_state.get("status","UNKNOWN")))
    ae_status=(str(ae_state.get("status","NO_NEW_M15")) if ae_state
               else "NOT_YET_PRIMED")
    backfill_state=payload.get("candle_backfill") or {}
    backfill_enabled=(os.getenv("FOKUS_CANDLE_BACKFILL_ENABLED","false")
                      .strip().lower() in ("true","1","yes","on"))

    wave_enabled=os.getenv("FOKUS_WAVE_SHADOW_ENABLED","true").strip().lower() in ("true","1","yes","on")
    # Research-only; does not touch AUTO, PAPER or execute broker orders.
    ae_enabled=os.getenv("FOKUS_WAVE_AE_AUTO_ENABLED","true").strip().lower() in ("true","1","yes","on")
    # A closed market skips the M15 audit but does not disable an already
    # saved WAVE archive. Never call this situation NOT_CONFIGURED.
    wave_status=("DISABLED" if not wave_enabled else
                 "NO_NEW_M15" if wave_state else "NOT_YET_OBSERVED")
    # Selection uses outcomes completed PRIOR to the current decision.
    previous_shadow_report=shadow_scorecard(shadow_state)
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
        nonlocal auto_state,candidates,forecast_state,vote_audit,shadow_state,mtf_veto_state,momentum_test_state,raw_test_state,manual_test_state
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
        vote_audit["progress"]=progress_for_votes(snapshot.frame,votes,blockers)
        # Explicit owner-requested virtual LONG/SHORT is a SEPARATE lane.
        # It never changes strategy votes, AUTO PAPER, RAW, broker DEMO or
        # global market protections. Only next VERIFIED closed M1 advances.
        if tf=="MINUTE":
            try:
                # A forced VIRTUAL diagnostic should test entry/exit
                # without inheriting AUTO's MTF/macro signal restrictions.
                # Fail CLOSED for stale/closed data and disabled setups.
                essential=tuple(b for b in blockers if b in (
                    "SETUPS_DISABLED","MARKET_NOT_TRADEABLE","DATA_STALE"))
                manual_test_state=advance_manual_test(
                    manual_test_state,snapshot.frame,essential,
                    spread=snapshot.spread,source=snapshot.source,
                    epic=epic,market_status=(
                        "NOT_TRADEABLE" if "MARKET_NOT_TRADEABLE" in blockers
                        else "TRADEABLE"))
            except (ValueError,TypeError,KeyError,OverflowError,
                    IndexError,RuntimeError,ArithmeticError) as exc:
                manual_test_state={**(manual_test_state if isinstance(
                    manual_test_state,dict) else {}),
                    "last_reason":"ERROR_"+type(exc).__name__}
        if strategy==AUTO_MODE:
            # Diagnostic A/B, NOT an override of actual AUTO/PAPER. A failure
            # in optional audit can never stop the production PAPER worker.
            try:
                vote_audit["obstacle_ab"]=obstacle_ab_snapshot(
                    snapshot.frame,snapshot.spread,views,
                    blockers=blockers,source=snapshot.source,epic=epic)
            except (ValueError,TypeError,KeyError,OverflowError,
                    IndexError,RuntimeError,ArithmeticError) as exc:
                vote_audit["obstacle_ab"]={
                    "status":"ERROR_"+type(exc).__name__,"rows":[],
                    "research_only":True}
        # Independent one-slot-per-method SHADOW experiment. Never changes
        # current PAPER verdict or models an immediate broker fill.
        if strategy==AUTO_MODE:
            shadow_state=advance_shadow(shadow_state,snapshot.frame,votes,
                                        blockers,spread=snapshot.spread)
            # An INDEPENDENT, strictly DEMO research lane requested for early
            # LONG/SHORT testing. A test candidate is never queued into the
            # existing PAPER v3 ledger, and cannot execute broker orders.
            # Default opt-in for PAPER-only testing; owner can disable by ENV.
            try:
                momentum_enabled=(os.getenv("FOKUS_MOMENTUM_PAPER_TEST_ENABLED",
                    "true").strip().lower() in ("true","1","yes","on"))
                momentum_test_state=advance_momentum_paper_test(
                    momentum_test_state,snapshot.frame,vote_audit["progress"],
                    views,blockers,spread=snapshot.spread,
                    source=snapshot.source,epic=epic,enabled=momentum_enabled)
            except (ValueError,TypeError,KeyError,OverflowError,
                    IndexError,RuntimeError,ArithmeticError) as exc:
                momentum_test_state={**(momentum_test_state if isinstance(
                    momentum_test_state,dict) else {}),
                    "last_reason":"ERROR_"+type(exc).__name__}
            # Independent RAW M1 PAPER test: the exact unfiltered M1 LONG/
            # SHORT candidates (including those rejected by directional MTF)
            # are monitored as actual forward-only simulated positions.
            # Global data, account, broker, macro and risk GATES still apply.
            # No order, no v3 mutation, no switching production AUTO filters.
            if tf=="MINUTE":
                try:
                    raw_enabled=(os.getenv("FOKUS_RAW_M1_PAPER_TEST_ENABLED",
                        "true").strip().lower() in ("true","1","yes","on"))
                    raw_test_state=advance_raw_paper(
                        raw_test_state,snapshot.frame,votes,
                        raw_research_blockers(blockers),
                        spread=snapshot.spread,source=snapshot.source,
                        epic=epic,enabled=raw_enabled)
                except (ValueError,TypeError,KeyError,OverflowError,
                        IndexError,RuntimeError,ArithmeticError) as exc:
                    raw_test_state={**(raw_test_state if isinstance(
                        raw_test_state,dict) else {}),
                        "last_reason":"ERROR_"+type(exc).__name__}
            # Independent FORWARD counterfactual: what happened to REAL raw
            # setups that MTF passed vs vetoed? Never alters PAPER decisions.
            # A broken research record must not block the actual scanner.
            try:
                mtf_veto_state=advance_mtf_comparison(
                    mtf_veto_state,snapshot.frame,votes,blockers,
                    spread=snapshot.spread,source=snapshot.source,epic=epic)
            except (ValueError,TypeError,KeyError,OverflowError,
                    IndexError,RuntimeError,ArithmeticError) as exc:
                mtf_veto_state={**(mtf_veto_state if isinstance(
                    mtf_veto_state,dict) else {}),
                    "last_error":"ERROR_"+type(exc).__name__}
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
            range_exp=decide_any(snapshot.frame,RANGE_NAME,spread=snapshot.spread)
            research_votes.append({"Strategia":RANGE_NAME+" • SHADOW",
                "Setup OHLC":range_exp.action,
                "Po filtrze MTF":"NIE WYLICZANO (SHADOW)",
                "RR":range_exp.rr,"Powód":range_exp.reason})
        candidates=append_candidate(candidates,snapshot,decision,research_votes,blockers,
                                    progress=vote_audit["progress"],
                                    obstacle_ab=vote_audit.get("obstacle_ab"))
        auto_state=review_closed_candle(auto_state,snapshot,decision,votes,views,
                                      blockers,news_context=news_feed,
                                      macro_context=macro_watch)
    def archive_wave_m15(snapshot):
        nonlocal wave_state,wave_status,ae_state,ae_status
        nonlocal threef_state,threef_status
        # Independent RESEARCH only. No PAPER queue and no AUTO votes.
        if not threef_enabled:
            threef_status="DISABLED"
        elif not clock_confirmed_open:
            threef_status="CLOCK_UNVERIFIED"
        else:
            try:
                threef_state=advance_3f_forward(
                    threef_state,snapshot.frame,epic=epic,source=snapshot.source)
                threef_status=str(threef_state.get("status","UNKNOWN"))
            except (ValueError,TypeError,KeyError,OverflowError,
                    IndexError,RuntimeError) as exc:
                # Shadow cannot block account/PAPER updates or leak secrets.
                threef_status="ERROR_"+type(exc).__name__
        if os.getenv("FOKUS_WAVE_SHADOW_ENABLED","true").strip().lower() not in (
                "true","1","yes","on"):
            wave_status="DISABLED"
            return wave_status
        if not clock_confirmed_open:
            wave_status="CLOCK_UNVERIFIED"
            return wave_status
        wave_state=advance_wave_shadow(
            wave_state,snapshot.frame,epic=epic,source=snapshot.source)
        if ae_enabled:
            try:
                ae_state=advance_wave_ae_forward(
                    ae_state,snapshot.frame,epic=epic,source=snapshot.source)
                ae_status=str(ae_state.get("status","UNKNOWN"))
            except (ValueError,TypeError,KeyError,OverflowError,
                    IndexError,RuntimeError) as exc:
                # Fail closed for research without blocking PAPER accounting.
                ae_status="ERROR_"+type(exc).__name__
        else:
            ae_status="DISABLED"
        wave_status=("OK_M15_"+str(wave_state["last_closed_utc"])[:19]+
                     "_N="+str(wave_state["events_retained"]))
        return wave_status
    db=sqlite3.connect(":memory:")
    try:
        restore_state(db,payload)
        status=scan_once(client,epic,tf,strategy,max_spread,db,
                         enable_setups=enable_setups,strict_macro=strict_macro,
                         calendar_fetch=calendar_fetch,telegram_enabled=False,
                         remote=remote,reviewer=review_snapshot,
                         learning=previous_shadow_report,
                         wave_audit=archive_wave_m15)
        # Optional research archive repair. Run after the normal PAPER scan,
        # never before votes, gates or position transitions. One bounded
        # broker query per hour; disabled unless explicitly opted in.
        if backfill_enabled:
            if not clock_confirmed_open:
                backfill_state={**backfill_state,
                                "status":"CLOCK_UNVERIFIED"}
            else:
                try:
                    from .cloud_gap_backfill import backfill_pass
                    backfill_state=backfill_pass(remote,client,backfill_state,
                                                 epic=epic)
                except (RemoteError, FeedError, ValueError, TypeError,
                        OverflowError, OSError) as exc:
                    # Repair failure must not revise PAPER decisions or erase
                    # the old durable cursor. Never expose provider error
                    # text, URLs, tokens or response payloads.
                    backfill_state={**backfill_state,
                                    "last_attempt_utc":datetime.now(timezone.utc).isoformat(),
                                    "status":"ERROR_"+type(exc).__name__}
        # This runs even if scan_once returned before its M1 reviewer.
        # E.g. a stale/missing M1 must be diagnosed as such, rather than
        # silently leaving the UI at QUEUED with no worker heartbeat.
        if tf=="MINUTE":
            manual_test_state=note_worker_cycle(
                manual_test_state,status,now=datetime.now(timezone.utc))
        payload=dump_state(db)
        # Preserve the owner's CAS-saved TEST request across the original
        # SQLite checkpoint dump. Expire it even when a stale data scan
        # returned before reviewer could advance to a new M1.
        if tf=="MINUTE":
            manual_test_state=expire_request_only(manual_test_state)
        payload["manual_paper_test"]=manual_test_state
        payload["manual_paper_test_report"]=manual_report(manual_test_state)
        if backfill_state:
            payload["candle_backfill"]=backfill_state
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
        payload["shadow_per_strategy"]=shadow_state
        if strategy==AUTO_MODE:
            payload["momentum_paper_test"]=momentum_test_state
            payload["momentum_paper_test_report"]=momentum_paper_test_report(
                momentum_test_state)
            if tf=="MINUTE":
                payload["raw_m1_forward_paper"]=raw_test_state
                payload["raw_m1_forward_paper_report"]=raw_paper_report(
                    raw_test_state)
        if strategy==AUTO_MODE:
            payload["mtf_veto_forward"]=mtf_veto_state
            payload["mtf_veto_forward_report"]=mtf_comparison_report(
                mtf_veto_state)
        if wave_state:
            payload["wave_shadow"]=wave_state
            # WAVE SHADOW must persist even on market closure, before
            # the new A-E module has been primed.
            payload["wave_shadow_report"]=wave_shadow_scorecard(wave_state)
        if ae_state:
            payload["wave_ae_forward"]=ae_state
            payload["wave_ae_forward_report"]=wave_ae_forward_scorecard(ae_state)
        if threef_state:
            payload["fokus_3f_forward"]=threef_state
            payload["fokus_3f_forward_report"]=forward_3f_scorecard(threef_state)
        latest_shadow_report=shadow_scorecard(shadow_state)
        payload["shadow_learning_report"]=latest_shadow_report
        # Audit each scan from the SAME durable CLOSED v3, Momentum and RAW
        # histories; deduplicate events across restart and old archive reads.
        # Never mix lanes, use Poland-local day/week/month boundaries, never
        # manufacture old entries from OHLC. No extra Supabase tables/keys.
        # Keep a previously valid archive intact if optional audit fails.
        try:
            payload=attach_periodic_audit(
                periodic_archive_before,payload,
                now=datetime.now(timezone.utc))
        except (ValueError,TypeError,KeyError,OverflowError,RuntimeError,
                ArithmeticError) as exc:
            if isinstance(periodic_archive_before,dict) and periodic_archive_before.get("schema")==1:
                payload["periodic_audit_archive"]=periodic_archive_before
            payload["periodic_audit_status"]="ERROR_"+type(exc).__name__
        # Sample thread diagnostics immediately before commit, not before
        # potentially long MTF/GPT/Supabase scan. The callback is pure.
        if callable(quote_health):
            quote_health=quote_health()
        payload["meta"]={
            "last_scan_utc":datetime.now(timezone.utc).isoformat(),
            "scan_quality":advance_scan_quality(status,old_quality),
            "last_scan_summary":status[:350],
            "source":"Capital.com DEMO REST",
            "timeframe":tf,"epic":epic,
            "strategy":strategy,
            "wave_shadow_status":wave_status,
            "wave_shadow_enabled":os.getenv("FOKUS_WAVE_SHADOW_ENABLED",
                                            "true").strip().lower() in ("true","1","yes","on"),
            "wave_shadow_last_m15":wave_state.get("last_closed_utc"),
            "wave_shadow_forward_events":wave_state.get("events_forward",0),
            "wave_ae_auto_enabled":bool(ae_enabled),
            "wave_ae_status":ae_status,
            "wave_ae_forward_events":len(ae_state.get("events") or []),
            "wave_ae_last_m15":ae_state.get("last_closed_utc"),
            "fokus_3f_enabled":bool(threef_enabled),
            "fokus_3f_status":threef_status,
            "fokus_3f_last_m15":threef_state.get("last_closed_utc"),
            "fokus_3f_forward_events":len(threef_state.get("events") or []),
            "fokus_3f_trade_permission":"WAIT",
            # Nonsecret PAPER simulation threshold for the owner's read-only
            # terminal; the worker alone decides whether entries are paused.
            "paper_daily_stop_pts":os.getenv(
                "FOKUS_PAPER_DAILY_STOP_PTS",str(DEFAULT_DAILY_STOP_PTS)),
            "auto_virtual_daily_brake_enabled":(
                os.getenv("FOKUS_AUTO_VIRTUAL_DAILY_BRAKE_ENABLED",
                          "false").strip().lower() in
                ("true","1","yes","on")),
            "shadow_leader":latest_shadow_report.get("leader"),
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
            # Nonsecret, non-trading diagnostics for the independent
            # same-login quote pump, retained in the existing checkpoint.
            "quote_pump":(
                {k:quote_health.get(k) for k in (
                    "mode","status","last_attempt_utc","last_write_utc",
                    "last_fresh_utc","attempts","trade_permission")}
                if isinstance(quote_health,dict) else
                {"mode":"DISABLED_OR_LEGACY","status":"NO_BACKGROUND_PUMP",
                 "last_attempt_utc":None,"last_write_utc":None,
                 "last_fresh_utc":None,"attempts":0,
                 "trade_permission":"WAIT"}),
            "candle_backfill_enabled":bool(backfill_enabled),
            "candle_backfill_status":backfill_state.get("status","DISABLED")
                if backfill_enabled else "DISABLED",
            "telegram_remote":"DISABLED"}
        new_version=remote.save(version,payload)
        # Optional REAL executions on the Capital.com DEMO VIRTUAL account.
        # They are NOT PAPER v3, and the default is OFF. Only the exact
        # DEMO_ONLY_CONFIRMED env setting with explicitly verified account ID
        # and position size allows any order request. NEVER touch LIVE.
        demo_line=""
        demo_cfg=demo_broker_config()
        if demo_cfg["enabled"] and strategy==AUTO_MODE:
            try:
                new_version,payload,demo_event=advance_demo_broker(
                    remote,client,new_version,payload)
                demo_line=" / CAPITAL_DEMO_BROKER="+str(
                    demo_event.get("status","UNKNOWN"))[:90]
            except (DemoExecutionError,RemoteError,FeedError,ValueError,
                    TypeError,OverflowError,RuntimeError) as exc:
                # A broker execution failure must not cause a second order.
                # The broker executor persists ATTEMPTED BEFORE any POST.
                demo_line=" / CAPITAL_DEMO_BROKER=ERROR_"+type(exc).__name__
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
            preview=vote_audit.get("progress") or []
            if preview:
                audit_line+=" / SETUP_PROGRESS="+json.dumps([
                    str(p.get("strategy"))+":"+str(p.get("progress"))+
                    ":"+str(p.get("side")) for p in preview],ensure_ascii=False)
            audit_line+=" / MTF_STATES="+json.dumps([
                str(v.get("timeframe"))+":"+str(v.get("trend"))+
                (":READY" if v.get("ready") else ":NOT_READY")
                for v in vote_audit.get("mtf",[])],ensure_ascii=False)
        return (status+f" / CLOUD_CHECKPOINT_VERSION={new_version} / TELEGRAM_REMOTE=DISABLED"
                +" / SHADOW_LEARNING="+str(latest_shadow_report.get("leader") or "INSUFFICIENT_DATA")
                +demo_line+audit_line)
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
    scalp_5s_enabled=(use_remote and os.getenv("FOKUS_SCALP_5S_ENABLED","true")
                      .strip().lower() in ("true","1","yes","on"))
    quote_sampler=Quote5sSampler() if scalp_5s_enabled else None
    client=CapitalReadOnly(os.getenv("CAPITAL_API_KEY",""),
        os.getenv("CAPITAL_IDENTIFIER",os.getenv("CAPITAL_LOGIN","")),
        os.getenv("CAPITAL_PASSWORD",""),environment="DEMO")
    quote_pump=None
    if quote_sampler is not None and not args.once:
        # Quote collection MUST continue even when the complete MTF +
        # Supabase PAPER scan consumes all available idle seconds.
        # Separate HTTP clients, the SAME Capital login.
        quote_pump=build_quote_pump(client,epic=args.epic,
                                   sampler=quote_sampler).start()
        print("CLOUD QUOTE PUMP: 5s observer independent of PAPER scans; "
              "one broker login, one PAPER checkpoint writer.",
              flush=True)
    if not candle_time_ok:
        print("WAIT / CANDLE_TIME_UNVERIFIED: collecting DEMO candles, NEW PAPER SETUPS BLOCKED.",flush=True)
    consecutive_errors=0
    while True:
        try:
            if use_remote:
                message=remote_scan_once(remote,client,args.epic,args.tf,
                    args.strategy,2.0,enable_setups=(not args.disable_new_setups and candle_time_ok),
                    strict_macro=not args.skip_macro_calendar,
                    quote_health=quote_pump.snapshot if quote_pump else None)
            else:
                message=scan_once(client,args.epic,args.tf,args.strategy,2.0,db,
                    enable_setups=(not args.disable_new_setups and candle_time_ok),
                    strict_macro=not args.skip_macro_calendar,
                    telegram_token=os.getenv("TELEGRAM_BOT_TOKEN",""),
                    telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID",""),
                    telegram_enabled=os.getenv("PAPER_TELEGRAM_ALERTS_ENABLED","").lower()
                        in ("true","1","yes"))
            print(datetime.now(timezone.utc).isoformat(),message,flush=True)
            consecutive_errors=0
        except (FeedError,ValueError,OSError,RuntimeError) as exc:
            # A failed cycle NEVER writes an authorised PAPER entry. The next
            # cycle reloads Supabase before taking any further decisions.
            # In a persistent host, one transient HTTP 429/503 or failed
            # Supabase request must not restart the process and drop M1 bars.
            # Explicit --once jobs, CAS conflicts and repeated/auth failures
            # still exit nonzero. Do not print arbitrary provider exceptions.
            consecutive_errors+=1
            safe_detail=(" / "+str(exc)) if isinstance(exc, RemoteError) else ""
            action=retryable_host_error_action(
                exc,once=args.once,failures=consecutive_errors)
            print(datetime.now(timezone.utc).isoformat(),
                "WAIT / WORKER ERROR:",type(exc).__name__+safe_detail,
                " / FAILURE_STREAK="+str(consecutive_errors),
                " / RECOVERY="+action,flush=True)
            if action=="EXIT":
                raise SystemExit(1) from None
        if args.once:
            break
        idle_seconds=(seconds_until_next_m1_scan() if args.align_minute
                      else args.interval)
        if quote_pump is not None:
            # Background worker handles all quote samples, also during
            # the PAPER scan and this wait. Do NOT double-poll.
            diag=quote_pump.snapshot()
            if diag["status"].startswith(("QUOTE_WAIT_",
                                           "QUOTE_PUMP_ERROR_")):
                print(datetime.now(timezone.utc).isoformat(),
                      "WAIT / CLOUD_QUOTE_PUMP / "+diag["status"]+
                      " / last_fresh_utc="+str(diag["last_fresh_utc"]),
                      flush=True)
            time.sleep(idle_seconds)
        elif quote_sampler is not None and not args.once:
            idle_quote_pulses(client,remote,args.epic,idle_seconds,quote_sampler)
        else:
            time.sleep(idle_seconds)

if __name__=="__main__":
    main()
