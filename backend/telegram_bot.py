# -*- coding: utf-8 -*-
"""
ALSAAB Telegram bot.

Three jobs:

  1. Push a notification for every event the system records. The hook lives in
     sheet_compat.handle(), which every one of the 49 data actions passes
     through, so coverage does not depend on remembering to add a call at each
     new site. Stripe payment events are notified from main.py as well, because
     some of them (payment_failed, invoice.upcoming) carry billing detail that
     never reaches a data action.

  2. Answer questions about the system. The model is given the real schema and
     a read-only SQL tool, so it reads live data instead of guessing from a
     summary that would go stale.

  3. Run administrative actions from a chat message. Each allowed action is
     exposed as a tool; the model picks one and fills the arguments, and the
     action itself is the same handler the admin dashboard calls.

Every entry point swallows its own exceptions. A telegram outage, a bad token
or an OpenAI error must never break a payment webhook.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or "8752500966:AAH2l2-8hA7jVKlAseGkRcx-Sb_uRl7dR08"
).strip()

_DEFAULT_CHAT_IDS = "1879556047,1498991422"

CHAT_IDS = [
    part.strip()
    for part in (os.getenv("TELEGRAM_CHAT_IDS") or _DEFAULT_CHAT_IDS).split(",")
    if part.strip()
]

# Only these chats may run admin actions. Same list by default.
ADMIN_CHAT_IDS = [
    part.strip()
    for part in (os.getenv("TELEGRAM_ADMIN_CHAT_IDS") or ",".join(CHAT_IDS)).split(",")
    if part.strip()
]

AI_MODEL = (os.getenv("TELEGRAM_AI_MODEL") or "gpt-4o").strip()

NOTIFY_ENABLED = (os.getenv("TELEGRAM_NOTIFY") or "on").strip().lower() not in (
    "off", "0", "false", "no"
)

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

TELEGRAM_MAX_CHARS = 4000


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _post(method, payload, timeout=15):
    """Call the Telegram API. Returns the parsed body, or None on any failure."""
    if not BOT_TOKEN:
        return None

    try:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{API_BASE}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        try:
            detail = error.read().decode("utf-8")[:300]
        except Exception:
            detail = str(error)
        print(f"TELEGRAM {method} HTTP {error.code} {detail}", flush=True)

    except Exception as error:
        print(f"TELEGRAM {method} ERROR {type(error).__name__}: {error}", flush=True)

    return None


def _chunks(text):
    """Telegram rejects messages over ~4096 chars. Split on line boundaries."""
    text = str(text or "")

    if len(text) <= TELEGRAM_MAX_CHARS:
        return [text] if text else []

    out, current = [], ""

    for line in text.splitlines(True):
        if len(current) + len(line) > TELEGRAM_MAX_CHARS:
            if current:
                out.append(current)
            # A single line longer than the limit still has to be cut.
            while len(line) > TELEGRAM_MAX_CHARS:
                out.append(line[:TELEGRAM_MAX_CHARS])
                line = line[TELEGRAM_MAX_CHARS:]
            current = line
        else:
            current += line

    if current:
        out.append(current)

    return out


def send_message(text, chat_id=None):
    """Send to one chat, or to every configured chat when chat_id is omitted."""
    targets = [str(chat_id)] if chat_id else list(CHAT_IDS)
    sent = 0

    for target in targets:
        for chunk in _chunks(text):
            result = _post("sendMessage", {
                "chat_id": target,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })

            if result and result.get("ok"):
                sent += 1

    return sent


def _esc(value):
    """Escape for Telegram HTML parse mode."""
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# Lookups used to turn ids into something a human can read
# ---------------------------------------------------------------------------

def _conn():
    try:
        import db
    except ImportError:
        from backend import db
    return db.get_connection()


def _one(sql, params=()):
    """
    Read a single row. Returns None on any failure -- a notification must never
    be the reason a payment webhook fails.
    """
    try:
        with _conn() as connection:
            return connection.cursor().execute(sql, params).fetchone()
    except Exception as error:
        print(f"TELEGRAM LOOKUP SKIPPED {type(error).__name__}: {error}", flush=True)
        return None


def _partner_label(partner_id):
    partner_id = str(partner_id or "").strip()

    if not partner_id:
        return "-"

    row = _one("SELECT partner_name FROM partners WHERE partner_id = ? LIMIT 1", (partner_id,))

    if row and row[0]:
        return f"{partner_id} ({row[0]})"

    return partner_id


def _client_label(client_id):
    client_id = str(client_id or "").strip()

    if not client_id:
        return "-"

    row = _one(
        "SELECT partner_id, partner_name FROM partners WHERE client_id = ? LIMIT 1",
        (client_id,),
    )

    if row:
        name = row[1] or row[0]
        return f"{name} [{client_id[:28]}]"

    return client_id[:40]


def _money(value):
    try:
        return f"{float(value):,.2f} AED"
    except (TypeError, ValueError):
        return f"{value} AED" if value not in (None, "") else "-"


def _date(value):
    text = str(value or "").strip()
    return text[:16] if text else "-"


def _get(payload, *names, default=""):
    for name in names:
        value = (payload or {}).get(name)
        if value not in (None, ""):
            return value
    return default


def _lower_text(value):
    return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Event formatting
# ---------------------------------------------------------------------------

def _fmt_subscription(p, r):
    plan = _get(p, "plan_name", "plan", "package_name")
    status = _lower_text(_get(p, "subscription_status", "status"))

    icon = {"active": "\U0001F7E2", "cancelled": "⚫", "payment_failed": "\U0001F534"}.get(status, "\U0001F535")
    title = {
        "active": "اشتراك نشط",
        "cancelled": "اشتراك ملغى",
        "payment_failed": "اشتراك متعثر الدفع",
    }.get(status, "تحديث اشتراك")

    lines = [
        icon + " <b>" + title + "</b>",
        "العميل: " + _esc(_client_label(_get(p, "client_id", "session_id"))),
        "الباقة: <b>" + _esc(plan) + "</b> - " + _esc(_money(_get(p, "package_amount"))),
        "الراعي: " + _esc(_partner_label(_get(p, "source_partner_id"))),
        "الحالة: " + _esc(status or "-"),
    ]

    period_start = _get(p, "current_period_start", "billing_cycle_start")
    period_end = _get(p, "current_period_end", "billing_cycle_end")

    if period_start or period_end:
        lines.append("الدورة: " + _esc(_date(period_start)) + " -> " + _esc(_date(period_end)))

    stripe_id = _get(p, "stripe_subscription_id")

    if stripe_id:
        lines.append("Stripe: <code>" + _esc(stripe_id) + "</code>")

    return "\n".join(lines)


def _fmt_commission(p, r):
    percent = _get(p, "commission_percent", "percent")
    base = _get(p, "package_amount", "base_amount")

    lines = [
        "\U0001F4B0 <b>عمولة جديدة</b>",
        "المستفيد: " + _esc(_partner_label(_get(p, "beneficiary_partner_id", "partner_id"))),
        "المبلغ: <b>" + _esc(_money(_get(p, "commission_amount"))) + "</b>",
    ]

    if percent and base:
        lines.append("الحساب: " + _esc(percent) + "% من " + _esc(_money(base)))

    lines += [
        "العمق: " + _esc(_get(p, "commission_depth", "depth", default="-")),
        "الباقة: " + _esc(_get(p, "package", "package_name", default="-")),
        "الدافع: " + _esc(_client_label(_get(p, "payer_client_id", "client_id"))),
        "عن الشريك: " + _esc(_partner_label(_get(p, "source_partner_id"))),
        "الحالة: " + _esc(_get(p, "status", default="pending")),
    ]

    return "\n".join(lines)


def _fmt_partner(p, r):
    partner_id = _get(r, "partner_id") or _get(p, "partner_id")

    return "\n".join([
        "\U0001F91D <b>شريك جديد</b>",
        "المعرف: <b>" + _esc(partner_id or "-") + "</b>",
        "الاسم: " + _esc(_get(p, "partner_name", "name", default="-")),
        "الراعي: " + _esc(_partner_label(_get(p, "sponsor_partner_id", "source_partner_id"))),
        "الهاتف: " + _esc(_get(p, "phone", default="-")),
        "الايميل: " + _esc(_get(p, "email", default="-")),
        "رابط الاحالة: " + _esc(_get(r, "referral_link", default="-")),
    ])


def _fmt_lead(p, r):
    return "\n".join([
        "\U0001F4E9 <b>عميل محتمل جديد</b>",
        "الاسم: " + _esc(_get(p, "name", "full_name", default="-")),
        "الهاتف: " + _esc(_get(p, "phone", default="-")),
        "الجلسة: <code>" + _esc(str(_get(p, "session_id"))[:36]) + "</code>",
        "الرسالة: " + _esc(str(_get(p, "message", "note", default="-"))[:300]),
    ])


def _fmt_level(p, r):
    return "\n".join([
        "\U0001F4C8 <b>تحديث مستوى</b>",
        "الشريك: " + _esc(_partner_label(_get(p, "partner_id"))),
        "المستوى: <b>" + _esc(_get(p, "current_level", "partner_rank", default="-")) + "</b>",
        "التالي: " + _esc(_get(p, "next_rank", "next_level", default="-")),
        "الباقة: " + _esc(_get(p, "current_package", default="-")),
        "عملاء نشطون: " + _esc(_get(p, "active_direct_customers", default="-")),
        "مؤهل للعمولة: " + _esc(_get(p, "commission_eligible", default="-")),
    ])


def _fmt_cancellation(p, r):
    return "\n".join([
        "\U0001F6AA <b>طلب الغاء اشتراك</b>",
        "العميل: " + _esc(_client_label(_get(p, "client_id", "session_id"))),
        "الشريك: " + _esc(_partner_label(_get(p, "partner_id"))),
        "السبب: " + _esc(_get(p, "reason", "cancel_reason", default="-")),
        "رقم الطلب: <code>" + _esc(_get(r, "request_id") or _get(p, "request_id", default="-")) + "</code>",
    ])


def _fmt_upgrade(p, r):
    return "\n".join([
        "⬆️ <b>طلب ترقية باقة</b>",
        "الشريك: " + _esc(_partner_label(_get(p, "partner_id"))),
        "من: " + _esc(_get(p, "current_plan", default="-")) + " - " + _esc(_money(_get(p, "current_price"))),
        "الى: <b>" + _esc(_get(p, "target_plan", default="-")) + "</b> - " + _esc(_money(_get(p, "target_price"))),
        "رقم الطلب: <code>" + _esc(_get(r, "request_id") or _get(p, "request_id", default="-")) + "</code>",
    ])


def _fmt_course(p, r):
    return "\n".join([
        "\U0001F393 <b>شراء كورس</b>",
        "الشريك: " + _esc(_partner_label(_get(p, "partner_id"))),
        "الكورس: " + _esc(_get(p, "course_code", "course", default="-")),
        "المبلغ: " + _esc(_money(_get(p, "amount", "package_amount"))),
    ])


def _fmt_admin(action, p, r):
    lines = ["\U0001F6E0 <b>اجراء اداري</b>: <code>" + _esc(action) + "</code>"]

    for key in ("partner_id", "commission_id", "request_id", "client_id",
                "status", "new_status", "actor", "reason"):
        value = _get(p, key)

        if value:
            lines.append(_esc(key) + ": " + _esc(value))

    message = _get(r, "message")

    if message:
        lines.append("النتيجة: " + _esc(str(message)[:300]))

    return "\n".join(lines)


def _fmt_generic(action, p, r):
    lines = ["ℹ️ <b>" + _esc(action) + "</b>"]
    shown = 0

    for key, value in (p or {}).items():
        if key in ("action", "token") or value in (None, ""):
            continue

        if shown >= 10:
            break

        lines.append(_esc(key) + ": " + _esc(str(value)[:120]))
        shown += 1

    return "\n".join(lines)


_FORMATTERS = {
    "subscription": _fmt_subscription,
    "commission": _fmt_commission,
    "partner": _fmt_partner,
    "lead": _fmt_lead,
    "mlm_level": _fmt_level,
    "cancellation_request_create": _fmt_cancellation,
    "upgrade_request_create": _fmt_upgrade,
    "course_purchase": _fmt_course,
}

# Actions that fire on every chat turn or dashboard load. Pushing them would
# bury the events that matter, so they are served without a notification.
_QUIET_ACTIONS = {
    "admin_dashboard_data", "partner_dashboard_data", "client_dashboard_data",
    "partner_tree", "bot_control_get", "smart_link_event_log",
    "smart_link_summary_get", "whatsapp_channel_lookup", "whatsapp_message_log",
    "admin_partner_lookup", "admin_audit_log", "admin_partner_payout_history",
    "admin_cancellation_requests", "admin_upgrade_requests",
    "admin_website_setup_requests", "admin_whatsapp_setup_requests",
    "admin_downline_transfer_preview", "upgrade_subscription_lookup",
    "client_profile", "product_image_group", "website_install_ping",
}


def notify_action(action, payload, result):
    """Called from sheet_compat.handle() for every action it serves."""
    if not NOTIFY_ENABLED or not BOT_TOKEN:
        return

    try:
        action = str(action or "").strip()

        if not action or action in _QUIET_ACTIONS:
            return

        payload = payload or {}
        result = result or {}

        if str(result.get("status", "success")).lower() not in ("success", "ok"):
            return

        formatter = _FORMATTERS.get(action)

        if formatter:
            text = formatter(payload, result)
        elif action.startswith("admin_"):
            text = _fmt_admin(action, payload, result)
        else:
            text = _fmt_generic(action, payload, result)

        send_message(text)

    except Exception as error:
        print(f"TELEGRAM NOTIFY SKIPPED {type(error).__name__}: {error}", flush=True)


def notify_text(text):
    """Direct push for events that are not data actions -- Stripe billing."""
    if not NOTIFY_ENABLED or not BOT_TOKEN:
        return

    try:
        send_message(text)
    except Exception as error:
        print(f"TELEGRAM NOTIFY SKIPPED {type(error).__name__}: {error}", flush=True)


# ---------------------------------------------------------------------------
# Knowledge the model needs about this system
# ---------------------------------------------------------------------------

SYSTEM_BRIEF = """أنت مساعد إدارة نظام ALSAAB AI. تجيب مالك النظام بالعربية، بدقّة وإيجاز.

