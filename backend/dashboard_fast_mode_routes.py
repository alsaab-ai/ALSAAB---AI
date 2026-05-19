from flask import request
import re


DASHBOARD_PATHS = {
    "/client-dashboard",
    "/partner-dashboard",
}


BAD_SMART_LINK_MARKERS = [
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


def _strip_bad_dashboard_scripts(html):
    if not html:
        return html

    cleaned = html

    # Remove full comment blocks for public smart-link scripts only.
    for marker in BAD_SMART_LINK_MARKERS:
        base = marker.replace("__", "")
        pattern = (
            r"<!--\s*" + re.escape(base) + r"\s+START\s*-->"
            r"[\s\S]*?"
            r"<!--\s*" + re.escape(base) + r"\s+END\s*-->"
        )
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Remove any script tag that contains one of the public smart-link markers.
    for marker in BAD_SMART_LINK_MARKERS:
        pattern = r"<script\b[^>]*>[\s\S]*?" + re.escape(marker) + r"[\s\S]*?</script>"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Remove style tags that belong to the floating smart chat only.
    smart_style_patterns = [
        r"<style\b[^>]*>[\s\S]*?alsaab-smart-overlay[\s\S]*?</style>",
        r"<style\b[^>]*>[\s\S]*?alsaab-smart-chat[\s\S]*?</style>",
        r"<style\b[^>]*>[\s\S]*?alsaab-smart-income[\s\S]*?</style>",
    ]

    for pattern in smart_style_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Remove any leftover floating smart-chat containers if they were injected server-side.
    leftover_patterns = [
        r"<div[^>]+id=[\"']alsaabSmartChatOverlay[\"'][\s\S]*?</div>",
        r"<div[^>]+class=[\"'][^\"']*alsaab-smart-overlay[^\"']*[\"'][\s\S]*?</div>",
    ]

    for pattern in leftover_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned


def register_dashboard_fast_mode_routes(app):
    if getattr(app, "alsaab_dashboard_fast_mode_registered", False):
        return

    app.alsaab_dashboard_fast_mode_registered = True

    @app.after_request
    def dashboard_fast_mode_after_request(response):
        try:
            path = (request.path or "").rstrip("/") or "/"

            if path not in DASHBOARD_PATHS:
                return response

            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type:
                return response

            html = response.get_data(as_text=True)

            if not html:
                return response

            cleaned = _strip_bad_dashboard_scripts(html)

            if cleaned != html:
                response.set_data(cleaned)

            response.headers["X-ALSAAB-Dashboard-Fast-Mode"] = "1"
            response.headers["Cache-Control"] = "no-store, max-age=0"

            return response

        except Exception as error:
            print(f"DASHBOARD FAST MODE ERROR ❌ {error}", flush=True)
            return response
