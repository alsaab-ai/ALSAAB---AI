# -*- coding: utf-8 -*-
"""
Customer-facing sign-in and pricing.

Sign-in is passwordless: the customer types the email Stripe captured at
checkout, and we mail them a link carrying the same signed SSO token the admin
dashboard already issues. Nothing new is trusted -- create_dashboard_sso_token
and /dashboard-sso were built and tested long before this, and they stay the
only way a session is opened.

The reply to a sign-in request is identical whether the address is on file or
not, so the form cannot be used to find out who is a customer. Requests are
rate limited per address and per IP.
"""

import re
import time
from collections import defaultdict

from flask import redirect, render_template, request


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

TOKEN_TTL_SECONDS = 15 * 60

# Passed as a parameter, never inlined: a literal % inside a statement that
# also carries parameters makes psycopg read it as a placeholder, which made
# both lookups below fail silently and report every address as unknown.
PARTNER_PREFIX = "ALS-P%"

# address -> [timestamps], ip -> [timestamps]
_ATTEMPTS_BY_EMAIL = defaultdict(list)
_ATTEMPTS_BY_IP = defaultdict(list)

RATE_WINDOW_SECONDS = 15 * 60
MAX_PER_EMAIL = 3
MAX_PER_IP = 10


def _db():
    try:
        import db
        return db
    except ImportError:
        from backend import db
        return db


def _client_ip():
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "unknown")


def _rate_limited(email, ip):
    """True when this address or address-source has asked too often."""
    now = time.time()
    cutoff = now - RATE_WINDOW_SECONDS

    for store in (_ATTEMPTS_BY_EMAIL, _ATTEMPTS_BY_IP):
        for key in list(store.keys()):
            store[key] = [t for t in store[key] if t > cutoff]

            if not store[key]:
                del store[key]

    if len(_ATTEMPTS_BY_EMAIL.get(email, [])) >= MAX_PER_EMAIL:
        return True

    if len(_ATTEMPTS_BY_IP.get(ip, [])) >= MAX_PER_IP:
        return True

    _ATTEMPTS_BY_EMAIL[email].append(now)
    _ATTEMPTS_BY_IP[ip].append(now)

    return False


def _find_partner_by_email(email):
    """
    Resolve an address to a partner id.

    partners.email is filled from the checkout contact, but a customer may well
    type the address Stripe holds on the subscription instead, so both are
    searched. Returns None when nothing matches -- the caller must not reveal
    which case it was.
    """
    database = _db()

    try:
        with database.get_connection() as connection:
            cursor = connection.cursor()

            cursor.execute(
                "SELECT partner_id FROM partners "
                "WHERE LOWER(TRIM(COALESCE(email, ''))) = ? "
                "  AND partner_id LIKE ? "
                "ORDER BY partner_id LIMIT 1",
                (email, PARTNER_PREFIX),
            )
            row = cursor.fetchone()

            if row:
                return row[0]

            cursor.execute(
                "SELECT p.partner_id FROM subscriptions s "
                "JOIN partners p ON p.client_id = s.client_id OR p.client_id = s.session_id "
                "WHERE LOWER(TRIM(COALESCE(s.customer_email, ''))) = ? "
                "  AND p.partner_id LIKE ? "
                "ORDER BY p.partner_id LIMIT 1",
                (email, PARTNER_PREFIX),
            )
            row = cursor.fetchone()

            if row:
                return row[0]

    except Exception as error:
        print(f"LOGIN LOOKUP ERROR {type(error).__name__}: {error}", flush=True)

    return None


def _login_email_html(link, partner_id):
    return f"""<!doctype html>
<html dir="rtl" lang="ar">
<body style="margin:0;padding:32px 16px;background:#05070d;font-family:Cairo,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center">
      <table role="presentation" width="100%" style="max-width:460px;background:#0c101a;
             border:1px solid rgba(255,255,255,0.08);border-radius:22px;" cellpadding="0" cellspacing="0">
        <tr><td style="padding:34px 30px;text-align:center;color:#f8fafc;">

          <div style="font-size:30px;font-weight:900;color:#d6a84f;margin-bottom:14px;">A</div>

          <h1 style="margin:0 0 8px;font-size:21px;font-weight:900;color:#f8fafc;">
            رابط الدخول إلى حسابك
          </h1>

          <p style="margin:0 0 26px;font-size:13px;line-height:1.9;color:#94a3b8;">
            اضغط الزر للدخول مباشرة إلى لوحتك.<br>
            الرابط صالح <b style="color:#f3d37b;">15 دقيقة</b> ويُستخدم مرة واحدة.
          </p>

          <a href="{link}" style="display:inline-block;padding:15px 40px;border-radius:14px;
             background:#d6a84f;color:#1a1206;font-size:15px;font-weight:900;text-decoration:none;">
            الدخول إلى لوحتي
          </a>

          <p style="margin:26px 0 0;font-size:11.5px;line-height:1.9;color:#64748b;">
            رقم الشريك: {partner_id}<br>
            لم تطلب هذا الرابط؟ تجاهل الرسالة ولن يحدث شيء.
          </p>

        </td></tr>
      </table>
      <p style="margin:18px 0 0;font-size:11px;color:#475569;">ALSAAB AI</p>
    </td></tr>
  </table>
</body>
</html>"""


