# admin_compat.py
#
# PostgreSQL versions of the admin actions that move money or restructure the
# network. Ported from the LIVE Apps Script definitions:
#
#   updateCommissionStatusAdmin              line 6549
#   updateCommissionStatusBulkAdmin          line 6846
#   autoApprovePendingCommissionsAdmin       line 9042
#   markPartnerApprovedCommissionsPaidAdmin  line 9988
#   getAdminPartnerPayoutHistory             line 10389
#   getAdminPartnerLookup                    line 6179
#   updatePartnerStatusAdmin                 line 7321
#   getAdminDownlineTransferPreview          line 7654
#   executeAdminTransferDownlineToAlsaab     line 8167
#
# Every one of these ran as a read-modify-write loop over a Google Sheet with
# no transaction. Here each is a single transaction: a payout run either
# marks every commission paid AND writes the payout history row, or it does
# neither. That was not possible before.

import json
import uuid
from datetime import datetime

# updateCommissionStatusAdmin accepts all five; the bulk variant refuses
# "pending" so a bulk action can never silently un-approve work.
SINGLE_ALLOWED_STATUSES = ("pending", "approved", "hold", "rejected", "paid")
BULK_ALLOWED_STATUSES = ("approved", "hold", "rejected", "paid")

MAX_ROWS = 25


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
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        import re
        cleaned = re.sub(r"[^\d.\-]", "", str(value))
        return float(cleaned) if cleaned else 0.0


def _now_iso():
    return datetime.utcnow().isoformat()


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


def _append_note(existing, new_status, reason):
    """Reproduces the "; "-joined note the Apps Script appended."""
    parts = [
        _text(existing),
        f"admin_status_update={new_status}",
        f"reason={reason}" if _text(reason) else "",
        f"updated_at={_now_iso()}",
    ]
    return "; ".join(p for p in parts if _text(p))


def _audit(cur, actor, action, target_type, target_id, partner_id,
           before, after, reason, source, notes):
    cur.execute(
        """
        INSERT INTO audit_logs (
            audit_id, actor, action, target_type, target_id, partner_id,
            before_json, after_json, reason, source, status, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', ?)
        """,
        (
            str(uuid.uuid4()),
            _text(actor) or "owner_admin",
            action,
            target_type,
            _text(target_id),
            _partner_id(partner_id),
            json.dumps(before, ensure_ascii=False, default=str),
            json.dumps(after, ensure_ascii=False, default=str),
            _text(reason),
            _text(source) or "admin_dashboard",
            notes,
        ),
    )


def _commission_row(cur, commission_id):
    cur.execute(
        """
        SELECT commission_id, beneficiary_partner_id, status, commission_amount,
               paid_date, notes
        FROM commissions WHERE commission_id = ?
        """,
        (commission_id,),
    )
    found = _rows(cur)
    return found[0] if found else None


# =====================================================================
# Single commission status update
# =====================================================================

def admin_update_commission_status(payload):
    new_status = _lower(payload.get("new_status") or payload.get("status"))

    if new_status not in SINGLE_ALLOWED_STATUSES:
        return _err("Invalid commission status", allowed_statuses=list(SINGLE_ALLOWED_STATUSES))

    commission_id = _text(payload.get("commission_id"))
    unique_key = _text(payload.get("commission_unique_key"))

    if not commission_id and not unique_key:
        return _err("commission_id or commission_unique_key is required")

    with _conn() as conn:
        cur = conn.cursor()

        if commission_id:
            before = _commission_row(cur, commission_id)
            match_by = "commission_id"
        else:
            cur.execute(
                """
                SELECT commission_id, beneficiary_partner_id, status,
                       commission_amount, paid_date, notes
                FROM commissions WHERE commission_unique_key = ?
                """,
                (unique_key,),
            )
            found = _rows(cur)
            before = found[0] if found else None
            match_by = "commission_unique_key"

        if not before:
            return _err(
                "Commission not found",
                commission_id=commission_id,
                commission_unique_key=unique_key,
            )

        commission_id = before["commission_id"]
        note = _append_note(before["notes"], new_status, payload.get("admin_note") or payload.get("reason"))

        cur.execute(
            """
            UPDATE commissions
            SET status = ?,
                paid_date = CASE WHEN ? = 'paid' THEN COALESCE(?, NOW()) ELSE paid_date END,
                notes = ?
            WHERE commission_id = ?
            """,
            (
                new_status,
                new_status,
                _text(payload.get("paid_date")) or None,
                note,
                commission_id,
            ),
        )

        after = _commission_row(cur, commission_id)

        _audit(
            cur, payload.get("actor"), "update_commission_status", "commission",
            commission_id, before["beneficiary_partner_id"], before, after,
            payload.get("reason"), payload.get("source"),
            f"Commission status updated by admin to {new_status}",
        )

    return _ok(
        "Commission status updated",
        match_by=match_by,
        commission_id=commission_id,
        beneficiary_partner_id=_text(before["beneficiary_partner_id"]),
        old_status=_text(before["status"]),
        new_status=new_status,
    )


