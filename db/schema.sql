-- =====================================================================
-- ALSAAB AI — Unified PostgreSQL Schema (Supabase / Render Postgres)
-- =====================================================================
-- Replaces BOTH data stores with one SQL database:
--   1. SQLite  alsaab_ai.db      (messages, leads, profiles, subs, usage)
--   2. Google Sheets (27 tabs)   (partners, tree, commissions, levels, ...)
--
-- Derived from:
--   backend/database.py            -> init_db(), init_level_qualification_tables()
--   Google Apps Script (15,202 ln) -> all *_HEADERS definitions
--
-- Run once:  psql "$DATABASE_URL" -f db/schema.sql
-- Idempotent: safe to re-run.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 0. Helpers
-- ---------------------------------------------------------------------

-- Auto-maintain updated_at on every UPDATE.
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Replicates Apps Script generatePartnerId(): "ALS-P" + zero-padded counter.
-- The sheet version scanned every row for MAX(); a sequence is atomic and
-- cannot produce duplicates under concurrent signups.
CREATE SEQUENCE IF NOT EXISTS partner_id_seq START WITH 1;

CREATE OR REPLACE FUNCTION next_partner_id()
RETURNS TEXT AS $$
    SELECT 'ALS-P' || LPAD(nextval('partner_id_seq')::TEXT, 5, '0');
$$ LANGUAGE sql;


-- =====================================================================
-- 1. PARTNERS  (Sheet: Partners)
-- =====================================================================
CREATE TABLE IF NOT EXISTS partners (
    partner_id               TEXT PRIMARY KEY DEFAULT next_partner_id(),
    client_id                TEXT,
    sponsor_partner_id       TEXT,
    parent_partner_id        TEXT,
    partner_name             TEXT NOT NULL DEFAULT '',
    phone                    TEXT,
    email                    TEXT,
    country                  TEXT,
    partner_rank             TEXT NOT NULL DEFAULT 'Level 1',
    status                   TEXT NOT NULL DEFAULT 'active',
    referral_link            TEXT,
    invited_by               TEXT,
    active_direct_customers  INTEGER NOT NULL DEFAULT 0,
    active_network_customers INTEGER NOT NULL DEFAULT 0,
    notes                    TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- DEFERRABLE so a bulk CSV import can insert rows in any order; the
    -- whole tree only has to be consistent at COMMIT time.
    CONSTRAINT partners_sponsor_fk
        FOREIGN KEY (sponsor_partner_id) REFERENCES partners(partner_id)
        ON DELETE SET NULL
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT partners_no_self_sponsor
        CHECK (sponsor_partner_id IS DISTINCT FROM partner_id)
);

-- NOTE: the 'alsaab' company-root row is seeded at the END of this file, not
-- here. Inserting into a table whose FK is DEFERRABLE INITIALLY DEFERRED
-- leaves a pending trigger event, and PostgreSQL then refuses to build an
-- index on that table inside the same transaction:
--     ERROR 55006: cannot CREATE INDEX "partners" because it has pending
--                  trigger events
-- All DDL first, seed data last.

-- Apps Script findExistingPartner() matched on phone / email / client_id.
-- These partial-unique indexes make that dedup a database guarantee.
CREATE UNIQUE INDEX IF NOT EXISTS partners_phone_uidx
    ON partners (phone)     WHERE phone     IS NOT NULL AND phone     <> '';
CREATE UNIQUE INDEX IF NOT EXISTS partners_email_uidx
    ON partners (LOWER(email)) WHERE email  IS NOT NULL AND email     <> '';
CREATE UNIQUE INDEX IF NOT EXISTS partners_client_uidx
    ON partners (client_id) WHERE client_id IS NOT NULL AND client_id <> '';

CREATE INDEX IF NOT EXISTS partners_sponsor_idx ON partners (sponsor_partner_id);
CREATE INDEX IF NOT EXISTS partners_status_idx  ON partners (status);

DROP TRIGGER IF EXISTS partners_touch ON partners;
CREATE TRIGGER partners_touch BEFORE UPDATE ON partners
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 2. PARTNER_TREE  (Sheet: PartnerTree)  — closure table
-- =====================================================================
-- NOTE: this table is now OPTIONAL. Postgres can walk the upline/downline
-- directly from partners.sponsor_partner_id with a RECURSIVE CTE
-- (see views at the bottom). It is kept so the migration is 1:1 and the
-- existing dashboards keep working unchanged.
CREATE TABLE IF NOT EXISTS partner_tree (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ancestor_partner_id    TEXT NOT NULL,
    descendant_partner_id  TEXT NOT NULL,
    depth                  INTEGER NOT NULL CHECK (depth BETWEEN 1 AND 5),
    line_owner_partner_id  TEXT,
    notes                  TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT partner_tree_unique
        UNIQUE (ancestor_partner_id, descendant_partner_id, depth)
);

CREATE INDEX IF NOT EXISTS partner_tree_ancestor_idx   ON partner_tree (ancestor_partner_id, depth);
CREATE INDEX IF NOT EXISTS partner_tree_descendant_idx ON partner_tree (descendant_partner_id, depth);


