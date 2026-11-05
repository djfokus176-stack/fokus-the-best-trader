-- PAPER V4 private durable checkpoint. Run in a NEW dedicated Supabase
-- project (never reuse an unrelated project without owner approval).
-- SERVICE SECRET belongs ONLY in server-side Secrets / GitHub Actions secrets.
-- This table stores hypothetical PAPER account state and event outbox,
-- not personally identifying brokerage credentials or OpenAI transcripts.
create table if not exists public.fokus_paper_checkpoint (
    id text primary key check (id = 'main'),
    version bigint not null default 0 check (version >= 0),
    payload jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);
alter table public.fokus_paper_checkpoint enable row level security;
revoke all on public.fokus_paper_checkpoint from anon, authenticated;
grant select, update on public.fokus_paper_checkpoint to service_role;
insert into public.fokus_paper_checkpoint(id,version,payload)
values ('main',0,'{"schema":1,"tables":{}}'::jsonb)
on conflict (id) do nothing;
-- No public or authenticated RLS policy. Service role / backend only.

-- Isolated durable OHLC record archive (separate from PAPER state).
create table if not exists public.fokus_closed_candles (
    source text not null,
    epic text not null,
    timeframe text not null,
    candle_utc timestamptz not null,
    open numeric not null,
    high numeric not null,
    low numeric not null,
    close numeric not null,
    spread numeric not null,
    primary key (source,epic,timeframe,candle_utc),
    constraint fokus_candle_valid check
      (high >= greatest(open,low,close)
       and low <= least(open,high,close)
       and spread >= 0)
);
create index if not exists fokus_closed_candles_range
on public.fokus_closed_candles (epic,timeframe,candle_utc desc);
alter table public.fokus_closed_candles enable row level security;
revoke all on public.fokus_closed_candles from anon, authenticated;
grant select, insert, update on public.fokus_closed_candles to service_role;
-- No public RLS policies. No INSERT through browser JavaScript.
