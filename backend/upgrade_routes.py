from flask import request, jsonify, render_template_string
from urllib.parse import quote
import os

# ===== ALSAAB_UPGRADE_SCHEDULE_STRIPE_V1 START =====
UPGRADE_PRICE_IDS = {
    "entry": "price_1TXetrJbltD9Bsg8wnVMaBnZ",
    "starter": "price_1TWEwPJbltD9Bsg8SH2xMao1",
    "growth": "price_1TWFRJJbltD9Bsg8vgUXA1WD",
    "elite": "price_1TWFUhJbltD9Bsg848phcf6P",
}
# ===== ALSAAB_UPGRADE_SCHEDULE_STRIPE_V1 END =====



def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def register_upgrade_routes(app, ADMIN_KEY):
    if getattr(app, "alsaab_upgrade_routes_registered", False):
        return

    app.alsaab_upgrade_routes_registered = True

    def client_request_upgrade():
        partner_id = (request.form.get("partner_id", "") or "").strip().upper()
        current_plan = (request.form.get("current_plan", "") or "").strip().lower()
        target_plan = (request.form.get("target_plan", "") or "").strip().lower()
        notes = (request.form.get("customer_notes", "") or "").strip()

        if not partner_id:
            return "Partner ID is required", 400

        if not current_plan or not target_plan:
            return "Current plan and target plan are required", 400

        try:
            database = _db()
            partner_id = database.normalize_partner_id(partner_id)

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "upgrade_request_create",
                    "client_id": partner_id,
                    "partner_id": partner_id,
                    "current_plan": current_plan,
                    "target_plan": target_plan,
                    "customer_notes": notes,
                    "source": "client_dashboard",
                },
                label="upgrade_request_create",
            )

            if not isinstance(result, dict) or result.get("status") != "success":
                return render_template_string(
                    """
                    <html lang="ar" dir="rtl">
                    <head><meta charset="utf-8"><title>خطأ في طلب الترقية</title></head>
                    <body style="background:#0b0b0b;color:#fff;font-family:Arial;padding:30px;">
                      <div style="max-width:760px;margin:auto;background:#111;border:1px solid #d7b85a;border-radius:18px;padding:22px;">
                        <h2 style="color:#d7b85a;">تعذر إرسال طلب الترقية</h2>
                        <pre style="direction:ltr;white-space:pre-wrap;background:#000;padding:12px;border-radius:12px;">{{ result }}</pre>
                        <a href="javascript:history.back()" style="color:#f0cc68;">رجوع</a>
                      </div>
                    </body>
                    </html>
                    """,
                    result=result,
                ), 500

            html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>تم إرسال طلب الترقية</title>