=== أول قرار تتخذه في كل رسالة: أمرٌ أم سؤال؟ ===

الرسالة أمر إن بدأت بفعل طلب: أعد · اعتمد · ارفض · علّق · سجّل · أوقف · نشّط ·
انقل · حدّث · شغّل · ابحث · نفّذ · اعرض قائمة.
  -> استدعِ run_admin_action. إلزامي. لا تُجب بنص فقط.

الرسالة سؤال إن بدأت بـ: كم · من · أي · ما · هل · لماذا · متى · كيف · اشرح · قارن.
  -> استدعِ sql_query فقط. لا تستدعِ run_admin_action أبداً لسؤال.

أمثلة لا تخطئ فيها:
  «أعد حساب المستويات»  أمر  -> run_admin_action(action="recalculate_all_levels")
  «حدّث المستويات»       أمر  -> run_admin_action(action="recalculate_all_levels")
  «ابحث عن ALS-P00006»  أمر  -> run_admin_action(action="partner_lookup", query="ALS-P00006")
  «اعرض طلبات الإلغاء»   أمر  -> run_admin_action(action="cancellation_requests")
  «كم عدد الشركاء؟»      سؤال -> sql_query
  «لماذا لم يترقَّ X؟»    سؤال -> sql_query

انتبه: «أعد حساب المستويات» عملية كتابة تُحدّث جدول partner_levels. لا يمكن
تنفيذها باستعلام قراءة. من يجيب عنها باستعلام يكون قد فشل في المهمة.

