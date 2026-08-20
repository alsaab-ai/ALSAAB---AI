# requests_compat.py
#
# The remaining Apps Script actions. They all follow the same three shapes —
# create a request row, list rows for admin, update one row — so they are
# built here from one small set of helpers rather than repeated by hand:
#
#   upgrade_request_create / admin_upgrade_requests /
#   admin_upgrade_request_update / upgrade_subscription_lookup /
#   upgrade_request_mark_scheduled
#   cancellation_request_create / admin_cancellation_requests /
#   admin_cancellation_request_update
#   website_setup_request / admin_website_setup_requests /
#   admin_update_website_setup_request / website_install_ping
#   whatsapp_setup_request / admin_whatsapp_setup_requests /
#   admin_update_whatsapp_setup_request / whatsapp_channel_upsert /
#   whatsapp_channel_lookup / whatsapp_message_log
#   product_image_group / client_payment_link
#   smart_link_summary_get

import json
import uuid
from datetime import datetime

MAX_ROWS = 100


def _conn():
    from db import get_connection
    return get_connection()


def _partner_id(value):
    from sheet_compat import normalize_partner_id
    return normalize_partner_id(value)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()


def _lower(value):
    return _text(value).lower()


def _money(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        import re
        cleaned = re.sub(r"[^\d.\-]", "", str(value))
        return float(cleaned) if cleaned else None


def _int(value):
    amount = _money(value)
    return int(amount) if amount is not None else None


def _bool(value):
    if isinstance(value, bool):
        return value
    return _lower(value) in ("yes", "true", "1", "on", "enabled")


def _new_id(prefix):
    return f"{prefix}-{uuid.uuid4()}"


def _rows(cur):
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _serialize(rows, date_field="created_at"):
    out = []
    for index, row in enumerate(rows, start=1):
        record = {"row_number": index, "date": _text(row.get(date_field))}
        for key, value in row.items():
            if isinstance(value, datetime):
                record[key] = _text(value)
            elif isinstance(value, bool):
                record[key] = "yes" if value else "no"
            elif value is None:
                record[key] = ""
            elif isinstance(value, (int, float)):
                record[key] = value
            else:
                record[key] = _text(value)
        out.append(record)
    return out


def _ok(message, **fields):
    result = {"status": "success", "message": message}
    result.update(fields)
    return result


def _err(message, **fields):
    result = {"status": "error", "message": message}
    result.update(fields)
    return result


def _list_requests(table, action, key_column, order_column="created_at", status_filter=None):
    """Builds an admin list handler for a request table."""

    def handler(payload):
        clauses, params = [], []

        wanted_status = _lower(payload.get("status") or payload.get("filter_status"))
        if wanted_status and wanted_status != "all" and status_filter:
            clauses.append(f"{status_filter} = ?")
            params.append(wanted_status)

        client_id = _text(payload.get("client_id"))
        if client_id:
            clauses.append("client_id = ?")
            params.append(client_id)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT * FROM {table}{where} ORDER BY {order_column} DESC LIMIT {MAX_ROWS}",
                tuple(params),
            )
            rows = _rows(cur)

        serialized = _serialize(rows)

        return {
            "status": "success",
            "action": action,
            "count": len(serialized),
            "requests": serialized,
            "rows": serialized,
            "recent": serialized,
        }

    return handler


def _update_request(table, action, key_column, allowed_fields):
    """Builds an admin update handler for a request table."""

    def handler(payload):
        request_id = _text(payload.get("request_id") or payload.get(key_column))

        if not request_id:
            return _err(f"{key_column} is required")

        assignments, params = [], []

        for field, incoming in allowed_fields.items():
            for name in incoming:
                if name in payload and _text(payload.get(name)):
                    assignments.append(f"{field} = ?")
                    params.append(_text(payload.get(name)))
                    break

        if not assignments:
            return _err("nothing to update", request_id=request_id)

        params.append(request_id)

        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {table} WHERE {key_column} = ?", (request_id,))
            before = _rows(cur)

            if not before:
                return _err("Request not found", request_id=request_id)

            cur.execute(
                f"UPDATE {table} SET {', '.join(assignments)} WHERE {key_column} = ?",
                tuple(params),
            )

            cur.execute(f"SELECT * FROM {table} WHERE {key_column} = ?", (request_id,))
            after = _rows(cur)

        return _ok(
            "Request updated",
            action=action,
            request_id=request_id,
            before=_serialize(before)[0],
            after=_serialize(after)[0],
        )

    return handler


