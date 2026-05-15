from flask import request, jsonify
import os
import re
import time


def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def register_smart_link_protection_routes(app):
    if getattr(app, "alsaab_smart_link_protection_registered", False):
        return

    app.alsaab_smart_link_protection_registered = True

    def _normalize_ref(value):
        value = str(value or "").strip()

        if value.lower() == "alsaab":
            return "alsaab"

        value = re.sub(r"[^a-zA-Z0-9_\-]", "", value).upper()
        return value

    def _walk_dicts(value):
        items = []

        def walk(x):
            if isinstance(x, dict):
                items.append(x)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(value)
        return items

    def _get_value(obj, keys):
        if not isinstance(obj, dict):
            return ""

        lower = {str(k).strip().lower(): v for k, v in obj.items()}

        for key in keys:
            k = str(key).strip().lower()
            if k in lower and str(lower[k] or "").strip():
                return str(lower[k] or "").strip()

        return ""

    def _extract_status(result):
        if not isinstance(result, dict):
            return ""

        statuses = []

        for item in _walk_dicts(result):
            # Subscription-like records
            if any(str(k).lower() in ["subscription_status", "current_package", "plan_name", "package_amount"] for k in item.keys()):
                statuses.append(_get_value(item, [
                    "subscription_status",
                    "Subscription Status",
                    "Subscription Sat",
                    "status",
                    "Status",
                    "state",
                ]))

            # Partner/account-like records
            if any(str(k).lower() in ["partner_status", "account_status", "client_status"] for k in item.keys()):
                statuses.append(_get_value(item, [
                    "partner_status",
                    "account_status",
                    "client_status",
                    "status",
                    "Status",
                ]))

        statuses = [s for s in statuses if s]

        if not statuses:
            return ""

        negative_words = [
            "suspended",
            "cancelled",
            "canceled",
            "inactive",
            "expired",
            "deleted",
            "disabled",
            "unpaid",
            "past_due",
            "payment_failed",
            "failed",
            "hold",
            "موقوف",
            "ملغي",
            "منتهي",
            "غير فعال",
        ]

        for s in statuses:
            raw = s.lower()
            if any(word in raw for word in negative_words):
                return s

        return statuses[0]

    def _is_blocked_status(status):
        raw = str(status or "").strip().lower()

        if not raw:
            return False

        blocked = [
            "suspended",
            "cancelled",
            "canceled",
            "inactive",
            "expired",
            "deleted",
            "disabled",
            "unpaid",
            "past_due",
            "payment_failed",
            "failed",
            "hold",
            "موقوف",
            "ملغي",
            "منتهي",
            "غير فعال",
        ]

        return any(x in raw for x in blocked)

    def _get_link_status(ref):
        ref = _normalize_ref(ref)

        if not ref or ref == "alsaab":
            return {
                "smart_ref": ref,
                "is_active": True,
                "status": "active",
                "reason": "",
            }

        cache = getattr(app, "alsaab_smart_link_status_cache", None)
        if cache is None:
            cache = {}
            setattr(app, "alsaab_smart_link_status_cache", cache)

        now = time.time()
        cached = cache.get(ref)

        if cached and now - cached.get("ts", 0) < 180:
            return cached.get("data") or {}

        try:
            database = _db()

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "client_dashboard_data",
                    "partner_id": ref,
                    "client_id": ref,
                    "source": "smart_link_protection",
                },
                label="smart_link_protection_client_dashboard_data",
            )

            status = _extract_status(result)
            is_blocked = _is_blocked_status(status)

            data = {
                "smart_ref": ref,
                "is_active": not is_blocked,
                "status": status or "unknown",
                "reason": "subscription_or_account_not_active" if is_blocked else "",
            }

            cache[ref] = {
                "ts": now,
                "data": data,
            }

            return data

        except Exception as error:
            print(f"SMART LINK STATUS ERROR ❌ {error}", flush=True)

            # لا نوقف الرابط بسبب خطأ مؤقت في جلب البيانات.
            return {
                "smart_ref": ref,
                "is_active": True,
                "status": "unknown",
                "reason": "status_lookup_failed",
            }

    def smart_link_status():
        ref = (
            request.args.get("ref")
            or request.args.get("partner_id")
            or request.args.get("client_id")
            or request.args.get("aid")
            or ""
        )

        data = _get_link_status(ref)
        return jsonify({
            "status": "success",
            **data,
        })

    def protect_smart_chat():
        if request.path != "/chat" or request.method != "POST":
            return None

        try:
            payload = request.get_json(silent=True)

            if not isinstance(payload, dict):
                return None

            ref = (
                payload.get("smart_link_ref")
                or payload.get("context_partner_id")
                or payload.get("client_context_id")
                or payload.get("source_partner_id")
                or payload.get("ref")
                or ""
            )

            ref = _normalize_ref(ref)

            if not ref or ref == "alsaab":
                return None

            link_status = _get_link_status(ref)

            if not link_status.get("is_active", True):
                return jsonify({
                    "status": "inactive",
                    "reply": "هذا الحساب غير مفعل حالياً. يرجى التواصل مع فريق الصعب لمعرفة التفاصيل.",
                    "smart_ref": ref,
                    "account_status": link_status.get("status", ""),
                })

        except Exception as error:
            print(f"SMART LINK PROTECTION CHAT ERROR ❌ {error}", flush=True)

        return None

    def smart_link_protection_injector(response):
        try:
            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type and "javascript" not in content_type and request.path != "/widget.js":
                return response

            body = response.get_data(as_text=True)

            if not body or "ALSAAB_SMART_LINK_PROTECTION_CLIENT_V1" in body:
                return response

            js = r'''
/* ALSAAB_SMART_LINK_PROTECTION_CLIENT_V1 START */
(function(){
  try{
    if(window.__ALSAAB_SMART_LINK_PROTECTION_CLIENT_V1__) return;
    window.__ALSAAB_SMART_LINK_PROTECTION_CLIENT_V1__ = true;

    function getParam(name){
      try{
        return new URLSearchParams(location.search || "").get(name) || "";
      }catch(e){
        return "";
      }
    }

    function cleanRef(value){
      value = String(value || "").trim().replace(/[^a-zA-Z0-9_\-]/g, "");
      if(value.toLowerCase() === "alsaab") return "alsaab";
      return value.toUpperCase();
    }

    function getRef(){
      var ref = cleanRef(getParam("ref") || getParam("aid") || getParam("client_id") || getParam("partner_id") || "");

      if(ref) return ref;

      try{
        return cleanRef(sessionStorage.getItem("alsaab_smart_ref") || localStorage.getItem("alsaab_smart_ref") || "");
      }catch(e){
        return "";
      }
    }

    function statusEndpoint(ref){
      if(location.hostname.indexOf("onrender.com") !== -1){
        return "/smart-link-status?ref=" + encodeURIComponent(ref);
      }

      return "https://alsaab-ai.onrender.com/smart-link-status?ref=" + encodeURIComponent(ref);
    }

    function blockUi(data){
      var card = document.querySelector(".alsaab-smart-card") || document.getElementById("alsaabSmartChatOverlay");

      if(!card) return;

      var warning = document.createElement("div");
      warning.className = "alsaab-smart-link-blocked";
      warning.innerHTML =
        "<strong>هذا الحساب غير مفعل حالياً.</strong><br>" +
        "يرجى التواصل مع فريق الصعب لمعرفة التفاصيل.";

      card.insertBefore(warning, card.firstChild);

      Array.prototype.slice.call(document.querySelectorAll(".alsaab-smart-form input, .alsaab-smart-form button, .alsaab-smart-quick button, .alsaab-smart-money"))
        .forEach(function(el){
          el.disabled = true;
          el.style.opacity = ".45";
          el.style.pointerEvents = "none";
        });
    }

    function injectStyle(){
      if(document.getElementById("alsaabSmartLinkProtectionStyle")) return;

      var style = document.createElement("style");
      style.id = "alsaabSmartLinkProtectionStyle";
      style.innerHTML = `
        .alsaab-smart-link-blocked{
          margin:14px;
          padding:16px;
          border:1px solid rgba(255,120,120,.45);
          background:rgba(160,30,30,.16);
          color:#ffdede;
          border-radius:16px;
          line-height:1.8;
          text-align:center;
          font-family:Arial,Tahoma,sans-serif;
          font-size:16px;
        }
      `;

      document.head.appendChild(style);
    }

    function check(){
      var ref = getRef();

      if(!ref || ref === "alsaab") return;

      fetch(statusEndpoint(ref))
        .then(function(r){ return r.json(); })
        .then(function(data){
          if(data && data.status === "success" && data.is_active === false){
            injectStyle();
            setTimeout(function(){ blockUi(data); }, 500);
            setTimeout(function(){ blockUi(data); }, 1500);
          }
        })
        .catch(function(){});
    }

    if(document.readyState === "loading"){
      document.addEventListener("DOMContentLoaded", function(){
        setTimeout(check, 500);
      });
    }else{
      setTimeout(check, 500);
    }
  }catch(e){}
})();
/* ALSAAB_SMART_LINK_PROTECTION_CLIENT_V1 END */
'''

            if "text/html" in content_type and "</body>" in body:
                body = body.replace("</body>", "<script>\n" + js + "\n</script>\n</body>", 1)
                response.set_data(body)
                return response

            if "javascript" in content_type or request.path == "/widget.js":
                body = body + "\n\n" + js + "\n"
                response.set_data(body)
                return response

            return response

        except Exception as error:
            print(f"SMART LINK PROTECTION INJECTOR ERROR ❌ {error}", flush=True)
            return response

    existing_rules = {str(rule.rule) for rule in app.url_map.iter_rules()}

    if "/smart-link-status" not in existing_rules:
        app.add_url_rule(
            "/smart-link-status",
            "smart_link_status",
            smart_link_status,
            methods=["GET"],
        )

    app.before_request(protect_smart_chat)
    app.after_request(smart_link_protection_injector)
