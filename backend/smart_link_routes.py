from flask import request, jsonify
import re


SMART_LINK_JS = r"""
/* ALSAAB_SMART_LINK_CAPTURE_V1 START */
(function () {
  try {
    if (window.__ALSAAB_SMART_LINK_CAPTURE_V1__) return;
    window.__ALSAAB_SMART_LINK_CAPTURE_V1__ = true;

    function clean(value) {
      value = String(value || "").trim();
      value = value.replace(/[^a-zA-Z0-9_\-]/g, "");
      return value;
    }

    function normalizeRef(value) {
      value = clean(value);
      if (!value) return "";
      if (value.toLowerCase() === "alsaab") return "alsaab";
      value = value.toUpperCase();
      if (/^ALS-P\d{5,}$/.test(value)) return value;
      return value;
    }

    function getParam(name) {
      try {
        var params = new URLSearchParams(window.location.search || "");
        return params.get(name) || "";
      } catch (e) {
        return "";
      }
    }

    var incomingRef =
      getParam("ref") ||
      getParam("aid") ||
      getParam("client_id") ||
      getParam("partner_id") ||
      "";

    var incomingSource =
      getParam("src") ||
      getParam("source") ||
      "";

    var smartRef = normalizeRef(incomingRef);

    if (smartRef) {
      localStorage.setItem("alsaab_smart_ref", smartRef);
      sessionStorage.setItem("alsaab_smart_ref", smartRef);
    } else {
      smartRef =
        normalizeRef(sessionStorage.getItem("alsaab_smart_ref")) ||
        normalizeRef(localStorage.getItem("alsaab_smart_ref"));
    }

    var source = clean(incomingSource || sessionStorage.getItem("alsaab_smart_source") || localStorage.getItem("alsaab_smart_source"));

    if (source === "wa" || source === "whatsapp") {
      source = "whatsapp_redirect";
    }

    if (smartRef && !source) {
      source = "smart_link";
    }

    if (source) {
      localStorage.setItem("alsaab_smart_source", source);
      sessionStorage.setItem("alsaab_smart_source", source);
    }

    window.ALSAAB_SMART_LINK = {
      ref: smartRef,
      source: source,
      page_url: window.location.href
    };

    var originalFetch = window.fetch;

    if (typeof originalFetch === "function") {
      window.fetch = function (input, init) {
        try {
          var url = "";

          if (typeof input === "string") {
            url = input;
          } else if (input && input.url) {
            url = input.url;
          }

          if (url && url.indexOf("/chat") !== -1) {
            init = init || {};

            var body = init.body;

            if (body && typeof body === "string") {
              var payload = JSON.parse(body);

              if (smartRef) {
                payload.smart_link_ref = payload.smart_link_ref || smartRef;
                payload.context_partner_id = payload.context_partner_id || smartRef;
                payload.client_context_id = payload.client_context_id || smartRef;
                payload.source_partner_id = payload.source_partner_id || smartRef;
                payload.ref = payload.ref || smartRef;
              }

              if (source) {
                payload.entry_source = payload.entry_source || source;
                payload.source = payload.source || source;
              }

              payload.page_url = payload.page_url || window.location.href;
              payload.referrer_url = payload.referrer_url || document.referrer || "";

              init.body = JSON.stringify(payload);
            }
          }
        } catch (e) {}

        return originalFetch.call(this, input, init);
      };
    }
  } catch (e) {}
})();

/* ALSAAB_SMART_CHAT_UI_V1 START */
(function () {
  try {
    if (window.__ALSAAB_SMART_CHAT_UI_V1__) return;
    window.__ALSAAB_SMART_CHAT_UI_V1__ = true;

    function onReady(fn) {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", fn);
      } else {
        fn();
      }
    }

    function getSmartRef() {
      try {
        var data = window.ALSAAB_SMART_LINK || {};
        return data.ref || sessionStorage.getItem("alsaab_smart_ref") || localStorage.getItem("alsaab_smart_ref") || "";
      } catch (e) {
        return "";
      }
    }

    function getSmartSource() {
      try {
        var data = window.ALSAAB_SMART_LINK || {};
        return data.source || sessionStorage.getItem("alsaab_smart_source") || localStorage.getItem("alsaab_smart_source") || "smart_link";
      } catch (e) {
        return "smart_link";
      }
    }

    function makeSessionId(ref) {
      var key = "alsaab_smart_chat_session_" + ref;
      var existing = localStorage.getItem(key);
      if (existing) return existing;

      var id = "smart_" + ref + "_" + Date.now() + "_" + Math.random().toString(16).slice(2);
      localStorage.setItem(key, id);
      return id;
    }

    function shouldOpenSmartChat(ref) {
      /* ALSAAB_SMART_CHAT_DASHBOARD_EXCLUDE_V1 START */
      if (!ref) return false;

      var path = String(window.location.pathname || "").toLowerCase();

      var blockedPaths = [
        "client-dashboard",
        "partner-dashboard",
        "admin-dashboard",
        "/admin/",
        "/client/",
        "/partner/",
        "dashboard"
      ];

      for (var i = 0; i < blockedPaths.length; i++) {
        if (path.indexOf(blockedPaths[i]) !== -1) {
          return false;
        }
      }

      var params = new URLSearchParams(window.location.search || "");

      // Smart sales chat opens only from the public smart link.
      // Dashboard links use partner_id/client_id and must NOT open the sales chat.
      return Boolean(
        params.get("ref") ||
        params.get("aid")
      );
      /* ALSAAB_SMART_CHAT_DASHBOARD_EXCLUDE_V1 END */
    }

    function addMessage(container, who, text) {
      var item = document.createElement("div");
      item.className = "alsaab-smart-msg " + (who === "user" ? "user" : "bot");
      item.innerHTML = String(text || "").replace(/\n/g, "<br>");
      container.appendChild(item);
      container.scrollTop = container.scrollHeight;
      return item;
    }

    function createSmartChat() {
      var ref = getSmartRef();
      if (!shouldOpenSmartChat(ref)) return;
      if (document.getElementById("alsaabSmartChatOverlay")) return;

      var source = getSmartSource();
      if (source === "wa" || source === "whatsapp") source = "whatsapp_redirect";

      var sessionId = makeSessionId(ref);
      var chatEndpoint = window.location.hostname.indexOf("onrender.com") !== -1
        ? "/chat"
        : "https://alsaab-ai.onrender.com/chat";

      var overlay = document.createElement("div");
      overlay.id = "alsaabSmartChatOverlay";
      overlay.dir = "rtl";
      overlay.innerHTML = `
        <div class="alsaab-smart-shell">
          <div class="alsaab-smart-card">
            <div class="alsaab-smart-head">
              <div>
                <div class="alsaab-smart-title">موظف المبيعات الذكي</div>
                <div class="alsaab-smart-subtitle">مرحباً بك، اكتب طلبك أو اختر من الخيارات السريعة.</div>
              </div>
              <div class="alsaab-smart-top-actions">
                <button type="button" class="alsaab-smart-money" id="alsaabSmartIncomeBtn">💰 أريد فرصة دخل إضافي</button>
                <button type="button" class="alsaab-smart-back" id="alsaabSmartBackBtn">الرجوع إلى واتساب</button>
              </div>
            </div>

            <div class="alsaab-smart-quick">
              <button type="button" data-msg="أريد معرفة الأسعار">أريد معرفة الأسعار</button>
              <button type="button" data-msg="أريد المنتج أو الخدمة الأنسب لي">أريد الأنسب لي</button>
              <button type="button" data-msg="أريد رابط الدفع">أريد رابط الدفع</button>
              <button type="button" data-msg="أريد التحدث مع شخص">أريد التحدث مع شخص</button>
            </div>

            <div class="alsaab-smart-messages" id="alsaabSmartMessages"></div>

            <form class="alsaab-smart-form" id="alsaabSmartForm">
              <input id="alsaabSmartInput" autocomplete="off" placeholder="اكتب رسالتك هنا..." />
              <button type="submit">إرسال</button>
            </form>
          </div>
        </div>
      `;

      var style = document.createElement("style");
      style.innerHTML = `
        #alsaabSmartChatOverlay{
          position:fixed;
          inset:0;
          z-index:2147483000;
          background:rgba(5,5,5,.78);
          backdrop-filter:blur(8px);
          display:flex;
          align-items:center;
          justify-content:center;
          padding:18px;
          box-sizing:border-box;
          font-family:Arial,Tahoma,sans-serif;
        }

        .alsaab-smart-shell{
          width:min(980px,96vw);
          height:min(760px,92vh);
          display:flex;
        }

        .alsaab-smart-card{
          width:100%;
          height:100%;
          background:#0b0b0b;
          color:#fff;
          border:1px solid rgba(215,184,90,.55);
          border-radius:26px;
          box-shadow:0 22px 80px rgba(0,0,0,.55);
          display:flex;
          flex-direction:column;
          overflow:hidden;
        }

        .alsaab-smart-head{
          padding:20px 22px;
          border-bottom:1px solid rgba(215,184,90,.25);
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:12px;
          background:linear-gradient(135deg,#111,#15110a);
        }

        .alsaab-smart-title{
          color:#d7b85a;
          font-size:28px;
          font-weight:900;
        }

        .alsaab-smart-subtitle{
          color:#d9cfaa;
          margin-top:6px;
          font-size:15px;
          line-height:1.6;
        }

        .alsaab-smart-back{
          border:1px solid rgba(215,184,90,.55);
          color:#f0cc68;
          background:#111;
          border-radius:999px;
          padding:10px 14px;
          font-weight:800;
          cursor:pointer;
          white-space:nowrap;
        }

        /* ALSAAB_SMART_INCOME_BUTTON_TOP_V2 START */
        .alsaab-smart-top-actions{
          display:flex;
          flex-direction:column;
          align-items:flex-start;
          gap:9px;
          min-width:190px;
        }

        .alsaab-smart-money{
          border:1px solid rgba(64,220,120,.85)!important;
          color:#061b0e!important;
          background:linear-gradient(135deg,#43e97b,#168a45)!important;
          border-radius:999px;
          padding:11px 15px;
          font-weight:950;
          cursor:pointer;
          white-space:nowrap;
          box-shadow:0 0 22px rgba(67,233,123,.25);
        }

        .alsaab-smart-money:hover{
          transform:translateY(-1px);
          box-shadow:0 0 28px rgba(67,233,123,.38);
        }
        /* ALSAAB_SMART_INCOME_BUTTON_TOP_V2 END */

        .alsaab-smart-quick{
          display:flex;
          gap:10px;
          flex-wrap:wrap;
          padding:14px 18px;
          border-bottom:1px solid rgba(255,255,255,.07);
          background:#0f0f0f;
        }

        .alsaab-smart-quick button{
          border:1px solid rgba(215,184,90,.42);
          color:#f0cc68;
          background:#111;
          border-radius:999px;
          padding:10px 13px;
          font-weight:800;
          cursor:pointer;
        }

        .alsaab-smart-messages{
          flex:1;
          overflow:auto;
          padding:18px;
          display:flex;
          flex-direction:column;
          gap:12px;
        }

        .alsaab-smart-msg{
          max-width:78%;
          padding:13px 15px;
          border-radius:18px;
          line-height:1.75;
          font-size:16px;
          white-space:normal;
        }

        .alsaab-smart-msg.bot{
          align-self:flex-start;
          background:#151515;
          border:1px solid rgba(215,184,90,.22);
          color:#f7f1df;
        }

        .alsaab-smart-msg.user{
          align-self:flex-end;
          background:linear-gradient(135deg,#d7b85a,#aa842a);
          color:#111;
          font-weight:800;
        }

        .alsaab-smart-form{
          display:flex;
          gap:10px;
          padding:16px;
          border-top:1px solid rgba(215,184,90,.25);
          background:#0f0f0f;
        }

        .alsaab-smart-form input{
          flex:1;
          background:#050505;
          border:1px solid rgba(215,184,90,.35);
          color:#fff;
          border-radius:16px;
          padding:14px;
          font-size:16px;
          outline:none;
        }

        .alsaab-smart-form button{
          background:linear-gradient(135deg,#d7b85a,#aa842a);
          color:#111;
          border:0;
          border-radius:16px;
          padding:0 22px;
          font-weight:900;
          cursor:pointer;
        }

        @media(max-width:720px){
          #alsaabSmartChatOverlay{padding:0;}
          .alsaab-smart-shell{width:100vw;height:100vh;}
          .alsaab-smart-card{border-radius:0;border:0;}
          .alsaab-smart-head{align-items:flex-start;flex-direction:column;}
          .alsaab-smart-title{font-size:23px;}
          .alsaab-smart-msg{max-width:92%;font-size:15px;}
          .alsaab-smart-form{padding-bottom:22px;}
        }

        /* Wider existing widget fallback */
        .alsaab-chat-widget,
        .chat-widget,
        #chat-widget,
        #chatContainer,
        .chat-container{
          max-width:920px!important;
        }
      `;

      document.head.appendChild(style);
      document.body.appendChild(overlay);

      var messages = document.getElementById("alsaabSmartMessages");
      var form = document.getElementById("alsaabSmartForm");
      var input = document.getElementById("alsaabSmartInput");
      var backBtn = document.getElementById("alsaabSmartBackBtn");

      addMessage(messages, "bot", "هلا وسهلاً 👋\nأنا موظف المبيعات الذكي. أقدر أساعدك في معرفة التفاصيل، اختيار الأنسب، أو إرسال رابط الدفع.");

      backBtn.addEventListener("click", function () {
        try {
          if (document.referrer && document.referrer.indexOf("whatsapp") !== -1) {
            history.back();
          } else {
            addMessage(messages, "bot", "إذا تحب ترجع لواتساب، ارجع من زر الرجوع في المتصفح أو اطلب التحدث مع شخص وسأساعدك.");
          }
        } catch (e) {
          history.back();
        }
      });

      function send(text) {
        text = String(text || "").trim();
        if (!text) return;

        addMessage(messages, "user", text);
        input.value = "";

        var typing = addMessage(messages, "bot", "جاري التفكير...");

        fetch(chatEndpoint, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            message: text,
            session_id: sessionId,
            smart_link_ref: ref,
            context_partner_id: ref,
            client_context_id: ref,
            source_partner_id: ref,
            ref: ref,
            source: source || "smart_link",
            entry_source: source || "smart_link",
            channel: "smart_link",
            page_url: window.location.href,
            referrer_url: document.referrer || ""
          })
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var reply = data.reply || data.response || data.message || "تم استلام رسالتك.";
          typing.innerHTML = String(reply).replace(/\n/g, "<br>");
          messages.scrollTop = messages.scrollHeight;
        })
        .catch(function () {
          typing.innerHTML = "صار خطأ مؤقت. جرّب مرة ثانية أو اطلب التحدث مع شخص.";
        });
      }

      var incomeBtn = document.getElementById("alsaabSmartIncomeBtn");
      if (incomeBtn) {
        incomeBtn.addEventListener("click", function () {
          send("أريد فرصة دخل إضافي");
        });
      }

      form.addEventListener("submit", function (e) {
        e.preventDefault();
        send(input.value);
      });

      Array.prototype.slice.call(overlay.querySelectorAll(".alsaab-smart-quick button")).forEach(function (btn) {
        btn.addEventListener("click", function () {
          send(btn.getAttribute("data-msg") || btn.innerText);
        });
      });

      setTimeout(function(){ input.focus(); }, 350);
    }

    onReady(createSmartChat);
  } catch (e) {}
})();
/* ALSAAB_SMART_CHAT_UI_V1 END */

/* ALSAAB_SMART_LINK_CAPTURE_V1 END */
"""


