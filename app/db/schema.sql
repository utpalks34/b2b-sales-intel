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