# =====================================================================
# Bulk commission status update
# =====================================================================

def admin_bulk_update_commission_status(payload):
    new_status = _lower(payload.get("new_status") or payload.get("status"))

    if new_status not in BULK_ALLOWED_STATUSES:
        return _err("Invalid commission status", allowed_statuses=list(BULK_ALLOWED_STATUSES))

    raw_ids = payload.get("commission_ids") or payload.get("ids") or ""

    if isinstance(raw_ids, str):
        ids = [i.strip() for i in raw_ids.replace("\n", ",").split(",") if i.strip()]
    else:
        ids = [_text(i) for i in raw_ids if _text(i)]

    if not ids:
        return _err("commission_ids is required")

    updated, skipped = [], []

    with _conn() as conn:
        cur = conn.cursor()

        for commission_id in ids:
            before = _commission_row(cur, commission_id)

            if not before:
                skipped.append({"commission_id": commission_id, "reason": "not_found"})
                continue

            note = _append_note(before["notes"], new_status, payload.get("reason"))

            cur.execute(
                """
                UPDATE commissions
                SET status = ?,
                    paid_date = CASE WHEN ? = 'paid' THEN COALESCE(paid_date, NOW()) ELSE paid_date END,
                    notes = ?
                WHERE commission_id = ?
                """,
                (new_status, new_status, note, commission_id),
            )

            updated.append({
                "commission_id": commission_id,
                "old_status": _text(before["status"]),
                "new_status": new_status,
                "beneficiary_partner_id": _text(before["beneficiary_partner_id"]),
            })

        _audit(
            cur, payload.get("actor"), "bulk_update_commission_status", "commission",
            ",".join(ids)[:200], payload.get("partner_id"),
            {"requested": ids}, {"updated": updated, "skipped": skipped},
            payload.get("reason"), payload.get("source"),
            f"{len(updated)} commissions set to {new_status}",
        )

    return _ok(
        f"{len(updated)} commission(s) updated",
        new_status=new_status,
        updated_count=len(updated),
        skipped_count=len(skipped),
        updated=updated,
        skipped=skipped,
    )


# =====================================================================
# Auto-approve pending
# =====================================================================

def admin_auto_approve_pending_commissions(payload):
    partner_id = _partner_id(payload.get("partner_id"))
    reason = _text(payload.get("reason")) or "Auto approve pending commissions by owner admin"

    with _conn() as conn:
        cur = conn.cursor()

        if partner_id:
            cur.execute(
                "SELECT commission_id, beneficiary_partner_id, commission_amount, notes "
                "FROM commissions WHERE status = 'pending' AND beneficiary_partner_id = ?",
                (partner_id,),
            )
        else:
            cur.execute(
                "SELECT commission_id, beneficiary_partner_id, commission_amount, notes "
                "FROM commissions WHERE status = 'pending'"
            )

        pending = _rows(cur)
        approved_ids = []

        for row in pending:
            cur.execute(
                "UPDATE commissions SET status = 'approved', notes = ? WHERE commission_id = ?",
                (_append_note(row["notes"], "approved", reason), row["commission_id"]),
            )
            approved_ids.append(row["commission_id"])

        _audit(
            cur, payload.get("actor"), "auto_approve_pending_commissions", "commission",
            partner_id or "ALL", partner_id,
            {"pending_count": len(pending)}, {"approved_ids": approved_ids},
            reason, payload.get("source"),
            f"{len(approved_ids)} pending commissions approved",
        )

    return _ok(
        f"{len(approved_ids)} pending commission(s) approved",
        partner_id=partner_id,
        approved_count=len(approved_ids),
        commission_ids=approved_ids,
    )