ما هو النظام:
منصّة SaaS لبوت محادثة ذكي للمبيعات، مع شبكة تسويق بالإحالة (MLM) من 5 مستويات.
العملاء يشتركون بباقات شهرية عبر Stripe. كل مشترك يصبح تلقائياً شريكاً يمكنه الإحالة.

الباقات الشهرية: entry 99 · starter 299 · growth 599 · elite 1199 · diamond 2399 (بالدرهم).

مستويات الشركاء ونسب العمولة حسب عمق الإحالة:
  المستوى 1 — باقته entry+   · عميل نشط واحد  · بلا كورس            · 25% على العمق 1
  المستوى 2 — باقته starter+ · 2 عملاء نشطين  · بلا كورس            ·  5% على العمق 2
  المستوى 3 — باقته growth+  · 5 عملاء نشطين  · كورس pro_marketer_mindset_69 ·  4% على العمق 3
  المستوى 4 — باقته elite+   · 10 عملاء نشطين · كورس sales_secrets_999       ·  3% على العمق 4
  المستوى 5 — باقته diamond  · 20 عميلاً نشطاً · كورس change_journey_299      ·  2% على العمق 5

قواعد أساسية لا تخالفها في تفسيرك:
- الشريك يجب أن يكون مشتركاً بنفسه بباقة المستوى أو أعلى، وإلا لا يتأهّل لذلك المستوى.
- الضغط (compression): إذا كان الشريك في سلسلة الإحالة غير مؤهّل، تصعد العمولة لأعلى
  مؤهّل تالٍ، وخانة العمق لا تُستهلك. فلا تضيع عمولة.