def _plan_rows():
    """Pricing cards, built from the same config the checkout uses."""
    try:
        import config
    except ImportError:
        from backend import config

    order = ["entry", "starter", "growth", "elite", "diamond"]

    # entry and diamond carry no feature list in config; describe them from
    # what the rest of the system already knows about them.
    fallback = {
        "entry": [
            "بوت مبيعات ذكي يردّ عن مشروعك",
            "تركيب على WhatsApp",
            "حفظ بيانات العملاء والمحادثات",
            "لوحة تحكّم خاصة بك",
            "يؤهّلك للمستوى الأول في برنامج الشراكة",
        ],
        "diamond": [
            "أعلى سقف ردود في المنصّة",
            "كل مزايا باقة النخبة",
            "أولوية في الدعم والتجهيز",
            "تدريب موسّع على مشاريعك",
            "يؤهّلك لأعلى مستوى في برنامج الشراكة",
        ],
    }

    referral = (
        request.args.get("ref")
        or request.args.get("partner_id")
        or request.args.get("source_partner_id")
        or ""
    ).strip()

    rows = []

    for key in order:
        plan = config.PACKAGES.get(key)
        stripe_plan = config.STRIPE_PLAN_CONFIG.get(key) or {}

        if not isinstance(plan, dict):
            continue

        amount = re.sub(r"[^\d]", "", str(stripe_plan.get("package_amount") or "")) or "-"
        replies = stripe_plan.get("monthly_reply_limit") or plan.get("monthly_reply_limit") or 0

        features = plan.get("features") or fallback.get(key) or []

        # The reply allowance already has its own badge on the card; drop any
        # feature line that only restates it, so starter does not read
        # "2,000 replies" twice in a row.
        if replies:
            features = [f for f in features if str(int(replies)) not in str(f)]

        checkout = f"/pay/{key}"

        if referral:
            checkout += f"?ref={referral}"

        rows.append({
            "key": key,
            "name_ar": plan.get("name_ar") or key,
            "amount": amount,
            "replies": f"{int(replies):,}" if replies else "-",
            "features": features[:8],
            "featured": key == "growth",
            "checkout_url": checkout,
        })

    return rows


def register_auth_routes(app):

    @app.route("/plans", methods=["GET"])
    def plans_page():
        return render_template("plans.html", plans=_plan_rows())

    @app.route("/login", methods=["GET"])
    def login_page():
        return render_template("login.html", sent=False, error="", email="")

    @app.route("/login", methods=["POST"])
    def login_submit():
        email = (request.form.get("email") or "").strip().lower()

        if not EMAIL_RE.match(email):
            return render_template(
                "login.html", sent=False, email=email,
                error="اكتب بريداً إلكترونياً صحيحاً.",
            ), 400

        if _rate_limited(email, _client_ip()):
            return render_template(
                "login.html", sent=False, email=email,
                error="حاولت كثيراً خلال وقت قصير. انتظر ربع ساعة ثم أعد المحاولة.",
            ), 429

        partner_id = _find_partner_by_email(email)

        if partner_id:
            try:
                import main as app_module
            except ImportError:
                from backend import main as app_module

            try:
                import mailer
            except ImportError:
                from backend import mailer

            try:
                token = app_module.create_dashboard_sso_token(
                    partner_id, target="client", lang="ar",
                    ttl_seconds=TOKEN_TTL_SECONDS,
                )

                base = (app_module.APP_BASE_URL or "").rstrip("/") \
                    if hasattr(app_module, "APP_BASE_URL") else ""
                base = base or request.url_root.rstrip("/")

                link = f"{base}/dashboard-sso?token={token}"

                mailer.send(
                    email,
                    "رابط الدخول إلى ALSAAB AI",
                    _login_email_html(link, partner_id),
                    f"رابط الدخول (صالح 15 دقيقة): {link}",
                )

                print(f"LOGIN LINK SENT partner_id={partner_id}", flush=True)

            except Exception as error:
                # The customer still sees the neutral message; only the log
                # records that the send failed.
                print(f"LOGIN LINK ERROR {type(error).__name__}: {error}", flush=True)
        else:
            print(f"LOGIN NO MATCH for a submitted address from {_client_ip()}", flush=True)

        return render_template("login.html", sent=True, error="", email=email)

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        from flask import session
        session.clear()
        return redirect("/login")

    print("AUTH ROUTES ENABLED (/login, /plans, /logout)", flush=True)
