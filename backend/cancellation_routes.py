from flask import request, render_template_string
from urllib.parse import quote
import os


def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def register_cancellation_routes(app, ADMIN_KEY):
    if getattr(app, "alsaab_cancellation_routes_registered", False):
        return

    app.alsaab_cancellation_routes_registered = True

    def client_request_cancellation():
        partner_id = (request.form.get("partner_id", "") or "").strip().upper()
        reason = (request.form.get("reason", "") or "").strip()
        customer_notes = (request.form.get("customer_notes", "") or "").strip()

        if not partner_id:
            return "Partner ID is required", 400

        try:
            database = _db()
            partner_id = database.normalize_partner_id(partner_id)

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "cancellation_request_create",
                    "client_id": partner_id,
                    "partner_id": partner_id,
                    "reason": reason,
                    "customer_notes": customer_notes,
                    "source": "client_dashboard",
                },
                label="cancellation_request_create",
            )

            if not isinstance(result, dict) or result.get("status") != "success":
                return render_template_string(
                    """
                    <html lang="ar" dir="rtl">
                    <head><meta charset="utf-8"><title>تعذر إرسال طلب الإلغاء</title></head>
                    <body style="background:#0b0b0b;color:#fff;font-family:Arial;padding:30px;">
                      <div style="max-width:780px;margin:auto;background:#111;border:1px solid #d7b85a;border-radius:18px;padding:22px;">
                        <h2 style="color:#d7b85a;">تعذر إرسال طلب الإلغاء</h2>
                        <pre style="direction:ltr;white-space:pre-wrap;background:#000;padding:12px;border-radius:12px;">{{ result }}</pre>
                        <a href="javascript:history.back()" style="color:#f0cc68;">رجوع</a>
                      </div>
                    </body>
                    </html>
                    """,
                    result=result,
                ), 500

            return render_template_string(
                """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>تم إرسال طلب الإلغاء</title>
<style>
body{background:#0b0b0b;color:#fff;font-family:Arial;padding:30px}
.card{max-width:780px;margin:auto;background:#111;border:1px solid rgba(215,184,90,.45);border-radius:20px;padding:24px}
h1{color:#d7b85a}
.box{background:#0b0b0b;border:1px solid rgba(215,184,90,.25);border-radius:14px;padding:14px;line-height:1.8}
a{display:inline-block;margin-top:15px;color:#f0cc68;text-decoration:none;border:1px solid rgba(215,184,90,.45);padding:10px 14px;border-radius:999px}
</style>
</head>
<body>
<div class="card">
  <h1>تم إرسال طلب الإلغاء ✅</h1>
  <div class="box">
    رقم الطلب: {{ request_id }}<br>
    الحساب: {{ partner_id }}<br>
    الحالة: cancel_requested<br>
    الإلغاء عند الموافقة يكون في نهاية الفترة الشهرية المدفوعة.
  </div>
  <p>
    لا يوجد استرداد بعد الدفع. إذا وافقت الإدارة على طلب الإلغاء، ستستمر الخدمة إلى نهاية الشهر المدفوع، ثم يتم إيقاف التجديد والخدمات.
  </p>
  <a href="javascript:history.back()">رجوع إلى لوحة الحساب</a>
</div>
</body>
</html>
                """,
                request_id=result.get("request_id"),
                partner_id=partner_id,
            )

        except Exception as error:
            print(f"CLIENT CANCELLATION REQUEST ERROR ❌ {error}", flush=True)
            return str(error), 500

    def admin_cancellation_requests():
        key = request.args.get("key", "").strip()

        if key != ADMIN_KEY:
            return "Unauthorized", 401

        status_filter = request.args.get("status", "all").strip() or "all"

        try:
            database = _db()
            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "admin_cancellation_requests",
                    "status_filter": status_filter,
                    "limit": 200,
                },
                label="admin_cancellation_requests",
            )

            requests_list = []

            if isinstance(result, dict) and result.get("status") == "success":
                requests_list = result.get("requests") or []

            html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>طلبات إلغاء الاشتراك</title>
