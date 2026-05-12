from flask import request, jsonify
import os


def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def register_bot_control_routes(app):
    if getattr(app, "alsaab_bot_control_registered", False):
        return

    app.alsaab_bot_control_registered = True

    def _get_partner_id_from_payload(payload):
        return (
            payload.get("client_id")
            or payload.get("partner_id")
            or payload.get("account_id")
            or ""
        )

    def get_control(partner_id):
        database = _db()
        result = database.post_to_google_sheet_json(
            {
                "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                "action": "bot_control_get",
                "partner_id": partner_id,
                "client_id": partner_id,
            },
            label="bot_control_get",
        )
        return result if isinstance(result, dict) else {}

    def update_control(partner_id, status, reason, actor, source):
        database = _db()
        partner_id = database.normalize_partner_id(partner_id)
        return database.post_to_google_sheet_json(
            {
                "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                "action": "bot_control_update",
                "partner_id": partner_id,
                "client_id": partner_id,
                "bot_status": status,
                "reason": reason,
                "actor": actor,
                "source": source,
            },
            label="bot_control_update",
        )

    def client_bot_control_status():
        partner_id = request.args.get("partner_id", "").strip().upper()

        if not partner_id:
            return jsonify({"status": "error", "message": "partner_id is required"}), 400

        return jsonify(get_control(partner_id))

    def client_bot_control_update():
        partner_id = request.form.get("partner_id", "").strip().upper()
        bot_status = request.form.get("bot_status", "on").strip()
        reason = request.form.get("reason", "").strip()

        if not partner_id:
            return "partner_id is required", 400

        result = update_control(
            partner_id=partner_id,
            status=bot_status,
            reason=reason,
            actor="client",
            source="client_dashboard",
        )

        html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>تحديث حالة الموظف الذكي</title>
