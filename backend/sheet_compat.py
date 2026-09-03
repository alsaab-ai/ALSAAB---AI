# sheet_compat.py
#
# ALSAAB AI — PostgreSQL replacement for the Google Apps Script backend.
#
# Every Google Sheets call in this codebase funnels through two functions in
# database.py:
#     post_to_google_sheet(payload, label)
#     post_to_google_sheet_json(payload, label)
#
# There are 57 call sites across 11 files, but they all pass the same shape:
# a dict with an "action" key. This module answers those same actions from
# PostgreSQL and returns the same JSON shape, so NONE of the 57 call sites
# and NONE of the 40+ Flask routes have to change.
#
# ---------------------------------------------------------------------
# Incremental migration, not a big bang
# ---------------------------------------------------------------------
# Actions listed in HANDLERS are answered from PostgreSQL.
# Any action NOT yet ported falls through to the real Google Apps Script,
# exactly as before. So the system keeps working at every step, and we move
# actions over one at a time.
#
# Controlled by DATA_BACKEND:
#     sheets   -> everything goes to Google Sheets (current behaviour)
#     dual     -> ported actions write to BOTH, read from PostgreSQL
#     postgres -> ported actions use PostgreSQL only; rest still fall back
#
# ---------------------------------------------------------------------
# Ported from the Apps Script. Note that the script defines doPost 19 times
# and several core functions 2-3 times; JavaScript keeps only the LAST
# definition, so the earlier ones were dead code. What is ported here is the
# LIVE version in each case:
#     saveSubscription                   line 3248  (not 748)
#     saveCommissionRecord               line 3364  (not 921)
#     generateCommissionsForSubscription line 3523  (not 2048)
#     saveMLMLevel                       line 3145  (not 1033)
#     getPackageAmount                   line 3230  (not 1572)
#     isPartnerQualifiedForCommission    line 3123  (not 1948)

import json
import os
import re
import uuid
from datetime import datetime

# Importing db first loads the local .env, so DATA_BACKEND below sees it.
try:
    import db as _db_module
except ImportError:
    from backend import db as _db_module

DATA_BACKEND = os.getenv("DATA_BACKEND", "sheets").lower().strip()

COMPANY_OWNER_PARTNER_ID = os.getenv("COMPANY_OWNER_PARTNER_ID", "alsaab")
# The referral link has to land on the sales chat, which is where the smart
# link script reads ?ref and attributes the visit. The old default pointed at
# the WordPress marketing site, which has no such script, so every partner
# created after the first two got a link that dropped the referral on the
# floor -- the visitor arrived at a homepage and nobody was credited.
def _default_referral_base():
    """
    Derive the referral base from the app's own address.

    Keeping it as an independent setting is what let it drift to the marketing
    site, which never reads ?ref -- so 18 partners were handed links that
    credited nobody. Tying it to APP_BASE_URL means the two cannot disagree
    again: wherever the app answers, that is where a referral lands.
    REFERRAL_BASE_URL still overrides, for the case where the chat is served
    from somewhere else.
    """
    override = (os.getenv("REFERRAL_BASE_URL") or "").strip()

    if override:
        return override

    try:
        from config import APP_BASE_URL
    except ImportError:
        try:
            from backend.config import APP_BASE_URL
        except ImportError:
            APP_BASE_URL = ""

    base = (APP_BASE_URL or "https://alsaab-ai.onrender.com").rstrip("/")

    return f"{base}/?ref="


REFERRAL_BASE_URL = _default_referral_base()

ACTIVE_SUBSCRIPTION_STATUSES = ("active", "paid", "trialing")
ACTIVE_PARTNER_STATUSES = ("active", "approved", "نشط")

# MLM_COMMISSION_RULES, Apps Script line 16.
COMMISSION_RULES = {
    1: {"percent": 25, "required_rank_number": 1, "label": "Level 1 Direct Commission"},
    2: {"percent": 5,  "required_rank_number": 2, "label": "Level 2 Upline Commission"},
    3: {"percent": 4,  "required_rank_number": 3, "label": "Level 3 Upline Commission"},
    4: {"percent": 3,  "required_rank_number": 4, "label": "Level 4 Upline Commission"},
    5: {"percent": 2,  "required_rank_number": 5, "label": "Level 5 Upline Commission"},
}

MAX_COMMISSION_DEPTH = 5


# =====================================================================
# Small helpers
# =====================================================================

def _conn():
    from db import get_connection
    return get_connection()


def _text(value):
    return str(value if value is not None else "").strip()


def _lower(value):
    return _text(value).lower()


def _now():
    return datetime.utcnow()


def _ok(**fields):
    result = {"status": "success"}
    result.update(fields)
    return result


def _skip(reason, **fields):
    result = {"status": "skipped", "reason": reason}
    result.update(fields)
    return result


def _err(message, **fields):
    result = {"status": "error", "message": message}
    result.update(fields)
    return result


_EXACT_PARTNER_RE = re.compile(r"^ALS-P\d+$", re.IGNORECASE)
_EMBEDDED_PARTNER_RE = re.compile(r"\bALS-P\d+\b", re.IGNORECASE)


def normalize_partner_id(value):
    """
    Exact port of normalizePartnerId() (Apps Script line 366).

    Deliberately does NOT zero-pad. The Apps Script leaves "ALS-P2" as
    "ALS-P2", so padding it to "ALS-P00002" here would turn every short id
    already stored in the sheets into a different partner after migration —
    silently detaching their downline and commissions.

    Also note that unrecognised input returns "" (not the input), which is
    what the commission gate relies on to reject junk sponsor ids.
    """
    raw = _text(value)

    if not raw:
        return ""

    if raw.lower() == COMPANY_OWNER_PARTNER_ID.lower():
        return COMPANY_OWNER_PARTNER_ID

    exact = _EXACT_PARTNER_RE.match(raw)
    if exact:
        return exact.group(0).upper()

    embedded = _EMBEDDED_PARTNER_RE.search(raw)
    if embedded:
        return embedded.group(0).upper()

    return ""


# Exact alias table from normalizePartnerRank() (Apps Script line 1716).
_RANK_ALIASES = {
    1: ("level 1", "1", "starter partner", "starter", "المستوى الأول"),
    2: ("level 2", "2", "growth partner", "growth", "المستوى الثاني"),
    3: ("level 3", "3", "sales partner", "sales", "المستوى الثالث"),
    4: ("level 4", "4", "leader partner", "leader", "المستوى الرابع"),
    5: ("level 5", "5", "elite partner", "elite", "المستوى الخامس"),
}


