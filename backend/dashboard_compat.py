# dashboard_compat.py
#
# PostgreSQL versions of the three dashboard read actions:
#     partner_dashboard_data   Apps Script getPartnerDashboardData()   line 4391
#     client_dashboard_data    Apps Script getClientDashboardData()    line 4844
#     admin_dashboard_data     Apps Script getAdminDashboardData()     line 5985
#
# The JSON these return is consumed directly by the dashboard HTML inside
# main.py, so every key name, nesting level and bucket name below is chosen to
# match the Apps Script output exactly. Where the Apps Script looped over an
# entire sheet in JavaScript, the equivalent work is done here as SQL
# aggregation.
#
# One deliberate difference: "row_number" was the Google Sheets row index. It
# has no meaning in a database, but the dashboard HTML reads it, so it is
# emitted as a 1-based position within the returned list. Nothing in the admin
# actions keys off it — those use commission_id / partner_id.

from datetime import date, datetime
from decimal import Decimal

MAX_PARTNER_ROWS = 20
MAX_ADMIN_ROWS = 25
MAX_TREE_ROWS = 100

ACTIVE_SUBSCRIPTION_STATUSES = ("active", "paid", "trialing")
ACTIVE_PARTNER_STATUSES = ("active", "approved", "نشط")

COMMISSION_BUCKETS = ("pending", "approved", "paid", "rejected", "hold", "other", "all")


def _conn():
    from db import get_connection
    return get_connection()


def _text(value):
    """Apps Script ALSAAB_DASHBOARD_TEXT_ - never emit None into the JSON."""
    if value is None:
        return ""

    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value.isoformat()

    return str(value).strip()


def _lower(value):
    return _text(value).lower()


def _money(value):
    """Apps Script ALSAAB_DASHBOARD_MONEY_ - always a JSON number."""
    if value is None:
        return 0.0

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (int, float)):
        return float(value)

    import re

    cleaned = re.sub(r"[^\d.\-]", "", str(value).replace(",", ""))

    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _rows_as_dicts(cur):
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _commission_bucket(status):
    """Apps Script bucketing, including the hold/held alias."""
    normalized = _lower(status) or "pending"

    if normalized in ("pending", "approved", "paid", "rejected"):
        return normalized

    if normalized in ("hold", "held"):
        return "hold"

    return "other"


def _subscription_bucket(status):
    """Port of ALSAAB_ADMIN_DASHBOARD_STATUS_BUCKET_ (line 5618)."""
    normalized = _lower(status)

    if not normalized:
        return "unknown"

    if normalized in ACTIVE_SUBSCRIPTION_STATUSES:
        return "active"

    if normalized == "pending":
        return "pending"

    if normalized in ("payment_failed", "past_due", "unpaid"):
        return "payment_failed"

    if normalized in ("cancelled", "canceled"):
        return "cancelled"

    if normalized == "inactive":
        return "inactive"

    return "other"


def _empty_commission_totals():
    return {bucket: 0 for bucket in COMMISSION_BUCKETS}


# =====================================================================
# partner_dashboard_data
# =====================================================================

def _partner_profile(cur, partner_id):
    cur.execute(
        """
        SELECT partner_id, partner_name, client_id, sponsor_partner_id,
               parent_partner_id, phone, email, country, partner_rank, status,
               referral_link, invited_by, active_direct_customers,
               active_network_customers, notes
        FROM partners WHERE partner_id = ?
        """,
        (partner_id,),
    )
    rows = _rows_as_dicts(cur)

    if not rows:
        return {"found": False, "partner_id": partner_id}

    row = rows[0]

    return {
        "found": True,
        "row_number": 1,
        "partner_id": partner_id,
        "partner_name": _text(row["partner_name"]),
        "client_id": _text(row["client_id"]),
        "sponsor_partner_id": _text(row["sponsor_partner_id"]),
        "parent_partner_id": _text(row["parent_partner_id"]),
        "phone": _text(row["phone"]),
        "email": _text(row["email"]),
        "country": _text(row["country"]),
        "partner_rank": _text(row["partner_rank"]),
        "status": _text(row["status"]),
        "referral_link": _text(row["referral_link"]),
        "invited_by": _text(row["invited_by"]),
        "active_direct_customers": _text(row["active_direct_customers"]),
        "active_network_customers": _text(row["active_network_customers"]),
        "notes": _text(row["notes"]),
    }