# =====================================================================
# Mark a partner's approved commissions as paid
# =====================================================================

def admin_mark_partner_approved_commissions_paid(payload):
    """
    The Apps Script updated each commission row, then appended a PayoutHistory
    row at the end. If it failed partway the commissions were marked paid with
    no payout record. Here both happen in one transaction or neither does.
    """
    partner_id = _partner_id(payload.get("partner_id"))

    if not partner_id:
        return _err("partner_id is required")

    reason = _text(payload.get("reason")) or (
        "Owner manually transferred payout and marked approved commissions as paid"
    )
    payment_method = _text(payload.get("payment_method")) or "manual_transfer"

    with _conn() as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT commission_id, commission_amount, notes FROM commissions "
            "WHERE beneficiary_partner_id = ? AND status = 'approved'",
            (partner_id,),
        )
        approved = _rows(cur)

        if not approved:
            return _ok(
                "No approved commissions to pay",
                partner_id=partner_id,
                commission_count=0,
                total_amount=0,
            )

        commission_ids = []
        total_amount = 0.0

        for row in approved:
            cur.execute(
                "UPDATE commissions SET status = 'paid', paid_date = NOW(), notes = ? "
                "WHERE commission_id = ?",
                (_append_note(row["notes"], "paid", reason), row["commission_id"]),
            )
            commission_ids.append(row["commission_id"])
            total_amount += _money(row["commission_amount"])

        cur.execute("SELECT partner_name FROM partners WHERE partner_id = ?", (partner_id,))
        found = cur.fetchone()
        partner_name = _text(found[0]) if found else ""

        payout_id = "PAY-" + str(uuid.uuid4())

        cur.execute(
            """
            INSERT INTO payout_history (
                payout_id, partner_id, partner_name, commission_count,
                commission_ids, total_amount, currency, payment_method,
                status, paid_date, actor, reason, source, notes
            ) VALUES (?, ?, ?, ?, ?, ?, 'AED', ?, 'paid', NOW(), ?, ?, ?, ?)
            """,
            (
                payout_id, partner_id, partner_name, len(commission_ids),
                ",".join(commission_ids), round(total_amount, 2), payment_method,
                _text(payload.get("actor")) or "owner_admin", reason,
                _text(payload.get("source")) or "admin_dashboard",
                f"{len(commission_ids)} commissions paid in one payout",
            ),
        )

        _audit(
            cur, payload.get("actor"), "mark_approved_commissions_paid", "partner",
            partner_id, partner_id,
            {"approved_count": len(approved)},
            {"payout_id": payout_id, "total_amount": total_amount},
            reason, payload.get("source"),
            f"Payout {payout_id} for {len(commission_ids)} commissions",
        )

    return _ok(
        f"{len(commission_ids)} commission(s) marked as paid",
        partner_id=partner_id,
        partner_name=partner_name,
        payout_id=payout_id,
        commission_count=len(commission_ids),
        commission_ids=commission_ids,
        total_amount=round(total_amount, 2),
        payment_method=payment_method,
    )


# =====================================================================
# Payout history
# =====================================================================