def normalize_partner_rank(value):
    """
    Exact port of normalizePartnerRank() (line 1716).

    Matches on the WHOLE string against a fixed alias list — it does not go
    looking for a digit anywhere in the text. Anything unrecognised is
    returned unchanged, which is load-bearing: the live MLMLevels sheet is
    full of "Direct Partner", a rank that is in no alias list, so it stays
    "Direct Partner" and getRankNumber() yields 0. Those partners are
    therefore not eligible for commission at any depth, and the sheet agrees
    (Level Status = inactive, Commission Eligible = no).

    An earlier version of this function searched for any digit 1-5 and mapped
    everything else to "Level 1". That would have promoted every "Direct
    Partner" to a commission-earning rank.
    """
    normalized = _lower(value)

    for level, aliases in _RANK_ALIASES.items():
        if normalized in aliases:
            return f"Level {level}"

    return value or "Level 1"


def rank_number(value):
    """Exact port of getRankNumber() (line 1773). Unknown rank -> 0."""
    match = re.search(r"Level\s*(\d+)", _text(normalize_partner_rank(value)), flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def parse_money(value):
    """Mirrors parseMoney() (line 1618) — strips currency symbols and commas."""
    text = _text(value)

    if not text:
        return 0.0

    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))

    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _normalize_key_part(value):
    """Mirrors normalizeKeyPart() (line 1680)."""
    return re.sub(r"\s+", "_", _lower(value))


def _period_month_key(value):
    """Mirrors getCommissionPeriodMonthKey() (line 1655)."""
    text = _text(value)

    if not text:
        return _now().strftime("%Y-%m")

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:len(fmt) + 4], fmt).strftime("%Y-%m")
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m")
    except ValueError:
        return _now().strftime("%Y-%m")


def build_commission_unique_key(data):
    """
    Identifies one commission slot: this subscription, this billing month, this
    depth.

    Ported from buildCommissionUniqueKey() (line 1689) with one deliberate
    change -- the beneficiary is NOT part of the key.

    The Apps Script version included it, which meant the same subscription
    month could be paid twice at the same depth as long as a different partner
    collected it. That is reachable: commissions are regenerated whenever a
    subscription row is saved, and if the partner who earned the slot has since
    become ineligible, compression rolls it up and the upline gets a second
    payout for a month that was already settled. Observed live -- July 2026 on
    sub_1TtQbe... paid depth 1 to ALS-P00007, and a later save created a second
    depth-1 commission for the same month to ALS-P00003.

    Dropping the beneficiary makes the slot itself unique, so a month can only
    ever be paid once no matter who ends up entitled to it. Existing rows were
    backfilled to this format, so the unique index covers old and new alike.
    """
    stripe_subscription_id = _normalize_key_part(data.get("stripe_subscription_id", ""))
    payer_client_id = _normalize_key_part(data.get("payer_client_id") or data.get("client_id") or "")
    source_partner_id = _normalize_key_part(normalize_partner_id(data.get("source_partner_id", "")))
    beneficiary_partner_id = _normalize_key_part(
        normalize_partner_id(data.get("beneficiary_partner_id") or data.get("partner_id") or "")
    )
    commission_depth = _normalize_key_part(data.get("commission_depth") or data.get("depth") or "")
    package_name = _normalize_key_part(
        data.get("package_name") or data.get("package") or data.get("plan_name") or ""
    )
    period_month = _period_month_key(data.get("period_start") or data.get("period_end") or "")

    # beneficiary_partner_id is deliberately absent -- see the docstring.
    del beneficiary_partner_id

    return "::".join([
        "commission",
        stripe_subscription_id or payer_client_id or "unknown_payer",
        source_partner_id or "unknown_source",
        "depth_" + (commission_depth or "unknown_depth"),
        package_name or "unknown_package",
        period_month,
    ])


def _is_company_owner(partner_id):
    return _lower(partner_id) == _lower(COMPANY_OWNER_PARTNER_ID)


# =====================================================================
# Handlers — writes
# =====================================================================

def _save_lead(payload):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO leads (
                session_id, client_id, source_partner_id, name, phone,
                user_type, business_name, business_type, pain_point,
                channel, status, email, country
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _text(payload.get("session_id")),
                _text(payload.get("client_id")),
                normalize_partner_id(payload.get("source_partner_id") or payload.get("ref")),
                _text(payload.get("name")),
                _text(payload.get("phone")),
                _text(payload.get("user_type")),
                _text(payload.get("business_name")),
                _text(payload.get("business_type")),
                _text(payload.get("pain_point")),
                _text(payload.get("channel")) or "website",
                _text(payload.get("status")) or "new",
                _text(payload.get("email")),
                _text(payload.get("country")),
            ),
        )
        lead_id = cur.lastrowid

    return _ok(message="Lead saved", lead_id=lead_id)