# =====================================================================
# Upgrades
# =====================================================================

def upgrade_request_create(payload):
    request_id = _text(payload.get("request_id")) or _new_id("UPG")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO upgrade_requests (
                request_id, client_id, partner_id, current_plan, target_plan,
                current_price, target_price, current_customer_reply_limit,
                target_customer_reply_limit, current_advisory_reply_limit,
                target_advisory_reply_limit, status, payment_status,
                stripe_checkout_session_id, stripe_subscription_id,
                customer_notes, admin_notes, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (request_id) DO NOTHING
            """,
            (
                request_id,
                _text(payload.get("client_id")),
                _partner_id(payload.get("partner_id")),
                _text(payload.get("current_plan")),
                _text(payload.get("target_plan")),
                _money(payload.get("current_price")),
                _money(payload.get("target_price")),
                _int(payload.get("current_customer_reply_limit")),
                _int(payload.get("target_customer_reply_limit")),
                _int(payload.get("current_advisory_reply_limit")),
                _int(payload.get("target_advisory_reply_limit")),
                _lower(payload.get("status")) or "pending",
                _lower(payload.get("payment_status")) or "pending",
                _text(payload.get("stripe_checkout_session_id")),
                _text(payload.get("stripe_subscription_id")),
                _text(payload.get("customer_notes")),
                _text(payload.get("admin_notes")),
                _text(payload.get("source")) or "client_dashboard",
            ),
        )

    return _ok("Upgrade request created", request_id=request_id)


def upgrade_subscription_lookup(payload):
    client_id = _text(payload.get("client_id"))
    session_id = _text(payload.get("session_id"))

    if not client_id and not session_id:
        return _err("client_id or session_id is required")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT client_id, session_id, plan_name, package_amount,
                   subscription_status, monthly_reply_limit, monthly_replies_used,
                   owner_advisory_replies_used, stripe_customer_id,
                   stripe_subscription_id, current_period_start, current_period_end
            FROM subscriptions
            WHERE (client_id = ? AND ? <> '') OR (session_id = ? AND ? <> '')
            ORDER BY updated_at DESC LIMIT 1
            """,
            (client_id, client_id, session_id, session_id),
        )
        rows = _rows(cur)

    if not rows:
        return _err("Subscription not found", client_id=client_id, session_id=session_id)

    return {
        "status": "success",
        "action": "upgrade_subscription_lookup",
        "found": True,
        "subscription": _serialize(rows)[0],
    }


def upgrade_request_mark_scheduled(payload):
    request_id = _text(payload.get("request_id"))

    if not request_id:
        return _err("request_id is required")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE upgrade_requests SET status = 'scheduled', admin_notes = ? WHERE request_id = ?",
            (_text(payload.get("admin_notes") or payload.get("notes")), request_id),
        )
        cur.execute("SELECT request_id FROM upgrade_requests WHERE request_id = ?", (request_id,))

        if not cur.fetchone():
            return _err("Request not found", request_id=request_id)

    return _ok("Upgrade request marked as scheduled", request_id=request_id)


# =====================================================================
# Cancellations
# =====================================================================