def admin_partner_payout_history(payload):
    partner_id = _partner_id(payload.get("partner_id"))

    if not partner_id:
        return _err("partner_id is required")

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT payout_id, partner_id, partner_name, commission_count,
                   commission_ids, total_amount, currency, payment_method,
                   status, paid_date, actor, reason, source, notes, created_at
            FROM payout_history
            WHERE partner_id = ?
            ORDER BY paid_date DESC NULLS LAST, created_at DESC
            """,
            (partner_id,),
        )
        rows = _rows(cur)

    recent = []
    total_paid = 0.0
    total_commissions_paid = 0
    last_paid_date = ""

    for index, row in enumerate(rows, start=1):
        total_paid += _money(row["total_amount"])
        total_commissions_paid += int(row["commission_count"] or 0)

        if not last_paid_date:
            last_paid_date = _text(row["paid_date"])

        if len(recent) < MAX_ROWS:
            recent.append({
                "row_number": index,
                "date": _text(row["created_at"]),
                "payout_id": _text(row["payout_id"]),
                "partner_id": _text(row["partner_id"]),
                "partner_name": _text(row["partner_name"]),
                "commission_count": int(row["commission_count"] or 0),
                "commission_ids": _text(row["commission_ids"]),
                "total_amount": _money(row["total_amount"]),
                "currency": _text(row["currency"]),
                "payment_method": _text(row["payment_method"]),
                "status": _text(row["status"]),
                "paid_date": _text(row["paid_date"]),
                "actor": _text(row["actor"]),
                "reason": _text(row["reason"]),
                "source": _text(row["source"]),
                "notes": _text(row["notes"]),
            })

    return {
        "status": "success",
        "action": "admin_partner_payout_history",
        "partner_id": partner_id,
        "summary": {
            "payout_count": len(rows),
            "total_paid": round(total_paid, 2),
            "total_commissions_paid": total_commissions_paid,
            "last_paid_date": last_paid_date,
        },
        "recent": recent,
    }


# =====================================================================
# Partner lookup
# =====================================================================

def admin_partner_lookup(payload):
    query = _text(payload.get("query") or payload.get("q") or payload.get("search"))

    if not query:
        return _err("query is required")

    like = f"%{query.lower()}%"

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT partner_id, client_id, partner_name, phone, email, country,
                   partner_rank, status, sponsor_partner_id, referral_link,
                   active_direct_customers, active_network_customers, created_at
            FROM partners
            WHERE LOWER(partner_id)   LIKE ?
               OR LOWER(partner_name) LIKE ?
               OR LOWER(COALESCE(email, '')) LIKE ?
               OR COALESCE(phone, '')  LIKE ?
               OR LOWER(COALESCE(client_id, '')) LIKE ?
            ORDER BY partner_id
            LIMIT 50
            """,
            (like, like, like, f"%{query}%", like),
        )
        rows = _rows(cur)

    results = []

    for index, row in enumerate(rows, start=1):
        results.append({
            "row_number": index,
            "partner_id": _text(row["partner_id"]),
            "client_id": _text(row["client_id"]),
            "partner_name": _text(row["partner_name"]),
            "phone": _text(row["phone"]),
            "email": _text(row["email"]),
            "country": _text(row["country"]),
            "partner_rank": _text(row["partner_rank"]),
            "status": _text(row["status"]),
            "sponsor_partner_id": _text(row["sponsor_partner_id"]),
            "referral_link": _text(row["referral_link"]),
            "active_direct_customers": row["active_direct_customers"],
            "active_network_customers": row["active_network_customers"],
            "date": _text(row["created_at"]),
        })

    # main.py reads a top-level "partner_id" off this response and uses it to
    # pull the full profile; without it the admin search reports "no partner
    # found" even when results came back. Apps Script returned the single best
    # match, so pick one the same way: an exact partner_id wins over a partial
    # hit on client_id/name/phone, which is what makes searching for
    # "ALS-P00006" land on ALS-P00006 rather than on ALS-P00009, whose
    # client_id happens to contain its sponsor's id.
    best = ""
    wanted = query.strip().lower()

    for row in results:
        if _text(row["partner_id"]).lower() == wanted:
            best = _text(row["partner_id"])
            break

    if not best and results:
        best = _text(results[0]["partner_id"])

    return {
        "status": "success",
        "action": "admin_partner_lookup",
        "query": query,
        "found": bool(best),
        "partner_id": best,
        "count": len(results),
        "results": results,
        "partners": results,
    }