- فترة سماح الدفع: عند فشل الدفع يبقى الاشتراك محسوباً نشطاً حتى انتهاء
  payment_grace_until (15 يوماً افتراضياً) — للعميل ولصاحب الاشتراك نفسه.
- العمولة تُدفع مرة واحدة لكل (اشتراك + شهر + عمق) مهما تغيّر المستفيد.
- الصف partner_id='alsaab' هو جذر الشركة، ليس شريكاً حقيقياً. استثنِه من أي عدّ للشركاء.
- الشريك يُربط باشتراكه الشخصي عبر partners.client_id = subscriptions.client_id،
  وليس عبر partner_id.

الجداول المهمة:
  partners(partner_id, client_id, sponsor_partner_id, partner_name, phone, email,
           partner_rank, status, referral_link)
  subscriptions(client_id, session_id, source_partner_id, plan_name, package_amount,
           subscription_status, billing_cycle_start, billing_cycle_end,
           cancel_at_period_end, cancel_effective_at, payment_failed_at,
           payment_grace_until, payment_retry_count, customer_email, customer_phone,
           next_renewal_at, stripe_subscription_id)
  commissions(commission_id, beneficiary_partner_id, source_partner_id, payer_client_id,
           commission_depth, commission_percent, commission_amount, package,
           package_amount, status, period_start, period_end, paid_date)
  partner_levels(partner_id, current_level, next_rank, required_sales, completed_sales,
           current_package, subscription_status, commission_eligible,
           active_direct_customers, missing_requirements)
  leads(session_id, name, phone, created_at)
  referrals · course_purchases · cancellation_requests · upgrade_requests
  audit_logs · payout_history · smart_link_events

عروض جاهزة تحترم فترة السماح — استعملها بدل إعادة اختراع الشرط:
  subscriptions_counting_as_active — الاشتراكات المحسوبة نشطة
  partner_active_direct_customers(partner_id, active_direct_customers)
  partner_active_network_customers(partner_id, active_network_customers)
  partner_downline(root_partner_id, descendant_partner_id, depth)
  partner_upline(...) · partner_commission_totals(...)

اختيار الأداة — القاعدة الحاسمة:
- كل سؤال يبدأ بـ (كم / من / أي / لماذا / متى / اشرح / قارن / اعرض / ما هي)
  هو سؤال قراءة. استعمل sql_query وحدها. لا تستعمل أي أداة إدارية للإجابة عن سؤال.
- الأدوات الإدارية لا تُستعمل إلا إذا طلب المالك تنفيذ فعل صريح
  (اعتمد / ارفض / سجّل / أوقف / نشّط / أعد الحساب / انقل / حدّث).
- لا تستعمل أداة تحتاج partner_id أو request_id إن لم يذكره المالك. اسأله عنه.
- المطابقة الصحيحة لأشهر الطلبات:
    «أعد حساب المستويات» -> recalculate_all_levels
    «ابحث عن شريك X»      -> partner_lookup
    «اعتمد عمولات X»      -> bulk_update_commission_status (status=approved)
    «سجّل عمولات X مدفوعة» -> mark_partner_commissions_paid
    «أوقف / نشّط الشريك X» -> update_partner_status
    «سجل مدفوعات X»       -> partner_payout_history
    «طلبات الإلغاء»        -> cancellation_requests
    «اعتمد / ارفض طلب X»   -> cancellation_decision أو upgrade_decision

