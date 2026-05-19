from flask import request, jsonify, make_response
import os
import time
import hashlib


def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def register_smart_link_event_filter_routes(app):
    if getattr(app, "alsaab_smart_link_event_filter_registered", False):
        return

    app.alsaab_smart_link_event_filter_registered = True

    event_cache = {}

    def cors_json(data, status_code=200):
        response = jsonify(data)
        response.status_code = status_code
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
        return response

    def normalize_ref(value):
        value = str(value or "").strip()

        if value.lower() == "alsaab":
            return "alsaab"

        return "".join(ch for ch in value.upper() if ch.isalnum() or ch in ["-", "_"])

    def normalize_event_type(value):
        raw = str(value or "").strip().lower()

        if raw in ["chat_message", "message", "user_message", "send_message"]:
            return "conversation_start"

        if raw in ["payment", "payment_link", "payment_request", "checkout_request"]:
            return "payment_request"

        if raw in ["human", "human_request", "handoff", "handoff_request", "whatsapp_return"]:
            return "human_request"

        if raw in ["income", "income_request", "extra_income", "partner_income"]:
            return "income_request"

        if raw in ["visit", "page_visit", "landing_visit"]:
            return "visit"

        return raw

    def fallback_session_id(ref, event_type):
        raw = "|".join([
            ref,
            event_type,
            request.headers.get("User-Agent", ""),
            request.remote_addr or "",
        ])

        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]

    def cleanup_cache():
        now = time.time()
        old_keys = []

        for key, item in list(event_cache.items()):
            if now - item.get("ts", 0) > 86400:
                old_keys.append(key)

        for key in old_keys:
            event_cache.pop(key, None)

    def event_ttl(event_type):
        if event_type == "visit":
            return 86400

        if event_type == "conversation_start":
            return 86400

        if event_type in ["payment_request", "human_request", "income_request"]:
            return 21600

        return 3600

    @app.before_request
    def filter_smart_link_events():
        try:
            path = (request.path or "").rstrip("/")

            if path != "/smart-link-event":
                return None

            if request.method == "OPTIONS":
                response = make_response("", 204)
                response.headers["Access-Control-Allow-Origin"] = "*"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type"
                response.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
                return response

            if request.method != "POST":
                return cors_json({
                    "status": "error",
                    "message": "POST required",
                }, 405)

            payload = request.get_json(silent=True) or {}

            ref = normalize_ref(
                payload.get("smart_ref")
                or payload.get("ref")
                or payload.get("partner_id")
                or payload.get("client_id")
                or payload.get("source_partner_id")
                or ""
            )

            event_type = normalize_event_type(payload.get("event_type"))

            allowed_events = {
                "visit",
                "conversation_start",
                "payment_request",
                "human_request",
                "income_request",
            }

            if not ref:
                return cors_json({
                    "status": "success",
                    "ignored": True,
                    "reason": "missing_ref",
                })

            if event_type not in allowed_events:
                return cors_json({
                    "status": "success",
                    "ignored": True,
                    "reason": "event_not_logged",
                    "event_type": event_type,
                    "smart_ref": ref,
                })

            session_id = str(payload.get("session_id") or "").strip()

            if not session_id:
                session_id = fallback_session_id(ref, event_type)

            cleanup_cache()

            now = time.time()
            key = f"{ref}|{event_type}|{session_id}"
            previous = event_cache.get(key)
            ttl = event_ttl(event_type)

            if previous and now - previous.get("ts", 0) < ttl:
                return cors_json({
                    "status": "success",
                    "duplicate_ignored": True,
                    "event_type": event_type,
                    "smart_ref": ref,
                })

            event_cache[key] = {
                "ts": now,
            }

            if event_type == "conversation_start":
                clean_message = "conversation started"
            elif event_type == "visit":
                clean_message = "visit"
            elif event_type == "payment_request":
                clean_message = "payment requested"
            elif event_type == "human_request":
                clean_message = "human requested"
            elif event_type == "income_request":
                clean_message = "income opportunity requested"
            else:
                clean_message = ""

            database = _db()

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "smart_link_event_log",
                    "smart_ref": ref,
                    "ref": ref,
                    "partner_id": ref,
                    "client_id": ref,
                    "event_type": event_type,
                    "source": "smart_link",
                    "session_id": session_id,
                    "page_url": payload.get("page_url") or "",
                    "referrer_url": payload.get("referrer_url") or "",
                    "message": clean_message,
                    "user_agent": request.headers.get("User-Agent", ""),
                },
                label="smart_link_event_log_filtered",
            )

            if isinstance(result, dict):
                result["filtered"] = True
                result["event_type"] = event_type
                result["smart_ref"] = ref
                return cors_json(result)

            return cors_json({
                "status": "success",
                "action": "smart_link_event_log",
                "filtered": True,
                "event_type": event_type,
                "smart_ref": ref,
            })

        except Exception as error:
            print(f"SMART LINK EVENT FILTER ERROR ❌ {error}", flush=True)

            return cors_json({
                "status": "success",
                "ignored": True,
                "reason": "filter_error",
                "error": str(error),
            })