def _save_client_profile(payload):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO client_profiles (
                session_id, client_id, business_name, business_type,
                general_description, products, prices, offers, ordering,
                whatsapp, areas, faqs, objections, tone
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                client_id           = COALESCE(NULLIF(EXCLUDED.client_id, ''), client_profiles.client_id),
                business_name       = COALESCE(NULLIF(EXCLUDED.business_name, ''), client_profiles.business_name),
                business_type       = COALESCE(NULLIF(EXCLUDED.business_type, ''), client_profiles.business_type),
                general_description = COALESCE(NULLIF(EXCLUDED.general_description, ''), client_profiles.general_description),
                products            = COALESCE(NULLIF(EXCLUDED.products, ''), client_profiles.products),
                prices              = COALESCE(NULLIF(EXCLUDED.prices, ''), client_profiles.prices),
                offers              = COALESCE(NULLIF(EXCLUDED.offers, ''), client_profiles.offers),
                ordering            = COALESCE(NULLIF(EXCLUDED.ordering, ''), client_profiles.ordering),
                whatsapp            = COALESCE(NULLIF(EXCLUDED.whatsapp, ''), client_profiles.whatsapp),
                areas               = COALESCE(NULLIF(EXCLUDED.areas, ''), client_profiles.areas),
                faqs                = COALESCE(NULLIF(EXCLUDED.faqs, ''), client_profiles.faqs),
                objections          = COALESCE(NULLIF(EXCLUDED.objections, ''), client_profiles.objections),
                tone                = COALESCE(NULLIF(EXCLUDED.tone, ''), client_profiles.tone)
            """,
            (
                _text(payload.get("session_id")),
                _text(payload.get("client_id")),
                _text(payload.get("business_name")),
                _text(payload.get("business_type")),
                _text(payload.get("general_description")),
                _text(payload.get("products")),
                _text(payload.get("prices")),
                _text(payload.get("offers")),
                _text(payload.get("ordering")),
                _text(payload.get("whatsapp")),
                _text(payload.get("areas")),
                _text(payload.get("faqs")),
                _text(payload.get("objections")),
                _text(payload.get("tone")),
            ),
        )

    return _ok(message="Client profile saved")


def _find_existing_partner(cur, phone, email, client_id):
    """Mirrors findExistingPartner() (line 1157) — phone, then email, then client_id."""
    for column, value in (("phone", phone), ("email", email), ("client_id", client_id)):
        if not value:
            continue

        cur.execute(
            f"SELECT partner_id, referral_link FROM partners WHERE {column} = ? LIMIT 1",
            (value,),
        )
        row = cur.fetchone()

        if row:
            return {"partner_id": row[0], "referral_link": row[1]}

    return None


def _save_partner(payload):
    """
    Port of savePartner() (line 562).

    Two behaviours are strengthened rather than copied:
      - generatePartnerId() scanned the sheet for MAX(id), which produced
        duplicate ids under concurrent signups. Here a Postgres sequence
        (next_partner_id()) makes it atomic.
      - The whole insert now runs in one transaction with the tree and level
        rows, so a partial partner can no longer exist.
    """
    client_id = _text(payload.get("client_id"))
    partner_name = _text(payload.get("partner_name") or payload.get("name"))
    phone = _text(payload.get("phone") or payload.get("whatsapp"))
    email = _text(payload.get("email"))
    partner_rank = normalize_partner_rank(
        payload.get("partner_rank") or payload.get("level") or payload.get("rank")
    )

    sponsor_partner_id = normalize_partner_id(
        payload.get("sponsor_partner_id")
        or payload.get("sponsor_id")
        or payload.get("invited_by")
        or ""
    )

    if not sponsor_partner_id:
        return _err(
            "Valid sponsor_partner_id is required. "
            "Use alsaab or an existing Partner ID like ALS-P00001."
        )

    with _conn() as conn:
        cur = conn.cursor()

        existing = _find_existing_partner(cur, phone, email, client_id)
        if existing:
            return _ok(
                message="Partner already exists",
                partner_id=existing["partner_id"],
                referral_link=existing["referral_link"],
            )

        cur.execute("SELECT 1 FROM partners WHERE partner_id = ?", (sponsor_partner_id,))
        if not cur.fetchone():
            return _err(
                "Sponsor Partner ID does not exist in Partners sheet",
                sponsor_partner_id=sponsor_partner_id,
            )

        requested_partner_id = normalize_partner_id(payload.get("partner_id"))

        if requested_partner_id:
            partner_id = requested_partner_id
        else:
            cur.execute("SELECT next_partner_id()")
            partner_id = cur.fetchone()[0]

        referral_link = _text(payload.get("referral_link")) or (REFERRAL_BASE_URL + partner_id)

        cur.execute(
            """
            INSERT INTO partners (
                partner_id, client_id, sponsor_partner_id, parent_partner_id,
                partner_name, phone, email, country, partner_rank, status,
                referral_link, invited_by, active_direct_customers,
                active_network_customers, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                partner_id,
                client_id,
                sponsor_partner_id,
                sponsor_partner_id,
                partner_name,
                phone,
                email,
                _text(payload.get("country")),
                partner_rank,
                _text(payload.get("status")) or "active",
                referral_link,
                sponsor_partner_id,
                int(parse_money(payload.get("active_direct_customers")) or 0),
                int(parse_money(payload.get("active_network_customers")) or 0),
                _text(payload.get("notes")),
            ),
        )

        _write_tree_relations(cur, partner_id, sponsor_partner_id)

        cur.execute(
            """
            INSERT INTO partner_levels (
                partner_id, partner_rank, current_level, required_sales,
                completed_sales, required_course_workshop, level_status, next_rank
            ) VALUES (?, ?, ?, 1, 0, ?, 'active', ?)
            ON CONFLICT (partner_id) DO NOTHING
            """,
            (
                partner_id,
                partner_rank,
                rank_number(partner_rank),
                "الاشتراك بأي باقة",
                "Level " + str(min(rank_number(partner_rank) + 1, MAX_COMMISSION_DEPTH)),
            ),
        )

    return _ok(
        message="Partner saved",
        partner_id=partner_id,
        referral_link=referral_link,
        sponsor_partner_id=sponsor_partner_id,
        parent_partner_id=sponsor_partner_id,
        invited_by=sponsor_partner_id,
    )


def _write_tree_relations(cur, partner_id, sponsor_partner_id):
    """
    Port of createPartnerTreeRelations() (line 1342).

    The partner_tree table is now redundant — partner_upline / partner_downline
    views derive the same thing from partners.sponsor_partner_id — but it is
    still written so the existing dashboards keep reading what they expect.
    """
    ancestor = sponsor_partner_id
    depth = 1

    while ancestor and depth <= MAX_COMMISSION_DEPTH:
        cur.execute(
            """
            INSERT INTO partner_tree (
                ancestor_partner_id, descendant_partner_id, depth, line_owner_partner_id
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT (ancestor_partner_id, descendant_partner_id, depth) DO NOTHING
            """,
            (ancestor, partner_id, depth, sponsor_partner_id),
        )

        cur.execute("SELECT sponsor_partner_id FROM partners WHERE partner_id = ?", (ancestor,))
        row = cur.fetchone()
        next_ancestor = normalize_partner_id(row[0]) if row and row[0] else ""

        if not next_ancestor or next_ancestor == ancestor:
            break

        ancestor = next_ancestor
        depth += 1