def cancellation_request_create(payload):
    request_id = _text(payload.get("request_id")) or _new_id("CAN")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cancellation_requests (
                request_id, client_id, partner_id, current_plan,
                subscription_status, stripe_customer_id, stripe_subscription_id,
                current_period_end, cancellation_reason, customer_notes,
                status, admin_decision, admin_notes, cancel_at_period_end, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (request_id) DO NOTHING
            """,
            (
                request_id,
                _text(payload.get("client_id")),
                _partner_id(payload.get("partner_id")),
                _text(payload.get("current_plan")),
                _lower(payload.get("subscription_status")),
                _text(payload.get("stripe_customer_id")),
                _text(payload.get("stripe_subscription_id")),
                _text(payload.get("current_period_end")) or None,
                _text(payload.get("cancellation_reason")),
                _text(payload.get("customer_notes")),
                _lower(payload.get("status")) or "pending",
                _text(payload.get("admin_decision")),
                _text(payload.get("admin_notes")),
                _bool(payload.get("cancel_at_period_end")),
                _text(payload.get("source")) or "client_dashboard",
            ),
        )

    return _ok("Cancellation request created", request_id=request_id)


# =====================================================================
# Website setup
# =====================================================================

def website_setup_request(payload):
    request_id = _text(payload.get("request_id")) or _new_id("WEB")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO website_setup_requests (
                request_id, client_id, partner_id, business_name, website_domain,
                setup_type, setup_status, installation_snippet, customer_notes,
                admin_notes, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (request_id) DO NOTHING
            """,
            (
                request_id,
                _text(payload.get("client_id")),
                _partner_id(payload.get("partner_id")),
                _text(payload.get("business_name")),
                _text(payload.get("website_domain")),
                _text(payload.get("setup_type")),
                _lower(payload.get("setup_status")) or "pending",
                _text(payload.get("installation_snippet")),
                _text(payload.get("customer_notes")),
                _text(payload.get("admin_notes")),
                _text(payload.get("source")) or "client_dashboard",
            ),
        )

    return _ok("Website setup request created", request_id=request_id)


def website_install_ping(payload):
    """
    Fired by widget.js on a client's site. Upserts the channel row and bumps
    the ping counter - the admin "website installations" screen reads this to
    tell installed sites from merely requested ones.
    """
    partner_id = _partner_id(payload.get("partner_id") or payload.get("client_id"))

    if not partner_id:
        return _err("client_id/partner_id is required")

    domain = _text(payload.get("domain"))

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, ping_count FROM client_website_channels WHERE partner_id = ? AND COALESCE(detected_domain,'') = ?",
            (partner_id, domain),
        )
        found = cur.fetchone()

        if found:
            cur.execute(
                """
                UPDATE client_website_channels
                SET ping_count = ping_count + 1, last_ping_at = NOW(),
                    setup_status = ?, last_user_agent = ?
                WHERE id = ?
                """,
                (_lower(payload.get("setup_status")) or "installed_detected",
                 _text(payload.get("user_agent")), found[0]),
            )
            ping_count = int(found[1] or 0) + 1
        else:
            cur.execute(
                """
                INSERT INTO client_website_channels (
                    client_id, partner_id, website_domain, detected_domain,
                    setup_status, ping_count, last_ping_at, last_user_agent
                ) VALUES (?, ?, ?, ?, ?, 1, NOW(), ?)
                """,
                (
                    _text(payload.get("client_id")) or partner_id,
                    partner_id, domain, domain,
                    _lower(payload.get("setup_status")) or "installed_detected",
                    _text(payload.get("user_agent")),
                ),
            )
            ping_count = 1

    return _ok("Website install ping recorded",
               partner_id=partner_id, domain=domain, ping_count=ping_count)


# =====================================================================
# WhatsApp
# =====================================================================

