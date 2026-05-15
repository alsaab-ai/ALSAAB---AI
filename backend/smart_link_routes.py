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
      if (!ref) return false;

      var params = new URLSearchParams(window.location.search || "");
      return Boolean(
        params.get("ref") ||
        params.get("aid") ||
        params.get("client_id") ||
        params.get("partner_id")
      );
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
              <button type="button" class="alsaab-smart-back" id="alsaabSmartBackBtn">الرجوع إلى واتساب</button>
            </div>

            <div class="alsaab-smart-quick">
              <button type="button" data-msg="أريد معرفة الأسعار">أريد معرفة الأسعار</button>
              <button type="button" data-msg="أريد المنتج أو الخدمة الأنسب لي">أريد الأنسب لي</button>
              <button type="button" data-msg="أريد رابط الدفع">أريد رابط الدفع</button>
              <button type="button" data-msg="أريد فرصة دخل إضافي">أريد فرصة دخل إضافي</button>
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

    existing_rules = {str(rule.rule) for rule in app.url_map.iter_rules()}

    if "/smart-link-debug" not in existing_rules:
        app.add_url_rule(
            "/smart-link-debug",
            "smart_link_debug",
            smart_link_debug,
            methods=["GET"],
        )

    app.before_request(smart_link_chat_payload_guard)
    app.after_request(smart_link_injector)