def _save_partner_tree(payload):
    ancestor = normalize_partner_id(payload.get("ancestor_partner_id") or payload.get("ancestor"))
    descendant = normalize_partner_id(payload.get("descendant_partner_id") or payload.get("descendant"))

    if not ancestor or not descendant:
        return _err("ancestor_partner_id and descendant_partner_id are required")

    try:
        depth = int(parse_money(payload.get("depth")) or 0)
    except (TypeError, ValueError):
        depth = 0

    if depth < 1 or depth > MAX_COMMISSION_DEPTH:
        return _skip("invalid_depth", depth=payload.get("depth"))

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO partner_tree (
                ancestor_partner_id, descendant_partner_id, depth,
                line_owner_partner_id, notes
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (ancestor_partner_id, descendant_partner_id, depth) DO NOTHING
            """,
            (
                ancestor,
                descendant,
                depth,
                normalize_partner_id(payload.get("line_owner_partner_id") or payload.get("line_owner")),
                _text(payload.get("notes")),
            ),
        )

    return _ok(message="Partner tree relation saved", depth=depth)


def _save_referral(payload):
    source_partner_id = normalize_partner_id(
        payload.get("source_partner_id") or payload.get("partner_id") or payload.get("ref")
    )

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO referrals (
                source_partner_id, referral_name, referral_phone, referral_email,
                source, package, payment_status, subscription_status,
                session_id, client_id, stripe_subscription_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_partner_id,
                _text(payload.get("referral_name") or payload.get("name")),
                _text(payload.get("referral_phone") or payload.get("phone")),
                _text(payload.get("referral_email") or payload.get("email")),
                _text(payload.get("source")) or "website",
                _text(payload.get("package") or payload.get("plan_name")),
                _text(payload.get("payment_status")) or "pending",
                _text(payload.get("subscription_status")) or "pending",
                _text(payload.get("session_id")),
                _text(payload.get("client_id")),
                _text(payload.get("stripe_subscription_id")),
                _text(payload.get("notes")),
            ),
        )

    return _ok(message="Referral saved", source_partner_id=source_partner_id)


def _save_subscription(payload):
    """
    Port of saveSubscription() (line 3248 — the live one, not 748).

    After upserting the subscription it triggers commission generation, same
    as the Apps Script did.
    """
    client_id = _text(payload.get("client_id"))
    session_id = _text(payload.get("session_id"))
    source_partner_id = normalize_partner_id(
        payload.get("source_partner_id") or payload.get("partner_id") or payload.get("ref")
    )
    stripe_subscription_id = _text(payload.get("stripe_subscription_id"))
    subscription_status = _lower(payload.get("subscription_status") or payload.get("status")) or "active"
    plan_name = _text(payload.get("plan_name") or payload.get("package"))
    package_amount = parse_money(payload.get("package_amount"))

    with _conn() as conn:
        cur = conn.cursor()

        # findExistingSubscription(): stripe subscription id first, then session.
        existing_id = None

        if stripe_subscription_id:
            cur.execute(
                "SELECT id FROM subscriptions WHERE stripe_subscription_id = ? LIMIT 1",
                (stripe_subscription_id,),
            )
            row = cur.fetchone()
            existing_id = row[0] if row else None

        if existing_id is None and session_id:
            cur.execute("SELECT id FROM subscriptions WHERE session_id = ? LIMIT 1", (session_id,))
            row = cur.fetchone()
            existing_id = row[0] if row else None

        if existing_id is None:
            cur.execute(
                """
                INSERT INTO subscriptions (
                    session_id, client_id, source_partner_id, plan_name,
                    package_amount, subscription_status, stripe_customer_id,
                    stripe_subscription_id, current_period_start,
                    current_period_end, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id or None,
                    client_id,
                    source_partner_id,
                    plan_name,
                    package_amount or None,
                    subscription_status,
                    _text(payload.get("stripe_customer_id")),
                    stripe_subscription_id,
                    _text(payload.get("current_period_start")) or None,
                    _text(payload.get("current_period_end")) or None,
                    _text(payload.get("notes")),
                ),
            )
        else:
            cur.execute(
                """
                UPDATE subscriptions SET
                    client_id            = COALESCE(NULLIF(?, ''), client_id),
                    source_partner_id    = COALESCE(NULLIF(?, ''), source_partner_id),
                    plan_name            = COALESCE(NULLIF(?, ''), plan_name),
                    package_amount       = COALESCE(?, package_amount),
                    subscription_status  = ?,
                    stripe_customer_id   = COALESCE(NULLIF(?, ''), stripe_customer_id),
                    current_period_start = COALESCE(?, current_period_start),
                    current_period_end   = COALESCE(?, current_period_end)
                WHERE id = ?
                """,
                (
                    client_id,
                    source_partner_id,
                    plan_name,
                    package_amount or None,
                    subscription_status,
                    _text(payload.get("stripe_customer_id")),
                    _text(payload.get("current_period_start")) or None,
                    _text(payload.get("current_period_end")) or None,
                    existing_id,
                ),
            )

    commissions = _generate_commissions_for_subscription(payload, source_partner_id)

    return _ok(
        message="Subscription saved",
        client_id=client_id,
        source_partner_id=source_partner_id,
        commissions=commissions,
    )


# =====================================================================
# Commission engine
# =====================================================================

