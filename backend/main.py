print("ALSAAB AI is running 🔥")

from flask import Flask, request, jsonify, render_template_string, redirect, session
from brain import think
from database import (
    init_db,
    save_message,
    get_leads,
    get_client_subscription,
    can_client_use_bot,
    record_bot_reply_usage,
    create_or_update_subscription,
    get_usage_summary,
    send_partner_to_google_sheet,
    get_source_partner_id_for_session,
    get_client_subscription_by_stripe_subscription_id,
    ensure_paid_client_is_partner,
)
from config import (
    STRIPE_PLAN_CONFIG,
    STRIPE_WEBHOOK_SECRET,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS,
)
import uuid
import os
import json
import time
import hmac
import hashlib
import re
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

app = Flask(__name__)


# ===== ALSAAB_DASHBOARD_SSO_SESSION_SECRET_V1 START =====
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    os.environ.get("DASHBOARD_SSO_SECRET", "alsaab-ai-dev-session-secret-change-me")
)
# ===== ALSAAB_DASHBOARD_SSO_SESSION_SECRET_V1 END =====

init_db()

ADMIN_KEY = "alsaab123"
SAFE_STRIPE_REFERENCE_SEPARATOR = "__"

TRAINING_COMMANDS = [
    "تدريب",
    "تدريب البوت",
    "/train",
    "train",
]

TRAINING_LOCKED_REPLY = (
    "تدريب البوت متاح للمشتركين فقط ✅\n\n"
    "إذا تبغي نجهز البوت لمشروعك، اختر الباقة المناسبة أولاً، "
    "وبعد تفعيل الاشتراك نبدأ تدريب مشروعك خطوة خطوة."
)


def is_training_command(message):
    msg = str(message or "").lower().strip()
    return msg in TRAINING_COMMANDS


def is_active_subscription(subscription):
    if not subscription:
        return False

    status = str(subscription.get("subscription_status", "")).lower().strip()
    return status == "active"


def normalize_source_partner_id(value):
    value = str(value or "").strip()

    if not value:
        return ""

    if value.lower() == "alsaab":
        return "alsaab"

    match = re.search(r"ALS-P\d+", value.upper())

    if match:
        return match.group(0).strip()

    return ""


def build_stripe_client_reference_id(session_id, plan_name, source_partner_id=""):
    source_partner_id = normalize_source_partner_id(source_partner_id)

    if source_partner_id:
        return (
            f"{session_id}"
            f"{SAFE_STRIPE_REFERENCE_SEPARATOR}{plan_name}"
            f"{SAFE_STRIPE_REFERENCE_SEPARATOR}{source_partner_id}"
        )

    return f"{session_id}{SAFE_STRIPE_REFERENCE_SEPARATOR}{plan_name}"


def parse_stripe_client_reference_id(reference_id):
    if not reference_id:
        return "", "", ""

    reference_id = str(reference_id).strip()

    if SAFE_STRIPE_REFERENCE_SEPARATOR in reference_id:
        parts = reference_id.rsplit(SAFE_STRIPE_REFERENCE_SEPARATOR, 2)

        if len(parts) == 3:
            return (
                parts[0].strip(),
                parts[1].strip(),
                normalize_source_partner_id(parts[2])
            )

        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip(), ""

    if "::" in reference_id:
        parts = reference_id.rsplit("::", 2)

        if len(parts) == 3:
            return (
                parts[0].strip(),
                parts[1].strip(),
                normalize_source_partner_id(parts[2])
            )

        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip(), ""

    return "", "", ""


def append_query_params(url, params):
    parsed_url = urlparse(url)
    current_params = dict(parse_qsl(parsed_url.query))

    for key, value in params.items():
        if value is not None and value != "":
            current_params[key] = value

    new_query = urlencode(current_params)

    return urlunparse(parsed_url._replace(query=new_query))


def verify_stripe_signature(payload, signature_header, webhook_secret, tolerance_seconds=300):
    if not webhook_secret:
        return False, "STRIPE_WEBHOOK_SECRET is not configured"

    if not signature_header:
        return False, "Stripe-Signature header is missing"

    try:
        parts = signature_header.split(",")
        timestamp = None
        signatures = []

        for part in parts:
            if "=" not in part:
                continue

            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()

            if key == "t":
                timestamp = value

            if key == "v1":
                signatures.append(value)

        if not timestamp:
            return False, "Stripe timestamp is missing"

        if not signatures:
            return False, "Stripe v1 signature is missing"

        timestamp_int = int(timestamp)
        current_time = int(time.time())

        if tolerance_seconds and abs(current_time - timestamp_int) > int(tolerance_seconds):
            return False, "Stripe signature timestamp is outside tolerance"

        signed_payload = timestamp.encode("utf-8") + b"." + payload

        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256
        ).hexdigest()

        for signature in signatures:
            if hmac.compare_digest(expected_signature, signature):
                return True, "verified"

        return False, "No matching Stripe signature"

    except Exception as error:
        return False, str(error)


def get_admin_payload():
    """
    يقرأ بيانات admin routes من JSON أو Form.
    مهم: GET صار للمعاينة فقط، والتنفيذ الحقيقي POST فقط.
    """
    if request.is_json:
        return request.json or {}

    if request.form:
        return request.form.to_dict()

    return {}


def get_payload_value(payload, *keys, default=""):
    for key in keys:
        value = payload.get(key)

        if value is not None and str(value).strip() != "":
            return str(value).strip()

    return default


def get_admin_key(payload):
    return (
        get_payload_value(payload, "key", default="")
        or request.args.get("key", "").strip()
    )


def admin_get_preview(action_name, required_fields=None, example_body=None):
    return jsonify({
        "status": "preview_only",
        "message": (
            f"{action_name} does not execute with GET anymore. "
            "Use POST with JSON body to execute this admin action."
        ),
        "method_required": "POST",
        "reason": "GET links can be triggered by browser preview, prefetch, or copy/link scanners.",
        "required_fields": required_fields or [],
        "example_body": example_body or {}
    })


HTML = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ALSAAB AI</title>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">

<style>
* {
    box-sizing: border-box;
}

:root {
    --bg-main: #05070d;
    --bg-card: rgba(12, 16, 26, 0.92);
    --bg-card-soft: rgba(255, 255, 255, 0.045);
    --border-soft: rgba(255, 255, 255, 0.08);
    --gold: #d6a84f;
    --gold-2: #f3d37b;
    --gold-3: #a97824;
    --green: #22c55e;
    --text-main: #f8fafc;
    --text-soft: #cbd5e1;
    --text-muted: #94a3b8;
    --shadow: 0 24px 80px rgba(0,0,0,0.55);
}

html, body {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    background: var(--bg-main);
    font-family: "Cairo", Arial, sans-serif;
    color: var(--text-main);
    overflow: hidden;
}

.luxury-bg {
    position: fixed;
    inset: 0;
    background:
        radial-gradient(circle at 15% 15%, rgba(214, 168, 79, 0.16), transparent 28%),
        radial-gradient(circle at 85% 85%, rgba(214, 168, 79, 0.12), transparent 32%),
        linear-gradient(135deg, #03050a 0%, #0a0f1d 42%, #060810 100%);
    z-index: -3;
}

.luxury-bg::before {
    content: "";
    position: absolute;
    inset: 0;
    background-image:
        linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
    background-size: 42px 42px;
    mask-image: radial-gradient(circle at center, black, transparent 78%);
    opacity: 0.55;
}

.luxury-bg::after {
    content: "";
    position: absolute;
    inset: 0;
    background:
        radial-gradient(circle at 55% 115%, rgba(214,168,79,0.22), transparent 35%),
        radial-gradient(circle at 95% 10%, rgba(255,255,255,0.05), transparent 25%);
    opacity: 0.9;
}

.page {
    width: 100%;
    height: 100vh;
    padding: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
}

.chat-shell {
    width: min(1040px, 100%);
    height: min(880px, calc(100vh - 36px));
    min-height: 620px;
    display: grid;
    grid-template-columns: 280px 1fr;
    border: 1px solid rgba(214, 168, 79, 0.38);
    border-radius: 28px;
    background:
        linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.01)),
        rgba(7, 10, 18, 0.92);
    box-shadow:
        var(--shadow),
        0 0 0 1px rgba(255,255,255,0.025) inset,
        0 0 80px rgba(214, 168, 79, 0.08);
    overflow: hidden;
    backdrop-filter: blur(18px);
}

.sidebar {
    position: relative;
    padding: 24px 18px;
    border-left: 1px solid rgba(255,255,255,0.07);
    background:
        radial-gradient(circle at top, rgba(214,168,79,0.13), transparent 34%),
        linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.01));
    overflow-y: auto;
}

.sidebar::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
        linear-gradient(145deg, transparent 0%, rgba(214,168,79,0.045) 45%, transparent 80%);
    pointer-events: none;
}

.brand-block {
    position: relative;
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 28px;
}

.logo-mark {
    width: 58px;
    height: 58px;
    border-radius: 18px;
    display: grid;
    place-items: center;
    background:
        linear-gradient(145deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)),
        radial-gradient(circle at top, rgba(243,211,123,0.25), transparent 60%);
    border: 1px solid rgba(214,168,79,0.45);
    box-shadow:
        0 12px 30px rgba(0,0,0,0.35),
        0 0 24px rgba(214,168,79,0.12);
    color: white;
    font-weight: 900;
    font-size: 30px;
    line-height: 1;
}

.logo-mark span {
    background: linear-gradient(180deg, #ffffff, #d6a84f);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.brand-text h1 {
    margin: 0;
    font-size: 22px;
    font-weight: 900;
    letter-spacing: 0.4px;
}

.brand-text p {
    margin: 3px 0 0;
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.6;
}

.side-card {
    position: relative;
    padding: 18px;
    border-radius: 22px;
    background: rgba(255,255,255,0.045);
    border: 1px solid rgba(255,255,255,0.07);
    margin-bottom: 16px;
}

.side-card.gold {
    border-color: rgba(214,168,79,0.35);
    background:
        radial-gradient(circle at top right, rgba(214,168,79,0.13), transparent 45%),
        rgba(255,255,255,0.04);
}

.side-label {
    color: var(--gold-2);
    font-size: 12px;
    font-weight: 800;
    margin-bottom: 8px;
}

.side-title {
    margin: 0;
    font-size: 22px;
    font-weight: 900;
    line-height: 1.35;
}

.side-text {
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.8;
    margin: 8px 0 0;
}

.side-list {
    display: grid;
    gap: 12px;
    margin-top: 16px;
}

.side-item {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--text-soft);
    font-size: 13px;
}

.side-icon {
    width: 32px;
    height: 32px;
    border-radius: 12px;
    display: grid;
    place-items: center;
    border: 1px solid rgba(214,168,79,0.28);
    color: var(--gold-2);
    background: rgba(214,168,79,0.07);
    flex-shrink: 0;
}

.mini-cta {
    margin-top: 18px;
    width: 100%;
    border: none;
    border-radius: 16px;
    background: linear-gradient(135deg, var(--gold-2), var(--gold));
    color: #111827;
    font-family: "Cairo", Arial, sans-serif;
    font-weight: 900;
    font-size: 14px;
    padding: 13px 14px;
    cursor: pointer;
    box-shadow: 0 12px 28px rgba(214,168,79,0.22);
}

.main-chat {
    display: flex;
    flex-direction: column;
    min-width: 0;
    height: 100%;
    overflow: hidden;
}

.chat-header {
    min-height: 92px;
    padding: 18px 22px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    border-bottom: 1px solid rgba(214,168,79,0.26);
    background:
        radial-gradient(circle at top left, rgba(214,168,79,0.09), transparent 35%),
        linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.015));
    flex-shrink: 0;
}

.header-title {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;
}

.header-logo {
    width: 52px;
    height: 52px;
    border-radius: 17px;
    display: grid;
    place-items: center;
    border: 1px solid rgba(214,168,79,0.45);
    background: rgba(255,255,255,0.045);
    box-shadow: 0 10px 24px rgba(0,0,0,0.25);
    flex-shrink: 0;
    font-size: 26px;
    font-weight: 900;
}

.header-logo span {
    background: linear-gradient(180deg, #ffffff, #d6a84f);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.header-copy h2 {
    margin: 0;
    font-size: 21px;
    font-weight: 900;
}

.header-copy p {
    margin: 4px 0 0;
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.5;
}

.header-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-shrink: 0;
}

.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 9px;
    padding: 10px 13px;
    border-radius: 999px;
    background: rgba(34,197,94,0.10);
    border: 1px solid rgba(34,197,94,0.24);
    color: #bbf7d0;
    font-size: 12px;
    font-weight: 800;
    white-space: nowrap;
}

.status-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 0 6px rgba(34,197,94,0.16);
}

.chat-close-btn {
    width: 42px;
    height: 42px;
    border-radius: 15px;
    border: 1px solid rgba(214,168,79,0.38);
    background:
        linear-gradient(145deg, rgba(255,255,255,0.08), rgba(255,255,255,0.025)),
        rgba(7, 10, 18, 0.82);
    color: var(--gold-2);
    display: grid;
    place-items: center;
    cursor: pointer;
    font-family: "Cairo", Arial, sans-serif;
    font-size: 20px;
    font-weight: 900;
    line-height: 1;
    box-shadow:
        0 10px 24px rgba(0,0,0,0.22),
        0 0 18px rgba(214,168,79,0.08);
    transition: 0.18s ease;
    flex-shrink: 0;
}

.chat-close-btn:hover {
    transform: translateY(-1px);
    border-color: rgba(243,211,123,0.65);
    background:
        linear-gradient(145deg, rgba(243,211,123,0.18), rgba(214,168,79,0.06)),
        rgba(7, 10, 18, 0.92);
    color: #ffffff;
    box-shadow:
        0 14px 30px rgba(0,0,0,0.30),
        0 0 26px rgba(214,168,79,0.18);
}

.chat-close-btn:active {
    transform: scale(0.96);
}

.messages-wrap {
    flex: 1;
    min-height: 0;
    position: relative;
    display: flex;
    flex-direction: column;
    background:
        radial-gradient(circle at 85% 15%, rgba(214,168,79,0.06), transparent 34%),
        radial-gradient(circle at 12% 88%, rgba(34,197,94,0.04), transparent 28%);
    overflow: hidden;
}

.messages {
    flex: 1;
    min-height: 0;
    overflow-y: scroll;
    overflow-x: hidden;
    padding: 22px;
    scroll-behavior: smooth;
    scrollbar-width: thin;
    scrollbar-color: rgba(214,168,79,0.55) rgba(255,255,255,0.06);
}

.messages::-webkit-scrollbar {
    width: 11px;
}

.messages::-webkit-scrollbar-track {
    background: rgba(255,255,255,0.05);
    border-radius: 999px;
}

.messages::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, rgba(243,211,123,0.75), rgba(214,168,79,0.35));
    border-radius: 999px;
    border: 2px solid rgba(7,10,18,0.85);
}

.welcome-card {
    margin-bottom: 20px;
    padding: 18px;
    border-radius: 24px;
    background:
        linear-gradient(145deg, rgba(255,255,255,0.055), rgba(255,255,255,0.025));
    border: 1px solid rgba(214,168,79,0.24);
    box-shadow: 0 18px 40px rgba(0,0,0,0.18);
}

.welcome-title {
    margin: 0;
    color: #ffffff;
    font-size: 18px;
    font-weight: 900;
}

.welcome-text {
    margin: 8px 0 0;
    color: var(--text-soft);
    font-size: 14px;
    line-height: 1.9;
}

.quick-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 14px;
}

.quick-chip {
    border: 1px solid rgba(214,168,79,0.35);
    color: var(--gold-2);
    background: rgba(214,168,79,0.07);
    border-radius: 999px;
    padding: 9px 12px;
    font-family: "Cairo", Arial, sans-serif;
    font-size: 12px;
    font-weight: 800;
    cursor: pointer;
}

.msg-row {
    display: flex;
    margin-bottom: 14px;
}

.msg-row.user-row {
    justify-content: flex-start;
}

.msg-row.bot-row {
    justify-content: flex-end;
}

.msg-bubble {
    max-width: min(82%, 720px);
    padding: 14px 16px;
    border-radius: 18px;
    line-height: 1.9;
    font-size: 15px;
    overflow-wrap: break-word;
    word-wrap: break-word;
    white-space: normal;
    box-shadow: 0 10px 26px rgba(0,0,0,0.22);
}

.user {
    background:
        linear-gradient(145deg, rgba(255,255,255,0.08), rgba(255,255,255,0.035));
    border: 1px solid rgba(214,168,79,0.30);
    color: var(--text-main);
    border-bottom-right-radius: 7px;
}

.bot {
    background:
        linear-gradient(145deg, rgba(22,163,74,0.95), rgba(21,128,61,0.95));
    border: 1px solid rgba(255,255,255,0.09);
    color: white;
    border-bottom-left-radius: 7px;
}

.bot a {
    color: #ffffff;
    font-weight: 900;
    text-decoration: underline;
    word-break: break-all;
}

.meta-line {
    margin-top: 8px;
    color: rgba(255,255,255,0.65);
    font-size: 11px;
}

.user .meta-line {
    color: rgba(203,213,225,0.68);
}

.typing-wrap {
    display: none;
    padding: 0 22px 14px;
    flex-shrink: 0;
}

.typing {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-radius: 999px;
    background: rgba(255,255,255,0.045);
    border: 1px solid rgba(214,168,79,0.24);
    color: var(--text-soft);
    font-size: 13px;
    font-weight: 700;
}

.typing-dots {
    display: inline-flex;
    gap: 5px;
}

.typing-dots span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--gold-2);
    animation: pulseDot 1.2s infinite ease-in-out;
}

.typing-dots span:nth-child(2) { animation-delay: 0.15s; }
.typing-dots span:nth-child(3) { animation-delay: 0.30s; }

@keyframes pulseDot {
    0%, 80%, 100% { opacity: 0.35; transform: translateY(0) scale(0.9); }
    40% { opacity: 1; transform: translateY(-3px) scale(1); }
}

.chat-footer {
    padding: 18px 22px 20px;
    border-top: 1px solid rgba(255,255,255,0.07);
    background:
        linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.04));
    flex-shrink: 0;
}

.composer {
    display: flex;
    align-items: flex-end;
    gap: 12px;
    padding: 10px;
    border-radius: 22px;
    background: rgba(255,255,255,0.045);
    border: 1px solid rgba(214,168,79,0.30);
    box-shadow: 0 12px 34px rgba(0,0,0,0.18);
}

.input-area {
    flex: 1;
    min-width: 0;
}

textarea {
    width: 100%;
    min-height: 54px;
    max-height: 150px;
    resize: none;
    border: none;
    outline: none;
    background: transparent;
    color: var(--text-main);
    font-family: "Cairo", Arial, sans-serif;
    font-size: 15px;
    line-height: 1.8;
    padding: 9px 10px;
}

textarea::placeholder {
    color: #94a3b8;
}

.send-btn {
    width: 58px;
    height: 58px;
    border: none;
    border-radius: 18px;
    background: linear-gradient(145deg, var(--gold-2), var(--gold));
    color: #111827;
    display: grid;
    place-items: center;
    cursor: pointer;
    box-shadow: 0 14px 32px rgba(214,168,79,0.28);
    transition: 0.18s ease;
    flex-shrink: 0;
    font-size: 22px;
    font-weight: 900;
}

.send-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 18px 38px rgba(214,168,79,0.36);
}

.send-btn:disabled {
    opacity: 0.58;
    cursor: pointer;
    transform: none;
}

.footer-note {
    margin-top: 10px;
    color: rgba(148,163,184,0.9);
    font-size: 11px;
    text-align: center;
}

@media (max-width: 860px) {
    .page {
        padding: 0;
    }

    .chat-shell {
        width: 100%;
        height: 100vh;
        min-height: 100vh;
        border-radius: 0;
        grid-template-columns: 1fr;
        border: none;
    }

    .sidebar {
        display: none;
    }

    .chat-header {
        min-height: 78px;
        padding: 14px 14px;
    }

    .header-logo {
        width: 46px;
        height: 46px;
        border-radius: 15px;
        font-size: 23px;
    }

    .header-copy h2 {
        font-size: 18px;
    }

    .header-copy p {
        font-size: 12px;
    }

    .header-actions {
        gap: 8px;
    }

    .status-pill {
        display: none;
    }

    .chat-close-btn {
        width: 42px;
        height: 42px;
        border-radius: 14px;
        font-size: 19px;
    }

    .messages {
        padding: 14px;
    }

    .msg-bubble {
        max-width: 92%;
        font-size: 14px;
        line-height: 1.85;
    }

    .chat-footer {
        padding: 12px;
    }

    .composer {
        border-radius: 18px;
        gap: 8px;
        padding: 8px;
    }

    textarea {
        min-height: 50px;
        font-size: 14px;
    }

    .send-btn {
        width: 52px;
        height: 52px;
        border-radius: 16px;
        font-size: 20px;
    }

    .welcome-card {
        padding: 15px;
        border-radius: 20px;
    }

    .welcome-title {
        font-size: 16px;
    }

    .welcome-text {
        font-size: 13px;
    }
}
</style>
</head>

<body>
<div class="luxury-bg"></div>

<div class="page">
    <div class="chat-shell">

        <aside class="sidebar">
            <div class="brand-block">
                <div class="logo-mark"><span>A</span></div>
                <div class="brand-text">
                    <h1>ALSAAB AI</h1>
                    <p>Smart Sales Assistant</p>
                </div>
            </div>

            <div class="side-card gold">
                <div class="side-label">نظام مبيعات ذكي</div>
                <h2 class="side-title">أقوى نظام مبيعات ذكي يرفع المبيعات بشكل صاروخي 🚀</h2>
                <p class="side-text">
                    مساعد مبيعات ذكي، يفهم و يحلل العميل و يشخّص و يحل المشكلة و يساعدك في إغلاق الصفقات و اتخاذ القرار مع العملاء.
                </p>

                <div class="side-list">
                    <div class="side-item">
                        <div class="side-icon">⚡</div>
                        <span>ردود ذكية وسريعة</span>
                    </div>
                    <div class="side-item">
                        <div class="side-icon">🎯</div>
                        <span>بيع وإقناع وإغلاق</span>
                    </div>
                    <div class="side-item">
                        <div class="side-icon">📈</div>
                        <span>مصمم لزيادة المبيعات</span>
                    </div>
                </div>

                <button class="mini-cta" onclick="sendQuick('أبغي أعرف الباقات')">
                    عرض الباقات
                </button>
            </div>

            <div class="side-card">
                <div class="side-label">الوضع الحالي</div>
                <p class="side-text">
                    اكتب رسالتك، والبوت بيساعدك تفهم أفضل خطوة لمشروعك أو دخلك.
                </p>
            </div>
        </aside>

        <main class="main-chat">
            <header class="chat-header">
                <div class="header-title">
                    <div class="header-logo"><span>A</span></div>
                    <div class="header-copy">
                        <h2>ALSAAB AI</h2>
                        <p>مساعدك الذكي للمبيعات، الرد، الإقناع، والإغلاق</p>
                    </div>
                </div>

                <div class="header-actions">
                    <div class="status-pill">
                        <span class="status-dot"></span>
                        <span>Online 24/7</span>
                    </div>

                    <button class="chat-close-btn" onclick="closeChat()" title="إغلاق الشات" aria-label="إغلاق الشات">
                        ✕
                    </button>
                </div>
            </header>

            <section class="messages-wrap">
                <div id="messages" class="messages">
                    <div class="welcome-card">
                        <h3 class="welcome-title">هلا وسهلا 👋</h3>
                        <p class="welcome-text">
                            أنا ALSAAB AI. أقدر أساعدك في زيادة المبيعات، اختيار الباقة المناسبة،
                            أو معرفة نظام الشراكة والدخل الإضافي.
                        </p>

                        <div class="quick-actions">
                            <button class="quick-chip" onclick="sendQuick('أبغي أعرف الباقات')">عرض الباقات</button>
                            <button class="quick-chip" onclick="sendQuick('عندي مشروع وأبغي أرفع المبيعات')">عندي مشروع</button>
                            <button class="quick-chip" onclick="sendQuick('محتاج دخل إضافي')">دخل إضافي</button>
                        </div>
                    </div>
                </div>

                <div id="typingWrap" class="typing-wrap">
                    <div class="typing">
                        <div class="typing-dots">
                            <span></span><span></span><span></span>
                        </div>
                        <strong>ALSAAB AI يكتب الآن...</strong>
                    </div>
                </div>
            </section>

            <footer class="chat-footer">
                <div class="composer">
                    <div class="input-area">
                        <textarea id="msg" placeholder="اكتب رسالتك هنا..."></textarea>
                    </div>
                    <button id="sendBtn" class="send-btn" onclick="sendMsg()" title="إرسال">➤</button>
                </div>

                <div class="footer-note">
                    Powered by ALSAAB AI • Sales Automation
                </div>
            </footer>
        </main>

    </div>
</div>

<script>
let sessionId = localStorage.getItem("session_id");
let sourcePartnerId = localStorage.getItem("source_partner_id") || "";
let isSending = false;

function normalizeSourcePartnerId(value) {
    value = String(value || "").trim();

    if (!value) return "";

    if (value.toLowerCase() === "alsaab") {
        return "alsaab";
    }

    const match = value.toUpperCase().match(/ALS-P\d+/);

    if (match && match[0]) {
        return match[0];
    }

    return "";
}

function captureSourcePartnerId() {
    try {
        const params = new URLSearchParams(window.location.search);
        const ref =
            params.get("ref") ||
            params.get("source_partner_id") ||
            params.get("partner_id") ||
            params.get("sponsor_partner_id") ||
            "";

        const normalizedRef = normalizeSourcePartnerId(ref);

        if (normalizedRef) {
            sourcePartnerId = normalizedRef;
            localStorage.setItem("source_partner_id", normalizedRef);
            console.log("ALSAAB referral captured:", normalizedRef);
            return normalizedRef;
        }

        sourcePartnerId = normalizeSourcePartnerId(sourcePartnerId);

        if (sourcePartnerId) {
            localStorage.setItem("source_partner_id", sourcePartnerId);
        }

        return sourcePartnerId;
    } catch (error) {
        console.error("Referral capture error:", error);
        return "";
    }
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function linkify(text) {
    let safeText = escapeHtml(text);

    safeText = safeText.replace(
        /(https?:\/\/[^\s<>"']+)/g,
        function(url) {
            let cleanUrl = url.replace(/[،,.؛:!?)]$/, "");
            let tail = url.substring(cleanUrl.length);

            return '<a href="' + cleanUrl + '" target="_blank" rel="noopener noreferrer">' + cleanUrl + '</a>' + tail;
        }
    );

    safeText = safeText.replace(/\n/g, "<br>");
    return safeText;
}

function currentTime() {
    const now = new Date();

    return now.toLocaleTimeString("ar-AE", {
        hour: "numeric",
        minute: "2-digit"
    });
}

function scrollToBottom() {
    const box = document.getElementById("messages");

    if (!box) return;

    requestAnimationFrame(function() {
        box.scrollTop = box.scrollHeight;

        setTimeout(function() {
            box.scrollTop = box.scrollHeight;
        }, 80);

        setTimeout(function() {
            box.scrollTop = box.scrollHeight;
        }, 250);
    });
}

function addMsg(text, type) {
    const box = document.getElementById("messages");

    const row = document.createElement("div");
    row.className = "msg-row " + (type === "bot" ? "bot-row" : "user-row");

    const div = document.createElement("div");
    div.className = "msg-bubble " + type;

    if (type === "bot") {
        div.innerHTML = linkify(text) + '<div class="meta-line">' + currentTime() + '</div>';
    } else {
        div.innerHTML = escapeHtml(text).replace(/\n/g, "<br>") + '<div class="meta-line">' + currentTime() + '</div>';
    }

    row.appendChild(div);
    box.appendChild(row);
    scrollToBottom();
}

function showTyping(show) {
    const typingWrap = document.getElementById("typingWrap");

    typingWrap.style.display = show ? "block" : "none";
    scrollToBottom();
}

function sendQuick(text) {
    const input = document.getElementById("msg");
    input.value = text;
    sendMsg();
}

function closeChat() {
    try {
        window.parent.postMessage({
            type: "ALSAAB_CLOSE_CHAT",
            source: "ALSAAB_AI"
        }, "*");
    } catch (error) {
        console.error(error);
    }

    const page = document.querySelector(".page");

    if (page) {
        page.style.display = "none";
    }
}

async function sendMsg() {
    if (isSending) return;

    const input = document.getElementById("msg");
    const button = document.getElementById("sendBtn");
    const text = input.value.trim();

    if (!text) return;

    sourcePartnerId = captureSourcePartnerId();

    isSending = true;
    button.disabled = true;

    addMsg(text, "user");
    input.value = "";
    input.style.height = "54px";
    showTyping(true);

    try {
        const res = await fetch("/chat", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                message: text,
                session_id: sessionId,
                source_partner_id: sourcePartnerId
            })
        });

        const data = await res.json();

        sessionId = data.session_id;
        localStorage.setItem("session_id", sessionId);

        if (data.source_partner_id) {
            sourcePartnerId = normalizeSourcePartnerId(data.source_partner_id);

            if (sourcePartnerId) {
                localStorage.setItem("source_partner_id", sourcePartnerId);
            }
        }

        showTyping(false);
        addMsg(data.reply, "bot");
        scrollToBottom();

    } catch (error) {
        showTyping(false);
        addMsg("صار خطأ مؤقت في الاتصال. جرّب مرة ثانية.", "bot");
        console.error(error);
    }

    isSending = false;
    button.disabled = false;
    input.focus();
}

