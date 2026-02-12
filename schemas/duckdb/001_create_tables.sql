-- After Hours – DuckDB Analytical Schema
-- This schema stores raw and staging data for the analytical lakehouse.

------------------------------------------------------------
-- Parliament Members
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parliament_members (
    member_id       INTEGER PRIMARY KEY,
    name_display    VARCHAR NOT NULL,
    name_first      VARCHAR,
    name_last       VARCHAR,
    date_of_birth   DATE,
    gender          VARCHAR,
    party           VARCHAR,
    constituency    VARCHAR,
    house           VARCHAR NOT NULL,  -- 'Commons' | 'Lords'
    start_date      DATE,
    end_date        DATE,
    thumbnail_url   VARCHAR,
    fetched_at      TIMESTAMP DEFAULT current_timestamp
);

------------------------------------------------------------
-- Committee Memberships
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS committee_memberships (
    membership_id   INTEGER PRIMARY KEY,
    member_id       INTEGER NOT NULL REFERENCES parliament_members(member_id),
    committee_name  VARCHAR NOT NULL,
    start_date      DATE,
    end_date        DATE,
    fetched_at      TIMESTAMP DEFAULT current_timestamp
);

------------------------------------------------------------
-- Register of Financial Interests
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_interests (
    interest_id     VARCHAR PRIMARY KEY,
    member_id       INTEGER NOT NULL REFERENCES parliament_members(member_id),
    category        VARCHAR NOT NULL,
    description     TEXT NOT NULL,
    date_registered DATE,
    date_updated    DATE,
    -- Extracted fields (best-effort from free-text descriptions)
    extracted_company_name VARCHAR,
    extracted_role         VARCHAR,
    extracted_amount       DECIMAL(15, 2),
    fetched_at      TIMESTAMP DEFAULT current_timestamp
);

------------------------------------------------------------
-- Companies House Officers
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ch_officers (
    officer_id          VARCHAR PRIMARY KEY,
    company_number      VARCHAR NOT NULL,
    name                VARCHAR NOT NULL,
    date_of_birth_year  INTEGER,
    date_of_birth_month INTEGER,
    role                VARCHAR NOT NULL,  -- 'director' | 'secretary' | etc.
    appointed_on        DATE,
    resigned_on         DATE,
    nationality         VARCHAR,
    country_of_residence VARCHAR,
    address_locality    VARCHAR,
    address_postcode    VARCHAR,
    identity_verified   BOOLEAN DEFAULT FALSE,
    fetched_at          TIMESTAMP DEFAULT current_timestamp
);

------------------------------------------------------------
-- Companies House Company Profiles
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ch_companies (
    company_number      VARCHAR PRIMARY KEY,
    company_name        VARCHAR NOT NULL,
    company_status      VARCHAR,
    company_type        VARCHAR,
    date_of_creation    DATE,
    date_of_cessation   DATE,
    registered_office_address_line1 VARCHAR,
    registered_office_postcode      VARCHAR,
    registered_office_locality      VARCHAR,
    registered_office_region        VARCHAR,
    sic_codes           VARCHAR[],
    fetched_at          TIMESTAMP DEFAULT current_timestamp
);

------------------------------------------------------------
-- Procurement Contracts (OCDS)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS procurement_contracts (
    ocid                VARCHAR PRIMARY KEY,
    title               VARCHAR,
    description         TEXT,
    status              VARCHAR,
    tender_value        DECIMAL(15, 2),
    tender_currency     VARCHAR DEFAULT 'GBP',
    award_date          DATE,
    buyer_name          VARCHAR,
    buyer_id            VARCHAR,
    supplier_name       VARCHAR,
    supplier_id         VARCHAR,  -- Companies House number where available
    procurement_method  VARCHAR,
    fetched_at          TIMESTAMP DEFAULT current_timestamp
);

------------------------------------------------------------
-- Council Extracted Data (from PDFs via Gemini)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS council_extracted (
    record_id           VARCHAR PRIMARY KEY,
    source_pdf          VARCHAR NOT NULL,
    council_name        VARCHAR,
    meeting_date        DATE,
    councillor_name     VARCHAR,
    vote_direction      VARCHAR,  -- 'for' | 'against' | 'abstain'
    planning_decision   VARCHAR,
    motion_text         TEXT,
    extraction_model    VARCHAR DEFAULT 'gemini-2.0-flash',
    confidence_score    FLOAT,
    fetched_at          TIMESTAMP DEFAULT current_timestamp
);

------------------------------------------------------------
-- Entity Resolution Linkage Table
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS linkage_table (
    link_id             VARCHAR PRIMARY KEY,
    source_a_table      VARCHAR NOT NULL,
    source_a_id         VARCHAR NOT NULL,
    source_b_table      VARCHAR NOT NULL,
    source_b_id         VARCHAR NOT NULL,
    match_probability   FLOAT NOT NULL,  -- 0.0 to 1.0
    risk_score          INTEGER,         -- 1 to 100
    review_status       VARCHAR NOT NULL DEFAULT 'pending_review',
    reviewed_by         VARCHAR,
    reviewed_at         TIMESTAMP,
    created_at          TIMESTAMP DEFAULT current_timestamp
);