def whatsapp_setup_request(payload):
    request_id = _text(payload.get("request_id")) or _new_id("WAS")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO whatsapp_setup_requests (
                request_id, client_id, partner_id, business_name,
                whatsapp_number, setup_type, connection_status,
                preferred_language, human_handoff, customer_notes, admin_notes,
                phone_number_id, waba_id, provider
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (request_id) DO NOTHING
            """,
            (
                request_id,
                _text(payload.get("client_id")),
                _partner_id(payload.get("partner_id")),
                _text(payload.get("business_name")),
                _text(payload.get("whatsapp_number")),
                _text(payload.get("setup_type")),
                _lower(payload.get("connection_status")) or "pending",
                _text(payload.get("preferred_language")),
                _bool(payload.get("human_handoff")),
                _text(payload.get("customer_notes")),
                _text(payload.get("admin_notes")),
                _text(payload.get("phone_number_id")),
                _text(payload.get("waba_id")),
                _text(payload.get("provider")),
            ),
        )

    return _ok("WhatsApp setup request created", request_id=request_id)


def whatsapp_channel_upsert(payload):
    phone_number_id = _text(payload.get("phone_number_id"))

    if not phone_number_id:
        return _err("phone_number_id is required")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO client_channels (
                client_id, partner_id, channel, business_name, whatsapp_number,
                phone_number_id, waba_id, setup_type, connection_status,
                usage_limit, human_handoff_enabled, notes
            ) VALUES (?, ?, 'whatsapp', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            -- Partial unique index, so its predicate must be repeated here or
            -- PostgreSQL will not match it (InvalidColumnReference).
            ON CONFLICT (phone_number_id)
                WHERE phone_number_id IS NOT NULL AND phone_number_id <> ''
            DO UPDATE SET
                client_id             = COALESCE(NULLIF(EXCLUDED.client_id, ''), client_channels.client_id),
                partner_id            = COALESCE(NULLIF(EXCLUDED.partner_id, ''), client_channels.partner_id),
                business_name         = COALESCE(NULLIF(EXCLUDED.business_name, ''), client_channels.business_name),
                whatsapp_number       = COALESCE(NULLIF(EXCLUDED.whatsapp_number, ''), client_channels.whatsapp_number),
                waba_id               = COALESCE(NULLIF(EXCLUDED.waba_id, ''), client_channels.waba_id),
                connection_status     = EXCLUDED.connection_status,
                human_handoff_enabled = EXCLUDED.human_handoff_enabled
            """,
            (
                _text(payload.get("client_id")),
                _partner_id(payload.get("partner_id")),
                _text(payload.get("business_name")),
                _text(payload.get("whatsapp_number")),
                phone_number_id,
                _text(payload.get("waba_id")),
                _text(payload.get("setup_type")),
                _lower(payload.get("connection_status")) or "connected",
                _int(payload.get("usage_limit")),
                _bool(payload.get("human_handoff_enabled")),
                _text(payload.get("notes")),
            ),
        )

    return _ok("WhatsApp channel saved", phone_number_id=phone_number_id)


def whatsapp_channel_lookup(payload):
    """Runs on every inbound WhatsApp message, so it must stay a single indexed read."""
    phone_number_id = _text(payload.get("phone_number_id"))

    if not phone_number_id:
        return _err("phone_number_id is required")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT client_id, partner_id, channel, business_name, whatsapp_number,
                   connection_status, usage_limit, usage_count, human_handoff_enabled
            FROM client_channels WHERE phone_number_id = ?
            """,
            (phone_number_id,),
        )
        rows = _rows(cur)

    if not rows:
        return {"status": "success", "found": False, "phone_number_id": phone_number_id}

    row = rows[0]

    return {
        "status": "success",
        "found": True,
        "phone_number_id": phone_number_id,
        "client_id": _text(row["client_id"]),
        "partner_id": _text(row["partner_id"]),
        "channel": _text(row["channel"]),
        "business_name": _text(row["business_name"]),
        "whatsapp_number": _text(row["whatsapp_number"]),
        "connection_status": _text(row["connection_status"]),
        "usage_limit": row["usage_limit"],
        "usage_count": row["usage_count"],
        "human_handoff_enabled": "yes" if row["human_handoff_enabled"] else "no",
    }


def whatsapp_message_log(payload):
    message_id = _text(payload.get("message_id"))

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO whatsapp_messages (
                message_id, direction, client_id, partner_id, phone_number_id,
                from_number, to_number, customer_name, text, message_type,
                channel, status, raw_json, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'whatsapp', ?, ?, ?)
            ON CONFLICT (message_id)
                WHERE message_id IS NOT NULL AND message_id <> ''
            DO NOTHING
            """,
            (
                message_id or str(uuid.uuid4()),
                _lower(payload.get("direction")) or "inbound",
                _text(payload.get("client_id")),
                _partner_id(payload.get("partner_id")),
                _text(payload.get("phone_number_id")),
                _text(payload.get("from") or payload.get("from_number")),
                _text(payload.get("to") or payload.get("to_number")),
                _text(payload.get("customer_name")),
                _text(payload.get("text")),
                _text(payload.get("message_type")),
                _text(payload.get("status")),
                json.dumps(payload.get("raw_json") or {}, ensure_ascii=False, default=str),
                _text(payload.get("notes")),
            ),
        )

        if _text(payload.get("phone_number_id")):
            cur.execute(
                "UPDATE client_channels SET usage_count = usage_count + 1, last_message_at = NOW() "
                "WHERE phone_number_id = ?",
                (_text(payload.get("phone_number_id")),),
            )

    return _ok("WhatsApp message logged", message_id=message_id)