def register_smart_link_routes(app):
    if getattr(app, "alsaab_smart_link_registered", False):
        return

    app.alsaab_smart_link_registered = True

    def _normalize_ref(value):
        value = str(value or "").strip()
        value = re.sub(r"[^a-zA-Z0-9_\-]", "", value)

        if value.lower() == "alsaab":
            return "alsaab"

        value = value.upper()

        if re.match(r"^ALS-P\d{5,}$", value):
            return value

        return value

    def smart_link_debug():
        ref = _normalize_ref(
            request.args.get("ref")
            or request.args.get("aid")
            or request.args.get("client_id")
            or request.args.get("partner_id")
            or ""
        )

        source = (
            request.args.get("src")
            or request.args.get("source")
            or ""
        )

        if source in ["wa", "whatsapp"]:
            source = "whatsapp_redirect"

        return jsonify({
            "status": "success",
            "smart_link_ref": ref,
            "source": source,
            "message": "Smart link is readable"
        })

    def smart_link_chat_payload_guard():
        if request.path != "/chat" or request.method != "POST":
            return None

        try:
            payload = request.get_json(silent=True)

            if not isinstance(payload, dict):
                return None

            ref = _normalize_ref(
                payload.get("smart_link_ref")
                or payload.get("context_partner_id")
                or payload.get("client_context_id")
                or payload.get("source_partner_id")
                or payload.get("ref")
                or request.args.get("ref")
                or request.args.get("aid")
                or ""
            )

            source = (
                payload.get("entry_source")
                or payload.get("source")
                or request.args.get("src")
                or request.args.get("source")
                or ""
            )

            if source in ["wa", "whatsapp"]:
                source = "whatsapp_redirect"

            if ref:
                payload["smart_link_ref"] = ref
                payload.setdefault("context_partner_id", ref)
                payload.setdefault("client_context_id", ref)
                payload.setdefault("source_partner_id", ref)
                payload.setdefault("ref", ref)

            if source:
                payload.setdefault("entry_source", source)
                payload["source"] = payload.get("source") or source

            # Update Flask cached JSON so the existing /chat route receives the enriched payload.
            request._cached_json = (payload, payload)

        except Exception as error:
            print(f"SMART LINK PAYLOAD GUARD ERROR ❌ {error}", flush=True)

        return None

    def smart_link_injector(response):
        try:
            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if (
                "text/html" not in content_type
                and "javascript" not in content_type
                and request.path != "/widget.js"
            ):
                return response

            body = response.get_data(as_text=True)

            if not body or "ALSAAB_SMART_LINK_CAPTURE_V1" in body:
                return response

            if "text/html" in content_type and "</body>" in body:
                body = body.replace(
                    "</body>",
                    "<script>\n" + SMART_LINK_JS + "\n</script>\n</body>",
                    1
                )
                response.set_data(body)
                return response

            if "javascript" in content_type or request.path == "/widget.js":
                body = body + "\n\n" + SMART_LINK_JS + "\n"
                response.set_data(body)
                return response

        except Exception as error:
            print(f"SMART LINK INJECTOR ERROR ❌ {error}", flush=True)

        return response


    # ===== ALSAAB_SMART_PROJECT_CONTEXT_V1 START =====
    def _smart_db():
        try:
            import database
            return database
        except ImportError:
            from backend import database
            return database

    def _short_text(value, limit=900):
        value = str(value or "").strip()
        if len(value) > limit:
            return value[:limit] + "..."
        return value

    def _first_value(obj, keys):
        if not isinstance(obj, dict):
            return ""

        lower_map = {str(k).strip().lower(): v for k, v in obj.items()}

        for key in keys:
            key_lower = str(key).strip().lower()
            if key_lower in lower_map and str(lower_map[key_lower] or "").strip():
                return lower_map[key_lower]

        return ""

    def _find_dicts(value, wanted_keys, max_items=10):
        found = []

        def walk(item):
            if len(found) >= max_items:
                return

            if isinstance(item, dict):
                lower_keys = {str(k).strip().lower() for k in item.keys()}
                if any(k.lower() in lower_keys for k in wanted_keys):
                    found.append(item)

                for child in item.values():
                    walk(child)

            elif isinstance(item, list):
                for child in item:
                    walk(child)

        walk(value)
        return found

    def _build_project_context_from_result(ref, result):
        if not isinstance(result, dict):
            result = {}

        profile_candidates = _find_dicts(
            result,
            [
                "project_name",
                "business_name",
                "general_description",
                "project_description",
                "sales_instructions",
                "client_name",
                "partner_name",
            ],
            max_items=8,
        )

        profile = profile_candidates[0] if profile_candidates else result

        project_name = _first_value(profile, [
            "project_name",
            "business_name",
            "brand_name",
            "company_name",
            "client_name",
            "partner_name",
            "name",
            "Project Name",
            "Business Name",
        ])

        description = _first_value(profile, [
            "general_description",
            "project_description",
            "business_description",
            "description",
            "about",
            "Project Description",
            "General Description",
        ])

        sales_instructions = _first_value(profile, [
            "sales_instructions",
            "sales_instruction",
            "instructions",
            "selling_instructions",
            "Sales Instructions",
        ])

        owner_whatsapp_phone = _first_value(profile, [
            "whatsapp_number",
            "whatsapp_phone",
            "whatsapp",
            "phone",
            "phone_number",
            "mobile",
            "business_phone",
            "owner_phone",
            "client_phone",
            "contact_phone",
            "Client Phone",
            "Phone",
            "WhatsApp Number",
            "Business WhatsApp",
        ])

        if not owner_whatsapp_phone:
            phone_candidates = _find_dicts(
                result,
                [
                    "whatsapp_number",
                    "whatsapp_phone",
                    "phone",
                    "phone_number",
                    "mobile",
                    "owner_phone",
                    "client_phone",
                    "contact_phone",
                ],
                max_items=12,
            )

            for phone_item in phone_candidates:
                owner_whatsapp_phone = _first_value(phone_item, [
                    "whatsapp_number",
                    "whatsapp_phone",
                    "whatsapp",
                    "phone",
                    "phone_number",
                    "mobile",
                    "business_phone",
                    "owner_phone",
                    "client_phone",
                    "contact_phone",
                    "Client Phone",
                    "Phone",
                    "WhatsApp Number",
                    "Business WhatsApp",
                ])

                if owner_whatsapp_phone:
                    break


        payment_link_items = _find_dicts(
            result,
            ["payment_url", "payment_link", "link_url", "url"],
            max_items=8,
        )

        payment_lines = []
        for item in payment_link_items:
            title = _first_value(item, ["title", "name", "label", "product_name", "service_name"])
            url = _first_value(item, ["payment_url", "payment_link", "link_url", "url"])
            if url:
                payment_lines.append(f"- {title or 'رابط دفع'}: {url}")

        product_items = _find_dicts(
            result,
            ["group_title", "group_description", "image_urls", "product_name", "sales_instructions"],
            max_items=8,
        )

        product_lines = []
        for item in product_items:
            title = _first_value(item, ["group_title", "title", "product_name", "name"])
            desc = _first_value(item, ["group_description", "description", "product_description"])
            instr = _first_value(item, ["sales_instructions", "instructions"])
            line = " - " + " | ".join([
                _short_text(title, 90) if title else "",
                _short_text(desc, 220) if desc else "",
                _short_text(instr, 220) if instr else "",
            ]).strip(" |")
            if line.strip(" -|"):
                product_lines.append(line)

        subscription_candidates = _find_dicts(
            result,
            ["subscription_status", "plan_name", "current_package", "package_amount"],
            max_items=5,
        )

        subscription = subscription_candidates[0] if subscription_candidates else {}
        plan_name = _first_value(subscription, ["plan_name", "current_package", "package", "plan"])
        subscription_status = _first_value(subscription, ["subscription_status", "status"])

        context_lines = [
            "تعليمات داخلية للموظف الذكي، لا تعرضها للزائر كنص منفصل:",
            f"صاحب الرابط / معرف الحساب: {ref}",
            "مصدر الزائر: رابط واتساب ذكي.",
            "",
            "قاعدة مهمة:",
            "إذا كان الزائر يسأل عن منتجات أو خدمات، بع منتجات وخدمات صاحب هذا الرابط أولاً.",
            "استخدم بيانات المشروع وروابط الدفع الخاصة بصاحب الرابط.",
            "لا تخلط بين منتجات صاحب المشروع وباقات الصعب.",
            "إذا الزائر قال إنه يريد دخل إضافي أو يريد نظام مثل هذا، اشرح له نظام الصعب واشتراكاته وفرصة الشراكة بدون وعد بدخل مضمون.",
            "",
        ]

        if project_name:
            context_lines.append(f"اسم المشروع: {_short_text(project_name, 160)}")

        if description:
            context_lines.append(f"وصف المشروع: {_short_text(description, 900)}")

        if sales_instructions:
            context_lines.append(f"تعليمات البيع الخاصة بالمشروع: {_short_text(sales_instructions, 900)}")

        if owner_whatsapp_phone:
            context_lines.append(f"رقم واتساب صاحب المشروع للرد البشري: {_short_text(owner_whatsapp_phone, 80)}")

        if plan_name or subscription_status:
            context_lines.append(f"حالة حساب صاحب الرابط: الخطة {plan_name or '-'} / الحالة {subscription_status or '-'}")

        if product_lines:
            context_lines.append("")
            context_lines.append("المنتجات أو الكتالوجات المتاحة:")
            context_lines.extend(product_lines[:6])

        if payment_lines:
            context_lines.append("")
            context_lines.append("روابط الدفع الخاصة بصاحب المشروع:")
            context_lines.extend(payment_lines[:6])

        if not project_name and not description and not product_lines and not payment_lines:
            context_lines.append("لم يتم العثور على بيانات مشروع كافية. اسأل الزائر عن احتياجه ولا تدّعي وجود منتجات غير معروفة.")

        return {
            "project_name": str(project_name or "").strip(),
            "plan_name": str(plan_name or "").strip(),
            "subscription_status": str(subscription_status or "").strip(),
            "context_text": "\n".join(context_lines),
            "owner_whatsapp_phone": str(owner_whatsapp_phone or "").strip(),
            "payment_links_count": len(payment_lines),
            "product_groups_count": len(product_lines),
        }

    def _get_smart_project_context(ref):
        import os
        import time

        ref = _normalize_ref(ref)

        if not ref or ref.lower() == "alsaab":
            return {
                "project_name": "ALSAAB AI",
                "context_text": "",
                "subscription_status": "active",
                "plan_name": "",
                "payment_links_count": 0,
                "product_groups_count": 0,
            }

        cache = getattr(app, "alsaab_smart_project_context_cache", None)
        if cache is None:
            cache = {}
            setattr(app, "alsaab_smart_project_context_cache", cache)

        now = time.time()
        cached = cache.get(ref)

        if cached and now - cached.get("ts", 0) < 300:
            return cached.get("data") or {}

        try:
            database = _smart_db()

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "client_dashboard_data",
                    "partner_id": ref,
                    "client_id": ref,
                    "source": "smart_link_context",
                },
                label="smart_link_client_dashboard_data",
            )

            data = _build_project_context_from_result(ref, result)
            cache[ref] = {"ts": now, "data": data}
            return data

        except Exception as error:
            print(f"SMART PROJECT CONTEXT FETCH ERROR ❌ {error}", flush=True)
            return {
                "project_name": "",
                "context_text": f"تعذر تحميل بيانات صاحب الرابط {ref}. لا تدّعي معلومات غير مؤكدة.",
                "subscription_status": "",
                "plan_name": "",
                "payment_links_count": 0,
                "product_groups_count": 0,
            }

    def smart_link_context():
        ref = _normalize_ref(
            request.args.get("ref")
            or request.args.get("aid")
            or request.args.get("client_id")
            or request.args.get("partner_id")
            or ""
        )

        data = _get_smart_project_context(ref)

        return jsonify({
            "status": "success",
            "smart_link_ref": ref,
            "project_name": data.get("project_name", ""),
            "plan_name": data.get("plan_name", ""),
            "subscription_status": data.get("subscription_status", ""),
            "owner_whatsapp_phone": data.get("owner_whatsapp_phone", ""),
            "payment_links_count": data.get("payment_links_count", 0),
            "product_groups_count": data.get("product_groups_count", 0),
        })


    # ===== ALSAAB_SMART_LINK_SALES_LOGIC_V3 START =====
    def _smart_sales_logic_for_message(message):
        raw = str(message or "").strip().lower()

        payment_terms = [
            "رابط الدفع",
            "الدفع",
            "ادفع",
            "أدفع",
            "ابا ادفع",
            "أبغي أدفع",
            "ابي ادفع",
            "اشتري",
            "أشتري",
            "شراء",
            "احجز",
            "أحجز",
            "ارسل الرابط",
            "أرسل الرابط",
            "pay",
            "payment",
            "buy",
            "checkout",
        ]

        human_terms = [
            "شخص",
            "موظف",
            "إنسان",
            "انسان",
            "تواصل",
            "اتصل",
            "كلموني",
            "اريد اتحدث",
            "أريد أتحدث",
            "اكلم شخص",
            "أكلم شخص",
        ]

        income_terms = [
            "دخل",
            "دخل اضافي",
            "دخل إضافي",
            "فلوس",
            "فرصة",
            "شراكة",
            "عمولة",
            "عمولات",
            "mlm",
            "ربح",
            "اربح",
            "أربح",
            "ابي اشتغل",
            "أبي أشتغل",
            "كيف استفيد",
            "كيف أستفيد",
            "بدون مشروع",
            "ما عندي مشروع",
            "ماعندي مشروع",
        ]

        system_terms = [
            "النظام",
            "البوت",
            "موظف المبيعات",
            "نفس النظام",
            "اركب",
            "أركب",
            "اشتراك",
            "باقات",
            "الصعب",
            "alsaab",
        ]

        wants_payment = any(term in raw for term in payment_terms)
        wants_human = any(term in raw for term in human_terms)
        wants_income = any(term in raw for term in income_terms)
        asks_about_system = any(term in raw for term in system_terms)

        if wants_payment:
            return "\n".join([
                "منطق البيع لهذه الرسالة:",
                "الزائر يطلب الدفع أو الشراء.",
                "إذا كانت روابط دفع صاحب المشروع موجودة في بيانات السياق، استخدمها وارسل الرابط المناسب.",
                "إذا يوجد أكثر من رابط دفع ولا تعرف أي منتج أو خدمة يريد، اسأله سؤالاً قصيراً: أي منتج أو خدمة تريد؟",
                "لا ترسل روابط دفع الصعب إلا إذا كان الزائر يسأل عن نظام الصعب أو الاشتراك في نظام الصعب.",
                "إذا لا توجد روابط دفع لصاحب المشروع، لا تخترع رابط دفع.",
                "في حالة عدم وجود رابط دفع، قل له إنك تحتاج تحديد المنتج أو الرجوع لصاحب المشروع لإرسال الرابط المناسب.",
                "حافظ على أسلوب بيعي محترم ومباشر، وادفعه لخطوة الشراء بدون ضغط مزعج.",
            ])

        if wants_human:
            return "\n".join([
                "منطق البيع لهذه الرسالة:",
                "الزائر يريد التحدث مع شخص.",
                "جاوب بلطف ووضّح أنه يقدر يرجع إلى واتساب صاحب المشروع أو يطلب رد بشري.",
                "لا تدّعي أنه تم تحويله فعلياً إذا لم يوجد نظام تحويل حقيقي لهذه المحادثة.",
                "اختصر الرد واسأله عن أفضل طريقة للتواصل أو اطلب منه الضغط على زر الرجوع إلى واتساب.",
            ])

        if wants_income:
            return "\n".join([
                "منطق البيع لهذه الرسالة:",
                "نية الزائر واضحة: يبحث عن فرصة دخل إضافي أو شراكة أو طريقة يربح منها.",
                "في هذه الحالة اشرح نظام الصعب مباشرة بطريقة بيعية محترمة.",
                "اشرح أن النظام مناسب لنوعين من الناس:",
                "1. صاحب مشروع يريد يرفع مبيعاته.",
                "2. شخص لا يملك مشروع ويريد يبدأ فرصة دخل إضافي من خلال الاشتراك والشراكة.",
                "وضح أن الدخل ليس مضموناً ولا تلقائياً، بل يعتمد على الجهد، التسويق، فهم النظام، وعدد العملاء الذين يجلبهم.",
                "رشح باقة النمو كخيار ذكي إذا كان جاداً، ولا ترشح البداية إلا إذا ميزانيته محدودة.",
                "اسأله سؤالاً ينقله للقرار: هل تريد تبدأ كصاحب مشروع أم كشريك يبحث عن دخل إضافي؟",
            ])

        if asks_about_system:
            return "\n".join([
                "منطق البيع لهذه الرسالة:",
                "الزائر يسأل عن نظام الصعب أو موظف المبيعات الذكي.",
                "اشرح نظام الصعب بوضوح: يساعد في الرد، الإقناع، البيع، إرسال روابط الدفع، وتقليل ضياع العملاء.",
                "إذا عنده مشروع، اربط الشرح بمشروعه وكيف يرفع المبيعات.",
                "إذا ما عنده مشروع، اشرح له فرصة الدخول كشريك والاستفادة من العمولات بدون وعد بدخل مضمون.",
                "رشح باقة النمو كخيار أساسي، واذكر النخبة للجادين، والبداية للميزانية المحدودة.",
            ])

        return "\n".join([
            "منطق البيع لهذه الرسالة:",
            "الزائر غالباً داخل من رابط واتساب الخاص بصاحب المشروع.",
            "ركز أولاً على بيع منتجات أو خدمات صاحب الرابط.",
            "استخدم بيانات المشروع وروابط الدفع الخاصة بصاحب الرابط إذا كانت متاحة.",
            "لا تعرض نظام الصعب في بداية المحادثة.",
            "بعد أن تساعد الزائر وتعطيه تجربة قوية، يمكنك فتح فرصة الصعب بذكاء فقط إذا صار مناسباً.",
            "إذا اكتشفت أن الزائر لا يريد منتج صاحب المشروع بل يريد فرصة دخل أو نظام ذكي، انتقل لبيع نظام الصعب.",
            "لا تخلط بين أسعار منتجات صاحب المشروع وباقات الصعب.",
        ])
    # ===== ALSAAB_SMART_LINK_SALES_LOGIC_V3 END =====



    def smart_project_context_guard():
        if request.path != "/chat" or request.method != "POST":
            return None

        try:
            payload = request.get_json(silent=True)

            if not isinstance(payload, dict):
                return None

            ref = _normalize_ref(
                payload.get("smart_link_ref")
                or payload.get("context_partner_id")
                or payload.get("client_context_id")
                or payload.get("source_partner_id")
                or payload.get("ref")
                or ""
            )

            if not ref or ref.lower() == "alsaab":
                return None

            original_message = str(payload.get("message") or "").strip()

            if not original_message:
                return None

            if payload.get("smart_project_context_applied"):
                return None

            context_data = _get_smart_project_context(ref)
            context_text = context_data.get("context_text") or ""

            if context_text:
                payload["original_user_message"] = original_message
                payload["smart_project_context_applied"] = True
                payload["smart_project_name"] = context_data.get("project_name", "")
                payload["smart_project_plan"] = context_data.get("plan_name", "")
                payload["smart_project_subscription_status"] = context_data.get("subscription_status", "")

                smart_sales_logic = _smart_sales_logic_for_message(original_message)
                payload["smart_sales_logic_applied"] = True

                payload["message"] = (
                    context_text
                    + "\n\n"
                    + smart_sales_logic
                    + "\n\nرسالة الزائر الحالية:\n"
                    + original_message
                )

                request._cached_json = (payload, payload)

        except Exception as error:
            print(f"SMART PROJECT CONTEXT GUARD ERROR ❌ {error}", flush=True)

        return None

    def smart_project_context_ui_injector(response):
        try:
            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type and "javascript" not in content_type and request.path != "/widget.js":
                return response

            body = response.get_data(as_text=True)

            if not body or "ALSAAB_SMART_PROJECT_CONTEXT_UI_V1" in body:
                return response

            js = r"""
/* ALSAAB_SMART_PROJECT_CONTEXT_UI_V1 START */
(function(){
  try{
    function getRef(){
      var data = window.ALSAAB_SMART_LINK || {};
      return data.ref || sessionStorage.getItem("alsaab_smart_ref") || localStorage.getItem("alsaab_smart_ref") || "";
    }

    function baseUrl(){
      if (location.hostname.indexOf("onrender.com") !== -1) return "";
      return "https://alsaab-ai.onrender.com";
    }

    function updateTitle(data){
      if(!data || !data.project_name) return;

      var title = document.querySelector(".alsaab-smart-title");
      var subtitle = document.querySelector(".alsaab-smart-subtitle");

      if(title){
        title.textContent = "موظف المبيعات الذكي - " + data.project_name;
      }

      if(subtitle){
        subtitle.textContent = "مرحباً بك في " + data.project_name + "، اختر من الخيارات أو اكتب طلبك.";
      }
    }

    function load(){
      var ref = getRef();
      if(!ref) return;

      fetch(baseUrl() + "/smart-link-context?ref=" + encodeURIComponent(ref))
        .then(function(r){ return r.json(); })
        .then(updateTitle)
        .catch(function(){});
    }

    if(document.readyState === "loading"){
      document.addEventListener("DOMContentLoaded", function(){ setTimeout(load, 500); });
    }else{
      setTimeout(load, 500);
    }
  }catch(e){}
})();
/* ALSAAB_SMART_PROJECT_CONTEXT_UI_V1 END */
"""
            if "text/html" in content_type and "</body>" in body:
                body = body.replace("</body>", "<script>\n" + js + "\n</script>\n</body>", 1)
                response.set_data(body)
                return response

            if "javascript" in content_type or request.path == "/widget.js":
                body = body + "\n\n" + js + "\n"
                response.set_data(body)
                return response

        except Exception as error:
            print(f"SMART PROJECT CONTEXT UI INJECTOR ERROR ❌ {error}", flush=True)

        return response

    # ===== ALSAAB_SMART_PROJECT_CONTEXT_V1 END =====



    # ===== ALSAAB_SMART_WHATSAPP_HANDOFF_V1 START =====
    def smart_whatsapp_handoff_ui_injector(response):
        try:
            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type and "javascript" not in content_type and request.path != "/widget.js":
                return response

            body = response.get_data(as_text=True)

            if not body or "ALSAAB_SMART_WHATSAPP_HANDOFF_CLIENT_V1" in body:
                return response

            js = r"""
/* ALSAAB_SMART_WHATSAPP_HANDOFF_CLIENT_V1 START */
(function(){
  try{
    if(window.__ALSAAB_SMART_WHATSAPP_HANDOFF_CLIENT_V1__) return;
    window.__ALSAAB_SMART_WHATSAPP_HANDOFF_CLIENT_V1__ = true;

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

    function contextEndpoint(ref){
      if(location.hostname.indexOf("onrender.com") !== -1){
        return "/smart-link-context?ref=" + encodeURIComponent(ref);
      }

      return "https://alsaab-ai.onrender.com/smart-link-context?ref=" + encodeURIComponent(ref);
    }

    function normalizePhone(phone){
      phone = String(phone || "").trim();

      if(!phone) return "";

      phone = phone.replace(/[^\d+]/g, "");

      if(phone.indexOf("+") === 0){
        phone = phone.slice(1);
      }

      if(phone.indexOf("00") === 0){
        phone = phone.slice(2);
      }

      if(phone.indexOf("0") === 0 && phone.length === 10){
        phone = "971" + phone.slice(1);
      }

      return phone;
    }

    function getSessionId(ref){
      try{
        var key = "alsaab_smart_analytics_session_" + ref;
        return sessionStorage.getItem(key) || localStorage.getItem(key) || "";
      }catch(e){
        return "";
      }
    }

    function logHumanRequest(ref, message){
      try{
        var endpoint = location.hostname.indexOf("onrender.com") !== -1
          ? "/smart-link-event"
          : "https://alsaab-ai.onrender.com/smart-link-event";

        fetch(endpoint, {
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({
            smart_ref: ref,
            ref: ref,
            partner_id: ref,
            client_id: ref,
            event_type: "human_request",
            source: "smart_link",
            session_id: getSessionId(ref),
            page_url: location.href,
            referrer_url: document.referrer || "",
            message: message || "طلب الرجوع إلى واتساب أو التحدث مع شخص"
          }),
          keepalive:true
        }).catch(function(){});
      }catch(e){}
    }

    function addBotNotice(text){
      try{
        var messages = document.getElementById("alsaabSmartMessages");
        if(!messages) return;

        var item = document.createElement("div");
        item.className = "alsaab-smart-msg bot";
        item.innerHTML = String(text || "").replace(/\n/g, "<br>");
        messages.appendChild(item);
        messages.scrollTop = messages.scrollHeight;
      }catch(e){}
    }

    function openWhatsApp(phone, ref){
      var normalized = normalizePhone(phone);

      if(!normalized){
        addBotNotice("رقم واتساب صاحب المشروع غير مخزن حالياً. اطلب من صاحب المشروع إضافة رقم واتساب في بيانات المشروع حتى يعمل زر الرجوع إلى واتساب.");
        return;
      }

      var text = "هلا، وصلتني المحادثة من موظف المبيعات الذكي وأريد التحدث مع شخص.";
      var url = "https://wa.me/" + normalized + "?text=" + encodeURIComponent(text);

      logHumanRequest(ref, text);

      window.open(url, "_blank");
    }

    function replaceClick(el, handler){
      if(!el) return;

      var clone = el.cloneNode(true);
      el.parentNode.replaceChild(clone, el);
      clone.addEventListener("click", handler);
      return clone;
    }

    function apply(data){
      var ref = getRef();

      if(!ref) return;

      var ownerPhone = data && data.owner_whatsapp_phone ? data.owner_whatsapp_phone : "";

      window.ALSAAB_SMART_OWNER_WHATSAPP = ownerPhone || "";

      var backBtn = document.getElementById("alsaabSmartBackBtn");

      replaceClick(backBtn, function(){
        openWhatsApp(ownerPhone, ref);
      });

      var quickButtons = Array.prototype.slice.call(document.querySelectorAll(".alsaab-smart-quick button"));

      quickButtons.forEach(function(btn){
        var text = (btn.innerText || btn.getAttribute("data-msg") || "").trim();

        if(text.indexOf("التحدث مع شخص") !== -1 || text.indexOf("تحدث مع شخص") !== -1 || text.indexOf("شخص") !== -1){
          replaceClick(btn, function(){
            openWhatsApp(ownerPhone, ref);
          });
        }
      });
    }

    function load(){
      var ref = getRef();

      if(!ref || ref === "alsaab") return;

      fetch(contextEndpoint(ref))
        .then(function(r){ return r.json(); })
        .then(function(data){
          setTimeout(function(){ apply(data); }, 400);
          setTimeout(function(){ apply(data); }, 1200);
        })
        .catch(function(){});
    }

    if(document.readyState === "loading"){
      document.addEventListener("DOMContentLoaded", load);
    }else{
      load();
    }
  }catch(e){}
})();
/* ALSAAB_SMART_WHATSAPP_HANDOFF_CLIENT_V1 END */
"""

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
            print(f"SMART WHATSAPP HANDOFF UI ERROR ❌ {error}", flush=True)
            return response
    # ===== ALSAAB_SMART_WHATSAPP_HANDOFF_V1 END =====


    existing_rules = {str(rule.rule) for rule in app.url_map.iter_rules()}

    if "/smart-link-debug" not in existing_rules:
        app.add_url_rule(
            "/smart-link-debug",
            "smart_link_debug",
            smart_link_debug,
            methods=["GET"],
        )

    if "/smart-link-context" not in existing_rules:
        app.add_url_rule(
            "/smart-link-context",
            "smart_link_context",
            smart_link_context,
            methods=["GET"],
        )

    app.before_request(smart_link_chat_payload_guard)
    app.before_request(smart_project_context_guard)
    app.after_request(smart_link_injector)
    app.after_request(smart_project_context_ui_injector)
    app.after_request(smart_whatsapp_handoff_ui_injector)
