-- FOKU$ quote-only 5s cloud snapshot, ONE row per instrument.
-- Run once in the EXISTING FOKU$ Supabase project's SQL Editor.
-- Does NOT alter PAPER, previous checkpoints or closed candle archives.
-- No public/anonymous read access is granted.
CREATE TABLE IF NOT EXISTS public.fokus_live_quotes (
    epic text PRIMARY KEY CHECK (epic = 'US500'),
    source text NOT NULL DEFAULT 'Capital.com DEMO REST'
      CHECK (source = 'Capital.com DEMO REST'),
    bid numeric(20,8) NOT NULL CHECK (bid > 0),
    ask numeric(20,8) NOT NULL CHECK (ask >= bid),
    mid numeric(20,8) NOT NULL CHECK (mid > 0),
    spread numeric(20,8) NOT NULL CHECK (spread >= 0),
    broker_status text NOT NULL,
    broker_update_utc timestamptz,
    received_utc timestamptz NOT NULL,
    delay_seconds numeric(12,3) NOT NULL DEFAULT 0,
    fresh boolean NOT NULL DEFAULT false,
    samples jsonb NOT NULL DEFAULT '[]'::jsonb
      CHECK (jsonb_typeof(samples)='array' AND jsonb_array_length(samples)<=24),
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.fokus_live_quotes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.fokus_live_quotes FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.fokus_live_quotes TO service_role;
COMMENT ON TABLE public.fokus_live_quotes IS
  'FOKUS 5-second broker BID/ASK best-effort cache for read-only owner terminal. No trade decisions or orders.';

-- Audit only. Expected 0 rows before first successful quote:
SELECT COUNT(*) AS cytaty_zapisane FROM public.fokus_live_quotes;
