# cancellation_flow.py
#
# The cancellation path, rebuilt so that approving a request actually cancels
# something.
#
# ---------------------------------------------------------------------
# How it used to work
# ---------------------------------------------------------------------
#   client presses "cancel"  -> a row is written to cancellation_requests
#                               and nothing else. Stripe never hears about it,
#                               the subscription stays active, the bot keeps
#                               running, and the customer is charged again.
#   admin presses "approve"  -> the status field on that row changes.
#                               Still nothing is cancelled.
#   only "schedule at period end" ever reached Stripe, and it stored the
#   result as free text inside admin_notes.
#
# ---------------------------------------------------------------------
# How it works now
# ---------------------------------------------------------------------
#   client presses "cancel"  -> request row + cancel_requested_at stamped on
#                               the subscription, so the intent is visible
#                               everywhere. The subscription is NOT touched
#                               otherwise: the admin decides.
#   admin presses "approve"  -> approve_cancellation() below:
#                                 1. Stripe cancel_at_period_end = True
#                                 2. subscription rows record the end date
#                                 3. request row marked approved
#                                 4. audit log
#                               all inside one database transaction.
#
# Cancellation is always END OF PERIOD. The customer paid for the month and
# keeps the service until it expires; can_client_use_bot() stops the bot once
# cancel_effective_at passes.

import os
import uuid
from datetime import datetime, timedelta

SCHEDULED_STATUS = "approved_period_end"


def _conn():
    from db import get_connection
    return get_connection()


def _text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()


def _lower(value):
    return _text(value).lower()


def _rows(cur):
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _ok(message, **fields):
    result = {"status": "success", "message": message}
    result.update(fields)
    return result


def _err(message, **fields):
    result = {"status": "error", "message": message}
    result.update(fields)
    return result


def _find_subscription(cur, client_id, stripe_subscription_id):
    if stripe_subscription_id:
        cur.execute(
            "SELECT * FROM subscriptions WHERE stripe_subscription_id = ? LIMIT 1",
            (stripe_subscription_id,),
        )
        found = _rows(cur)
        if found:
            return found[0]

    if client_id:
        cur.execute(
            "SELECT * FROM subscriptions WHERE client_id = ? OR session_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (client_id, client_id),
        )
        found = _rows(cur)
        if found:
            return found[0]

    return None


def _stripe_cancel_at_period_end(stripe_subscription_id):
    """
    Ask Stripe to stop renewing at the end of the paid period.

    Returns (ok, effective_at, detail). A failure here must abort the whole
    approval: marking the request approved while Stripe keeps billing is the
    exact problem this module exists to fix.
    """
    secret = (
        os.getenv("STRIPE_SECRET_KEY")
        or os.getenv("STRIPE_API_KEY")
        or os.getenv("STRIPE_KEY")
        or ""
    ).strip()

    if not secret:
        return False, None, "STRIPE_SECRET_KEY is not set"

    try:
        import stripe
    except ImportError:
        return False, None, "the stripe package is not installed"

    try:
        stripe.api_key = secret
        subscription = stripe.Subscription.modify(
            stripe_subscription_id, cancel_at_period_end=True
        )

        period_end = subscription.get("current_period_end")
        effective_at = datetime.utcfromtimestamp(int(period_end)) if period_end else None

        return True, effective_at, "scheduled with stripe"

    except Exception as error:
        return False, None, f"{type(error).__name__}: {error}"


