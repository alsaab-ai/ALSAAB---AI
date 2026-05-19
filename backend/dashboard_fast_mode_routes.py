import re
from flask import request


DASHBOARD_PATHS = {
    "/client-dashboard",
    "/partner-dashboard",
}


PUBLIC_SMART_SCRIPT_MARKERS = [
    "ALSAAB_SMART_CHAT_UI_V1",
    "ALSAAB_SMART_CHAT_UNIFIED_DASHBOARD_EXCLUDE_V2",
    "ALSAAB_SMART_INCOME_BUTTON_TOP_V2",
    "ALSAAB_SMART_LINK_ANALYTICS_CLIENT_V1",
    "ALSAAB_SMART_LINK_CAPTURE_V1",
    "ALSAAB_SMART_LINK_PROTECTION_CLIENT_V1",
    "ALSAAB_SMART_PROJECT_CONTEXT_UI_V1",
    "ALSAAB_SMART_WHATSAPP_HANDOFF_CLIENT_V1",
    "ALSAAB_SMART_OWNER_WHATSAPP",
]


def _is_dashboard_request():
    path = (request.path or "").rstrip("/") or "/"
    return path in DASHBOARD_PATHS


def _strip_public_smart_scripts(html):
    if not html:
        return html

    cleaned = html

    # Remove script tags that contain public smart-link/chat markers.
    for marker in PUBLIC_SMART_SCRIPT_MARKERS:
        pattern = r"<script\b[^>]*>[\s\S]*?" + re.escape(marker) + r"[\s\S]*?</script>"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Remove HTML comment blocks if any were injected that way.
    for marker in PUBLIC_SMART_SCRIPT_MARKERS:
        pattern = (
            r"<!--\s*" + re.escape(marker) + r"\s+START\s*-->"
            r"[\s\S]*?"
            r"<!--\s*" + re.escape(marker) + r"\s+END\s*-->"
        )
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Remove public floating chat styles only.
    style_patterns = [
        r"<style\b[^>]*>[\s\S]*?alsaab-smart-overlay[\s\S]*?</style>",
        r"<style\b[^>]*>[\s\S]*?alsaab-smart-chat[\s\S]*?</style>",
        r"<style\b[^>]*>[\s\S]*?alsaab-smart-income[\s\S]*?</style>",
        r"<style\b[^>]*>[\s\S]*?alsaabSmartChat[\s\S]*?</style>",
    ]

    for pattern in style_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Remove floating chat containers if they exist.
    container_patterns = [
        r"<div[^>]+id=[\"']alsaabSmartChatOverlay[\"'][\s\S]*?</div>",
        r"<div[^>]+class=[\"'][^\"']*alsaab-smart-overlay[^\"']*[\"'][\s\S]*?</div>",
        r"<div[^>]+class=[\"'][^\"']*alsaab-smart-chat[^\"']*[\"'][\s\S]*?</div>",
    ]

    for pattern in container_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned


def register_dashboard_fast_mode_routes(app):
    if getattr(app, "alsaab_dashboard_fast_mode_final_registered", False):
        return

    app.alsaab_dashboard_fast_mode_final_registered = True

    original_process_response = app.process_response

    def final_dashboard_process_response(response):
        # Run all normal after_request injections first.
        response = original_process_response(response)

        try:
            if not _is_dashboard_request():
                return response

            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type:
                return response

            html = response.get_data(as_text=True)

            if not html:
                return response

            cleaned = _strip_public_smart_scripts(html)

            if cleaned != html:
                response.set_data(cleaned)

            response.headers["X-ALSAAB-Dashboard-Fast-Mode"] = "final-cleaner-v1"
            response.headers["Cache-Control"] = "no-store, max-age=0"

            return response

        except Exception as error:
            print(f"DASHBOARD FAST MODE FINAL CLEANER ERROR ❌ {error}", flush=True)
            return response

    app.process_response = final_dashboard_process_response
    print("DASHBOARD FAST MODE FINAL CLEANER ENABLED ✅", flush=True)