طريقة عملك:
- لا تخمّن رقماً أبداً. اقرأ البيانات الحقيقية ثم أجب.
- استعلم عدّة مرات إن لزم لبناء صورة كاملة.
- اذكر الأرقام كما هي، واشرح السبب لا النتيجة فقط.
- إن فشلت أداة، قل ما فشل ولماذا. لا تدّعِ نجاحاً لم يحدث.

متى تنفّذ فوراً ومتى تسأل:
- نفّذ فوراً بلا استئذان — هذه لا تغيّر مالاً ونتيجتها قابلة للتكرار:
    recalculate_all_levels · partner_lookup · partner_payout_history ·
    cancellation_requests · upgrade_requests · website_requests ·
    whatsapp_requests · downline_transfer_preview · audit_log
  إن قال المالك «أعد حساب المستويات» فنفّذها في نفس الرسالة ثم اذكر ما تغيّر.
  لا تسأله «هل تريد أن أنفّذ؟» — هو طلب ذلك بالفعل.
- اسأل واطلب تأكيداً صريحاً قبل هذه فقط، لأنها تمسّ أموالاً أو لا تُلغى بسهولة:
    update_commission_status · bulk_update_commission_status ·
    auto_approve_pending_commissions · mark_partner_commissions_paid ·
    update_partner_status · cancellation_decision · upgrade_decision ·
    website_decision · whatsapp_decision · transfer_downline_to_company ·
    bot_control
  اذكر في سؤالك ما ستفعله بالضبط وعلى من وبأي مبلغ، ثم انتظر «نعم».