def request_cancellation(payload):
    """
    Client-initiated request. Creates the ticket AND stamps the intent on the
    subscription so the admin, the client dashboard and the partner dashboard
    all show that a cancellation is pending.
    """
    request_id = _text(payload.get("request_id")) or f"CAN-{uuid.uuid4()}"
    client_id = _text(payload.get("client_id"))
    reason = _text(payload.get("cancellation_reason"))

    if not client_id:
        return _err("client_id is required")

    with _conn() as conn:
        cur = conn.cursor()

        subscription = _find_subscription(
            cur, client_id, _text(payload.get("stripe_subscription_id"))
        )

        cur.execute(
            """
            INSERT INTO cancellation_requests (
                request_id, client_id, partner_id, current_plan,
                subscription_status, stripe_customer_id, stripe_subscription_id,
                current_period_end, cancellation_reason, customer_notes,
                status, cancel_at_period_end, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', TRUE, ?)
            ON CONFLICT (request_id) DO NOTHING
            """,
            (
                request_id,
                client_id,
                _text(payload.get("partner_id")),
                _text(payload.get("current_plan")) or (subscription or {}).get("plan_name") or "",
                (subscription or {}).get("subscription_status") or "",
                _text(payload.get("stripe_customer_id")) or (subscription or {}).get("stripe_customer_id") or "",
                _text(payload.get("stripe_subscription_id")) or (subscription or {}).get("stripe_subscription_id") or "",
                (subscription or {}).get("current_period_end") or (subscription or {}).get("billing_cycle_end"),
                reason,
                _text(payload.get("customer_notes")),
                _text(payload.get("source")) or "client_dashboard",
            ),
        )

        if subscription:
            cur.execute(
                "UPDATE subscriptions SET cancel_requested_at = NOW(), cancel_reason = ? WHERE id = ?",
                (reason, subscription["id"]),
            )

    return _ok(
        "Cancellation request received",
        request_id=request_id,
        client_id=client_id,
        subscription_found=bool(subscription),
        note="Awaiting admin approval. The subscription is still active.",
    )


def approve_cancellation(payload):
    """
    Admin approval — this is the step that actually cancels.

    Order matters: Stripe is called FIRST and the database is only updated if
    Stripe accepted. The reverse order could leave the app believing a
    subscription was cancelled while Stripe carries on charging the customer.
    """
    request_id = _text(payload.get("request_id"))

    if not request_id:
        return _err("request_id is required")

    with _conn() as conn:
        cur = conn.cursor()

        cur.execute("SELECT * FROM cancellation_requests WHERE request_id = ?", (request_id,))
        found = _rows(cur)

        if not found:
            return _err("Cancellation request not found", request_id=request_id)

        cancellation_request = found[0]
        client_id = _text(cancellation_request.get("client_id"))
        stripe_subscription_id = _text(cancellation_request.get("stripe_subscription_id"))

        subscription = _find_subscription(cur, client_id, stripe_subscription_id)

        if not subscription:
            return _err(
                "No subscription found for this request",
                request_id=request_id,
                client_id=client_id,
            )

        stripe_subscription_id = stripe_subscription_id or _text(
            subscription.get("stripe_subscription_id")
        )

        # 1. Stripe first.
        if stripe_subscription_id:
            ok, effective_at, detail = _stripe_cancel_at_period_end(stripe_subscription_id)

            if not ok:
                return _err(
                    f"Stripe refused the cancellation, nothing was changed: {detail}",
                    request_id=request_id,
                    stripe_subscription_id=stripe_subscription_id,
                )
        else:
            # A manual subscription has no Stripe object. It still ends at the
            # close of the period it was paid for.
            effective_at = (
                subscription.get("current_period_end")
                or subscription.get("billing_cycle_end")
                or (datetime.utcnow() + timedelta(days=30))
            )
            detail = "no stripe subscription; scheduled internally"

        if isinstance(effective_at, str):
            from database import parse_timestamp
            effective_at = parse_timestamp(effective_at)

        if not effective_at:
            effective_at = datetime.utcnow() + timedelta(days=30)

        # 2. Record the end date on the subscription.
        cur.execute(
            """
            UPDATE subscriptions
            SET cancel_at_period_end = TRUE,
                cancel_effective_at  = ?,
                cancel_reason        = COALESCE(NULLIF(?, ''), cancel_reason),
                notes                = CONCAT(COALESCE(notes, ''),
                                              '; cancellation approved by admin, ends ',
                                              ?::TEXT)
            WHERE id = ?
            """,
            (
                effective_at,
                _text(payload.get("reason")) or _text(cancellation_request.get("cancellation_reason")),
                effective_at.strftime("%Y-%m-%d"),
                subscription["id"],
            ),
        )

        # 3. Close the request.
        cur.execute(
            """
            UPDATE cancellation_requests
            SET status               = ?,
                admin_decision       = 'approved',
                cancel_at_period_end = TRUE,
                current_period_end   = ?,
                admin_notes          = ?
            WHERE request_id = ?
            """,
            (
                SCHEDULED_STATUS,
                effective_at,
                f"Approved by {_text(payload.get('actor')) or 'owner_admin'}; {detail}; "
                f"service ends {effective_at.strftime('%Y-%m-%d')}",
                request_id,
            ),
        )

        # 4. Audit.
        cur.execute(
            """
            INSERT INTO audit_logs (
                audit_id, actor, action, target_type, target_id, partner_id,
                before_json, after_json, reason, source, status, notes
            ) VALUES (?, ?, 'approve_cancellation', 'subscription', ?, ?, ?, ?, ?, ?, 'success', ?)
            """,
            (
                str(uuid.uuid4()),
                _text(payload.get("actor")) or "owner_admin",
                _text(subscription.get("session_id")) or client_id,
                _text(cancellation_request.get("partner_id")),
                '{"cancel_at_period_end": false}',
                '{"cancel_at_period_end": true}',
                _text(payload.get("reason")),
                _text(payload.get("source")) or "admin_dashboard",
                f"Cancellation approved; {detail}",
            ),
        )

    return _ok(
        "Cancellation approved and scheduled",
        request_id=request_id,
        client_id=client_id,
        stripe_subscription_id=stripe_subscription_id,
        cancel_at_period_end=True,
        cancel_effective_at=effective_at.strftime("%Y-%m-%d %H:%M:%S"),
        service_ends_on=effective_at.strftime("%Y-%m-%d"),
        detail=detail,
    )