# =====================================================================
# Partner status
# =====================================================================

def admin_update_partner_status(payload):
    partner_id = _partner_id(payload.get("partner_id"))
    new_status = _lower(payload.get("new_status") or payload.get("status"))

    if not partner_id:
        return _err("partner_id is required")

    if new_status not in ("active", "inactive", "suspended", "approved"):
        return _err(
            "Invalid partner status",
            allowed_statuses=["active", "inactive", "suspended", "approved"],
        )

    with _conn() as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT partner_id, partner_name, status, notes FROM partners WHERE partner_id = ?",
            (partner_id,),
        )
        found = _rows(cur)

        if not found:
            return _err("Partner not found", partner_id=partner_id)

        before = found[0]
        reason = _text(payload.get("reason"))
        note = "; ".join(p for p in [
            _text(before["notes"]),
            f"admin_status_update={new_status}",
            f"reason={reason}" if reason else "",
            f"updated_at={_now_iso()}",
        ] if p)

        cur.execute(
            "UPDATE partners SET status = ?, notes = ? WHERE partner_id = ?",
            (new_status, note, partner_id),
        )

        # A suspended partner must stop earning immediately; the Apps Script
        # mirrored the status into MLMLevels for exactly this reason.
        cur.execute(
            """
            UPDATE partner_levels
            SET level_status = ?,
                commission_eligible = CASE WHEN ? IN ('active', 'approved')
                                           THEN commission_eligible ELSE FALSE END
            WHERE partner_id = ?
            """,
            (new_status, new_status, partner_id),
        )

        _audit(
            cur, payload.get("actor"), "update_partner_status", "partner",
            partner_id, partner_id, before, {"status": new_status},
            reason, payload.get("source"),
            f"Partner status changed to {new_status}",
        )

    return _ok(
        "Partner status updated",
        partner_id=partner_id,
        old_status=_text(before["status"]),
        new_status=new_status,
    )


# =====================================================================
# Downline transfer to the company root
# =====================================================================

def _downline_snapshot(cur, partner_id):
    cur.execute(
        """
        SELECT p.partner_id, p.partner_name, p.status, p.partner_rank,
               d.depth,
               CASE
                   WHEN d.depth = 1 THEN p.partner_id
                   ELSE (
                       SELECT o.root_partner_id
                         FROM partner_downline o
                        WHERE o.descendant_partner_id = d.descendant_partner_id
                          AND o.root_partner_id IN (
                                SELECT c.descendant_partner_id
                                  FROM partner_downline c
                                 WHERE c.root_partner_id = ? AND c.depth = 1)
                        LIMIT 1)
               END AS line_owner_partner_id
        FROM partner_downline d
        JOIN partners p ON p.partner_id = d.descendant_partner_id
        WHERE d.root_partner_id = ?
        ORDER BY d.depth, p.partner_id
        """,
        (partner_id, partner_id),
    )
    return _rows(cur)


