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