def _calculate_partner_level_progress(cur, partner_id):
    """
    Port of calculatePartnerLevelProgress() (line 2884).

    Where the Apps Script scanned entire sheets, this reads the
    partner_active_direct_customers view and two indexed lookups.
    """
    cur.execute(
        "SELECT partner_rank, status FROM partners WHERE partner_id = ? LIMIT 1",
        (partner_id,),
    )
    row = cur.fetchone()

    if not row:
        return {
            "partner_rank": "",
            "current_level": 0,
            "subscription_status": "",
            "commission_eligible": False,
            "active_direct_customers": 0,
            "missing_requirements": ["partner_not_found"],
        }

    partner_rank, partner_status = normalize_partner_rank(row[0]), _lower(row[1])

    # The partner's OWN subscription — the one that decides which level their
    # package qualifies them for.
    #
    # A partner is joined to their subscription through partners.client_id, not
    # through partner_id: the subscription row was created when they paid as a
    # customer, so its client_id is something like
    # "smart_ALS-P00008_1784463363710_80d", never "ALS-P00010".
    #
    # The previous query matched on `client_id = partner_id OR
    # source_partner_id = partner_id` and got both directions wrong:
    #   - the first branch never matched, so partners with a real paid
    #     subscription looked like they had none and were denied their level;
    #   - the second branch matched a subscription they had REFERRED, so a
    #     partner with no package of their own inherited a customer's package
    #     and qualified on someone else's payment.
    cur.execute(
        """
        SELECT s.plan_name, s.subscription_status, s.id
        FROM partners p
        JOIN subscriptions s
          ON s.client_id = p.client_id
          OR s.session_id = p.client_id
        WHERE p.partner_id = ?
        ORDER BY s.updated_at DESC
        LIMIT 1
        """,
        (partner_id,),
    )
    sub = cur.fetchone()
    current_package = _text(sub[0]) if sub else ""
    subscription_status = _lower(sub[1]) if sub else ""

    # Honour the payment grace period on the partner's OWN subscription.
    #
    # A customer whose payment failed keeps counting towards their referrer for
    # the length of the grace period, because the count comes from the
    # partner_active_direct_customers view, which is built on
    # subscriptions_counting_as_active. The partner's own subscription was read
    # straight off `subscriptions`, so the same failed payment dropped THEM to
    # level 0 immediately -- grace for their customers, none for themselves.
    # ALS-P00006 and ALS-P00007 were both sitting in that contradiction.
    #
    # The raw status is kept for display; only the value handed to the level
    # engine is normalised, and only while the grace window is genuinely open
    # (the view checks payment_grace_until > now()).
    if sub and subscription_status not in ACTIVE_SUBSCRIPTION_STATUSES:
        cur.execute(
            "SELECT 1 FROM subscriptions_counting_as_active WHERE id = ?",
            (sub[2],),
        )

        if cur.fetchone():
            subscription_status = "active"

    cur.execute(
        "SELECT COALESCE(active_direct_customers, 0) "
        "FROM partner_active_direct_customers WHERE partner_id = ?",
        (partner_id,),
    )
    row = cur.fetchone()
    active_direct = int(row[0]) if row else 0

    # Level requirements are measured against the WHOLE network, not just the
    # people directly underneath — a paying customer five levels down counts
    # toward the threshold exactly like a direct one.
    cur.execute(
        "SELECT COALESCE(active_network_customers, 0) "
        "FROM partner_active_network_customers WHERE partner_id = ?",
        (partner_id,),
    )
    row = cur.fetchone()
    active_network = int(row[0]) if row else 0

    cur.execute(
        "SELECT course_code FROM course_purchases WHERE partner_id = ? AND status = 'paid'",
        (partner_id,),
    )
    purchased_courses = [r[0] for r in cur.fetchall()]

    subscription_active = subscription_status in ACTIVE_SUBSCRIPTION_STATUSES
    partner_active = partner_status in ACTIVE_PARTNER_STATUSES

    # Highest level whose requirements are all met.
    #
    # The rules come from level_engine.LEVEL_REQUIREMENTS, which is the single
    # source of truth. There used to be two: this gate read the
    # level_requirements table while the dashboards read level_engine, and the
    # two disagreed — a partner could be shown as eligible while the payout
    # gate refused them, or the reverse.
    try:
        from level_engine import LEVEL_REQUIREMENTS
    except ImportError:
        from backend.level_engine import LEVEL_REQUIREMENTS

    rules = [
        (
            number,
            list(rule.allowed_packages),
            rule.min_active_direct_customers,
            list(rule.required_courses),
        )
        for number, rule in sorted(LEVEL_REQUIREMENTS.items())
    ]

    current_level = 0
    missing = []

    for level_number, allowed_packages, min_direct, required_courses in rules:
        if not subscription_active:
            missing.append("subscription_not_active")
            break

        if current_package and current_package.lower() not in [p.lower() for p in (allowed_packages or [])]:
            missing.append(f"level_{level_number}_requires_package_in_{list(allowed_packages or [])}")
            break

        if active_network < int(min_direct or 0):
            missing.append(f"level_{level_number}_requires_{min_direct}_active_network_customers")
            break

        if any(course not in purchased_courses for course in (required_courses or [])):
            missing.append(f"level_{level_number}_requires_courses_{list(required_courses or [])}")
            break

        current_level = level_number

    commission_eligible = bool(current_level >= 1 and subscription_active and partner_active)

    return {
        "partner_rank": partner_rank,
        "current_level": current_level,
        "current_package": current_package,
        "subscription_status": subscription_status,
        "subscription_active": subscription_active,
        "commission_eligible": commission_eligible,
        "active_direct_customers": active_direct,
        "active_network_customers": active_network,
        "purchased_courses": purchased_courses,
        "missing_requirements": missing,
    }


def _sync_partner_level(cur, partner_id, progress):
    """Port of syncPartnerLevel() (line 2999) — persists the computed progress."""
    cur.execute(
        """
        INSERT INTO partner_levels (
            partner_id, partner_rank, current_level, current_package,
            subscription_status, subscription_active, commission_eligible,
            active_direct_customers, purchased_courses, missing_requirements,
            next_rank, level_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        ON CONFLICT (partner_id) DO UPDATE SET
            partner_rank            = EXCLUDED.partner_rank,
            current_level           = EXCLUDED.current_level,
            current_package         = EXCLUDED.current_package,
            subscription_status     = EXCLUDED.subscription_status,
            subscription_active     = EXCLUDED.subscription_active,
            commission_eligible     = EXCLUDED.commission_eligible,
            active_direct_customers = EXCLUDED.active_direct_customers,
            purchased_courses       = EXCLUDED.purchased_courses,
            missing_requirements    = EXCLUDED.missing_requirements,
            next_rank               = EXCLUDED.next_rank
        """,
        (
            partner_id,
            progress["partner_rank"] or "Level 1",
            progress["current_level"],
            progress.get("current_package", ""),
            progress.get("subscription_status", ""),
            progress.get("subscription_active", False),
            progress.get("commission_eligible", False),
            progress.get("active_direct_customers", 0),
            json.dumps(progress.get("purchased_courses", []), ensure_ascii=False),
            json.dumps(progress.get("missing_requirements", []), ensure_ascii=False),
            "Level " + str(min(int(progress["current_level"] or 0) + 1, MAX_COMMISSION_DEPTH)),
        ),
    )


def _eligible_beneficiaries(cur, source_partner_id):
    """
    Port of getEligibleCommissionBeneficiaries() (line 1976).

    Depth 1 is the referring partner, then up to 4 sponsors above them.
    Replaces a full PartnerTree sheet scan with one recursive view read.
    """
    beneficiaries = [{
        "beneficiary_partner_id": source_partner_id,
        "commission_depth": 1,
        "line_owner_partner_id": source_partner_id,
    }]

    cur.execute(
        """
        SELECT ancestor_partner_id, depth
        FROM partner_upline
        WHERE root_partner_id = ? AND depth <= ?
        ORDER BY depth
        """,
        (source_partner_id, MAX_COMMISSION_DEPTH - 1),
    )

    for ancestor_partner_id, depth in cur.fetchall():
        if _is_company_owner(ancestor_partner_id):
            continue

        beneficiaries.append({
            "beneficiary_partner_id": ancestor_partner_id,
            "commission_depth": int(depth) + 1,
            "line_owner_partner_id": source_partner_id,
        })

    return beneficiaries