def admin_downline_transfer_preview(payload):
    partner_id = _partner_id(payload.get("partner_id"))

    if not partner_id:
        return _err("partner_id is required")

    with _conn() as conn:
        cur = conn.cursor()

        cur.execute("SELECT partner_name, status, partner_rank FROM partners WHERE partner_id = ?", (partner_id,))
        found = _rows(cur)

        if not found:
            return _err("Partner not found", partner_id=partner_id)

        cur.execute(
            "SELECT partner_id, partner_name, status FROM partners WHERE sponsor_partner_id = ? ORDER BY partner_id",
            (partner_id,),
        )
        direct = _rows(cur)

        downline = _downline_snapshot(cur, partner_id)

    depth_counts = {str(d): 0 for d in range(1, 6)}

    for row in downline:
        key = str(int(row["depth"]))
        if key in depth_counts:
            depth_counts[key] += 1

    return {
        "status": "success",
        "action": "admin_downline_transfer_preview",
        "partner_id": partner_id,
        "partner_name": _text(found[0]["partner_name"]),
        # main.py/downline_transfer_preview.html read "target_partner" and
        # "network_rows"; the port exposed the same data as top-level fields and
        # a "downline" list, so the header showed "-" and the network table
        # rendered empty. Both shapes are returned now.
        "target_partner": {
            "partner_id": partner_id,
            "partner_name": _text(found[0]["partner_name"]),
            "status": _text(found[0]["status"]),
            "partner_rank": _text(found[0]["partner_rank"]),
        },
        "network_rows": [
            {
                "descendant_partner_id": _text(r["partner_id"]),
                "depth": int(r["depth"]),
                "line_owner_partner_id": _text(r["line_owner_partner_id"]),
                "partner_name": _text(r["partner_name"]),
                "status": _text(r["status"]),
                "partner_rank": _text(r["partner_rank"]),
            }
            for r in downline
        ],
        "direct_children_count": len(direct),
        "downline_count": len(downline),
        "depth_counts": depth_counts,
        "direct_children": [
            {
                "partner_id": _text(r["partner_id"]),
                "partner_name": _text(r["partner_name"]),
                "status": _text(r["status"]),
            }
            for r in direct
        ],
        "downline": [
            {
                "partner_id": _text(r["partner_id"]),
                "partner_name": _text(r["partner_name"]),
                "depth": int(r["depth"]),
                "status": _text(r["status"]),
            }
            for r in downline[:100]
        ],
        "note": (
            "Executing will re-parent the direct children to the company root. "
            "Deeper levels stay attached to their own sponsors and simply move up with them."
        ),
    }


def admin_transfer_downline_to_alsaab(payload):
    from sheet_compat import COMPANY_OWNER_PARTNER_ID

    partner_id = _partner_id(payload.get("partner_id"))

    if not partner_id:
        return _err("partner_id is required")

    if partner_id.lower() == COMPANY_OWNER_PARTNER_ID.lower():
        return _err("Cannot transfer the company root to itself")

    with _conn() as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT partner_id, partner_name FROM partners WHERE sponsor_partner_id = ?",
            (partner_id,),
        )
        direct = _rows(cur)

        if not direct:
            return _ok("Partner has no direct children to transfer",
                       partner_id=partner_id, transferred_count=0)

        moved = []

        for row in direct:
            cur.execute(
                """
                UPDATE partners
                SET sponsor_partner_id = ?, parent_partner_id = ?, invited_by = ?
                WHERE partner_id = ?
                """,
                (COMPANY_OWNER_PARTNER_ID, COMPANY_OWNER_PARTNER_ID,
                 COMPANY_OWNER_PARTNER_ID, row["partner_id"]),
            )
            moved.append(_text(row["partner_id"]))

        # partner_tree is a cache of the sponsor chain, so rebuild it from the
        # authoritative column. The recursive view already reflects the change
        # without this, but the dashboards still read the table.
        cur.execute("DELETE FROM partner_tree")
        cur.execute(
            """
            INSERT INTO partner_tree (ancestor_partner_id, descendant_partner_id, depth, line_owner_partner_id)
            SELECT u.ancestor_partner_id, u.root_partner_id, u.depth, p.sponsor_partner_id
            FROM partner_upline u
            JOIN partners p ON p.partner_id = u.root_partner_id
            WHERE u.depth BETWEEN 1 AND 5
            ON CONFLICT (ancestor_partner_id, descendant_partner_id, depth) DO NOTHING
            """
        )
        cur.execute("SELECT COUNT(*) FROM partner_tree")
        rebuilt = cur.fetchone()[0]

        _audit(
            cur, payload.get("actor"), "transfer_downline_to_alsaab", "partner",
            partner_id, partner_id, {"direct_children": moved}, {"moved_to": COMPANY_OWNER_PARTNER_ID},
            payload.get("reason"), payload.get("source"),
            f"{len(moved)} direct children re-parented to {COMPANY_OWNER_PARTNER_ID}",
        )

    return _ok(
        f"{len(moved)} direct partner(s) transferred",
        partner_id=partner_id,
        transferred_count=len(moved),
        transferred_partner_ids=moved,
        new_sponsor=COMPANY_OWNER_PARTNER_ID,
        partner_tree_rows_rebuilt=rebuilt,
    )


