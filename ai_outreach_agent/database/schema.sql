-- ============================================================
-- AI Outreach Agent — PostgreSQL Schema
-- Apply with: psql outreach_db -f schema.sql
-- ============================================================

-- Companies discovered by the scrapers
CREATE TABLE IF NOT EXISTS companies (
    id                  SERIAL PRIMARY KEY,
    company_name        TEXT NOT NULL,
    website             TEXT UNIQUE,
    description         TEXT,
    tech_stack          JSONB DEFAULT '[]'::JSONB,
    contact_email       TEXT,
    linkedin            TEXT,
    location            TEXT,
    source              TEXT,                        -- yc | github_org | directory
    relevance_score     NUMERIC(4, 2),               -- 1.00–10.00
    reasoning           TEXT,
    is_qualified        BOOLEAN DEFAULT FALSE,       -- true when score > threshold
    scraped_at          TIMESTAMPTZ DEFAULT NOW(),
    ranked_at           TIMESTAMPTZ,
    CONSTRAINT uq_website UNIQUE (website)
);

-- Email history — one row per outreach attempt
CREATE TABLE IF NOT EXISTS emails_sent (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    to_address      TEXT NOT NULL,
    subject         TEXT,
    body            TEXT,
    template_used   TEXT,
    status          TEXT DEFAULT 'pending',          -- pending | sent | failed
    error_message   TEXT,
    sent_at         TIMESTAMPTZ DEFAULT NOW()
);

-- Replies received via IMAP
CREATE TABLE IF NOT EXISTS replies (
    id                  SERIAL PRIMARY KEY,
    company_id          INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    from_address        TEXT,
    subject             TEXT,
    raw_message         TEXT,
    classification      TEXT,                        -- positive | neutral | negative
    received_at         TIMESTAMPTZ DEFAULT NOW(),
    notified            BOOLEAN DEFAULT FALSE
);

-- Daily send counter (helper for rate limiting)
CREATE OR REPLACE VIEW daily_send_count AS
    SELECT COUNT(*) AS sent_today
    FROM   emails_sent
    WHERE  status = 'sent'
    AND    sent_at::DATE = CURRENT_DATE;

-- Useful indexes
CREATE INDEX IF NOT EXISTS idx_companies_score     ON companies (relevance_score);
CREATE INDEX IF NOT EXISTS idx_companies_qualified ON companies (is_qualified);
CREATE INDEX IF NOT EXISTS idx_emails_company      ON emails_sent (company_id);
CREATE INDEX IF NOT EXISTS idx_replies_company     ON replies (company_id);
CREATE INDEX IF NOT EXISTS idx_emails_sent_date    ON emails_sent (sent_at);