const textarea = document.getElementById("msg");

textarea.addEventListener("input", function() {
    this.style.height = "54px";
    this.style.height = Math.min(this.scrollHeight, 150) + "px";
});

textarea.addEventListener("keydown", function(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMsg();
    }
});

window.addEventListener("load", function() {
    captureSourcePartnerId();
    textarea.focus();
    scrollToBottom();
});
</script>
</body>
</html>
"""

LEADS_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>ALSAAB AI Leads</title>
<style>
body { font-family: Arial; background:#111; color:white; padding:30px; }
table { width:100%; border-collapse:collapse; background:#1b1b1b; }
th, td { border:1px solid #444; padding:10px; text-align:right; }
th { background:#0b5; color:white; }
</style>
</head>
<body>
<h2>Leads / العملاء المحفوظين 🔥</h2>

<table>
<tr>
<th>ID</th>
<th>الاسم</th>
<th>الهاتف</th>
<th>النشاط</th>
<th>المشكلة</th>
<th>القناة</th>
<th>الحالة</th>
<th>التاريخ</th>
</tr>
{% for lead in leads %}
<tr>
<td>{{ lead["id"] }}</td>
<td>{{ lead["name"] }}</td>
<td>{{ lead["phone"] }}</td>
<td>{{ lead["business_type"] }}</td>
<td>{{ lead["pain_point"] }}</td>
<td>{{ lead["channel"] }}</td>
<td>{{ lead["status"] }}</td>
<td>{{ lead["created_at"] }}</td>
</tr>
{% endfor %}
</table>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/pay/<plan_name>", methods=["GET"])
def pay(plan_name):
    plan_name = str(plan_name or "").lower().strip()
    session_id = request.args.get("sid") or request.args.get("session_id")
    source_partner_id = normalize_source_partner_id(
        request.args.get("ref")
        or request.args.get("source_partner_id")
        or request.args.get("partner_id")
        or ""
    )

    if plan_name not in STRIPE_PLAN_CONFIG:
        return jsonify({
            "status": "error",
            "message": "Invalid plan name"
        }), 400

    if not session_id:
        return render_template_string("""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>ALSAAB AI Payment</title>
            <style>
                body {
                    margin: 0;
                    min-height: 100vh;
                    display: grid;
                    place-items: center;
                    background: #05070d;
                    color: #fff;
                    font-family: Arial, sans-serif;
                    padding: 24px;
                }
                .card {
                    max-width: 520px;
                    background: rgba(255,255,255,0.06);
                    border: 1px solid rgba(214,168,79,0.35);
                    border-radius: 22px;
                    padding: 28px;
                    text-align: center;
                    box-shadow: 0 24px 70px rgba(0,0,0,0.45);
                }
                h1 {
                    color: #f3d37b;
                    margin-top: 0;
                }
                p {
                    line-height: 1.8;
                    color: #cbd5e1;
                }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>رابط الدفع غير مكتمل</h1>
                <p>
                    افتح رابط الدفع من داخل محادثة ALSAAB AI عشان نربط الدفع بجلسة العميل بشكل صحيح.
                </p>
            </div>
        </body>
        </html>
        """), 400

    if not source_partner_id:
        try:
            source_partner_id = get_source_partner_id_for_session(session_id)
        except Exception as error:
            print(f"PAY SOURCE PARTNER LOOKUP ERROR ❌ {error}", flush=True)
            source_partner_id = ""

    source_partner_id = normalize_source_partner_id(source_partner_id)

    plan_config = STRIPE_PLAN_CONFIG[plan_name]
    payment_link = plan_config.get("payment_link", "")

    if not payment_link:
        return jsonify({
            "status": "error",
            "message": "Payment link is not configured"
        }), 500

    client_reference_id = build_stripe_client_reference_id(
        session_id=session_id,
        plan_name=plan_name,
        source_partner_id=source_partner_id
    )

    payment_url = append_query_params(
        payment_link,
        {
            "client_reference_id": client_reference_id
        }
    )

    print(
        f"PAYMENT REDIRECT ✅ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id} reference={client_reference_id}",
        flush=True
    )

    return redirect(payment_url, code=302)


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    signature_header = request.headers.get("Stripe-Signature", "")

    verified, verification_message = verify_stripe_signature(
        payload=payload,
        signature_header=signature_header,
        webhook_secret=STRIPE_WEBHOOK_SECRET,
        tolerance_seconds=STRIPE_WEBHOOK_TOLERANCE_SECONDS
    )

    if not verified:
        print(f"STRIPE WEBHOOK SIGNATURE FAILED ❌ {verification_message}", flush=True)

        return jsonify({
            "status": "error",
            "message": "Invalid Stripe signature"
        }), 400

    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception as error:
        print(f"STRIPE WEBHOOK JSON ERROR ❌ {error}", flush=True)

        return jsonify({
            "status": "error",
            "message": "Invalid JSON payload"
        }), 400

    event_type = event.get("type", "")
    event_id = event.get("id", "")

    print(f"STRIPE WEBHOOK RECEIVED ✅ event={event_type} id={event_id}", flush=True)

    if event_type == "checkout.session.completed":
        checkout_session = event.get("data", {}).get("object", {})

        client_reference_id = checkout_session.get("client_reference_id", "")
        session_id, plan_name, source_partner_id = parse_stripe_client_reference_id(client_reference_id)

        if not session_id or not plan_name:
            print(
                f"STRIPE CHECKOUT IGNORED ⚠️ missing client_reference_id={client_reference_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_or_invalid_client_reference_id"
            })

        plan_name = str(plan_name).lower().strip()

        if plan_name not in STRIPE_PLAN_CONFIG:
            print(f"STRIPE CHECKOUT IGNORED ⚠️ invalid plan={plan_name}", flush=True)

            return jsonify({
                "status": "ignored",
                "reason": "invalid_plan"
            })

        if not source_partner_id:
            try:
                source_partner_id = get_source_partner_id_for_session(session_id)
            except Exception as error:
                print(f"STRIPE SOURCE PARTNER LOOKUP ERROR ❌ {error}", flush=True)
                source_partner_id = ""

        source_partner_id = normalize_source_partner_id(source_partner_id)

        plan_config = STRIPE_PLAN_CONFIG[plan_name]

        stripe_customer_id = checkout_session.get("customer", "") or ""
        stripe_subscription_id = checkout_session.get("subscription", "") or ""
        package_amount = plan_config.get("package_amount", "")

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=session_id,
            bot_id="",
            status="active",
            custom_reply_limit=plan_config.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Activated automatically by Stripe checkout.session.completed event {event_id}",
            reset_usage=True,
            source_partner_id=source_partner_id
        )

        try:
            customer_details = checkout_session.get("customer_details", {}) or {}

            auto_partner_result = ensure_paid_client_is_partner(
                session_id=session_id,
                client_id=session_id,
                source_partner_id=source_partner_id,
                partner_name=customer_details.get("name", "") or "",
                phone=customer_details.get("phone", "") or "",
                email=(
                    customer_details.get("email", "")
                    or checkout_session.get("customer_email", "")
                    or ""
                ),
                country="",
                notes=f"auto_partner_from_checkout_session_completed; stripe_event_id={event_id}",
                stripe_subscription_id=stripe_subscription_id,
                plan_name=plan_name,
                package_amount=package_amount
            )

            print(f"STRIPE AUTO PARTNER RESULT {auto_partner_result}", flush=True)

        except Exception as error:
            print(f"STRIPE AUTO PARTNER ERROR {error}", flush=True)

        print(
            f"STRIPE SUBSCRIPTION ACTIVATED ✅ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id}",
            flush=True
        )

        return jsonify({
            "status": "success",
            "message": "Subscription activated",
            "subscription": subscription
        })

    if event_type == "invoice.paid":
        invoice = event.get("data", {}).get("object", {})

        invoice_id = invoice.get("id", "") or ""
        stripe_subscription_id = invoice.get("subscription", "") or ""

        if isinstance(stripe_subscription_id, dict):
            stripe_subscription_id = stripe_subscription_id.get("id", "") or ""

        if not stripe_subscription_id:
            parent = invoice.get("parent", {}) or {}
            subscription_details = parent.get("subscription_details", {}) or {}
            stripe_subscription_id = subscription_details.get("subscription", "") or ""

        if not stripe_subscription_id:
            print(
                f"STRIPE INVOICE PAID IGNORED ⚠️ missing stripe_subscription_id invoice_id={invoice_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_stripe_subscription_id",
                "invoice_id": invoice_id
            })

        existing_subscription = get_client_subscription_by_stripe_subscription_id(
            stripe_subscription_id
        )

        if not existing_subscription:
            print(
                f"STRIPE INVOICE PAID IGNORED ⚠️ subscription not found stripe_subscription_id={stripe_subscription_id} invoice_id={invoice_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "subscription_not_found",
                "stripe_subscription_id": stripe_subscription_id,
                "invoice_id": invoice_id
            })

        session_id = existing_subscription.get("session_id") or ""
        plan_name = existing_subscription.get("plan_name") or "growth"
        source_partner_id = normalize_source_partner_id(
            existing_subscription.get("source_partner_id") or ""
        )

        stripe_customer_id = (
            invoice.get("customer", "")
            or existing_subscription.get("stripe_customer_id")
            or ""
        )

        package_amount = existing_subscription.get("package_amount") or ""

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=existing_subscription.get("client_id") or session_id,
            bot_id=existing_subscription.get("bot_id") or "",
            status="active",
            custom_reply_limit=existing_subscription.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Renewed automatically by Stripe invoice.paid event {event_id}; invoice_id={invoice_id}",
            reset_usage=True,
            source_partner_id=source_partner_id
        )

        try:
            auto_partner_result = ensure_paid_client_is_partner(
                session_id=session_id,
                client_id=existing_subscription.get("client_id") or session_id,
                source_partner_id=source_partner_id,
                partner_name="",
                phone="",
                email="",
                country="",
                notes=f"auto_partner_from_invoice_paid_fallback; stripe_event_id={event_id}; invoice_id={invoice_id}",
                stripe_subscription_id=stripe_subscription_id,
                plan_name=plan_name,
                package_amount=package_amount
            )

            print(f"INVOICE PAID AUTO PARTNER RESULT {auto_partner_result}", flush=True)

        except Exception as error:
            print(f"INVOICE PAID AUTO PARTNER ERROR {error}", flush=True)

        print(
            f"STRIPE INVOICE PAID HANDLED ✅ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id} invoice_id={invoice_id}",
            flush=True
        )

        return jsonify({
            "status": "success",
            "message": "invoice.paid handled",
            "invoice_id": invoice_id,
            "stripe_subscription_id": stripe_subscription_id,
            "subscription": subscription
        })

    if event_type == "invoice.payment_failed":
        invoice = event.get("data", {}).get("object", {})

        invoice_id = invoice.get("id", "") or ""
        stripe_subscription_id = invoice.get("subscription", "") or ""

        if isinstance(stripe_subscription_id, dict):
            stripe_subscription_id = stripe_subscription_id.get("id", "") or ""

        if not stripe_subscription_id:
            parent = invoice.get("parent", {}) or {}
            subscription_details = parent.get("subscription_details", {}) or {}
            stripe_subscription_id = subscription_details.get("subscription", "") or ""

        if not stripe_subscription_id:
            print(
                f"STRIPE INVOICE PAYMENT FAILED IGNORED ⚠️ missing stripe_subscription_id invoice_id={invoice_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_stripe_subscription_id",
                "invoice_id": invoice_id
            })

        existing_subscription = get_client_subscription_by_stripe_subscription_id(
            stripe_subscription_id
        )

        if not existing_subscription:
            print(
                f"STRIPE INVOICE PAYMENT FAILED IGNORED ⚠️ subscription not found stripe_subscription_id={stripe_subscription_id} invoice_id={invoice_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "subscription_not_found",
                "stripe_subscription_id": stripe_subscription_id,
                "invoice_id": invoice_id
            })

        session_id = existing_subscription.get("session_id") or ""
        plan_name = existing_subscription.get("plan_name") or "growth"
        source_partner_id = normalize_source_partner_id(
            existing_subscription.get("source_partner_id") or ""
        )

        stripe_customer_id = (
            invoice.get("customer", "")
            or existing_subscription.get("stripe_customer_id")
            or ""
        )

        package_amount = existing_subscription.get("package_amount") or ""

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=existing_subscription.get("client_id") or session_id,
            bot_id=existing_subscription.get("bot_id") or "",
            status="payment_failed",
            custom_reply_limit=existing_subscription.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Payment failed by Stripe invoice.payment_failed event {event_id}; invoice_id={invoice_id}",
            reset_usage=False,
            source_partner_id=source_partner_id
        )

        print(
            f"STRIPE INVOICE PAYMENT FAILED HANDLED ⚠️ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id} invoice_id={invoice_id}",
            flush=True
        )

        return jsonify({
            "status": "success",
            "message": "invoice.payment_failed handled",
            "invoice_id": invoice_id,
            "stripe_subscription_id": stripe_subscription_id,
            "subscription": subscription
        })

    if event_type == "customer.subscription.deleted":
        stripe_subscription = event.get("data", {}).get("object", {})

        stripe_subscription_id = stripe_subscription.get("id", "") or ""

        if isinstance(stripe_subscription_id, dict):
            stripe_subscription_id = stripe_subscription_id.get("id", "") or ""

        if not stripe_subscription_id:
            print(
                "STRIPE SUBSCRIPTION DELETED IGNORED ⚠️ missing stripe_subscription_id",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_stripe_subscription_id"
            })

        existing_subscription = get_client_subscription_by_stripe_subscription_id(
            stripe_subscription_id
        )

        if not existing_subscription:
            print(
                f"STRIPE SUBSCRIPTION DELETED IGNORED ⚠️ subscription not found stripe_subscription_id={stripe_subscription_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "subscription_not_found",
                "stripe_subscription_id": stripe_subscription_id
            })

        session_id = existing_subscription.get("session_id") or ""
        plan_name = existing_subscription.get("plan_name") or "growth"
        source_partner_id = normalize_source_partner_id(
            existing_subscription.get("source_partner_id") or ""
        )

        stripe_customer_id = (
            stripe_subscription.get("customer", "")
            or existing_subscription.get("stripe_customer_id")
            or ""
        )

        package_amount = existing_subscription.get("package_amount") or ""

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=existing_subscription.get("client_id") or session_id,
            bot_id=existing_subscription.get("bot_id") or "",
            status="cancelled",
            custom_reply_limit=existing_subscription.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Cancelled automatically by Stripe customer.subscription.deleted event {event_id}",
            reset_usage=False,
            source_partner_id=source_partner_id
        )

        print(
            f"STRIPE SUBSCRIPTION DELETED HANDLED ⚠️ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id} stripe_subscription_id={stripe_subscription_id}",
            flush=True
        )

        return jsonify({
            "status": "success",
            "message": "customer.subscription.deleted handled",
            "stripe_subscription_id": stripe_subscription_id,
            "subscription": subscription
        })

    if event_type == "customer.subscription.updated":
        stripe_subscription = event.get("data", {}).get("object", {})

        stripe_subscription_id = stripe_subscription.get("id", "") or ""

        if isinstance(stripe_subscription_id, dict):
            stripe_subscription_id = stripe_subscription_id.get("id", "") or ""

        if not stripe_subscription_id:
            print(
                "STRIPE SUBSCRIPTION UPDATED IGNORED ⚠️ missing stripe_subscription_id",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_stripe_subscription_id"
            })

        existing_subscription = get_client_subscription_by_stripe_subscription_id(
            stripe_subscription_id
        )

        if not existing_subscription:
            print(
                f"STRIPE SUBSCRIPTION UPDATED IGNORED ⚠️ subscription not found stripe_subscription_id={stripe_subscription_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "subscription_not_found",
                "stripe_subscription_id": stripe_subscription_id
            })

        stripe_status = str(stripe_subscription.get("status", "") or "").lower().strip()

        mapped_status = existing_subscription.get("subscription_status") or "active"

        if stripe_status in ["past_due", "unpaid", "incomplete", "incomplete_expired"]:
            mapped_status = "payment_failed"

        elif stripe_status in ["canceled", "cancelled"]:
            mapped_status = "cancelled"

        elif stripe_status in ["paused"]:
            mapped_status = "inactive"

        elif stripe_status in ["active", "trialing"]:
            print(
                f"STRIPE SUBSCRIPTION UPDATED RECEIVED ✅ active update ignored for commission safety stripe_subscription_id={stripe_subscription_id}",
                flush=True
            )

            return jsonify({
                "status": "received",
                "message": "customer.subscription.updated active event received; invoice.paid handles renewal/commission logic",
                "stripe_subscription_id": stripe_subscription_id,
                "stripe_status": stripe_status
            })

        session_id = existing_subscription.get("session_id") or ""
        plan_name = existing_subscription.get("plan_name") or "growth"
        source_partner_id = normalize_source_partner_id(
            existing_subscription.get("source_partner_id") or ""
        )

        stripe_customer_id = (
            stripe_subscription.get("customer", "")
            or existing_subscription.get("stripe_customer_id")
            or ""
        )

        package_amount = existing_subscription.get("package_amount") or ""

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=existing_subscription.get("client_id") or session_id,
            bot_id=existing_subscription.get("bot_id") or "",
            status=mapped_status,
            custom_reply_limit=existing_subscription.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Updated automatically by Stripe customer.subscription.updated event {event_id}; stripe_status={stripe_status}",
            reset_usage=False,
            source_partner_id=source_partner_id
        )

        print(
            f"STRIPE SUBSCRIPTION UPDATED HANDLED ✅ session_id={session_id} mapped_status={mapped_status} stripe_status={stripe_status} stripe_subscription_id={stripe_subscription_id}",
            flush=True
        )

        return jsonify({
            "status": "success",
            "message": "customer.subscription.updated handled",
            "stripe_subscription_id": stripe_subscription_id,
            "stripe_status": stripe_status,
            "mapped_status": mapped_status,
            "subscription": subscription
        })

    return jsonify({
        "status": "ignored",
        "message": f"Unhandled event type: {event_type}"
    })


@app.route("/payment-success", methods=["GET"])
def payment_success():
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>تم الدفع - ALSAAB AI</title>
        <style>
            body {
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background:
                    radial-gradient(circle at 20% 20%, rgba(214,168,79,0.16), transparent 30%),
                    linear-gradient(135deg, #03050a, #0a0f1d);
                color: #fff;
                font-family: Arial, sans-serif;
                padding: 24px;
            }
            .card {
                max-width: 620px;
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(214,168,79,0.38);
                border-radius: 24px;
                padding: 32px;
                text-align: center;
                box-shadow: 0 24px 70px rgba(0,0,0,0.48);
            }
            h1 {
                margin-top: 0;
                color: #f3d37b;
                font-size: 28px;
            }
            p {
                color: #cbd5e1;
                line-height: 1.9;
                font-size: 16px;
            }
            .note {
                margin-top: 18px;
                color: #94a3b8;
                font-size: 13px;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>تم الدفع بنجاح ✅</h1>
            <p>
                اشتراكك في ALSAAB AI قيد التفعيل الآن.
                ارجع للمحادثة واكتب: <strong>تدريب البوت</strong>
                عشان نجهز النظام لمشروعك خطوة خطوة.
            </p>
            <div class="note">
                إذا ما تفعل الاشتراك مباشرة، انتظر دقيقة ثم جرب مرة ثانية.
            </div>
        </div>
    </body>
    </html>
    """)