-- =====================================================================
-- 3. PARTNER_LEVELS  (Sheet: MLMLevels + SQLite partner_level_progress)
-- =====================================================================
-- The two stores held the SAME entity with different columns. Merged here.
CREATE TABLE IF NOT EXISTS partner_levels (
    partner_id               TEXT PRIMARY KEY REFERENCES partners(partner_id) ON DELETE CASCADE,
    partner_rank             TEXT NOT NULL DEFAULT 'Level 1',
    current_level            INTEGER NOT NULL DEFAULT 0,
    current_level_name       TEXT,
    next_rank                TEXT,
    next_level               INTEGER,
    next_level_name          TEXT,
    required_sales           INTEGER NOT NULL DEFAULT 1,
    completed_sales          INTEGER NOT NULL DEFAULT 0,
    required_course_workshop TEXT,
    level_status             TEXT NOT NULL DEFAULT 'active',
    current_package          TEXT,
    subscription_status      TEXT,
    subscription_active      BOOLEAN NOT NULL DEFAULT FALSE,
    commission_eligible      BOOLEAN NOT NULL DEFAULT FALSE,
    active_direct_customers  INTEGER NOT NULL DEFAULT 0,
    purchased_courses        JSONB NOT NULL DEFAULT '[]'::JSONB,
    missing_requirements     JSONB NOT NULL DEFAULT '[]'::JSONB,
    progress_json            JSONB,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS partner_levels_eligible_idx
    ON partner_levels (commission_eligible, current_level);

DROP TRIGGER IF EXISTS partner_levels_touch ON partner_levels;
CREATE TRIGGER partner_levels_touch BEFORE UPDATE ON partner_levels
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- Static level rules, lifted out of ALSAAB_LEVEL_REQUIREMENTS() so they
-- can be tuned without a code deploy.
CREATE TABLE IF NOT EXISTS level_requirements (
    level_number                INTEGER PRIMARY KEY CHECK (level_number BETWEEN 1 AND 5),
    rank_label                  TEXT NOT NULL,
    level_name                  TEXT NOT NULL,
    allowed_packages            TEXT[] NOT NULL,
    min_active_direct_customers INTEGER NOT NULL DEFAULT 0,
    required_courses            TEXT[] NOT NULL DEFAULT '{}',
    commission_rate             NUMERIC(5,2) NOT NULL
);

-- The plan rules, as confirmed by the business owner.
--
-- allowed_packages is CUMULATIVE: "299 and up" means starter, growth, elite
-- and diamond — not starter alone. Every package on sale must therefore
-- appear in every level it satisfies, otherwise the partner who sold it drops
-- to level 0 and earns nothing.
--
--   level  own package    direct paying customers  course          rate  depth
--   1      99   entry+    1                        -               25%   1
--   2      299  starter+  2                        -                5%   2
--   3      599  growth+   5                        pro marketer     4%   3
--   4      1199 elite+    10                       sales secrets    3%   4
--   5      2399 diamond   20                       change journey   2%   5
--
-- The Apps Script version this replaces predated the entry and diamond
-- packages, set level 1 and 2 one package too high, required 15/30 customers
-- for levels 4/5, and pointed at three course codes that do not exist.
INSERT INTO level_requirements
    (level_number, rank_label, level_name, allowed_packages, min_active_direct_customers, required_courses, commission_rate)
VALUES
    (1, 'Level 1', 'Starter Partner', ARRAY['entry','starter','growth','elite','diamond'],  1, ARRAY[]::TEXT[],                    25),
    (2, 'Level 2', 'Growth Partner',  ARRAY['starter','growth','elite','diamond'],          2, ARRAY[]::TEXT[],                     5),
    (3, 'Level 3', 'Sales Partner',   ARRAY['growth','elite','diamond'],                    5, ARRAY['pro_marketer_mindset_69'],    4),
    (4, 'Level 4', 'Leader Partner',  ARRAY['elite','diamond'],                            10, ARRAY['sales_secrets_999'],          3),
    (5, 'Level 5', 'Elite Partner',   ARRAY['diamond'],                                    20, ARRAY['change_journey_299'],         2)
ON CONFLICT (level_number) DO UPDATE SET
    allowed_packages            = EXCLUDED.allowed_packages,
    min_active_direct_customers = EXCLUDED.min_active_direct_customers,
    required_courses            = EXCLUDED.required_courses,
    commission_rate             = EXCLUDED.commission_rate;


-- =====================================================================
-- 4. LEADS  (Sheet: Leads + SQLite leads)
-- =====================================================================
CREATE TABLE IF NOT EXISTS leads (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id         TEXT,
    client_id          TEXT,
    source_partner_id  TEXT,
    referral_saved_at  TIMESTAMPTZ,
    name               TEXT,
    phone              TEXT,
    user_type          TEXT,
    business_name      TEXT,
    business_type      TEXT,
    pain_point         TEXT,
    channel            TEXT NOT NULL DEFAULT 'website',
    status             TEXT NOT NULL DEFAULT 'new',
    email              TEXT,
    country            TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS leads_session_idx  ON leads (session_id);
CREATE INDEX IF NOT EXISTS leads_phone_idx    ON leads (phone);
CREATE INDEX IF NOT EXISTS leads_partner_idx  ON leads (source_partner_id);
CREATE INDEX IF NOT EXISTS leads_created_idx  ON leads (created_at DESC);


-- =====================================================================
-- 5. REFERRALS  (Sheet: Referrals)
-- =====================================================================
CREATE TABLE IF NOT EXISTS referrals (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_partner_id      TEXT,
    referral_name          TEXT,
    referral_phone         TEXT,
    referral_email         TEXT,
    source                 TEXT NOT NULL DEFAULT 'website',
    package                TEXT,
    payment_status         TEXT NOT NULL DEFAULT 'pending',
    subscription_status    TEXT NOT NULL DEFAULT 'pending',
    session_id             TEXT,
    client_id              TEXT,
    stripe_subscription_id TEXT,
    notes                  TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS referrals_partner_idx ON referrals (source_partner_id);
CREATE INDEX IF NOT EXISTS referrals_session_idx ON referrals (session_id);
CREATE INDEX IF NOT EXISTS referrals_sub_idx     ON referrals (stripe_subscription_id);

DROP TRIGGER IF EXISTS referrals_touch ON referrals;
CREATE TRIGGER referrals_touch BEFORE UPDATE ON referrals
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 6. CLIENT_PROFILES  (Sheet: ClientProfiles + SQLite client_profiles)
-- =====================================================================
CREATE TABLE IF NOT EXISTS client_profiles (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id          TEXT UNIQUE,
    client_id           TEXT,
    business_name       TEXT,
    business_type       TEXT,
    general_description TEXT,
    products            TEXT,
    prices              TEXT,
    offers              TEXT,
    ordering            TEXT,
    whatsapp            TEXT,
    areas               TEXT,
    faqs                TEXT,
    objections          TEXT,
    tone                TEXT,
    raw_data            JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS client_profiles_client_idx ON client_profiles (client_id);

DROP TRIGGER IF EXISTS client_profiles_touch ON client_profiles;
CREATE TRIGGER client_profiles_touch BEFORE UPDATE ON client_profiles
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 7. SUBSCRIPTIONS  (Sheet: Subscriptions + SQLite client_subscriptions)
-- =====================================================================
-- MERGED. The sheet held billing/commission fields; SQLite held usage
-- counters. Same entity, one row now.
CREATE TABLE IF NOT EXISTS subscriptions (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id                  TEXT UNIQUE,
    client_id                   TEXT,
    bot_id                      TEXT,
    source_partner_id           TEXT,
    plan_name                   TEXT,
    package_amount              NUMERIC(12,2),
    subscription_status         TEXT NOT NULL DEFAULT 'inactive',
    monthly_reply_limit         INTEGER,
    monthly_replies_used        INTEGER NOT NULL DEFAULT 0,
    owner_advisory_replies_used INTEGER NOT NULL DEFAULT 0,
    billing_cycle_start         TIMESTAMPTZ,
    billing_cycle_end           TIMESTAMPTZ,
    current_period_start        TIMESTAMPTZ,
    current_period_end          TIMESTAMPTZ,
    stripe_customer_id          TEXT,
    stripe_subscription_id      TEXT,
    notes                       TEXT,
    -- Cancellation is always end-of-period: the customer paid for the month
    -- and keeps the service until it runs out. Until these columns existed the
    -- system could not tell "active" from "active but ending on the 26th" —
    -- that state lived only in the free-text admin notes of the request row.
    cancel_requested_at         TIMESTAMPTZ,
    cancel_at_period_end        BOOLEAN NOT NULL DEFAULT FALSE,
    cancel_effective_at         TIMESTAMPTZ,
    cancel_reason               TEXT,
    -- Stripe retries a failed charge up to four times across roughly three
    -- weeks. Dropping the customer on the first failure therefore punishes a
    -- sponsor for a card that is about to go through anyway, and can cost them
    -- a whole level for a few days. grace_until holds the line until Stripe
    -- has actually given up.
    payment_failed_at           TIMESTAMPTZ,
    payment_grace_until         TIMESTAMPTZ,
    payment_retry_count         INTEGER NOT NULL DEFAULT 0,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Finds subscriptions that are winding down, for the admin view and for any
-- future "your customer leaves in 5 days" reminder.
CREATE INDEX IF NOT EXISTS subscriptions_ending_idx
    ON subscriptions (cancel_effective_at)
    WHERE cancel_at_period_end IS TRUE;

-- findExistingSubscription() in Apps Script matched on these keys.
CREATE UNIQUE INDEX IF NOT EXISTS subscriptions_stripe_sub_uidx
    ON subscriptions (stripe_subscription_id)
    WHERE stripe_subscription_id IS NOT NULL AND stripe_subscription_id <> '';

CREATE INDEX IF NOT EXISTS subscriptions_client_idx  ON subscriptions (client_id);
CREATE INDEX IF NOT EXISTS subscriptions_partner_idx ON subscriptions (source_partner_id);
CREATE INDEX IF NOT EXISTS subscriptions_status_idx  ON subscriptions (subscription_status);

DROP TRIGGER IF EXISTS subscriptions_touch ON subscriptions;
CREATE TRIGGER subscriptions_touch BEFORE UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 8. COMMISSIONS  (Sheet: Commissions)
-- =====================================================================
CREATE TABLE IF NOT EXISTS commissions (
    commission_id          TEXT PRIMARY KEY,
    invoice_id             TEXT,
    stripe_subscription_id TEXT,
    payer_client_id        TEXT,
    payer_name             TEXT,
    source_partner_id      TEXT,
    beneficiary_partner_id TEXT NOT NULL,
    commission_depth       INTEGER NOT NULL CHECK (commission_depth BETWEEN 1 AND 5),
    line_owner_partner_id  TEXT,
    partner_rank           TEXT,
    package                TEXT,
    package_amount         NUMERIC(12,2),
    commission_percent     NUMERIC(5,2),
    commission_amount      NUMERIC(12,2),
    period_start           TIMESTAMPTZ,
    period_end             TIMESTAMPTZ,
    status                 TEXT NOT NULL DEFAULT 'pending',
    paid_date              TIMESTAMPTZ,
    notes                  TEXT,
    commission_unique_key  TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- These are exactly the values ALSAAB_ADMIN_COMMISSION_ALLOWED_STATUSES_
    -- (Apps Script line 6446) accepts, plus the 'held' spelling the dashboard
    -- bucketing also tolerates. 'hold' was missing from an earlier version of
    -- this constraint, which blocked the admin "put on hold" action outright.
    CONSTRAINT commissions_status_valid
        CHECK (status IN ('pending','approved','hold','held','rejected','paid','cancelled'))
);

-- ***** THE FIX FOR DOUBLE-PAID COMMISSIONS *****
-- Apps Script built this key in buildCommissionUniqueKey() but only checked
-- it with a best-effort row scan — a retried Stripe webhook could still
-- insert a duplicate. Here the database refuses it outright.
CREATE UNIQUE INDEX IF NOT EXISTS commissions_unique_key_uidx
    ON commissions (commission_unique_key);

CREATE INDEX IF NOT EXISTS commissions_beneficiary_idx ON commissions (beneficiary_partner_id, status);
CREATE INDEX IF NOT EXISTS commissions_source_idx      ON commissions (source_partner_id);
CREATE INDEX IF NOT EXISTS commissions_invoice_idx     ON commissions (invoice_id);
CREATE INDEX IF NOT EXISTS commissions_period_idx      ON commissions (period_start DESC);

DROP TRIGGER IF EXISTS commissions_touch ON commissions;
CREATE TRIGGER commissions_touch BEFORE UPDATE ON commissions
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 9. COURSE_PURCHASES  (Sheet: CoursePurchases + SQLite course_purchases)
-- =====================================================================
CREATE TABLE IF NOT EXISTS course_purchases (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    partner_id         TEXT,
    client_id          TEXT,
    course_code        TEXT NOT NULL,
    course_name        TEXT,
    amount             NUMERIC(12,2),
    currency           TEXT NOT NULL DEFAULT 'USD',
    status             TEXT NOT NULL DEFAULT 'paid',
    stripe_payment_id  TEXT,
    stripe_customer_id TEXT,
    notes              TEXT,
    paid_at            TIMESTAMPTZ DEFAULT NOW(),
    refunded_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT course_purchases_unique UNIQUE (partner_id, course_code, stripe_payment_id)
);

CREATE INDEX IF NOT EXISTS course_purchases_partner_idx ON course_purchases (partner_id, status);

DROP TRIGGER IF EXISTS course_purchases_touch ON course_purchases;
CREATE TRIGGER course_purchases_touch BEFORE UPDATE ON course_purchases
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 10. PARTNER_CLIENT_MAP  (SQLite partner_client_map)
-- =====================================================================
CREATE TABLE IF NOT EXISTS partner_client_map (
    partner_id             TEXT PRIMARY KEY,
    client_id              TEXT,
    session_id             TEXT,
    sponsor_partner_id     TEXT,
    partner_name           TEXT,
    phone                  TEXT,
    email                  TEXT,
    country                TEXT,
    plan_name              TEXT,
    package_amount         NUMERIC(12,2),
    stripe_subscription_id TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS partner_client_map_client_idx ON partner_client_map (client_id);

DROP TRIGGER IF EXISTS partner_client_map_touch ON partner_client_map;
CREATE TRIGGER partner_client_map_touch BEFORE UPDATE ON partner_client_map
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 11. MESSAGES  (SQLite messages)
-- =====================================================================
CREATE TABLE IF NOT EXISTS messages (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id TEXT,
    role       TEXT,
    content    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- get_last_messages() reads the newest N rows for one session — this is the
-- hottest query in the app (every single chat turn).
CREATE INDEX IF NOT EXISTS messages_session_created_idx ON messages (session_id, id DESC);


-- =====================================================================
-- 12. USAGE_LOGS  (SQLite usage_logs)
-- =====================================================================
CREATE TABLE IF NOT EXISTS usage_logs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id      TEXT,
    client_id       TEXT,
    bot_id          TEXT,
    plan_name       TEXT,
    usage_type      TEXT NOT NULL DEFAULT 'bot_reply',
    message_role    TEXT NOT NULL DEFAULT 'bot',
    replies_count   INTEGER NOT NULL DEFAULT 1,
    tokens_estimate INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS usage_logs_session_idx ON usage_logs (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS usage_logs_client_idx  ON usage_logs (client_id, created_at DESC);


-- =====================================================================
-- 13. PAYOUTS  (Sheets: PayoutBatches, PayoutBatchItems, PayoutHistory)
-- =====================================================================
CREATE TABLE IF NOT EXISTS payout_batches (
    batch_id         TEXT PRIMARY KEY,
    partner_id       TEXT,
    partner_name     TEXT,
    commission_count INTEGER NOT NULL DEFAULT 0,
    total_amount     NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency         TEXT NOT NULL DEFAULT 'USD',
    status           TEXT NOT NULL DEFAULT 'pending',
    created_by       TEXT,
    reason           TEXT,
    paid_date        TIMESTAMPTZ,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS payout_batches_partner_idx ON payout_batches (partner_id, status);

CREATE TABLE IF NOT EXISTS payout_batch_items (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id          TEXT REFERENCES payout_batches(batch_id) ON DELETE CASCADE,
    partner_id        TEXT,
    commission_id     TEXT REFERENCES commissions(commission_id) ON DELETE RESTRICT,
    commission_amount NUMERIC(12,2),
    commission_status TEXT,
    item_status       TEXT NOT NULL DEFAULT 'pending',
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A commission can never be paid out through two batches.
    CONSTRAINT payout_batch_items_unique UNIQUE (commission_id)
);

CREATE INDEX IF NOT EXISTS payout_batch_items_batch_idx ON payout_batch_items (batch_id);

CREATE TABLE IF NOT EXISTS payout_history (
    payout_id        TEXT PRIMARY KEY,
    partner_id       TEXT,
    partner_name     TEXT,
    commission_count INTEGER NOT NULL DEFAULT 0,
    commission_ids   TEXT,
    total_amount     NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency         TEXT NOT NULL DEFAULT 'USD',
    payment_method   TEXT,
    status           TEXT NOT NULL DEFAULT 'paid',
    paid_date        TIMESTAMPTZ,
    actor            TEXT,
    reason           TEXT,
    source           TEXT,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS payout_history_partner_idx ON payout_history (partner_id, paid_date DESC);


-- =====================================================================
-- 14. AUDIT_LOGS  (Sheet: AuditLogs)
-- =====================================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id    TEXT PRIMARY KEY,
    actor       TEXT,
    action      TEXT,
    target_type TEXT,
    target_id   TEXT,
    partner_id  TEXT,
    before_json JSONB,
    after_json  JSONB,
    reason      TEXT,
    source      TEXT,
    status      TEXT,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS audit_logs_target_idx  ON audit_logs (target_type, target_id);
CREATE INDEX IF NOT EXISTS audit_logs_partner_idx ON audit_logs (partner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_logs_created_idx ON audit_logs (created_at DESC);


-- =====================================================================
-- 15. WHATSAPP  (Sheets: ClientChannels, WhatsAppMessages, WhatsAppSetupRequests)
-- =====================================================================
CREATE TABLE IF NOT EXISTS client_channels (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id             TEXT,
    partner_id            TEXT,
    channel               TEXT NOT NULL DEFAULT 'whatsapp',
    business_name         TEXT,
    whatsapp_number       TEXT,
    phone_number_id       TEXT,
    waba_id               TEXT,
    setup_type            TEXT,
    connection_status     TEXT NOT NULL DEFAULT 'pending',
    usage_limit           INTEGER,
    usage_count           INTEGER NOT NULL DEFAULT 0,
    human_handoff_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    last_message_at       TIMESTAMPTZ,
    notes                 TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- lookupClientChannelByPhoneNumberId() runs on EVERY inbound WhatsApp message.
CREATE UNIQUE INDEX IF NOT EXISTS client_channels_phone_number_id_uidx
    ON client_channels (phone_number_id)
    WHERE phone_number_id IS NOT NULL AND phone_number_id <> '';
CREATE INDEX IF NOT EXISTS client_channels_client_idx ON client_channels (client_id);

DROP TRIGGER IF EXISTS client_channels_touch ON client_channels;
CREATE TRIGGER client_channels_touch BEFORE UPDATE ON client_channels
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message_id      TEXT,
    direction       TEXT,
    client_id       TEXT,
    partner_id      TEXT,
    phone_number_id TEXT,
    from_number     TEXT,
    to_number       TEXT,
    customer_name   TEXT,
    text            TEXT,
    message_type    TEXT,
    channel         TEXT NOT NULL DEFAULT 'whatsapp',
    status          TEXT,
    raw_json        JSONB,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Meta retries webhooks; this makes inbound message handling idempotent.
CREATE UNIQUE INDEX IF NOT EXISTS whatsapp_messages_message_id_uidx
    ON whatsapp_messages (message_id)
    WHERE message_id IS NOT NULL AND message_id <> '';
CREATE INDEX IF NOT EXISTS whatsapp_messages_client_idx ON whatsapp_messages (client_id, created_at DESC);

CREATE TABLE IF NOT EXISTS whatsapp_setup_requests (
    request_id         TEXT PRIMARY KEY,
    client_id          TEXT,
    partner_id         TEXT,
    business_name      TEXT,
    whatsapp_number    TEXT,
    setup_type         TEXT,
    connection_status  TEXT NOT NULL DEFAULT 'pending',
    preferred_language TEXT,
    human_handoff      BOOLEAN NOT NULL DEFAULT FALSE,
    customer_notes     TEXT,
    admin_notes        TEXT,
    phone_number_id    TEXT,
    waba_id            TEXT,
    provider           TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS whatsapp_setup_requests_status_idx
    ON whatsapp_setup_requests (connection_status, created_at DESC);

DROP TRIGGER IF EXISTS whatsapp_setup_requests_touch ON whatsapp_setup_requests;
CREATE TRIGGER whatsapp_setup_requests_touch BEFORE UPDATE ON whatsapp_setup_requests
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 16. WEBSITE  (Sheets: WebsiteSetupRequests, ClientWebsiteChannels)
-- =====================================================================
CREATE TABLE IF NOT EXISTS website_setup_requests (
    request_id           TEXT PRIMARY KEY,
    client_id            TEXT,
    partner_id           TEXT,
    business_name        TEXT,
    website_domain       TEXT,
    setup_type           TEXT,
    setup_status         TEXT NOT NULL DEFAULT 'pending',
    installation_snippet TEXT,
    customer_notes       TEXT,
    admin_notes          TEXT,
    source               TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS website_setup_requests_status_idx
    ON website_setup_requests (setup_status, created_at DESC);

DROP TRIGGER IF EXISTS website_setup_requests_touch ON website_setup_requests;
CREATE TRIGGER website_setup_requests_touch BEFORE UPDATE ON website_setup_requests
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TABLE IF NOT EXISTS client_website_channels (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id            TEXT,
    partner_id           TEXT,
    channel              TEXT NOT NULL DEFAULT 'website',
    website_domain       TEXT,
    allowed_domain       TEXT,
    widget_client_id     TEXT,
    setup_status         TEXT NOT NULL DEFAULT 'pending',
    installation_snippet TEXT,
    -- ALSAAB_WEBSITE_AUTO_EXTRA_HEADERS_
    last_ping_at         TIMESTAMPTZ,
    last_message_at      TIMESTAMPTZ,
    ping_count           INTEGER NOT NULL DEFAULT 0,
    detected_domain      TEXT,
    last_user_agent      TEXT,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS client_website_channels_widget_uidx
    ON client_website_channels (widget_client_id)
    WHERE widget_client_id IS NOT NULL AND widget_client_id <> '';

DROP TRIGGER IF EXISTS client_website_channels_touch ON client_website_channels;
CREATE TRIGGER client_website_channels_touch BEFORE UPDATE ON client_website_channels
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 17. BOT CONTROL  (Sheets: ClientBotControls, BotControlLogs)
-- =====================================================================
CREATE TABLE IF NOT EXISTS client_bot_controls (
    client_id      TEXT PRIMARY KEY,
    partner_id     TEXT,
    bot_status     TEXT NOT NULL DEFAULT 'on',
    handoff_reason TEXT,
    updated_by     TEXT,
    source         TEXT,
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT client_bot_controls_status_valid CHECK (bot_status IN ('on','off','paused'))
);

DROP TRIGGER IF EXISTS client_bot_controls_touch ON client_bot_controls;
CREATE TRIGGER client_bot_controls_touch BEFORE UPDATE ON client_bot_controls
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TABLE IF NOT EXISTS bot_control_logs (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id  TEXT,
    partner_id TEXT,
    old_status TEXT,
    new_status TEXT,
    reason     TEXT,
    actor      TEXT,
    source     TEXT,
    notes      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS bot_control_logs_client_idx ON bot_control_logs (client_id, created_at DESC);


-- =====================================================================
-- 18. UPGRADES  (Sheets: UpgradeRequests, PlanChangeEvents)
-- =====================================================================
CREATE TABLE IF NOT EXISTS upgrade_requests (
    request_id                    TEXT PRIMARY KEY,
    client_id                     TEXT,
    partner_id                    TEXT,
    current_plan                  TEXT,
    target_plan                   TEXT,
    current_price                 NUMERIC(12,2),
    target_price                  NUMERIC(12,2),
    current_customer_reply_limit  INTEGER,
    target_customer_reply_limit   INTEGER,
    current_advisory_reply_limit  INTEGER,
    target_advisory_reply_limit   INTEGER,
    status                        TEXT NOT NULL DEFAULT 'pending',
    payment_status                TEXT NOT NULL DEFAULT 'pending',
    stripe_checkout_session_id    TEXT,
    stripe_subscription_id        TEXT,
    customer_notes                TEXT,
    admin_notes                   TEXT,
    source                        TEXT,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS upgrade_requests_client_idx ON upgrade_requests (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS upgrade_requests_status_idx ON upgrade_requests (status, created_at DESC);

DROP TRIGGER IF EXISTS upgrade_requests_touch ON upgrade_requests;
CREATE TRIGGER upgrade_requests_touch BEFORE UPDATE ON upgrade_requests
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TABLE IF NOT EXISTS plan_change_events (
    event_id                 TEXT PRIMARY KEY,
    request_id               TEXT,
    client_id                TEXT,
    partner_id               TEXT,
    old_plan                 TEXT,
    new_plan                 TEXT,
    old_customer_reply_limit INTEGER,
    new_customer_reply_limit INTEGER,
    old_advisory_reply_limit INTEGER,
    new_advisory_reply_limit INTEGER,
    actor                    TEXT,
    reason                   TEXT,
    source                   TEXT,
    notes                    TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS plan_change_events_client_idx ON plan_change_events (client_id, created_at DESC);


-- =====================================================================
-- 19. CANCELLATIONS  (Sheet: CancellationRequests)
-- =====================================================================
CREATE TABLE IF NOT EXISTS cancellation_requests (
    request_id             TEXT PRIMARY KEY,
    client_id              TEXT,
    partner_id             TEXT,
    current_plan           TEXT,
    subscription_status    TEXT,
    stripe_customer_id     TEXT,
    stripe_subscription_id TEXT,
    current_period_end     TIMESTAMPTZ,
    cancellation_reason    TEXT,
    customer_notes         TEXT,
    status                 TEXT NOT NULL DEFAULT 'pending',
    admin_decision         TEXT,
    admin_notes            TEXT,
    cancel_at_period_end   BOOLEAN NOT NULL DEFAULT FALSE,
    source                 TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS cancellation_requests_client_idx ON cancellation_requests (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS cancellation_requests_status_idx ON cancellation_requests (status, created_at DESC);

DROP TRIGGER IF EXISTS cancellation_requests_touch ON cancellation_requests;
CREATE TRIGGER cancellation_requests_touch BEFORE UPDATE ON cancellation_requests
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 20. SMART LINK EVENTS  (Sheet: SmartLinkEvents)
-- =====================================================================
CREATE TABLE IF NOT EXISTS smart_link_events (
    event_id     TEXT PRIMARY KEY,
    smart_ref    TEXT,
    client_id    TEXT,
    partner_id   TEXT,
    event_type   TEXT,
    source       TEXT,
    session_id   TEXT,
    page_url     TEXT,
    referrer_url TEXT,
    message      TEXT,
    user_agent   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- The analytics summary groups by partner + type + day.
CREATE INDEX IF NOT EXISTS smart_link_events_partner_idx ON smart_link_events (partner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS smart_link_events_ref_idx     ON smart_link_events (smart_ref);
CREATE INDEX IF NOT EXISTS smart_link_events_type_idx    ON smart_link_events (event_type, created_at DESC);


-- =====================================================================
-- 21. CLIENT DASHBOARD CONTENT
--     (Sheets: ProductImageGroups, ClientPaymentLinks)
-- =====================================================================
CREATE TABLE IF NOT EXISTS product_image_groups (
    group_id            TEXT PRIMARY KEY,
    partner_id          TEXT,
    client_id           TEXT,
    group_title         TEXT,
    group_description   TEXT,
    sales_instructions  TEXT,
    product_notes       TEXT,
    pricing_notes       TEXT,
    payment_links_notes TEXT,
    image_urls          JSONB NOT NULL DEFAULT '[]'::JSONB,
    status              TEXT NOT NULL DEFAULT 'active',
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS product_image_groups_partner_idx ON product_image_groups (partner_id, status);

DROP TRIGGER IF EXISTS product_image_groups_touch ON product_image_groups;
CREATE TRIGGER product_image_groups_touch BEFORE UPDATE ON product_image_groups
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TABLE IF NOT EXISTS client_payment_links (
    payment_link_id       TEXT PRIMARY KEY,
    partner_id            TEXT,
    client_id             TEXT,
    product_name          TEXT,
    payment_link          TEXT,
    amount                NUMERIC(12,2),
    currency              TEXT NOT NULL DEFAULT 'AED',
    description           TEXT,
    linked_image_group_id TEXT REFERENCES product_image_groups(group_id) ON DELETE SET NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    notes                 TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS client_payment_links_partner_idx ON client_payment_links (partner_id, status);

DROP TRIGGER IF EXISTS client_payment_links_touch ON client_payment_links;
CREATE TRIGGER client_payment_links_touch BEFORE UPDATE ON client_payment_links
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- =====================================================================
-- 22. VIEWS — replace the hand-maintained tree walks
-- =====================================================================

-- Everyone BELOW a partner, to depth 5. Replaces createPartnerTreeRelations()
-- + findTreeRowsByDescendant() + the whole PartnerTree maintenance loop.
CREATE OR REPLACE VIEW partner_downline AS
WITH RECURSIVE walk AS (
    SELECT partner_id AS root_partner_id,
           partner_id AS descendant_partner_id,
           0          AS depth
    FROM partners
    UNION ALL
    SELECT w.root_partner_id,
           p.partner_id,
           w.depth + 1
    FROM partners p
    JOIN walk w ON p.sponsor_partner_id = w.descendant_partner_id
    WHERE w.depth < 5
)
SELECT root_partner_id, descendant_partner_id, depth
FROM walk
WHERE depth > 0;

-- Everyone ABOVE a partner, to depth 5. This is the exact list
-- getEligibleCommissionBeneficiaries() needs when an invoice is paid.
CREATE OR REPLACE VIEW partner_upline AS
WITH RECURSIVE walk AS (
    SELECT partner_id AS root_partner_id,
           partner_id AS ancestor_partner_id,
           sponsor_partner_id,
           0          AS depth
    FROM partners
    UNION ALL
    SELECT w.root_partner_id,
           p.partner_id,
           p.sponsor_partner_id,
           w.depth + 1
    FROM partners p
    JOIN walk w ON p.partner_id = w.sponsor_partner_id
    WHERE w.depth < 5
)
SELECT root_partner_id, ancestor_partner_id, depth
FROM walk
WHERE depth > 0;

-- A subscription still counts while Stripe is retrying the charge.
CREATE OR REPLACE VIEW subscriptions_counting_as_active AS
SELECT *
FROM subscriptions
WHERE subscription_status IN ('active','paid','trialing')
   OR (
        subscription_status = 'payment_failed'
        AND payment_grace_until IS NOT NULL
        AND payment_grace_until > NOW()
      );

-- Live direct-customer count. Replaces countActiveDirectCustomers(), which
-- scanned the whole Subscriptions sheet on every call.
CREATE OR REPLACE VIEW partner_active_direct_customers AS
SELECT source_partner_id AS partner_id,
       COUNT(*)          AS active_direct_customers
FROM subscriptions_counting_as_active
WHERE source_partner_id IS NOT NULL
  AND source_partner_id <> ''
GROUP BY source_partner_id;

-- Whole-network paying customers, to depth 5.
--
-- Level requirements are measured against the ENTIRE network, not just the
-- people directly under you: anyone paying anywhere beneath you counts, plus
-- your own direct customers.
--
-- A plain customer is not a partner, so they never appear in partner_downline;
-- they are reached through the source_partner_id on their subscription. That
-- is why this joins on "the subscription was sold by me OR by anyone below
-- me" rather than walking partners alone.
CREATE OR REPLACE VIEW partner_active_network_customers AS
SELECT seller.partner_id,
       COUNT(DISTINCT s.id) AS active_network_customers
FROM (
        SELECT partner_id, partner_id AS seller_partner_id FROM partners
        UNION ALL
        SELECT root_partner_id, descendant_partner_id FROM partner_downline
     ) AS seller(partner_id, seller_partner_id)
JOIN subscriptions_counting_as_active s
  ON s.source_partner_id = seller.seller_partner_id
GROUP BY seller.partner_id;

-- One row per partner for the admin dashboard totals.
CREATE OR REPLACE VIEW partner_commission_totals AS
SELECT beneficiary_partner_id AS partner_id,
       COUNT(*)                                                       AS commission_count,
       COALESCE(SUM(commission_amount)                       , 0)     AS total_all,
       COALESCE(SUM(commission_amount) FILTER (WHERE status = 'pending' ), 0) AS total_pending,
       COALESCE(SUM(commission_amount) FILTER (WHERE status = 'approved'), 0) AS total_approved,
       COALESCE(SUM(commission_amount) FILTER (WHERE status = 'paid'    ), 0) AS total_paid
FROM commissions
GROUP BY beneficiary_partner_id;


-- =====================================================================
-- 23. SEED DATA — must come after all DDL, see the note in section 1
-- =====================================================================

-- The company root. COMPANY_OWNER_PARTNER_ID = 'alsaab' in config.py and in
-- the Apps Script; every orphan downline is re-parented to it, so it must
-- exist before any partner rows are imported.
INSERT INTO partners (partner_id, partner_name, partner_rank, status, notes)
VALUES ('alsaab', 'ALSAAB AI', 'Level 5', 'active', 'Company owner root. Receives no commission.')
ON CONFLICT (partner_id) DO NOTHING;

COMMIT;

-- =====================================================================
-- POST-MIGRATION: align the partner id sequence with imported data so the
-- next generated id continues after the highest existing ALS-Pxxxxx.
-- Run this ONCE, after importing the Partners sheet.
-- =====================================================================
-- SELECT setval('partner_id_seq', COALESCE((
--     SELECT MAX((regexp_match(partner_id, '^ALS-P(\d+)$'))[1]::INT)
--     FROM partners WHERE partner_id ~ '^ALS-P\d+$'
-- ), 0) + 1, false);