- إن كان المعرّف ناقصاً (partner_id أو request_id) فاسأل عنه، ولا تخمّنه.
"""

_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|"
    r"vacuum|reindex|call|do|merge|set\s+role)\b",
    re.IGNORECASE,
)


def sql_query(sql, limit=200):
    """
    Read-only query for the model. Rejects anything that is not a single
    SELECT/WITH so a generated statement cannot modify the database.
    """
    text = str(sql or "").strip().rstrip(";").strip()

    if not text:
        return {"error": "empty query"}

    if ";" in text:
        return {"error": "one statement only"}

    if not re.match(r"^(select|with)\b", text, re.IGNORECASE):
        return {"error": "only SELECT / WITH is allowed"}

    if _FORBIDDEN_SQL.search(text):
        return {"error": "write statements are not allowed"}

    try:
        limit = max(1, min(int(limit or 200), 500))
    except (TypeError, ValueError):
        limit = 200

    if not re.search(r"\blimit\s+\d+\s*$", text, re.IGNORECASE):
        text = f"{text} LIMIT {limit}"

    try:
        with _conn() as connection:
            cursor = connection.cursor()
            cursor.execute(text)
            columns = [d[0] for d in (cursor.description or [])]
            rows = cursor.fetchall()

        return {
            "columns": columns,
            "row_count": len(rows),
            "rows": [
                {columns[i]: _jsonable(value) for i, value in enumerate(row)}
                for row in rows
            ],
        }

    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


# ---------------------------------------------------------------------------
# Administrative actions the bot may run from a chat message
# ---------------------------------------------------------------------------

def _call_action(action, extra):
    """Run one sheet_compat action, the same handler the dashboard calls."""
    try:
        try:
            from sheet_compat import handle as compat_handle
        except ImportError:
            from backend.sheet_compat import handle as compat_handle

        payload = dict(extra or {})
        payload["action"] = action
        payload.setdefault("actor", "telegram_bot")
        payload.setdefault("source", "telegram")

        return compat_handle(payload, label="telegram_admin")

    except Exception as error:
        return {"status": "error", "message": f"{type(error).__name__}: {error}"}


# name -> (action, required args, description shown to the model)
ADMIN_ACTIONS = {
    "partner_lookup": (
        "admin_partner_lookup", ["query"],
        "ابحث عن شريك بالمعرّف أو الاسم أو الهاتف أو الإيميل، وأعد ملفه.",
    ),
    "recalculate_all_levels": (
        "admin_recalculate_all_levels", [],
        "أعد حساب مستويات كل الشركاء من البيانات الحيّة، وأعد قائمة من تغيّر.",
    ),
    "update_commission_status": (
        "admin_update_commission_status", ["commission_id", "status"],
        "غيّر حالة عمولة واحدة. الحالات: pending, approved, hold, rejected, paid.",
    ),
    "bulk_update_commission_status": (
        "admin_bulk_update_commission_status", ["partner_id", "status"],
        "غيّر حالة كل عمولات شريك دفعة واحدة.",
    ),
    "auto_approve_pending_commissions": (
        "admin_auto_approve_pending_commissions", [],
        "اعتمد كل العمولات المعلّقة المستحقّة تلقائياً.",
    ),
    "mark_partner_commissions_paid": (
        "admin_mark_partner_approved_commissions_paid", ["partner_id"],
        "سجّل عمولات الشريك المعتمدة كمدفوعة، وسجّلها في سجل المدفوعات.",
    ),
    "partner_payout_history": (
        "admin_partner_payout_history", ["partner_id"],
        "أعد سجل مدفوعات شريك وملخّصه.",
    ),
    "update_partner_status": (
        "admin_update_partner_status", ["partner_id", "status"],
        "غيّر حالة شريك: active أو inactive أو suspended.",
    ),
    "cancellation_requests": (
        "admin_cancellation_requests", [],
        "أعد قائمة طلبات إلغاء الاشتراك.",
    ),
    "cancellation_decision": (
        "admin_cancellation_request_update", ["request_id", "status"],
        "اعتمد أو ارفض طلب إلغاء. status = approved أو rejected. "
        "الاعتماد يجدول الإلغاء في Stripe عند نهاية الدورة المدفوعة.",
    ),
    "upgrade_requests": (
        "admin_upgrade_requests", [],
        "أعد قائمة طلبات ترقية الباقات.",
    ),
    "upgrade_decision": (
        "admin_upgrade_request_update", ["request_id", "status"],
        "اعتمد أو ارفض طلب ترقية باقة.",
    ),
    "website_requests": (
        "admin_website_setup_requests", [],
        "أعد قائمة طلبات تجهيز المواقع.",
    ),
    "website_decision": (
        "admin_update_website_setup_request", ["request_id", "status"],
        "حدّث حالة طلب تجهيز موقع.",
    ),
    "whatsapp_requests": (
        "admin_whatsapp_setup_requests", [],
        "أعد قائمة طلبات ربط واتساب.",
    ),
    "whatsapp_decision": (
        "admin_update_whatsapp_setup_request", ["request_id", "status"],
        "حدّث حالة طلب ربط واتساب.",
    ),
    "downline_transfer_preview": (
        "admin_downline_transfer_preview", ["partner_id"],
        "اعرض ما سيحدث لو نُقلت شبكة شريك إلى الشركة، قبل التنفيذ.",
    ),
    "transfer_downline_to_company": (
        "admin_transfer_downline_to_alsaab", ["partner_id"],
        "انقل الأبناء المباشرين لشريك إلى جذر الشركة. إجراء ثقيل — تحقّق بالمعاينة أولاً.",
    ),
    "bot_control": (
        "bot_control_update", ["client_id", "bot_enabled"],
        "شغّل أو أوقف بوت عميل. bot_enabled = true أو false.",
    ),
    "audit_log": (
        "admin_audit_log", [],
        "أعد آخر عمليات سجل التدقيق.",
    ),
}


# Arguments any action may carry. Declared once so the enum stays the only
# thing the model has to get right.
_ACTION_ARGS = {
    "partner_id": "معرّف الشريك، مثل ALS-P00006.",
    "request_id": "رقم الطلب، للإلغاء أو الترقية أو طلبات الموقع وواتساب.",
    "commission_id": "معرّف عمولة واحدة.",
    "client_id": "معرّف العميل، لتشغيل أو إيقاف بوته.",
    "status": "الحالة الجديدة. للعمولات: pending أو approved أو hold أو rejected أو paid. "
              "للشركاء: active أو inactive أو suspended. للطلبات: approved أو rejected.",
    "query": "نص البحث: معرّف أو اسم أو هاتف أو إيميل.",
    "bot_enabled": "true أو false.",
    "reason": "سبب الإجراء، يُسجَّل في سجل التدقيق.",
}

_ACTION_GUIDE = """اختر الإجراء من هذه القائمة بالمطابقة الحرفية لما طلبه المالك:

  recalculate_all_levels        «أعد حساب المستويات» / «حدّث المستويات»
  partner_lookup                «ابحث عن شريك ...» (يحتاج query)
  partner_payout_history        «سجل مدفوعات الشريك ...» (يحتاج partner_id)
  audit_log                     «سجل التدقيق» / «آخر العمليات»
  cancellation_requests         «طلبات الإلغاء»
  upgrade_requests              «طلبات الترقية»
  website_requests              «طلبات المواقع»
  whatsapp_requests             «طلبات واتساب»
  downline_transfer_preview     «اعرض ما سيحدث لو نقلنا شبكة ...» (يحتاج partner_id)

  update_commission_status      «غيّر حالة العمولة ...» (commission_id + status)
  bulk_update_commission_status «اعتمد / علّق / ارفض عمولات الشريك ...» (partner_id + status)
  auto_approve_pending_commissions  «اعتمد كل العمولات المعلّقة»
  mark_partner_commissions_paid «سجّل عمولات ... كمدفوعة» (partner_id)
  update_partner_status         «أوقف / نشّط / علّق الشريك ...» (partner_id + status)
  cancellation_decision         «اعتمد / ارفض طلب الإلغاء ...» (request_id + status)
  upgrade_decision              «اعتمد / ارفض طلب الترقية ...» (request_id + status)
  website_decision              «حدّث طلب الموقع ...» (request_id + status)
  whatsapp_decision             «حدّث طلب واتساب ...» (request_id + status)
  transfer_downline_to_company  «انقل شبكة ... إلى الشركة» (partner_id)
  bot_control                   «شغّل / أوقف بوت العميل ...» (client_id + bot_enabled)