<style>
body{margin:0;background:#0b0b0b;color:#f5f0df;font-family:Arial,Tahoma,sans-serif;direction:rtl}
.page{max-width:1320px;margin:0 auto;padding:24px}
.header,.section{background:#111;border:1px solid rgba(215,184,90,.35);border-radius:20px;padding:20px;margin-bottom:18px}
h1,h2{color:#d7b85a;margin-top:0}
.top-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:12px}
a.btn,button{border:1px solid rgba(215,184,90,.6);background:#111;color:#f0cc68;padding:10px 14px;border-radius:999px;text-decoration:none;font-weight:800;cursor:pointer}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:1250px}
th,td{padding:10px;border-bottom:1px solid rgba(255,255,255,.08);text-align:right;vertical-align:top;font-size:13px}
th{color:#d7b85a;background:#181818}
.badge{display:inline-block;border:1px solid rgba(215,184,90,.45);color:#f0cc68;padding:5px 9px;border-radius:999px;font-weight:700;white-space:nowrap}
select,textarea{width:100%;box-sizing:border-box;background:#0b0b0b;color:#fff;border:1px solid rgba(215,184,90,.35);border-radius:12px;padding:9px;margin-bottom:8px}
textarea{min-height:60px}
.notice{background:#0b0b0b;border:1px solid rgba(215,184,90,.22);border-radius:14px;padding:14px;line-height:1.8;color:#e8dfc2;margin-top:12px}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <h1>طلبات إلغاء الاشتراك</h1>
    <div class="notice">
      السياسة المعتمدة: لا يوجد استرداد بعد الدفع. العميل يرفع طلب إلغاء، والإدارة تراجعه يدوياً. إذا تمت الموافقة، تستمر الخدمة إلى نهاية الفترة الشهرية المدفوعة ثم يتم إيقاف التجديد والخدمات.
    </div>

    <div class="top-actions">
      <a class="btn" href="/admin-dashboard?key={{ encoded_key }}">رجوع إلى Admin Dashboard</a>
      <a class="btn" href="/admin/cancellation-requests?key={{ encoded_key }}&status=all">كل الطلبات</a>
      <a class="btn" href="/admin/cancellation-requests?key={{ encoded_key }}&status=cancel_requested">Cancel Requested</a>
      <a class="btn" href="/admin/cancellation-requests?key={{ encoded_key }}&status=approved_period_end">Approved Period End</a>
      <a class="btn" href="/admin/cancellation-requests?key={{ encoded_key }}&status=rejected">Rejected</a>
      <a class="btn" href="/admin/cancellation-requests?key={{ encoded_key }}&status=completed">Completed</a>
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
            <th>Subscription</th>
            <th>Stripe</th>
            <th>Reason</th>
            <th>Status</th>
            <th>Admin Decision</th>
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
              Plan: {{ item.current_plan or "-" }}<br>
              Status: {{ item.subscription_status or "-" }}<br>
              Period End: {{ item.current_period_end or "-" }}<br>
              Cancel At Period End: {{ item.cancel_at_period_end or "-" }}
            </td>

            <td>
              Customer: {{ item.stripe_customer_id or "-" }}<br>
              Subscription: {{ item.stripe_subscription_id or "-" }}
            </td>

            <td>
              Reason: {{ item.cancellation_reason or "-" }}<br>
              Customer Notes: {{ item.customer_notes or "-" }}<br>
              Admin Notes: {{ item.admin_notes or "-" }}
            </td>

            <td><span class="badge">{{ item.status or "-" }}</span></td>
            <td><span class="badge">{{ item.admin_decision or "-" }}</span></td>

            <td>
              <form method="POST" action="/admin/update-cancellation-request">
                <input type="hidden" name="key" value="{{ admin_key }}">
                <input type="hidden" name="request_id" value="{{ item.request_id }}">

                <select name="status">
                  <option value="">لا تغير الحالة</option>
                  <option value="cancel_requested">cancel_requested</option>
                  <option value="approved_period_end">approved_period_end</option>
                  <option value="rejected">rejected</option>
                  <option value="completed">completed</option>
                </select>

                <select name="admin_decision">
                  <option value="">لا تغير القرار</option>
                  <option value="approved">approved</option>
                  <option value="rejected">rejected</option>
                  <option value="needs_review">needs_review</option>
                </select>

                <textarea name="admin_notes" placeholder="Admin notes"></textarea>
                <button type="submit">تحديث</button>
              </form>

              <form method="POST" action="/admin/schedule-cancellation-at-period-end" style="margin-top:8px;">
                <input type="hidden" name="key" value="{{ admin_key }}">
                <input type="hidden" name="request_id" value="{{ item.request_id }}">
                <input type="hidden" name="partner_id" value="{{ item.partner_id }}">
                <input type="hidden" name="stripe_subscription_id" value="{{ item.stripe_subscription_id }}">
                <button type="submit" style="border-color:rgba(255,120,120,.65);color:#ffb5b5;">
                  جدولة الإلغاء لنهاية الدورة
                </button>
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
            print(f"ADMIN CANCELLATION REQUESTS ERROR ❌ {error}", flush=True)
            return str(error), 500

    def admin_update_cancellation_request():
        key = request.form.get("key", "").strip()

        if key != ADMIN_KEY:
            return "Unauthorized", 401

        request_id = request.form.get("request_id", "").strip()
        status = request.form.get("status", "").strip()
        admin_decision = request.form.get("admin_decision", "").strip()
        admin_notes = request.form.get("admin_notes", "").strip()

        if not request_id:
            return "request_id is required", 400

        try:
            database = _db()
            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "admin_cancellation_request_update",
                    "request_id": request_id,
                    "status": status,
                    "admin_decision": admin_decision,
                    "admin_notes": admin_notes,
                    "actor": "owner_admin",
                    "source": "admin_dashboard",
                },
                label="admin_cancellation_request_update",
            )

            return render_template_string(
                """
                <html lang="ar" dir="rtl">
                <head><meta charset="utf-8"><title>تم تحديث طلب الإلغاء</title></head>
                <body style="background:#0b0b0b;color:#fff;font-family:Arial;padding:30px;">
                <div style="max-width:820px;margin:auto;background:#111;border:1px solid #d7b85a;border-radius:18px;padding:22px;">
                  <h2 style="color:#d7b85a;">تم تحديث طلب الإلغاء ✅</h2>
                  <pre style="direction:ltr;white-space:pre-wrap;background:#000;padding:12px;border-radius:12px;">{{ result }}</pre>
                  <a href="/admin/cancellation-requests?key={{ key }}" style="color:#f0cc68;">رجوع إلى طلبات الإلغاء</a>
                </div>
                </body>
                </html>
                """,
                result=result,
                key=key,
            )

        except Exception as error:
            print(f"ADMIN UPDATE CANCELLATION REQUEST ERROR ❌ {error}", flush=True)
            return str(error), 500


    # ===== ALSAAB_SCHEDULE_CANCELLATION_STRIPE_V1 START =====
    def admin_schedule_cancellation_at_period_end():
        key = request.form.get("key", "").strip()

        if key != ADMIN_KEY:
            return "Unauthorized", 401

        request_id = request.form.get("request_id", "").strip()
        partner_id = request.form.get("partner_id", "").strip()
        stripe_subscription_id = request.form.get("stripe_subscription_id", "").strip()

        if not request_id:
            return "request_id is required", 400

        if not stripe_subscription_id:
            return render_template_string(
                """
                <html lang="ar" dir="rtl">
                <head><meta charset="utf-8"><title>لا يوجد اشتراك Stripe</title></head>
                <body style="background:#0b0b0b;color:#fff;font-family:Arial;padding:30px;">
                <div style="max-width:820px;margin:auto;background:#111;border:1px solid #d7b85a;border-radius:18px;padding:22px;">
                  <h2 style="color:#d7b85a;">لا يمكن جدولة الإلغاء</h2>
                  <p>طلب الإلغاء لا يحتوي على Stripe Subscription ID. هذا طبيعي إذا كان الطلب تجريبياً أو الاشتراك غير مربوط بـ Stripe.</p>
                  <a href="/admin/cancellation-requests?key={{ key }}" style="color:#f0cc68;">رجوع إلى طلبات الإلغاء</a>
                </div>
                </body>
                </html>
                """,
                key=key,
            ), 400

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

            subscription = stripe.Subscription.modify(
                stripe_subscription_id,
                cancel_at_period_end=True,
            )

            current_period_end = subscription.get("current_period_end", "")

            database = _db()
            update_result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "admin_cancellation_request_update",
                    "request_id": request_id,
                    "status": "approved_period_end",
                    "admin_decision": "approved",
                    "admin_notes": (
                        "Stripe cancellation scheduled at period end. "
                        + "Subscription: "
                        + stripe_subscription_id
                        + " | Current period end: "
                        + str(current_period_end)
                    ),
                    "actor": "owner_admin",
                    "source": "admin_dashboard",
                },
                label="admin_cancellation_request_update",
            )

            return render_template_string(
                """
                <html lang="ar" dir="rtl">
                <head><meta charset="utf-8"><title>تمت جدولة الإلغاء</title></head>
                <body style="background:#0b0b0b;color:#fff;font-family:Arial;padding:30px;">
                <div style="max-width:820px;margin:auto;background:#111;border:1px solid #d7b85a;border-radius:18px;padding:22px;">
                  <h2 style="color:#d7b85a;">تمت جدولة الإلغاء لنهاية الدورة ✅</h2>
                  <p>لن يتم إلغاء الخدمة فوراً. ستستمر إلى نهاية الفترة الشهرية المدفوعة، ثم يتوقف التجديد.</p>

                  <div style="background:#000;padding:12px;border-radius:12px;direction:ltr;white-space:pre-wrap;">
Request ID: {{ request_id }}
Partner ID: {{ partner_id }}
Stripe Subscription: {{ stripe_subscription_id }}
Cancel at period end: true
Current period end: {{ current_period_end }}
                  </div>

                  <pre style="direction:ltr;white-space:pre-wrap;background:#000;padding:12px;border-radius:12px;">{{ update_result }}</pre>

                  <a href="/admin/cancellation-requests?key={{ key }}" style="color:#f0cc68;">رجوع إلى طلبات الإلغاء</a>
                </div>
                </body>
                </html>
                """,
                key=key,
                request_id=request_id,
                partner_id=partner_id,
                stripe_subscription_id=stripe_subscription_id,
                current_period_end=current_period_end,
                update_result=update_result,
            )

        except Exception as error:
            print(f"SCHEDULE CANCELLATION AT PERIOD END ERROR ❌ {error}", flush=True)
            return str(error), 500

    # ===== ALSAAB_SCHEDULE_CANCELLATION_STRIPE_V1 END =====


    def cancellation_dashboard_injector(response):
        try:
            if "text/html" not in response.headers.get("Content-Type", ""):
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_CANCELLATION_UI_V1" in html:
                return response

            if request.path == "/client-dashboard" and "</body>" in html:
                section = """
<!-- ALSAAB_CANCELLATION_UI_V1 START -->
<div id="alsaabCancellationSection" class="alsaab-cancellation-section" dir="rtl">
  <h2>طلب إلغاء الاشتراك</h2>
  <p>
    الإلغاء لا يتم تلقائياً. يمكنك إرسال طلب إلغاء، وستقوم الإدارة بمراجعته يدوياً.
    لا يوجد استرداد بعد الدفع، والخدمة تستمر إلى نهاية الفترة الشهرية المدفوعة.
  </p>

  <form method="POST" action="/client/request-cancellation">
    <input type="hidden" name="partner_id" id="alsaabCancellationPartnerId">

    <label>سبب الإلغاء</label>
    <select name="reason" required>
      <option value="">اختر السبب</option>
      <option value="لا أحتاج الخدمة حالياً">لا أحتاج الخدمة حالياً</option>
      <option value="السعر غير مناسب">السعر غير مناسب</option>
      <option value="أريد التوقف مؤقتاً">أريد التوقف مؤقتاً</option>
      <option value="مشكلة تقنية">مشكلة تقنية</option>
      <option value="سبب آخر">سبب آخر</option>
    </select>

    <label>ملاحظات إضافية</label>
    <textarea name="customer_notes" placeholder="اكتب ملاحظاتك هنا..."></textarea>

    <button type="submit">إرسال طلب الإلغاء</button>
  </form>
</div>

<style>
.alsaab-cancellation-section{
  max-width:1100px;
  margin:22px auto;
  padding:22px;
  background:#111;
  border:1px solid rgba(255,120,120,.35);
  border-radius:22px;
  color:#f5f0df;
  font-family:Arial,Tahoma,sans-serif;
}
.alsaab-cancellation-section h2{
  color:#ff9b9b;
  margin-top:0;
  font-size:28px;
  font-weight:900;
}
.alsaab-cancellation-section p{
  color:#e8dfc2;
  line-height:1.8;
}
.alsaab-cancellation-section label{
  display:block;
  margin-top:13px;
  margin-bottom:6px;
  color:#d7b85a;
  font-weight:800;
}
.alsaab-cancellation-section select,
.alsaab-cancellation-section textarea{
  width:100%;
  box-sizing:border-box;
  background:#0b0b0b;
  color:#fff;
  border:1px solid rgba(215,184,90,.35);
  border-radius:14px;
  padding:12px;
  outline:none;
}
.alsaab-cancellation-section textarea{
  min-height:90px;
}
.alsaab-cancellation-section button{
  margin-top:14px;
  border:1px solid rgba(255,120,120,.65);
  background:#2a1111;
  color:#ffb5b5;
  border-radius:999px;
  padding:12px 18px;
  font-weight:900;
  cursor:pointer;
}
</style>

<script>
(function(){
  var input=document.getElementById("alsaabCancellationPartnerId");
  if(!input)return;

  var text=document.body.innerText||"";
  var match=text.match(/ALS-P\\d{5,}/i);

  if(match&&match[0]){
    input.value=match[0].toUpperCase();
  }
})();
</script>
<!-- ALSAAB_CANCELLATION_UI_V1 END -->
                """
                html = html.replace("</body>", section + "\n</body>", 1)
                response.set_data(html)
                return response

            if request.path == "/admin-dashboard" and "</body>" in html:
                key = request.args.get("key", "").strip()

                section = f"""
<!-- ALSAAB_CANCELLATION_UI_V1 START -->
<div class="section" style="margin-top:18px;">
  <h2>طلبات إلغاء الاشتراك</h2>
  <div class="grid">
    <div class="card">
      <h3>Cancellation Requests</h3>
      <div class="muted">عرض ومراجعة طلبات إلغاء الاشتراك. الإلغاء يتم يدوياً ومن نهاية الدورة المدفوعة.</div>
      <a href="/admin/cancellation-requests?key={key}" style="display:inline-block;margin-top:10px;border:1px solid rgba(255,120,120,.65);color:#ffb5b5;background:#111;border-radius:999px;padding:10px 14px;text-decoration:none;font-weight:900;">
        فتح طلبات الإلغاء
      </a>
    </div>
  </div>
</div>
<!-- ALSAAB_CANCELLATION_UI_V1 END -->
                """
                html = html.replace("</body>", section + "\n</body>", 1)
                response.set_data(html)
                return response

            return response

        except Exception as error:
            print(f"CANCELLATION DASHBOARD INJECTOR ERROR ❌ {error}", flush=True)
            return response

    existing_rules = {str(rule.rule) for rule in app.url_map.iter_rules()}

    if "/client/request-cancellation" not in existing_rules:
        app.add_url_rule(
            "/client/request-cancellation",
            "client_request_cancellation",
            client_request_cancellation,
            methods=["POST"],
        )

    if "/admin/cancellation-requests" not in existing_rules:
        app.add_url_rule(
            "/admin/cancellation-requests",
            "admin_cancellation_requests",
            admin_cancellation_requests,
            methods=["GET"],
        )

    if "/admin/update-cancellation-request" not in existing_rules:
        app.add_url_rule(
            "/admin/update-cancellation-request",
            "admin_update_cancellation_request",
            admin_update_cancellation_request,
            methods=["POST"],
        )

    if "/admin/schedule-cancellation-at-period-end" not in existing_rules:
        app.add_url_rule(
            "/admin/schedule-cancellation-at-period-end",
            "admin_schedule_cancellation_at_period_end",
            admin_schedule_cancellation_at_period_end,
            methods=["POST"],
        )

    app.after_request(cancellation_dashboard_injector)