# =====================================================================
# Client dashboard content
# =====================================================================

def product_image_group(payload):
    group_id = _text(payload.get("group_id")) or _new_id("GRP")
    partner_id = _partner_id(payload.get("partner_id"))

    if not partner_id:
        return _err("partner_id is required")

    image_urls = payload.get("image_urls") or []

    if isinstance(image_urls, str):
        image_urls = [u.strip() for u in image_urls.replace("\n", ",").split(",") if u.strip()]

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO product_image_groups (
                group_id, partner_id, client_id, group_title, group_description,
                sales_instructions, product_notes, pricing_notes,
                payment_links_notes, image_urls, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (group_id) DO UPDATE SET
                group_title         = EXCLUDED.group_title,
                group_description   = EXCLUDED.group_description,
                sales_instructions  = EXCLUDED.sales_instructions,
                product_notes       = EXCLUDED.product_notes,
                pricing_notes       = EXCLUDED.pricing_notes,
                payment_links_notes = EXCLUDED.payment_links_notes,
                image_urls          = EXCLUDED.image_urls,
                status              = EXCLUDED.status,
                notes               = EXCLUDED.notes
            """,
            (
                group_id, partner_id,
                _text(payload.get("client_id")),
                _text(payload.get("group_title")),
                _text(payload.get("group_description")),
                _text(payload.get("sales_instructions")),
                _text(payload.get("product_notes")),
                _text(payload.get("pricing_notes")),
                _text(payload.get("payment_links_notes")),
                json.dumps(image_urls, ensure_ascii=False),
                _lower(payload.get("status")) or "active",
                _text(payload.get("notes")),
            ),
        )

    return _ok("Product image group saved", group_id=group_id, partner_id=partner_id,
               image_count=len(image_urls))


def client_payment_link(payload):
    payment_link_id = _text(payload.get("payment_link_id")) or _new_id("PLK")
    partner_id = _partner_id(payload.get("partner_id"))

    if not partner_id:
        return _err("partner_id is required")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO client_payment_links (
                payment_link_id, partner_id, client_id, product_name,
                payment_link, amount, currency, description,
                linked_image_group_id, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (payment_link_id) DO UPDATE SET
                product_name          = EXCLUDED.product_name,
                payment_link          = EXCLUDED.payment_link,
                amount                = EXCLUDED.amount,
                currency              = EXCLUDED.currency,
                description           = EXCLUDED.description,
                linked_image_group_id = EXCLUDED.linked_image_group_id,
                status                = EXCLUDED.status,
                notes                 = EXCLUDED.notes
            """,
            (
                payment_link_id, partner_id,
                _text(payload.get("client_id")),
                _text(payload.get("product_name")),
                _text(payload.get("payment_link")),
                _money(payload.get("amount")),
                _text(payload.get("currency")) or "AED",
                _text(payload.get("description")),
                _text(payload.get("linked_image_group_id")) or None,
                _lower(payload.get("status")) or "active",
                _text(payload.get("notes")),
            ),
        )

    return _ok("Client payment link saved",
               payment_link_id=payment_link_id, partner_id=partner_id)


# =====================================================================
# Smart link summary
# =====================================================================