def reject_cancellation(payload):
    """Admin rejection — clears the pending flag so the badge disappears."""
    request_id = _text(payload.get("request_id"))

    if not request_id:
        return _err("request_id is required")

    with _conn() as conn:
        cur = conn.cursor()

        cur.execute("SELECT * FROM cancellation_requests WHERE request_id = ?", (request_id,))
        found = _rows(cur)

        if not found:
            return _err("Cancellation request not found", request_id=request_id)

        cancellation_request = found[0]
        subscription = _find_subscription(
            cur,
            _text(cancellation_request.get("client_id")),
            _text(cancellation_request.get("stripe_subscription_id")),
        )

        if subscription:
            cur.execute(
                "UPDATE subscriptions SET cancel_requested_at = NULL, cancel_reason = NULL WHERE id = ?",
                (subscription["id"],),
            )

        cur.execute(
            """
            UPDATE cancellation_requests
            SET status = 'rejected', admin_decision = 'rejected',
                cancel_at_period_end = FALSE, admin_notes = ?
            WHERE request_id = ?
            """,
            (_text(payload.get("admin_notes")) or _text(payload.get("reason")), request_id),
        )

    return _ok("Cancellation request rejected", request_id=request_id)


def admin_cancellation_request_update(payload):
    """
    Kept as the single entry point the admin dashboard already posts to, but
    it now routes a decision to the handler that performs it instead of only
    rewriting a status column.
    """
    decision = _lower(payload.get("admin_decision") or payload.get("status"))

    if decision in ("approved", "approve", SCHEDULED_STATUS):
        return approve_cancellation(payload)

    if decision in ("rejected", "reject"):
        return reject_cancellation(payload)

    request_id = _text(payload.get("request_id"))

    if not request_id:
        return _err("request_id is required")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cancellation_requests SET status = COALESCE(NULLIF(?, ''), status), "
            "admin_notes = COALESCE(NULLIF(?, ''), admin_notes) WHERE request_id = ?",
            (_lower(payload.get("status")), _text(payload.get("admin_notes")), request_id),
        )

    return _ok("Cancellation request updated", request_id=request_id, decision=decision or "none")


HANDLERS = {
    "cancellation_request_create": request_cancellation,
    "admin_cancellation_request_update": admin_cancellation_request_update,
    "admin_cancellation_approve": approve_cancellation,
    "admin_cancellation_reject": reject_cancellation,
}