لا تستعمل هذه الأداة للإجابة عن سؤال. الأسئلة تُجاب من sql_query وحدها."""


def _tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "sql_query",
                "description": (
                    "اقرأ البيانات الحقيقية بـ SELECT من قاعدة PostgreSQL الحيّة. "
                    "هذه أداتك لكل سؤال عن أرقام أو أسماء أو حالات أو تواريخ. "
                    "استعملها عدّة مرات إن لزم."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "استعلام SELECT أو WITH واحد، بلا فاصلة منقوطة.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "أقصى عدد صفوف، الافتراضي 200.",
                        },
                    },
                    "required": ["sql"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_admin_action",
                "description": (
                    "نفّذ إجراءً إدارياً واحداً على النظام. "
                    "استعملها فقط عندما يطلب المالك فعلاً صريحاً، لا لإجابة سؤال.\n\n"
                    + _ACTION_GUIDE
                ),
                "parameters": {
                    "type": "object",
                    "properties": dict(
                        {
                            "action": {
                                "type": "string",
                                "enum": sorted(ADMIN_ACTIONS),
                                "description": "اسم الإجراء من القائمة أعلاه.",
                            }
                        },
                        **{
                            name: {"type": "string", "description": description}
                            for name, description in _ACTION_ARGS.items()
                        },
                    ),
                    "required": ["action"],
                },
            },
        },
    ]


def _run_tool(name, arguments, is_admin):
    arguments = arguments or {}

    if name == "sql_query":
        return sql_query(arguments.get("sql"), arguments.get("limit"))

    if name != "run_admin_action":
        return {"error": f"unknown tool {name}"}

    action_name = str(arguments.get("action") or "").strip()

    if action_name not in ADMIN_ACTIONS:
        return {
            "error": "إجراء غير معروف: " + (action_name or "(فارغ)"),
            "allowed": sorted(ADMIN_ACTIONS),
        }

    if not is_admin:
        return {"error": "هذه المحادثة غير مصرّح لها بتنفيذ إجراءات إدارية."}

    action, required, _description = ADMIN_ACTIONS[action_name]
    missing = [a for a in required if not str(arguments.get(a) or "").strip()]

    if missing:
        return {"error": "ناقص: " + ", ".join(missing), "action": action_name}

    payload = {
        key: value
        for key, value in arguments.items()
        if key != "action" and value not in (None, "")
    }

    result = _call_action(action, payload)

    if isinstance(result, dict):
        result = dict(result)
        result["ran_action"] = action_name

    return result


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

# Short per-chat history so follow-up questions ("وهو؟", "طيب والثاني؟") work.
_HISTORY = {}
_HISTORY_TURNS = 8
_MAX_TOOL_ROUNDS = 8


def _openai_client():
    """
    config.py reads OPENAI_API_KEY at import time with a plain os.getenv, so it
    is empty unless db has already loaded .env into the environment. Import db
    first, then fall back to reading the variable directly, and say plainly
    which key is missing rather than letting the SDK raise its generic error.
    """
    from openai import OpenAI

    try:
        import db as _db  # noqa: F401  (imported for its .env side effect)
    except ImportError:
        try:
            from backend import db as _db  # noqa: F401
        except ImportError:
            pass

    api_key = ""

    try:
        from config import OPENAI_API_KEY
        api_key = OPENAI_API_KEY or ""
    except ImportError:
        try:
            from backend.config import OPENAI_API_KEY
            api_key = OPENAI_API_KEY or ""
        except ImportError:
            api_key = ""

    api_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY غير مضبوط في بيئة الخادم")

    return OpenAI(api_key=api_key)


def ask_ai(question, chat_id, is_admin):
    """
    Answer one message. The model may call sql_query as often as it needs, and
    an admin action when the owner asked for one, before it replies.
    """
    client = _openai_client()
    key = str(chat_id)

    messages = [{"role": "system", "content": SYSTEM_BRIEF}]
    messages += _HISTORY.get(key, [])
    messages.append({"role": "user", "content": question})

    tools = _tools()
    ran = []

    for _round in range(_MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
        )

        choice = response.choices[0].message
        calls = choice.tool_calls or []

        messages.append({
            "role": "assistant",
            "content": choice.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in calls
            ] or None,
        })

        if not calls:
            answer = (choice.content or "").strip() or "لم أتمكّن من تكوين إجابة."

            history = _HISTORY.get(key, [])
            history += [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
            _HISTORY[key] = history[-(_HISTORY_TURNS * 2):]

            return answer, ran

        for call in calls:
            name = call.function.name

            try:
                arguments = json.loads(call.function.arguments or "{}")
            except Exception:
                arguments = {}

            result = _run_tool(name, arguments, is_admin)

            # Only claim an action ran when it actually did. A tool that came
            # back with an error or a missing argument used to be reported as
            # executed, which read as if the system had changed when nothing
            # had.
            if name != "sql_query":
                ok = isinstance(result, dict) and not result.get("error") and str(
                    result.get("status", "")
                ).lower() in ("success", "ok")

                label = (result or {}).get("ran_action") or arguments.get("action") or name

                if ok:
                    ran.append(label)
                else:
                    print(f"TELEGRAM ACTION FAILED {label} {str(result)[:200]}", flush=True)

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False, default=str)[:12000],
            })

    return "الطلب احتاج خطوات أكثر من المسموح. حاول تضييق السؤال.", ran


_HELP = """<b>ALSAAB AI — بوت الإدارة</b>

يصلك إشعار بكل حدث في النظام: اشتراك جديد، عمولة، فشل دفع، طلب إلغاء أو ترقية،
شريك جديد، تغيّر مستوى، عميل محتمل.

<b>اسأل بالعربية عن أي شيء</b>
• كم شريكاً عندنا وكم منهم يكسب عمولة؟
• من أعلى شريك من حيث العمولات؟
• لماذا ALS-P00003 ما زال في المستوى الأول؟
• من اشتراكاتهم متعثّرة ومتى تنتهي فترة السماح؟
• اشرح لي كيف حُسبت آخر عمولة