def smart_link_summary_get(payload):
    """
    Counts smart-link events per type for one partner/ref. The Apps Script
    scanned the whole SmartLinkEvents sheet for every call; this is a grouped
    query over an index.
    """
    smart_ref = _text(
        payload.get("smart_ref") or payload.get("ref")
        or payload.get("partner_id") or payload.get("client_id")
    )

    if not smart_ref:
        return _err("smart_ref is required")

    partner_id = _partner_id(smart_ref) or smart_ref

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT event_type, COUNT(*) AS total
            FROM smart_link_events
            WHERE smart_ref = ? OR partner_id = ?
            GROUP BY event_type
            ORDER BY total DESC
            """,
            (smart_ref, partner_id),
        )
        counts = {_text(r["event_type"]) or "unknown": int(r["total"]) for r in _rows(cur)}

        cur.execute(
            """
            SELECT event_id, smart_ref, client_id, partner_id, event_type,
                   source, session_id, page_url, referrer_url, created_at
            FROM smart_link_events
            WHERE smart_ref = ? OR partner_id = ?
            ORDER BY created_at DESC
            LIMIT 25
            """,
            (smart_ref, partner_id),
        )
        recent = _serialize(_rows(cur))

    return {
        "status": "success",
        "action": "smart_link_summary_get",
        "smart_ref": smart_ref,
        "partner_id": partner_id,
        "total_events": sum(counts.values()),
        "event_counts": counts,
        "counts": counts,
        "recent": recent,
    }


HANDLERS = {
    # upgrades
    "upgrade_request_create": upgrade_request_create,
    "upgrade_subscription_lookup": upgrade_subscription_lookup,
    "upgrade_request_mark_scheduled": upgrade_request_mark_scheduled,
    "admin_upgrade_requests": _list_requests(
        "upgrade_requests", "admin_upgrade_requests", "request_id", status_filter="status"),
    "admin_upgrade_request_update": _update_request(
        "upgrade_requests", "admin_upgrade_request_update", "request_id",
        {"status": ("new_status", "status"),
         "payment_status": ("payment_status",),
         "admin_notes": ("admin_notes", "notes")}),

    # cancellations
    "cancellation_request_create": cancellation_request_create,
    "admin_cancellation_requests": _list_requests(
        "cancellation_requests", "admin_cancellation_requests", "request_id", status_filter="status"),
    "admin_cancellation_request_update": _update_request(
        "cancellation_requests", "admin_cancellation_request_update", "request_id",
        {"status": ("new_status", "status"),
         "admin_decision": ("admin_decision", "decision"),
         "admin_notes": ("admin_notes", "notes")}),

    # website
    "website_setup_request": website_setup_request,
    "website_install_ping": website_install_ping,
    "admin_website_setup_requests": _list_requests(
        "website_setup_requests", "admin_website_setup_requests", "request_id",
        status_filter="setup_status"),
    "admin_update_website_setup_request": _update_request(
        "website_setup_requests", "admin_update_website_setup_request", "request_id",
        {"setup_status": ("new_status", "setup_status", "status"),
         "installation_snippet": ("installation_snippet",),
         "admin_notes": ("admin_notes", "notes")}),

    # whatsapp
    "whatsapp_setup_request": whatsapp_setup_request,
    "whatsapp_channel_upsert": whatsapp_channel_upsert,
    "whatsapp_channel_lookup": whatsapp_channel_lookup,
    "whatsapp_message_log": whatsapp_message_log,
    "admin_whatsapp_setup_requests": _list_requests(
        "whatsapp_setup_requests", "admin_whatsapp_setup_requests", "request_id",
        status_filter="connection_status"),
    "admin_update_whatsapp_setup_request": _update_request(
        "whatsapp_setup_requests", "admin_update_whatsapp_setup_request", "request_id",
        {"connection_status": ("new_status", "connection_status", "status"),
         "phone_number_id": ("phone_number_id",),
         "waba_id": ("waba_id",),
         "admin_notes": ("admin_notes", "notes")}),

    # client dashboard content
    "product_image_group": product_image_group,
    "client_payment_link": client_payment_link,

    # smart links
    "smart_link_summary_get": smart_link_summary_get,
}