def _partner_level(cur, partner_id):
    cur.execute(
        """
        SELECT partner_rank, current_level, required_sales, completed_sales,
               required_course_workshop, level_status, next_rank,
               current_package, subscription_status, commission_eligible,
               missing_requirements, updated_at
        FROM partner_levels WHERE partner_id = ?
        """,
        (partner_id,),
    )
    rows = _rows_as_dicts(cur)

    empty = {
        "found": False,
        "partner_id": partner_id,
        "partner_rank": "",
        "current_level": "",
        "required_sales": "",
        "completed_sales": "0",
        "required_course_workshop": "",
        "level_status": "",
        "next_rank": "",
        "current_package": "",
        "subscription_status": "",
        "commission_eligible": "",
        "missing_requirements": "",
        "last_updated": "",
    }

    if not rows:
        return empty

    row = rows[0]

    return {
        "found": True,
        "partner_id": partner_id,
        "partner_rank": _text(row["partner_rank"]),
        # Report the level the partner has actually reached.
        #
        # This used to echo partner_rank, a stale label inherited from the
        # sheet. A partner sitting at level 2 was told "Level 1", and one who
        # had reached no level at all was also told "Level 1" — so the badge
        # promised a 25% tier that the payout engine would refuse.
        "current_level": f"Level {int(row['current_level'] or 0)}"
                         if int(row["current_level"] or 0)
                         else "لم تبلغ أي مستوى بعد",
        "required_sales": _text(row["required_sales"]),
        "completed_sales": _text(row["completed_sales"]),
        "required_course_workshop": _text(row["required_course_workshop"]),
        "level_status": _text(row["level_status"]),
        "next_rank": _text(row["next_rank"]),
        "current_package": _text(row["current_package"]),
        "subscription_status": _text(row["subscription_status"]),
        # The sheet stored yes/no strings; keep that so the HTML compares equal.
        "commission_eligible": "yes" if row["commission_eligible"] else "no",
        "missing_requirements": _text(row["missing_requirements"]),
        "last_updated": _text(row["updated_at"]),
    }


def _partner_commissions(cur, partner_id):
    cur.execute(
        """
        SELECT created_at, commission_id, invoice_id, stripe_subscription_id,
               payer_client_id, payer_name, source_partner_id,
               beneficiary_partner_id, commission_depth, partner_rank, package,
               package_amount, commission_percent, commission_amount, status,
               paid_date, notes
        FROM commissions
        WHERE beneficiary_partner_id = ?
        ORDER BY created_at DESC, commission_id DESC
        """,
        (partner_id,),
    )
    rows = _rows_as_dicts(cur)

    totals = _empty_commission_totals()
    counts = _empty_commission_totals()
    recent = []

    for index, row in enumerate(rows, start=1):
        amount = _money(row["commission_amount"])
        status = _lower(row["status"]) or "pending"
        bucket = _commission_bucket(status)

        totals[bucket] += amount
        totals["all"] += amount
        counts[bucket] += 1
        counts["all"] += 1

        if len(recent) < MAX_PARTNER_ROWS:
            recent.append({
                "row_number": index,
                "date": _text(row["created_at"]),
                "commission_id": _text(row["commission_id"]),
                "invoice_id": _text(row["invoice_id"]),
                "stripe_subscription_id": _text(row["stripe_subscription_id"]),
                "payer_client_id": _text(row["payer_client_id"]),
                "payer_name": _text(row["payer_name"]),
                "source_partner_id": _text(row["source_partner_id"]),
                "beneficiary_partner_id": _text(row["beneficiary_partner_id"]),
                "commission_depth": _text(row["commission_depth"]),
                "partner_rank": _text(row["partner_rank"]),
                "package": _text(row["package"]),
                "package_amount": _money(row["package_amount"]),
                "commission_percent": _money(row["commission_percent"]),
                "commission_amount": amount,
                "status": status,
                "paid_date": _text(row["paid_date"]),
                "notes": _text(row["notes"]),
            })

    return {"totals": totals, "counts": counts, "recent": recent}