<style>
body{background:#0b0b0b;color:#fff;font-family:Arial;padding:30px}
.card{max-width:760px;margin:auto;background:#111;border:1px solid rgba(215,184,90,.45);border-radius:20px;padding:24px}
h1{color:#d7b85a}
.box{background:#0b0b0b;border:1px solid rgba(215,184,90,.25);border-radius:14px;padding:14px;line-height:1.8}
a{display:inline-block;margin-top:15px;color:#f0cc68;text-decoration:none;border:1px solid rgba(215,184,90,.45);padding:10px 14px;border-radius:999px}
</style>
</head>
<body>
<div class="card">
  <h1>تم إرسال طلب الترقية ✅</h1>
  <div class="box">
    رقم الطلب: {{ request_id }}<br>
    الحساب: {{ partner_id }}<br>
    من: {{ current_plan }}<br>
    إلى: {{ target_plan }}<br>
    الحالة: pending_payment
  </div>
  <p>سيتم مراجعة طلب الترقية وتجهيز رابط الدفع أو تفعيل الترقية حسب الإجراء المعتمد.</p>
  <a href="javascript:history.back()">رجوع إلى لوحة الحساب</a>
</div>
</body>
</html>
            """

            return render_template_string(
                html,
                request_id=result.get("request_id"),
                partner_id=partner_id,
                current_plan=result.get("current_plan"),
                target_plan=result.get("target_plan"),
            )

        except Exception as error:
            print(f"CLIENT UPGRADE REQUEST ERROR ❌ {error}", flush=True)
            return str(error), 500

    def admin_upgrade_requests():
        key = request.args.get("key", "").strip()

        if key != ADMIN_KEY:
            return "Unauthorized", 401

        status_filter = request.args.get("status", "all").strip() or "all"

        try:
            database = _db()

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "admin_upgrade_requests",
                    "status_filter": status_filter,
                    "limit": 200,
                },
                label="admin_upgrade_requests",
            )

            requests_list = []
            if isinstance(result, dict) and result.get("status") == "success":
                requests_list = result.get("requests") or []

            html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>طلبات ترقية الباقات</title>
<style>
body{margin:0;background:#0b0b0b;color:#f5f0df;font-family:Arial,Tahoma,sans-serif;direction:rtl}
.page{max-width:1320px;margin:0 auto;padding:24px}
.header,.section{background:#111;border:1px solid rgba(215,184,90,.35);border-radius:20px;padding:20px;margin-bottom:18px}
h1,h2{color:#d7b85a;margin-top:0}
.top-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:12px}
a.btn,button{border:1px solid rgba(215,184,90,.6);background:#111;color:#f0cc68;padding:10px 14px;border-radius:999px;text-decoration:none;font-weight:800;cursor:pointer}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:1200px}
th,td{padding:10px;border-bottom:1px solid rgba(255,255,255,.08);text-align:right;vertical-align:top;font-size:13px}
th{color:#d7b85a;background:#181818}
.badge{display:inline-block;border:1px solid rgba(215,184,90,.45);color:#f0cc68;padding:5px 9px;border-radius:999px;font-weight:700;white-space:nowrap}
select,textarea{width:100%;box-sizing:border-box;background:#0b0b0b;color:#fff;border:1px solid rgba(215,184,90,.35);border-radius:12px;padding:9px;margin-bottom:8px}
textarea{min-height:60px}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <h1>طلبات ترقية الباقات</h1>
    <div>هنا تظهر طلبات Upgrade من العملاء. Downgrade مؤجل بعد الإطلاق.</div>

    <div class="top-actions">
      <a class="btn" href="/admin-dashboard?key={{ encoded_key }}">رجوع إلى Admin Dashboard</a>
      <a class="btn" href="/admin/upgrade-requests?key={{ encoded_key }}&status=all">كل الطلبات</a>
      <a class="btn" href="/admin/upgrade-requests?key={{ encoded_key }}&status=pending_payment">Pending Payment</a>
      <a class="btn" href="/admin/upgrade-requests?key={{ encoded_key }}&status=completed">Completed</a>
      <a class="btn" href="/admin/upgrade-requests?key={{ encoded_key }}&status=rejected">Rejected</a>
    </div>
  </div>

  <div class="section">
    <h2>الطلبات: {{ count }}</h2>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Request ID</th>
            <th>Partner / Client</th>
            <th>Upgrade</th>
            <th>Limits</th>
            <th>Status</th>
            <th>Payment</th>
            <th>Notes</th>
            <th>Admin Update</th>
          </tr>
        </thead>
        <tbody>
          {% for item in requests_list %}
          <tr>
            <td>
              <strong>{{ item.request_id or "-" }}</strong><br>
              <small>{{ item.created_at or "-" }}</small>
            </td>

            <td>
              Partner: {{ item.partner_id or "-" }}<br>
              Client: {{ item.client_id or "-" }}
            </td>

            <td>
              From: {{ item.current_plan or "-" }} — {{ item.current_price or "-" }}<br>
              To: <strong>{{ item.target_plan or "-" }}</strong> — {{ item.target_price or "-" }}
            </td>

            <td>
              Customer replies: {{ item.current_customer_reply_limit or "-" }} → {{ item.target_customer_reply_limit or "-" }}<br>
              Advisory: {{ item.current_advisory_reply_limit or "-" }} → {{ item.target_advisory_reply_limit or "-" }}
            </td>

            <td><span class="badge">{{ item.status or "-" }}</span></td>
            <td><span class="badge">{{ item.payment_status or "-" }}</span></td>

            <td>
              Customer: {{ item.customer_notes or "-" }}<br>
              Admin: {{ item.admin_notes or "-" }}
            </td>

            <td>
              <form method="POST" action="/admin/update-upgrade-request">
                <input type="hidden" name="key" value="{{ admin_key }}">
                <input type="hidden" name="request_id" value="{{ item.request_id }}">

                <select name="status">
                  <option value="">لا تغير الحالة</option>
                  <option value="pending_payment">pending_payment</option>
                  <option value="paid_pending_apply">paid_pending_apply</option>
                  <option value="completed">completed</option>
                  <option value="rejected">rejected</option>
                </select>

                <select name="payment_status">
                  <option value="">لا تغير الدفع</option>
                  <option value="not_paid">not_paid</option>
                  <option value="paid">paid</option>
                  <option value="failed">failed</option>
                </select>

                <textarea name="admin_notes" placeholder="Admin notes"></textarea>
                <button type="submit">تحديث</button>
              </form>

              <form method="POST" action="/admin/schedule-upgrade-at-period-end" style="margin-top:8px;">
                <input type="hidden" name="key" value="{{ admin_key }}">
                <input type="hidden" name="request_id" value="{{ item.request_id }}">
                <input type="hidden" name="partner_id" value="{{ item.partner_id }}">
                <input type="hidden" name="target_plan" value="{{ item.target_plan }}">
                <button type="submit">جدولة الترقية لنهاية الدورة</button>
              </form>
            </td>
          </tr>
          {% else %}
          <tr><td colspan="8">لا توجد طلبات حالياً.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
</body>
</html>
            """

            return render_template_string(
                html,
                admin_key=key,
                encoded_key=quote(key),
                count=len(requests_list),
                requests_list=requests_list,
            )

        except Exception as error:
            print(f"ADMIN UPGRADE REQUESTS ERROR ❌ {error}", flush=True)
            return str(error), 500

    def admin_update_upgrade_request():
        key = request.form.get("key", "").strip()

        if key != ADMIN_KEY:
            return "Unauthorized", 401

        request_id = request.form.get("request_id", "").strip()
        status = request.form.get("status", "").strip()
        payment_status = request.form.get("payment_status", "").strip()
        admin_notes = request.form.get("admin_notes", "").strip()

        if not request_id:
            return "request_id is required", 400

        try:
            database = _db()
            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "admin_upgrade_request_update",
                    "request_id": request_id,
                    "status": status,
                    "payment_status": payment_status,
                    "admin_notes": admin_notes,
                    "actor": "owner_admin",
                    "source": "admin_dashboard",
                },
                label="admin_upgrade_request_update",
            )

            return render_template_string(
                """
                <html lang="ar" dir="rtl">
                <head><meta charset="utf-8"><title>تم تحديث طلب الترقية</title></head>
                <body style="background:#0b0b0b;color:#fff;font-family:Arial;padding:30px;">
                <div style="max-width:760px;margin:auto;background:#111;border:1px solid #d7b85a;border-radius:18px;padding:22px;">
                  <h2 style="color:#d7b85a;">تم تحديث طلب الترقية ✅</h2>
                  <pre style="direction:ltr;white-space:pre-wrap;background:#000;padding:12px;border-radius:12px;">{{ result }}</pre>
                  <a href="/admin/upgrade-requests?key={{ key }}" style="color:#f0cc68;">رجوع إلى طلبات الترقية</a>
                </div>
                </body>
                </html>
                """,
                result=result,
                key=key,
            )

        except Exception as error:
            print(f"ADMIN UPDATE UPGRADE REQUEST ERROR ❌ {error}", flush=True)
            return str(error), 500


    def admin_schedule_upgrade_at_period_end():
        key = request.form.get("key", "").strip()

        if key != ADMIN_KEY:
            return "Unauthorized", 401

        request_id = request.form.get("request_id", "").strip()
        partner_id = request.form.get("partner_id", "").strip().upper()
        target_plan = request.form.get("target_plan", "").strip().lower()

        if not request_id:
            return "request_id is required", 400

        if not partner_id:
            return "partner_id is required", 400

        if target_plan not in UPGRADE_PRICE_IDS:
            return f"Invalid target plan: {target_plan}", 400

        try:
            import stripe

            stripe_key = (
                os.getenv("STRIPE_SECRET_KEY")
                or os.getenv("STRIPE_API_KEY")
                or os.getenv("STRIPE_KEY")
                or ""
            )

            if not stripe_key:
                return "STRIPE_SECRET_KEY is missing in Render environment", 500

            stripe.api_key = stripe_key

            database = _db()
            partner_id = database.normalize_partner_id(partner_id)

            lookup = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "upgrade_subscription_lookup",
                    "partner_id": partner_id,
                    "client_id": partner_id,
                },
                label="upgrade_subscription_lookup",
            )

            if not isinstance(lookup, dict) or lookup.get("status") != "success":
                return render_template_string(
                    """
                    <html lang="ar" dir="rtl">
                    <head><meta charset="utf-8"><title>تعذر إيجاد الاشتراك</title></head>
                    <body style="background:#0b0b0b;color:#fff;font-family:Arial;padding:30px;">
                    <div style="max-width:820px;margin:auto;background:#111;border:1px solid #d7b85a;border-radius:18px;padding:22px;">
                      <h2 style="color:#d7b85a;">تعذر إيجاد اشتراك Stripe لهذا الحساب</h2>
                      <pre style="direction:ltr;white-space:pre-wrap;background:#000;padding:12px;border-radius:12px;">{{ lookup }}</pre>
                      <a href="/admin/upgrade-requests?key={{ key }}" style="color:#f0cc68;">رجوع</a>
                    </div>
                    </body>
                    </html>
                    """,
                    lookup=lookup,
                    key=key,
                ), 500

            subscription_data = lookup.get("subscription") or {}
            stripe_subscription_id = str(subscription_data.get("stripe_subscription_id") or "").strip()

            if not stripe_subscription_id:
                return "Stripe Subscription ID is empty for this client", 500

            target_price_id = UPGRADE_PRICE_IDS[target_plan]

            subscription = stripe.Subscription.retrieve(
                stripe_subscription_id,
                expand=["items.data.price"],
            )

            items = subscription["items"]["data"]

            if not items:
                return "Stripe subscription has no items", 500

            current_items = []
            target_items = []

            for index, item in enumerate(items):
                current_price = item["price"]["id"]
                quantity = item.get("quantity") or 1

                current_items.append({
                    "price": current_price,
                    "quantity": quantity,
                })

                if index == 0:
                    target_items.append({
                        "price": target_price_id,
                        "quantity": quantity,
                    })
                else:
                    target_items.append({
                        "price": current_price,
                        "quantity": quantity,
                    })

            current_period_start = subscription.get("current_period_start")
            current_period_end = subscription.get("current_period_end")

            if not current_period_start or not current_period_end:
                return "Stripe subscription period dates missing", 500

            existing_schedule_id = subscription.get("schedule")

            if existing_schedule_id:
                schedule = stripe.SubscriptionSchedule.retrieve(existing_schedule_id)
            else:
                schedule = stripe.SubscriptionSchedule.create(
                    from_subscription=stripe_subscription_id
                )

            start_date = (
                (schedule.get("current_phase") or {}).get("start_date")
                or current_period_start
            )

            updated_schedule = stripe.SubscriptionSchedule.modify(
                schedule["id"],
                end_behavior="release",
                phases=[
                    {
                        "items": current_items,
                        "start_date": start_date,
                        "end_date": current_period_end,
                    },
                    {
                        "items": target_items,
                        "start_date": current_period_end,
                    },
                ],
            )

            mark_result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "upgrade_request_mark_scheduled",
                    "request_id": request_id,
                    "stripe_subscription_id": stripe_subscription_id,
                    "stripe_schedule_id": updated_schedule["id"],
                    "admin_notes": f"Scheduled upgrade to {target_plan} at period end",
                    "actor": "owner_admin",
                    "source": "admin_dashboard",
                },
                label="upgrade_request_mark_scheduled",
            )

            return render_template_string(
                """
                <html lang="ar" dir="rtl">
                <head><meta charset="utf-8"><title>تمت جدولة الترقية</title></head>
                <body style="background:#0b0b0b;color:#fff;font-family:Arial;padding:30px;">
                <div style="max-width:820px;margin:auto;background:#111;border:1px solid #d7b85a;border-radius:18px;padding:22px;">
                  <h2 style="color:#d7b85a;">تمت جدولة الترقية لنهاية الدورة ✅</h2>
                  <p>لن تتغير الباقة الآن. سيتم تطبيق الترقية عند بداية دورة الاشتراك القادمة.</p>
                  <div style="background:#000;padding:12px;border-radius:12px;direction:ltr;white-space:pre-wrap;">
Request ID: {{ request_id }}
Partner ID: {{ partner_id }}
Target Plan: {{ target_plan }}
Stripe Subscription: {{ stripe_subscription_id }}
Stripe Schedule: {{ schedule_id }}
                  </div>
                  <pre style="direction:ltr;white-space:pre-wrap;background:#000;padding:12px;border-radius:12px;">{{ mark_result }}</pre>
                  <a href="/admin/upgrade-requests?key={{ key }}" style="color:#f0cc68;">رجوع إلى طلبات الترقية</a>
                </div>
                </body>
                </html>
                """,
                key=key,
                request_id=request_id,
                partner_id=partner_id,
                target_plan=target_plan,
                stripe_subscription_id=stripe_subscription_id,
                schedule_id=updated_schedule["id"],
                mark_result=mark_result,
            )

        except Exception as error:
            print(f"SCHEDULE UPGRADE AT PERIOD END ERROR ❌ {error}", flush=True)
            return str(error), 500


    def upgrade_injector(response):
        try:
            if "text/html" not in response.headers.get("Content-Type", ""):
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_UPGRADE_UI_INJECTED" in html:
                return response

            if request.path == "/client-dashboard" and "</body>" in html:
                section = """
<!-- ALSAAB_UPGRADE_UI_INJECTED START -->
<div id="alsaabUpgradeSection" class="alsaab-upgrade-section" dir="rtl">
  <h2>ترقية الباقة</h2>
  <p>يمكنك طلب ترقية باقتك إلى باقة أعلى. الترقية فقط متاحة حالياً، أما Downgrade مؤجل بعد الإطلاق.</p>

  <form method="POST" action="/client/request-upgrade">
    <input type="hidden" name="partner_id" id="alsaabUpgradePartnerId">

    <label>الباقة الحالية</label>
    <select name="current_plan" required>
      <option value="">اختر الباقة الحالية</option>
      <option value="entry">الدخول / Entry</option>
      <option value="starter">البداية / Starter</option>
      <option value="growth">النمو / Growth</option>
      <option value="elite">النخبة / Elite</option>
    </select>

    <label>الباقة المطلوبة</label>
    <select name="target_plan" required>
      <option value="">اختر الباقة الجديدة</option>
      <option value="starter">البداية / Starter — 599 AED</option>
      <option value="growth">النمو / Growth — 1099 AED</option>
      <option value="elite">النخبة / Elite — 2099 AED</option>
    </select>

    <label>ملاحظات اختيارية</label>
    <textarea name="customer_notes" placeholder="مثال: أريد الترقية لأنني أحتاج ربط الموقع أو عدد ردود أعلى."></textarea>

    <button type="submit">إرسال طلب الترقية</button>
  </form>
</div>

<style>
.alsaab-upgrade-section{max-width:1100px;margin:22px auto;padding:22px;background:#111;border:1px solid rgba(215,184,90,.45);border-radius:22px;color:#f5f0df;font-family:Arial,Tahoma,sans-serif}
.alsaab-upgrade-section h2{color:#d7b85a;margin-top:0;font-size:28px;font-weight:900}
.alsaab-upgrade-section p{color:#d8cfad;line-height:1.8}
.alsaab-upgrade-section label{display:block;margin-top:13px;margin-bottom:6px;color:#d7b85a;font-weight:800}
.alsaab-upgrade-section select,.alsaab-upgrade-section textarea{width:100%;box-sizing:border-box;background:#0b0b0b;color:#fff;border:1px solid rgba(215,184,90,.35);border-radius:14px;padding:12px;outline:none}
.alsaab-upgrade-section textarea{min-height:90px}
.alsaab-upgrade-section button{margin-top:14px;border:1px solid rgba(215,184,90,.75);background:linear-gradient(135deg,#d7b85a,#a88425);color:#0b0b0b;border-radius:999px;padding:12px 18px;font-weight:900;cursor:pointer}
</style>

<script>
(function(){
  var input=document.getElementById("alsaabUpgradePartnerId");
  if(!input)return;
  var text=document.body.innerText||"";
  var match=text.match(/ALS-P\\d{5,}/i);
  if(match&&match[0]) input.value=match[0].toUpperCase();
})();
</script>
<!-- ALSAAB_UPGRADE_UI_INJECTED END -->
                """
                html = html.replace("</body>", section + "\n</body>", 1)
                response.set_data(html)
                return response

            if request.path == "/admin-dashboard" and "</body>" in html:
                key = request.args.get("key", "").strip()

                section = f"""
<!-- ALSAAB_UPGRADE_UI_INJECTED START -->
<div class="section" style="margin-top:18px;">
  <h2>طلبات ترقية الباقات</h2>
  <div class="grid">
    <div class="card">
      <h3>Upgrade Requests</h3>
      <div class="muted">عرض ومراجعة طلبات ترقية الباقات قبل الدفع أو التفعيل.</div>
      <a href="/admin/upgrade-requests?key={key}" style="display:inline-block;margin-top:10px;border:1px solid rgba(215,184,90,.65);color:#f0cc68;background:#111;border-radius:999px;padding:10px 14px;text-decoration:none;font-weight:900;">
        فتح طلبات الترقية
      </a>
    </div>
  </div>
</div>
<!-- ALSAAB_UPGRADE_UI_INJECTED END -->
                """
                html = html.replace("</body>", section + "\n</body>", 1)
                response.set_data(html)
                return response

            return response

        except Exception as error:
            print(f"UPGRADE UI INJECTOR ERROR ❌ {error}", flush=True)
            return response

    existing_rules = {str(rule.rule) for rule in app.url_map.iter_rules()}

    if "/client/request-upgrade" not in existing_rules:
        app.add_url_rule(
            "/client/request-upgrade",
            "client_request_upgrade",
            client_request_upgrade,
            methods=["POST"],
        )

    if "/admin/upgrade-requests" not in existing_rules:
        app.add_url_rule(
            "/admin/upgrade-requests",
            "admin_upgrade_requests",
            admin_upgrade_requests,
            methods=["GET"],
        )

    if "/admin/update-upgrade-request" not in existing_rules:
        app.add_url_rule(
            "/admin/update-upgrade-request",
            "admin_update_upgrade_request",
            admin_update_upgrade_request,
            methods=["POST"],
        )

    if "/admin/schedule-upgrade-at-period-end" not in existing_rules:
        app.add_url_rule(
            "/admin/schedule-upgrade-at-period-end",
            "admin_schedule_upgrade_at_period_end",
            admin_schedule_upgrade_at_period_end,
            methods=["POST"],
        )

    app.after_request(upgrade_injector)
