from flask import request, jsonify, make_response
import os
import time
import threading
import copy


def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def _cors_json(data, status_code=200):
    response = jsonify(data)
    response.status_code = status_code
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
    return response


def _empty_summary():
    return {
        "visits": 0,
        "conversations": 0,
        "messages": 0,
        "payment_requests": 0,
        "human_requests": 0,
        "income_requests": 0,
        "latest_events": [],
    }


def register_smart_link_summary_cache_routes(app):
    if getattr(app, "alsaab_smart_link_summary_cache_registered", False):
        return

    app.alsaab_smart_link_summary_cache_registered = True

    cache = {}
    refreshing = set()
    lock = threading.Lock()

    def normalize_ref(value):
        value = str(value or "").strip()
        if value.lower() == "alsaab":
            return "alsaab"
        return "".join(ch for ch in value.upper() if ch.isalnum() or ch in ["-", "_"])

    def build_response_payload(ref, result=None, loading=False, stale=False):
        if isinstance(result, dict) and result.get("status") == "success":
            payload = copy.deepcopy(result)
        else:
            payload = {
                "status": "success",
                "action": "smart_link_summary_get",
                "smart_ref": ref,
                "summary": _empty_summary(),
            }

        payload["_cache"] = {
            "enabled": True,
            "loading": bool(loading),
            "stale": bool(stale),
            "note": "Smart link summary is cached to keep the dashboard fast.",
        }

        return payload

    def refresh_summary(ref):
        try:
            with app.app_context():
                database = _db()
                result = database.post_to_google_sheet_json(
                    {
                        "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                        "action": "smart_link_summary_get",
                        "smart_ref": ref,
                        "ref": ref,
                        "partner_id": ref,
                        "client_id": ref,
                    },
                    label="smart_link_summary_get_cached_background",
                )

                if isinstance(result, dict) and result.get("status") == "success":
                    with lock:
                        cache[ref] = {
                            "ts": time.time(),
                            "result": result,
                        }
        except Exception as error:
            print(f"SMART LINK SUMMARY BACKGROUND REFRESH ERROR ❌ {error}", flush=True)
        finally:
            with lock:
                refreshing.discard(ref)

    def start_refresh_if_needed(ref):
        with lock:
            if ref in refreshing:
                return False

            refreshing.add(ref)

        thread = threading.Thread(target=refresh_summary, args=(ref,), daemon=True)
        thread.start()
        return True

    @app.before_request
    def fast_smart_link_summary():
        try:
            path = (request.path or "").rstrip("/")

            if path != "/client/smart-link-summary":
                return None

            if request.method == "OPTIONS":
                response = make_response("", 204)
                response.headers["Access-Control-Allow-Origin"] = "*"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type"
                response.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
                return response

            ref = normalize_ref(
                request.args.get("partner_id")
                or request.args.get("client_id")
                or request.args.get("ref")
                or ""
            )

            if not ref:
                return _cors_json(
                    {
                        "status": "error",
                        "message": "partner_id/ref is required",
                    },
                    400,
                )

            now = time.time()
            ttl_seconds = 600

            with lock:
                cached = cache.get(ref)

            if cached and now - cached.get("ts", 0) < ttl_seconds:
                return _cors_json(build_response_payload(ref, cached.get("result"), loading=False, stale=False))

            # If stale cache exists, return it immediately and refresh in background.
            if cached:
                start_refresh_if_needed(ref)
                return _cors_json(build_response_payload(ref, cached.get("result"), loading=True, stale=True))

            # No cache: return immediately with empty data, then populate cache in background.
            start_refresh_if_needed(ref)
            return _cors_json(build_response_payload(ref, None, loading=True, stale=False))

        except Exception as error:
            print(f"FAST SMART LINK SUMMARY ERROR ❌ {error}", flush=True)
            return _cors_json(
                {
                    "status": "success",
                    "action": "smart_link_summary_get",
                    "summary": _empty_summary(),
                    "_cache": {
                        "enabled": True,
                        "loading": False,
                        "stale": False,
                        "error": str(error),
                    },
                }
            )