def _save_commission_record(cur, data):
    """
    Port of saveCommissionRecord() (line 3364).

    The Apps Script looked for an existing row with the same unique key before
    inserting, which could still double-write if two webhooks raced. Here the
    UNIQUE index on commission_unique_key makes ON CONFLICT DO NOTHING an
    absolute guarantee.
    """
    unique_key = build_commission_unique_key(data)
    commission_id = _text(data.get("commission_id")) or ("COM-" + str(uuid.uuid4()))

    cur.execute(
        """
        INSERT INTO commissions (
            commission_id, invoice_id, stripe_subscription_id, payer_client_id,
            payer_name, source_partner_id, beneficiary_partner_id,
            commission_depth, line_owner_partner_id, partner_rank, package,
            package_amount, commission_percent, commission_amount,
            period_start, period_end, status, notes, commission_unique_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (commission_unique_key) DO NOTHING
        RETURNING commission_id
        """,
        (
            commission_id,
            _text(data.get("invoice_id")),
            _text(data.get("stripe_subscription_id")),
            _text(data.get("payer_client_id")),
            _text(data.get("payer_name")),
            normalize_partner_id(data.get("source_partner_id")),
            normalize_partner_id(data.get("beneficiary_partner_id")),
            int(data.get("commission_depth") or 1),
            normalize_partner_id(data.get("line_owner_partner_id")),
            _text(data.get("partner_rank")),
            _text(data.get("package")),
            parse_money(data.get("package_amount")) or None,
            parse_money(data.get("commission_percent")) or None,
            parse_money(data.get("commission_amount")) or None,
            _text(data.get("period_start")) or None,
            _text(data.get("period_end")) or None,
            _text(data.get("status")) or "pending",
            _text(data.get("notes")),
            unique_key,
        ),
    )

    inserted = cur.fetchone()

    if not inserted:
        return _skip(
            "duplicate_commission_blocked",
            commission_unique_key=unique_key,
            beneficiary_partner_id=data.get("beneficiary_partner_id"),
        )

    return _ok(
        message="Commission saved",
        commission_id=inserted[0],
        commission_amount=data.get("commission_amount"),
        commission_depth=data.get("commission_depth"),
        beneficiary_partner_id=data.get("beneficiary_partner_id"),
    )


def _generate_commissions_for_subscription(payload, source_partner_id):
    """Port of generateCommissionsForSubscription() (line 3523 — the live one)."""
    source_partner_id = normalize_partner_id(source_partner_id)

    if not source_partner_id:
        return [_skip("missing_source_partner_id")]

    if _is_company_owner(source_partner_id):
        return [_skip("company_owner_source_partner_no_commission", source_partner_id=source_partner_id)]

    subscription_status = _lower(payload.get("subscription_status") or payload.get("status")) or "active"

    if subscription_status not in ACTIVE_SUBSCRIPTION_STATUSES:
        return [_skip("subscription_not_active", subscription_status=subscription_status)]

    package_name = _text(payload.get("plan_name") or payload.get("package"))
    package_amount = parse_money(payload.get("package_amount"))

    if package_amount <= 0:
        return [_skip("invalid_package_amount", package_name=package_name)]

    payer_client_id = _text(payload.get("client_id") or payload.get("session_id"))
    results = []

    with _conn() as conn:
        cur = conn.cursor()

        # ---------------------------------------------------------------
        # Compression
        # ---------------------------------------------------------------
        # The five commission slots are handed out to the first FIVE QUALIFIED
        # partners walking up the chain, not to whoever happens to sit at that
        # position. Someone who does not qualify is passed over and their share
        # rolls up to the next qualified partner above them.
        #
        # Without this a single unqualified partner in the middle silently
        # deleted every deeper payout in that leg: the money stayed with the
        # company and the qualified partners above earned nothing, despite
        # having met their own requirements.
        chain = _eligible_beneficiaries(cur, source_partner_id)
        slot = 1

        for beneficiary in chain:
            if slot > MAX_COMMISSION_DEPTH:
                break

            beneficiary_partner_id = beneficiary["beneficiary_partner_id"]
            position = beneficiary["commission_depth"]

            # The slot only advances when it is actually paid out, so an
            # unqualified partner is passed over and the next one up is offered
            # the SAME slot at the SAME rate.
            depth = slot

            # isSelfCommission() (line 2672) — a partner never earns on their
            # own subscription.
            if payer_client_id and _lower(beneficiary_partner_id) == _lower(payer_client_id):
                results.append(_skip(
                    "self_commission_blocked",
                    beneficiary_partner_id=beneficiary_partner_id,
                    payer_client_id=payer_client_id,
                ))
                continue

            progress = _calculate_partner_level_progress(cur, beneficiary_partner_id)
            _sync_partner_level(cur, beneficiary_partner_id, progress)

            rule = COMMISSION_RULES.get(depth)

            if not rule:
                results.append(_skip("invalid_commission_depth", commission_depth=depth))
                continue

            # isPartnerQualifiedForCommission() (line 3123)
            qualified = (
                progress["commission_eligible"]
                and progress["current_level"] >= rule["required_rank_number"]
            )

            if not qualified:
                # Passed over: slot is NOT consumed, it rolls up.
                results.append(_skip(
                    "rolled_up_to_next_qualified",
                    beneficiary_partner_id=beneficiary_partner_id,
                    position_in_chain=position,
                    slot_offered=depth,
                    current_level=progress["current_level"],
                    required_rank_number=rule["required_rank_number"],
                    subscription_status=progress["subscription_status"],
                    missing_requirements=progress["missing_requirements"],
                ))
                continue

            commission_percent = rule["percent"]
            commission_amount = round(package_amount * commission_percent / 100.0, 2)

            results.append(_save_commission_record(cur, {
                "invoice_id": payload.get("invoice_id") or payload.get("stripe_invoice_id"),
                "stripe_subscription_id": payload.get("stripe_subscription_id"),
                "payer_client_id": payer_client_id,
                "payer_name": payload.get("payer_name") or payload.get("referral_name"),
                "source_partner_id": source_partner_id,
                "beneficiary_partner_id": beneficiary_partner_id,
                "commission_depth": depth,
                "line_owner_partner_id": beneficiary["line_owner_partner_id"],
                "partner_rank": progress["partner_rank"],
                "package": package_name,
                "plan_name": package_name,
                "package_amount": package_amount,
                "commission_percent": commission_percent,
                "commission_amount": commission_amount,
                "period_start": payload.get("current_period_start") or payload.get("period_start"),
                "period_end": payload.get("current_period_end") or payload.get("period_end"),
                "status": "pending",
                "notes": (
                    "auto_generated_from_subscription; postgres_level_gate=true; "
                    f"rule={rule['label']}; "
                    f"required_rank_number={rule['required_rank_number']}; "
                    f"beneficiary_current_level={progress['current_level']}; "
                    f"subscription_status={progress['subscription_status']}; "
                    f"chain_position={position}; compressed={position != depth}"
                ),
            }))

            slot += 1

    return results or [_skip("no_eligible_beneficiaries")]


