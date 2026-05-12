from flask import request, jsonify, render_template_string, Response
from urllib.parse import quote
import os


def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def register_website_setup_routes(app, ADMIN_KEY):
    if getattr(app, "alsaab_website_setup_registered", False):
        return

    app.alsaab_website_setup_registered = True

    def client_request_website_setup():
        partner_id = (request.form.get("partner_id", "") or "").strip().upper()
        business_name = (request.form.get("business_name", "") or "").strip()
        website_domain = (request.form.get("website_domain", "") or "").strip()
        customer_notes = (request.form.get("customer_notes", "") or "").strip()
        lang = (request.form.get("lang", "ar") or "ar").strip()

        if not partner_id:
            return "Partner ID is required.", 400

        if not website_domain:
            return "Website domain is required.", 400

        try:
            database = _db()
            partner_id = database.normalize_partner_id(partner_id)
            google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

            result = database.post_to_google_sheet_json(
                {
                    "token": google_sheet_token,
                    "action": "website_setup_request",
                    "client_id": partner_id,
                    "partner_id": partner_id,
                    "business_name": business_name,
                    "website_domain": website_domain,
                    "setup_type": "self_install",
                    "setup_status": "snippet_generated",
                    "customer_notes": customer_notes,
                    "lang": lang,
                    "source": "client_dashboard",
                },
                label="website_setup_request",
            )

            if not isinstance(result, dict) or result.get("status") != "success":
                return jsonify(result), 500

            snippet = result.get("installation_snippet", "")
            request_id = result.get("request_id", "")
            domain = result.get("website_domain", website_domain)

            html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>كود تركيب ALSAAB AI على الموقع</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{margin:0;background:#0b0b0b;color:#f5f0df;font-family:Arial,Tahoma,sans-serif;direction:rtl}
    .wrap{max-width:920px;margin:0 auto;padding:28px}
    .card{background:#111;border:1px solid rgba(215,184,90,.45);border-radius:22px;padding:24px}
    h1{color:#d7b85a;margin-top:0}
    .muted{color:#cfc7ad;line-height:1.8}
    textarea{width:100%;min-height:130px;box-sizing:border-box;background:#0b0b0b;color:#fff;border:1px solid rgba(215,184,90,.45);border-radius:14px;padding:14px;direction:ltr;font-family:Consolas,monospace;margin-top:14px}
    button,a.btn{display:inline-block;margin-top:14px;border:1px solid rgba(215,184,90,.65);background:#111;color:#f0cc68;padding:12px 16px;border-radius:999px;cursor:pointer;text-decoration:none;font-weight:800}
    .success{border:1px solid rgba(128,226,138,.45);color:#80e28a;background:rgba(128,226,138,.08);padding:12px;border-radius:14px;margin:14px 0}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>تم إنشاء كود تركيب الموقع ✅</h1>
      <div class="success">
        رقم الطلب: {{ request_id }}<br>
        الموقع: {{ domain }}<br>
        الحالة: snippet_generated
      </div>
      <p class="muted">
        انسخ الكود التالي وضعه في موقعك قبل نهاية وسم <strong>&lt;/body&gt;</strong>.
        بعد تركيب الكود، سيتغير الوضع تلقائياً إلى <strong>installed_detected</strong>.
      </p>
      <textarea id="installSnippet" readonly>{{ snippet }}</textarea>
      <button onclick="copySnippet()">نسخ كود التركيب</button>
      <a class="btn" href="javascript:history.back()">رجوع إلى لوحة العميل</a>
    </div>
  </div>
  <script>
    function copySnippet(){
      var t=document.getElementById("installSnippet");
      t.select();
      t.setSelectionRange(0,99999);
      document.execCommand("copy");
      alert("تم نسخ كود التركيب");
    }
  </script>
</body>
</html>
            """

            return render_template_string(
                html,
                request_id=request_id,
                domain=domain,
                snippet=snippet,
            )

        except Exception as error:
            print(f"CLIENT WEBSITE SETUP ERROR ❌ {error}", flush=True)
            return str(error), 500

    def widget_install_ping():
        if request.method == "OPTIONS":
            return jsonify({"status": "ok"}), 200

        try:
            database = _db()

            if request.method == "POST":
                payload = request.get_json(silent=True) or request.form.to_dict() or {}
            else:
                payload = request.args.to_dict() or {}

            partner_id = payload.get("client_id") or payload.get("partner_id") or ""
            domain = (
                payload.get("domain")
                or payload.get("website_domain")
                or request.headers.get("Origin", "")
                or request.headers.get("Referer", "")
                or ""
            )
            setup_status = payload.get("setup_status") or payload.get("status") or "installed_detected"

            partner_id = database.normalize_partner_id(str(partner_id or "").strip())

            if not partner_id:
                return jsonify({"status": "error", "message": "client_id/partner_id is required"}), 400

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "website_install_ping",
                    "partner_id": partner_id,
                    "client_id": partner_id,
                    "domain": domain,
                    "setup_status": setup_status,
                    "user_agent": request.headers.get("User-Agent", ""),
                    "source": "widget_install_ping",
                },
                label="website_install_ping",
            )

            return jsonify(result)

        except Exception as error:
            print(f"WIDGET INSTALL PING ERROR ❌ {error}", flush=True)
            return jsonify({"status": "error", "message": str(error)}), 500

    def alsaab_widget_js():
        js = r'''
(function(){
  var script=document.currentScript||(function(){var s=document.getElementsByTagName("script");return s[s.length-1];})();
  var BASE="https://alsaab-ai.onrender.com";
  var clientId=(script&&(script.getAttribute("data-client-id")||script.getAttribute("data-partner-id")))||"";
  var lang=(script&&script.getAttribute("data-lang"))||"ar";
  var domain=(script&&script.getAttribute("data-domain"))||window.location.hostname||"";

  function ping(status){
    try{
      fetch(BASE+"/widget-install-ping",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({client_id:clientId,partner_id:clientId,domain:domain,setup_status:status||"installed_detected"}),
        keepalive:true
      }).catch(function(){});
    }catch(e){}
  }

  ping("installed_detected");

  if(!clientId){
    console.warn("ALSAAB widget missing data-client-id");
    return;
  }

  var style=document.createElement("style");
  style.innerHTML=`
    #alsaabWidgetButton{position:fixed;right:18px;bottom:18px;z-index:999999;background:linear-gradient(135deg,#d7b85a,#a88425);color:#0b0b0b;border:none;border-radius:999px;padding:13px 18px;font-weight:900;cursor:pointer;box-shadow:0 0 24px rgba(0,0,0,.3);font-family:Arial,sans-serif}
    #alsaabWidgetPanel{position:fixed;right:18px;bottom:76px;width:360px;max-width:calc(100vw - 36px);height:520px;max-height:calc(100vh - 120px);z-index:999999;background:#0b0b0b;color:#fff;border:1px solid rgba(215,184,90,.55);border-radius:20px;display:none;flex-direction:column;overflow:hidden;box-shadow:0 0 35px rgba(0,0,0,.45);font-family:Arial,sans-serif;direction:rtl}
    #alsaabWidgetHeader{padding:14px 16px;background:#111;color:#d7b85a;font-weight:900;border-bottom:1px solid rgba(215,184,90,.25)}
    #alsaabWidgetMessages{flex:1;overflow-y:auto;padding:14px;font-size:14px;line-height:1.7}
    .alsaabMsg{margin:8px 0;padding:10px 12px;border-radius:14px;white-space:pre-wrap}
    .alsaabUser{background:#d7b85a;color:#0b0b0b;margin-left:35px}
    .alsaabBot{background:#151515;color:#f5f0df;border:1px solid rgba(215,184,90,.18);margin-right:35px}
    #alsaabWidgetInputRow{display:flex;gap:8px;padding:10px;border-top:1px solid rgba(215,184,90,.25);background:#111}
    #alsaabWidgetInput{flex:1;background:#0b0b0b;color:#fff;border:1px solid rgba(215,184,90,.35);border-radius:999px;padding:10px 12px;outline:none}
    #alsaabWidgetSend{background:#d7b85a;color:#0b0b0b;border:none;border-radius:999px;padding:10px 13px;font-weight:900;cursor:pointer}
  `;
  document.head.appendChild(style);

  var button=document.createElement("button");
  button.id="alsaabWidgetButton";
  button.textContent=lang==="en"?"Smart Sales Assistant":"موظف المبيعات الذكي";
  document.body.appendChild(button);

  var panel=document.createElement("div");
  panel.id="alsaabWidgetPanel";
  panel.innerHTML='<div id="alsaabWidgetHeader">'+(lang==="en"?"Smart Sales Assistant":"موظف المبيعات الذكي")+'</div><div id="alsaabWidgetMessages"></div><div id="alsaabWidgetInputRow"><input id="alsaabWidgetInput" placeholder="'+(lang==="en"?"Write your message...":"اكتب رسالتك...")+'"><button id="alsaabWidgetSend">'+(lang==="en"?"Send":"إرسال")+'</button></div>';
  document.body.appendChild(panel);

  var messages=document.getElementById("alsaabWidgetMessages");
  var input=document.getElementById("alsaabWidgetInput");
  var send=document.getElementById("alsaabWidgetSend");
  var sessionId="web_"+clientId+"_"+Math.random().toString(36).slice(2);

  function addMessage(text,cls){
    var div=document.createElement("div");
    div.className="alsaabMsg "+cls;
    div.textContent=text;
    messages.appendChild(div);
    messages.scrollTop=messages.scrollHeight;
  }

  button.addEventListener("click",function(){
    panel.style.display=panel.style.display==="flex"?"none":"flex";
    if(!messages.dataset.started){
      messages.dataset.started="yes";
      addMessage(lang==="en"?"Hello, how can I help you?":"هلا، كيف أقدر أساعدك؟","alsaabBot");
    }
  });

  function sendMessage(){
    var text=(input.value||"").trim();
    if(!text)return;
    input.value="";
    addMessage(text,"alsaabUser");
    ping("live");

    fetch(BASE+"/chat",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        message:text,
        session_id:sessionId,
        client_id:clientId,
        partner_id:clientId,
        channel:"website",
        source:"client_widget",
        page_url:window.location.href,
        domain:domain
      })
    })
    .then(function(res){return res.json();})
    .then(function(data){
      addMessage(data.reply||data.response||data.message||"تم استلام رسالتك.","alsaabBot");
    })
    .catch(function(){
      addMessage(lang==="en"?"Connection error. Please try again.":"صار خطأ في الاتصال، جرّب مرة ثانية.","alsaabBot");
    });
  }

  send.addEventListener("click",sendMessage);
  input.addEventListener("keydown",function(e){if(e.key==="Enter")sendMessage();});
})();
'''
        return Response(js, mimetype="application/javascript")

    def admin_website_installations():
        key = request.args.get("key", "").strip()

        if key != ADMIN_KEY:
            return "Unauthorized", 401

        status_filter = request.args.get("status", "all").strip() or "all"

        try:
            database = _db()
            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "admin_website_setup_requests",
                    "status_filter": status_filter,
                    "limit": 200,
                },
                label="admin_website_installations",
            )

            requests_list = []
            if isinstance(result, dict) and result.get("status") == "success":
                requests_list = result.get("requests") or []

            html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>تركيبات المواقع</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{margin:0;background:#0b0b0b;color:#f5f0df;font-family:Arial,Tahoma,sans-serif;direction:rtl}
.page{max-width:1320px;margin:0 auto;padding:24px}
.header,.section{background:#111;border:1px solid rgba(215,184,90,.35);border-radius:20px;padding:20px;margin-bottom:18px}
h1,h2{color:#d7b85a;margin-top:0}
.top-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:12px}
a.btn{border:1px solid rgba(215,184,90,.6);background:#111;color:#f0cc68;padding:10px 14px;border-radius:999px;text-decoration:none;font-weight:800}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:1100px}
th,td{padding:10px;border-bottom:1px solid rgba(255,255,255,.08);text-align:right;vertical-align:top;font-size:13px}
th{color:#d7b85a;background:#181818}
.badge{display:inline-block;border:1px solid rgba(215,184,90,.45);color:#f0cc68;padding:5px 9px;border-radius:999px;font-weight:700;white-space:nowrap}
.snippet-box{direction:ltr;font-family:Consolas,monospace;max-width:380px;white-space:nowrap;overflow-x:auto;background:rgba(255,255,255,.035);border-radius:10px;padding:8px}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <h1>تركيبات المواقع</h1>
    <div>هنا تظهر طلبات تركيب موظف المبيعات الذكي على مواقع العملاء. الحالة تتغير تلقائياً عند تركيب الكود أو بدء الاستخدام.</div>
    <div class="top-actions">
      <a class="btn" href="/admin-dashboard?key={{ encoded_key }}">رجوع إلى Admin Dashboard</a>
      <a class="btn" href="/admin/website-installations?key={{ encoded_key }}&status=all">كل الطلبات</a>
      <a class="btn" href="/admin/website-installations?key={{ encoded_key }}&status=snippet_generated">Snippet Generated</a>
      <a class="btn" href="/admin/website-installations?key={{ encoded_key }}&status=installed_detected">Installed</a>
      <a class="btn" href="/admin/website-installations?key={{ encoded_key }}&status=live">Live</a>
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
            <th>Business</th>
            <th>Domain</th>
            <th>Status</th>
            <th>Snippet</th>
            <th>Customer Notes</th>
            <th>Admin Notes</th>
          </tr>
        </thead>
        <tbody>
          {% for item in requests_list %}
          <tr>
            <td><strong>{{ item.request_id or "-" }}</strong><br><small>{{ item.created_at or item.date or "-" }}</small></td>
            <td>Partner: {{ item.partner_id or "-" }}<br>Client: {{ item.client_id or "-" }}</td>
            <td>{{ item.business_name or "-" }}</td>
            <td>{{ item.website_domain or "-" }}</td>
            <td><span class="badge">{{ item.setup_status or "-" }}</span></td>
            <td><div class="snippet-box">{{ item.installation_snippet or "-" }}</div></td>
            <td>{{ item.customer_notes or "-" }}</td>
            <td>{{ item.admin_notes or "-" }}</td>
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
                encoded_key=quote(key),
                count=len(requests_list),
                requests_list=requests_list,
            )

        except Exception as error:
            print(f"ADMIN WEBSITE INSTALLATIONS ERROR ❌ {error}", flush=True)
            return str(error), 500

    def website_setup_injector(response):
        try:
            if "text/html" not in response.headers.get("Content-Type", ""):
                return response

            html = response.get_data(as_text=True)
            if not html or "ALSAAB_WEBSITE_SETUP_MODULE_INJECTED" in html:
                return response

            if request.path == "/client-dashboard" and "</body>" in html:
                section = '''
<!-- ALSAAB_WEBSITE_SETUP_MODULE_INJECTED START -->
<div id="alsaabWebsiteInstallSection" class="alsaab-website-install-section" dir="rtl">
  <h2>تركيب النظام على الموقع</h2>
  <p>بعد إعداد WhatsApp، تقدر تركب موظف المبيعات الذكي على موقعك من خلال كود بسيط. الحالة تتغير تلقائياً بعد تركيب الكود.</p>
  <form method="POST" action="/client/request-website-setup">
    <input type="hidden" name="partner_id" id="alsaabWebsitePartnerId">
    <input type="hidden" name="lang" value="ar">
    <label>اسم النشاط / الشركة</label>
    <input name="business_name" placeholder="مثال: ALSAAB AI">
    <label>رابط الموقع أو الدومين</label>
    <input name="website_domain" required placeholder="example.com أو https://example.com">
    <label>ملاحظات للتركيب</label>
    <textarea name="customer_notes" placeholder="مثال: الموقع WordPress، أريد تركيبه في الصفحة الرئيسية."></textarea>
    <button type="submit">إنشاء كود تركيب الموقع</button>
  </form>
  <div class="alsaab-website-install-note">بعد تركيب الكود، النظام يكتشف التركيب تلقائياً ويغير الحالة إلى installed_detected.</div>
</div>
<style>
.alsaab-website-install-section{max-width:1100px;margin:22px auto;padding:22px;background:#111;border:1px solid rgba(215,184,90,.45);border-radius:22px;color:#f5f0df;font-family:Arial,Tahoma,sans-serif}
.alsaab-website-install-section h2{color:#d7b85a;margin-top:0;font-size:28px;font-weight:900}
.alsaab-website-install-section p,.alsaab-website-install-note{color:#d8cfad;line-height:1.8}
.alsaab-website-install-section label{display:block;margin-top:13px;margin-bottom:6px;color:#d7b85a;font-weight:800}
.alsaab-website-install-section input,.alsaab-website-install-section textarea{width:100%;box-sizing:border-box;background:#0b0b0b;color:#fff;border:1px solid rgba(215,184,90,.35);border-radius:14px;padding:12px;outline:none}
.alsaab-website-install-section textarea{min-height:90px}
.alsaab-website-install-section button{margin-top:14px;border:1px solid rgba(215,184,90,.75);background:linear-gradient(135deg,#d7b85a,#a88425);color:#0b0b0b;border-radius:999px;padding:12px 18px;font-weight:900;cursor:pointer}
.alsaab-website-install-note{margin-top:12px;font-size:13px}
</style>
<script>
(function(){
  var section=document.getElementById("alsaabWebsiteInstallSection");
  var input=document.getElementById("alsaabWebsitePartnerId");
  if(!section||!input)return;

  var text=document.body.innerText||"";
  var match=text.match(/ALS-P\\d{5,}/i);
  if(match&&match[0]) input.value=match[0].toUpperCase();

  var candidates=Array.prototype.slice.call(document.querySelectorAll("div,section,article"));
  var whatsappContainer=null;

  for(var i=0;i<candidates.length;i++){
    var t=(candidates[i].innerText||"").trim();
    if(t.indexOf("WhatsApp")!==-1||t.indexOf("واتساب")!==-1||t.indexOf("ربط WhatsApp")!==-1||t.indexOf("إعداد WhatsApp")!==-1){
      if(candidates[i].contains(section)) continue;
      whatsappContainer=candidates[i];
      break;
    }
  }

  if(whatsappContainer&&whatsappContainer.parentNode){
    whatsappContainer.parentNode.insertBefore(section,whatsappContainer.nextSibling);
  }
})();
</script>
<!-- ALSAAB_WEBSITE_SETUP_MODULE_INJECTED END -->
                '''
                html = html.replace("</body>", section + "\n</body>", 1)
                response.set_data(html)
                return response

            if request.path == "/admin-dashboard" and "</body>" in html:
                key = request.args.get("key", "").strip()

                section = f'''
<!-- ALSAAB_WEBSITE_SETUP_MODULE_INJECTED START -->
<div class="section" style="margin-top:18px;">
  <h2>قنوات العملاء</h2>
  <div class="grid">
    <div class="card">
      <h3>طلبات ربط WhatsApp</h3>
      <div class="muted">إدارة طلبات ربط واتساب للعملاء من الزر الحالي في الداشبورد.</div>
    </div>
    <div class="card">
      <h3>تركيبات المواقع</h3>
      <div class="muted">عرض طلبات تركيب النظام على مواقع العملاء وحالة التركيب التلقائية.</div>
      <a href="/admin/website-installations?key={key}" style="display:inline-block;margin-top:10px;border:1px solid rgba(215,184,90,.65);color:#f0cc68;background:#111;border-radius:999px;padding:10px 14px;text-decoration:none;font-weight:900;">فتح تركيبات المواقع</a>
    </div>
  </div>
</div>
<!-- ALSAAB_WEBSITE_SETUP_MODULE_INJECTED END -->
                '''
                html = html.replace("</body>", section + "\n</body>", 1)
                response.set_data(html)
                return response

            return response

        except Exception as error:
            print(f"WEBSITE SETUP MODULE INJECTOR ERROR ❌ {error}", flush=True)
            return response

    def website_setup_cors(response):
        try:
            if request.path in ["/widget.js", "/widget-install-ping", "/chat"]:
                response.headers["Access-Control-Allow-Origin"] = "*"
                response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        except Exception:
            pass
        return response

    existing_rules = {str(rule.rule) for rule in app.url_map.iter_rules()}

    if "/client/request-website-setup" not in existing_rules:
        app.add_url_rule(
            "/client/request-website-setup",
            "client_request_website_setup_module",
            client_request_website_setup,
            methods=["POST"],
        )

    if "/widget-install-ping" not in existing_rules:
        app.add_url_rule(
            "/widget-install-ping",
            "widget_install_ping_module",
            widget_install_ping,
            methods=["GET", "POST", "OPTIONS"],
        )

    if "/widget.js" not in existing_rules:
        app.add_url_rule(
            "/widget.js",
            "alsaab_widget_js_module",
            alsaab_widget_js,
            methods=["GET"],
        )

    if "/admin/website-installations" not in existing_rules:
        app.add_url_rule(
            "/admin/website-installations",
            "admin_website_installations_module",
            admin_website_installations,
            methods=["GET"],
        )

    app.after_request(website_setup_injector)
    app.after_request(website_setup_cors)

    # ===== ALSAAB_ADMIN_CHANNEL_BUTTONS_FINAL_FIX START =====
    def admin_channel_buttons_final_fix(response):
        try:
            import json

            if request.path != "/admin-dashboard":
                return response

            if "text/html" not in response.headers.get("Content-Type", ""):
                return response

            html = response.get_data(as_text=True)

            if "ALSAAB_ADMIN_CHANNEL_BUTTONS_FINAL_FIX_MARKER" in html:
                return response

            key = request.args.get("key", "").strip()
            website_url = "/admin/website-installations?key=" + key

            script = """
<!-- ALSAAB_ADMIN_CHANNEL_BUTTONS_FINAL_FIX_MARKER START -->
<style>
  .alsaab-admin-channel-inline-btn {
    display: inline-block !important;
    margin-right: 10px !important;
    margin-left: 10px !important;
    border: 1px solid rgba(215,184,90,.65) !important;
    color: #f0cc68 !important;
    background: #111 !important;
    border-radius: 999px !important;
    padding: 10px 14px !important;
    text-decoration: none !important;
    font-weight: 900 !important;
  }
</style>

<script>
(function () {
  var websiteUrl = __WEBSITE_URL__;

  function cleanAndAttach() {
    // Hide the duplicate bottom "قنوات العملاء" block.
    Array.prototype.slice.call(document.querySelectorAll(".section, .card, div")).forEach(function (el) {
      var t = (el.innerText || "").replace(/\\s+/g, " ").trim();

      if (
        t.indexOf("قنوات العملاء") !== -1 &&
        t.indexOf("تركيبات المواقع") !== -1 &&
        t.indexOf("طلبات ربط WhatsApp") !== -1
      ) {
        el.style.display = "none";
      }
    });

    if (document.getElementById("alsaabWebsiteInstallAdminBtn")) {
      return;
    }

    var target = null;
    var items = Array.prototype.slice.call(document.querySelectorAll("a, button"));

    for (var i = 0; i < items.length; i++) {
      var txt = (items[i].innerText || items[i].textContent || "").replace(/\\s+/g, " ").trim();
      var href = items[i].getAttribute("href") || "";

      if (
        txt.indexOf("فتح طلبات ربط WhatsApp") !== -1 ||
        txt.indexOf("طلبات ربط WhatsApp") !== -1 ||
        href.indexOf("whatsapp-setup") !== -1
      ) {
        target = items[i];
        break;
      }
    }

    if (!target) {
      return;
    }

    var link = document.createElement("a");
    link.id = "alsaabWebsiteInstallAdminBtn";
    link.className = "alsaab-admin-channel-inline-btn";
    link.href = websiteUrl;
    link.innerText = "فتح تركيبات المواقع";

    target.insertAdjacentElement("afterend", link);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", cleanAndAttach);
  } else {
    cleanAndAttach();
  }

  setTimeout(cleanAndAttach, 300);
  setTimeout(cleanAndAttach, 900);
})();
</script>
<!-- ALSAAB_ADMIN_CHANNEL_BUTTONS_FINAL_FIX_MARKER END -->
            """.replace("__WEBSITE_URL__", json.dumps(website_url))

            html = html.replace("</body>", script + "\n</body>", 1)
            response.set_data(html)

            return response

        except Exception as error:
            print(f"ADMIN CHANNEL BUTTONS FINAL FIX ERROR ❌ {error}", flush=True)
            return response

    app.after_request(admin_channel_buttons_final_fix)
    # ===== ALSAAB_ADMIN_CHANNEL_BUTTONS_FINAL_FIX END =====

