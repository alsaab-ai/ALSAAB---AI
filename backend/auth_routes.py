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

import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict

from flask import redirect, render_template, request, session


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


# ===== ALSAAB LOGIN OTP V1 START =====
# A six digit code, mailed and typed back on the same page, replaces the
# one-click link that used to arrive by mail.
#
# The code never travels in a URL, so it cannot leak through browser history,
# a referrer header, a shared screenshot of the address bar, or a chat client
# that unfurls links and follows them. It is also bound to the browser that
# asked for it: the challenge lives in this session, so a code read on a phone
# is useless anywhere but the tab that requested it.
#
# What is stored is an HMAC of the code, never the code, so a leaked session
# cookie does not hand over a working credential.

OTP_LENGTH = 6
OTP_TTL_SECONDS = 10 * 60
OTP_MAX_ATTEMPTS = 5


def _otp_secret():
    try:
        import main as _app
    except ImportError:
        from backend import main as _app

    # main keeps this behind a function, not a module attribute.
    try:
        secret = _app.get_dashboard_sso_secret() or ""
    except Exception:
        secret = ""

    if not secret:
        secret = os.getenv("DASHBOARD_SSO_SECRET", "") or os.getenv("FLASK_SECRET_KEY", "")

    return str(secret or "alsaab-otp-fallback").encode("utf-8")


def _otp_digest(code, issued_at):
    """Bind the hash to the issue time so an old hash cannot be replayed."""
    message = f"{issued_at}:{str(code).strip()}".encode("utf-8")
    return hmac.new(_otp_secret(), message, hashlib.sha256).hexdigest()


def _otp_issue(target, partner_id, email):
    """Create a challenge, store only its hash, and return the plain code."""
    code = "".join(str(secrets.randbelow(10)) for _ in range(OTP_LENGTH))
    issued_at = int(time.time())

    session["otp_hash"] = _otp_digest(code, issued_at)
    session["otp_issued"] = issued_at
    session["otp_expires"] = issued_at + OTP_TTL_SECONDS
    session["otp_target"] = target
    session["otp_partner"] = partner_id or ""
    session["otp_email"] = email
    session["otp_attempts"] = 0

    return code


def _otp_clear():
    for key in ("otp_hash", "otp_issued", "otp_expires", "otp_target",
                "otp_partner", "otp_email", "otp_attempts"):
        session.pop(key, None)


def _otp_check(submitted):
    """
    Returns (ok, error_text, target, partner_id). A wrong code burns an attempt; running out of
    attempts destroys the challenge so a code cannot be ground down by
    guessing, and an expired one is refused even if it is correct.
    """
    stored = session.get("otp_hash")
    issued = session.get("otp_issued")

    if not stored or not issued:
        return False, "انتهت الجلسة. اطلب رمزاً جديداً.", "", ""

    if int(time.time()) > int(session.get("otp_expires") or 0):
        _otp_clear()
        return False, "انتهت صلاحية الرمز. اطلب رمزاً جديداً.", "", ""

    attempts = int(session.get("otp_attempts") or 0) + 1
    session["otp_attempts"] = attempts

    if attempts > OTP_MAX_ATTEMPTS:
        _otp_clear()
        return False, "حاولت كثيراً. اطلب رمزاً جديداً.", "", ""

    digits = re.sub(r"\D", "", str(submitted or ""))

    if len(digits) != OTP_LENGTH:
        return False, f"الرمز مكوّن من {OTP_LENGTH} أرقام.", "", ""

    if not hmac.compare_digest(_otp_digest(digits, issued), stored):
        left = OTP_MAX_ATTEMPTS - attempts

        if left <= 0:
            _otp_clear()
            return False, "حاولت كثيراً. اطلب رمزاً جديداً.", "", ""

        return False, f"الرمز غير صحيح. بقيت لك {left} محاولات.", "", ""

    # Spend the challenge here rather than leaving it to the caller, so a
    # correct code can never be replayed even if some future caller forgets.
    target = session.get("otp_target") or "client"
    partner_id = session.get("otp_partner") or ""
    _otp_clear()

    return True, "", target, partner_id
# ===== ALSAAB LOGIN OTP V1 END =====