def _partner_customers(cur, partner_id):
    cur.execute(
        """
        SELECT created_at, client_id, session_id, source_partner_id, plan_name,
               package_amount, subscription_status, stripe_subscription_id,
               current_period_start, current_period_end,
               cancel_at_period_end, cancel_effective_at, cancel_requested_at
        FROM subscriptions
        WHERE source_partner_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (partner_id,),
    )
    rows = _rows_as_dicts(cur)

    active_keys = set()
    all_keys = set()
    recent = []

    for index, row in enumerate(rows, start=1):
        customer_key = _text(row["client_id"]) or _text(row["session_id"])

        if not customer_key:
            continue

        status = _text(row["subscription_status"])
        all_keys.add(customer_key)

        if _lower(status) in ACTIVE_SUBSCRIPTION_STATUSES:
            active_keys.add(customer_key)

        if len(recent) < MAX_PARTNER_ROWS:
            recent.append({
                "row_number": index,
                "date": _text(row["created_at"]),
                "client_id": _text(row["client_id"]),
                "session_id": _text(row["session_id"]),
                "source_partner_id": _text(row["source_partner_id"]),
                "plan_name": _text(row["plan_name"]),
                "package_amount": _money(row["package_amount"]),
                "subscription_status": status,
                "stripe_subscription_id": _text(row["stripe_subscription_id"]),
                "current_period_start": _text(row["current_period_start"]),
                "current_period_end": _text(row["current_period_end"]),
                # A customer who is winding down still counts as active until
                # the date passes, so the partner needs to see it coming rather
                # than discover it when the count drops.
                "cancel_at_period_end": bool(row["cancel_at_period_end"]),
                "cancel_effective_at": _text(row["cancel_effective_at"]),
                "ends_on": _text(row["cancel_effective_at"])[:10],
                "cancel_pending": bool(row["cancel_requested_at"]) and not bool(row["cancel_at_period_end"]),
            })

    return {
        "active_direct_paid_count": len(active_keys),
        "all_direct_count": len(all_keys),
        "recent": recent,
    }


def _partner_courses(cur, partner_id):
    cur.execute(
        """
        SELECT created_at, partner_id, client_id, course_code, course_name,
               amount, currency, status, stripe_payment_id, paid_at,
               refunded_at, notes
        FROM course_purchases
        WHERE partner_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (partner_id,),
    )

    courses = []

    for index, row in enumerate(_rows_as_dicts(cur), start=1):
        courses.append({
            "row_number": index,
            "date": _text(row["created_at"]),
            "partner_id": _text(row["partner_id"]),
            "client_id": _text(row["client_id"]),
            "course_code": _text(row["course_code"]),
            "course_name": _text(row["course_name"]),
            "amount": _money(row["amount"]),
            "currency": _text(row["currency"]),
            "status": _text(row["status"]),
            "stripe_payment_id": _text(row["stripe_payment_id"]),
            "paid_at": _text(row["paid_at"]),
            "refunded_at": _text(row["refunded_at"]),
            "notes": _text(row["notes"]),
        })

    return {"purchased_courses": courses}


def _partner_tree(cur, partner_id):
    """
    Reads the derived partner_downline view rather than the partner_tree
    table. The view walks partners.sponsor_partner_id recursively, so it stays
    correct without anyone maintaining a closure table - and on the imported
    data it already found one relation the hand-maintained sheet was missing.
    """
    cur.execute(
        """
        SELECT d.descendant_partner_id, d.depth, p.sponsor_partner_id
        FROM partner_downline d
        LEFT JOIN partners p ON p.partner_id = d.descendant_partner_id
        WHERE d.root_partner_id = ?
        ORDER BY d.depth, d.descendant_partner_id
        """,
        (partner_id,),
    )
    rows = _rows_as_dicts(cur)

    depth_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    out = []

    for index, row in enumerate(rows, start=1):
        depth = int(row["depth"] or 0)

        if depth < 1 or depth > 5:
            continue

        depth_counts[depth] += 1

        if len(out) < MAX_TREE_ROWS:
            out.append({
                "row_number": index,
                "ancestor_partner_id": partner_id,
                "descendant_partner_id": _text(row["descendant_partner_id"]),
                "depth": depth,
                "line_owner_partner_id": _text(row["sponsor_partner_id"]),
                "notes": "",
            })

    return {
        "downline_count": sum(depth_counts.values()),
        # JSON object keys must be strings for the HTML to index them.
        "depth_counts": {str(k): v for k, v in depth_counts.items()},
        "rows": out,
    }