def _save_commission(payload):
    """Direct `commission` action — bypasses the subscription trigger."""
    beneficiary = normalize_partner_id(
        payload.get("beneficiary_partner_id") or payload.get("partner_id")
    )

    if not beneficiary:
        return _skip("missing_beneficiary_partner_id")

    if _is_company_owner(beneficiary):
        return _skip("company_owner_does_not_receive_commission", beneficiary_partner_id=beneficiary)

    with _conn() as conn:
        cur = conn.cursor()
        payload = dict(payload)
        payload["beneficiary_partner_id"] = beneficiary
        return _save_commission_record(cur, payload)


def _save_mlm_level(payload):
    """Port of saveMLMLevel() (line 3145 — the live one, not 1033)."""
    partner_id = normalize_partner_id(payload.get("partner_id"))

    if not partner_id:
        return _err("partner_id is required")

    missing = payload.get("missing_requirements")
    if isinstance(missing, (list, dict)):
        missing = json.dumps(missing, ensure_ascii=False)
    else:
        missing = json.dumps([_text(missing)] if _text(missing) else [], ensure_ascii=False)

    eligible = payload.get("commission_eligible")
    if isinstance(eligible, bool):
        eligible_value = eligible
    else:
        eligible_value = _lower(eligible) in ("yes", "true", "1")

    partner_rank = normalize_partner_rank(payload.get("partner_rank") or payload.get("current_level"))

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO partner_levels (
                partner_id, partner_rank, current_level, required_sales,
                completed_sales, required_course_workshop, level_status,
                next_rank, current_package, subscription_status,
                commission_eligible, missing_requirements
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (partner_id) DO UPDATE SET
                partner_rank             = EXCLUDED.partner_rank,
                current_level            = EXCLUDED.current_level,
                required_sales           = EXCLUDED.required_sales,
                completed_sales          = EXCLUDED.completed_sales,
                required_course_workshop = EXCLUDED.required_course_workshop,
                level_status             = EXCLUDED.level_status,
                next_rank                = EXCLUDED.next_rank,
                current_package          = EXCLUDED.current_package,
                subscription_status      = EXCLUDED.subscription_status,
                commission_eligible      = EXCLUDED.commission_eligible,
                missing_requirements     = EXCLUDED.missing_requirements
            """,
            (
                partner_id,
                partner_rank,
                rank_number(partner_rank),
                int(parse_money(payload.get("required_sales")) or 1),
                int(parse_money(payload.get("completed_sales")) or 0),
                _text(payload.get("required_course_workshop") or payload.get("required_course")),
                _text(payload.get("level_status")) or "active",
                _text(payload.get("next_rank") or payload.get("next_level")),
                _text(payload.get("current_package")),
                _lower(payload.get("subscription_status")),
                eligible_value,
                missing,
            ),
        )

    return _ok(message="MLM level saved", partner_id=partner_id, partner_rank=partner_rank)


def _save_course_purchase(payload):
    partner_id = normalize_partner_id(payload.get("partner_id"))

    if not partner_id:
        return _err("partner_id is required")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO course_purchases (
                partner_id, client_id, course_code, course_name, amount,
                currency, status, stripe_payment_id, stripe_customer_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (partner_id, course_code, stripe_payment_id) DO NOTHING
            """,
            (
                partner_id,
                _text(payload.get("client_id")),
                _text(payload.get("course_code")),
                _text(payload.get("course_name")),
                parse_money(payload.get("amount")) or None,
                _text(payload.get("currency")) or "USD",
                _text(payload.get("status")) or "paid",
                _text(payload.get("stripe_payment_id")),
                _text(payload.get("stripe_customer_id")),
                _text(payload.get("notes")),
            ),
        )

    return _ok(message="Course purchase saved", partner_id=partner_id)


def _bot_control_get(payload):
    client_id = _text(payload.get("client_id"))

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT bot_status, handoff_reason, updated_by, updated_at "
            "FROM client_bot_controls WHERE client_id = ?",
            (client_id,),
        )
        row = cur.fetchone()

    if not row:
        return _ok(bot_status="on", client_id=client_id, found=False)

    return _ok(
        client_id=client_id,
        found=True,
        bot_status=row[0],
        handoff_reason=row[1],
        updated_by=row[2],
        updated_at=str(row[3] or ""),
    )


