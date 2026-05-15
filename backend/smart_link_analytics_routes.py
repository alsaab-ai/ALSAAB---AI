from flask import request, jsonify, make_response
import os


def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def _cors_response(data=None, status_code=200):
    if data is None:
        response = make_response("", status_code)
    else:
        response = jsonify(data)
        response.status_code = status_code

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


def register_smart_link_analytics_routes(app):
    if getattr(app, "alsaab_smart_link_analytics_registered", False):
        return

    app.alsaab_smart_link_analytics_registered = True

    def smart_link_event():
        if request.method == "OPTIONS":
            return _cors_response(None, 204)

        try:
            database = _db()
            payload = request.get_json(silent=True) or request.form.to_dict() or request.args.to_dict() or {}

            smart_ref = (
                payload.get("smart_ref")
                or payload.get("ref")
                or payload.get("partner_id")
                or payload.get("client_id")
                or ""
            )

            if not smart_ref:
                return _cors_response({"status": "error", "message": "smart_ref/ref is required"}, 400)

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "smart_link_event_log",
                    "smart_ref": smart_ref,
                    "ref": smart_ref,
                    "partner_id": payload.get("partner_id") or smart_ref,
                    "client_id": payload.get("client_id") or smart_ref,
                    "event_type": payload.get("event_type") or "unknown",
                    "source": payload.get("source") or "smart_link",
                    "session_id": payload.get("session_id") or "",
                    "page_url": payload.get("page_url") or "",
                    "referrer_url": payload.get("referrer_url") or "",
                    "message": payload.get("message") or "",
                    "user_agent": request.headers.get("User-Agent", ""),
                },
                label="smart_link_event_log",
            )

            return _cors_response(result)

        except Exception as error:
            print(f"SMART LINK EVENT ERROR ❌ {error}", flush=True)
            return _cors_response({"status": "error", "message": str(error)}, 500)

    def client_smart_link_summary():
        if request.method == "OPTIONS":
            return _cors_response(None, 204)

        try:
            database = _db()

            smart_ref = (
                request.args.get("partner_id")
                or request.args.get("client_id")
                or request.args.get("ref")
                or ""
            )

            if not smart_ref:
                return _cors_response({"status": "error", "message": "partner_id/ref is required"}, 400)

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "smart_link_summary_get",
                    "smart_ref": smart_ref,
                    "ref": smart_ref,
                    "partner_id": smart_ref,
                    "client_id": smart_ref,
                },
                label="smart_link_summary_get",
            )

            return _cors_response(result)

        except Exception as error:
            print(f"CLIENT SMART LINK SUMMARY ERROR ❌ {error}", flush=True)
            return _cors_response({"status": "error", "message": str(error)}, 500)

    def smart_link_analytics_script_injector(response):
        try:
            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type and "javascript" not in content_type and request.path != "/widget.js":
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_SMART_LINK_ANALYTICS_CLIENT_V1" in html:
                return response

            js = r'''
/* ALSAAB_SMART_LINK_ANALYTICS_CLIENT_V1 START */
(function(){
  try{
    if(window.__ALSAAB_SMART_LINK_ANALYTICS_CLIENT_V1__) return;
    window.__ALSAAB_SMART_LINK_ANALYTICS_CLIENT_V1__ = true;

    function getParam(name){
      try{
        return new URLSearchParams(location.search || "").get(name) || "";
      }catch(e){
        return "";
      }
    }

    function cleanRef(value){
      value = String(value || "").trim();
      value = value.replace(/[^a-zA-Z0-9_\-]/g, "");
      if(value.toLowerCase() === "alsaab") return "alsaab";
      return value.toUpperCase();
    }

    function getRef(){
      var ref = getParam("ref") || getParam("aid") || getParam("client_id") || getParam("partner_id") || "";
      ref = cleanRef(ref);

      if(ref) return ref;

      try{
        return cleanRef(sessionStorage.getItem("alsaab_smart_ref") || localStorage.getItem("alsaab_smart_ref") || "");
      }catch(e){
        return "";
      }
    }

    function getSource(){
      var src = getParam("src") || getParam("source") || "";

      if(src === "wa" || src === "whatsapp"){
        return "whatsapp_redirect";
      }

      return src || "smart_link";
    }

    function getSessionId(ref){
      var key = "alsaab_smart_analytics_session_" + ref;

      try{
        var id = sessionStorage.getItem(key) || localStorage.getItem(key) || "";

        if(!id){
          id = "sl_" + ref + "_" + Date.now() + "_" + Math.random().toString(16).slice(2);
          sessionStorage.setItem(key, id);
          localStorage.setItem(key, id);
        }

        return id;
      }catch(e){
        return "sl_" + ref + "_" + Date.now();
      }
    }

    function endpoint(){
      if(location.hostname.indexOf("onrender.com") !== -1){
        return "/smart-link-event";
      }

      return "https://alsaab-ai.onrender.com/smart-link-event";
    }

    function classifyMessage(text){
      text = String(text || "").toLowerCase();

      if(
        text.indexOf("رابط الدفع") !== -1 ||
        text.indexOf("الدفع") !== -1 ||
        text.indexOf("اشتري") !== -1 ||
        text.indexOf("أشتري") !== -1 ||
        text.indexOf("شراء") !== -1
      ){
        return "payment_request";
      }

      if(
        text.indexOf("شخص") !== -1 ||
        text.indexOf("موظف") !== -1 ||
        text.indexOf("انسان") !== -1 ||
        text.indexOf("إنسان") !== -1 ||
        text.indexOf("تواصل") !== -1 ||
        text.indexOf("اتصل") !== -1
      ){
        return "human_request";
      }

      if(
        text.indexOf("دخل") !== -1 ||
        text.indexOf("فلوس") !== -1 ||
        text.indexOf("عمولة") !== -1 ||
        text.indexOf("شراكة") !== -1 ||
        text.indexOf("فرصة") !== -1 ||
        text.indexOf("ربح") !== -1
      ){
        return "income_request";
      }

      return "chat_message";
    }

    function logEvent(eventType, message){
      var ref = getRef();

      if(!ref) return;

      var source = getSource();
      var sessionId = getSessionId(ref);

      var payload = {
        smart_ref: ref,
        ref: ref,
        partner_id: ref,
        client_id: ref,
        event_type: eventType,
        source: source,
        session_id: sessionId,
        page_url: location.href,
        referrer_url: document.referrer || "",
        message: message || ""
      };

      try{
        fetch(endpoint(), {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify(payload),
          keepalive: true
        }).catch(function(){});
      }catch(e){}
    }

    var refFromUrl = cleanRef(getParam("ref") || getParam("aid") || getParam("client_id") || getParam("partner_id") || "");

    if(refFromUrl){
      var visitKey = "alsaab_smart_visit_logged_" + refFromUrl + "_" + location.pathname + location.search;

      try{
        if(!sessionStorage.getItem(visitKey)){
          sessionStorage.setItem(visitKey, "1");
          logEvent("visit", "");
        }
      }catch(e){
        logEvent("visit", "");
      }
    }

    var originalFetch = window.fetch;

    if(typeof originalFetch === "function"){
      window.fetch = function(input, init){
        try{
          var url = "";

          if(typeof input === "string"){
            url = input;
          }else if(input && input.url){
            url = input.url;
          }

          if(url && url.indexOf("/chat") !== -1 && init && init.body && typeof init.body === "string"){
            var data = JSON.parse(init.body);
            var msg = data.message || "";
            var eventType = classifyMessage(msg);

            logEvent("chat_message", msg);

            if(eventType !== "chat_message"){
              logEvent(eventType, msg);
            }
          }
        }catch(e){}

        return originalFetch.call(this, input, init);
      };
    }
  }catch(e){}
})();
/* ALSAAB_SMART_LINK_ANALYTICS_CLIENT_V1 END */
'''

            if "text/html" in content_type and "</body>" in html:
                html = html.replace("</body>", "<script>\n" + js + "\n</script>\n</body>", 1)
                response.set_data(html)
                return response

            if "javascript" in content_type or request.path == "/widget.js":
                html = html + "\n\n" + js + "\n"
                response.set_data(html)
                return response

            return response

        except Exception as error:
            print(f"SMART LINK ANALYTICS SCRIPT INJECTOR ERROR ❌ {error}", flush=True)
            return response

    def smart_link_dashboard_summary_injector(response):
        try:
            if request.path != "/client-dashboard":
                return response

            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type:
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_SMART_LINK_SUMMARY_DASHBOARD_V1" in html:
                return response

            section = r'''
<!-- ALSAAB_SMART_LINK_SUMMARY_DASHBOARD_V1 START -->
<div id="alsaabSmartLinkSummarySection" class="alsaab-smart-summary-section" dir="rtl">
  <h2>أداء مدخل واتساب الذكي</h2>
  <p>هذه الأرقام توضح أداء رابط موظف المبيعات الذكي الخاص بحسابك.</p>

  <div class="alsaab-smart-summary-grid">
    <div class="alsaab-smart-summary-card"><span id="smartVisits">-</span><small>زيارات الرابط</small></div>
    <div class="alsaab-smart-summary-card"><span id="smartConversations">-</span><small>محادثات</small></div>
    <div class="alsaab-smart-summary-card"><span id="smartPaymentRequests">-</span><small>طلبات دفع</small></div>
    <div class="alsaab-smart-summary-card"><span id="smartHumanRequests">-</span><small>طلبات رد بشري</small></div>
    <div class="alsaab-smart-summary-card"><span id="smartIncomeRequests">-</span><small>فرص دخل إضافي</small></div>
    <div class="alsaab-smart-summary-card"><span id="smartMessages">-</span><small>رسائل</small></div>
  </div>

  <div id="alsaabSmartLatestEvents" class="alsaab-smart-latest-events" style="display:none!important;"></div>
</div>

<style>
.alsaab-smart-summary-section{
  max-width:1100px;
  margin:22px auto;
  padding:22px;
  background:#111;
  border:1px solid rgba(215,184,90,.45);
  border-radius:22px;
  color:#f5f0df;
  font-family:Arial,Tahoma,sans-serif;
}

.alsaab-smart-summary-section h2{
  color:#d7b85a;
  margin-top:0;
  font-size:28px;
  font-weight:900;
}

.alsaab-smart-summary-section p{
  color:#d8cfad;
  line-height:1.8;
}

.alsaab-smart-summary-grid{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:12px;
  margin-top:14px;
}

.alsaab-smart-summary-card{
  background:#0b0b0b;
  border:1px solid rgba(215,184,90,.22);
  border-radius:16px;
  padding:16px;
  text-align:center;
}

.alsaab-smart-summary-card span{
  display:block;
  font-size:28px;
  font-weight:900;
  color:#d7b85a;
}

.alsaab-smart-summary-card small{
  color:#e8dfc2;
}

.alsaab-smart-latest-events{
  margin-top:16px;
  background:#0b0b0b;
  border:1px solid rgba(255,255,255,.08);
  border-radius:16px;
  padding:14px;
  color:#e8dfc2;
  line-height:1.8;
}

@media(max-width:720px){
  .alsaab-smart-summary-grid{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }
}
</style>

<script>
(function(){
  try{
    function findPartnerId(){
      var text = document.body.innerText || "";
      var match = text.match(/ALS-P\d{5,}/i);
      return match && match[0] ? match[0].toUpperCase() : "";
    }

    function loadSummary(){
      var partnerId = findPartnerId();
      if(!partnerId) return;

      fetch("/client/smart-link-summary?partner_id=" + encodeURIComponent(partnerId))
        .then(function(r){ return r.json(); })
        .then(function(data){
          var summary = data.summary || {};

          document.getElementById("smartVisits").innerText = summary.visits || 0;
          document.getElementById("smartConversations").innerText = summary.conversations || 0;
          document.getElementById("smartPaymentRequests").innerText = summary.payment_requests || 0;
          document.getElementById("smartHumanRequests").innerText = summary.human_requests || 0;
          document.getElementById("smartIncomeRequests").innerText = summary.income_requests || 0;
          document.getElementById("smartMessages").innerText = summary.messages || 0;

          // ALSAAB_HIDE_RAW_VISIT_EVENTS_V1 START
          // لا نعرض الأحداث الخام مثل visit للعميل.
          // الأرقام تكفي في لوحة العميل، والتفاصيل تبقى داخل الشيت/الأدمن.
          var latestBox = document.getElementById("alsaabSmartLatestEvents");
          if(latestBox){
            latestBox.style.display = "none";
            latestBox.innerHTML = "";
          }
          return;
          // ALSAAB_HIDE_RAW_VISIT_EVENTS_V1 END

          var latestBox = document.getElementById("alsaabSmartLatestEvents");
          var latest = summary.latest_events || [];

          if(!latest.length){
            latestBox.innerText = "لا توجد أحداث حتى الآن.";
            return;
          }

          latestBox.innerHTML = latest.map(function(item){
            var msg = String(item.message || "").slice(0,90);
            return "<div>• " + (item.event_type || "-") + " — " + msg + "</div>";
          }).join("");
        })
        .catch(function(){
          var latestBox = document.getElementById("alsaabSmartLatestEvents");
          if(latestBox) latestBox.innerText = "تعذر تحميل أرقام الأداء حالياً.";
        });
    }

    function moveSection(){
      var smartLinkSection = document.getElementById("alsaabSmartLinkDashboardSection");
      var summarySection = document.getElementById("alsaabSmartLinkSummarySection");

      if(smartLinkSection && summarySection && smartLinkSection.parentNode){
        smartLinkSection.parentNode.insertBefore(summarySection, smartLinkSection.nextSibling);
      }
    }

    setTimeout(loadSummary, 500);
    setTimeout(moveSection, 700);
  }catch(e){}
})();
</script>
<!-- ALSAAB_SMART_LINK_SUMMARY_DASHBOARD_V1 END -->
'''

            if "</body>" in html:
                html = html.replace("</body>", section + "\n</body>", 1)
                response.set_data(html)

            return response

        except Exception as error:
            print(f"SMART LINK DASHBOARD SUMMARY INJECTOR ERROR ❌ {error}", flush=True)
            return response

    existing_rules = {str(rule.rule) for rule in app.url_map.iter_rules()}

    if "/smart-link-event" not in existing_rules:
        app.add_url_rule(
            "/smart-link-event",
            "smart_link_event",
            smart_link_event,
            methods=["GET", "POST", "OPTIONS"],
        )

    if "/client/smart-link-summary" not in existing_rules:
        app.add_url_rule(
            "/client/smart-link-summary",
            "client_smart_link_summary",
            client_smart_link_summary,
            methods=["GET", "OPTIONS"],
        )

    app.after_request(smart_link_analytics_script_injector)
    app.after_request(smart_link_dashboard_summary_injector)
