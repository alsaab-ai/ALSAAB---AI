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

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    partner_id = request.args.get("partner_id", "").strip()

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

        ar_url = f"/partner-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang=ar"
        en_url = f"/partner-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang=en"

        language_url = en_url if is_ar else ar_url
        partner_dashboard_url = f"/partner-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={lang}"
        client_dashboard_url = f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={lang}"
        owner_advisory_url = f"/owner-advisory?key={quote(key)}&partner_id={quote(partner_id)}&lang={lang}"

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
    """
    Client Dashboard MVP page.

    Temporary security:
    - Requires ADMIN_KEY for testing.
    - Later this will use logged-in WordPress/user session.
    - Official login should use Partner ID as the main identifier, then resolve client_id internally.
    """
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    partner_id = request.args.get("partner_id", "").strip()

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
            "dashboard_title": "Client Dashboard",
            "intro": "لوحة العميل الخاصة بمشروعك. هنا تتابع باقتك، استخدامك، بيانات مشروعك، وموظف المبيعات الذكي.",
            "back_site": "العودة إلى موقع ALSAAB AI",
            "language": "English",
            "partner_portal": "Partner Dashboard",
            "client_portal": "Client Dashboard",
            "partner_text": "الشراكة، العمولات، المستويات، العملاء، الكورسات، ومتطلبات الترقية.",
            "client_text": "مشروعك، باقتك، استخدامك، بيانات موظف المبيعات الذكي، الصور، والكتالوجات.",
            "client_id": "Client ID",
            "partner_id": "Partner ID",
            "current_package": "الباقة الحالية",
            "subscription_status": "حالة الاشتراك",
            "customer_replies": "ردود العملاء",
            "advisory_replies": "ردود الاستشارات",
            "channels": "القنوات",
            "features": "المزايا",
            "project_data": "بيانات المشروع",
            "image_groups": "صور المنتجات والكتالوجات",
            "payment_links": "روابط الدفع الخاصة",
            "owner_advisory": "استشارات صاحب المشروع",
            "owner_advisory_desc": "من هنا تستخدم ردود الاستشارات الخاصة بك كمشترك. تسأل عن المبيعات، التسويق، تطوير العروض، الاعتراضات، وتحسين أداء مشروعك.",
            "ask_advisor": "فتح الاستشارات الخاصة",
            "image_group_title": "اسم مجموعة الصور",
            "image_group_description": "وصف عام للمجموعة وتعليمات البيع",
            "image_group_notes": "اكتب شرحاً واضحاً عن المنتجات، الأسعار، العروض، متى يرشح موظف المبيعات الذكي كل منتج، وأي ملاحظات مهمة.",
            "upload_images": "رفع صور المنتجات والكتالوجات",
            "upload_note": "رفع الصور والحفظ الفعلي سيتم ربطه في المرحلة القادمة. حالياً هذه واجهة تجهيز.",
            "product_name": "اسم المنتج",
            "payment_link": "رابط الدفع",
            "payment_description": "وصف المنتج أو العرض",
            "add_payment_link": "إضافة رابط دفع",
            "save_image_group": "حفظ مجموعة المنتجات",
            "save_payment_link": "حفظ رابط الدفع",
            "image_urls": "روابط الصور",
            "image_urls_note": "ضع روابط الصور أو روابط الكتالوجات حالياً. رفع الصور كملفات سيتم ربطه في المرحلة القادمة.",
            "saved_success": "تم الحفظ بنجاح.",
            "existing_image_groups": "مجموعات المنتجات المحفوظة",
            "existing_payment_links": "روابط الدفع المحفوظة",
            "payment_note": "العميل يضيف روابط الدفع الخاصة به، وهو يستلم مبالغ عملائه بنفسه. ALSAAB AI لا يستلم مبالغ عملاء العميل.",
            "coming_soon": "قيد التجهيز في المرحلة القادمة",
            "mvp_note": "هذه نسخة MVP مبدئية. لاحقاً سيتم ربطها بتسجيل الدخول الرسمي، واستخدامها لإدارة مشروعك وموظف المبيعات الذكي."
        },
        "en": {
            "page_title": "ALSAAB AI - Client Dashboard",
            "dashboard_title": "Client Dashboard",
            "intro": "Your project dashboard. Track your package, usage, project data, and Smart Sales Employee setup.",
            "back_site": "Back to ALSAAB AI Website",
            "language": "العربية",
            "partner_portal": "Partner Dashboard",
            "client_portal": "Client Dashboard",
            "partner_text": "Partnership, commissions, levels, customers, courses, and upgrade requirements.",
            "client_text": "Your project, package, usage, Smart Sales Employee data, product images, and catalogs.",
            "client_id": "Client ID",
            "partner_id": "Partner ID",
            "current_package": "Current Package",
            "subscription_status": "Subscription Status",
            "customer_replies": "Customer Replies",
            "advisory_replies": "Advisory Replies",
            "channels": "Channels",
            "features": "Features",
            "project_data": "Project Data",
            "image_groups": "Product & Catalog Image Groups",
            "payment_links": "Client Payment Links",
            "owner_advisory": "Owner Advisory",
            "owner_advisory_desc": "Use your private advisory replies to ask about sales, marketing, offers, objections, and improving your business performance.",
            "ask_advisor": "Open Advisory Chat",
            "image_group_title": "Image Group Title",
            "image_group_description": "Group Description & Sales Instructions",
            "image_group_notes": "Describe the products, prices, offers, when the Smart Sales Employee should recommend them, and any important notes.",
            "upload_images": "Upload Product & Catalog Images",
            "upload_note": "Image upload and saving will be connected in the next phase. This is a preparation UI.",
            "product_name": "Product Name",
            "payment_link": "Payment Link",
            "payment_description": "Product or Offer Description",
            "add_payment_link": "Add Payment Link",
            "save_image_group": "Save Product Group",
            "save_payment_link": "Save Payment Link",
            "image_urls": "Image URLs",
            "image_urls_note": "Add image/catalog URLs for now. Real file upload will be connected in the next phase.",
            "saved_success": "Saved successfully.",
            "existing_image_groups": "Saved Product Groups",
            "existing_payment_links": "Saved Payment Links",
            "payment_note": "The client adds their own payment links and receives their customer payments directly. ALSAAB AI does not collect the client's customer payments.",
            "coming_soon": "Coming in the next phase",
            "mvp_note": "This is an early MVP. Later it will be connected to the official login and used to manage your project and Smart Sales Employee."
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
            label="client_dashboard_page"
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

        profile = result.get("partner_profile") or {}
        level = result.get("level") or {}

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

        product_groups = client_dashboard_result.get("product_image_groups") or []
        client_payment_links = client_dashboard_result.get("client_payment_links") or []
        saved_message = request.args.get("saved", "").strip()

        client_id = profile.get("client_id") or partner_id or ""
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

        ar_url = f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang=ar"
        en_url = f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang=en"
        language_url = en_url if is_ar else ar_url

        partner_dashboard_url = f"/partner-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={lang}"
        client_dashboard_url = f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={lang}"

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
      font-size: 24px;
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

    @media (max-width: 900px) {
      .grid, .portal-switch {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .info-row {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 600px) {
      .grid, .portal-switch {
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
          <div class="brand-note">Official account dashboard MVP</div>
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
    <div class="grid">
      <div class="card">
        <h3>{{ "معرف الحساب" if lang == "ar" else "Account ID" }}</h3>
        <div class="big">{{ partner_id }}</div>
        <div class="muted">{{ t.partner_id }}: {{ partner_id }}</div>
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
      <div class="info-row"><div class="label">{{ t.channels }}</div><div class="value">{{ channels | join(", ") if channels else "-" }}</div></div>
      <div class="info-row"><div class="label">{{ t.features }}</div><div class="value">{{ t.coming_soon }}</div></div>
    </div>

    {% if saved_message %}
    <div class="status-message">{{ t.saved_success }}</div>
    {% endif %}

    <div class="section">
      <h2>{{ t.owner_advisory }}</h2>
      <div class="sub">{{ t.owner_advisory_desc }}</div>
      <a class="primary-btn" href="{{ owner_advisory_url }}">{{ t.ask_advisor }}</a>
      <div class="muted">{{ t.coming_soon }}</div>
    </div>

    <div class="section">
      <h2>{{ t.project_data }}</h2>
      <div class="sub">اكتب بيانات مشروعك الأساسية حتى يفهم موظف المبيعات الذكي طبيعة مشروعك.</div>

      <form method="POST" action="/client-dashboard/save-project-data">
        <input type="hidden" name="key" value="{{ key }}">
        <input type="hidden" name="partner_id" value="{{ partner_id }}">
        <input type="hidden" name="client_id" value="{{ client_id }}">
        <input type="hidden" name="lang" value="{{ lang }}">

        <div class="form-grid">
          <div class="field">
            <label>اسم المشروع</label>
            <input type="text" name="business_name" placeholder="مثال: متجر العطور الفاخر">
          </div>

          <div class="field">
            <label>نوع النشاط</label>
            <input type="text" name="business_type" placeholder="مثال: عطور، مطعم، عيادة، عقار">
          </div>

          <div class="field full">
            <label>وصف مبسط للمشروع</label>
            <textarea name="general_description" placeholder="اكتب ماذا يبيع مشروعك، من هو جمهورك، وما أهم مميزاتك."></textarea>
          </div>

          <div class="field full">
            <label>ملاحظات مهمة لموظف المبيعات الذكي</label>
            <textarea name="products" placeholder="اكتب المنتجات أو الخدمات الأساسية، الأسعار العامة، العروض، وطريقة الطلب."></textarea>
          </div>
        </div>

        <button class="primary-btn" type="submit">حفظ بيانات المشروع</button>
      </form>
    </div>

    <div class="section">
      <h2>{{ t.image_groups }}</h2>
      <div class="sub">{{ t.image_group_notes }}</div>

      <form method="POST" action="/client-dashboard/save-image-group" enctype="multipart/form-data">
        <input type="hidden" name="key" value="{{ key }}">
        <input type="hidden" name="partner_id" value="{{ partner_id }}">
        <input type="hidden" name="client_id" value="{{ client_id }}">
        <input type="hidden" name="lang" value="{{ lang }}">

        <div class="form-grid">
          <div class="field">
            <label>{{ t.image_group_title }}</label>
            <input type="text" name="group_title" placeholder="{{ t.image_group_title }}" required>
          </div>

          <div class="field">
            <label>رفع الصور أو الكتالوجات</label>
            <input type="file" name="images" multiple accept="image/*,.pdf">
          </div>

          <div class="field full">
            <label>{{ t.image_group_description }}</label>
            <textarea name="group_description" placeholder="{{ t.image_group_description }}" required></textarea>
          </div>

          <div class="field full">
            <label>{{ t.image_group_notes }}</label>
            <textarea name="sales_instructions" placeholder="{{ t.image_group_notes }}"></textarea>
          </div>
        </div>

        <button class="primary-btn" type="submit">حفظ وإضافة مجموعة منتجات</button>
      </form>

      <div class="upload-box">{{ t.image_urls_note }}</div>

      <div class="small-list">
        <h3 style="color:#d7b85a;">{{ t.existing_image_groups }}</h3>

        {% for group in product_groups[:8] %}
        <div class="small-item">
          <div class="small-item-title">{{ group["Group Title"] or "-" }}</div>
          <div class="muted">{{ group["Group Description"] or "-" }}</div>
          <div class="muted">Status: {{ group["Status"] or "-" }}</div>
        </div>
        {% else %}
        <div class="muted">{{ t.coming_soon }}</div>
        {% endfor %}
      </div>
    </div>

    <div class="section">
      <h2>{{ t.payment_links }}</h2>
      <div class="sub">{{ t.payment_note }}</div>

      <form method="POST" action="/client-dashboard/save-payment-link">
        <input type="hidden" name="key" value="{{ key }}">
        <input type="hidden" name="partner_id" value="{{ partner_id }}">
        <input type="hidden" name="client_id" value="{{ client_id }}">
        <input type="hidden" name="lang" value="{{ lang }}">

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
            <label>Currency</label>
            <input type="text" name="currency" value="AED">
          </div>

          <div class="field full">
            <label>{{ t.payment_description }}</label>
            <textarea name="description" placeholder="{{ t.payment_description }}"></textarea>
          </div>
        </div>

        <button class="primary-btn" type="submit">{{ t.save_payment_link }}</button><div class="muted" style="margin-top:10px;">بعد الحفظ تقدر تضيف رابط دفع إضافي لنفس العميل.</div>
      </form>

      <div class="small-list">
        <h3 style="color:#d7b85a;">{{ t.existing_payment_links }}</h3>

        {% for link in client_payment_links[:8] %}
        <div class="small-item">
          <div class="small-item-title">{{ link["Product Name"] or "-" }}</div>
          <div><a href="{{ link["Payment Link"] }}" target="_blank">{{ link["Payment Link"] }}</a></div>
          <div class="muted">{{ link["Amount"] or "-" }} {{ link["Currency"] or "" }}</div>
          <div class="muted">{{ link["Description"] or "-" }}</div>
        </div>
        {% else %}
        <div class="muted">{{ t.coming_soon }}</div>
        {% endfor %}
      </div>
    </div>
</div>
</body>
</html>
        """

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
            key=key,
            partner_id=partner_id,
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

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    partner_id = request.form.get("partner_id", "").strip()
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

            # Basic safety limit per file for MVP: 5 MB
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
            "image_urls": request.form.get("image_urls", "").strip(),
            "uploaded_files": uploaded_files,
            "notes": "Saved from Client Dashboard MVP with file upload"
        }

        result = post_to_google_sheet_json(payload, label="client_dashboard_save_image_group")
        status = "image_group_saved" if isinstance(result, dict) and result.get("status") == "success" else "image_group_error"

        return redirect(
            f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={quote(lang)}&saved={quote(status)}"
        )

    except Exception as error:
        print(f"CLIENT DASHBOARD SAVE IMAGE GROUP ERROR ❌ {error}", flush=True)

        return redirect(
            f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={quote(lang)}&saved=image_group_error"
        )


@app.route("/client-dashboard/save-payment-link", methods=["POST"])
def client_dashboard_save_payment_link():
    import os
    from urllib.parse import quote

    key = request.form.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    partner_id = request.form.get("partner_id", "").strip()
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
                "notes": "Saved from Client Dashboard MVP"
            }

            result = post_to_google_sheet_json(payload, label="client_dashboard_save_payment_link")

            if isinstance(result, dict) and result.get("status") == "success":
                saved_count += 1

        status = "payment_link_saved" if saved_count > 0 else "payment_link_error"

        return redirect(
            f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={quote(lang)}&saved={quote(status)}"
        )

    except Exception as error:
        print(f"CLIENT DASHBOARD SAVE PAYMENT LINK ERROR ❌ {error}", flush=True)

        return redirect(
            f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={quote(lang)}&saved=payment_link_error"
        )

# ===== ALSAAB_CLIENT_DASHBOARD_SAVE_ROUTES_V1 END =====



# ===== ALSAAB_CLIENT_PROJECT_DATA_AND_ADVISORY_V1 START =====

@app.route("/client-dashboard/save-project-data", methods=["POST"])
def client_dashboard_save_project_data():
    import os
    from urllib.parse import quote

    key = request.form.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    partner_id = request.form.get("partner_id", "").strip()
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
            "notes": "Saved from Client Dashboard project data MVP"
        }

        result = post_to_google_sheet_json(payload, label="client_dashboard_save_project_data")
        status = "project_data_saved" if isinstance(result, dict) and result.get("status") == "success" else "project_data_error"

        return redirect(
            f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={quote(lang)}&saved={quote(status)}"
        )

    except Exception as error:
        print(f"CLIENT DASHBOARD SAVE PROJECT DATA ERROR ❌ {error}", flush=True)

        return redirect(
            f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={quote(lang)}&saved=project_data_error"
        )


@app.route("/owner-advisory", methods=["GET"])
def owner_advisory_view():
    from urllib.parse import quote

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    partner_id = request.args.get("partner_id", "").strip()
    lang = request.args.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    if not partner_id:
        return "partner_id is required", 400

    direction = "rtl" if lang == "ar" else "ltr"

    title = "استشارات صاحب المشروع" if lang == "ar" else "Owner Advisory"
    subtitle = (
        "هذه صفحة الاستشارات الخاصة المرتبطة بمعرف حسابك. سيتم ربط المحادثة الذكية المستمرة في المرحلة القادمة."
        if lang == "ar"
        else "This advisory page is tied to your account ID. Persistent smart advisory chat will be connected in the next phase."
    )

    back_url = f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={quote(lang)}"

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
            a { color:#f0cc68; text-decoration:none; display:inline-block; margin-top:18px; border:1px solid rgba(215,184,90,.45); padding:10px 14px; border-radius:999px; }
          </style>
        </head>
        <body>
          <div class="page">
            <div class="card">
              <h1>{{ title }}</h1>
              <div class="sub">{{ subtitle }}</div>
              <div class="sub" style="margin-top:12px;">Partner ID: {{ partner_id }}</div>
              <a href="{{ back_url }}">العودة إلى Client Dashboard</a>
            </div>
          </div>
        </body>
        </html>
        """,
        lang=lang,
        direction=direction,
        title=title,
        subtitle=subtitle,
        partner_id=partner_id,
        back_url=back_url
    )

# ===== ALSAAB_CLIENT_PROJECT_DATA_AND_ADVISORY_V1 END =====


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)