<style>
body{background:#0b0b0b;color:#fff;font-family:Arial;padding:30px}
.card{max-width:760px;margin:auto;background:#111;border:1px solid rgba(215,184,90,.45);border-radius:20px;padding:24px}
h1{color:#d7b85a}
a{display:inline-block;margin-top:15px;color:#f0cc68;text-decoration:none;border:1px solid rgba(215,184,90,.45);padding:10px 14px;border-radius:999px}
</style>
</head>
<body>
<div class="card">
<h1>تم تحديث حالة الموظف الذكي ✅</h1>
<p>الحالة الجديدة: <strong>{{ status }}</strong></p>
<p>ملاحظة: إذا اخترت الإيقاف أو التحويل البشري، لن يرد الموظف الذكي تلقائياً حتى يتم تشغيله مرة أخرى.</p>
<a href="javascript:history.back()">رجوع إلى لوحة العميل</a>
</div>
</body>
</html>
        """
        from flask import render_template_string
        return render_template_string(html, status=result.get("bot_status", bot_status))

    def chat_bot_control_guard():
        if request.path != "/chat" or request.method != "POST":
            return None

        try:
            payload = request.get_json(silent=True) or {}

            channel = str(payload.get("channel") or "").lower()
            source = str(payload.get("source") or "").lower()

            if channel in ["owner_advisory", "advisory"] or source in ["owner_advisory", "advisory"]:
                return None

            partner_id = _get_partner_id_from_payload(payload)

            if not partner_id:
                return None

            control = get_control(partner_id)
            bot_status = str(control.get("bot_status") or "on").lower()

            if bot_status == "on":
                return None

            if bot_status == "off":
                reply = "الموظف الذكي متوقف مؤقتاً لهذا الحساب. سيتم الرد عليك من فريق العمل."
            else:
                reply = "تم تحويل المحادثة للرد البشري. سيتم التواصل معك من فريق العمل."

            return jsonify({
                "status": "bot_control_blocked",
                "bot_status": bot_status,
                "reply": reply,
                "message": reply
            })

        except Exception as error:
            print(f"BOT CONTROL GUARD ERROR ❌ {error}", flush=True)
            return None

    def bot_control_injector(response):
        try:
            if request.path != "/client-dashboard":
                return response

            if "text/html" not in response.headers.get("Content-Type", ""):
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_BOT_CONTROL_UI_INJECTED" in html:
                return response

            section = '''
<!-- ALSAAB_BOT_CONTROL_UI_INJECTED START -->
<div id="alsaabBotControlSection" class="alsaab-bot-control-section" dir="rtl">
  <h2>حالة موظف المبيعات الذكي</h2>
  <p>
    يمكنك تشغيل أو إيقاف الموظف الذكي مؤقتاً. عند اختيار التحويل البشري، سيتوقف الرد التلقائي حتى تعيد تشغيله.
  </p>

  <div id="alsaabBotCurrentStatus" class="alsaab-bot-status">الحالة الحالية: جاري التحميل...</div>

  <form method="POST" action="/client/bot-control-update">
    <input type="hidden" name="partner_id" id="alsaabBotControlPartnerId">

    <label>سبب التغيير / ملاحظة اختيارية</label>
    <input name="reason" placeholder="مثال: العميل طلب شخص حقيقي أو نحتاج نرد يدوياً.">

    <div class="alsaab-bot-actions">
      <button name="bot_status" value="on" type="submit">تشغيل الموظف الذكي</button>
      <button name="bot_status" value="off" type="submit">إيقاف مؤقت</button>
      <button name="bot_status" value="human_handoff" type="submit">تحويل للرد البشري</button>
    </div>
  </form>
</div>

<style>
.alsaab-bot-control-section{max-width:1100px;margin:22px auto;padding:22px;background:#111;border:1px solid rgba(215,184,90,.45);border-radius:22px;color:#f5f0df;font-family:Arial,Tahoma,sans-serif}
.alsaab-bot-control-section h2{color:#d7b85a;margin-top:0;font-size:28px;font-weight:900}
.alsaab-bot-control-section p,.alsaab-bot-status{color:#d8cfad;line-height:1.8}
.alsaab-bot-control-section label{display:block;margin-top:13px;margin-bottom:6px;color:#d7b85a;font-weight:800}
.alsaab-bot-control-section input{width:100%;box-sizing:border-box;background:#0b0b0b;color:#fff;border:1px solid rgba(215,184,90,.35);border-radius:14px;padding:12px;outline:none}
.alsaab-bot-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
.alsaab-bot-actions button{border:1px solid rgba(215,184,90,.75);background:#111;color:#f0cc68;border-radius:999px;padding:12px 18px;font-weight:900;cursor:pointer}
.alsaab-bot-actions button:first-child{background:linear-gradient(135deg,#d7b85a,#a88425);color:#0b0b0b}
</style>

<script>
(function(){
  var section=document.getElementById("alsaabBotControlSection");
  var input=document.getElementById("alsaabBotControlPartnerId");
  var statusBox=document.getElementById("alsaabBotCurrentStatus");
  if(!section||!input)return;

  var text=document.body.innerText||"";
  var match=text.match(/ALS-P\\d{5,}/i);
  if(match&&match[0]) input.value=match[0].toUpperCase();

  if(input.value && statusBox){
    fetch("/client/bot-control-status?partner_id="+encodeURIComponent(input.value))
      .then(function(r){return r.json();})
      .then(function(data){
        statusBox.innerText = "الحالة الحالية: " + (data.bot_status || "on");
      })
      .catch(function(){statusBox.innerText="الحالة الحالية: غير معروفة";});
  }

  var website=document.getElementById("alsaabWebsiteInstallSection");
  if(website && website.parentNode){
    website.parentNode.insertBefore(section, website);
    return;
  }

  var candidates=Array.prototype.slice.call(document.querySelectorAll("div,section,article"));
  var whatsappContainer=null;

  for(var i=0;i<candidates.length;i++){
    var t=(candidates[i].innerText||"").trim();
    if(t.indexOf("WhatsApp")!==-1||t.indexOf("واتساب")!==-1||t.indexOf("إعداد WhatsApp")!==-1){
      if(candidates[i].contains(section)) continue;
      whatsappContainer=candidates[i];
      break;
    }
  }

  if(whatsappContainer&&whatsappContainer.parentNode){
    whatsappContainer.parentNode.insertBefore(section, whatsappContainer.nextSibling);
  }
})();
</script>
<!-- ALSAAB_BOT_CONTROL_UI_INJECTED END -->
            '''

            html = html.replace("</body>", section + "\n</body>", 1)
            response.set_data(html)
            return response

        except Exception as error:
            print(f"BOT CONTROL UI INJECTOR ERROR ❌ {error}", flush=True)
            return response

    existing_rules = {str(rule.rule) for rule in app.url_map.iter_rules()}

    if "/client/bot-control-status" not in existing_rules:
        app.add_url_rule(
            "/client/bot-control-status",
            "client_bot_control_status",
            client_bot_control_status,
            methods=["GET"],
        )

    if "/client/bot-control-update" not in existing_rules:
        app.add_url_rule(
            "/client/bot-control-update",
            "client_bot_control_update",
            client_bot_control_update,
            methods=["POST"],
        )

    app.before_request(chat_bot_control_guard)
    app.after_request(bot_control_injector)