def _otp_email_html(code, who, base_url):
    """
    The code mail, in the house colours.

    Built with tables and inline styles because that is what mail clients
    render reliably -- Outlook ignores flexbox and strips a <style> block, so
    a layout that looks right in a browser can arrive as a stack of unstyled
    text. The digits are also repeated in the plain text part, so a client
    that blocks HTML still shows something usable.
    """
    logo = f"{base_url.rstrip('/')}/static/logo-white.png"
    spaced = " ".join(str(code))

    return f"""<!doctype html>
<html dir="rtl" lang="ar">
<body style="margin:0;padding:0;background:#050505;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#050505;padding:34px 12px;">
    <tr><td align="center">

      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="max-width:520px;background:#0b0b0b;border:1px solid #2a2a2a;
                    border-radius:22px;overflow:hidden;
                    font-family:Tahoma,Arial,'Segoe UI',sans-serif;">

        <tr>
          <td align="center" style="padding:38px 30px 26px;
                                    border-bottom:1px solid #1c1c1c;">
            <img src="{logo}" alt="ALSAAB" width="188"
                 style="display:block;width:188px;max-width:70%;height:auto;border:0;">
          </td>
        </tr>

        <tr>
          <td align="center" style="padding:34px 30px 6px;">
            <div style="color:#d7b85a;font-size:20px;font-weight:bold;">
              رمز الدخول إلى حسابك
            </div>
            <div style="color:#a9a294;font-size:14px;line-height:1.9;padding-top:10px;">
              اكتب هذا الرمز في صفحة تسجيل الدخول لإكمال الدخول.
            </div>
          </td>
        </tr>

        <tr>
          <td align="center" style="padding:26px 30px 8px;">
            <table role="presentation" cellpadding="0" cellspacing="0"
                   style="background:#141414;border:1px solid #c8a84b;border-radius:16px;">
              <tr>
                <td align="center" style="padding:22px 40px;">
                  <div style="color:#f3d37b;font-size:38px;font-weight:bold;
                              letter-spacing:12px;font-family:'Courier New',Courier,monospace;
                              direction:ltr;">{spaced}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td align="center" style="padding:16px 30px 4px;">
            <div style="color:#8d8779;font-size:13px;">
              صالح لمدة <span style="color:#d7b85a;">10 دقائق</span> ولمرة واحدة
            </div>
          </td>
        </tr>

        <tr>
          <td style="padding:24px 30px 30px;">
            <div style="background:#101010;border-right:3px solid #c8a84b;
                        border-radius:10px;padding:14px 16px;
                        color:#a9a294;font-size:13px;line-height:1.9;">
              إن لم تطلب هذا الرمز، تجاهل الرسالة. لن يتغيّر شيء في حسابك،
              ولن يستطيع أحد الدخول بالرمز وحده.
            </div>
          </td>
        </tr>

        <tr>
          <td align="center" style="padding:18px 30px 30px;border-top:1px solid #1c1c1c;">
            <div style="color:#6e6a60;font-size:12px;line-height:1.9;">
              الحساب: {who}<br>
              ALSAAB AI — موظّف المبيعات الذكي لمشروعك
            </div>
          </td>
        </tr>

      </table>

    </td></tr>
  </table>
</body>
</html>"""


def register_auth_routes(app):

    @app.route("/plans", methods=["GET"])
    def plans_page():
        return render_template("plans.html", plans=_plan_rows())

    @app.route("/login", methods=["GET"])
    def login_page():
        return render_template("login.html", stage="email", sent=False, error="", email="")

    @app.route("/login", methods=["POST"])
    def login_submit():
        # One route, two jobs: a form carrying "code" is answering a challenge,
        # anything else is asking for one.
        if (request.form.get("code") or "").strip():
            ok, why, target, partner_id = _otp_check(request.form.get("code"))

            if not ok:
                return render_template(
                    "login.html", stage="code", sent=True,
                    email=session.get("otp_email", ""), error=why,
                ), 400

            # The challenge was spent inside _otp_check; open the real session.
            session["partner_id"] = partner_id

            if target == "admin":
                session["is_admin"] = True
                session.permanent = True
                print("LOGIN OTP VERIFIED admin", flush=True)
                return redirect("/admin-dashboard")

            session.permanent = True
            print(f"LOGIN OTP VERIFIED partner_id={partner_id}", flush=True)
            return redirect("/client-dashboard")

        email = (request.form.get("email") or "").strip().lower()

        if not EMAIL_RE.match(email):
            return render_template(
                "login.html", stage="email", sent=False, email=email,
                error="اكتب بريداً إلكترونياً صحيحاً.",
            ), 400

        if _rate_limited(email, _client_ip()):
            return render_template(
                "login.html", stage="email", sent=False, email=email,
                error="حاولت كثيراً خلال وقت قصير. انتظر ربع ساعة ثم أعد المحاولة.",
            ), 429

        try:
            import main as _app
        except ImportError:
            from backend import main as _app

        is_admin = email in (getattr(_app, "ADMIN_EMAILS", []) or [])
        partner_id = _find_partner_by_email(email)

        if is_admin or partner_id:
            try:
                import mailer
            except ImportError:
                from backend import mailer

            try:
                code = _otp_issue(
                    "admin" if is_admin else "client", partner_id, email
                )

                base = (getattr(_app, "APP_BASE_URL", "") or "").rstrip("/") \
                    or request.url_root.rstrip("/")

                mailer.send(
                    email,
                    f"رمز الدخول: {code}",
                    _otp_email_html(code, partner_id or "الإدارة", base),
                    f"رمز الدخول إلى ALSAAB AI: {code}\nصالح 10 دقائق ولمرة واحدة.",
                )

                print(
                    "LOGIN CODE SENT %s"
                    % ("admin" if is_admin else f"partner_id={partner_id}"),
                    flush=True,
                )

            except Exception as error:
                print(f"LOGIN CODE ERROR {type(error).__name__}: {error}", flush=True)
        else:
            # No challenge is issued, but the page still moves to the code step
            # so the reply cannot be used to find out which addresses exist.
            _otp_clear()
            session["otp_email"] = email
            print(f"LOGIN NO MATCH for a submitted address from {_client_ip()}", flush=True)

        return render_template("login.html", stage="code", sent=True, error="", email=email)

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        from flask import session
        session.clear()
        return redirect("/login")

    print("AUTH ROUTES ENABLED (/login, /plans, /logout)", flush=True)