# =====================================================================
# Recalculate every partner level
# =====================================================================

def admin_recalculate_all_levels(payload):
    """
    Rebuild partner_levels for every partner from the live data.

    Levels are normally refreshed as a side effect of a payment arriving. That
    leaves the stored values stale whenever anything else changes the inputs —
    a customer cancelling, a package being upgraded, or the level rules
    themselves being corrected.

    The gap is not cosmetic: the dashboards read the stored value while the
    payout engine recomputes from scratch, so partners were being shown
    "eligible" for a commission the engine would then refuse (and, in one
    case, the reverse). This handler forces the two back into agreement
    without waiting for a payment.
    """
    from sheet_compat import _calculate_partner_level_progress, _sync_partner_level

    changed, unchanged, failed = [], 0, []

    with _conn() as conn:
        cur = conn.cursor()

        # Skip the company root: it is a structural row, holds no subscription
        # and can never earn a commission, so recalculating it is meaningless
        # and it made the summary say "out of 18" where the dashboard shows 17.
        from sheet_compat import COMPANY_OWNER_PARTNER_ID

        cur.execute(
            "SELECT partner_id FROM partners WHERE LOWER(partner_id) <> LOWER(?) ORDER BY partner_id",
            (COMPANY_OWNER_PARTNER_ID,),
        )
        partner_ids = [row[0] for row in cur.fetchall()]

        for partner_id in partner_ids:
            try:
                cur.execute(
                    "SELECT current_level, commission_eligible FROM partner_levels WHERE partner_id = ?",
                    (partner_id,),
                )
                found = cur.fetchone()
                before = (int(found[0] or 0), bool(found[1])) if found else (None, None)

                progress = _calculate_partner_level_progress(cur, partner_id)
                _sync_partner_level(cur, partner_id, progress)

                after = (int(progress["current_level"] or 0), bool(progress["commission_eligible"]))

                if before != after:
                    changed.append({
                        "partner_id": partner_id,
                        "level_before": before[0],
                        "level_after": after[0],
                        "eligible_before": before[1],
                        "eligible_after": after[1],
                    })
                else:
                    unchanged += 1

            except Exception as error:
                failed.append({"partner_id": partner_id, "error": str(error)[:160]})

        _audit(
            cur, payload.get("actor"), "recalculate_all_levels", "system",
            "ALL", None, {"partners": len(partner_ids)},
            {"changed": len(changed), "unchanged": unchanged, "failed": len(failed)},
            payload.get("reason"), payload.get("source"),
            f"{len(changed)} partner level(s) corrected",
        )

    return _ok(
        f"{len(changed)} partner level(s) corrected out of {len(partner_ids)}",
        total=len(partner_ids),
        changed_count=len(changed),
        unchanged_count=unchanged,
        failed_count=len(failed),
        changed=changed,
        failed=failed,
    )


HANDLERS = {
    "admin_update_commission_status": admin_update_commission_status,
    "admin_bulk_update_commission_status": admin_bulk_update_commission_status,
    "admin_auto_approve_pending_commissions": admin_auto_approve_pending_commissions,
    "admin_mark_partner_approved_commissions_paid": admin_mark_partner_approved_commissions_paid,
    "admin_partner_payout_history": admin_partner_payout_history,
    "admin_partner_lookup": admin_partner_lookup,
    "admin_update_partner_status": admin_update_partner_status,
    "admin_downline_transfer_preview": admin_downline_transfer_preview,
    "admin_transfer_downline_to_alsaab": admin_transfer_downline_to_alsaab,
    "admin_recalculate_all_levels": admin_recalculate_all_levels,
}