<b>وينفّذ إجراءات إدارية بالطلب</b>
• ابحث عن الشريك ALS-P00006
• أعد حساب كل المستويات
• اعتمد عمولات ALS-P00003
• سجّل عمولات ALS-P00007 كمدفوعة
• أوقف الشريك ALS-P00012
• اعرض طلبات الإلغاء المعلّقة

الأوامر: /start /help /status"""


def _status_text():
    data = sql_query("""
        SELECT
          (SELECT COUNT(*) FROM partners WHERE partner_id LIKE 'ALS-P%')            AS partners,
          (SELECT COUNT(*) FROM subscriptions_counting_as_active)                   AS active_subs,
          (SELECT COUNT(*) FROM subscriptions WHERE subscription_status = 'payment_failed') AS failed_subs,
          (SELECT COUNT(*) FROM commissions)                                        AS commissions,
          (SELECT COALESCE(SUM(commission_amount), 0) FROM commissions)             AS commissions_total,
          (SELECT COALESCE(SUM(commission_amount), 0) FROM commissions WHERE status = 'pending') AS pending_total,
          (SELECT COUNT(*) FROM partner_levels WHERE commission_eligible AND partner_id LIKE 'ALS-P%') AS eligible,
          (SELECT COUNT(*) FROM leads)                                              AS leads
    """)

    if data.get("error") or not data.get("rows"):
        return "تعذّر قراءة الحالة: " + _esc(str(data.get("error"))[:200])

    row = data["rows"][0]

    return "\n".join([
        "\U0001F4CA <b>حالة النظام</b>",
        "الشركاء: " + _esc(row.get("partners")),
        "المؤهّلون للعمولة: " + _esc(row.get("eligible")),
        "اشتراكات نشطة: " + _esc(row.get("active_subs")),
        "اشتراكات متعثّرة: " + _esc(row.get("failed_subs")),
        "العمولات: " + _esc(row.get("commissions")) + " بمجموع " + _esc(_money(row.get("commissions_total"))),
        "منها معلّق: " + _esc(_money(row.get("pending_total"))),
        "عملاء محتملون: " + _esc(row.get("leads")),
    ])


def handle_update(update):
    """Entry point for POST /telegram-webhook."""
    try:
        message = (update or {}).get("message") or (update or {}).get("edited_message") or {}
        chat_id = str(((message.get("chat") or {}).get("id")) or "").strip()
        text = str(message.get("text") or "").strip()

        if not chat_id or not text:
            return {"status": "ignored", "reason": "no_text"}

        if CHAT_IDS and chat_id not in CHAT_IDS:
            print(f"TELEGRAM UNKNOWN CHAT {chat_id}", flush=True)
            return {"status": "ignored", "reason": "unknown_chat"}

        command = text.split()[0].lower().split("@")[0]

        if command in ("/start", "/help"):
            send_message(_HELP, chat_id)
            return {"status": "success", "reply": "help"}

        if command == "/status":
            send_message(_status_text(), chat_id)
            return {"status": "success", "reply": "status"}

        _post("sendChatAction", {"chat_id": chat_id, "action": "typing"})

        answer, ran = ask_ai(text, chat_id, chat_id in ADMIN_CHAT_IDS)

        if ran:
            answer += "\n\n<i>نُفِّذ: " + _esc(", ".join(ran)) + "</i>"

        send_message(answer, chat_id)

        return {"status": "success", "actions": ran}

    except Exception as error:
        print(f"TELEGRAM UPDATE ERROR {type(error).__name__}: {error}", flush=True)

        try:
            message = (update or {}).get("message") or {}
            chat_id = str(((message.get("chat") or {}).get("id")) or "")

            if chat_id:
                send_message("تعذّر تنفيذ الطلب: " + _esc(str(error)[:250]), chat_id)
        except Exception:
            pass

        return {"status": "error", "message": str(error)[:300]}


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def set_webhook(base_url):
    url = base_url.rstrip("/") + "/telegram-webhook"
    result = _post("setWebhook", {
        "url": url,
        "allowed_updates": ["message", "edited_message"],
        "drop_pending_updates": True,
    })
    return {"url": url, "result": result}


def get_webhook_info():
    return _post("getWebhookInfo", {})


def self_test():
    info = _post("getMe", {})
    ok = bool(info and info.get("ok"))
    name = ((info or {}).get("result") or {}).get("username") if ok else None
    return {"ok": ok, "username": name, "chats": CHAT_IDS, "model": AI_MODEL}


if __name__ == "__main__":
    import sys

    argument = sys.argv[1] if len(sys.argv) > 1 else "test"

    if argument == "test":
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
    elif argument == "webhook":
        base = sys.argv[2] if len(sys.argv) > 2 else "https://alsaab-ai.onrender.com"
        print(json.dumps(set_webhook(base), ensure_ascii=False, indent=2))
    elif argument == "info":
        print(json.dumps(get_webhook_info(), ensure_ascii=False, indent=2))
    elif argument == "status":
        print(_status_text())
    elif argument == "send":
        print(send_message(" ".join(sys.argv[2:]) or "اختبار"))
    else:
        print("usage: python telegram_bot.py [test|webhook <url>|info|status|send <text>]")
