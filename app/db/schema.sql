CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain TEXT UNIQUE NOT NULL,
    company_name TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    url TEXT NOT NULL,
    source_type TEXT,
    scraped_via TEXT,
    content TEXT,
    fetched_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE decision_makers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    name TEXT,
    title TEXT,
    source_confidence FLOAT
);

CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    signal_type TEXT,
    description TEXT
);

CREATE TABLE email_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    run_id UUID NOT NULL,
    version INT NOT NULL,
    body TEXT,
    critic_score FLOAT,
    critic_feedback TEXT,
    status TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Added for the API/orchestration layer: per-run status + failure
-- tracking. NOT a general run-history table -- only used for looking up
-- a single run_id's current status and surfacing a hard failure
-- (e.g. persist_node's save_research() raising inside a background
-- thread, which would otherwise be silently lost). Run status for the
-- non-failure case (running / awaiting_review / completed / rejected)
-- is derived from LangGraph's own checkpoint state, not from this table.
CREATE TABLE run_status (
    run_id UUID PRIMARY KEY,
    domain TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
