print("ALSAAB AI is running 🔥")

from flask import Flask, request, jsonify, render_template_string, redirect
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
    cursor: not-allowed;
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
        print("STRIPE INVOICE PAID ✅ received for future renewal handling", flush=True)

        return jsonify({
            "status": "received",
            "message": "invoice.paid received"
        })

    if event_type == "invoice.payment_failed":
        print("STRIPE INVOICE PAYMENT FAILED ⚠️ received for future handling", flush=True)

        return jsonify({
            "status": "received",
            "message": "invoice.payment_failed received"
        })

    if event_type == "customer.subscription.deleted":
        print("STRIPE SUBSCRIPTION DELETED ⚠️ received for future cancellation handling", flush=True)

        return jsonify({
            "status": "received",
            "message": "customer.subscription.deleted received"
        })

    if event_type == "customer.subscription.updated":
        print("STRIPE SUBSCRIPTION UPDATED ✅ received for future handling", flush=True)

        return jsonify({
            "status": "received",
            "message": "customer.subscription.updated received"
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
                "package_amount": "799 AED",
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)