def _bot_control_update(payload):
    client_id = _text(payload.get("client_id"))
    new_status = _lower(payload.get("bot_status")) or "on"

    if new_status not in ("on", "off", "paused"):
        return _err("bot_status must be on, off or paused")

    with _conn() as conn:
        cur = conn.cursor()

        cur.execute("SELECT bot_status FROM client_bot_controls WHERE client_id = ?", (client_id,))
        row = cur.fetchone()
        old_status = row[0] if row else ""

        cur.execute(
            """
            INSERT INTO client_bot_controls (
                client_id, partner_id, bot_status, handoff_reason, updated_by, source, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (client_id) DO UPDATE SET
                partner_id     = COALESCE(NULLIF(EXCLUDED.partner_id, ''), client_bot_controls.partner_id),
                bot_status     = EXCLUDED.bot_status,
                handoff_reason = EXCLUDED.handoff_reason,
                updated_by     = EXCLUDED.updated_by,
                source         = EXCLUDED.source
            """,
            (
                client_id,
                normalize_partner_id(payload.get("partner_id")),
                new_status,
                _text(payload.get("handoff_reason")),
                _text(payload.get("updated_by") or payload.get("actor")),
                _text(payload.get("source")),
                _text(payload.get("notes")),
            ),
        )

        cur.execute(
            """
            INSERT INTO bot_control_logs (
                client_id, partner_id, old_status, new_status, reason, actor, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                normalize_partner_id(payload.get("partner_id")),
                old_status,
                new_status,
                _text(payload.get("handoff_reason") or payload.get("reason")),
                _text(payload.get("updated_by") or payload.get("actor")),
                _text(payload.get("source")),
            ),
        )

    return _ok(message="Bot control updated", client_id=client_id, bot_status=new_status)


def _save_smart_link_event(payload):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO smart_link_events (
                event_id, smart_ref, client_id, partner_id, event_type,
                source, session_id, page_url, referrer_url, message, user_agent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                _text(payload.get("event_id")) or str(uuid.uuid4()),
                _text(payload.get("smart_ref")),
                _text(payload.get("client_id")),
                normalize_partner_id(payload.get("partner_id")),
                _text(payload.get("event_type")),
                _text(payload.get("source")),
                _text(payload.get("session_id")),
                _text(payload.get("page_url")),
                _text(payload.get("referrer_url")),
                _text(payload.get("message")),
                _text(payload.get("user_agent")),
            ),
        )

    return _ok(message="Smart link event saved")


def _save_admin_audit_log(payload):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_logs (
                audit_id, actor, action, target_type, target_id, partner_id,
                before_json, after_json, reason, source, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (audit_id) DO NOTHING
            """,
            (
                _text(payload.get("audit_id")) or str(uuid.uuid4()),
                _text(payload.get("actor")),
                _text(payload.get("audit_action") or payload.get("target_action")),
                _text(payload.get("target_type")),
                _text(payload.get("target_id")),
                normalize_partner_id(payload.get("partner_id")),
                json.dumps(payload.get("before_json") or {}, ensure_ascii=False),
                json.dumps(payload.get("after_json") or {}, ensure_ascii=False),
                _text(payload.get("reason")),
                _text(payload.get("source")),
                _text(payload.get("status")),
                _text(payload.get("notes")),
            ),
        )

    return _ok(message="Audit log saved")


# =====================================================================
# Router
# =====================================================================

HANDLERS = {
    "lead": _save_lead,
    "client_profile": _save_client_profile,
    "partner": _save_partner,
    "partner_tree": _save_partner_tree,
    "referral": _save_referral,
    "subscription": _save_subscription,
    "commission": _save_commission,
    "mlm_level": _save_mlm_level,
    "course_purchase": _save_course_purchase,
    "bot_control_get": _bot_control_get,
    "bot_control_update": _bot_control_update,
    "smart_link_event_log": _save_smart_link_event,
    "admin_audit_log": _save_admin_audit_log,
}

# The three dashboard reads live in their own module - they are pure queries
# and together they are as large as everything above.
# cancellation_flow is loaded LAST so its handlers replace the plain
# create/update stubs that requests_compat registers for the same actions.
for _module_name in ("dashboard_compat", "admin_compat", "requests_compat", "cancellation_flow"):
    try:
        _module = __import__(_module_name)
    except ImportError:
        _module = __import__(f"backend.{_module_name}", fromlist=[_module_name])

    HANDLERS.update(_module.HANDLERS)

# Still served by Google Apps Script until ported. Listed explicitly so the
# remaining work is visible rather than implied.
PENDING_ACTIONS = ()


def _fallback_to_sheets(payload, label):
    """
    Send an unported action to the real Google Apps Script, as before.

    Imports the _real_ implementation, not the public wrapper — the wrapper
    routes back into this module, which would recurse forever.
    """
    try:
        from database import _post_to_google_sheet_json_real as real_sheet_call
    except ImportError:
        from backend.database import _post_to_google_sheet_json_real as real_sheet_call

    return real_sheet_call(payload, label=label)


def handle(payload, label="unknown"):
    """
    Entry point. Same signature and same return shape as
    database.post_to_google_sheet_json().
    """
    action = _text((payload or {}).get("action")) or "lead"

    if DATA_BACKEND == "sheets":
        return _fallback_to_sheets(payload, label)

    handler = HANDLERS.get(action)

    if handler is None:
        print(f"SHEET COMPAT FALLBACK -> google sheets | action={action}", flush=True)
        return _fallback_to_sheets(payload, label)

    try:
        result = handler(payload or {})
    except Exception as error:
        print(f"SHEET COMPAT ERROR | action={action} | {type(error).__name__}: {error}", flush=True)
        return _err(str(error), action=action)

    # During `dual`, keep writing to the sheet as well so the team can compare
    # both stores before cutting over for real.
    if DATA_BACKEND == "dual" and action not in ("bot_control_get",):
        try:
            _fallback_to_sheets(payload, label)
        except Exception as error:
            print(f"SHEET COMPAT DUAL-WRITE WARNING | action={action} | {error}", flush=True)

    print(f"SHEET COMPAT OK | action={action} | status={result.get('status')}", flush=True)

    # Telegram notification. Every data action passes through here, so hooking
    # this one point covers the whole system instead of relying on a call being
    # added at each new write site. telegram_bot filters the read-only chatter
    # and swallows its own errors, so a telegram outage cannot fail an action.
    try:
        try:
            from telegram_bot import notify_action
        except ImportError:
            from backend.telegram_bot import notify_action

        notify_action(action, payload, result)
    except Exception as notify_error:
        print(f"TELEGRAM HOOK SKIPPED | action={action} | {notify_error}", flush=True)

    return result


def coverage():
    """Reports what is on PostgreSQL and what still goes to Google Sheets."""
    return {
        "backend": DATA_BACKEND,
        "ported": sorted(HANDLERS),
        "ported_count": len(HANDLERS),
        "pending": sorted(PENDING_ACTIONS),
        "pending_count": len(PENDING_ACTIONS),
    }


if __name__ == "__main__":
    report = coverage()
    print(f"DATA_BACKEND = {report['backend']}")
    print(f"\nOn PostgreSQL ({report['ported_count']}):")
    for name in report["ported"]:
        print(f"  + {name}")
    print(f"\nStill on Google Sheets ({report['pending_count']}):")
    for name in report["pending"]:
        print(f"  - {name}")
