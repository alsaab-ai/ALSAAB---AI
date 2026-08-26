# -*- coding: utf-8 -*-
"""
Outbound email.

The system had no way to send mail at all, which is why the login below had to
be built around a link the customer receives. Two transports are supported and
picked by whichever environment variables are present, so the provider can be
chosen later without touching this file:

  RESEND_API_KEY                      -> Resend / any compatible HTTP API
  SMTP_HOST + SMTP_USER + SMTP_PASS   -> plain SMTP (Gmail app password, etc.)

MAIL_FROM sets the visible sender. With neither transport configured send()
returns a "not configured" result instead of raising, so a missing provider
degrades to "the mail did not go out" rather than a 500 on the login page.
"""

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr


def _env(name, default=""):
    return (os.getenv(name) or default).strip()


MAIL_FROM = _env("MAIL_FROM", "ALSAAB AI <no-reply@alsaab.io>")
MAIL_REPLY_TO = _env("MAIL_REPLY_TO")

RESEND_API_KEY = _env("RESEND_API_KEY")
RESEND_ENDPOINT = _env("RESEND_ENDPOINT", "https://api.resend.com/emails")

SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587") or 587)
SMTP_USER = _env("SMTP_USER")
SMTP_PASS = _env("SMTP_PASS")
SMTP_SSL = _env("SMTP_SSL", "off").lower() in ("1", "true", "yes", "on")


def transport():
    """Which transport is configured, without revealing any credential."""
    if RESEND_API_KEY:
        return "resend"

    if SMTP_HOST and SMTP_USER and SMTP_PASS:
        return "smtp"

    return "none"


def _split_from(value):
    """"Name <addr>" -> ("Name", "addr"). Bare addresses come back unnamed."""
    value = (value or "").strip()

    if "<" in value and value.endswith(">"):
        name, address = value.split("<", 1)
        return name.strip().strip('"'), address[:-1].strip()

    return "", value


def _send_resend(to_address, subject, html, text):
    payload = {
        "from": MAIL_FROM,
        "to": [to_address],
        "subject": subject,
        "html": html,
    }

    if text:
        payload["text"] = text

    if MAIL_REPLY_TO:
        payload["reply_to"] = MAIL_REPLY_TO

    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")

        return {"status": "success", "transport": "resend", "detail": body[:200]}

    except urllib.error.HTTPError as error:
        try:
            detail = error.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = str(error)

        return {"status": "error", "transport": "resend",
                "message": f"HTTP {error.code}", "detail": detail}

    except Exception as error:
        return {"status": "error", "transport": "resend",
                "message": f"{type(error).__name__}: {error}"}


def _send_smtp(to_address, subject, html, text):
    name, address = _split_from(MAIL_FROM)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((name, address)) if name else address
    message["To"] = to_address

    if MAIL_REPLY_TO:
        message["Reply-To"] = MAIL_REPLY_TO

    message.set_content(text or "افتح الرابط في نسخة HTML من هذه الرسالة.")
    message.add_alternative(html, subtype="html")

    try:
        if SMTP_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT,
                                  context=ssl.create_default_context(), timeout=20) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(message)

        return {"status": "success", "transport": "smtp"}

    except Exception as error:
        return {"status": "error", "transport": "smtp",
                "message": f"{type(error).__name__}: {error}"}


def send(to_address, subject, html, text=""):
    """Send one message. Never raises."""
    to_address = (to_address or "").strip()

    if not to_address:
        return {"status": "skipped", "message": "no recipient"}

    active = transport()

    if active == "none":
        print("MAIL NOT CONFIGURED - set RESEND_API_KEY or SMTP_HOST/USER/PASS", flush=True)
        return {"status": "skipped", "message": "no transport configured"}

    result = _send_resend(to_address, subject, html, text) if active == "resend" \
        else _send_smtp(to_address, subject, html, text)

    print(f"MAIL {result.get('status')} via {active} -> {to_address[:60]} | {subject[:60]}", flush=True)

    return result


if __name__ == "__main__":
    import sys

    print("transport:", transport())

    if len(sys.argv) > 1:
        print(send(
            sys.argv[1],
            "ALSAAB AI - اختبار الإرسال",
            "<p style='font-family:Cairo,Arial'>تجربة ناجحة.</p>",
            "تجربة ناجحة.",
        ))