@app.route("/payment-cancel", methods=["GET"])
def payment_cancel():
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>لم يكتمل الدفع - ALSAAB AI</title>
        <style>
            body {
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background:
                    radial-gradient(circle at 20% 20%, rgba(214,168,79,0.16), transparent 30%),
                    linear-gradient(135deg, #03050a, #0a0f1d);
                color: #fff;
                font-family: Arial, sans-serif;
                padding: 24px;
            }
            .card {
                max-width: 620px;
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(214,168,79,0.38);
                border-radius: 24px;
                padding: 32px;
                text-align: center;
                box-shadow: 0 24px 70px rgba(0,0,0,0.48);
            }
            h1 {
                margin-top: 0;
                color: #f3d37b;
                font-size: 28px;
            }
            p {
                color: #cbd5e1;
                line-height: 1.9;
                font-size: 16px;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>لم يكتمل الدفع</h1>
            <p>
                ما عليك، تقدر ترجع للمحادثة وتختار الباقة المناسبة لك مرة ثانية.
            </p>
        </div>
    </body>
    </html>
    """)


@app.route("/chat", methods=["POST"])
def chat():
    print("MAIN CHAT ROUTE HIT ✅", flush=True)

    data = request.json or {}
    print(f"MAIN REQUEST DATA ✅ {data}", flush=True)

    message = data.get("message", "").strip()
    session_id = data.get("session_id")
    source_partner_id = normalize_source_partner_id(
        data.get("source_partner_id")
        or data.get("referrer_partner_id")
        or data.get("ref")
        or ""
    )

    print(f"MAIN MESSAGE ✅ {message}", flush=True)
    print(f"MAIN SESSION BEFORE ✅ {session_id}", flush=True)
    print(f"MAIN SOURCE PARTNER ✅ {source_partner_id}", flush=True)

    if not session_id:
        session_id = str(uuid.uuid4())
        print(f"MAIN NEW SESSION CREATED ✅ {session_id}", flush=True)

    if not message:
        print("MAIN EMPTY MESSAGE ❌", flush=True)
        return jsonify({
            "reply": "اكتب رسالتك عشان أقدر أساعدك.",
            "session_id": session_id,
            "source_partner_id": source_partner_id
        })

    try:
        save_message(session_id, "user", message)
        print("MAIN USER MESSAGE SAVED ✅", flush=True)

        subscription = get_client_subscription(session_id)

        if is_training_command(message) and not is_active_subscription(subscription):
            print("TRAINING BLOCKED ❌ no active subscription", flush=True)

            save_message(session_id, "bot", TRAINING_LOCKED_REPLY)

            return jsonify({
                "reply": TRAINING_LOCKED_REPLY,
                "session_id": session_id,
                "source_partner_id": source_partner_id,
                "training": {
                    "allowed": False,
                    "reason": "no_active_subscription"
                }
            })

        if subscription:
            print(f"SUBSCRIPTION FOUND ✅ session_id={session_id}", flush=True)

            usage_check = can_client_use_bot(session_id)

            if not usage_check.get("allowed"):
                blocked_reply = usage_check.get("message") or "تم إيقاف الاستخدام مؤقتاً بسبب حالة الاشتراك."

                print(
                    f"USAGE BLOCKED ❌ session_id={session_id} reason={usage_check.get('reason')}",
                    flush=True
                )

                save_message(session_id, "bot", blocked_reply)

                return jsonify({
                    "reply": blocked_reply,
                    "session_id": session_id,
                    "source_partner_id": source_partner_id,
                    "usage": {
                        "allowed": False,
                        "reason": usage_check.get("reason"),
                    }
                })

        else:
            print("NO SUBSCRIPTION FOUND ✅ treating as ALSAAB main sales bot / new visitor", flush=True)

        try:
            reply = think(
                message,
                session_id,
                source_partner_id=source_partner_id
            )
        except TypeError as type_error:
            if "source_partner_id" in str(type_error) or "unexpected keyword argument" in str(type_error):
                print("THINK FALLBACK ⚠️ brain.py does not accept source_partner_id yet", flush=True)
                reply = think(message, session_id)
            else:
                raise

        print(f"MAIN THINK REPLY ✅ {reply}", flush=True)

        save_message(session_id, "bot", reply)
        print("MAIN BOT MESSAGE SAVED ✅", flush=True)

        if subscription:
            record_bot_reply_usage(session_id)
            print("BOT REPLY USAGE RECORDED ✅", flush=True)

        return jsonify({
            "reply": reply,
            "session_id": session_id,
            "source_partner_id": source_partner_id
        })

    except Exception as error:
        print(f"MAIN CHAT ERROR ❌ {error}", flush=True)

        return jsonify({
            "reply": "صار خطأ تقني مؤقت. جرب مرة ثانية.",
            "session_id": session_id,
            "source_partner_id": source_partner_id,
            "error": str(error)
        }), 500


@app.route("/admin/activate-subscription", methods=["GET", "POST"])
def activate_subscription():
    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    if request.method == "GET":
        return admin_get_preview(
            action_name="activate-subscription",
            required_fields=[
                "key",
                "session_id",
                "plan",
                "source_partner_id optional",
                "package_amount optional"
            ],
            example_body={
                "key": ADMIN_KEY,
                "session_id": "commission-test-001",
                "plan": "growth",
                "source_partner_id": "ALS-P00001",
                "package_amount": "1099 AED",
                "notes": "manual_post_activation"
            }
        )

    session_id = get_payload_value(payload, "session_id")
    plan = get_payload_value(payload, "plan", default="growth")
    client_id = get_payload_value(payload, "client_id")
    bot_id = get_payload_value(payload, "bot_id")
    status = get_payload_value(payload, "status", default="active")
    limit = get_payload_value(payload, "limit")
    package_amount = get_payload_value(payload, "package_amount")
    notes = get_payload_value(payload, "notes")

    source_partner_id = normalize_source_partner_id(
        get_payload_value(payload, "source_partner_id")
        or get_payload_value(payload, "ref")
        or get_payload_value(payload, "partner_id")
    )

    if not session_id:
        return jsonify({
            "status": "error",
            "message": "session_id is required"
        }), 400

    custom_reply_limit = None

    if limit:
        try:
            custom_reply_limit = int(limit)
        except Exception:
            return jsonify({
                "status": "error",
                "message": "limit must be a number"
            }), 400

    if not client_id:
        client_id = session_id

    if not source_partner_id:
        try:
            source_partner_id = get_source_partner_id_for_session(session_id)
        except Exception as error:
            print(f"ADMIN SOURCE PARTNER LOOKUP ERROR ❌ {error}", flush=True)
            source_partner_id = ""

    subscription = create_or_update_subscription(
        session_id=session_id,
        plan_name=plan,
        client_id=client_id,
        bot_id=bot_id,
        status=status,
        custom_reply_limit=custom_reply_limit,
        package_amount=package_amount,
        notes=notes,
        reset_usage=True,
        source_partner_id=source_partner_id
    )

    if str(status or "").lower().strip() in ["active", "paid"]:
        try:
            auto_partner_result = ensure_paid_client_is_partner(
                session_id=session_id,
                client_id=client_id,
                source_partner_id=source_partner_id,
                partner_name="",
                phone="",
                email="",
                country="",
                notes=f"auto_partner_from_admin_activate_subscription; {notes}",
                stripe_subscription_id="",
                plan_name=plan,
                package_amount=package_amount
            )

            print(f"ADMIN AUTO PARTNER RESULT {auto_partner_result}", flush=True)

        except Exception as error:
            print(f"ADMIN AUTO PARTNER ERROR {error}", flush=True)

    return jsonify({
        "status": "success",
        "message": "Subscription activated successfully",
        "subscription": subscription
    })


@app.route("/admin/usage-summary", methods=["GET"])
def usage_summary():
    key = request.args.get("key")

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    session_id = request.args.get("session_id", "").strip()

    if not session_id:
        return jsonify({
            "status": "error",
            "message": "session_id is required"
        }), 400

    summary = get_usage_summary(session_id)

    return jsonify({
        "status": "success",
        "usage": summary
    })


@app.route("/admin/create-partner", methods=["GET", "POST"])
def create_partner():
    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    if request.method == "GET":
        return admin_get_preview(
            action_name="create-partner",
            required_fields=[
                "key",
                "partner_name",
                "phone",
                "invited_by",
                "level"
            ],
            example_body={
                "key": ADMIN_KEY,
                "partner_name": "MLM Level 1 Test",
                "phone": "+971500000001",
                "email": "test@alsaab.ai",
                "country": "UAE",
                "invited_by": "alsaab",
                "level": "Level 1",
                "status": "active",
                "notes": "created_by_post_only"
            }
        )

    partner_name = (
        get_payload_value(payload, "partner_name")
        or get_payload_value(payload, "name")
    )

    phone = (
        get_payload_value(payload, "phone")
        or get_payload_value(payload, "whatsapp")
    )

    email = get_payload_value(payload, "email")
    country = get_payload_value(payload, "country")
    invited_by = (
        get_payload_value(payload, "invited_by")
        or get_payload_value(payload, "invitedBy")
        or get_payload_value(payload, "sponsor_partner_id")
        or get_payload_value(payload, "sponsor_id")
        or get_payload_value(payload, "parent_partner_id")
        or get_payload_value(payload, "ref")
        or get_payload_value(payload, "source_partner_id")
    )
    notes = get_payload_value(payload, "notes")
    level = get_payload_value(payload, "level", default="Level 1")
    status = get_payload_value(payload, "status", default="active")
    client_id = get_payload_value(payload, "client_id")

    if not partner_name:
        return jsonify({
            "status": "error",
            "message": "partner name is required"
        }), 400

    if not phone:
        return jsonify({
            "status": "error",
            "message": "phone is required"
        }), 400

    if not invited_by:
        return jsonify({
            "status": "error",
            "message": "invited_by / sponsor_partner_id is required"
        }), 400

    try:
        result = send_partner_to_google_sheet(
            partner_name=partner_name,
            phone=phone,
            email=email,
            country=country,
            invited_by=invited_by,
            notes=notes,
            level=level,
            status=status,
            client_id=client_id,
            sponsor_partner_id=invited_by,
            parent_partner_id=invited_by,
            partner_rank=level
        )
    except TypeError:
        result = send_partner_to_google_sheet(
            partner_name=partner_name,
            phone=phone,
            email=email,
            country=country,
            invited_by=invited_by,
            notes=notes,
            level=level,
            status=status
        )

    if result.get("status") == "success":
        return jsonify({
            "status": "success",
            "message": result.get("message", "Partner saved"),
            "partner_id": result.get("partner_id", ""),
            "referral_link": result.get("referral_link", ""),
            "sponsor_partner_id": result.get("sponsor_partner_id", invited_by),
            "parent_partner_id": result.get("parent_partner_id", invited_by),
            "invited_by": result.get("invited_by", invited_by),
            "result": result
        })

    return jsonify({
        "status": "error",
        "message": result.get("message", "Partner save failed"),
        "result": result
    }), 500


@app.route("/leads", methods=["GET"])
def leads_json():
    key = request.args.get("key")

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    return jsonify(get_leads())


@app.route("/leads-view", methods=["GET"])
def leads_view():
    key = request.args.get("key")

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    leads = get_leads()
    return render_template_string(LEADS_HTML, leads=leads)



# ===== ALSAAB_PARTNER_DASHBOARD_RENDER_API_V1 START =====

@app.route("/partner-dashboard-data", methods=["GET", "POST"])
def partner_dashboard_data():
    """
    Partner Dashboard Data API MVP.

    Temporary security:
    - Requires ADMIN_KEY for testing.
    - Later this must use logged-in user session and resolve partner_id internally.

    Returns:
    - partner profile
    - level progress
    - direct customers
    - commissions
    - courses
    - tree data
    """
    import os

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.args.get("partner_id", "").strip()
    )

    partner_id = str(partner_id or "").strip()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing in environment"
            }), 500

        sheet_payload = {
            "token": google_sheet_token,
            "action": "partner_dashboard_data",
            "partner_id": partner_id
        }

        result = post_to_google_sheet_json(
            sheet_payload,
            label="partner_dashboard_data"
        )

        if not isinstance(result, dict):
            return jsonify({
                "status": "error",
                "message": "Invalid partner dashboard response",
                "raw_result": str(result)
            }), 500

        return jsonify(result)

    except Exception as error:
        print(
            f"PARTNER DASHBOARD DATA ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        return jsonify({
            "status": "error",
            "message": str(error),
            "partner_id": partner_id
        }), 500

# ===== ALSAAB_PARTNER_DASHBOARD_RENDER_API_V1 END =====



# ===== ALSAAB_PARTNER_DASHBOARD_UI_MVP_V1 START =====

@app.route("/partner-dashboard", methods=["GET"])
def partner_dashboard_view():
    """
    Partner Dashboard MVP page.

    Temporary security:
    - Requires ADMIN_KEY for testing.
    - Later this will use logged-in WordPress/user session.
    """
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()
    sso_token = request.args.get("sso", "").strip() or request.args.get("token", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("partner", "", request.args.get("lang", "ar"))), 302

    partner_id = (
        request.args.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        return redirect(build_dashboard_login_redirect("partner", partner_id, request.args.get("lang", "ar"))), 302

    if not partner_id:
        return "partner_id is required", 400

    lang = request.args.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    is_ar = lang == "ar"
    direction = "rtl" if is_ar else "ltr"
    text_align = "right" if is_ar else "left"

    try:
        from config import WEBSITE_URL
    except Exception:
        WEBSITE_URL = "https://alsaab.io"

    t = {
        "ar": {
            "page_title": "ALSAAB AI - لوحة الشريك",
            "dashboard_title": "Partner Dashboard",
            "intro": "لوحة الشريك الرسمية في ALSAAB AI. هنا تشوف رابطك، مستواك، عملاءك، عمولاتك، ومتطلبات الترقية.",
            "back_site": "العودة إلى موقع ALSAAB AI",
            "language": "English",
            "partner_id": "Partner ID",
            "current_level": "المستوى الحالي",
            "next": "التالي",
            "active_direct_customers": "العملاء المباشرين النشطين",
            "all_direct": "إجمالي المباشرين",
            "pending_commissions": "العمولات المعلقة",
            "commission_count": "عددها",
            "partner_info": "بيانات الشريك",
            "name": "الاسم",
            "status": "الحالة",
            "sponsor": "Sponsor",
            "referral_link": "Referral Link",
            "level_progress": "المستوى والترقية",
            "completed_sales": "Completed Sales",
            "required_sales": "Required Sales",
            "current_package": "Current Package",
            "subscription_status": "Subscription Status",
            "commission_eligible": "Commission Eligible",
            "required_course": "Required Course",
            "missing_requirements": "Missing Requirements",
            "network": "الشبكة",
            "direct": "المباشرين",
            "level_2": "المستوى الثاني",
            "level_3": "المستوى الثالث",
            "total_network": "إجمالي الشبكة",
            "commission_summary": "ملخص العمولات",
            "recent_commissions": "آخر العمولات",
            "date": "التاريخ",
            "depth": "العمق",
            "package": "الباقة",
            "percent": "النسبة",
            "amount": "المبلغ",
            "direct_customers": "العملاء المباشرين",
            "client_id": "Client ID",
            "courses": "الكورسات والمتطلبات",
            "course": "الكورس",
            "code": "الكود",
            "paid_at": "تاريخ الدفع",
            "no_commissions": "لا توجد عمولات حتى الآن.",
            "no_customers": "لا يوجد عملاء مباشرين حتى الآن.",
            "no_courses": "لا توجد كورسات مسجلة حتى الآن.",
            "mvp_note_title": "ملاحظة",
            "mvp_note": "هذه نسخة MVP تجريبية من Partner Dashboard. لاحقاً سيتم ربطها بتسجيل الدخول الرسمي، وإخفاء مفتاح الإدارة، وتحسين التصميم والصلاحيات.",
            "logo_note": "سيتم استبدال هذا المكان بشعار الشركة الرسمي لاحقاً."
        },
        "en": {
            "page_title": "ALSAAB AI - Partner Dashboard",
            "dashboard_title": "Partner Dashboard",
            "intro": "The official ALSAAB AI partner dashboard. View your referral link, level, customers, commissions, and upgrade requirements.",
            "back_site": "Back to ALSAAB AI Website",
            "language": "العربية",
            "partner_id": "Partner ID",
            "current_level": "Current Level",
            "next": "Next",
            "active_direct_customers": "Active Direct Customers",
            "all_direct": "All Direct Customers",
            "pending_commissions": "Pending Commissions",
            "commission_count": "Count",
            "partner_info": "Partner Information",
            "name": "Name",
            "status": "Status",
            "sponsor": "Sponsor",
            "referral_link": "Referral Link",
            "level_progress": "Level & Progress",
            "completed_sales": "Completed Sales",
            "required_sales": "Required Sales",
            "current_package": "Current Package",
            "subscription_status": "Subscription Status",
            "commission_eligible": "Commission Eligible",
            "required_course": "Required Course",
            "missing_requirements": "Missing Requirements",
            "network": "Network",
            "direct": "Direct",
            "level_2": "Level 2",
            "level_3": "Level 3",
            "total_network": "Total Network",
            "commission_summary": "Commission Summary",
            "recent_commissions": "Recent Commissions",
            "date": "Date",
            "depth": "Depth",
            "package": "Package",
            "percent": "Percent",
            "amount": "Amount",
            "direct_customers": "Direct Customers",
            "client_id": "Client ID",
            "courses": "Courses & Requirements",
            "course": "Course",
            "code": "Code",
            "paid_at": "Paid At",
            "no_commissions": "No commissions yet.",
            "no_customers": "No direct customers yet.",
            "no_courses": "No courses recorded yet.",
            "mvp_note_title": "Note",
            "mvp_note": "This is an MVP version of the Partner Dashboard. Later it will be connected to the official login system, admin key will be removed, and permissions/design will be improved.",
            "logo_note": "This area will be replaced with the official company logo later."
        }
    }[lang]

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN is missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "partner_dashboard_data",
                "partner_id": partner_id
            },
            label="partner_dashboard_page"
        )

        if not isinstance(result, dict) or result.get("status") != "success":

            # ===== ALSAAB_FORCE_WHATSAPP_FORM_IN_CLIENT_PAGES_V3 START =====
            try:
                if isinstance(html, str) and "ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3" not in html:
                    html = html.replace("</body>", r"""
        <!-- ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3 START -->
        <div class="section" style="margin-top:18px;">
          <h2>إعداد WhatsApp</h2>
          <div class="muted">
            أرسل طلب ربط موظف المبيعات الذكي على رقم WhatsApp Business الحالي الخاص بمشروعك.
          </div>

          {% if request.args.get("saved") == "whatsapp_setup_saved" %}
          <div style="background:rgba(128,226,138,.08); border:1px solid rgba(128,226,138,.4); color:#80e28a; border-radius:14px; padding:13px 16px; margin:14px 0; font-weight:700;">
            تم إرسال طلب ربط WhatsApp بنجاح.
          </div>
          {% elif request.args.get("saved") == "whatsapp_setup_error" %}
          <div style="background:rgba(255,122,122,.08); border:1px solid rgba(255,122,122,.4); color:#ff7a7a; border-radius:14px; padding:13px 16px; margin:14px 0; font-weight:700;">
            حدث خطأ أثناء حفظ طلب WhatsApp.
          </div>
          {% endif %}

          <form method="POST" action="/client-dashboard/save-whatsapp-setup" style="margin-top:14px;">
            <input type="hidden" name="key" value="{{ request.args.get('key', '') }}">
            <input type="hidden" name="sso" value="{{ request.args.get('sso', '') or request.args.get('token', '') }}">
            <input type="hidden" name="partner_id" value="{{ partner_id if partner_id is defined else request.args.get('partner_id', '') }}">
            <input type="hidden" name="lang" value="{{ request.args.get('lang', 'ar') }}">

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              اسم النشاط / الشركة
            </label>
            <input
              name="business_name"
              placeholder="مثال: Alsaab Projects Management"
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              رقم WhatsApp Business الحالي
            </label>
            <input
              name="whatsapp_number"
              required
              placeholder="+971..."
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              لغة الرد الأساسية
            </label>
            <select
              name="preferred_language"
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >
              <option value="ar">العربية</option>
              <option value="en">English</option>
              <option value="both">Arabic + English</option>
            </select>

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              ملاحظات للربط
            </label>
            <textarea
              name="customer_notes"
              placeholder="مثال: هذا الرقم مستخدم حالياً في WhatsApp Business، ونريد ربط النظام عليه."
              style="width:100%; min-height:90px; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            ></textarea>

            <button
              type="submit"
              style="border:1px solid rgba(215,184,90,.75); color:#0b0b0b; background:linear-gradient(135deg,#d7b85a,#a88425); padding:12px 18px; border-radius:999px; font-weight:900; cursor:pointer;"
            >
              إرسال طلب ربط WhatsApp
            </button>
          </form>

          <div class="muted" style="margin-top:10px;">
            بعد الإرسال، تظهر الحالة عند الإدارة للمراجعة والربط.
          </div>
        </div>
        <!-- ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3 END -->
""" + "\n</body>", 1)
            except Exception as whatsapp_form_error:
                print(f"CLIENT WHATSAPP FORM INJECTION ERROR ❌ {whatsapp_form_error}", flush=True)
            # ===== ALSAAB_FORCE_WHATSAPP_FORM_IN_CLIENT_PAGES_V3 END =====

            return render_template_string(
                """
                <html>
                <head><meta charset="utf-8"><title>Partner Dashboard Error</title></head>
                <body style="font-family:Arial; direction:rtl; padding:30px;">
                  <h2>حدث خطأ في تحميل بيانات الشريك</h2>
                  <pre>{{ result }}</pre>
                </body>
                </html>
                """,
                result=result
            ), 500

        profile = result.get("partner_profile") or {}
        level = result.get("level") or {}
        customers = result.get("customers") or {}
        commissions = result.get("commissions") or {}
        courses = result.get("courses") or {}
        tree = result.get("tree") or {}

        totals = commissions.get("totals") or {}
        counts = commissions.get("counts") or {}
        recent_commissions = commissions.get("recent") or []
        recent_customers = customers.get("recent") or []
        purchased_courses = courses.get("purchased_courses") or []
        depth_counts = tree.get("depth_counts") or {}

        ar_url = build_dashboard_nav_url("/partner-dashboard", partner_id, "ar", key)
        en_url = build_dashboard_nav_url("/partner-dashboard", partner_id, "en", key)

        language_url = en_url if is_ar else ar_url
        partner_dashboard_url = build_dashboard_nav_url("/partner-dashboard", partner_id, lang, key)
        client_dashboard_url = build_dashboard_nav_url("/client-dashboard", partner_id, lang, key)
        owner_advisory_url = build_dashboard_nav_url("/owner-advisory", partner_id, lang, key)

        def money(value):
            try:
                return f"{float(value or 0):,.2f} AED"
            except Exception:
                return f"{value or 0} AED"

        html = """
<!DOCTYPE html>
<html lang="{{ lang }}" dir="{{ direction }}">
<head>
  <meta charset="utf-8">
  <title>{{ t.page_title }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      margin: 0;
      background: #0b0b0b;
      color: #f5f0df;
      font-family: Arial, Tahoma, sans-serif;
      direction: {{ direction }};
      text-align: {{ text_align }};
    }

    .page {
      max-width: 1200px;
      margin: 0 auto;
      padding: 28px;
    }

    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .logo-mark {
      width: 54px;
      height: 54px;
      border-radius: 16px;
      border: 1px solid #c8a84b;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #d7b85a;
      font-weight: 800;
      letter-spacing: 1px;
      background: linear-gradient(135deg, #111, #211c0f);
      box-shadow: 0 0 18px rgba(200, 168, 75, 0.2);
      font-size: 12px;
    }

    .brand-title {
      color: #d7b85a;
      font-size: 19px;
      font-weight: 800;
    }

    .brand-note {
      color: #9f967b;
      font-size: 12px;
      margin-top: 3px;
    }

    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    .action-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(215, 184, 90, 0.5);
      color: #f0cc68;
      background: #111;
      padding: 10px 14px;
      border-radius: 999px;
      text-decoration: none;
      font-size: 14px;
    }

    .action-btn:hover {
      background: #1a160d;
    }

    .portal-switch {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }

    .portal-card {
      background: linear-gradient(135deg, #111, #17130b);
      border: 1px solid rgba(215, 184, 90, 0.45);
      border-radius: 18px;
      padding: 18px;
      color: #f5f0df;
      text-decoration: none;
      display: block;
      transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
    }

    .portal-card:hover {
      transform: translateY(-2px);
      border-color: #d7b85a;
      background: linear-gradient(135deg, #161616, #211a0d);
    }

    .portal-card.active {
      border-color: #d7b85a;
      background: linear-gradient(135deg, #d7b85a, #8b6b21);
      color: #0b0b0b;
      box-shadow: 0 0 25px rgba(215, 184, 90, 0.22);
      position: relative;
    }

    .portal-card.active .portal-card-title,
    .portal-card.active .portal-card-text {
      color: #0b0b0b;
    }

    .portal-card.active::after {
      content: "أنت هنا";
      position: absolute;
      top: 12px;
      left: 14px;
      background: #0b0b0b;
      color: #f0cc68;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 700;
    }

    .portal-card-title {
      color: #d7b85a;
      font-weight: 800;
      font-size: 20px;
      margin-bottom: 8px;
    }

    .portal-card-text {
      color: #cfc7ad;
      line-height: 1.6;
      font-size: 14px;
    }

    .header {
      background: linear-gradient(135deg, #111, #1d1a10);
      border: 1px solid #c8a84b;
      border-radius: 18px;
      padding: 24px;
      margin-bottom: 20px;
      box-shadow: 0 0 25px rgba(200, 168, 75, 0.12);
    }

    .header h1 {
      margin: 0 0 8px;
      color: #d7b85a;
      font-size: 28px;
    }

    .sub {
      color: #cfc7ad;
      line-height: 1.7;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 20px;
    }

    .card {
      background: #121212;
      border: 1px solid rgba(215, 184, 90, 0.35);
      border-radius: 16px;
      padding: 18px;
    }

    .card h3 {
      margin: 0 0 10px;
      color: #d7b85a;
      font-size: 16px;
    }

    .big {
      font-size: 26px;
      font-weight: 700;
      color: #fff;
    }

    .muted {
      color: #aaa;
      font-size: 13px;
      margin-top: 5px;
    }

    .section {
      background: #111;
      border: 1px solid rgba(215, 184, 90, 0.25);
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 18px;
    }

    .status-message {
      background: rgba(128, 226, 138, 0.08);
      border: 1px solid rgba(128, 226, 138, 0.4);
      color: #80e28a;
      border-radius: 14px;
      padding: 13px 16px;
      margin-bottom: 18px;
      font-weight: 700;
    }

    .small-list {
      margin-top: 14px;
      border-top: 1px solid rgba(255,255,255,0.08);
      padding-top: 12px;
    }

    .small-item {
      border: 1px solid rgba(215, 184, 90, 0.20);
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 10px;
      background: rgba(255,255,255,0.02);
    }

    .small-item-title {
      color: #d7b85a;
      font-weight: 800;
      margin-bottom: 6px;
    }

    .section h2 {
      margin: 0 0 14px;
      color: #d7b85a;
      font-size: 21px;
    }

    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 14px;
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: 7px;
    }

    .field.full {
      grid-column: 1 / -1;
    }

    .field label {
      color: #d7b85a;
      font-size: 14px;
      font-weight: 700;
    }

    input, textarea {
      width: 100%;
      box-sizing: border-box;
      background: #0b0b0b;
      border: 1px solid rgba(215, 184, 90, 0.35);
      color: #fff;
      border-radius: 12px;
      padding: 12px;
      font-family: Arial, Tahoma, sans-serif;
      font-size: 14px;
      outline: none;
    }

    textarea {
      min-height: 110px;
      resize: vertical;
    }

    .upload-box {
      border: 1px dashed rgba(215, 184, 90, 0.45);
      border-radius: 14px;
      padding: 18px;
      color: #cfc7ad;
      background: rgba(255,255,255,0.02);
      margin-top: 12px;
    }

    .primary-btn {
      display: inline-block;
      margin-top: 12px;
      border: 1px solid rgba(215, 184, 90, 0.55);
      background: linear-gradient(135deg, #2a220f, #141414);
      color: #f0cc68;
      padding: 11px 16px;
      border-radius: 999px;
      text-decoration: none;
      font-weight: 700;
      cursor: pointer;
      opacity: 1;
    }

    .info-row {
      display: grid;
      grid-template-columns: 210px 1fr;
      gap: 12px;
      padding: 9px 0;
      border-bottom: 1px solid rgba(255,255,255,0.08);
    }

    .label {
      color: #c8a84b;
    }

    .value {
      color: #fff;
      word-break: break-word;
    }

    a {
      color: #f0cc68;
      text-decoration: none;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      overflow: hidden;
      border-radius: 12px;
    }

    th, td {
      padding: 11px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      text-align: {{ text_align }};
      font-size: 14px;
    }

    th {
      color: #d7b85a;
      background: #181818;
    }

    td {
      color: #f5f0df;
    }

    .badge {
      display: inline-block;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid rgba(215, 184, 90, 0.45);
      color: #f0cc68;
      font-size: 13px;
    }

    pre {
      white-space: pre-wrap;
      background: #0b0b0b;
      border: 1px solid rgba(215, 184, 90, 0.25);
      padding: 12px;
      border-radius: 12px;
      color: #eee;
      direction: ltr;
      text-align: left;
    }

    @media (max-width: 900px) {
      .grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .info-row {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 600px) {
      .grid {
        grid-template-columns: 1fr;
      }

      .page {
        padding: 16px;
      }
    }
  </style>
</head>
<body>
  <div class="page">

    <div class="topbar">
      <div class="brand">
        <div class="logo-mark">ALSAAB</div>
        <div>
          <div class="brand-title">ALSAAB AI</div>
          <div class="brand-note">{{ t.logo_note }}</div>
        </div>
      </div>

      <div class="actions">
        <a class="action-btn" href="{{ website_url }}">{{ t.back_site }}</a>
        <a class="action-btn" href="{{ language_url }}">{{ t.language }}</a>
      </div>
    </div>

    <div class="portal-switch">
      <a class="portal-card active" href="{{ partner_dashboard_url }}">
        <div class="portal-card-title">Partner Dashboard</div>
        <div class="portal-card-text">
          الشراكة، العمولات، المستويات، العملاء، الكورسات، ومتطلبات الترقية.
        </div>
      </a>

      <a class="portal-card" href="{{ client_dashboard_url }}">
        <div class="portal-card-title">Client Dashboard</div>
        <div class="portal-card-text">
          مشروعك، باقتك، استخدامك، بيانات موظف المبيعات الذكي، الصور، والكتالوجات.
        </div>
      </a>
    </div>
    <div class="grid">
      <div class="card">
        <h3>{{ t.partner_id }}</h3>
        <div class="big">{{ profile.partner_id }}</div>
        <div class="muted">{{ profile.partner_name or "Partner" }}</div>
      </div>

      <div class="card">
        <h3>{{ t.current_level }}</h3>
        <div class="big">{{ level.current_level or level.partner_rank or "Level 1" }}</div>
        <div class="muted">{{ t.next }}: {{ level.next_rank or "-" }}</div>
      </div>

      <div class="card">
        <h3>{{ t.active_direct_customers }}</h3>
        <div class="big">{{ customers.active_direct_paid_count or 0 }}</div>
        <div class="muted">{{ t.all_direct }}: {{ customers.all_direct_count or 0 }}</div>
      </div>

      <div class="card">
        <h3>{{ t.pending_commissions }}</h3>
        <div class="big">{{ money(totals.pending) }}</div>
        <div class="muted">{{ t.commission_count }}: {{ counts.pending or 0 }}</div>
      </div>
    </div>

    <div class="section">
      <h2>{{ t.partner_info }}</h2>
      <div class="info-row"><div class="label">{{ t.partner_id }}</div><div class="value">{{ profile.partner_id }}</div></div>
      <div class="info-row"><div class="label">{{ t.name }}</div><div class="value">{{ profile.partner_name or "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.status }}</div><div class="value"><span class="badge">{{ profile.status or "-" }}</span></div></div>
      <div class="info-row"><div class="label">{{ t.sponsor }}</div><div class="value">{{ profile.sponsor_partner_id or "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.referral_link }}</div><div class="value"><a href="{{ profile.referral_link }}" target="_blank">{{ profile.referral_link }}</a></div></div>
    </div>

    <div class="section">
      <h2>{{ t.level_progress }}</h2>
      <div class="info-row"><div class="label">{{ t.current_level }}</div><div class="value">{{ level.current_level or level.partner_rank or "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.next }}</div><div class="value">{{ level.next_rank or "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.completed_sales }}</div><div class="value">{{ level.completed_sales or "0" }}</div></div>
      <div class="info-row"><div class="label">{{ t.required_sales }}</div><div class="value">{{ level.required_sales or "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.current_package }}</div><div class="value">{{ level.current_package or "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.subscription_status }}</div><div class="value">{{ level.subscription_status or "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.commission_eligible }}</div><div class="value">{{ level.commission_eligible or "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.required_course }}</div><div class="value">{{ level.required_course_workshop or "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.missing_requirements }}</div><div class="value"><pre>{{ level.missing_requirements or "-" }}</pre></div></div>
    </div>

    <div class="section">
      <h2>{{ t.network }}</h2>
      <div class="grid">
        <div class="card"><h3>{{ t.direct }}</h3><div class="big">{{ depth_counts.get("1", 0) }}</div></div>
        <div class="card"><h3>{{ t.level_2 }}</h3><div class="big">{{ depth_counts.get("2", 0) }}</div></div>
        <div class="card"><h3>{{ t.level_3 }}</h3><div class="big">{{ depth_counts.get("3", 0) }}</div></div>
        <div class="card"><h3>{{ t.total_network }}</h3><div class="big">{{ tree.downline_count or 0 }}</div></div>
      </div>
    </div>

    <div class="section">
      <h2>{{ t.commission_summary }}</h2>
      <div class="grid">
        <div class="card"><h3>Pending</h3><div class="big">{{ money(totals.pending) }}</div><div class="muted">{{ counts.pending or 0 }}</div></div>
        <div class="card"><h3>Approved</h3><div class="big">{{ money(totals.approved) }}</div><div class="muted">{{ counts.approved or 0 }}</div></div>
        <div class="card"><h3>Paid</h3><div class="big">{{ money(totals.paid) }}</div><div class="muted">{{ counts.paid or 0 }}</div></div>
        <div class="card"><h3>Total</h3><div class="big">{{ money(totals.all) }}</div><div class="muted">{{ counts.all or 0 }}</div></div>
      </div>
    </div>

    <div class="section">
      <h2>{{ t.recent_commissions }}</h2>
      <table>
        <thead>
          <tr>
            <th>{{ t.date }}</th>
            <th>{{ t.depth }}</th>
            <th>{{ t.package }}</th>
            <th>{{ t.percent }}</th>
            <th>{{ t.amount }}</th>
            <th>{{ t.status }}</th>
          </tr>
        </thead>
        <tbody>
          {% for c in recent_commissions[:10] %}
          <tr>
            <td>{{ c.date or "-" }}</td>
            <td>{{ c.commission_depth or "-" }}</td>
            <td>{{ c.package or "-" }}</td>
            <td>{{ c.commission_percent or "-" }}%</td>
            <td>{{ money(c.commission_amount) }}</td>
            <td><span class="badge">{{ c.status or "-" }}</span></td>
          </tr>
          {% else %}
          <tr><td colspan="6">{{ t.no_commissions }}</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>{{ t.direct_customers }}</h2>
      <table>
        <thead>
          <tr>
            <th>{{ t.date }}</th>
            <th>{{ t.client_id }}</th>
            <th>{{ t.package }}</th>
            <th>{{ t.amount }}</th>
            <th>{{ t.status }}</th>
          </tr>
        </thead>
        <tbody>
          {% for customer in recent_customers[:10] %}
          <tr>
            <td>{{ customer.date or "-" }}</td>
            <td>{{ customer.client_id or customer.session_id or "-" }}</td>
            <td>{{ customer.plan_name or "-" }}</td>
            <td>{{ money(customer.package_amount) }}</td>
            <td><span class="badge">{{ customer.subscription_status or "-" }}</span></td>
          </tr>
          {% else %}
          <tr><td colspan="5">{{ t.no_customers }}</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>{{ t.courses }}</h2>
      <table>
        <thead>
          <tr>
            <th>{{ t.course }}</th>
            <th>{{ t.code }}</th>
            <th>{{ t.amount }}</th>
            <th>{{ t.status }}</th>
            <th>{{ t.paid_at }}</th>
          </tr>
        </thead>
        <tbody>
          {% for course in purchased_courses %}
          <tr>
            <td>{{ course.course_name or "-" }}</td>
            <td>{{ course.course_code or "-" }}</td>
            <td>{{ money(course.amount) }}</td>
            <td><span class="badge">{{ course.status or "-" }}</span></td>
            <td>{{ course.paid_at or course.date or "-" }}</td>
          </tr>
          {% else %}
          <tr><td colspan="5">{{ t.no_courses }}</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>{{ t.mvp_note_title }}</h2>
      <div class="sub">{{ t.mvp_note }}</div>
    </div>
  </div>
</body>
</html>
        """


        # ===== ALSAAB_FORCE_WHATSAPP_FORM_IN_CLIENT_PAGES_V3 START =====

        try:

            if isinstance(html, str) and "ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3" not in html:

                html = html.replace("</body>", r"""
        <!-- ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3 START -->
        <div class="section" style="margin-top:18px;">
          <h2>إعداد WhatsApp</h2>
          <div class="muted">
            أرسل طلب ربط موظف المبيعات الذكي على رقم WhatsApp Business الحالي الخاص بمشروعك.
          </div>

          {% if request.args.get("saved") == "whatsapp_setup_saved" %}
          <div style="background:rgba(128,226,138,.08); border:1px solid rgba(128,226,138,.4); color:#80e28a; border-radius:14px; padding:13px 16px; margin:14px 0; font-weight:700;">
            تم إرسال طلب ربط WhatsApp بنجاح.
          </div>
          {% elif request.args.get("saved") == "whatsapp_setup_error" %}
          <div style="background:rgba(255,122,122,.08); border:1px solid rgba(255,122,122,.4); color:#ff7a7a; border-radius:14px; padding:13px 16px; margin:14px 0; font-weight:700;">
            حدث خطأ أثناء حفظ طلب WhatsApp.
          </div>
          {% endif %}

          <form method="POST" action="/client-dashboard/save-whatsapp-setup" style="margin-top:14px;">
            <input type="hidden" name="key" value="{{ request.args.get('key', '') }}">
            <input type="hidden" name="sso" value="{{ request.args.get('sso', '') or request.args.get('token', '') }}">
            <input type="hidden" name="partner_id" value="{{ partner_id if partner_id is defined else request.args.get('partner_id', '') }}">
            <input type="hidden" name="lang" value="{{ request.args.get('lang', 'ar') }}">

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              اسم النشاط / الشركة
            </label>
            <input
              name="business_name"
              placeholder="مثال: Alsaab Projects Management"
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              رقم WhatsApp Business الحالي
            </label>
            <input
              name="whatsapp_number"
              required
              placeholder="+971..."
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              لغة الرد الأساسية
            </label>
            <select
              name="preferred_language"
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >
              <option value="ar">العربية</option>
              <option value="en">English</option>
              <option value="both">Arabic + English</option>
            </select>

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              ملاحظات للربط
            </label>
            <textarea
              name="customer_notes"
              placeholder="مثال: هذا الرقم مستخدم حالياً في WhatsApp Business، ونريد ربط النظام عليه."
              style="width:100%; min-height:90px; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            ></textarea>

            <button
              type="submit"
              style="border:1px solid rgba(215,184,90,.75); color:#0b0b0b; background:linear-gradient(135deg,#d7b85a,#a88425); padding:12px 18px; border-radius:999px; font-weight:900; cursor:pointer;"
            >
              إرسال طلب ربط WhatsApp
            </button>
          </form>

          <div class="muted" style="margin-top:10px;">
            بعد الإرسال، تظهر الحالة عند الإدارة للمراجعة والربط.
          </div>
        </div>
        <!-- ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3 END -->
""" + "\n</body>", 1)

        except Exception as whatsapp_form_error:

            print(f"CLIENT WHATSAPP FORM INJECTION ERROR ❌ {whatsapp_form_error}", flush=True)

        # ===== ALSAAB_FORCE_WHATSAPP_FORM_IN_CLIENT_PAGES_V3 END =====


        return render_template_string(
            html,
            lang=lang,
            direction=direction,
            text_align=text_align,
            t=t,
            website_url=WEBSITE_URL,
            language_url=language_url,
            partner_dashboard_url=partner_dashboard_url,
            client_dashboard_url=client_dashboard_url,
            owner_advisory_url=owner_advisory_url,
            data=result,
            profile=profile,
            level=level,
            customers=customers,
            commissions=commissions,
            totals=totals,
            counts=counts,
            recent_commissions=recent_commissions,
            recent_customers=recent_customers,
            purchased_courses=purchased_courses,
            tree=tree,
            depth_counts=depth_counts,
            money=money
        )

    except Exception as error:
        print(
            f"PARTNER DASHBOARD VIEW ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        return render_template_string(
            """
            <html>
            <head><meta charset="utf-8"><title>Partner Dashboard Error</title></head>
            <body style="font-family:Arial; direction:rtl; padding:30px;">
              <h2>حدث خطأ في عرض Partner Dashboard</h2>
              <p>{{ error }}</p>
            </body>
            </html>
            """,
            error=str(error)
        ), 500

# ===== ALSAAB_PARTNER_DASHBOARD_UI_MVP_V1 END =====



# ===== ALSAAB_CLIENT_DASHBOARD_UI_MVP_V1 START =====

@app.route("/client-dashboard", methods=["GET"])
def client_dashboard_view():
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()
    sso_token = request.args.get("sso", "").strip() or request.args.get("token", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", request.args.get("lang", "ar"))), 302

    partner_id = (
        request.args.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        return redirect(build_dashboard_login_redirect("client", partner_id, request.args.get("lang", "ar"))), 302

    if not partner_id:
        return "partner_id is required", 400

    lang = request.args.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    is_ar = lang == "ar"
    direction = "rtl" if is_ar else "ltr"
    text_align = "right" if is_ar else "left"

    try:
        from config import WEBSITE_URL, PACKAGES
    except Exception:
        WEBSITE_URL = "https://alsaab.io"
        PACKAGES = {}

    t = {
        "ar": {
            "page_title": "ALSAAB AI - لوحة العميل",
            "back_site": "العودة إلى موقع ALSAAB AI",
            "language": "English",
            "partner_portal": "Partner Dashboard",
            "client_portal": "Client Dashboard",
            "partner_text": "الشراكة، العمولات، المستويات، العملاء، الكورسات، ومتطلبات الترقية.",
            "client_text": "مشروعك، باقتك، استخدامك، بيانات موظف المبيعات الذكي، الصور، والكتالوجات.",
            "account_id": "معرف الحساب",
            "current_package": "الباقة الحالية",
            "subscription_status": "حالة الاشتراك",
            "customer_replies": "ردود العملاء",
            "advisory_replies": "ردود الاستشارات",
            "channels": "القنوات",
            "owner_advisory": "استشارات صاحب المشروع",
            "owner_advisory_desc": "من هنا تفتح محادثة خاصة مع موظف المبيعات الذكي كمستشار لمشروعك. المحادثة مرتبطة بمعرف حسابك حتى يستمر معك في رحلة تطوير طويلة.",
            "ask_advisor": "فتح الاستشارات الخاصة",
            "project_data": "بيانات المشروع",
            "project_data_desc": "اكتب معلومات مشروعك الأساسية حتى يفهم موظف المبيعات الذكي طبيعة مشروعك.",
            "business_name": "اسم المشروع",
            "business_type": "نوع النشاط",
            "general_description": "وصف مبسط للمشروع",
            "products_notes": "ماذا تبيع أو تقدم؟",
            "save_project": "حفظ بيانات المشروع",
            "image_groups": "صور المنتجات والكتالوجات",
            "image_group_title": "اسم مجموعة المنتجات",
            "image_group_description": "وصف المجموعة وتعليمات البيع",
            "sales_instructions": "تعليمات مهمة لموظف المبيعات الذكي",
            "upload_images": "رفع الصور أو الكتالوجات",
            "save_image_group": "حفظ وإضافة مجموعة منتجات",
            "saved_image_groups": "مجموعات المنتجات المحفوظة",
            "payment_links": "روابط الدفع الخاصة",
            "product_name": "اسم المنتج",
            "payment_link": "رابط الدفع",
            "amount": "السعر",
            "currency": "العملة",
            "payment_description": "وصف المنتج أو العرض",
            "add_more_payment": "إضافة رابط دفع إضافي",
            "save_payment_links": "حفظ روابط الدفع",
            "saved_payment_links": "روابط الدفع المحفوظة",
            "saved_success": "تم الحفظ بنجاح.",
            "empty": "لا توجد بيانات محفوظة حتى الآن."
        },
        "en": {
            "page_title": "ALSAAB AI - Client Dashboard",
            "back_site": "Back to ALSAAB AI Website",
            "language": "العربية",
            "partner_portal": "Partner Dashboard",
            "client_portal": "Client Dashboard",
            "partner_text": "Partnership, commissions, levels, customers, courses, and upgrade requirements.",
            "client_text": "Your project, package, usage, Smart Sales Employee data, product images, and catalogs.",
            "account_id": "Account ID",
            "current_package": "Current Package",
            "subscription_status": "Subscription Status",
            "customer_replies": "Customer Replies",
            "advisory_replies": "Advisory Replies",
            "channels": "Channels",
            "owner_advisory": "Owner Advisory",
            "owner_advisory_desc": "Open a private advisory conversation with your Smart Sales Employee. The conversation is tied to your Account ID and continues with your long-term business journey.",
            "ask_advisor": "Open Advisory Chat",
            "project_data": "Project Data",
            "project_data_desc": "Add your core project information so the Smart Sales Employee understands your business.",
            "business_name": "Business Name",
            "business_type": "Business Type",
            "general_description": "General Description",
            "products_notes": "What do you sell or provide?",
            "save_project": "Save Project Data",
            "image_groups": "Product & Catalog Images",
            "image_group_title": "Product Group Name",
            "image_group_description": "Group Description & Sales Instructions",
            "sales_instructions": "Important instructions for the Smart Sales Employee",
            "upload_images": "Upload Images or Catalogs",
            "save_image_group": "Save & Add Product Group",
            "saved_image_groups": "Saved Product Groups",
            "payment_links": "Client Payment Links",
            "product_name": "Product Name",
            "payment_link": "Payment Link",
            "amount": "Amount",
            "currency": "Currency",
            "payment_description": "Product or Offer Description",
            "add_more_payment": "Add Another Payment Link",
            "save_payment_links": "Save Payment Links",
            "saved_payment_links": "Saved Payment Links",
            "saved_success": "Saved successfully.",
            "empty": "No saved data yet."
        }
    }[lang]

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN is missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "partner_dashboard_data",
                "partner_id": partner_id
            },
            label="client_dashboard_partner_data"
        )

        if not isinstance(result, dict) or result.get("status") != "success":
            return render_template_string(
                """
                <html>
                <head><meta charset="utf-8"><title>Client Dashboard Error</title></head>
                <body style="font-family:Arial; direction:rtl; padding:30px;">
                  <h2>حدث خطأ في تحميل بيانات العميل</h2>
                  <pre>{{ result }}</pre>
</body>
                </html>
                """,
                result=result
            ), 500

        client_dashboard_result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "client_dashboard_data",
                "partner_id": partner_id
            },
            label="client_dashboard_data_page"
        )

        if not isinstance(client_dashboard_result, dict):
            client_dashboard_result = {}

        profile = result.get("partner_profile") or {}
        level = result.get("level") or {}

        product_groups = client_dashboard_result.get("product_image_groups") or []
        client_payment_links = client_dashboard_result.get("client_payment_links") or []

        account_id = partner_id
        client_id = partner_id

        current_package = (level.get("current_package") or "").lower()
        subscription_status = level.get("subscription_status") or ""

        package = PACKAGES.get(current_package) or {}

        customer_limit = (
            package.get("total_customer_reply_limit")
            or package.get("customer_reply_limit")
            or package.get("monthly_reply_limit")
            or "-"
        )

        advisory_limit = package.get("owner_advisory_reply_limit", 0)
        channels = package.get("channels") or []

        ar_url = build_dashboard_nav_url("/client-dashboard", partner_id, "ar", key)
        en_url = build_dashboard_nav_url("/client-dashboard", partner_id, "en", key)
        language_url = en_url if is_ar else ar_url

        partner_dashboard_url = build_dashboard_nav_url("/partner-dashboard", partner_id, lang, key)
        client_dashboard_url = build_dashboard_nav_url("/client-dashboard", partner_id, lang, key)
        owner_advisory_url = build_dashboard_nav_url("/owner-advisory", partner_id, lang, key)

        saved_message = request.args.get("saved", "").strip()

        html = """
<!DOCTYPE html>
<html lang="{{ lang }}" dir="{{ direction }}">
<head>
  <meta charset="utf-8">
  <title>{{ t.page_title }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      margin: 0;
      background: #0b0b0b;
      color: #f5f0df;
      font-family: Arial, Tahoma, sans-serif;
      direction: {{ direction }};
      text-align: {{ text_align }};
    }

    .page { max-width: 1200px; margin: 0 auto; padding: 28px; }

    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }

    .brand { display: flex; align-items: center; gap: 12px; }

    .logo-mark {
      width: 54px;
      height: 54px;
      border-radius: 16px;
      border: 1px solid #c8a84b;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #d7b85a;
      font-weight: 800;
      background: linear-gradient(135deg, #111, #211c0f);
      font-size: 12px;
    }

    .brand-title { color: #d7b85a; font-size: 19px; font-weight: 800; }
    .brand-note { color: #9f967b; font-size: 12px; margin-top: 3px; }

    .actions { display: flex; gap: 10px; flex-wrap: wrap; }

    .action-btn {
      border: 1px solid rgba(215, 184, 90, 0.5);
      color: #f0cc68;
      background: #111;
      padding: 10px 14px;
      border-radius: 999px;
      text-decoration: none;
      font-size: 14px;
    }

    .portal-switch {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }

    .portal-card {
      background: linear-gradient(135deg, #111, #17130b);
      border: 1px solid rgba(215, 184, 90, 0.45);
      border-radius: 18px;
      padding: 18px;
      color: #f5f0df;
      text-decoration: none;
      display: block;
      position: relative;
    }

    .portal-card.active {
      border-color: #d7b85a;
      background: linear-gradient(135deg, #d7b85a, #9e7c28);
      color: #0b0b0b;
      box-shadow: 0 0 28px rgba(215, 184, 90, 0.28);
    }

    .portal-card.active .portal-card-title,
    .portal-card.active .portal-card-text { color: #0b0b0b; }

    .portal-card.active::after {
      content: "أنت هنا";
      position: absolute;
      top: 12px;
      left: 14px;
      background: #0b0b0b;
      color: #f0cc68;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 700;
    }

    .portal-card-title { color: #d7b85a; font-weight: 800; font-size: 20px; margin-bottom: 8px; }
    .portal-card-text { color: #cfc7ad; line-height: 1.6; font-size: 14px; }

    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 20px;
    }

    .card, .section {
      background: #121212;
      border: 1px solid rgba(215, 184, 90, 0.35);
      border-radius: 16px;
      padding: 18px;
    }

    .section { margin-bottom: 18px; }

    .card h3, .section h2 {
      margin: 0 0 10px;
      color: #d7b85a;
    }

    .big { font-size: 24px; font-weight: 700; color: #fff; }
    .muted { color: #aaa; font-size: 13px; margin-top: 5px; }
    .sub { color: #cfc7ad; line-height: 1.7; }

    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 14px;
    }

    .field { display: flex; flex-direction: column; gap: 7px; }
    .field.full { grid-column: 1 / -1; }

    .field label {
      color: #d7b85a;
      font-size: 14px;
      font-weight: 700;
    }

    input, textarea {
      width: 100%;
      box-sizing: border-box;
      background: #0b0b0b;
      border: 1px solid rgba(215, 184, 90, 0.35);
      color: #fff;
      border-radius: 12px;
      padding: 12px;
      font-family: Arial, Tahoma, sans-serif;
      font-size: 14px;
      outline: none;
    }

    textarea { min-height: 110px; resize: vertical; }

    .primary-btn {
      display: inline-block;
      margin-top: 12px;
      border: 1px solid rgba(215, 184, 90, 0.55);
      background: linear-gradient(135deg, #2a220f, #141414);
      color: #f0cc68;
      padding: 11px 16px;
      border-radius: 999px;
      text-decoration: none;
      font-weight: 700;
      cursor: pointer;
    }

    .status-message {
      background: rgba(128, 226, 138, 0.08);
      border: 1px solid rgba(128, 226, 138, 0.4);
      color: #80e28a;
      border-radius: 14px;
      padding: 13px 16px;
      margin-bottom: 18px;
      font-weight: 700;
    }

    .small-list {
      margin-top: 14px;
      border-top: 1px solid rgba(255,255,255,0.08);
      padding-top: 12px;
    }

    .small-item {
      border: 1px solid rgba(215, 184, 90, 0.20);
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 10px;
      background: rgba(255,255,255,0.02);
    }

    .small-item-title { color: #d7b85a; font-weight: 800; margin-bottom: 6px; }

    .payment-row {
      border: 1px solid rgba(215, 184, 90, 0.22);
      border-radius: 14px;
      padding: 14px;
      margin-bottom: 12px;
      background: rgba(255,255,255,0.02);
    }

    a { color: #f0cc68; text-decoration: none; }

    @media (max-width: 900px) {
      .grid, .portal-switch, .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    @media (max-width: 600px) {
      .grid, .portal-switch, .form-grid { grid-template-columns: 1fr; }
      .page { padding: 16px; }
    }
  </style>
</head>
<body>
  <div class="page">

    <div class="topbar">
      <div class="brand">
        <div class="logo-mark">ALSAAB</div>
        <div>
          <div class="brand-title">ALSAAB AI</div>
          <div class="brand-note">Official account dashboard</div>
        </div>
      </div>

      <div class="actions">
        <a class="action-btn" href="{{ website_url }}">{{ t.back_site }}</a>
        <a class="action-btn" href="{{ language_url }}">{{ t.language }}</a>
      </div>
    </div>

    <div class="portal-switch">
      <a class="portal-card" href="{{ partner_dashboard_url }}">
        <div class="portal-card-title">{{ t.partner_portal }}</div>
        <div class="portal-card-text">{{ t.partner_text }}</div>
      </a>

      <a class="portal-card active" href="{{ client_dashboard_url }}">
        <div class="portal-card-title">{{ t.client_portal }}</div>
        <div class="portal-card-text">{{ t.client_text }}</div>
      </a>
    </div>

    {% if saved_message %}
    <div class="status-message">{{ t.saved_success }}</div>
    {% endif %}

    <div class="grid">
      <div class="card">
        <h3>{{ t.account_id }}</h3>
        <div class="big">{{ account_id }}</div>
        <div class="muted">Partner ID: {{ partner_id }}</div>
      </div>

      <div class="card">
        <h3>{{ t.current_package }}</h3>
        <div class="big">{{ current_package or "-" }}</div>
        <div class="muted">{{ t.subscription_status }}: {{ subscription_status or "-" }}</div>
      </div>

      <div class="card">
        <h3>{{ t.customer_replies }}</h3>
        <div class="big">{{ customer_limit }}</div>
        <div class="muted">Monthly customer reply limit</div>
      </div>

      <div class="card">
        <h3>{{ t.advisory_replies }}</h3>
        <div class="big">{{ advisory_limit }}</div>
        <div class="muted">Monthly owner advisory limit</div>
      </div>
    </div>

    <div class="section">
      <h2>{{ t.channels }}</h2>
      <div class="sub">{{ channels | join(", ") if channels else "-" }}</div>
    </div>

    <div class="section">
      <h2>{{ t.owner_advisory }}</h2>
      <div class="sub">{{ t.owner_advisory_desc }}</div>
      <a class="primary-btn" href="{{ owner_advisory_url }}">{{ t.ask_advisor }}</a>
    </div>

    <div class="section">
      <h2>{{ t.project_data }}</h2>
      <div class="sub">{{ t.project_data_desc }}</div>

      <form method="POST" action="/client-dashboard/save-project-data">
        <input type="hidden" name="key" value="{{ key }}">
        <input type="hidden" name="sso" value="{{ sso_token }}">
        <input type="hidden" name="partner_id" value="{{ partner_id }}">
        <input type="hidden" name="client_id" value="{{ client_id }}">
        <input type="hidden" name="lang" value="{{ lang }}">

        <div class="form-grid">
          <div class="field">
            <label>{{ t.business_name }}</label>
            <input type="text" name="business_name" placeholder="{{ t.business_name }}">
          </div>

          <div class="field">
            <label>{{ t.business_type }}</label>
            <input type="text" name="business_type" placeholder="{{ t.business_type }}">
          </div>

          <div class="field full">
            <label>{{ t.general_description }}</label>
            <textarea name="general_description" placeholder="{{ t.general_description }}"></textarea>
          </div>

          <div class="field full">
            <label>{{ t.products_notes }}</label>
            <textarea name="products" placeholder="{{ t.products_notes }}"></textarea>
          </div>
        </div>

        <button class="primary-btn" type="submit">{{ t.save_project }}</button>
      </form>
    </div>

    <div class="section">
      <h2>{{ t.image_groups }}</h2>

      <form method="POST" action="/client-dashboard/save-image-group" enctype="multipart/form-data">
        <input type="hidden" name="key" value="{{ key }}">
        <input type="hidden" name="sso" value="{{ sso_token }}">
        <input type="hidden" name="partner_id" value="{{ partner_id }}">
        <input type="hidden" name="client_id" value="{{ client_id }}">
        <input type="hidden" name="lang" value="{{ lang }}">

        <div class="form-grid">
          <div class="field">
            <label>{{ t.image_group_title }}</label>
            <input type="text" name="group_title" placeholder="{{ t.image_group_title }}" required>
          </div>

          <div class="field">
            <label>{{ t.upload_images }}</label>
            <input type="file" name="images" multiple accept="image/*,.pdf">
          </div>

          <div class="field full">
            <label>{{ t.image_group_description }}</label>
            <textarea name="group_description" placeholder="{{ t.image_group_description }}" required></textarea>
          </div>

          <div class="field full">
            <label>{{ t.sales_instructions }}</label>
            <textarea name="sales_instructions" placeholder="{{ t.sales_instructions }}"></textarea>
          </div>
        </div>

        <button class="primary-btn" type="submit">{{ t.save_image_group }}</button>
      </form>

      <div class="small-list">
        <h3 style="color:#d7b85a;">{{ t.saved_image_groups }}</h3>
        {% for group in product_groups[:8] %}
          <div class="small-item">
            <div class="small-item-title">{{ group.get("Group Title") or "-" }}</div>
            <div class="muted">{{ group.get("Group Description") or "-" }}</div>
            <div class="muted">Status: {{ group.get("Status") or "-" }}</div>
          </div>
        {% else %}
          <div class="muted">{{ t.empty }}</div>
        {% endfor %}
      </div>
    </div>

    <div class="section">
      <h2>{{ t.payment_links }}</h2>

      <form method="POST" action="/client-dashboard/save-payment-link">
        <input type="hidden" name="key" value="{{ key }}">
        <input type="hidden" name="sso" value="{{ sso_token }}">
        <input type="hidden" name="partner_id" value="{{ partner_id }}">
        <input type="hidden" name="client_id" value="{{ client_id }}">
        <input type="hidden" name="lang" value="{{ lang }}">

        <div id="paymentRows">
          <div class="payment-row">
            <div class="form-grid">
              <div class="field">
                <label>{{ t.product_name }}</label>
                <input type="text" name="product_name" placeholder="{{ t.product_name }}" required>
              </div>

              <div class="field">
                <label>{{ t.payment_link }}</label>
                <input type="url" name="payment_link" placeholder="https://..." required>
              </div>

              <div class="field">
                <label>{{ t.amount }}</label>
                <input type="number" step="0.01" name="amount" placeholder="499">
              </div>

              <div class="field">
                <label>{{ t.currency }}</label>
                <input type="text" name="currency" value="AED">
              </div>

              <div class="field full">
                <label>{{ t.payment_description }}</label>
                <textarea name="description" placeholder="{{ t.payment_description }}"></textarea>
              </div>
            </div>
          </div>
        </div>

        <button class="primary-btn" type="button" onclick="addPaymentRow()">{{ t.add_more_payment }}</button>
        <button class="primary-btn" type="submit">{{ t.save_payment_links }}</button>
      </form>

      <div class="small-list">
        <h3 style="color:#d7b85a;">{{ t.saved_payment_links }}</h3>
        {% for link in client_payment_links[:8] %}
          <div class="small-item">
            <div class="small-item-title">{{ link.get("Product Name") or "-" }}</div>
            <div><a href="{{ link.get("Payment Link") }}" target="_blank">{{ link.get("Payment Link") }}</a></div>
            <div class="muted">{{ link.get("Amount") or "-" }} {{ link.get("Currency") or "" }}</div>
            <div class="muted">{{ link.get("Description") or "-" }}</div>
          </div>
        {% else %}
          <div class="muted">{{ t.empty }}</div>
        {% endfor %}
      </div>
    </div>

  </div>

  <script>
    function addPaymentRow() {
      const container = document.getElementById("paymentRows");
      const first = container.querySelector(".payment-row");
      const clone = first.cloneNode(true);

      clone.querySelectorAll("input, textarea").forEach(function(el) {
        if (el.name === "currency") {
          el.value = "AED";
        } else {
          el.value = "";
        }
      });

      container.appendChild(clone);
    }
  </script>
</body>
</html>
        """


        # ===== ALSAAB_FORCE_WHATSAPP_FORM_IN_CLIENT_PAGES_V3 START =====

        try:

            if isinstance(html, str) and "ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3" not in html:

                html = html.replace("</body>", r"""
        <!-- ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3 START -->
        <div class="section" style="margin-top:18px;">
          <h2>إعداد WhatsApp</h2>
          <div class="muted">
            أرسل طلب ربط موظف المبيعات الذكي على رقم WhatsApp Business الحالي الخاص بمشروعك.
          </div>

          {% if request.args.get("saved") == "whatsapp_setup_saved" %}
          <div style="background:rgba(128,226,138,.08); border:1px solid rgba(128,226,138,.4); color:#80e28a; border-radius:14px; padding:13px 16px; margin:14px 0; font-weight:700;">
            تم إرسال طلب ربط WhatsApp بنجاح.
          </div>
          {% elif request.args.get("saved") == "whatsapp_setup_error" %}
          <div style="background:rgba(255,122,122,.08); border:1px solid rgba(255,122,122,.4); color:#ff7a7a; border-radius:14px; padding:13px 16px; margin:14px 0; font-weight:700;">
            حدث خطأ أثناء حفظ طلب WhatsApp.
          </div>
          {% endif %}

          <form method="POST" action="/client-dashboard/save-whatsapp-setup" style="margin-top:14px;">
            <input type="hidden" name="key" value="{{ request.args.get('key', '') }}">
            <input type="hidden" name="sso" value="{{ request.args.get('sso', '') or request.args.get('token', '') }}">
            <input type="hidden" name="partner_id" value="{{ partner_id if partner_id is defined else request.args.get('partner_id', '') }}">
            <input type="hidden" name="lang" value="{{ request.args.get('lang', 'ar') }}">

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              اسم النشاط / الشركة
            </label>
            <input
              name="business_name"
              placeholder="مثال: Alsaab Projects Management"
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              رقم WhatsApp Business الحالي
            </label>
            <input
              name="whatsapp_number"
              required
              placeholder="+971..."
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              لغة الرد الأساسية
            </label>
            <select
              name="preferred_language"
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >
              <option value="ar">العربية</option>
              <option value="en">English</option>
              <option value="both">Arabic + English</option>
            </select>

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              ملاحظات للربط
            </label>
            <textarea
              name="customer_notes"
              placeholder="مثال: هذا الرقم مستخدم حالياً في WhatsApp Business، ونريد ربط النظام عليه."
              style="width:100%; min-height:90px; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            ></textarea>

            <button
              type="submit"
              style="border:1px solid rgba(215,184,90,.75); color:#0b0b0b; background:linear-gradient(135deg,#d7b85a,#a88425); padding:12px 18px; border-radius:999px; font-weight:900; cursor:pointer;"
            >
              إرسال طلب ربط WhatsApp
            </button>
          </form>

          <div class="muted" style="margin-top:10px;">
            بعد الإرسال، تظهر الحالة عند الإدارة للمراجعة والربط.
          </div>
        </div>
        <!-- ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3 END -->
""" + "\n</body>", 1)

        except Exception as whatsapp_form_error:

            print(f"CLIENT WHATSAPP FORM INJECTION ERROR ❌ {whatsapp_form_error}", flush=True)

        # ===== ALSAAB_FORCE_WHATSAPP_FORM_IN_CLIENT_PAGES_V3 END =====


        return render_template_string(
            html,
            lang=lang,
            direction=direction,
            text_align=text_align,
            t=t,
            website_url=WEBSITE_URL,
            language_url=language_url,
            partner_dashboard_url=partner_dashboard_url,
            client_dashboard_url=client_dashboard_url,
            owner_advisory_url=owner_advisory_url,
            key=key,
            sso_token=sso_token,
            partner_id=partner_id,
            account_id=account_id,
            client_id=client_id,
            current_package=current_package,
            subscription_status=subscription_status,
            customer_limit=customer_limit,
            advisory_limit=advisory_limit,
            channels=channels,
            product_groups=product_groups,
            client_payment_links=client_payment_links,
            saved_message=saved_message
        )

    except Exception as error:
        print(
            f"CLIENT DASHBOARD VIEW ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )


        # ===== ALSAAB_FORCE_WHATSAPP_FORM_IN_CLIENT_PAGES_V3 START =====

        try:

            if isinstance(html, str) and "ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3" not in html:

                html = html.replace("</body>", r"""
        <!-- ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3 START -->
        <div class="section" style="margin-top:18px;">
          <h2>إعداد WhatsApp</h2>
          <div class="muted">
            أرسل طلب ربط موظف المبيعات الذكي على رقم WhatsApp Business الحالي الخاص بمشروعك.
          </div>

          {% if request.args.get("saved") == "whatsapp_setup_saved" %}
          <div style="background:rgba(128,226,138,.08); border:1px solid rgba(128,226,138,.4); color:#80e28a; border-radius:14px; padding:13px 16px; margin:14px 0; font-weight:700;">
            تم إرسال طلب ربط WhatsApp بنجاح.
          </div>
          {% elif request.args.get("saved") == "whatsapp_setup_error" %}
          <div style="background:rgba(255,122,122,.08); border:1px solid rgba(255,122,122,.4); color:#ff7a7a; border-radius:14px; padding:13px 16px; margin:14px 0; font-weight:700;">
            حدث خطأ أثناء حفظ طلب WhatsApp.
          </div>
          {% endif %}

          <form method="POST" action="/client-dashboard/save-whatsapp-setup" style="margin-top:14px;">
            <input type="hidden" name="key" value="{{ request.args.get('key', '') }}">
            <input type="hidden" name="sso" value="{{ request.args.get('sso', '') or request.args.get('token', '') }}">
            <input type="hidden" name="partner_id" value="{{ partner_id if partner_id is defined else request.args.get('partner_id', '') }}">
            <input type="hidden" name="lang" value="{{ request.args.get('lang', 'ar') }}">

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              اسم النشاط / الشركة
            </label>
            <input
              name="business_name"
              placeholder="مثال: Alsaab Projects Management"
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              رقم WhatsApp Business الحالي
            </label>
            <input
              name="whatsapp_number"
              required
              placeholder="+971..."
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              لغة الرد الأساسية
            </label>
            <select
              name="preferred_language"
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >
              <option value="ar">العربية</option>
              <option value="en">English</option>
              <option value="both">Arabic + English</option>
            </select>

            <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">
              ملاحظات للربط
            </label>
            <textarea
              name="customer_notes"
              placeholder="مثال: هذا الرقم مستخدم حالياً في WhatsApp Business، ونريد ربط النظام عليه."
              style="width:100%; min-height:90px; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            ></textarea>

            <button
              type="submit"
              style="border:1px solid rgba(215,184,90,.75); color:#0b0b0b; background:linear-gradient(135deg,#d7b85a,#a88425); padding:12px 18px; border-radius:999px; font-weight:900; cursor:pointer;"
            >
              إرسال طلب ربط WhatsApp
            </button>
          </form>

          <div class="muted" style="margin-top:10px;">
            بعد الإرسال، تظهر الحالة عند الإدارة للمراجعة والربط.
          </div>
        </div>
        <!-- ALSAAB_CLIENT_WHATSAPP_SETUP_FORM_VISIBLE_V3 END -->
""" + "\n</body>", 1)

        except Exception as whatsapp_form_error:

            print(f"CLIENT WHATSAPP FORM INJECTION ERROR ❌ {whatsapp_form_error}", flush=True)

        # ===== ALSAAB_FORCE_WHATSAPP_FORM_IN_CLIENT_PAGES_V3 END =====


        return render_template_string(
            """
            <html>
            <head><meta charset="utf-8"><title>Client Dashboard Error</title></head>
            <body style="font-family:Arial; direction:rtl; padding:30px;">
              <h2>حدث خطأ في عرض Client Dashboard</h2>
              <p>{{ error }}</p>
            </body>
            </html>
            """,
            error=str(error)
        ), 500

# ===== ALSAAB_CLIENT_DASHBOARD_UI_MVP_V1 END =====



# ===== ALSAAB_CLIENT_DASHBOARD_SAVE_ROUTES_V1 START =====

@app.route("/client-dashboard/save-image-group", methods=["POST"])
def client_dashboard_save_image_group():
    import os
    import base64
    from urllib.parse import quote

    key = request.form.get("key", "").strip()
    sso_token = request.form.get("sso", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", request.form.get("lang", "ar"))), 302

    partner_id = (
        request.form.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        return redirect(build_dashboard_login_redirect("client", partner_id, request.form.get("lang", "ar"))), 302
    client_id = request.form.get("client_id", "").strip() or partner_id
    lang = request.form.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    uploaded_files = []

    try:
        for file in request.files.getlist("images"):
            if not file or not file.filename:
                continue

            raw = file.read()

            if not raw:
                continue

            # MVP safety limit per file: 5 MB
            if len(raw) > 5 * 1024 * 1024:
                print(f"CLIENT DASHBOARD UPLOAD SKIPPED large file={file.filename}", flush=True)
                continue

            uploaded_files.append({
                "name": file.filename,
                "mime_type": file.content_type or "application/octet-stream",
                "content_base64": base64.b64encode(raw).decode("ascii")
            })

        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        payload = {
            "token": google_sheet_token,
            "action": "product_image_group",
            "partner_id": partner_id,
            "client_id": client_id,
            "group_title": request.form.get("group_title", "").strip(),
            "group_description": request.form.get("group_description", "").strip(),
            "sales_instructions": request.form.get("sales_instructions", "").strip(),
            "uploaded_files": uploaded_files,
            "notes": "Saved from Client Dashboard with file upload"
        }

        result = post_to_google_sheet_json(payload, label="client_dashboard_save_image_group")
        status = "image_group_saved" if isinstance(result, dict) and result.get("status") == "success" else "image_group_error"

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, status))

    except Exception as error:
        print(f"CLIENT DASHBOARD SAVE IMAGE GROUP ERROR ❌ {error}", flush=True)

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "image_group_error"))


@app.route("/client-dashboard/save-payment-link", methods=["POST"])
def client_dashboard_save_payment_link():
    import os
    from urllib.parse import quote

    key = request.form.get("key", "").strip()
    sso_token = request.form.get("sso", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", request.form.get("lang", "ar"))), 302

    partner_id = (
        request.form.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        return redirect(build_dashboard_login_redirect("client", partner_id, request.form.get("lang", "ar"))), 302
    client_id = request.form.get("client_id", "").strip() or partner_id
    lang = request.form.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        product_names = request.form.getlist("product_name")
        payment_links = request.form.getlist("payment_link")
        amounts = request.form.getlist("amount")
        currencies = request.form.getlist("currency")
        descriptions = request.form.getlist("description")

        max_len = max(len(product_names), len(payment_links), len(amounts), len(currencies), len(descriptions), 1)
        saved_count = 0

        for index in range(max_len):
            product_name = product_names[index].strip() if index < len(product_names) else ""
            payment_link = payment_links[index].strip() if index < len(payment_links) else ""
            amount = amounts[index].strip() if index < len(amounts) else ""
            currency = currencies[index].strip() if index < len(currencies) and currencies[index].strip() else "AED"
            description = descriptions[index].strip() if index < len(descriptions) else ""

            if not product_name and not payment_link:
                continue

            payload = {
                "token": google_sheet_token,
                "action": "client_payment_link",
                "partner_id": partner_id,
                "client_id": client_id,
                "product_name": product_name,
                "payment_link": payment_link,
                "amount": amount,
                "currency": currency,
                "description": description,
                "notes": "Saved from Client Dashboard"
            }

            result = post_to_google_sheet_json(payload, label="client_dashboard_save_payment_link")

            if isinstance(result, dict) and result.get("status") == "success":
                saved_count += 1

        status = "payment_link_saved" if saved_count > 0 else "payment_link_error"

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, status))

    except Exception as error:
        print(f"CLIENT DASHBOARD SAVE PAYMENT LINK ERROR ❌ {error}", flush=True)

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "payment_link_error"))

# ===== ALSAAB_CLIENT_DASHBOARD_SAVE_ROUTES_V1 END =====



# ===== ALSAAB_CLIENT_PROJECT_DATA_AND_ADVISORY_V1 START =====

@app.route("/client-dashboard/save-project-data", methods=["POST"])
@app.route("/client-dashboard/save-project-data", methods=["POST"])
def client_dashboard_save_project_data():
    import os
    from urllib.parse import quote

    key = request.form.get("key", "").strip()
    sso_token = request.form.get("sso", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", request.form.get("lang", "ar"))), 302

    partner_id = (
        request.form.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        return redirect(build_dashboard_login_redirect("client", partner_id, request.form.get("lang", "ar"))), 302
    client_id = request.form.get("client_id", "").strip() or partner_id
    lang = request.form.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        payload = {
            "token": google_sheet_token,
            "action": "client_profile",
            "partner_id": partner_id,
            "client_id": client_id,
            "session_id": client_id,
            "business_name": request.form.get("business_name", "").strip(),
            "business_type": request.form.get("business_type", "").strip(),
            "general_description": request.form.get("general_description", "").strip(),
            "products": request.form.get("products", "").strip(),
            "notes": "Saved from Client Dashboard project data"
        }

        result = post_to_google_sheet_json(payload, label="client_dashboard_save_project_data")
        status = "project_data_saved" if isinstance(result, dict) and result.get("status") == "success" else "project_data_error"

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, status))

    except Exception as error:
        print(f"CLIENT DASHBOARD SAVE PROJECT DATA ERROR ❌ {error}", flush=True)

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "project_data_error"))


@app.route("/owner-advisory", methods=["GET"])
@app.route("/owner-advisory", methods=["GET"])
def owner_advisory_view():
    from urllib.parse import quote

    key = request.args.get("key", "").strip()
    sso_token = request.args.get("sso", "").strip() or request.args.get("token", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("advisory", "", request.args.get("lang", "ar"))), 302

    partner_id = (
        request.args.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        return redirect(build_dashboard_login_redirect("advisory", partner_id, request.args.get("lang", "ar"))), 302
    lang = request.args.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    if not partner_id:
        return "partner_id is required", 400

    direction = "rtl" if lang == "ar" else "ltr"
    title = "استشارات صاحب المشروع" if lang == "ar" else "Owner Advisory"
    subtitle = (
        "هذه محادثة خاصة مرتبطة بمعرف حسابك. استخدمها للاستشارات في المبيعات، التسويق، تطوير العروض، وتحسين أداء مشروعك."
        if lang == "ar"
        else "This private advisory chat is tied to your Account ID. Use it for sales, marketing, offers, objections, and business improvement."
    )

    back_url = f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={quote(lang)}"
    session_id = f"owner_advisory_{partner_id}"

    return render_template_string(
        """
        <!doctype html>
        <html lang="{{ lang }}" dir="{{ direction }}">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>{{ title }}</title>
          <style>
            body { margin:0; background:#0b0b0b; color:#f5f0df; font-family:Arial,Tahoma,sans-serif; direction:{{ direction }}; }
            .page { max-width:900px; margin:0 auto; padding:30px; }
            .card { background:#111; border:1px solid rgba(215,184,90,.4); border-radius:18px; padding:24px; }
            h1 { color:#d7b85a; margin-top:0; }
            .sub { color:#cfc7ad; line-height:1.8; }
            .chat { margin-top:18px; border:1px solid rgba(215,184,90,.25); border-radius:14px; padding:14px; min-height:330px; max-height:520px; overflow:auto; background:#0b0b0b; }
            .msg { margin-bottom:12px; line-height:1.7; }
            .user { color:#f0cc68; }
            .assistant { color:#fff; }
            textarea { width:100%; box-sizing:border-box; margin-top:14px; min-height:90px; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; font-family:Arial,Tahoma,sans-serif; }
            button, a { color:#f0cc68; background:#111; text-decoration:none; display:inline-block; margin-top:12px; border:1px solid rgba(215,184,90,.45); padding:10px 14px; border-radius:999px; cursor:pointer; }
          </style>
        </head>
        <body>
          <div class="page">
            <div class="card">
              <h1>{{ title }}</h1>
              <div class="sub">{{ subtitle }}</div>
              <div class="sub" style="margin-top:8px;">Account ID: {{ partner_id }}</div>

              <div id="chat" class="chat"></div>

              <textarea id="message" placeholder="اكتب سؤالك هنا..."></textarea>
              <br>
              <button onclick="sendMessage()">إرسال</button>
              <a href="{{ back_url }}">العودة إلى Client Dashboard</a>
            </div>
          </div>

          <script>
            const partnerId = {{ partner_id|tojson }};
            const sessionId = {{ session_id|tojson }};
            const chatKey = "alsaab_owner_advisory_" + partnerId;
            const chat = document.getElementById("chat");
            const messageBox = document.getElementById("message");

            let history = [];

            try {
              history = JSON.parse(localStorage.getItem(chatKey) || "[]");
            } catch (e) {
              history = [];
            }

            function renderHistory() {
              chat.innerHTML = "";
              history.forEach(function(item) {
                const div = document.createElement("div");
                div.className = "msg " + item.role;
                div.innerHTML = "<strong>" + (item.role === "user" ? "أنت" : "المستشار") + ":</strong><br>" + item.text.replace(/\\n/g, "<br>");
                chat.appendChild(div);
              });
              chat.scrollTop = chat.scrollHeight;
            }

            function saveHistory() {
              localStorage.setItem(chatKey, JSON.stringify(history));
            }

            async function sendMessage() {
              const text = messageBox.value.trim();

              if (!text) {
                return;
              }

              history.push({role: "user", text: text});
              messageBox.value = "";
              renderHistory();
              saveHistory();

              try {
                const response = await fetch("/chat", {
                  method: "POST",
                  headers: {"Content-Type": "application/json"},
                  body: JSON.stringify({
                    message: text,
                    session_id: sessionId,
                    client_id: partnerId,
                    partner_id: partnerId,
                    source_partner_id: partnerId,
                    channel: "owner_advisory",
                    user_type: "business",
                    intent: "owner_advisory"
                  })
                });

                const data = await response.json();
                const reply = data.reply || data.response || data.answer || data.message || JSON.stringify(data);

                history.push({role: "assistant", text: reply});
                renderHistory();
                saveHistory();

              } catch (error) {
                history.push({role: "assistant", text: "حدث خطأ مؤقت في الاتصال. حاول مرة أخرى."});
                renderHistory();
                saveHistory();
              }
            }

            renderHistory();
          </script>
        </body>
        </html>
        """,
        lang=lang,
        direction=direction,
        title=title,
        subtitle=subtitle,
        partner_id=partner_id,
        session_id=session_id,
        back_url=back_url
    )

# ===== ALSAAB_CLIENT_PROJECT_DATA_AND_ADVISORY_V1 END =====



# ===== ALSAAB_DASHBOARD_SSO_BRIDGE_V1 START =====

def normalize_dashboard_partner_id(value):
    value = str(value or "").strip()

    if not value:
        return ""

    if value.lower() == "alsaab":
        return "alsaab"

    value = value.upper()

    if value.startswith("ALS-P"):
        return value

    return ""


def get_dashboard_sso_secret():
    return os.environ.get("DASHBOARD_SSO_SECRET", "").strip()


def dashboard_b64url_encode(raw_bytes):
    import base64
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")


def dashboard_b64url_decode(value):
    import base64

    value = str(value or "")
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def create_dashboard_sso_token(partner_id, target="client", lang="ar", ttl_seconds=900):
    import json
    import time
    import hmac
    import hashlib

    secret = get_dashboard_sso_secret()

    if not secret:
        raise ValueError("DASHBOARD_SSO_SECRET is missing")

    partner_id = normalize_dashboard_partner_id(partner_id)

    if not partner_id:
        raise ValueError("partner_id is required")

    target = str(target or "client").strip().lower()

    if target not in ("client", "partner", "advisory"):
        target = "client"

    lang = str(lang or "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    payload = {
        "partner_id": partner_id,
        "target": target,
        "lang": lang,
        "exp": int(time.time()) + int(ttl_seconds or 900)
    }

    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_part = dashboard_b64url_encode(payload_json)

    signature = hmac.new(
        secret.encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256
    ).digest()

    signature_part = dashboard_b64url_encode(signature)

    return payload_part + "." + signature_part


def verify_dashboard_sso_token(token):
    import json
    import time
    import hmac
    import hashlib

    secret = get_dashboard_sso_secret()

    if not secret:
        return None, "DASHBOARD_SSO_SECRET is missing"

    token = str(token or "").strip()

    if "." not in token:
        return None, "Invalid token format"

    payload_part, signature_part = token.split(".", 1)

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256
    ).digest()

    expected_signature_part = dashboard_b64url_encode(expected_signature)

    if not hmac.compare_digest(expected_signature_part, signature_part):
        return None, "Invalid token signature"

    try:
        payload = json.loads(dashboard_b64url_decode(payload_part).decode("utf-8"))
    except Exception:
        return None, "Invalid token payload"

    if int(payload.get("exp") or 0) < int(time.time()):
        return None, "Token expired"

    partner_id = normalize_dashboard_partner_id(payload.get("partner_id", ""))

    if not partner_id:
        return None, "Invalid partner_id"

    payload["partner_id"] = partner_id

    target = str(payload.get("target") or "client").strip().lower()

    if target not in ("client", "partner", "advisory"):
        target = "client"

    payload["target"] = target

    lang = str(payload.get("lang") or "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    payload["lang"] = lang

    return payload, ""


def is_dashboard_access_allowed(partner_id, key=""):
    partner_id = normalize_dashboard_partner_id(partner_id)

    # Internal admin bypass only. Do not use key in public/customer links.
    if key and key == ADMIN_KEY:
        return True

    session_partner_id = normalize_dashboard_partner_id(session.get("partner_id", ""))

    if session_partner_id and partner_id and session_partner_id == partner_id:
        return True

    return False


def build_dashboard_nav_url(path, partner_id="", lang="ar", key=""):
    from urllib.parse import urlencode

    params = {
        "lang": lang or "ar"
    }

    current_sso = ""

    try:
        current_sso = (
            request.args.get("sso", "").strip()
            or request.form.get("sso", "").strip()
            or request.args.get("token", "").strip()
        )
    except Exception:
        current_sso = ""

    if current_sso:
        params["sso"] = current_sso
    elif key:
        params["key"] = key

        if partner_id:
            params["partner_id"] = normalize_dashboard_partner_id(partner_id)

    return path + "?" + urlencode(params)


def build_dashboard_login_redirect(target="client", partner_id="", lang="ar"):
    from urllib.parse import urlencode

    params = {
        "target": target or "client",
        "lang": lang or "ar"
    }

    partner_id = normalize_dashboard_partner_id(partner_id)

    if partner_id:
        params["partner_id"] = partner_id

    return "/account-login-placeholder?" + urlencode(params)


@app.route("/dashboard-sso", methods=["GET"])
def dashboard_sso():
    from urllib.parse import quote

    token = request.args.get("token", "").strip()
    payload, error = verify_dashboard_sso_token(token)

    if error:
        return render_template_string(
            """
            <html>
            <head><meta charset="utf-8"><title>Dashboard Login Error</title></head>
            <body style="font-family:Arial; direction:rtl; padding:30px;">
              <h2>تعذر الدخول إلى الداشبورد</h2>
              <p>{{ error }}</p>
            </body>
            </html>
            """,
            error=error
        ), 401

    partner_id = payload.get("partner_id")
    target = payload.get("target") or "client"
    lang = payload.get("lang") or "ar"

    session["partner_id"] = partner_id

    encoded_token = quote(token)

    if target == "partner":
        return redirect(f"/partner-dashboard?lang={lang}&sso={encoded_token}")

    if target == "advisory":
        return redirect(f"/owner-advisory?lang={lang}&sso={encoded_token}")

    return redirect(f"/client-dashboard?lang={lang}&sso={encoded_token}")


@app.route("/admin/create-dashboard-sso-link", methods=["GET"])
def admin_create_dashboard_sso_link():
    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = normalize_dashboard_partner_id(request.args.get("partner_id", ""))
    target = request.args.get("target", "client").strip().lower()
    lang = request.args.get("lang", "ar").strip().lower()

    if target not in ("client", "partner", "advisory"):
        target = "client"

    if lang not in ("ar", "en"):
        lang = "ar"

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    try:
        token = create_dashboard_sso_token(
            partner_id=partner_id,
            target=target,
            lang=lang,
            ttl_seconds=900
        )

        base_url = request.url_root.rstrip("/")
        url = f"{base_url}/dashboard-sso?token={token}"

        return jsonify({
            "status": "success",
            "partner_id": partner_id,
            "target": target,
            "lang": lang,
            "url": url
        })

    except Exception as error:
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500


@app.route("/account-login-placeholder", methods=["GET"])
def account_login_placeholder():
    return render_template_string(
        """
        <html>
        <head><meta charset="utf-8"><title>ALSAAB AI Login</title></head>
        <body style="font-family:Arial; direction:rtl; background:#0b0b0b; color:#f5f0df; padding:30px;">
          <h2 style="color:#d7b85a;">تسجيل الدخول الرسمي سيتم من WordPress</h2>
          <p>هذه الصفحة محمية. للدخول الرسمي، استخدم حسابك في موقع ALSAAB AI.</p>
          <p>لاحقاً سيتم ربط WordPress Login بهذه الصفحة عبر SSO Token.</p>
        </body>
        </html>
        """
    )

# ===== ALSAAB_DASHBOARD_SSO_BRIDGE_V1 END =====



# ===== ALSAAB_DASHBOARD_RETURN_URL_V1 START =====

def build_dashboard_return_url(path, key="", partner_id="", lang="ar", saved=""):
    from urllib.parse import urlencode

    params = {
        "lang": lang or "ar"
    }

    current_sso = ""

    try:
        current_sso = (
            request.form.get("sso", "").strip()
            or request.args.get("sso", "").strip()
            or request.args.get("token", "").strip()
        )
    except Exception:
        current_sso = ""

    if current_sso:
        params["sso"] = current_sso
    elif key:
        params["key"] = key

        if partner_id:
            params["partner_id"] = normalize_dashboard_partner_id(partner_id)

    if saved:
        params["saved"] = saved

    return path + "?" + urlencode(params)

# ===== ALSAAB_DASHBOARD_RETURN_URL_V1 END =====



# ===== ALSAAB_ADMIN_DASHBOARD_MVP_V1 START =====

@app.route("/admin-dashboard-data", methods=["GET"])
def admin_dashboard_data():
    """
    Admin Dashboard Data API.

    Internal MVP security:
    - Requires ADMIN_KEY.
    - Later this can be connected to WordPress admin SSO/session.
    """
    import os

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_dashboard_data"
            },
            label="admin_dashboard_data"
        )

        return jsonify(result)

    except Exception as error:
        print(f"ADMIN DASHBOARD DATA ERROR ❌ {error}", flush=True)

        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500


@app.route("/admin-dashboard", methods=["GET"])
def admin_dashboard_view():
    """
    Admin Dashboard MVP page.

    Internal MVP security:
    - Requires ADMIN_KEY.
    - Do not expose this link publicly.
    """
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN is missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_dashboard_data"
            },
            label="admin_dashboard_page"
        )

        if not isinstance(result, dict) or result.get("status") != "success":
            return render_template_string(
                """
                <html>
                <head><meta charset="utf-8"><title>Admin Dashboard Error</title></head>
                <body style="font-family:Arial; direction:rtl; padding:30px;">
                  <h2>حدث خطأ في تحميل Admin Dashboard</h2>
                  <pre>{{ result }}</pre>
                </body>
                </html>
                """,
                result=result
            ), 500

        partners = result.get("partners") or {}
        subscriptions = result.get("subscriptions") or {}
        commissions = result.get("commissions") or {}
        levels = result.get("levels") or {}
        courses = result.get("courses") or {}

        partner_summary = partners.get("summary") or {}
        subscription_summary = subscriptions.get("summary") or {}
        commission_totals = commissions.get("totals") or {}
        commission_counts = commissions.get("counts") or {}
        course_summary = courses.get("summary") or {}
        level_counts = levels.get("level_counts") or {}
        eligible_counts = levels.get("eligible_counts") or {}

        recent_partners = partners.get("recent") or []
        recent_subscriptions = subscriptions.get("recent") or []
        recent_commissions = commissions.get("recent") or []
        recent_levels = levels.get("recent") or []
        recent_courses = courses.get("recent") or []

        # ===== ALSAAB_ADMIN_DASHBOARD_SEARCH_V1 START =====
        search_query = (
            request.args.get("partner_id", "")
            or request.args.get("search", "")
            or request.args.get("q", "")
        ).strip()

        search_lookup = {}
        search_result = {}

        search_profile = {}
        search_level = {}
        search_customers = {}
        search_commissions = {}
        search_courses = {}
        search_tree = {}

        search_recent_commissions = []
        search_recent_customers = []
        search_purchased_courses = []

        # ===== ALSAAB_ADMIN_PAYOUT_HISTORY_DISPLAY_V1 START =====
        search_payout_history = {}
        search_payout_summary = {}
        search_recent_payouts = []
        # ===== ALSAAB_ADMIN_PAYOUT_HISTORY_DISPLAY_V1 END =====

        search_commission_totals = {}
        search_commission_counts = {}

        # ===== ALSAAB_ADMIN_PARTNER_COMMISSION_SUMMARY_V1 START =====
        search_unpaid_total = 0
        search_payable_now = 0
        search_rejected_hold_total = 0
        search_paid_total = 0
        # ===== ALSAAB_ADMIN_PARTNER_COMMISSION_SUMMARY_V1 END =====

        if search_query:
            search_lookup = post_to_google_sheet_json(
                {
                    "token": google_sheet_token,
                    "action": "admin_partner_lookup",
                    "query": search_query
                },
                label="admin_partner_lookup"
            )

            found_partner_id = ""

            if isinstance(search_lookup, dict) and search_lookup.get("status") == "success":
                found_partner_id = str(search_lookup.get("partner_id") or "").strip()

            if found_partner_id:
                search_result = post_to_google_sheet_json(
                    {
                        "token": google_sheet_token,
                        "action": "partner_dashboard_data",
                        "partner_id": found_partner_id
                    },
                    label="admin_partner_detail"
                )

                if isinstance(search_result, dict) and search_result.get("status") == "success":
                    search_profile = search_result.get("partner_profile") or {}
                    search_level = search_result.get("level") or {}
                    search_customers = search_result.get("customers") or {}
                    search_commissions = search_result.get("commissions") or {}
                    search_courses = search_result.get("courses") or {}
                    search_tree = search_result.get("tree") or {}

                    search_recent_commissions = search_commissions.get("recent") or []
                    search_recent_customers = search_customers.get("recent") or []
                    search_purchased_courses = search_courses.get("purchased_courses") or []

                    search_payout_history = post_to_google_sheet_json(
                        {
                            "token": google_sheet_token,
                            "action": "admin_partner_payout_history",
                            "partner_id": found_partner_id
                        },
                        label="admin_partner_payout_history"
                    )

                    if isinstance(search_payout_history, dict) and search_payout_history.get("status") == "success":
                        search_payout_summary = search_payout_history.get("summary") or {}
                        search_recent_payouts = search_payout_history.get("recent") or []

                    search_commission_totals = search_commissions.get("totals") or {}
                    search_commission_counts = search_commissions.get("counts") or {}

                    try:
                        search_payout_history = post_to_google_sheet_json(
                            {
                                "token": google_sheet_token,
                                "action": "admin_partner_payout_history",
                                "partner_id": found_partner_id
                            },
                            label="admin_partner_payout_history_v3"
                        )

                        if isinstance(search_payout_history, dict) and search_payout_history.get("status") == "success":
                            search_payout_summary = search_payout_history.get("summary") or {}
                            search_recent_payouts = search_payout_history.get("recent") or []
                    except Exception as payout_history_error:
                        search_payout_history = {
                            "status": "error",
                            "message": str(payout_history_error)
                        }
                        search_payout_summary = {}
                        search_recent_payouts = []

                    def _admin_float(value):
                        try:
                            return float(value or 0)
                        except Exception:
                            return 0

                    pending_amount = _admin_float(search_commission_totals.get("pending"))
                    approved_amount = _admin_float(search_commission_totals.get("approved"))
                    paid_amount = _admin_float(search_commission_totals.get("paid"))
                    rejected_amount = _admin_float(search_commission_totals.get("rejected"))
                    hold_amount = _admin_float(search_commission_totals.get("hold"))

                    # غير مدفوع = pending + approved
                    search_unpaid_total = pending_amount + approved_amount

                    # جاهز للدفع الآن = approved فقط
                    # pending يحتاج موافقة أولاً
                    search_payable_now = approved_amount

                    search_paid_total = paid_amount
                    search_rejected_hold_total = rejected_amount + hold_amount
        # ===== ALSAAB_ADMIN_DASHBOARD_SEARCH_V1 END =====

        def money(value):
            try:
                return f"{float(value or 0):,.2f} AED"
            except Exception:
                return f"{value or 0} AED"

        action_status = request.args.get("admin_action", "").strip()

        admin_action_message = ""

        if action_status == "recalculated":
            admin_action_message = "تمت إعادة حساب مستوى الشريك وتسجيل العملية في AuditLogs."
        elif action_status == "recalculate_error":
            admin_action_message = "حدث خطأ أثناء إعادة حساب مستوى الشريك."

        encoded_key = quote(key)

        html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>ALSAAB AI - Admin Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    body {
      margin: 0;
      background: #0b0b0b;
      color: #f5f0df;
      font-family: Arial, Tahoma, sans-serif;
      direction: rtl;
    }

    .page {
      max-width: 1320px;
      margin: 0 auto;
      padding: 28px;
    }

    .topbar {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: center;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .logo {
      width: 56px;
      height: 56px;
      border-radius: 16px;
      border: 1px solid #c8a84b;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #d7b85a;
      font-weight: 900;
      background: linear-gradient(135deg, #111, #211c0f);
      font-size: 12px;
    }

    .brand-title {
      color: #d7b85a;
      font-size: 23px;
      font-weight: 900;
    }

    .brand-sub {
      color: #a99d7b;
      font-size: 13px;
      margin-top: 4px;
    }

    .action-btn {
      border: 1px solid rgba(215, 184, 90, 0.55);
      color: #f0cc68;
      background: #111;
      padding: 10px 14px;
      border-radius: 999px;
      text-decoration: none;
      font-weight: 700;
      display: inline-block;
    }

    .search-panel {
      background: #111;
      border: 1px solid rgba(215, 184, 90, 0.35);
      border-radius: 18px;
      padding: 18px;
      margin-bottom: 18px;
    }

    .search-form {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      margin-top: 12px;
    }

    .search-input {
      width: 100%;
      box-sizing: border-box;
      background: #0b0b0b;
      color: #fff;
      border: 1px solid rgba(215, 184, 90, 0.4);
      border-radius: 14px;
      padding: 13px;
      font-size: 15px;
      outline: none;
    }

    .disabled-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }

    .disabled-actions button {
      border: 1px solid rgba(215, 184, 90, 0.25);
      color: #9f967b;
      background: #0b0b0b;
      padding: 10px 13px;
      border-radius: 999px;
      cursor: not-allowed;
      opacity: 0.75;
    }

    .bulk-panel {
      border: 1px solid rgba(215,184,90,.25);
      background: rgba(255,255,255,.025);
      border-radius: 14px;
      padding: 12px;
      margin-bottom: 12px;
      display: grid;
      grid-template-columns: minmax(150px, 220px) 1fr auto;
      gap: 10px;
      align-items: center;
    }

    .bulk-panel select,
    .bulk-panel input {
      width: 100%;
      box-sizing: border-box;
      background: #0b0b0b;
      color: #fff;
      border: 1px solid rgba(215,184,90,.35);
      border-radius: 12px;
      padding: 10px;
      outline: none;
    }

    .bulk-panel button {
      border: 1px solid rgba(215,184,90,.6);
      color: #f0cc68;
      background: #111;
      border-radius: 999px;
      padding: 10px 14px;
      cursor: pointer;
      font-weight: 700;
    }

    .header {
      background: linear-gradient(135deg, #111, #1d1a10);
      border: 1px solid #c8a84b;
      border-radius: 20px;
      padding: 24px;
      margin-bottom: 20px;
      box-shadow: 0 0 25px rgba(200, 168, 75, 0.12);
    }

    .header h1 {
      margin: 0 0 8px;
      color: #d7b85a;
      font-size: 30px;
    }

    .sub {
      color: #cfc7ad;
      line-height: 1.7;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 20px;
    }

    .card {
      background: #121212;
      border: 1px solid rgba(215, 184, 90, 0.35);
      border-radius: 16px;
      padding: 18px;
      min-height: 104px;
    }

    .card h3 {
      margin: 0 0 10px;
      color: #d7b85a;
      font-size: 16px;
    }

    .big {
      color: #fff;
      font-size: 27px;
      font-weight: 900;
      word-break: break-word;
    }

    .muted {
      color: #aaa;
      font-size: 13px;
      margin-top: 6px;
      line-height: 1.5;
    }

    .section {
      background: #111;
      border: 1px solid rgba(215, 184, 90, 0.25);
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 18px;
    }

    .section h2 {
      margin: 0 0 14px;
      color: #d7b85a;
      font-size: 22px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      overflow: hidden;
      border-radius: 12px;
    }

    th, td {
      padding: 11px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      text-align: right;
      font-size: 13px;
      vertical-align: top;
    }

    th {
      color: #d7b85a;
      background: #181818;
      white-space: nowrap;
    }

    td {
      color: #f5f0df;
    }

    .badge {
      display: inline-block;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid rgba(215, 184, 90, 0.45);
      color: #f0cc68;
      font-size: 12px;
      white-space: nowrap;
    }

    .table-wrap {
      overflow-x: auto;
    }

    .two-col {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }

    .small-box {
      background: #121212;
      border: 1px solid rgba(215, 184, 90, 0.25);
      border-radius: 16px;
      padding: 16px;
    }

    .small-box h3 {
      margin: 0 0 10px;
      color: #d7b85a;
    }

    .kv {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 7px 0;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      color: #f5f0df;
    }

    .kv span:first-child {
      color: #c8a84b;
    }

    @media (max-width: 1000px) {
      .grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .two-col {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 600px) {
      .page {
        padding: 16px;
      }

      .grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>

<body>
  <div class="page">

    <div class="topbar">
      <div class="brand">
        <div class="logo">ALSAAB</div>
        <div>
          <div class="brand-title">ALSAAB AI Admin Dashboard</div>
          <div class="brand-sub">لوحة إدارة داخلية مؤقتة - MVP</div>
        </div>
      </div>

      <div>
        <a class="action-btn" href="/admin-dashboard?key={{ encoded_key }}">تحديث البيانات</a>
      </div>
    </div>

    <div class="header">
      <h1>Admin Dashboard</h1>
      <div class="sub">
        هذه نسخة MVP لعرض بيانات الإدارة من Google Sheets. لاحقاً نضيف أزرار الموافقة على العمولات، الدفع، تعديل الشركاء، وإعادة حساب المستويات.
      </div>
    </div>

    {% if admin_action_message %}
    <div style="background:rgba(128,226,138,.08); border:1px solid rgba(128,226,138,.4); color:#80e28a; border-radius:14px; padding:13px 16px; margin-bottom:18px; font-weight:700;">
      {{ admin_action_message }}
    </div>
    {% endif %}

    <div class="search-panel">
      <h2 style="color:#d7b85a; margin:0;">بحث شريك / عميل</h2>
      <div class="sub">
        ابحث بالـ Partner ID أو الاسم أو الإيميل أو رقم الهاتف. البحث يعرض ملف الشريك التفصيلي من النظام الرسمي.
      </div>

      <form class="search-form" method="GET" action="/admin-dashboard">
        <input type="hidden" name="key" value="{{ admin_key }}">
        <input
          class="search-input"
          name="partner_id"
          value="{{ search_query }}"
          placeholder="مثال: ALS-P00009 أو email أو phone أو name"
        >
        <button class="action-btn" type="submit">بحث</button>
      </form>
    </div>

    {% if search_query %}
    <div class="section">
      <h2>نتيجة البحث</h2>

      {% if search_lookup and search_lookup.get("found") %}
        <div class="grid">
          <div class="card">
            <h3>Partner ID</h3>
            <div class="big">{{ search_profile.get("partner_id") or search_lookup.get("partner_id") or "-" }}</div>
            <div class="muted">{{ search_profile.get("partner_name") or "-" }}</div>
          </div>

          <div class="card">
            <h3>المستوى الحالي</h3>
            <div class="big">{{ search_level.get("current_level") or search_level.get("partner_rank") or "-" }}</div>
            <div class="muted">التالي: {{ search_level.get("next_rank") or "-" }}</div>
          </div>

          <div class="card">
            <h3>العملاء المباشرين النشطين</h3>
            <div class="big">{{ search_customers.get("active_direct_paid_count") or 0 }}</div>
            <div class="muted">إجمالي المباشرين: {{ search_customers.get("all_direct_count") or 0 }}</div>
          </div>

          <div class="card">
            <h3>العمولات المعلقة</h3>
            <div class="big">{{ money(search_commission_totals.get("pending")) }}</div>
            <div class="muted">عددها: {{ search_commission_counts.get("pending") or 0 }}</div>
          </div>
        </div>

        <div class="two-col">
          <div class="small-box">
            <h3>بيانات الشريك</h3>
            <div class="kv"><span>الاسم</span><strong>{{ search_profile.get("partner_name") or "-" }}</strong></div>
            <div class="kv"><span>Status</span><strong>{{ search_profile.get("status") or "-" }}</strong></div>
            <div class="kv"><span>Sponsor</span><strong>{{ search_profile.get("sponsor_partner_id") or "-" }}</strong></div>
            <div class="kv"><span>Referral Link</span><strong style="word-break:break-all;">{{ search_profile.get("referral_link") or "-" }}</strong></div>
            <div class="kv"><span>Downline Count</span><strong>{{ search_tree.get("downline_count") or 0 }}</strong></div>
          </div>

          <div class="small-box">
            <h3>المستوى والترقية</h3>
            <div class="kv"><span>Completed Sales</span><strong>{{ search_level.get("completed_sales") or "-" }}</strong></div>
            <div class="kv"><span>Required Sales</span><strong>{{ search_level.get("required_sales") or "-" }}</strong></div>
            <div class="kv"><span>Current Package</span><strong>{{ search_level.get("current_package") or "-" }}</strong></div>
            <div class="kv"><span>Subscription Status</span><strong>{{ search_level.get("subscription_status") or "-" }}</strong></div>
            <div class="kv"><span>Commission Eligible</span><strong>{{ search_level.get("commission_eligible") or "-" }}</strong></div>
          </div>
        </div>

        <div class="section" style="margin-top:18px;">
          <h2>حالة عمولات هذا الشريك</h2>

          <div class="grid">
            <div class="card">
              <h3>إجمالي العمولات</h3>
              <div class="big">{{ money(search_commission_totals.get("all")) }}</div>
              <div class="muted">عدد العمولات: {{ search_commission_counts.get("all") or 0 }}</div>
            </div>

            <div class="card">
              <h3>Pending</h3>
              <div class="big">{{ money(search_commission_totals.get("pending")) }}</div>
              <div class="muted">تحتاج مراجعة / موافقة: {{ search_commission_counts.get("pending") or 0 }}</div>
            </div>

            <div class="card">
              <h3>Approved</h3>
              <div class="big">{{ money(search_commission_totals.get("approved")) }}</div>
              <div class="muted">جاهزة للدفع: {{ search_commission_counts.get("approved") or 0 }}</div>
            </div>

            <div class="card">
              <h3>Paid</h3>
              <div class="big">{{ money(search_paid_total) }}</div>
              <div class="muted">اندفعت للشريك: {{ search_commission_counts.get("paid") or 0 }}</div>
            </div>

            <div class="card">
              <h3>غير مدفوع</h3>
              <div class="big">{{ money(search_unpaid_total) }}</div>
              <div class="muted">Pending + Approved</div>
            </div>

            <div class="card">
              <h3>المستحق للدفع الآن</h3>
              <div class="big">{{ money(search_payable_now) }}</div>
              <div class="muted">Approved فقط</div>
            </div>

            <div class="card">
              <h3>Rejected / Hold</h3>
              <div class="big">{{ money(search_rejected_hold_total) }}</div>
              <div class="muted">
                Rejected: {{ search_commission_counts.get("rejected") or 0 }}
                /
                Hold: {{ search_commission_counts.get("hold") or 0 }}
              </div>
            </div>

            <div class="card">
              <h3>حالة الدفع</h3>
              <div class="big">
                {% if search_payable_now and search_payable_now > 0 %}
                  يحتاج دفع
                {% elif search_unpaid_total and search_unpaid_total > 0 %}
                  يحتاج موافقة
                {% else %}
                  لا يوجد مستحق
                {% endif %}
              </div>
              <div class="muted">ملخص سريع لحالة عمولات الشريك</div>
            </div>
          </div>
        </div>

        
        <!-- ALSAAB_PARTNER_STATUS_ACTION_PANEL_V2 START -->
        <div class="small-box" style="margin-top:14px;">
          <h3>إدارة حالة الشريك</h3>
          <div class="muted">
            هذه الأزرار خاصة بالأدمن فقط. تعليق الشريك يوقف أهليته مؤقتاً، والتفعيل يرجعه active مع إعادة حساب مستواه.
          </div>

          <div class="disabled-actions" style="margin-top:14px;">
            <form method="POST" action="/admin/update-partner-status" style="display:inline-block;">
              <input type="hidden" name="key" value="{{ admin_key }}">
              <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">
              <input type="hidden" name="new_status" value="suspended">
              <input type="hidden" name="reason" value="Manual suspend from Admin Dashboard">
              <button type="submit" onclick="return confirm('تأكيد تعليق هذا الشريك؟')" style="border:1px solid rgba(255,122,122,.6); color:#ff7a7a; background:#111; padding:10px 13px; border-radius:999px; cursor:pointer;">
                Suspend Partner
              </button>
            </form>

            <form method="POST" action="/admin/update-partner-status" style="display:inline-block;">
              <input type="hidden" name="key" value="{{ admin_key }}">
              <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">
              <input type="hidden" name="new_status" value="active">
              <input type="hidden" name="reason" value="Manual activate from Admin Dashboard">
              <button type="submit" onclick="return confirm('تأكيد تفعيل هذا الشريك؟')" style="border:1px solid rgba(128,226,138,.6); color:#80e28a; background:#111; padding:10px 13px; border-radius:999px; cursor:pointer;">
                Activate Partner
              </button>
            </form>
          </div>
        </div>
        <!-- ALSAAB_PARTNER_STATUS_ACTION_PANEL_V2 END -->


        <!-- ALSAAB_AUTO_APPROVE_PENDING_BUTTON_V1 START -->
        <div class="section" style="margin-top:18px;">
          <h2>اعتماد العمولات القديمة تلقائياً</h2>
          <div class="muted">
            النظام الجديد يعتمد العمولات الصحيحة تلقائياً. هذا الزر فقط لتحويل العمولات القديمة pending لهذا الشريك إلى approved.
          </div>

          <form method="POST" action="/admin/auto-approve-pending-commissions" style="margin-top:14px;">
            <input type="hidden" name="key" value="{{ admin_key }}">
            <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">
            <input type="hidden" name="reason" value="Convert old pending commissions to approved for this partner">

            <button
              type="submit"
              onclick="return confirm('تأكيد تحويل العمولات القديمة pending لهذا الشريك إلى approved؟')"
              style="border:1px solid rgba(128,226,138,.6); color:#80e28a; background:#111; padding:12px 16px; border-radius:999px; font-weight:900; cursor:pointer;"
            >
              Auto Approve Old Pending
            </button>
          </form>
        </div>
        

        
        


        <!-- ALSAAB_PAYOUT_HISTORY_SINGLE_SECTION_V4 START -->
        <div class="section" style="margin-top:18px;">
          <h2>سجل دفعات هذا الشريك</h2>

          <div class="grid">
            <div class="card">
              <h3>إجمالي المدفوع</h3>
              <div class="big">{{ money(search_payout_summary.get("total_paid")) }}</div>
              <div class="muted">كل الدفعات المسجلة في PayoutHistory</div>
            </div>

            <div class="card">
              <h3>عدد الدفعات</h3>
              <div class="big">{{ search_payout_summary.get("payout_count") or 0 }}</div>
              <div class="muted">عدد مرات الدفع للشريك</div>
            </div>

            <div class="card">
              <h3>عمولات مدفوعة</h3>
              <div class="big">{{ search_payout_summary.get("total_commissions_paid") or 0 }}</div>
              <div class="muted">عدد العمولات المدفوعة ضمن الدفعات</div>
            </div>

            <div class="card">
              <h3>آخر دفعة</h3>
              <div class="big" style="font-size:18px;">{{ search_payout_summary.get("last_paid_date") or "-" }}</div>
              <div class="muted">آخر تاريخ دفع مسجل</div>
            </div>
          </div>

          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Payout ID</th>
                  <th>Amount</th>
                  <th>Commission Count</th>
                  <th>Method</th>
                  <th>Status</th>
                  <th>Paid Date</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {% for payout in search_recent_payouts[:10] %}
                <tr>
                  <td>{{ payout.payout_id or "-" }}</td>
                  <td>{{ money(payout.total_amount) }}</td>
                  <td>{{ payout.commission_count or 0 }}</td>
                  <td>{{ payout.payment_method or "-" }}</td>
                  <td><span class="badge">{{ payout.status or "-" }}</span></td>
                  <td>{{ payout.paid_date or "-" }}</td>
                  <td>{{ payout.reason or "-" }}</td>
                </tr>
                {% else %}
                <tr><td colspan="7">لا توجد دفعات مسجلة لهذا الشريك بعد.</td></tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        </div>
        <!-- ALSAAB_PAYOUT_HISTORY_SINGLE_SECTION_V4 END -->

<!-- ALSAAB_MARK_PARTNER_PAID_BUTTON_V1 START -->
        <div class="section" style="margin-top:18px;">
          <h2>تسجيل دفع عمولة الشريك</h2>
          <div class="muted">
            بعد ما تحول المبلغ يدوياً للشريك، اضغط هذا الزر. النظام سيحول كل العمولات approved لهذا الشريك إلى paid ويحفظ العملية في PayoutHistory و AuditLogs.
          </div>

          <form method="POST" action="/admin/mark-partner-paid" style="margin-top:14px;">
            <input type="hidden" name="key" value="{{ admin_key }}">
            <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">
            <input
              name="reason"
              required
              value="Manual transfer completed by owner"
              style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
            >

            <button
              type="submit"
              onclick="return confirm('تأكيد: هل حولت المبلغ يدوياً للشريك وتريد تحويل كل approved إلى paid؟')"
              style="border:1px solid rgba(128,226,138,.6); color:#80e28a; background:#111; padding:12px 16px; border-radius:999px; font-weight:900; cursor:pointer;"
            >
              تم الدفع للشريك
            </button>
          </form>

          <div class="muted" style="margin-top:10px;">
            المستحق للدفع الآن: {{ money(search_payable_now) }}
          </div>
        </div>
        <!-- ALSAAB_MARK_PARTNER_PAID_BUTTON_V1 END -->

<div class="small-box">
          <h3>إجراءات إدارية لاحقة</h3>
          <div class="muted">
            هذه الأزرار مكانها هنا، لكنها غير مفعلة الآن حتى نبني الـ audit log والصلاحيات.
          </div>
          <div class="disabled-actions">
            
            <form method="POST" action="/admin/recalculate-partner-level" style="display:inline-block;">
              <input type="hidden" name="key" value="{{ admin_key }}">
              <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">
              <input type="hidden" name="reason" value="Manual recalculate from Admin Dashboard search result">
              <button type="submit" style="border:1px solid rgba(215,184,90,.55); color:#f0cc68; background:#111; padding:10px 13px; border-radius:999px; cursor:pointer;">
                Recalculate Level
              </button>
            </form>
            <button disabled>Suspend Partner</button>
            <button disabled>Activate Partner</button>
            
            <a
              href="/admin/downline-transfer-preview?key={{ admin_key }}&partner_id={{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}"
              style="border:1px solid rgba(255,207,102,.6); color:#ffcf66; background:#111; padding:10px 13px; border-radius:999px; text-decoration:none; display:inline-block;"
            >
              Preview Transfer Downline to alsaab
            </a>
            <button disabled>Approve Commissions</button>
            <button disabled>Mark Commissions Paid</button>
          </div>
        </div>

        <div class="section" style="margin-top:18px;">
          <h2>آخر عمولات هذا الشريك</h2>

          <form id="bulkCommissionForm" class="bulk-panel" method="POST" action="/admin/bulk-update-commission-status">
            <input type="hidden" name="key" value="{{ admin_key }}">
            <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">

            <select name="new_status" required>
              <option value="">Bulk Action</option>
              <option value="approved">Approve Selected</option>
              <option value="hold">Hold Selected</option>
              <option value="rejected">Reject Selected</option>
              <option value="paid">Mark Selected as Paid</option>
            </select>

            <input name="reason" placeholder="سبب الإجراء / ملاحظة الإدارة" required>

            <button type="submit" onclick="return confirm('تأكيد تنفيذ الإجراء الجماعي على العمولات المحددة؟')">
              تنفيذ
            </button>
          </form>

          <div class="muted" style="margin-bottom:10px;">
            ملاحظة: Mark as Paid في الإجراء الجماعي يطبق فقط على العمولات approved، ويتجاهل العمولات pending لحماية الدفع.
          </div>

          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th><input type="checkbox" onclick="toggleCommissionSelection(this)"></th>
                  <th>Source</th>
                  <th>Depth</th>
                  <th>Package</th>
                  <th>%</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {% for c in search_recent_commissions[:10] %}
                <tr>
                  <td>
                    <input
                      type="checkbox"
                      name="commission_ids"
                      form="bulkCommissionForm"
                      value="{{ c.commission_id }}"
                    >
                  </td>
                  <td>{{ c.source_partner_id or "-" }}</td>
                  <td>{{ c.commission_depth or "-" }}</td>
                  <td>{{ c.package or "-" }}</td>
                  <td>{{ c.commission_percent or "-" }}</td>
                  <td>{{ money(c.commission_amount) }}</td>
                  <td><span class="badge">{{ c.status or "-" }}</span></td>
                  <td>
                    <div style="display:flex; gap:6px; flex-wrap:wrap;">
                      <form method="POST" action="/admin/update-commission-status">
                        <input type="hidden" name="key" value="{{ admin_key }}">
                        <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">
                        <input type="hidden" name="commission_id" value="{{ c.commission_id }}">
                        <input type="hidden" name="new_status" value="approved">
                        <input type="hidden" name="reason" value="Approved from Admin Dashboard">
                        <button type="submit" style="border:1px solid rgba(128,226,138,.6); color:#80e28a; background:#111; border-radius:999px; padding:6px 9px; cursor:pointer;">Approve</button>
                      </form>

                      <form method="POST" action="/admin/update-commission-status">
                        <input type="hidden" name="key" value="{{ admin_key }}">
                        <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">
                        <input type="hidden" name="commission_id" value="{{ c.commission_id }}">
                        <input type="hidden" name="new_status" value="hold">
                        <input type="hidden" name="reason" value="Hold from Admin Dashboard">
                        <button type="submit" style="border:1px solid rgba(255,207,102,.6); color:#ffcf66; background:#111; border-radius:999px; padding:6px 9px; cursor:pointer;">Hold</button>
                      </form>

                      <form method="POST" action="/admin/update-commission-status">
                        <input type="hidden" name="key" value="{{ admin_key }}">
                        <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">
                        <input type="hidden" name="commission_id" value="{{ c.commission_id }}">
                        <input type="hidden" name="new_status" value="rejected">
                        <input type="hidden" name="reason" value="Rejected from Admin Dashboard">
                        <button type="submit" style="border:1px solid rgba(255,122,122,.6); color:#ff7a7a; background:#111; border-radius:999px; padding:6px 9px; cursor:pointer;">Reject</button>
                      </form>

                      <form method="POST" action="/admin/update-commission-status">
                        <input type="hidden" name="key" value="{{ admin_key }}">
                        <input type="hidden" name="partner_id" value="{{ search_profile.get("partner_id") or search_lookup.get("partner_id") }}">
                        <input type="hidden" name="commission_id" value="{{ c.commission_id }}">
                        <input type="hidden" name="new_status" value="paid">
                        <input type="hidden" name="reason" value="Marked paid from Admin Dashboard">
                        <button type="submit" style="border:1px solid rgba(215,184,90,.65); color:#f0cc68; background:#111; border-radius:999px; padding:6px 9px; cursor:pointer;">Mark Paid</button>
                      </form>
                    </div>
                  </td>
                </tr>
                {% else %}
                <tr><td colspan="8">لا توجد عمولات لهذا الشريك.</td></tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        </div>

        <div class="section">
          <h2>العملاء المباشرين لهذا الشريك</h2>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Client ID</th>
                  <th>Plan</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {% for customer in search_recent_customers[:10] %}
                <tr>
                  <td>{{ customer.client_id or customer.session_id or "-" }}</td>
                  <td>{{ customer.plan_name or "-" }}</td>
                  <td>{{ money(customer.package_amount) }}</td>
                  <td><span class="badge">{{ customer.subscription_status or "-" }}</span></td>
                  <td>{{ customer.date or "-" }}</td>
                </tr>
                {% else %}
                <tr><td colspan="5">لا توجد بيانات عملاء مباشرين.</td></tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        </div>

      {% else %}
        <div class="muted">
          لم يتم العثور على شريك مطابق للبحث: {{ search_query }}
        </div>

        {% if search_lookup and search_lookup.get("matches") %}
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Partner ID</th>
                <th>Name</th>
                <th>Email</th>
                <th>Phone</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {% for m in search_lookup.get("matches") %}
              <tr>
                <td>{{ m.partner_id or "-" }}</td>
                <td>{{ m.partner_name or "-" }}</td>
                <td>{{ m.email or "-" }}</td>
                <td>{{ m.phone or "-" }}</td>
                <td>{{ m.status or "-" }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        {% endif %}
      {% endif %}
    </div>
    {% endif %}

    <div class="grid">
      <div class="card">
        <h3>إجمالي الشركاء</h3>
        <div class="big">{{ partner_summary.total or 0 }}</div>
        <div class="muted">Active: {{ partner_summary.active or 0 }} / Suspended: {{ partner_summary.suspended or 0 }}</div>
      </div>

      <div class="card">
        <h3>الاشتراكات النشطة</h3>
        <div class="big">{{ subscription_summary.active or 0 }}</div>
        <div class="muted">Total: {{ subscription_summary.total or 0 }} / Failed: {{ subscription_summary.payment_failed or 0 }}</div>
      </div>

      <div class="card">
        <h3>العمولات المعلقة</h3>
        <div class="big">{{ money(commission_totals.pending) }}</div>
        <div class="muted">Count: {{ commission_counts.pending or 0 }}</div>
      </div>

      <div class="card">
        <h3>إجمالي العمولات</h3>
        <div class="big">{{ money(commission_totals.all) }}</div>
        <div class="muted">All count: {{ commission_counts.all or 0 }}</div>
      </div>

      <div class="card">
        <h3>إجمالي الاشتراكات</h3>
        <div class="big">{{ money(subscription_summary.total_amount) }}</div>
        <div class="muted">حسب بيانات Subscriptions</div>
      </div>

      <div class="card">
        <h3>الكورسات المدفوعة</h3>
        <div class="big">{{ course_summary.paid or 0 }}</div>
        <div class="muted">Total courses: {{ course_summary.total or 0 }}</div>
      </div>

      <div class="card">
        <h3>Commission Eligible</h3>
        <div class="big">{{ eligible_counts.yes or 0 }}</div>
        <div class="muted">Not eligible: {{ eligible_counts.no or 0 }}</div>
      </div>

      <div class="card">
        <h3>Payment Failed</h3>
        <div class="big">{{ subscription_summary.payment_failed or 0 }}</div>
        <div class="muted">Cancelled: {{ subscription_summary.cancelled or 0 }}</div>
      </div>
    </div>

    <div class="two-col">
      <div class="small-box">
        <h3>توزيع المستويات</h3>
        {% for level, count in level_counts.items() %}
        <div class="kv"><span>{{ level }}</span><strong>{{ count }}</strong></div>
        {% else %}
        <div class="muted">لا توجد بيانات مستويات.</div>
        {% endfor %}
      </div>

      <div class="small-box">
        <h3>Plan Counts</h3>
        {% for plan, count in (subscriptions.plan_counts or {}).items() %}
        <div class="kv"><span>{{ plan }}</span><strong>{{ count }}</strong></div>
        {% else %}
        <div class="muted">لا توجد بيانات باقات.</div>
        {% endfor %}
      </div>
    </div>

    <div class="section">
      <h2>آخر الشركاء</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Partner ID</th>
              <th>الاسم</th>
              <th>Sponsor</th>
              <th>Rank</th>
              <th>Status</th>
              <th>Email</th>
              <th>Referral Link</th>
            </tr>
          </thead>
          <tbody>
            {% for p in recent_partners %}
            <tr>
              <td>{{ p.partner_id or "-" }}</td>
              <td>{{ p.partner_name or "-" }}</td>
              <td>{{ p.sponsor_partner_id or "-" }}</td>
              <td>{{ p.partner_rank or "-" }}</td>
              <td><span class="badge">{{ p.status or "-" }}</span></td>
              <td>{{ p.email or "-" }}</td>
              <td>{{ p.referral_link or "-" }}</td>
            </tr>
            {% else %}
            <tr><td colspan="7">لا توجد بيانات.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <h2>آخر الاشتراكات</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Client ID</th>
              <th>Session ID</th>
              <th>Source Partner</th>
              <th>Plan</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Stripe Sub</th>
            </tr>
          </thead>
          <tbody>
            {% for s in recent_subscriptions %}
            <tr>
              <td>{{ s.client_id or "-" }}</td>
              <td>{{ s.session_id or "-" }}</td>
              <td>{{ s.source_partner_id or "-" }}</td>
              <td>{{ s.plan_name or "-" }}</td>
              <td>{{ money(s.package_amount) }}</td>
              <td><span class="badge">{{ s.subscription_status or "-" }}</span></td>
              <td>{{ s.stripe_subscription_id or "-" }}</td>
            </tr>
            {% else %}
            <tr><td colspan="7">لا توجد بيانات.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <h2>آخر العمولات</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Beneficiary</th>
              <th>Source</th>
              <th>Depth</th>
              <th>Rank</th>
              <th>Package</th>
              <th>%</th>
              <th>Amount</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {% for c in recent_commissions %}
            <tr>
              <td>{{ c.beneficiary_partner_id or "-" }}</td>
              <td>{{ c.source_partner_id or "-" }}</td>
              <td>{{ c.commission_depth or "-" }}</td>
              <td>{{ c.partner_rank or "-" }}</td>
              <td>{{ c.package or "-" }}</td>
              <td>{{ c.commission_percent or "-" }}</td>
              <td>{{ money(c.commission_amount) }}</td>
              <td><span class="badge">{{ c.status or "-" }}</span></td>
            </tr>
            {% else %}
            <tr><td colspan="8">لا توجد بيانات.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <h2>تقدم المستويات</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Partner ID</th>
              <th>Rank</th>
              <th>Completed</th>
              <th>Required</th>
              <th>Next</th>
              <th>Package</th>
              <th>Sub Status</th>
              <th>Eligible</th>
              <th>Missing</th>
            </tr>
          </thead>
          <tbody>
            {% for l in recent_levels %}
            <tr>
              <td>{{ l.partner_id or "-" }}</td>
              <td>{{ l.partner_rank or "-" }}</td>
              <td>{{ l.completed_sales or "-" }}</td>
              <td>{{ l.required_sales or "-" }}</td>
              <td>{{ l.next_rank or "-" }}</td>
              <td>{{ l.current_package or "-" }}</td>
              <td>{{ l.subscription_status or "-" }}</td>
              <td><span class="badge">{{ l.commission_eligible or "-" }}</span></td>
              <td>{{ l.missing_requirements or "-" }}</td>
            </tr>
            {% else %}
            <tr><td colspan="9">لا توجد بيانات.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <h2>آخر مشتريات الكورسات</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Partner ID</th>
              <th>Course Code</th>
              <th>Course Name</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Stripe Payment</th>
              <th>Paid At</th>
            </tr>
          </thead>
          <tbody>
            {% for course in recent_courses %}
            <tr>
              <td>{{ course.partner_id or "-" }}</td>
              <td>{{ course.course_code or "-" }}</td>
              <td>{{ course.course_name or "-" }}</td>
              <td>{{ money(course.amount) }}</td>
              <td><span class="badge">{{ course.status or "-" }}</span></td>
              <td>{{ course.stripe_payment_id or "-" }}</td>
              <td>{{ course.paid_at or "-" }}</td>
            </tr>
            {% else %}
            <tr><td colspan="7">لا توجد بيانات.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

  </div>
</body>
</html>
        """

        return render_template_string(
            html,
            encoded_key=encoded_key,
            admin_key=key,
            admin_action_message=admin_action_message,
            search_query=search_query,
            search_lookup=search_lookup,
            search_result=search_result,
            search_profile=search_profile,
            search_level=search_level,
            search_customers=search_customers,
            search_commissions=search_commissions,
            search_courses=search_courses,
            search_tree=search_tree,
            search_recent_commissions=search_recent_commissions,
            search_recent_customers=search_recent_customers,
            search_purchased_courses=search_purchased_courses,
            search_payout_history=search_payout_history,
            search_payout_summary=search_payout_summary,
            search_recent_payouts=search_recent_payouts,
            search_commission_totals=search_commission_totals,
            search_commission_counts=search_commission_counts,
            search_unpaid_total=search_unpaid_total,
            search_payable_now=search_payable_now,
            search_rejected_hold_total=search_rejected_hold_total,
            search_paid_total=search_paid_total,
            partner_summary=partner_summary,
            subscription_summary=subscription_summary,
            commission_totals=commission_totals,
            commission_counts=commission_counts,
            course_summary=course_summary,
            level_counts=level_counts,
            eligible_counts=eligible_counts,
            partners=partners,
            subscriptions=subscriptions,
            recent_partners=recent_partners,
            recent_subscriptions=recent_subscriptions,
            recent_commissions=recent_commissions,
            recent_levels=recent_levels,
            recent_courses=recent_courses,
            money=money
        )

    except Exception as error:
        print(f"ADMIN DASHBOARD VIEW ERROR ❌ {error}", flush=True)

        return render_template_string(
            """
            <html>
            <head><meta charset="utf-8"><title>Admin Dashboard Error</title></head>
            <body style="font-family:Arial; direction:rtl; padding:30px;">
              <h2>حدث خطأ في عرض Admin Dashboard</h2>
              <p>{{ error }}</p>
            
  <!-- ALSAAB_ADMIN_UI_SIMPLIFY_V1 START -->
  <script>
    (function simplifyAdminDashboard() {
      function cleanText(value) {
        return (value || "").replace(/\s+/g, " ").trim();
      }

      function hideElement(el) {
        if (!el) return;
        el.style.display = "none";
      }

      function hideClosestFormOrButton(el) {
        var form = el.closest("form");
        if (form) {
          hideElement(form);
          return;
        }
        hideElement(el);
      }

      // Hide daily approval buttons. Valid commissions are approved automatically now.
      document.querySelectorAll("button, a").forEach(function(el) {
        var text = cleanText(el.textContent);

        if (text === "Approve") {
          hideClosestFormOrButton(el);
        }

        if (text === "Mark Paid") {
          hideClosestFormOrButton(el);
        }

        if (text.indexOf("Auto Approve Old Pending") !== -1) {
          var sec = el.closest(".section");
          hideElement(sec || el);
        }

        if (text.indexOf("Create Payout Batch") !== -1) {
          var sec = el.closest(".section");
          hideElement(sec || el);
        }
      });

      // Hide old sections if they still exist.
      document.querySelectorAll(".section").forEach(function(sec) {
        var text = cleanText(sec.textContent);

        if (text.indexOf("اعتماد العمولات القديمة تلقائياً") !== -1) {
          hideElement(sec);
        }

        if (text.indexOf("Payout Workflow MVP") !== -1) {
          hideElement(sec);
        }
      });

      // Remove unnecessary bulk options. Owner uses "تم الدفع للشريك" for payout.
      document.querySelectorAll("select option").forEach(function(option) {
        var value = cleanText(option.value).toLowerCase();
        var text = cleanText(option.textContent).toLowerCase();

        if (value === "approved" || value === "paid") {
          option.remove();
        }

        if (text.indexOf("approve selected") !== -1 || text.indexOf("mark selected as paid") !== -1) {
          option.remove();
        }
      });
    })();
  </script>
  <!-- ALSAAB_ADMIN_UI_SIMPLIFY_V1 END -->

</body>
            </html>
            """,
            error=str(error)
        ), 500

# ===== ALSAAB_ADMIN_DASHBOARD_MVP_V1 END =====



# ===== ALSAAB_ADMIN_RECALCULATE_LEVEL_V1 START =====

@app.route("/admin/recalculate-partner-level", methods=["POST"])
def admin_recalculate_partner_level():
    """
    Owner/Admin action:
    Recalculate partner level and sync result to Google Sheets.

    Security:
    - Requires ADMIN_KEY.
    - This is an owner-level admin action.
    - Every action is logged in AuditLogs.
    """
    import os
    import json
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Manual admin recalculate from Admin Dashboard"
    )

    partner_id = str(partner_id or "").strip().upper()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    try:
        from database import (
            normalize_partner_id,
            sync_partner_level_progress_to_google_sheet,
            post_to_google_sheet_json,
        )

        partner_id = normalize_partner_id(partner_id)

        result = sync_partner_level_progress_to_google_sheet(partner_id)

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        audit_result = {}

        if google_sheet_token:
            audit_result = post_to_google_sheet_json(
                {
                    "token": google_sheet_token,
                    "action": "admin_audit_log",
                    "actor": "owner_admin",
                    "action_type": "recalculate_partner_level",
                    "target_type": "partner",
                    "target_id": partner_id,
                    "partner_id": partner_id,
                    "before_json": "",
                    "after_json": json.dumps(result, ensure_ascii=False),
                    "reason": reason,
                    "source": "admin_dashboard",
                    "status": result.get("status", "success") if isinstance(result, dict) else "success",
                    "notes": "Admin manual level recalculation"
                },
                label="admin_audit_log_recalculate_level"
            )

        print(
            f"ADMIN RECALCULATE LEVEL ✅ partner_id={partner_id} result={result} audit={audit_result}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "success",
                "partner_id": partner_id,
                "result": result,
                "audit_result": audit_result
            })

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=recalculated"
        )

    except Exception as error:
        print(
            f"ADMIN RECALCULATE LEVEL ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "partner_id": partner_id,
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=recalculate_error"
        )

# ===== ALSAAB_ADMIN_RECALCULATE_LEVEL_V1 END =====



# ===== ALSAAB_ADMIN_COMMISSION_ACTIONS_RENDER_V1 START =====

@app.route("/admin/update-commission-status", methods=["POST"])
def admin_update_commission_status():
    """
    Owner/Admin action:
    Update commission status: approved / hold / rejected / paid.

    Security:
    - Requires ADMIN_KEY.
    - Every change is logged in Apps Script AuditLogs.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    commission_id = (
        get_payload_value(payload, "commission_id", default="")
        or request.form.get("commission_id", "").strip()
    )

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    new_status = (
        get_payload_value(payload, "new_status", default="")
        or request.form.get("new_status", "").strip()
    ).lower().strip()

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Admin commission status update"
    )

    if new_status not in ("approved", "hold", "rejected", "paid", "pending"):
        return jsonify({
            "status": "error",
            "message": "Invalid new_status"
        }), 400

    if not commission_id:
        return jsonify({
            "status": "error",
            "message": "commission_id is required"
        }), 400

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_update_commission_status",
                "commission_id": commission_id,
                "partner_id": partner_id,
                "new_status": new_status,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard"
            },
            label="admin_update_commission_status"
        )

        print(
            f"ADMIN UPDATE COMMISSION STATUS ✅ commission_id={commission_id} new_status={new_status} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=commission_{quote(new_status)}"
        )

    except Exception as error:
        print(
            f"ADMIN UPDATE COMMISSION STATUS ERROR ❌ commission_id={commission_id} status={new_status} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=commission_error"
        )

# ===== ALSAAB_ADMIN_COMMISSION_ACTIONS_RENDER_V1 END =====



# ===== ALSAAB_ADMIN_BULK_COMMISSION_ACTIONS_RENDER_V1 START =====

@app.route("/admin/bulk-update-commission-status", methods=["POST"])
def admin_bulk_update_commission_status():
    """
    Owner/Admin action:
    Bulk update commission status.

    Safety:
    - Requires ADMIN_KEY.
    - Mark Paid is handled safely by Apps Script and skips non-approved commissions.
    - Every updated commission is logged in AuditLogs.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    new_status = (
        get_payload_value(payload, "new_status", default="")
        or request.form.get("new_status", "").strip()
    ).lower().strip()

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Bulk commission action from Admin Dashboard"
    )

    commission_ids = []

    if request.is_json:
        raw_ids = payload.get("commission_ids") or []
        if isinstance(raw_ids, list):
            commission_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
        else:
            commission_ids = [x.strip() for x in str(raw_ids).replace("\n", ",").split(",") if x.strip()]
    else:
        commission_ids = request.form.getlist("commission_ids")
        commission_ids = [str(x).strip() for x in commission_ids if str(x).strip()]

    if new_status not in ("approved", "hold", "rejected", "paid"):
        return jsonify({
            "status": "error",
            "message": "Invalid new_status"
        }), 400

    if not commission_ids:
        if request.is_json:
            return jsonify({
                "status": "error",
                "message": "No commissions selected"
            }), 400

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=bulk_no_selection"
        )

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_bulk_update_commission_status",
                "commission_ids": commission_ids,
                "partner_id": partner_id,
                "new_status": new_status,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard_bulk"
            },
            label="admin_bulk_update_commission_status"
        )

        print(
            f"ADMIN BULK UPDATE COMMISSION STATUS ✅ partner_id={partner_id} new_status={new_status} count={len(commission_ids)} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        updated_count = 0
        skipped_count = 0

        if isinstance(result, dict):
            updated_count = int(result.get("updated_count") or 0)
            skipped_count = int(result.get("skipped_count") or 0)

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=bulk_commission_{quote(new_status)}&updated={updated_count}&skipped={skipped_count}"
        )

    except Exception as error:
        print(
            f"ADMIN BULK UPDATE COMMISSION STATUS ERROR ❌ partner_id={partner_id} status={new_status} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=bulk_commission_error"
        )

# ===== ALSAAB_ADMIN_BULK_COMMISSION_ACTIONS_RENDER_V1 END =====



# ===== ALSAAB_ADMIN_PARTNER_STATUS_ACTIONS_RENDER_V2 START =====

@app.route("/admin/update-partner-status", methods=["POST"])
def admin_update_partner_status():
    """
    Owner/Admin action:
    Suspend or activate partner.

    Security:
    - Requires ADMIN_KEY.
    - Owner-level admin action.
    - Apps Script logs action in AuditLogs.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    new_status = (
        get_payload_value(payload, "new_status", default="")
        or request.form.get("new_status", "").strip()
    ).lower().strip()

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Admin partner status update"
    )

    partner_id = str(partner_id or "").strip().upper()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    if new_status not in ("active", "suspended"):
        return jsonify({
            "status": "error",
            "message": "Invalid new_status"
        }), 400

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id)

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_update_partner_status",
                "partner_id": partner_id,
                "new_status": new_status,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard"
            },
            label="admin_update_partner_status"
        )

        recalculate_result = {}

        if new_status == "active":
            try:
                from database import sync_partner_level_progress_to_google_sheet
                recalculate_result = sync_partner_level_progress_to_google_sheet(partner_id)
            except Exception as recalc_error:
                recalculate_result = {
                    "status": "error",
                    "message": str(recalc_error)
                }

        print(
            f"ADMIN UPDATE PARTNER STATUS ✅ partner_id={partner_id} new_status={new_status} result={result} recalc={recalculate_result}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "success",
                "partner_id": partner_id,
                "new_status": new_status,
                "result": result,
                "recalculate_result": recalculate_result
            })

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=partner_{quote(new_status)}"
        )

    except Exception as error:
        print(
            f"ADMIN UPDATE PARTNER STATUS ERROR ❌ partner_id={partner_id} status={new_status} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=partner_status_error"
        )

# ===== ALSAAB_ADMIN_PARTNER_STATUS_ACTIONS_RENDER_V2 END =====



# ===== ALSAAB_DOWNLINE_TRANSFER_PREVIEW_RENDER_V1 START =====

@app.route("/admin/downline-transfer-preview", methods=["GET"])
def admin_downline_transfer_preview():
    """
    Owner/Admin preview only:
    Shows what would be affected if partner direct downline is transferred to alsaab.

    No changes are made here.
    """
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    partner_id = request.args.get("partner_id", "").strip().upper()

    if not partner_id:
        return "partner_id is required", 400

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id)
        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN is missing", 500

        preview = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_downline_transfer_preview",
                "partner_id": partner_id
            },
            label="admin_downline_transfer_preview"
        )

        if not isinstance(preview, dict) or preview.get("status") != "success":
            return render_template_string(
                """
                <html>
                <head><meta charset="utf-8"><title>Transfer Preview Error</title></head>
                <body style="font-family:Arial; direction:rtl; padding:30px;">
                  <h2>حدث خطأ في معاينة النقل</h2>
                  <pre>{{ preview }}</pre>
                  <a href="/admin-dashboard?key={{ encoded_key }}&partner_id={{ partner_id }}">رجوع</a>
                </body>
                </html>
                """,
                preview=preview,
                encoded_key=quote(key),
                partner_id=partner_id
            ), 500

        target_partner = preview.get("target_partner") or {}
        direct_children = preview.get("direct_children") or []
        network_rows = preview.get("network_rows") or []
        depth_counts = preview.get("depth_counts") or {}

        html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>معاينة نقل الشبكة إلى alsaab</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    body {
      margin: 0;
      background: #0b0b0b;
      color: #f5f0df;
      font-family: Arial, Tahoma, sans-serif;
      direction: rtl;
    }

    .page {
      max-width: 1200px;
      margin: 0 auto;
      padding: 28px;
    }

    .header, .section, .card {
      background: #111;
      border: 1px solid rgba(215,184,90,.35);
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 18px;
    }

    h1, h2, h3 {
      color: #d7b85a;
      margin-top: 0;
    }

    .sub {
      color: #cfc7ad;
      line-height: 1.7;
    }

    .warning {
      background: rgba(255,207,102,.08);
      border: 1px solid rgba(255,207,102,.45);
      color: #ffcf66;
      border-radius: 14px;
      padding: 14px;
      margin-bottom: 18px;
      font-weight: 700;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }

    .big {
      font-size: 28px;
      font-weight: 900;
      color: #fff;
    }

    .muted {
      color: #aaa;
      font-size: 13px;
      margin-top: 6px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
    }

    th, td {
      padding: 10px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      text-align: right;
      font-size: 13px;
    }

    th {
      color: #d7b85a;
      background: #181818;
    }

    .table-wrap {
      overflow-x: auto;
    }

    .action-btn {
      display: inline-block;
      border: 1px solid rgba(215,184,90,.55);
      color: #f0cc68;
      background: #111;
      padding: 10px 14px;
      border-radius: 999px;
      text-decoration: none;
      font-weight: 700;
    }

    @media (max-width: 900px) {
      .grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 600px) {
      .grid {
        grid-template-columns: 1fr;
      }

      .page {
        padding: 16px;
      }
    }
  </style>
</head>

<body>
  <div class="page">
    <div class="header">
      <h1>معاينة نقل الشبكة إلى alsaab</h1>
      <div class="sub">
        هذه الصفحة للمعاينة فقط. لم يتم نقل أي شريك أو عميل. الهدف معرفة من سيتأثر قبل تفعيل النقل الحقيقي.
      </div>
    </div>

    <div class="warning">
      تنبيه: النقل الفعلي غير مفعّل هنا. هذه معاينة فقط قبل بناء زر Transfer Downline to alsaab.
    </div>

    <div class="grid">
      <div class="card">
        <h3>الشريك المستهدف</h3>
        <div class="big">{{ partner_id }}</div>
        <div class="muted">{{ target_partner.get("partner_name") or "-" }}</div>
      </div>

      <div class="card">
        <h3>الحالة الحالية</h3>
        <div class="big">{{ target_partner.get("status") or "-" }}</div>
        <div class="muted">Rank: {{ target_partner.get("partner_rank") or "-" }}</div>
      </div>

      <div class="card">
        <h3>المباشرين تحته</h3>
        <div class="big">{{ preview.get("direct_children_count") or 0 }}</div>
        <div class="muted">سيتم مراجعتهم كمرشحين للنقل إلى alsaab</div>
      </div>

      <div class="card">
        <h3>إجمالي الشبكة</h3>
        <div class="big">{{ preview.get("network_count") or 0 }}</div>
        <div class="muted">كل المستويات أسفل هذا الشريك</div>
      </div>
    </div>

    <div class="section">
      <h2>توزيع الشبكة حسب العمق</h2>
      <div class="grid">
        <div class="card"><h3>Depth 1</h3><div class="big">{{ depth_counts.get("1", 0) or depth_counts.get(1, 0) }}</div></div>
        <div class="card"><h3>Depth 2</h3><div class="big">{{ depth_counts.get("2", 0) or depth_counts.get(2, 0) }}</div></div>
        <div class="card"><h3>Depth 3</h3><div class="big">{{ depth_counts.get("3", 0) or depth_counts.get(3, 0) }}</div></div>
        <div class="card"><h3>Depth 4/5</h3><div class="big">{{ (depth_counts.get("4", 0) or depth_counts.get(4, 0)) + (depth_counts.get("5", 0) or depth_counts.get(5, 0)) }}</div></div>
      </div>
    </div>

    <div class="section">
      <h2>الشركاء المباشرين الذين سيتم مراجعتهم للنقل</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Partner ID</th>
              <th>الاسم</th>
              <th>Current Sponsor</th>
              <th>Current Parent</th>
              <th>Status</th>
              <th>Rank</th>
              <th>Email</th>
            </tr>
          </thead>
          <tbody>
            {% for child in direct_children %}
            <tr>
              <td>{{ child.partner_id or "-" }}</td>
              <td>{{ child.partner_name or "-" }}</td>
              <td>{{ child.current_sponsor_partner_id or "-" }}</td>
              <td>{{ child.current_parent_partner_id or "-" }}</td>
              <td>{{ child.status or "-" }}</td>
              <td>{{ child.partner_rank or "-" }}</td>
              <td>{{ child.email or "-" }}</td>
            </tr>
            {% else %}
            <tr><td colspan="7">لا يوجد direct downline لهذا الشريك.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <h2>عينة من الشبكة الكاملة أسفل الشريك</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Descendant Partner ID</th>
              <th>Depth</th>
              <th>Line Owner</th>
              <th>الاسم</th>
              <th>Status</th>
              <th>Rank</th>
            </tr>
          </thead>
          <tbody>
            {% for row in network_rows[:50] %}
            <tr>
              <td>{{ row.descendant_partner_id or "-" }}</td>
              <td>{{ row.depth or "-" }}</td>
              <td>{{ row.line_owner_partner_id or "-" }}</td>
              <td>{{ row.partner_name or "-" }}</td>
              <td>{{ row.status or "-" }}</td>
              <td>{{ row.partner_rank or "-" }}</td>
            </tr>
            {% else %}
            <tr><td colspan="6">لا توجد شبكة أسفل هذا الشريك.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    
    <!-- ALSAAB_DOWNLINE_TRANSFER_EXECUTION_FORM_FORCE_V1 START -->
    <div class="section">
      <h2>تنفيذ النقل الفعلي</h2>
      <div class="warning">
        هذا الإجراء سيغير Sponsor / Parent للشركاء المباشرين تحت هذا الشريك إلى alsaab، وسيعيد بناء PartnerTree. لا تستخدمه إلا بعد التأكد من المعاينة.
      </div>

      <form method="POST" action="/admin/transfer-downline-to-alsaab">
        <input type="hidden" name="key" value="{{ raw_admin_key or encoded_key }}">
        <input type="hidden" name="partner_id" value="{{ partner_id }}">

        <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">سبب النقل</label>
        <textarea
          name="reason"
          required
          placeholder="مثال: الشريك ألغى اشتراكه نهائياً، وبقرار إداري تم نقل الشبكة إلى alsaab."
          style="width:100%; min-height:90px; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
        ></textarea>

        <label style="display:block; color:#d7b85a; font-weight:700; margin-bottom:8px;">اكتب هذا النص للتأكيد</label>
        <input
          name="confirm_text"
          required
          placeholder="TRANSFER_TO_ALSAAB"
          style="width:100%; box-sizing:border-box; background:#0b0b0b; color:#fff; border:1px solid rgba(215,184,90,.35); border-radius:12px; padding:12px; margin-bottom:12px;"
        >

        <button
          type="submit"
          onclick="return confirm('تأكيد نهائي: هل تريد نقل الـ direct downline إلى alsaab؟')"
          style="border:1px solid rgba(255,122,122,.7); color:#ff7a7a; background:#111; padding:12px 16px; border-radius:999px; font-weight:900; cursor:pointer;"
        >
          Transfer Downline to alsaab
        </button>
      </form>
    </div>
    <!-- ALSAAB_DOWNLINE_TRANSFER_EXECUTION_FORM_FORCE_V1 END -->

<a class="action-btn" href="/admin-dashboard?key={{ encoded_key }}&partner_id={{ partner_id }}">رجوع إلى Admin Dashboard</a>
  </div>
</body>
</html>
        """

        return render_template_string(
            html,
            encoded_key=quote(key),
            raw_admin_key=key,
            partner_id=partner_id,
            preview=preview,
            target_partner=target_partner,
            direct_children=direct_children,
            network_rows=network_rows,
            depth_counts=depth_counts
        )

    except Exception as error:
        print(f"DOWNLINE TRANSFER PREVIEW ERROR ❌ partner_id={partner_id} error={error}", flush=True)

        return render_template_string(
            """
            <html>
            <head><meta charset="utf-8"><title>Transfer Preview Error</title></head>
            <body style="font-family:Arial; direction:rtl; padding:30px;">
              <h2>حدث خطأ في عرض معاينة النقل</h2>
              <p>{{ error }}</p>
            </body>
            </html>
            """,
            error=str(error)
        ), 500

# ===== ALSAAB_DOWNLINE_TRANSFER_PREVIEW_RENDER_V1 END =====



# ===== ALSAAB_DOWNLINE_TRANSFER_EXECUTE_RENDER_V1 START =====

@app.route("/admin/transfer-downline-to-alsaab", methods=["POST"])
def admin_transfer_downline_to_alsaab():
    """
    Owner/Admin action:
    Transfer direct downline of a partner to alsaab.

    Security:
    - Requires ADMIN_KEY.
    - Requires reason.
    - Requires confirm_text = TRANSFER_TO_ALSAAB.
    - Apps Script logs AuditLogs and rebuilds PartnerTree.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
    )

    confirm_text = (
        get_payload_value(payload, "confirm_text", default="")
        or request.form.get("confirm_text", "").strip()
    )

    partner_id = str(partner_id or "").strip().upper()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    if not reason:
        return jsonify({
            "status": "error",
            "message": "reason is required"
        }), 400

    if confirm_text != "TRANSFER_TO_ALSAAB":
        return jsonify({
            "status": "error",
            "message": "confirm_text must be TRANSFER_TO_ALSAAB"
        }), 400

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id)

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_transfer_downline_to_alsaab",
                "partner_id": partner_id,
                "reason": reason,
                "confirm_text": confirm_text,
                "actor": "owner_admin",
                "source": "admin_dashboard"
            },
            label="admin_transfer_downline_to_alsaab"
        )

        print(
            f"ADMIN TRANSFER DOWNLINE TO ALSAAB ✅ partner_id={partner_id} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        transferred_count = 0

        if isinstance(result, dict):
            transferred_count = int(result.get("transferred_count") or 0)

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=downline_transferred&transferred={transferred_count}"
        )

    except Exception as error:
        print(
            f"ADMIN TRANSFER DOWNLINE ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=downline_transfer_error"
        )

# ===== ALSAAB_DOWNLINE_TRANSFER_EXECUTE_RENDER_V1 END =====



# ===== ALSAAB_AUTO_APPROVE_PENDING_RENDER_V1 START =====

@app.route("/admin/auto-approve-pending-commissions", methods=["POST"])
def admin_auto_approve_pending_commissions():
    """
    Owner/Admin action:
    Convert old pending commissions to approved.

    This is for legacy pending data only.
    New valid commissions are auto-approved by Apps Script.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Convert old pending commissions to approved"
    )

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id) if partner_id else ""

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_auto_approve_pending_commissions",
                "partner_id": partner_id,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard"
            },
            label="admin_auto_approve_pending_commissions"
        )

        print(
            f"ADMIN AUTO APPROVE PENDING COMMISSIONS ✅ partner_id={partner_id} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        action = "auto_approved_pending"

        if isinstance(result, dict) and result.get("status") != "success":
            action = "auto_approve_pending_error"

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action={quote(action)}"
        )

    except Exception as error:
        print(
            f"ADMIN AUTO APPROVE PENDING ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=auto_approve_pending_error"
        )

# ===== ALSAAB_AUTO_APPROVE_PENDING_RENDER_V1 END =====



# ===== ALSAAB_MARK_PARTNER_PAID_BUTTON_RENDER_V1 START =====

@app.route("/admin/mark-partner-paid", methods=["POST"])
def admin_mark_partner_paid():
    """
    Owner/Admin action:
    After owner manually transfers payout to partner,
    mark all approved commissions for this partner as paid.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Owner manually transferred payout to partner"
    )

    partner_id = str(partner_id or "").strip().upper()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id)

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_mark_partner_approved_commissions_paid",
                "partner_id": partner_id,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard",
                "payment_method": "manual_transfer"
            },
            label="admin_mark_partner_paid"
        )

        print(
            f"ADMIN MARK PARTNER PAID ✅ partner_id={partner_id} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        action = "partner_marked_paid"

        if isinstance(result, dict) and result.get("status") != "success":
            action = "partner_marked_paid_error"

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action={quote(action)}"
        )

    except Exception as error:
        print(
            f"ADMIN MARK PARTNER PAID ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=partner_marked_paid_error"
        )

# ===== ALSAAB_MARK_PARTNER_PAID_BUTTON_RENDER_V1 END =====



# ===== ALSAAB_WHATSAPP_WEBHOOK_FOUNDATION_V1 START =====

@app.route("/whatsapp-webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    """
    WhatsApp Cloud API webhook foundation.

    GET:
    - Meta webhook verification.

    POST:
    - Receives WhatsApp messages/status events.
    - Looks up phone_number_id in ClientChannels.
    - Logs incoming messages into WhatsAppMessages.
    - Does not send AI replies yet. Sending replies is the next step.
    """
    import os
    import json
    import hmac
    import hashlib

    # Meta webhook verification.
    if request.method == "GET":
        verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()

        mode = request.args.get("hub.mode", "").strip()
        token = request.args.get("hub.verify_token", "").strip()
        challenge = request.args.get("hub.challenge", "").strip()

        if mode == "subscribe" and verify_token and token == verify_token:
            return challenge, 200

        return "Forbidden", 403

    raw_body = request.get_data() or b""

    # Optional signature verification.
    # If WHATSAPP_APP_SECRET is set, we verify X-Hub-Signature-256.
    app_secret = os.getenv("WHATSAPP_APP_SECRET", "").strip()

    if app_secret:
        received_signature = request.headers.get("X-Hub-Signature-256", "").strip()
        expected_signature = "sha256=" + hmac.new(
            app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        if not received_signature or not hmac.compare_digest(received_signature, expected_signature):
            print("WHATSAPP WEBHOOK SIGNATURE FAILED ❌", flush=True)
            return jsonify({"status": "error", "message": "Invalid signature"}), 403

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        payload = request.get_json(silent=True) or {}

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            print("WHATSAPP WEBHOOK ERROR ❌ GOOGLE_SHEET_TOKEN missing", flush=True)
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        processed = []
        status_events = []

        entries = payload.get("entry", []) if isinstance(payload, dict) else []

        for entry in entries:
            changes = entry.get("changes", []) if isinstance(entry, dict) else []

            for change in changes:
                value = change.get("value", {}) if isinstance(change, dict) else {}

                metadata = value.get("metadata", {}) if isinstance(value, dict) else {}
                phone_number_id = str(metadata.get("phone_number_id", "") or "").strip()
                display_phone_number = str(metadata.get("display_phone_number", "") or "").strip()

                # Lookup channel mapping from ClientChannels.
                lookup = {}

                if phone_number_id:
                    lookup = post_to_google_sheet_json(
                        {
                            "token": google_sheet_token,
                            "action": "whatsapp_channel_lookup",
                            "phone_number_id": phone_number_id
                        },
                        label="whatsapp_channel_lookup"
                    )

                found_channel = isinstance(lookup, dict) and lookup.get("found") is True

                client_id = ""
                partner_id = ""
                business_name = ""

                if found_channel:
                    client_id = str(lookup.get("client_id", "") or "").strip()
                    partner_id = str(lookup.get("partner_id", "") or "").strip()
                    business_name = str(lookup.get("business_name", "") or "").strip()
                else:
                    # Safe fallback for company pilot until ClientChannels is mapped.
                    client_id = os.getenv("WHATSAPP_DEFAULT_CLIENT_ID", "alsaab").strip()
                    partner_id = os.getenv("WHATSAPP_DEFAULT_PARTNER_ID", "alsaab").strip()
                    business_name = "ALSAAB AI"

                contacts = value.get("contacts", []) if isinstance(value, dict) else []
                contact_names = {}

                for contact in contacts:
                    wa_id = str(contact.get("wa_id", "") or "").strip()
                    profile = contact.get("profile", {}) or {}
                    contact_names[wa_id] = str(profile.get("name", "") or "").strip()

                messages = value.get("messages", []) if isinstance(value, dict) else []

                for message in messages:
                    message_id = str(message.get("id", "") or "").strip()
                    from_number = str(message.get("from", "") or "").strip()
                    message_type = str(message.get("type", "") or "unknown").strip()

                    text_value = ""

                    if message_type == "text":
                        text_value = str((message.get("text", {}) or {}).get("body", "") or "").strip()
                    elif message_type == "button":
                        text_value = str((message.get("button", {}) or {}).get("text", "") or "").strip()
                    elif message_type == "interactive":
                        interactive = message.get("interactive", {}) or {}
                        button_reply = interactive.get("button_reply", {}) or {}
                        list_reply = interactive.get("list_reply", {}) or {}
                        text_value = (
                            str(button_reply.get("title", "") or "").strip()
                            or str(button_reply.get("id", "") or "").strip()
                            or str(list_reply.get("title", "") or "").strip()
                            or str(list_reply.get("id", "") or "").strip()
                        )
                    else:
                        text_value = f"[{message_type}]"

                    customer_name = contact_names.get(from_number, "")

                    log_result = post_to_google_sheet_json(
                        {
                            "token": google_sheet_token,
                            "action": "whatsapp_message_log",
                            "message_id": message_id,
                            "direction": "incoming",
                            "client_id": client_id,
                            "partner_id": partner_id,
                            "phone_number_id": phone_number_id,
                            "from": from_number,
                            "to": display_phone_number,
                            "customer_name": customer_name,
                            "text": text_value,
                            "message_type": message_type,
                            "status": "received",
                            "raw_json": json.dumps(message, ensure_ascii=False),
                            "notes": (
                                f"business_name={business_name}; "
                                f"channel_lookup_found={str(found_channel).lower()}"
                            )
                        },
                        label="whatsapp_message_log"
                    )

                    processed.append({
                        "message_id": message_id,
                        "from": from_number,
                        "type": message_type,
                        "client_id": client_id,
                        "partner_id": partner_id,
                        "phone_number_id": phone_number_id,
                        "logged": log_result
                    })

                statuses = value.get("statuses", []) if isinstance(value, dict) else []

                for status in statuses:
                    status_events.append({
                        "phone_number_id": phone_number_id,
                        "status": status
                    })

                    # Keep status logs separate but still stored as WhatsAppMessages for now.
                    post_to_google_sheet_json(
                        {
                            "token": google_sheet_token,
                            "action": "whatsapp_message_log",
                            "message_id": str(status.get("id", "") or "").strip(),
                            "direction": "status",
                            "client_id": client_id,
                            "partner_id": partner_id,
                            "phone_number_id": phone_number_id,
                            "from": "",
                            "to": display_phone_number,
                            "customer_name": "",
                            "text": str(status.get("status", "") or "").strip(),
                            "message_type": "status",
                            "status": str(status.get("status", "") or "").strip(),
                            "raw_json": json.dumps(status, ensure_ascii=False),
                            "notes": "WhatsApp message status event"
                        },
                        label="whatsapp_status_log"
                    )

        print(
            f"WHATSAPP WEBHOOK RECEIVED ✅ processed={len(processed)} statuses={len(status_events)}",
            flush=True
        )

        return jsonify({
            "status": "success",
            "processed_count": len(processed),
            "status_count": len(status_events),
            "processed": processed[:10]
        }), 200

    except Exception as error:
        print(f"WHATSAPP WEBHOOK ERROR ❌ {error}", flush=True)

        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500

# ===== ALSAAB_WHATSAPP_WEBHOOK_FOUNDATION_V1 END =====



# ===== ALSAAB_CLIENT_WHATSAPP_SETUP_ROUTE_V1 START =====

@app.route("/client-dashboard/save-whatsapp-setup", methods=["POST"])
def client_dashboard_save_whatsapp_setup():
    """
    Client Dashboard action:
    Save WhatsApp setup request for current account.

    Default setup_type:
    existing_business_app_coexistence
    """
    import os

    lang = request.form.get("lang", "ar").strip() or "ar"
    key = request.form.get("key", "").strip()
    sso_token = request.form.get("sso", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", lang)), 302

    partner_id = (
        request.form.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        return redirect(build_dashboard_login_redirect("client", partner_id, lang)), 302

    business_name = request.form.get("business_name", "").strip()
    whatsapp_number = request.form.get("whatsapp_number", "").strip()
    preferred_language = request.form.get("preferred_language", "ar").strip() or "ar"
    human_handoff = request.form.get("human_handoff", "yes").strip() or "yes"
    customer_notes = request.form.get("customer_notes", "").strip()

    if not whatsapp_number:
        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "whatsapp_setup_error"))

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            print("WHATSAPP SETUP REQUEST ERROR ❌ GOOGLE_SHEET_TOKEN missing", flush=True)
            return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "whatsapp_setup_error"))

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "whatsapp_setup_request",
                "client_id": partner_id,
                "partner_id": partner_id,
                "business_name": business_name,
                "whatsapp_number": whatsapp_number,
                "setup_type": "existing_business_app_coexistence",
                "connection_status": "pending_setup",
                "preferred_language": preferred_language,
                "human_handoff": human_handoff,
                "customer_notes": customer_notes,
            },
            label="whatsapp_setup_request"
        )

        print(f"WHATSAPP SETUP REQUEST SAVED ✅ partner_id={partner_id} result={result}", flush=True)

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "whatsapp_setup_saved"))

    except Exception as error:
        print(f"WHATSAPP SETUP REQUEST ERROR ❌ partner_id={partner_id} error={error}", flush=True)
        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "whatsapp_setup_error"))

# ===== ALSAAB_CLIENT_WHATSAPP_SETUP_ROUTE_V1 END =====



# ===== ALSAAB_ADMIN_WHATSAPP_SETUP_REQUESTS_PAGE_V1 START =====

@app.route("/admin/whatsapp-setup-requests", methods=["GET"])
def admin_whatsapp_setup_requests_page():
    """
    Owner/Admin page:
    View WhatsApp setup requests from Client Dashboard.
    """
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    status_filter = request.args.get("status", "").strip()
    partner_id_filter = request.args.get("partner_id", "").strip()

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_whatsapp_setup_requests",
                "connection_status": status_filter,
                "partner_id": partner_id_filter
            },
            label="admin_whatsapp_setup_requests"
        )

        requests_list = []
        count = 0

        if isinstance(result, dict) and result.get("status") == "success":
            requests_list = result.get("requests") or []
            count = result.get("count") or len(requests_list)

        html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>WhatsApp Setup Requests</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    body {
      margin: 0;
      background: #0b0b0b;
      color: #f5f0df;
      font-family: Arial, Tahoma, sans-serif;
      direction: rtl;
    }

    .page {
      max-width: 1400px;
      margin: 0 auto;
      padding: 24px;
    }

    .header, .section {
      background: #111;
      border: 1px solid rgba(215,184,90,.35);
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 18px;
    }

    h1, h2, h3 {
      color: #d7b85a;
      margin-top: 0;
    }

    .muted {
      color: #cfc7ad;
      line-height: 1.7;
    }

    .filters {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }

    input, select, textarea {
      background: #0b0b0b;
      color: #fff;
      border: 1px solid rgba(215,184,90,.35);
      border-radius: 12px;
      padding: 10px;
      box-sizing: border-box;
    }

    button, .btn {
      border: 1px solid rgba(215,184,90,.65);
      background: #111;
      color: #f0cc68;
      border-radius: 999px;
      padding: 10px 14px;
      font-weight: 800;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
    }

    .btn-green {
      border-color: rgba(128,226,138,.65);
      color: #80e28a;
    }

    .table-wrap {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 1100px;
    }

    th, td {
      padding: 10px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      vertical-align: top;
      font-size: 13px;
      text-align: right;
    }

    th {
      color: #d7b85a;
      background: #181818;
      position: sticky;
      top: 0;
      z-index: 1;
    }

    .badge {
      display: inline-block;
      padding: 5px 9px;
      border-radius: 999px;
      border: 1px solid rgba(215,184,90,.45);
      color: #f0cc68;
      font-weight: 700;
      font-size: 12px;
    }

    .small {
      font-size: 12px;
      color: #aaa;
    }

    textarea {
      width: 220px;
      min-height: 70px;
    }

    .update-form {
      min-width: 270px;
    }

    .update-form input,
    .update-form select,
    .update-form textarea {
      width: 100%;
      margin-bottom: 8px;
    }

    @media (max-width: 700px) {
      .page {
        padding: 14px;
      }
    }
  </style>
</head>

<body>
  <div class="page">
    <div class="header">
      <h1>طلبات ربط WhatsApp</h1>
      <div class="muted">
        هذه الطلبات تأتي من Client Dashboard عندما يطلب العميل ربط رقم WhatsApp Business الحالي بنظام ALSAAB AI.
      </div>

      <form method="GET" action="/admin/whatsapp-setup-requests" class="filters">
        <input type="hidden" name="key" value="{{ key }}">
        <input name="partner_id" placeholder="Partner ID" value="{{ partner_id_filter }}">
        <select name="status">
          <option value="">كل الحالات</option>
          {% for status in ["pending_setup", "under_review", "connected", "testing", "live", "rejected"] %}
            <option value="{{ status }}" {% if status_filter == status %}selected{% endif %}>{{ status }}</option>
          {% endfor %}
        </select>
        <button type="submit">بحث</button>
        <a class="btn" href="/admin-dashboard?key={{ encoded_key }}">رجوع إلى Admin Dashboard</a>
      </form>
    </div>

    <div class="section">
      <h2>الطلبات: {{ count }}</h2>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Request ID</th>
              <th>Partner / Client</th>
              <th>Business</th>
              <th>WhatsApp Number</th>
              <th>Setup Type</th>
              <th>Status</th>
              <th>Customer Notes</th>
              <th>Meta IDs</th>
              <th>Admin Update</th>
            </tr>
          </thead>

          <tbody>
            {% for item in requests_list %}
            <tr>
              <td>
                <strong>{{ item.request_id or "-" }}</strong>
                <div class="small">{{ item.date or "" }}</div>
                <div class="small">Updated: {{ item.updated_at or "-" }}</div>
              </td>

              <td>
                <div><strong>Partner:</strong> {{ item.partner_id or "-" }}</div>
                <div><strong>Client:</strong> {{ item.client_id or "-" }}</div>
              </td>

              <td>
                <strong>{{ item.business_name or "-" }}</strong>
                <div class="small">Lang: {{ item.preferred_language or "-" }}</div>
                <div class="small">Handoff: {{ item.human_handoff or "-" }}</div>
              </td>

              <td>{{ item.whatsapp_number or "-" }}</td>

              <td>{{ item.setup_type or "-" }}</td>

              <td><span class="badge">{{ item.connection_status or "-" }}</span></td>

              <td>
                <div>{{ item.customer_notes or "-" }}</div>
                {% if item.admin_notes %}
                  <hr style="border-color:rgba(255,255,255,.08);">
                  <div class="small"><strong>Admin:</strong> {{ item.admin_notes }}</div>
                {% endif %}
              </td>

              <td>
                <div><strong>Phone Number ID:</strong> {{ item.phone_number_id or "-" }}</div>
                <div><strong>WABA ID:</strong> {{ item.waba_id or "-" }}</div>
                <div><strong>Provider:</strong> {{ item.provider or "-" }}</div>
              </td>

              <td>
                <form method="POST" action="/admin/update-whatsapp-setup-request" class="update-form">
                  <input type="hidden" name="key" value="{{ key }}">
                  <input type="hidden" name="request_id" value="{{ item.request_id }}">

                  <select name="connection_status">
                    {% for status in ["pending_setup", "under_review", "connected", "testing", "live", "rejected"] %}
                      <option value="{{ status }}" {% if item.connection_status == status %}selected{% endif %}>{{ status }}</option>
                    {% endfor %}
                  </select>

                  <input name="phone_number_id" placeholder="Phone Number ID" value="{{ item.phone_number_id or "" }}">
                  <input name="waba_id" placeholder="WABA ID" value="{{ item.waba_id or "" }}">
                  <input name="provider" placeholder="Provider" value="{{ item.provider or "" }}">

                  <textarea name="admin_notes" placeholder="Admin notes">{{ item.admin_notes or "" }}</textarea>

                  <button class="btn-green" type="submit">تحديث</button>
                </form>
              </td>
            </tr>
            {% else %}
            <tr>
              <td colspan="9">لا توجد طلبات WhatsApp حالياً.</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</body>
</html>
        """

        return render_template_string(
            html,
            key=key,
            encoded_key=quote(key),
            status_filter=status_filter,
            partner_id_filter=partner_id_filter,
            result=result,
            requests_list=requests_list,
            count=count
        )

    except Exception as error:
        print(f"ADMIN WHATSAPP SETUP REQUESTS PAGE ERROR ❌ {error}", flush=True)
        return f"Error loading WhatsApp setup requests: {error}", 500


@app.route("/admin/update-whatsapp-setup-request", methods=["POST"])
def admin_update_whatsapp_setup_request_route():
    """
    Owner/Admin action:
    Update WhatsApp setup request status and Meta IDs.
    """
    import os
    from urllib.parse import quote

    key = request.form.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    request_id = request.form.get("request_id", "").strip()
    connection_status = request.form.get("connection_status", "").strip()
    admin_notes = request.form.get("admin_notes", "").strip()
    phone_number_id = request.form.get("phone_number_id", "").strip()
    waba_id = request.form.get("waba_id", "").strip()
    provider = request.form.get("provider", "").strip()

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_update_whatsapp_setup_request",
                "request_id": request_id,
                "connection_status": connection_status,
                "admin_notes": admin_notes,
                "phone_number_id": phone_number_id,
                "waba_id": waba_id,
                "provider": provider,
                "actor": "owner_admin",
                "source": "admin_whatsapp_setup_requests_page",
                "reason": "Admin updated WhatsApp setup request"
            },
            label="admin_update_whatsapp_setup_request"
        )

        print(f"ADMIN UPDATE WHATSAPP SETUP REQUEST ✅ request_id={request_id} result={result}", flush=True)

        return redirect(f"/admin/whatsapp-setup-requests?key={quote(key)}")

    except Exception as error:
        print(f"ADMIN UPDATE WHATSAPP SETUP REQUEST ERROR ❌ request_id={request_id} error={error}", flush=True)
        return redirect(f"/admin/whatsapp-setup-requests?key={quote(key)}")

# ===== ALSAAB_ADMIN_WHATSAPP_SETUP_REQUESTS_PAGE_V1 END =====




# ===== ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2 START =====

@app.after_request
def inject_admin_whatsapp_requests_button(response):
    """
    Adds a normal non-floating WhatsApp setup requests button inside Admin Dashboard.
    """
    try:
        if request.path != "/admin-dashboard":
            return response

        content_type = response.headers.get("Content-Type", "")

        if "text/html" not in content_type:
            return response

        html = response.get_data(as_text=True)

        if "ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2_HTML" in html:
            return response

        snippet = """
<!-- ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2_HTML START -->
<script>
(function () {
  if (document.getElementById("alsaab-wa-requests-admin-box")) {
    return;
  }

  var params = new URLSearchParams(window.location.search);
  var key = params.get("key") || "";
  var href = "/admin/whatsapp-setup-requests?key=" + encodeURIComponent(key);

  var box = document.createElement("div");
  box.id = "alsaab-wa-requests-admin-box";
  box.style.cssText = [
    "background:#111",
    "border:1px solid rgba(215,184,90,.35)",
    "border-radius:18px",
    "padding:16px 18px",
    "margin:18px 0",
    "display:flex",
    "align-items:center",
    "justify-content:space-between",
    "gap:12px",
    "flex-wrap:wrap",
    "box-shadow:0 8px 25px rgba(0,0,0,.20)"
  ].join(";");

  box.innerHTML =
    '<div>' +
      '<div style="color:#d7b85a;font-size:20px;font-weight:900;margin-bottom:4px;">طلبات ربط WhatsApp</div>' +
      '<div style="color:#cfc7ad;font-size:13px;line-height:1.7;">إدارة طلبات ربط أرقام WhatsApp الحالية للعملاء وتحديث حالة الربط.</div>' +
    '</div>' +
    '<a href="' + href + '" style="' +
      'border:1px solid rgba(215,184,90,.75);' +
      'color:#d7b85a;' +
      'background:#0b0b0b;' +
      'border-radius:999px;' +
      'padding:11px 16px;' +
      'font-family:Arial,Tahoma,sans-serif;' +
      'font-weight:900;' +
      'text-decoration:none;' +
      'display:inline-block;' +
    '">فتح طلبات ربط WhatsApp</a>';

  var header = document.querySelector(".header");
  var page = document.querySelector(".page") || document.body;

  if (header && header.parentNode) {
    header.parentNode.insertBefore(box, header.nextSibling);
  } else if (page && page.firstChild) {
    page.insertBefore(box, page.firstChild);
  } else {
    document.body.insertBefore(box, document.body.firstChild);
  }
})();
</script>
<!-- ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2_HTML END -->
"""

        if "</body>" in html:
            html = html.replace("</body>", snippet + "\n</body>", 1)
        else:
            html = html + snippet

        response.set_data(html)

    except Exception as error:
        print(f"ADMIN WHATSAPP REQUESTS BUTTON INJECTION ERROR ❌ {error}", flush=True)

    return response

# ===== ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2 END =====



# ===== ALSAAB WEBSITE SETUP ROUTES REGISTER START =====
try:
    from website_setup_routes import register_website_setup_routes
except ImportError:
    from backend.website_setup_routes import register_website_setup_routes

register_website_setup_routes(app, ADMIN_KEY)
# ===== ALSAAB WEBSITE SETUP ROUTES REGISTER END =====
# ===== ALSAAB BOT CONTROL ROUTES REGISTER START =====
try:
    from bot_control_routes import register_bot_control_routes
except ImportError:
    from backend.bot_control_routes import register_bot_control_routes

register_bot_control_routes(app)
# ===== ALSAAB BOT CONTROL ROUTES REGISTER END =====
# ===== ALSAAB UPGRADE ROUTES REGISTER START =====
try:
    from upgrade_routes import register_upgrade_routes
except ImportError:
    from backend.upgrade_routes import register_upgrade_routes

register_upgrade_routes(app, ADMIN_KEY)
# ===== ALSAAB UPGRADE ROUTES REGISTER END =====
# ===== ALSAAB SMART LINK ROUTES REGISTER START =====
try:
    from smart_link_routes import register_smart_link_routes
except ImportError:
    from backend.smart_link_routes import register_smart_link_routes

register_smart_link_routes(app)
# ===== ALSAAB SMART LINK ROUTES REGISTER END =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)