def partner_dashboard_data(payload):
    from sheet_compat import normalize_partner_id, COMPANY_OWNER_PARTNER_ID

    partner_id = normalize_partner_id(
        payload.get("partner_id") or payload.get("partnerId") or payload.get("id") or ""
    )

    if not partner_id:
        return {"status": "error", "message": "partner_id is required"}

    if partner_id.lower() == COMPANY_OWNER_PARTNER_ID.lower():
        return {
            "status": "error",
            "message": "company owner does not have partner dashboard",
            "partner_id": partner_id,
        }

    with _conn() as conn:
        cur = conn.cursor()

        profile = _partner_profile(cur, partner_id)

        if not profile.get("found"):
            return {"status": "error", "message": "partner not found", "partner_id": partner_id}

        return {
            "status": "success",
            "action": "partner_dashboard_data",
            "generated_at": _now(),
            "partner_id": partner_id,
            "partner_profile": profile,
            "level": _partner_level(cur, partner_id),
            "customers": _partner_customers(cur, partner_id),
            "commissions": _partner_commissions(cur, partner_id),
            "courses": _partner_courses(cur, partner_id),
            "tree": _partner_tree(cur, partner_id),
        }


# =====================================================================
# client_dashboard_data
# =====================================================================

def client_dashboard_data(payload):
    from sheet_compat import normalize_partner_id

    partner_id = normalize_partner_id(payload.get("partner_id") or payload.get("partnerId") or "")

    if not partner_id:
        return {"status": "error", "message": "partner_id is required"}

    with _conn() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT group_id, partner_id, client_id, group_title, group_description,
                   sales_instructions, product_notes, pricing_notes,
                   payment_links_notes, image_urls, status, created_at,
                   updated_at, notes
            FROM product_image_groups
            WHERE partner_id = ? AND status <> 'deleted'
            ORDER BY created_at DESC
            """,
            (partner_id,),
        )

        groups = []

        for index, row in enumerate(_rows_as_dicts(cur), start=1):
            image_urls = row["image_urls"]

            if isinstance(image_urls, str):
                import json
                try:
                    image_urls = json.loads(image_urls)
                except ValueError:
                    image_urls = [u for u in image_urls.split(",") if u.strip()]

            groups.append({
                "row_number": index,
                "date": _text(row["created_at"]),
                "group_id": _text(row["group_id"]),
                "partner_id": _text(row["partner_id"]),
                "client_id": _text(row["client_id"]),
                "group_title": _text(row["group_title"]),
                "group_description": _text(row["group_description"]),
                "sales_instructions": _text(row["sales_instructions"]),
                "product_notes": _text(row["product_notes"]),
                "pricing_notes": _text(row["pricing_notes"]),
                "payment_links_notes": _text(row["payment_links_notes"]),
                "image_urls": image_urls or [],
                "status": _text(row["status"]),
                "created_at": _text(row["created_at"]),
                "updated_at": _text(row["updated_at"]),
                "notes": _text(row["notes"]),
            })

        cur.execute(
            """
            SELECT payment_link_id, partner_id, client_id, product_name,
                   payment_link, amount, currency, description,
                   linked_image_group_id, status, created_at, updated_at, notes
            FROM client_payment_links
            WHERE partner_id = ? AND status <> 'deleted'
            ORDER BY created_at DESC
            """,
            (partner_id,),
        )

        links = []

        for index, row in enumerate(_rows_as_dicts(cur), start=1):
            links.append({
                "row_number": index,
                "date": _text(row["created_at"]),
                "payment_link_id": _text(row["payment_link_id"]),
                "partner_id": _text(row["partner_id"]),
                "client_id": _text(row["client_id"]),
                "product_name": _text(row["product_name"]),
                "payment_link": _text(row["payment_link"]),
                "amount": _money(row["amount"]),
                "currency": _text(row["currency"]),
                "description": _text(row["description"]),
                "linked_image_group_id": _text(row["linked_image_group_id"]),
                "status": _text(row["status"]),
                "created_at": _text(row["created_at"]),
                "updated_at": _text(row["updated_at"]),
                "notes": _text(row["notes"]),
            })

    return {
        "status": "success",
        "action": "client_dashboard_data",
        "partner_id": partner_id,
        "product_image_groups": groups,
        "client_payment_links": links,
    }


# =====================================================================
# admin_dashboard_data
# =====================================================================

def _admin_partners(cur):
    cur.execute(
        """
        SELECT created_at, client_id, partner_id, sponsor_partner_id,
               partner_name, phone, email, partner_rank, status, referral_link
        FROM partners
        ORDER BY created_at DESC, partner_id DESC
        """
    )
    rows = _rows_as_dicts(cur)

    summary = {"total": 0, "active": 0, "inactive": 0, "suspended": 0, "other": 0}
    recent = []

    for index, row in enumerate(rows, start=1):
        status = _lower(row["status"])
        summary["total"] += 1

        if status in ACTIVE_PARTNER_STATUSES:
            summary["active"] += 1
        elif status == "inactive":
            summary["inactive"] += 1
        elif status == "suspended":
            summary["suspended"] += 1
        else:
            summary["other"] += 1

        if len(recent) < MAX_ADMIN_ROWS:
            recent.append({
                "row_number": index,
                "date": _text(row["created_at"]),
                "client_id": _text(row["client_id"]),
                "partner_id": _text(row["partner_id"]),
                "sponsor_partner_id": _text(row["sponsor_partner_id"]),
                "partner_name": _text(row["partner_name"]),
                "phone": _text(row["phone"]),
                "email": _text(row["email"]),
                "partner_rank": _text(row["partner_rank"]),
                "status": _text(row["status"]),
                "referral_link": _text(row["referral_link"]),
            })

    return {"summary": summary, "recent": recent}


def _admin_subscriptions(cur):
    cur.execute(
        """
        SELECT created_at, client_id, session_id, source_partner_id, plan_name,
               package_amount, subscription_status, stripe_customer_id,
               stripe_subscription_id
        FROM subscriptions
        ORDER BY created_at DESC, id DESC
        """
    )
    rows = _rows_as_dicts(cur)

    summary = {
        "total": 0, "active": 0, "pending": 0, "payment_failed": 0,
        "cancelled": 0, "inactive": 0, "other": 0, "total_amount": 0,
    }
    plan_counts = {}
    recent = []

    for index, row in enumerate(rows, start=1):
        status = _text(row["subscription_status"])
        bucket = _subscription_bucket(status)
        amount = _money(row["package_amount"])
        plan = _lower(row["plan_name"]) or "unknown"

        summary["total"] += 1
        summary["total_amount"] += amount

        if bucket in summary:
            summary[bucket] += 1
        else:
            summary["other"] += 1

        plan_counts[plan] = plan_counts.get(plan, 0) + 1

        if len(recent) < MAX_ADMIN_ROWS:
            recent.append({
                "row_number": index,
                "date": _text(row["created_at"]),
                "client_id": _text(row["client_id"]),
                "session_id": _text(row["session_id"]),
                "source_partner_id": _text(row["source_partner_id"]),
                "plan_name": _text(row["plan_name"]),
                "package_amount": amount,
                "subscription_status": status,
                "stripe_customer_id": _text(row["stripe_customer_id"]),
                "stripe_subscription_id": _text(row["stripe_subscription_id"]),
            })

    return {"summary": summary, "plan_counts": plan_counts, "recent": recent}


def _admin_commissions(cur):
    cur.execute(
        """
        SELECT created_at, commission_id, invoice_id, payer_client_id,
               source_partner_id, beneficiary_partner_id, commission_depth,
               partner_rank, package, package_amount, commission_percent,
               commission_amount, status, paid_date
        FROM commissions
        ORDER BY created_at DESC, commission_id DESC
        """
    )
    rows = _rows_as_dicts(cur)

    totals = _empty_commission_totals()
    counts = _empty_commission_totals()
    recent = []

    for index, row in enumerate(rows, start=1):
        amount = _money(row["commission_amount"])
        status = _lower(row["status"]) or "pending"
        bucket = _commission_bucket(status)

        totals[bucket] += amount
        totals["all"] += amount
        counts[bucket] += 1
        counts["all"] += 1

        if len(recent) < MAX_ADMIN_ROWS:
            recent.append({
                "row_number": index,
                "date": _text(row["created_at"]),
                "commission_id": _text(row["commission_id"]),
                "invoice_id": _text(row["invoice_id"]),
                "payer_client_id": _text(row["payer_client_id"]),
                "source_partner_id": _text(row["source_partner_id"]),
                "beneficiary_partner_id": _text(row["beneficiary_partner_id"]),
                "commission_depth": _text(row["commission_depth"]),
                "partner_rank": _text(row["partner_rank"]),
                "package": _text(row["package"]),
                "package_amount": _money(row["package_amount"]),
                "commission_percent": _money(row["commission_percent"]),
                "commission_amount": amount,
                "status": status,
                "paid_date": _text(row["paid_date"]),
            })

    return {"totals": totals, "counts": counts, "recent": recent}


def _admin_levels(cur):
    cur.execute(
        """
        SELECT partner_id, partner_rank, current_level, required_sales,
               completed_sales, level_status, next_rank, current_package,
               subscription_status, commission_eligible, missing_requirements,
               updated_at
        FROM partner_levels
        ORDER BY updated_at DESC, partner_id
        """
    )
    rows = _rows_as_dicts(cur)

    level_counts = {}
    eligible_counts = {"yes": 0, "no": 0, "unknown": 0}
    recent = []

    for index, row in enumerate(rows, start=1):
        rank = _text(row["partner_rank"]) or "unknown"

        # Group by the COMPUTED level, not the partner_rank text.
        #
        # partner_rank is a legacy label carried over from the sheet and it
        # drifts: 11 of 16 partners carried "Level 1" while their real level
        # was 0 or 2, so this panel claimed everyone had qualified for the 25%
        # tier when most had qualified for nothing.
        computed = int(row["current_level"] or 0)
        level_key = f"Level {computed}" if computed else "لم يبلغ أي مستوى"
        level_counts[level_key] = level_counts.get(level_key, 0) + 1

        eligible = "yes" if row["commission_eligible"] else "no"
        eligible_counts[eligible] += 1

        if len(recent) < MAX_ADMIN_ROWS:
            recent.append({
                "row_number": index,
                "partner_id": _text(row["partner_id"]),
                "partner_rank": rank,
                "current_level": computed,
                "required_sales": _text(row["required_sales"]),
                "completed_sales": _text(row["completed_sales"]),
                "level_status": _text(row["level_status"]),
                "next_rank": _text(row["next_rank"]),
                "current_package": _text(row["current_package"]),
                "subscription_status": _text(row["subscription_status"]),
                "commission_eligible": eligible,
                "missing_requirements": _text(row["missing_requirements"]),
                "last_updated": _text(row["updated_at"]),
            })

    return {"level_counts": level_counts, "eligible_counts": eligible_counts, "recent": recent}


def _admin_courses(cur):
    cur.execute(
        """
        SELECT created_at, partner_id, client_id, course_code, course_name,
               amount, currency, status, stripe_payment_id
        FROM course_purchases
        ORDER BY created_at DESC, id DESC
        """
    )
    rows = _rows_as_dicts(cur)

    course_counts = {}
    summary = {"total": 0, "total_amount": 0}
    recent = []

    for index, row in enumerate(rows, start=1):
        code = _text(row["course_code"]) or "unknown"
        amount = _money(row["amount"])

        course_counts[code] = course_counts.get(code, 0) + 1
        summary["total"] += 1
        summary["total_amount"] += amount

        if len(recent) < MAX_ADMIN_ROWS:
            recent.append({
                "row_number": index,
                "date": _text(row["created_at"]),
                "partner_id": _text(row["partner_id"]),
                "client_id": _text(row["client_id"]),
                "course_code": code,
                "course_name": _text(row["course_name"]),
                "amount": amount,
                "currency": _text(row["currency"]),
                "status": _text(row["status"]),
                "stripe_payment_id": _text(row["stripe_payment_id"]),
            })

    return {"summary": summary, "course_counts": course_counts, "recent": recent}


def admin_dashboard_data(payload):
    with _conn() as conn:
        cur = conn.cursor()

        return {
            "status": "success",
            "action": "admin_dashboard_data",
            "generated_at": _now(),
            "partners": _admin_partners(cur),
            "subscriptions": _admin_subscriptions(cur),
            "commissions": _admin_commissions(cur),
            "levels": _admin_levels(cur),
            "courses": _admin_courses(cur),
        }


HANDLERS = {
    "partner_dashboard_data": partner_dashboard_data,
    "client_dashboard_data": client_dashboard_data,
    "admin_dashboard_data": admin_dashboard_data,
}
