# database.py

import re
import sqlite3
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from uuid import uuid4

try:
    from config import GOOGLE_SHEET_WEBHOOK_URL, GOOGLE_SHEET_TOKEN
except Exception:
    GOOGLE_SHEET_WEBHOOK_URL = ""
    GOOGLE_SHEET_TOKEN = ""

try:
    from config import COMPANY_OWNER_PARTNER_ID
except Exception:
    COMPANY_OWNER_PARTNER_ID = "alsaab"

try:
    from config import PACKAGES, USAGE_LIMIT_MESSAGES
except Exception:
    PACKAGES = {
        "starter": {"monthly_reply_limit": 2000},
        "growth": {"monthly_reply_limit": 6000},
        "elite": {"monthly_reply_limit": 15000},
    }

    USAGE_LIMIT_MESSAGES = {
        "ar": (
            "تم استهلاك باقتك الحالية لهذا الشهر ✅\n\n"
            "لإكمال استخدام ALSAAB AI، تقدر ترقّي باقتك أو تنتظر تجديد الدورة الشهرية."
        )
    }


DB_NAME = "alsaab_ai.db"

# ===== ALSAAB POSTGRES BACKEND V1 START =====
# db.get_connection() returns a pooled PostgreSQL connection when DATABASE_URL
# is set, and falls back to sqlite3.connect(DB_NAME) when it is not — so this
# is a no-op until the environment variable exists.
import os as _os

# Import db FIRST: it reads the local .env into os.environ, and _DATA_BACKEND
# below is computed from those variables. Importing it lazily instead would
# leave DATA_BACKEND stuck on its default during local runs.
try:
    import db as _db_module
except ImportError:
    from backend import db as _db_module

_DATA_BACKEND = _os.getenv(
    "DATA_BACKEND",
    "postgres" if _os.getenv("DATABASE_URL", "").strip() else "sheets",
).lower().strip()


def get_connection():
    return _db_module.get_connection()
# ===== ALSAAB POSTGRES BACKEND V1 END =====


def current_timestamp():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def next_month_timestamp():
    return (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")


def parse_timestamp(value):
    """
    Always returns a NAIVE UTC datetime, whatever the input.

    PostgreSQL TIMESTAMPTZ columns come back timezone-aware, while the code
    compares them against datetime.utcnow(), which is naive. Mixing the two
    raises:

        TypeError: can't compare offset-naive and offset-aware datetimes

    Under SQLite every timestamp was a plain string, so this never came up.
    Converting to UTC and dropping tzinfo here keeps every existing comparison
    valid without touching the call sites.
    """
    if not value:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except Exception:
            return None


def add_column_if_missing(cursor, table_name, column_name, column_definition):
    """
    يضيف عمود جديد للجدول إذا ما كان موجود.
    هذا مهم لأن عندنا قاعدة بيانات قديمة فيها جدول leads بدون الأعمدة الجديدة.
    """
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]

    if column_name not in columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        client_id TEXT,
        source_partner_id TEXT,
        referral_saved_at TIMESTAMP,
        name TEXT,
        phone TEXT,
        user_type TEXT,
        business_name TEXT,
        business_type TEXT,
        pain_point TEXT,
        channel TEXT,
        status TEXT DEFAULT 'new',
        email TEXT,
        country TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    add_column_if_missing(c, "leads", "client_id", "TEXT")
    add_column_if_missing(c, "leads", "source_partner_id", "TEXT")
    add_column_if_missing(c, "leads", "referral_saved_at", "TIMESTAMP")
    add_column_if_missing(c, "leads", "user_type", "TEXT")
    add_column_if_missing(c, "leads", "business_name", "TEXT")
    add_column_if_missing(c, "leads", "email", "TEXT")
    add_column_if_missing(c, "leads", "country", "TEXT")

    c.execute("""
    CREATE TABLE IF NOT EXISTS client_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE,
        client_id TEXT,
        business_name TEXT,
        business_type TEXT,
        general_description TEXT,
        products TEXT,
        prices TEXT,
        offers TEXT,
        ordering TEXT,
        whatsapp TEXT,
        areas TEXT,
        faqs TEXT,
        objections TEXT,
        tone TEXT,
        raw_data TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    add_column_if_missing(c, "client_profiles", "client_id", "TEXT")
    add_column_if_missing(c, "client_profiles", "general_description", "TEXT")

    c.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE,
        client_id TEXT,
        bot_id TEXT,
        source_partner_id TEXT,
        plan_name TEXT,
        monthly_reply_limit INTEGER,
        monthly_replies_used INTEGER DEFAULT 0,
        subscription_status TEXT DEFAULT 'inactive',
        billing_cycle_start TIMESTAMP,
        billing_cycle_end TIMESTAMP,
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        package_amount TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    add_column_if_missing(c, "subscriptions", "client_id", "TEXT")
    add_column_if_missing(c, "subscriptions", "bot_id", "TEXT")
    add_column_if_missing(c, "subscriptions", "source_partner_id", "TEXT")
    add_column_if_missing(c, "subscriptions", "plan_name", "TEXT")
    add_column_if_missing(c, "subscriptions", "monthly_reply_limit", "INTEGER")
    add_column_if_missing(c, "subscriptions", "monthly_replies_used", "INTEGER DEFAULT 0")
    add_column_if_missing(c, "subscriptions", "owner_advisory_replies_used", "INTEGER DEFAULT 0")
    add_column_if_missing(c, "subscriptions", "subscription_status", "TEXT DEFAULT 'inactive'")
    add_column_if_missing(c, "subscriptions", "billing_cycle_start", "TIMESTAMP")
    add_column_if_missing(c, "subscriptions", "billing_cycle_end", "TIMESTAMP")
    add_column_if_missing(c, "subscriptions", "stripe_customer_id", "TEXT")
    add_column_if_missing(c, "subscriptions", "stripe_subscription_id", "TEXT")
    add_column_if_missing(c, "subscriptions", "package_amount", "TEXT")
    add_column_if_missing(c, "subscriptions", "notes", "TEXT")
    add_column_if_missing(c, "subscriptions", "created_at", "TIMESTAMP")
    add_column_if_missing(c, "subscriptions", "updated_at", "TIMESTAMP")

    c.execute("""
    CREATE TABLE IF NOT EXISTS usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        client_id TEXT,
        bot_id TEXT,
        plan_name TEXT,
        usage_type TEXT DEFAULT 'bot_reply',
        message_role TEXT DEFAULT 'bot',
        replies_count INTEGER DEFAULT 1,
        tokens_estimate INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    add_column_if_missing(c, "usage_logs", "client_id", "TEXT")
    add_column_if_missing(c, "usage_logs", "bot_id", "TEXT")
    add_column_if_missing(c, "usage_logs", "plan_name", "TEXT")
    add_column_if_missing(c, "usage_logs", "usage_type", "TEXT DEFAULT 'bot_reply'")
    add_column_if_missing(c, "usage_logs", "message_role", "TEXT DEFAULT 'bot'")
    add_column_if_missing(c, "usage_logs", "replies_count", "INTEGER DEFAULT 1")
    add_column_if_missing(c, "usage_logs", "tokens_estimate", "INTEGER DEFAULT 0")

    conn.commit()
    conn.close()

    print("DATABASE INIT DONE ✅", flush=True)


def save_message(session_id, role, content):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content)
    )

    conn.commit()
    conn.close()


def get_last_messages(session_id, limit=6):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, limit)
    )

    rows = c.fetchall()
    conn.close()

    return list(reversed(rows))


def get_state_value(state, key, default=""):
    if not state:
        return default

    value = state.get(key)

    if value:
        return value

    client_data = state.get("client_data", {})

    if isinstance(client_data, dict):
        return client_data.get(key, default)

    return default


def normalize_user_type(state):
    raw_user_type = get_state_value(state, "user_type", "")

    if not raw_user_type:
        return ""

    raw_user_type = str(raw_user_type).lower().strip()

    if raw_user_type == "business":
        return "Business"

    if raw_user_type in ["mlm", "personal"]:
        return "Personal"

    if raw_user_type == "unknown":
        return "Unknown"

    return raw_user_type


def get_effective_client_id(session_id, client_id="", state=None):
    """
    يرجع client_id ثابت للعميل.
    الأولوية:
    1. client_id المرسل صراحة
    2. client_id داخل state
    3. client_id داخل الاشتراك
    4. session_id كحل مؤقت
    """
    if client_id:
        return str(client_id).strip()

    if state:
        state_client_id = get_state_value(state, "client_id", "")
        if state_client_id:
            return str(state_client_id).strip()

    try:
        subscription = get_client_subscription(session_id)
        if subscription and subscription.get("client_id"):
            return str(subscription.get("client_id")).strip()
    except Exception:
        pass

    return session_id or ""


def normalize_partner_id(partner_id):
    if not partner_id:
        return ""

    partner_id = str(partner_id).strip()

    if not partner_id:
        return ""

    if partner_id.lower() == str(COMPANY_OWNER_PARTNER_ID).lower():
        return COMPANY_OWNER_PARTNER_ID

    if partner_id.lower().startswith("als-p"):
        return partner_id.upper()

    return partner_id


def get_source_partner_id_from_state(state):
    source_partner_id = (
        get_state_value(state, "source_partner_id", "")
        or get_state_value(state, "referrer_partner_id", "")
        or get_state_value(state, "ref", "")
        or ""
    )

    return normalize_partner_id(source_partner_id)


def get_source_partner_id_for_session(session_id):
    """
    يرجع source_partner_id المرتبط بالجلسة.
    الأولوية:
    1. subscriptions
    2. leads
    """
    if not session_id:
        return ""

    conn = get_connection()
    c = conn.cursor()

    try:
        c.execute(
            """
            SELECT source_partner_id
            FROM subscriptions
            WHERE session_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id,)
        )
        row = c.fetchone()

        if row and row[0]:
            conn.close()
            return normalize_partner_id(row[0])

        c.execute(
            """
            SELECT source_partner_id
            FROM leads
            WHERE session_id=? AND source_partner_id IS NOT NULL AND source_partner_id != ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id,)
        )
        row = c.fetchone()

        if row and row[0]:
            conn.close()
            return normalize_partner_id(row[0])

    except Exception as error:
        print(f"GET SOURCE PARTNER ERROR ❌ {error}", flush=True)

    conn.close()
    return ""


def normalize_partner_rank(rank_value):
    if not rank_value:
        return "Level 1"

    rank_value = str(rank_value).strip()

    aliases = {
        "1": "Level 1",
        "level 1": "Level 1",
        "entry": "Level 1",
        "entry partner": "Level 1",
        "starter": "Level 2",
        "starter partner": "Level 2",
        "المستوى الأول": "Level 1",

        "2": "Level 2",
        "level 2": "Level 2",
        "growth": "Level 3",
        "growth partner": "Level 3",
        "المستوى الثاني": "Level 2",

        "3": "Level 3",
        "level 3": "Level 3",
        "sales": "Level 3",
        "sales partner": "Level 3",
        "المستوى الثالث": "Level 3",

        "4": "Level 4",
        "level 4": "Level 4",
        "leader": "Level 4",
        "leader partner": "Level 4",
        "المستوى الرابع": "Level 4",

        "5": "Level 5",
        "level 5": "Level 5",
        "elite": "Level 4",
        "diamond": "Level 5",
        "diamond partner": "Level 5",
        "elite partner": "Level 4",
        "المستوى الخامس": "Level 5",
    }

    normalized_key = rank_value.lower()
    return aliases.get(normalized_key, rank_value)


def get_default_commission_percent_for_rank(rank_value):
    rank = normalize_partner_rank(rank_value).lower()

    if rank == "level 1":
        return "25"

    if rank == "level 2":
        return "5"

    if rank == "level 3":
        return "4"

    if rank == "level 4":
        return "3"

    if rank == "level 5":
        return "2"

    return "25"


def generate_commission_id():
    return f"COM-{uuid4()}"


def post_to_google_sheet(payload, label="unknown"):
    """
    يرسل Payload إلى Google Apps Script ويطبع الرد كامل في Render Logs.
    """
    print(f"GOOGLE SHEET SEND START ✅ label={label}", flush=True)

    if not GOOGLE_SHEET_WEBHOOK_URL:
        print("GOOGLE SHEET ERROR ❌ GOOGLE_SHEET_WEBHOOK_URL is empty", flush=True)
        return False

    if not GOOGLE_SHEET_TOKEN:
        print("GOOGLE SHEET ERROR ❌ GOOGLE_SHEET_TOKEN is empty", flush=True)
        return False

    print(f"GOOGLE SHEET URL EXISTS ✅ startswith={GOOGLE_SHEET_WEBHOOK_URL[:35]}", flush=True)
    print(f"GOOGLE SHEET PAYLOAD ACTION ✅ action={payload.get('action')}", flush=True)

    try:
        data_encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(
            GOOGLE_SHEET_WEBHOOK_URL,
            data=data_encoded,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            status_code = response.getcode()
            response_body = response.read().decode("utf-8", errors="replace")

        print(f"GOOGLE SHEET RESPONSE STATUS ✅ {status_code}", flush=True)
        print(f"GOOGLE SHEET RESPONSE BODY ✅ {response_body}", flush=True)

        try:
            response_json = json.loads(response_body)
            if response_json.get("status") == "success":
                print("GOOGLE SHEET SAVE SUCCESS ✅", flush=True)
                return True

            print(f"GOOGLE SHEET SAVE NOT SUCCESS ❌ {response_json}", flush=True)
            return False

        except Exception:
            print("GOOGLE SHEET RESPONSE NOT JSON ⚠️", flush=True)
            return status_code in [200, 201, 202]

    except urllib.error.HTTPError as error:
        try:
            error_body = error.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""

        print(f"GOOGLE SHEET HTTP ERROR ❌ code={error.code}", flush=True)
        print(f"GOOGLE SHEET HTTP ERROR BODY ❌ {error_body}", flush=True)
        return False

    except Exception as error:
        print(f"GOOGLE SHEET REQUEST ERROR ❌ {error}", flush=True)
        return False


def post_to_google_sheet_json(payload, label="unknown"):
    """
    نفس فكرة post_to_google_sheet، لكن يرجع JSON كامل.
    نحتاجه في MLM عشان نستلم partner_id و referral_link من Google Apps Script.

    ALSAAB POSTGRES BACKEND V1:
    عندما DATA_BACKEND != "sheets" يتم توجيه الطلب إلى sheet_compat الذي يرد
    من PostgreSQL بنفس شكل JSON. أي action لم يُنقل بعد يرجع تلقائياً إلى
    Google Apps Script عبر _post_to_google_sheet_json_real أدناه.
    """
    if _DATA_BACKEND != "sheets":
        try:
            from sheet_compat import handle as _compat_handle
        except ImportError:
            from backend.sheet_compat import handle as _compat_handle

        return _compat_handle(payload, label=label)

    return _post_to_google_sheet_json_real(payload, label=label)


def _post_to_google_sheet_json_real(payload, label="unknown"):
    """The original Google Apps Script call. Kept as the fallback path."""
    print(f"GOOGLE SHEET JSON SEND START ✅ label={label}", flush=True)

    if not GOOGLE_SHEET_WEBHOOK_URL:
        print("GOOGLE SHEET JSON ERROR ❌ GOOGLE_SHEET_WEBHOOK_URL is empty", flush=True)
        return {
            "status": "error",
            "message": "GOOGLE_SHEET_WEBHOOK_URL is empty"
        }

    if not GOOGLE_SHEET_TOKEN:
        print("GOOGLE SHEET JSON ERROR ❌ GOOGLE_SHEET_TOKEN is empty", flush=True)
        return {
            "status": "error",
            "message": "GOOGLE_SHEET_TOKEN is empty"
        }

    print(f"GOOGLE SHEET JSON PAYLOAD ACTION ✅ action={payload.get('action')}", flush=True)

    try:
        data_encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(
            GOOGLE_SHEET_WEBHOOK_URL,
            data=data_encoded,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            status_code = response.getcode()
            response_body = response.read().decode("utf-8", errors="replace")

        print(f"GOOGLE SHEET JSON RESPONSE STATUS ✅ {status_code}", flush=True)
        print(f"GOOGLE SHEET JSON RESPONSE BODY ✅ {response_body}", flush=True)

        try:
            response_json = json.loads(response_body)

            if response_json.get("status") == "success":
                print(f"GOOGLE SHEET JSON SAVE SUCCESS ✅ label={label}", flush=True)
            else:
                print(f"GOOGLE SHEET JSON SAVE NOT SUCCESS ❌ {response_json}", flush=True)

            return response_json

        except Exception:
            print("GOOGLE SHEET JSON RESPONSE NOT JSON ⚠️", flush=True)

            return {
                "status": "success" if status_code in [200, 201, 202] else "error",
                "message": "Response was not JSON",
                "status_code": status_code,
                "raw_response": response_body
            }

    except urllib.error.HTTPError as error:
        try:
            error_body = error.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""

        print(f"GOOGLE SHEET JSON HTTP ERROR ❌ code={error.code}", flush=True)
        print(f"GOOGLE SHEET JSON HTTP ERROR BODY ❌ {error_body}", flush=True)

        return {
            "status": "error",
            "message": "HTTP error",
            "code": error.code,
            "body": error_body
        }

    except Exception as error:
        print(f"GOOGLE SHEET JSON REQUEST ERROR ❌ {error}", flush=True)

        return {
            "status": "error",
            "message": str(error)
        }


def send_lead_to_google_sheet(session_id, name, phone, state, status="new"):
    client_id = get_effective_client_id(session_id, state=state)
    source_partner_id = get_source_partner_id_from_state(state)

    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "lead",
        "client_id": client_id or "",
        "source_partner_id": source_partner_id or "",
        "name": name or "",
        "phone": phone or "",
        "user_type": normalize_user_type(state),
        "business_name": get_state_value(state, "business_name", ""),
        "business_type": get_state_value(state, "business_type", ""),
        "pain_point": get_state_value(state, "pain_point", ""),
        "channel": get_state_value(state, "channel", "website"),
        "status": status or "new",
        "email": get_state_value(state, "email", "") or get_state_value(state, "lead_email", ""),
        "country": get_state_value(state, "country", ""),
        "session_id": session_id or "",
    }

    return post_to_google_sheet(payload, label="lead")


def send_client_profile_to_google_sheet(session_id, data, client_id=""):
    effective_client_id = get_effective_client_id(
        session_id,
        client_id=client_id or data.get("client_id", "")
    )

    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "client_profile",
        "session_id": session_id or "",
        "client_id": effective_client_id or "",
        "business_name": data.get("business_name", ""),
        "business_type": data.get("business_type", ""),
        "general_description": data.get("general_description", ""),
        "products": data.get("products", ""),
        "prices": data.get("prices", ""),
        "offers": data.get("offers", ""),
        "ordering": data.get("ordering", ""),
        "whatsapp": data.get("whatsapp", ""),
        "areas": data.get("areas", ""),
        "faqs": data.get("faqs", ""),
        "objections": data.get("objections", ""),
        "tone": data.get("tone", ""),
    }

    return post_to_google_sheet(payload, label="client_profile")


def mark_referral_saved_for_lead(lead_id):
    if not lead_id:
        return False

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        UPDATE leads
        SET referral_saved_at=?
        WHERE id=?
        """,
        (current_timestamp(), lead_id)
    )

    conn.commit()
    conn.close()

    return True


def send_referral_for_lead_if_needed(
    lead_id,
    session_id,
    client_id,
    name,
    phone,
    state,
    source_partner_id,
    referral_saved_at=""
):
    if not source_partner_id:
        print("REFERRAL NOT SAVED ⚠️ no source_partner_id", flush=True)
        return False

    if referral_saved_at:
        print("REFERRAL ALREADY SAVED ✅ skipping duplicate", flush=True)
        return False

    email = get_state_value(state, "email", "") or get_state_value(state, "lead_email", "")
    channel = get_state_value(state, "channel", "website")
    package_name = (
        get_state_value(state, "plan_name", "")
        or get_state_value(state, "package_name", "")
        or get_state_value(state, "selected_package", "")
    )

    notes = (
        "source=lead_capture_referral_tracking; "
        f"lead_id={lead_id}; "
        f"session_id={session_id}"
    )

    result = send_referral_to_google_sheet(
        source_partner_id=source_partner_id,
        partner_id=source_partner_id,
        referral_name=name,
        referral_phone=phone,
        referral_email=email,
        source=channel,
        package_name=package_name,
        payment_status="pending",
        subscription_status="pending",
        session_id=session_id,
        client_id=client_id,
        notes=notes
    )

    if result.get("status") == "success":
        mark_referral_saved_for_lead(lead_id)
        print(
            f"REFERRAL SAVED ✅ source_partner_id={source_partner_id} lead_id={lead_id}",
            flush=True
        )
        return True

    print(f"REFERRAL SAVE FAILED ❌ {result}", flush=True)
    return False


def save_lead(session_id, name, phone, state):
    conn = get_connection()
    c = conn.cursor()

    client_id = get_effective_client_id(session_id, state=state)
    source_partner_id = get_source_partner_id_from_state(state)
    user_type = normalize_user_type(state)
    business_name = get_state_value(state, "business_name", "")
    business_type = get_state_value(state, "business_type", "")
    pain_point = get_state_value(state, "pain_point", "")
    channel = get_state_value(state, "channel", "website")
    email = get_state_value(state, "email", "") or get_state_value(state, "lead_email", "")
    country = get_state_value(state, "country", "")

    c.execute(
        """
        SELECT
            id,
            source_partner_id,
            referral_saved_at
        FROM leads
        WHERE session_id=? AND phone=?
        """,
        (session_id, phone)
    )
    existing = c.fetchone()

    is_new_lead = False
    lead_id = None
    referral_saved_at = ""

    if existing:
        lead_id = existing[0]
        existing_source_partner_id = existing[1] or ""
        referral_saved_at = existing[2] or ""

        final_source_partner_id = source_partner_id or existing_source_partner_id

        c.execute(
            """
            UPDATE leads
            SET
                client_id=?,
                source_partner_id=?,
                name=?,
                user_type=?,
                business_name=?,
                business_type=?,
                pain_point=?,
                channel=?,
                email=?,
                country=?
            WHERE id=?
            """,
            (
                client_id,
                final_source_partner_id,
                name,
                user_type,
                business_name,
                business_type,
                pain_point,
                channel,
                email,
                country,
                lead_id
            )
        )

        source_partner_id = final_source_partner_id
    else:
        c.execute(
            """
            INSERT INTO leads (
                session_id,
                client_id,
                source_partner_id,
                name,
                phone,
                user_type,
                business_name,
                business_type,
                pain_point,
                channel,
                email,
                country
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                client_id,
                source_partner_id,
                name,
                phone,
                user_type,
                business_name,
                business_type,
                pain_point,
                channel,
                email,
                country
            )
        )

        lead_id = c.lastrowid
        is_new_lead = True

    conn.commit()
    conn.close()

    print("LEAD SAVED TO SQLITE ✅", flush=True)

    if is_new_lead:
        send_lead_to_google_sheet(
            session_id=session_id,
            name=name,
            phone=phone,
            state=state,
            status="new"
        )

    send_referral_for_lead_if_needed(
        lead_id=lead_id,
        session_id=session_id,
        client_id=client_id,
        name=name,
        phone=phone,
        state=state,
        source_partner_id=source_partner_id,
        referral_saved_at=referral_saved_at
    )


def get_leads(limit=100):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            id,
            session_id,
            client_id,
            source_partner_id,
            referral_saved_at,
            name,
            phone,
            user_type,
            business_name,
            business_type,
            pain_point,
            channel,
            status,
            email,
            country,
            created_at
        FROM leads
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows = c.fetchall()
    conn.close()

    leads = []

    for row in rows:
        leads.append({
            "id": row[0],
            "session_id": row[1],
            "client_id": row[2],
            "source_partner_id": row[3],
            "referral_saved_at": row[4],
            "name": row[5],
            "phone": row[6],
            "user_type": row[7],
            "business_name": row[8],
            "business_type": row[9],
            "pain_point": row[10],
            "channel": row[11],
            "status": row[12],
            "email": row[13],
            "country": row[14],
            "created_at": row[15],
        })

    return leads


def save_client_profile(session_id, data, client_id=""):
    print("SAVE CLIENT PROFILE START ✅", flush=True)
    print(f"SAVE CLIENT PROFILE SESSION ✅ {session_id}", flush=True)
    print(f"SAVE CLIENT PROFILE DATA KEYS ✅ {list(data.keys())}", flush=True)

    effective_client_id = get_effective_client_id(
        session_id,
        client_id=client_id or data.get("client_id", "")
    )

    data["client_id"] = effective_client_id

    conn = get_connection()
    c = conn.cursor()

    raw_data = json.dumps(data, ensure_ascii=False)

    c.execute(
        """
        SELECT id FROM client_profiles
        WHERE client_id=? OR session_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (effective_client_id, session_id)
    )
    existing = c.fetchone()

    values = (
        session_id,
        effective_client_id,
        data.get("business_name"),
        data.get("business_type"),
        data.get("general_description"),
        data.get("products"),
        data.get("prices"),
        data.get("offers"),
        data.get("ordering"),
        data.get("whatsapp"),
        data.get("areas"),
        data.get("faqs"),
        data.get("objections"),
        data.get("tone"),
        raw_data,
    )

    if existing:
        print("CLIENT PROFILE EXISTS ✅ updating SQLite", flush=True)

        c.execute(
            """
            UPDATE client_profiles
            SET
                session_id=?,
                client_id=?,
                business_name=?,
                business_type=?,
                general_description=?,
                products=?,
                prices=?,
                offers=?,
                ordering=?,
                whatsapp=?,
                areas=?,
                faqs=?,
                objections=?,
                tone=?,
                raw_data=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            values + (existing[0],)
        )
    else:
        print("CLIENT PROFILE NEW ✅ inserting SQLite", flush=True)

        c.execute(
            """
            INSERT INTO client_profiles (
                session_id,
                client_id,
                business_name,
                business_type,
                general_description,
                products,
                prices,
                offers,
                ordering,
                whatsapp,
                areas,
                faqs,
                objections,
                tone,
                raw_data
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values
        )

    conn.commit()
    conn.close()

    print(f"CLIENT PROFILE SAVED TO SQLITE ✅ client_id={effective_client_id}", flush=True)

    sheet_result = send_client_profile_to_google_sheet(
        session_id=session_id,
        data=data,
        client_id=effective_client_id
    )

    if sheet_result:
        print("CLIENT PROFILE SENT TO GOOGLE SHEET ✅", flush=True)
    else:
        print("CLIENT PROFILE GOOGLE SHEET SEND FAILED ❌", flush=True)


def get_client_profile(session_id, client_id=""):
    effective_client_id = get_effective_client_id(session_id, client_id=client_id)

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            client_id,
            business_name,
            business_type,
            general_description,
            products,
            prices,
            offers,
            ordering,
            whatsapp,
            areas,
            faqs,
            objections,
            tone,
            raw_data
        FROM client_profiles
        WHERE client_id=? OR session_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (effective_client_id, session_id)
    )

    row = c.fetchone()
    conn.close()

    if not row:
        return {}

    return {
        "client_id": row[0],
        "business_name": row[1],
        "business_type": row[2],
        "general_description": row[3],
        "products": row[4],
        "prices": row[5],
        "offers": row[6],
        "ordering": row[7],
        "whatsapp": row[8],
        "areas": row[9],
        "faqs": row[10],
        "objections": row[11],
        "tone": row[12],
        "raw_data": row[13],
    }


def get_client_profiles(limit=100):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            id,
            session_id,
            client_id,
            business_name,
            business_type,
            general_description,
            products,
            prices,
            offers,
            ordering,
            whatsapp,
            areas,
            faqs,
            objections,
            tone,
            updated_at
        FROM client_profiles
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows = c.fetchall()
    conn.close()

    profiles = []

    for row in rows:
        profiles.append({
            "id": row[0],
            "session_id": row[1],
            "client_id": row[2],
            "business_name": row[3],
            "business_type": row[4],
            "general_description": row[5],
            "products": row[6],
            "prices": row[7],
            "offers": row[8],
            "ordering": row[9],
            "whatsapp": row[10],
            "areas": row[11],
            "faqs": row[12],
            "objections": row[13],
            "tone": row[14],
            "updated_at": row[15],
        })

    return profiles


# =========================
# SUBSCRIPTION / USAGE SYSTEM
# =========================

def normalize_plan_name(plan_name):
    if not plan_name:
        return ""

    plan_name = str(plan_name).lower().strip()

    aliases = {
        "start": "starter",
        "basic": "starter",
        "beginner": "starter",
        "بداية": "starter",
        "البداية": "starter",
        "starter": "starter",

        "growth": "growth",
        "pro": "growth",
        "professional": "growth",
        "نمو": "growth",
        "النمو": "growth",

        "elite": "elite",
        "premium": "elite",
        "vip": "elite",
        "نخبة": "elite",
        "النخبة": "elite",

        "enterprise": "enterprise",
        "custom": "enterprise",
        "شركة": "enterprise",
        "شركات": "enterprise",
    }

    return aliases.get(plan_name, plan_name)


def get_plan_reply_limit(plan_name, custom_reply_limit=None):
    if custom_reply_limit not in (None, "", 0, "0"):
        try:
            return int(custom_reply_limit)
        except Exception:
            pass

    plan = normalize_plan_name(plan_name)

    try:
        from config import PACKAGES

        package = PACKAGES.get(plan) or {}
        limit = (
            package.get("customer_reply_limit")
            or package.get("total_customer_reply_limit")
            or package.get("monthly_reply_limit")
        )

        if str(limit).lower() == "custom":
            return 0

        if limit not in (None, ""):
            return int(limit)

    except Exception as error:
        print(f"GET PLAN REPLY LIMIT CONFIG ERROR ⚠️ {error}", flush=True)

    if plan == "starter":
        return 2000

    if plan == "growth":
        return 6000

    if plan == "elite":
        return 15000

    return 6000


def get_plan_owner_advisory_reply_limit(plan_name):
    plan = normalize_plan_name(plan_name)

    try:
        from config import PACKAGES

        package = PACKAGES.get(plan) or {}
        limit = package.get("owner_advisory_reply_limit") or 0
        return int(limit)

    except Exception as error:
        print(f"GET PLAN OWNER ADVISORY LIMIT ERROR ⚠️ {error}", flush=True)

    if plan == "growth":
        return 1000

    if plan == "elite":
        return 2000

    return 0


def get_plan_package_features(plan_name):
    plan = normalize_plan_name(plan_name)

    try:
        from config import PACKAGES

        package = PACKAGES.get(plan) or {}

        return {
            "plan_name": plan,
            "customer_reply_limit": int(package.get("customer_reply_limit") or package.get("monthly_reply_limit") or 0),
            "base_customer_reply_limit": int(package.get("base_customer_reply_limit") or package.get("customer_reply_limit") or package.get("monthly_reply_limit") or 0),
            "gift_reply_limit": int(package.get("gift_reply_limit") or 0),
            "total_customer_reply_limit": int(package.get("total_customer_reply_limit") or package.get("customer_reply_limit") or package.get("monthly_reply_limit") or 0),
            "owner_advisory_reply_limit": int(package.get("owner_advisory_reply_limit") or 0),
            "channels": package.get("channels") or [],
            "whatsapp_included": bool(package.get("whatsapp_included")),
            "website_included": bool(package.get("website_included")),
            "instagram_included": bool(package.get("instagram_included")),
            "dashboard_advisory_enabled": bool(package.get("dashboard_advisory_enabled")),
            "image_catalog_enabled": bool(package.get("image_catalog_enabled")),
            "client_payment_links_enabled": bool(package.get("client_payment_links_enabled")),
            "advisor_level": package.get("advisor_level") or "",
        }

    except Exception as error:
        print(f"GET PLAN PACKAGE FEATURES ERROR ⚠️ {error}", flush=True)

    return {
        "plan_name": plan,
        "customer_reply_limit": get_plan_reply_limit(plan),
        "base_customer_reply_limit": get_plan_reply_limit(plan),
        "gift_reply_limit": 0,
        "total_customer_reply_limit": get_plan_reply_limit(plan),
        "owner_advisory_reply_limit": get_plan_owner_advisory_reply_limit(plan),
        "channels": [],
        "whatsapp_included": False,
        "website_included": False,
        "instagram_included": False,
        "dashboard_advisory_enabled": False,
        "image_catalog_enabled": False,
        "client_payment_links_enabled": False,
        "advisor_level": "",
    }


def get_usage_limit_message(reason="limit_reached", subscription=None):
    if reason == "no_subscription":
        return (
            "لا يوجد اشتراك فعال مرتبط بهذه الجلسة حالياً.\n\n"
            "للاستمرار في استخدام ALSAAB AI، لازم يتم تفعيل اشتراكك أولاً أو اختيار إحدى الباقات."
        )

    if reason == "inactive_subscription":
        return (
            "اشتراكك غير فعال حالياً.\n\n"
            "للاستمرار في استخدام ALSAAB AI، يرجى تفعيل الاشتراك أو تجديد الباقة."
        )

    if reason == "cancelled_subscription":
        return (
            "اشتراكك ملغي حالياً.\n\n"
            "لإعادة استخدام ALSAAB AI، يرجى تفعيل اشتراك جديد."
        )

    if reason == "limit_reached":
        return USAGE_LIMIT_MESSAGES.get(
            "ar",
            (
                "تم استهلاك باقتك الحالية لهذا الشهر ✅\n\n"
                "لإكمال استخدام ALSAAB AI، تقدر ترقّي باقتك أو تنتظر تجديد الدورة الشهرية."
            )
        )

    return (
        "لا يمكن استخدام ALSAAB AI حالياً.\n\n"
        "يرجى مراجعة حالة الاشتراك أو ترقية الباقة."
    )


OWNER_ADVISORY_SESSION_PREFIX = "owner_advisory_"


def is_owner_advisory_session(session_id):
    return str(session_id or "").strip().startswith(OWNER_ADVISORY_SESSION_PREFIX)


def get_owner_advisory_account_id(session_id):
    raw_session_id = str(session_id or "").strip()

    if raw_session_id.startswith(OWNER_ADVISORY_SESSION_PREFIX):
        return raw_session_id[len(OWNER_ADVISORY_SESSION_PREFIX):].strip()

    return ""


def get_client_subscription(session_id):
    raw_session_id = str(session_id or "").strip()
    lookup_session_id = get_owner_advisory_account_id(raw_session_id) or raw_session_id

    # ===== ALSAAB RESOLVE PARTNER TO OWN SUBSCRIPTION V1 START =====
    # Callers pass a partner id here (the client dashboard does), but a
    # partner's own subscription is stored against partners.client_id — a value
    # like "smart_ALS-P00003_1783769419085_820", never "ALS-P00003".
    #
    # The query below also matches on source_partner_id, so for a partner with
    # customers it returned one of THEIR subscriptions instead, and which one
    # varied between calls. The dashboard was showing a partner someone else's
    # plan, renewal date and failed-payment state.
    #
    # Resolving the partner id to their own client_id first makes the lookup
    # both correct and stable.
    if re.match(r"^ALS-P\d+$", lookup_session_id, flags=re.IGNORECASE):
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute(
                "SELECT client_id FROM partners WHERE partner_id = ?",
                (lookup_session_id.upper(),),
            )
            row = c.fetchone()
            conn.close()

            if row and str(row[0] or "").strip():
                lookup_session_id = str(row[0]).strip()
        except Exception as resolve_error:
            print(f"PARTNER OWN SUBSCRIPTION RESOLVE ERROR ⚠️ {resolve_error}", flush=True)
    # ===== ALSAAB RESOLVE PARTNER TO OWN SUBSCRIPTION V1 END =====

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            id,
            session_id,
            client_id,
            bot_id,
            source_partner_id,
            plan_name,
            monthly_reply_limit,
            monthly_replies_used,
            owner_advisory_replies_used,
            subscription_status,
            billing_cycle_start,
            billing_cycle_end,
            stripe_customer_id,
            stripe_subscription_id,
            package_amount,
            notes,
            cancel_requested_at,
            cancel_at_period_end,
            cancel_effective_at,
            cancel_reason,
            payment_failed_at,
            payment_grace_until,
            payment_retry_count,
            customer_email,
            customer_phone,
            next_renewal_at,
            last_invoice_url,
            created_at,
            updated_at
        FROM subscriptions
        WHERE session_id=?
           OR client_id=?
           OR source_partner_id=?
        ORDER BY
            CASE
                WHEN session_id=? THEN 0
                WHEN client_id=? THEN 1
                ELSE 2
            END,
            updated_at DESC, id DESC
        LIMIT 1
        """,
        (
            lookup_session_id,
            lookup_session_id,
            lookup_session_id,
            lookup_session_id,
            lookup_session_id,
        )
    )

    row = c.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row[0],
        "session_id": row[1],
        "client_id": row[2],
        "bot_id": row[3],
        "source_partner_id": row[4],
        "plan_name": row[5],
        "monthly_reply_limit": row[6] or 0,
        "monthly_replies_used": row[7] or 0,
        "owner_advisory_replies_used": row[8] or 0,
        "subscription_status": row[9],
        "billing_cycle_start": row[10],
        "billing_cycle_end": row[11],
        "stripe_customer_id": row[12],
        "stripe_subscription_id": row[13],
        "package_amount": row[14],
        "notes": row[15],
        "cancel_requested_at": row[16],
        "cancel_at_period_end": bool(row[17]),
        "cancel_effective_at": row[18],
        "cancel_reason": row[19],
        "payment_failed_at": row[20],
        "payment_grace_until": row[21],
        "payment_retry_count": row[22] or 0,
        "customer_email": row[23],
        "customer_phone": row[24],
        "next_renewal_at": row[25],
        "last_invoice_url": row[26],
        "created_at": row[27],
        "updated_at": row[28],
    }

def get_client_subscription_by_stripe_subscription_id(stripe_subscription_id):
    stripe_subscription_id = str(stripe_subscription_id or "").strip()

    if not stripe_subscription_id:
        return None

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT session_id
        FROM subscriptions
        WHERE stripe_subscription_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (stripe_subscription_id,)
    )

    row = c.fetchone()
    conn.close()

    if not row or not row[0]:
        return None

    return get_client_subscription(row[0])

def get_latest_lead_for_session(session_id):
    session_id = str(session_id or "").strip()

    if not session_id:
        return {}

    try:
        conn = get_connection()
        c = conn.cursor()

        c.execute(
            """
            SELECT
                name,
                phone,
                email,
                country,
                business_name,
                user_type
            FROM leads
            WHERE session_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id,)
        )

        row = c.fetchone()
        conn.close()

        if not row:
            return {}

        return {
            "name": row[0] or "",
            "phone": row[1] or "",
            "email": row[2] or "",
            "country": row[3] or "",
            "business_name": row[4] or "",
            "user_type": row[5] or "",
        }

    except Exception as error:
        print(f"LATEST LEAD LOOKUP ERROR {error}", flush=True)
        return {}


def build_auto_partner_name(session_id, client_id="", email="", phone="", lead_name="", business_name=""):
    lead_name = str(lead_name or "").strip()
    business_name = str(business_name or "").strip()
    email = str(email or "").strip()
    phone = str(phone or "").strip()
    reference_id = str(client_id or session_id or "").strip()

    if lead_name:
        return lead_name

    if business_name:
        return business_name

    if email and "@" in email:
        return email.split("@")[0].strip() or email

    if phone:
        return f"ALSAAB Partner {phone}"

    if reference_id:
        return f"ALSAAB Partner {reference_id[:8]}"

    return "ALSAAB Partner"


def normalize_auto_partner_source(source_partner_id, session_id=""):
    normalized_source = normalize_partner_id(
        source_partner_id
        or get_source_partner_id_for_session(session_id)
        or COMPANY_OWNER_PARTNER_ID
    )

    if not normalized_source:
        return COMPANY_OWNER_PARTNER_ID

    if str(normalized_source).lower() == str(COMPANY_OWNER_PARTNER_ID).lower():
        return COMPANY_OWNER_PARTNER_ID

    if str(normalized_source).upper().startswith("ALS-P"):
        return str(normalized_source).upper()

    return COMPANY_OWNER_PARTNER_ID


def ensure_paid_client_is_partner(
    session_id,
    client_id="",
    source_partner_id="",
    partner_name="",
    phone="",
    email="",
    country="",
    notes="",
    stripe_subscription_id="",
    plan_name="",
    package_amount=""
):
    """
    أي شخص يدفع يصير عميل + شريك تلقائياً.
    إذا ما عنده Partner ID في Google Sheets، Apps Script يولده.
    إذا عنده Partner مسبقاً، Apps Script يرجع نفس Partner ID بدون تكرار.
    """
    session_id = str(session_id or "").strip()
    client_id = str(client_id or session_id or "").strip()

    if not session_id and not client_id:
        return {
            "status": "error",
            "message": "session_id or client_id is required"
        }

    if not session_id:
        session_id = client_id

    source_partner_id = normalize_auto_partner_source(
        source_partner_id,
        session_id=session_id
    )

    latest_lead = get_latest_lead_for_session(session_id)

    final_phone = str(phone or latest_lead.get("phone", "") or "").strip()
    final_email = str(email or latest_lead.get("email", "") or "").strip()
    final_country = str(country or latest_lead.get("country", "") or "").strip()

    final_partner_name = build_auto_partner_name(
        session_id=session_id,
        client_id=client_id,
        email=final_email,
        phone=final_phone,
        lead_name=partner_name or latest_lead.get("name", ""),
        business_name=latest_lead.get("business_name", "")
    )

    notes_parts = []

    if notes:
        notes_parts.append(str(notes))

    notes_parts.extend([
        "auto_created_from_paid_client",
        f"session_id={session_id}",
        f"client_id={client_id}",
        f"source_partner_id={source_partner_id}",
        f"stripe_subscription_id={stripe_subscription_id or ''}",
        f"plan_name={plan_name or ''}",
        f"package_amount={package_amount or ''}",
    ])

    final_notes = "; ".join(notes_parts)

    try:
        print(
            f"AUTO PARTNER CREATE START session_id={session_id} client_id={client_id} sponsor={source_partner_id}",
            flush=True
        )

        result = send_partner_to_google_sheet(
            partner_name=final_partner_name,
            phone=final_phone,
            email=final_email,
            country=final_country,
            invited_by=source_partner_id,
            notes=final_notes,
            level="Level 1",
            status="active",
            client_id=client_id,
            sponsor_partner_id=source_partner_id,
            parent_partner_id=source_partner_id,
            partner_rank="Level 1"
        )

        try:
            save_auto_partner_mapping_from_result(
                result=result,
                client_id=client_id,
                session_id=session_id,
                sponsor_partner_id=source_partner_id,
                partner_name=final_partner_name,
                phone=final_phone,
                email=final_email,
                country=final_country,
                plan_name=plan_name,
                package_amount=package_amount,
                stripe_subscription_id=stripe_subscription_id,
            )
        except Exception as mapping_error:
            print(f"AUTO PARTNER MAPPING SAVE ERROR {mapping_error}", flush=True)

        print(f"AUTO PARTNER CREATE RESULT {result}", flush=True)

        try:
            auto_partner_id = extract_partner_id_from_google_sheet_result(result)

            wordpress_link_result = send_wordpress_account_link(
                email=final_email,
                partner_id=auto_partner_id,
                client_id=client_id,
                plan_name=plan_name,
                subscription_status="active",
                name=final_partner_name,
            )

            print(f"AUTO WORDPRESS ACCOUNT LINK RESULT {wordpress_link_result}", flush=True)

        except Exception as wordpress_link_error:
            print(f"AUTO WORDPRESS ACCOUNT LINK ERROR ❌ {wordpress_link_error}", flush=True)


        return result

    except Exception as error:
        print(f"AUTO PARTNER CREATE ERROR {error}", flush=True)

        return {
            "status": "error",
            "message": str(error),
            "session_id": session_id,
            "client_id": client_id,
            "source_partner_id": source_partner_id
        }

def create_or_update_subscription(
    session_id,
    plan_name,
    client_id="",
    bot_id="",
    status="active",
    custom_reply_limit=None,
    stripe_customer_id="",
    stripe_subscription_id="",
    package_amount="",
    notes="",
    reset_usage=True,
    source_partner_id=""
):
    if not client_id:
        client_id = session_id

    source_partner_id = normalize_auto_partner_source(
        source_partner_id,
        session_id=session_id
    )

    plan_name = normalize_plan_name(plan_name)
    monthly_reply_limit = get_plan_reply_limit(plan_name, custom_reply_limit)

    now = current_timestamp()
    cycle_end = next_month_timestamp()

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        "SELECT id FROM subscriptions WHERE session_id=?",
        (session_id,)
    )
    existing = c.fetchone()

    if existing:
        if reset_usage:
            c.execute(
                """
                UPDATE subscriptions
                SET
                    client_id=?,
                    bot_id=?,
                    source_partner_id=?,
                    plan_name=?,
                    monthly_reply_limit=?,
                    monthly_replies_used=0,
                    subscription_status=?,
                    billing_cycle_start=?,
                    billing_cycle_end=?,
                    stripe_customer_id=?,
                    stripe_subscription_id=?,
                    package_amount=?,
                    notes=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE session_id=?
                """,
                (
                    client_id,
                    bot_id,
                    source_partner_id,
                    plan_name,
                    monthly_reply_limit,
                    status,
                    now,
                    cycle_end,
                    stripe_customer_id,
                    stripe_subscription_id,
                    package_amount,
                    notes,
                    session_id
                )
            )
        else:
            c.execute(
                """
                UPDATE subscriptions
                SET
                    client_id=?,
                    bot_id=?,
                    source_partner_id=?,
                    plan_name=?,
                    monthly_reply_limit=?,
                    subscription_status=?,
                    stripe_customer_id=?,
                    stripe_subscription_id=?,
                    package_amount=?,
                    notes=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE session_id=?
                """,
                (
                    client_id,
                    bot_id,
                    source_partner_id,
                    plan_name,
                    monthly_reply_limit,
                    status,
                    stripe_customer_id,
                    stripe_subscription_id,
                    package_amount,
                    notes,
                    session_id
                )
            )
    else:
        c.execute(
            """
            INSERT INTO subscriptions (
                session_id,
                client_id,
                bot_id,
                source_partner_id,
                plan_name,
                monthly_reply_limit,
                monthly_replies_used,
                subscription_status,
                billing_cycle_start,
                billing_cycle_end,
                stripe_customer_id,
                stripe_subscription_id,
                package_amount,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                client_id,
                bot_id,
                source_partner_id,
                plan_name,
                monthly_reply_limit,
                0,
                status,
                now,
                cycle_end,
                stripe_customer_id,
                stripe_subscription_id,
                package_amount,
                notes
            )
        )

    conn.commit()
    conn.close()

    print(
        f"SUBSCRIPTION SAVED ✅ session_id={session_id} client_id={client_id} source_partner_id={source_partner_id} plan={plan_name} limit={monthly_reply_limit} status={status}",
        flush=True
    )

    subscription = get_client_subscription(session_id)

    try:
        sheet_result = send_subscription_to_google_sheet(
            client_id=subscription.get("client_id") or client_id,
            session_id=subscription.get("session_id") or session_id,
            source_partner_id=subscription.get("source_partner_id") or source_partner_id,
            plan_name=subscription.get("plan_name") or plan_name,
            package_amount=subscription.get("package_amount") or package_amount,
            subscription_status=subscription.get("subscription_status") or status,
            stripe_customer_id=subscription.get("stripe_customer_id") or stripe_customer_id,
            stripe_subscription_id=subscription.get("stripe_subscription_id") or stripe_subscription_id,
            current_period_start=subscription.get("billing_cycle_start") or now,
            current_period_end=subscription.get("billing_cycle_end") or cycle_end,
            notes=notes or "Saved from create_or_update_subscription"
        )

        if sheet_result.get("status") == "success":
            print("SUBSCRIPTION SENT TO GOOGLE SHEET ✅", flush=True)
        else:
            print(f"SUBSCRIPTION GOOGLE SHEET SEND NOT SUCCESS ⚠️ {sheet_result}", flush=True)

    except Exception as error:
        print(f"SUBSCRIPTION GOOGLE SHEET SEND ERROR ❌ {error}", flush=True)

    try:
        if str(status or "").lower() in ("active", "paid", "trialing"):
            auto_partner_result = ensure_paid_client_is_partner(
                session_id=session_id,
                client_id=client_id,
                source_partner_id=source_partner_id,
                notes=(notes or "") + "; AUTO PAID CLIENT PARTNER ENSURE FROM SUBSCRIPTION",
                stripe_subscription_id=stripe_subscription_id,
                plan_name=plan_name,
                package_amount=package_amount
            )

            print(
                f"AUTO PAID CLIENT PARTNER ENSURE RESULT ✅ {auto_partner_result}",
                flush=True
            )
        else:
            print(
                f"AUTO PAID CLIENT PARTNER ENSURE SKIPPED status={status}",
                flush=True
            )
    except Exception as auto_partner_error:
        print(f"AUTO PAID CLIENT PARTNER ENSURE ERROR ❌ {auto_partner_error}", flush=True)

    # ===== ALSAAB LEVEL RESYNC BOTH SIDES V1 START =====
    # Recalculate the level of BOTH parties on any subscription change:
    #
    #   the referrer  - their active-customer count just moved
    #   the owner     - their own level depends on their own subscription, and
    #                   if it lapses they must stop showing as commission
    #                   eligible. Only the referrer used to be resynced, so a
    #                   partner who cancelled kept an "eligible" badge until
    #                   some unrelated event happened to touch them.
    #
    # The payout decision itself was never wrong — the commission engine
    # recomputes eligibility from scratch at payout time — but every dashboard
    # read a stale value in between.
    try:
        owner_partner_id = normalize_partner_id(client_id) or normalize_partner_id(session_id)

        for partner_to_resync in (source_partner_id, owner_partner_id):
            if not partner_to_resync:
                continue

            if str(partner_to_resync).lower() == str(COMPANY_OWNER_PARTNER_ID).lower():
                continue

            sync_partner_level_progress_to_google_sheet(partner_to_resync)

    except Exception as level_sync_error:
        print(f"SUBSCRIPTION LEVEL SYNC ERROR ❌ {level_sync_error}", flush=True)
    # ===== ALSAAB LEVEL RESYNC BOTH SIDES V1 END =====

    return subscription


def set_subscription_status(session_id, status, notes=""):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        UPDATE subscriptions
        SET
            subscription_status=?,
            notes=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE session_id=?
        """,
        (status, notes, session_id)
    )

    conn.commit()
    conn.close()

    print(f"SUBSCRIPTION STATUS UPDATED ✅ session_id={session_id} status={status}", flush=True)

    return get_client_subscription(session_id)


def cancel_subscription(session_id, notes="cancelled by admin or customer request"):
    return set_subscription_status(session_id, "cancelled", notes=notes)


def reset_subscription_usage(session_id):
    now = current_timestamp()
    cycle_end = next_month_timestamp()

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        UPDATE subscriptions
        SET
            monthly_replies_used=0,
            billing_cycle_start=?,
            billing_cycle_end=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE session_id=?
        """,
        (now, cycle_end, session_id)
    )

    conn.commit()
    conn.close()

    print(f"SUBSCRIPTION USAGE RESET ✅ session_id={session_id}", flush=True)

    return get_client_subscription(session_id)


def reset_subscription_usage_if_needed(session_id):
    subscription = get_client_subscription(session_id)

    if not subscription:
        return None

    status = str(subscription.get("subscription_status", "")).lower().strip()

    if status != "active":
        return subscription

    billing_cycle_end = parse_timestamp(subscription.get("billing_cycle_end"))

    if not billing_cycle_end:
        return subscription

    if datetime.utcnow() >= billing_cycle_end:
        return reset_subscription_usage(subscription.get("session_id") or session_id)

    return subscription


def can_client_use_bot(session_id):
    subscription = reset_subscription_usage_if_needed(session_id)

    if not subscription:
        return {
            "allowed": False,
            "reason": "no_subscription",
            "message": get_usage_limit_message("no_subscription"),
            "subscription": None,
        }

    status = str(subscription.get("subscription_status", "")).lower().strip()

    if status == "cancelled":
        return {
            "allowed": False,
            "reason": "cancelled_subscription",
            "message": get_usage_limit_message("cancelled_subscription", subscription),
            "subscription": subscription,
        }

    if status != "active":
        return {
            "allowed": False,
            "reason": "inactive_subscription",
            "message": get_usage_limit_message("inactive_subscription", subscription),
            "subscription": subscription,
        }

    # ===== ALSAAB CANCEL AT PERIOD END GATE V1 START =====
    # A scheduled cancellation keeps the bot running until the paid period
    # actually runs out — the customer paid for the month.
    #
    # This check is what ends it, rather than waiting for Stripe's
    # customer.subscription.deleted webhook: a manual subscription has no
    # Stripe object to fire one, and even a Stripe subscription would keep
    # serving replies if that webhook were ever missed.
    if subscription.get("cancel_at_period_end"):
        effective_at = parse_timestamp(subscription.get("cancel_effective_at"))

        if effective_at and datetime.utcnow() >= effective_at:
            return {
                "allowed": False,
                "reason": "cancelled_subscription",
                "message": get_usage_limit_message("cancelled_subscription", subscription),
                "subscription": subscription,
            }
    # ===== ALSAAB CANCEL AT PERIOD END GATE V1 END =====

    if is_owner_advisory_session(session_id):
        owner_advisory_reply_limit = int(
            subscription.get("owner_advisory_reply_limit")
            or get_plan_owner_advisory_reply_limit(subscription.get("plan_name"))
            or 0
        )
        owner_advisory_replies_used = int(subscription.get("owner_advisory_replies_used") or 0)

        if owner_advisory_reply_limit <= 0:
            return {
                "allowed": False,
                "reason": "owner_advisory_not_included",
                "message": "باقتك الحالية لا تشمل استشارات صاحب المشروع. هذه الميزة متاحة في باقة النمو والنخبة.",
                "subscription": subscription,
                "usage_type": "owner_advisory_reply",
            }

        if owner_advisory_replies_used >= owner_advisory_reply_limit:
            return {
                "allowed": False,
                "reason": "owner_advisory_limit_reached",
                "message": "وصلت للحد الشهري لاستشارات صاحب المشروع. تقدر ترقّي الباقة أو تنتظر بداية الدورة القادمة.",
                "subscription": subscription,
                "usage_type": "owner_advisory_reply",
            }

        return {
            "allowed": True,
            "reason": "active",
            "message": "",
            "subscription": subscription,
            "usage_type": "owner_advisory_reply",
            "usage_limit": owner_advisory_reply_limit,
            "usage_used": owner_advisory_replies_used,
        }

    monthly_reply_limit = int(subscription.get("monthly_reply_limit") or 0)
    monthly_replies_used = int(subscription.get("monthly_replies_used") or 0)

    if monthly_reply_limit <= 0:
        return {
            "allowed": False,
            "reason": "invalid_limit",
            "message": get_usage_limit_message("invalid_limit", subscription),
            "subscription": subscription,
            "usage_type": "bot_reply",
        }

    if monthly_replies_used >= monthly_reply_limit:
        return {
            "allowed": False,
            "reason": "limit_reached",
            "message": get_usage_limit_message("limit_reached", subscription),
            "subscription": subscription,
            "usage_type": "bot_reply",
        }

    return {
        "allowed": True,
        "reason": "active",
        "message": "",
        "subscription": subscription,
        "usage_type": "bot_reply",
        "usage_limit": monthly_reply_limit,
        "usage_used": monthly_replies_used,
    }

def record_bot_reply_usage(session_id, replies_count=1, tokens_estimate=0):
    usage_check = can_client_use_bot(session_id)

    if not usage_check.get("allowed"):
        print(
            f"USAGE NOT RECORDED ❌ session_id={session_id} reason={usage_check.get('reason')}",
            flush=True
        )
        return False

    subscription = usage_check.get("subscription") or {}

    client_id = subscription.get("client_id") or subscription.get("source_partner_id") or subscription.get("session_id") or session_id
    bot_id = subscription.get("bot_id") or ""
    plan_name = subscription.get("plan_name") or ""
    subscription_session_id = subscription.get("session_id") or session_id
    usage_type = usage_check.get("usage_type") or "bot_reply"

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO usage_logs (
            session_id,
            client_id,
            bot_id,
            plan_name,
            usage_type,
            message_role,
            replies_count,
            tokens_estimate
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            client_id,
            bot_id,
            plan_name,
            usage_type,
            "bot",
            replies_count,
            tokens_estimate
        )
    )

    if usage_type == "owner_advisory_reply":
        c.execute(
            """
            UPDATE subscriptions
            SET
                owner_advisory_replies_used = owner_advisory_replies_used + ?,
                updated_at=CURRENT_TIMESTAMP
            WHERE session_id=?
            """,
            (replies_count, subscription_session_id)
        )
    else:
        c.execute(
            """
            UPDATE subscriptions
            SET
                monthly_replies_used = monthly_replies_used + ?,
                updated_at=CURRENT_TIMESTAMP
            WHERE session_id=?
            """,
            (replies_count, subscription_session_id)
        )

    conn.commit()
    conn.close()

    updated_subscription = get_client_subscription(subscription_session_id)

    if usage_type == "owner_advisory_reply":
        print(
            f"OWNER ADVISORY USAGE RECORDED ✅ session_id={session_id} client_id={client_id} used={updated_subscription.get('owner_advisory_replies_used')} limit={get_plan_owner_advisory_reply_limit(plan_name)}",
            flush=True
        )
    else:
        print(
            f"USAGE RECORDED ✅ session_id={session_id} client_id={client_id} used={updated_subscription.get('monthly_replies_used')} limit={updated_subscription.get('monthly_reply_limit')}",
            flush=True
        )

    return True

def get_usage_summary(session_id):
    subscription = reset_subscription_usage_if_needed(session_id)

    if not subscription:
        return {
            "has_subscription": False,
            "allowed": False,
            "reason": "no_subscription",
            "message": get_usage_limit_message("no_subscription"),
        }

    monthly_reply_limit = int(subscription.get("monthly_reply_limit") or 0)
    monthly_replies_used = int(subscription.get("monthly_replies_used") or 0)
    remaining = max(monthly_reply_limit - monthly_replies_used, 0)

    usage_check = can_client_use_bot(session_id)

    return {
        "has_subscription": True,
        "allowed": usage_check.get("allowed"),
        "reason": usage_check.get("reason"),
        "message": usage_check.get("message"),
        "session_id": subscription.get("session_id"),
        "client_id": subscription.get("client_id"),
        "bot_id": subscription.get("bot_id"),
        "source_partner_id": subscription.get("source_partner_id"),
        "plan_name": subscription.get("plan_name"),
        "subscription_status": subscription.get("subscription_status"),
        "monthly_reply_limit": monthly_reply_limit,
        "monthly_replies_used": monthly_replies_used,
        "remaining_replies": remaining,
        "billing_cycle_start": subscription.get("billing_cycle_start"),
        "billing_cycle_end": subscription.get("billing_cycle_end"),
    }


def get_usage_logs(session_id, limit=100):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            id,
            session_id,
            client_id,
            bot_id,
            plan_name,
            usage_type,
            message_role,
            replies_count,
            tokens_estimate,
            created_at
        FROM usage_logs
        WHERE session_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, limit)
    )

    rows = c.fetchall()
    conn.close()

    logs = []

    for row in rows:
        logs.append({
            "id": row[0],
            "session_id": row[1],
            "client_id": row[2],
            "bot_id": row[3],
            "plan_name": row[4],
            "usage_type": row[5],
            "message_role": row[6],
            "replies_count": row[7],
            "tokens_estimate": row[8],
            "created_at": row[9],
        })

    return logs


def get_all_subscriptions(limit=100):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            id,
            session_id,
            client_id,
            bot_id,
            source_partner_id,
            plan_name,
            monthly_reply_limit,
            monthly_replies_used,
            subscription_status,
            billing_cycle_start,
            billing_cycle_end,
            stripe_customer_id,
            stripe_subscription_id,
            package_amount,
            notes,
            created_at,
            updated_at
        FROM subscriptions
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows = c.fetchall()
    conn.close()

    subscriptions = []

    for row in rows:
        subscriptions.append({
            "id": row[0],
            "session_id": row[1],
            "client_id": row[2],
            "bot_id": row[3],
            "source_partner_id": row[4],
            "plan_name": row[5],
            "monthly_reply_limit": row[6],
            "monthly_replies_used": row[7],
            "subscription_status": row[8],
            "billing_cycle_start": row[9],
            "billing_cycle_end": row[10],
            "stripe_customer_id": row[11],
            "stripe_subscription_id": row[12],
            "package_amount": row[13],
            "notes": row[14],
            "created_at": row[15],
            "updated_at": row[16],
        })

    return subscriptions


def export_leads_for_google_sheets():
    leads = get_leads(limit=1000)

    rows = [
        [
            "ID",
            "Session ID",
            "Client ID",
            "Source Partner ID",
            "Referral Saved At",
            "Name",
            "Phone",
            "User Type",
            "Business Name",
            "Business Type",
            "Pain Point",
            "Channel",
            "Status",
            "Email",
            "Country",
            "Created At",
        ]
    ]

    for lead in leads:
        rows.append([
            lead["id"],
            lead["session_id"],
            lead["client_id"],
            lead["source_partner_id"],
            lead["referral_saved_at"],
            lead["name"],
            lead["phone"],
            lead["user_type"],
            lead["business_name"],
            lead["business_type"],
            lead["pain_point"],
            lead["channel"],
            lead["status"],
            lead["email"],
            lead["country"],
            lead["created_at"],
        ])

    return rows


def export_client_profiles_for_google_sheets():
    profiles = get_client_profiles(limit=1000)

    rows = [
        [
            "ID",
            "Session ID",
            "Client ID",
            "Business Name",
            "Business Type",
            "General Description",
            "Products",
            "Prices",
            "Offers",
            "Ordering",
            "WhatsApp",
            "Areas",
            "FAQs",
            "Objections",
            "Tone",
            "Updated At",
        ]
    ]

    for profile in profiles:
        rows.append([
            profile["id"],
            profile["session_id"],
            profile["client_id"],
            profile["business_name"],
            profile["business_type"],
            profile["general_description"],
            profile["products"],
            profile["prices"],
            profile["offers"],
            profile["ordering"],
            profile["whatsapp"],
            profile["areas"],
            profile["faqs"],
            profile["objections"],
            profile["tone"],
            profile["updated_at"],
        ])

    return rows


def export_subscriptions_for_google_sheets():
    subscriptions = get_all_subscriptions(limit=1000)

    rows = [
        [
            "ID",
            "Session ID",
            "Client ID",
            "Bot ID",
            "Source Partner ID",
            "Plan Name",
            "Monthly Reply Limit",
            "Monthly Replies Used",
            "Remaining Replies",
            "Subscription Status",
            "Billing Cycle Start",
            "Billing Cycle End",
            "Stripe Customer ID",
            "Stripe Subscription ID",
            "Package Amount",
            "Notes",
            "Created At",
            "Updated At",
        ]
    ]

    for subscription in subscriptions:
        monthly_reply_limit = int(subscription.get("monthly_reply_limit") or 0)
        monthly_replies_used = int(subscription.get("monthly_replies_used") or 0)
        remaining = max(monthly_reply_limit - monthly_replies_used, 0)

        rows.append([
            subscription["id"],
            subscription["session_id"],
            subscription["client_id"],
            subscription["bot_id"],
            subscription["source_partner_id"],
            subscription["plan_name"],
            monthly_reply_limit,
            monthly_replies_used,
            remaining,
            subscription["subscription_status"],
            subscription["billing_cycle_start"],
            subscription["billing_cycle_end"],
            subscription["stripe_customer_id"],
            subscription["stripe_subscription_id"],
            subscription["package_amount"],
            subscription["notes"],
            subscription["created_at"],
            subscription["updated_at"],
        ])

    return rows


# =========================
# MLM / PARTNER GOOGLE SHEETS SYSTEM
# =========================

def send_partner_to_google_sheet(
    partner_name,
    phone,
    email="",
    country="",
    invited_by="",
    notes="",
    level="Level 1",
    status="active",
    partner_id="",
    referral_link="",
    client_id="",
    sponsor_partner_id="",
    parent_partner_id="",
    partner_rank=""
):
    """
    يسجل شريك جديد في Google Sheet صفحة Partners.
    Google Apps Script يولد Partner ID و Referral Link إذا ما أرسلناهم.
    يدعم الشجرة عن طريق sponsor_partner_id و parent_partner_id.
    """
    normalized_rank = normalize_partner_rank(partner_rank or level)
    normalized_sponsor = normalize_partner_id(sponsor_partner_id or invited_by)
    normalized_parent = normalize_partner_id(parent_partner_id or normalized_sponsor)

    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "partner",
        "client_id": client_id or "",
        "partner_name": partner_name or "",
        "name": partner_name or "",
        "phone": phone or "",
        "whatsapp": phone or "",
        "email": email or "",
        "country": country or "",
        "sponsor_partner_id": normalized_sponsor or "",
        "sponsor_id": normalized_sponsor or "",
        "parent_partner_id": normalized_parent or "",
        "invited_by": invited_by or normalized_sponsor or "",
        "notes": notes or "",
        "partner_rank": normalized_rank or "Level 1",
        "level": normalized_rank or "Level 1",
        "rank": normalized_rank or "Level 1",
        "status": status or "active",
        "partner_id": normalize_partner_id(partner_id) or "",
        "referral_link": referral_link or "",
    }

    return post_to_google_sheet_json(payload, label="partner")


def send_partner_tree_to_google_sheet(
    ancestor_partner_id,
    descendant_partner_id,
    depth,
    line_owner_partner_id="",
    notes=""
):
    """
    يحفظ علاقة في شجرة الشركاء PartnerTree.
    """
    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "partner_tree",
        "ancestor_partner_id": normalize_partner_id(ancestor_partner_id),
        "ancestor": normalize_partner_id(ancestor_partner_id),
        "descendant_partner_id": normalize_partner_id(descendant_partner_id),
        "descendant": normalize_partner_id(descendant_partner_id),
        "depth": depth,
        "line_owner_partner_id": normalize_partner_id(line_owner_partner_id),
        "line_owner": normalize_partner_id(line_owner_partner_id),
        "notes": notes or "",
    }

    return post_to_google_sheet_json(payload, label="partner_tree")


def send_referral_to_google_sheet(
    partner_id="",
    referral_name="",
    referral_phone="",
    referral_email="",
    source="website",
    package_name="",
    payment_status="pending",
    subscription_status="pending",
    session_id="",
    client_id="",
    notes="",
    source_partner_id="",
    stripe_subscription_id=""
):
    """
    يسجل إحالة جديدة في Google Sheet صفحة Referrals.
    partner_id موجود للتوافق القديم.
    source_partner_id هو الاسم الأدق للنظام الجديد.
    """
    normalized_source_partner_id = normalize_partner_id(source_partner_id or partner_id)

    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "referral",
        "source_partner_id": normalized_source_partner_id or "",
        "partner_id": normalized_source_partner_id or "",
        "ref": normalized_source_partner_id or "",
        "referral_name": referral_name or "",
        "name": referral_name or "",
        "referral_phone": referral_phone or "",
        "phone": referral_phone or "",
        "referral_email": referral_email or "",
        "email": referral_email or "",
        "source": source or "website",
        "package": package_name or "",
        "plan_name": package_name or "",
        "payment_status": payment_status or "pending",
        "subscription_status": subscription_status or "pending",
        "session_id": session_id or "",
        "client_id": client_id or "",
        "stripe_subscription_id": stripe_subscription_id or "",
        "notes": notes or "",
    }

    return post_to_google_sheet_json(payload, label="referral")


def send_subscription_to_google_sheet(
    client_id,
    session_id="",
    source_partner_id="",
    plan_name="",
    package_amount="",
    subscription_status="active",
    stripe_customer_id="",
    stripe_subscription_id="",
    current_period_start="",
    current_period_end="",
    notes=""
):
    """
    يحفظ اشتراك العميل في Google Sheet صفحة Subscriptions.
    هذا مهم لاحقاً لحساب العمولات الشهرية عند invoice.paid.
    """
    normalized_source_partner_id = normalize_partner_id(source_partner_id)

    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "subscription",
        "client_id": client_id or "",
        "session_id": session_id or "",
        "source_partner_id": normalized_source_partner_id or "",
        "partner_id": normalized_source_partner_id or "",
        "ref": normalized_source_partner_id or "",
        "plan_name": plan_name or "",
        "package": plan_name or "",
        "package_amount": package_amount or "",
        "subscription_status": subscription_status or "active",
        "status": subscription_status or "active",
        "stripe_customer_id": stripe_customer_id or "",
        "stripe_subscription_id": stripe_subscription_id or "",
        "current_period_start": current_period_start or "",
        "current_period_end": current_period_end or "",
        "notes": notes or "",
    }

    return post_to_google_sheet_json(payload, label="subscription")


def send_commission_to_google_sheet(
    partner_id="",
    partner_name="",
    referral_name="",
    package_name="",
    package_amount="",
    commission_percent="25",
    commission_amount="",
    recurring_type="monthly",
    status="pending",
    paid_date="",
    notes="",
    commission_id="",
    invoice_id="",
    stripe_subscription_id="",
    payer_client_id="",
    payer_name="",
    source_partner_id="",
    beneficiary_partner_id="",
    commission_depth="",
    line_owner_partner_id="",
    partner_rank="",
    period_start="",
    period_end=""
):
    """
    يسجل عمولة في Google Sheet صفحة Commissions.
    هذا الإصدار يمرر العمولة أولاً على Level Qualification Engine:
    - لا عمولة للشركة alsaab.
    - لا عمولة إذا اشتراك الشريك غير active.
    - لا عمولة على عمق أعلى من مستوى الشريك الحقيقي.
    """
    import re

    from level_engine import (
        get_commission_rate_for_depth,
        is_partner_eligible_for_commission_depth,
    )

    normalized_beneficiary = normalize_partner_id(beneficiary_partner_id or partner_id)
    normalized_source = normalize_partner_id(source_partner_id)
    normalized_line_owner = normalize_partner_id(line_owner_partner_id)
    normalized_rank = normalize_partner_rank(partner_rank or "Level 1")

    if not normalized_beneficiary:
        return {
            "status": "skipped",
            "reason": "missing_beneficiary_partner_id",
            "partner_id": partner_id,
            "beneficiary_partner_id": beneficiary_partner_id,
        }

    if str(normalized_beneficiary).lower() == str(COMPANY_OWNER_PARTNER_ID).lower():
        return {
            "status": "skipped",
            "reason": "company_owner_does_not_receive_commission",
            "beneficiary_partner_id": normalized_beneficiary,
        }

    depth_text = str(commission_depth or "").strip()
    depth_int = 0

    if depth_text:
        try:
            depth_int = int(float(depth_text))
        except (TypeError, ValueError):
            depth_int = 0

    if depth_int <= 0:
        match = re.search(r"level\s*([1-5])", str(normalized_rank or ""), flags=re.IGNORECASE)
        if match:
            depth_int = int(match.group(1))

    if depth_int <= 0:
        depth_int = 1

    if depth_int < 1 or depth_int > 5:
        return {
            "status": "skipped",
            "reason": "invalid_commission_depth",
            "beneficiary_partner_id": normalized_beneficiary,
            "commission_depth": commission_depth,
        }

    try:
        progress = calculate_and_save_partner_level_progress(normalized_beneficiary)
    except Exception as error:
        print(f"COMMISSION LEVEL CHECK ERROR ❌ partner_id={normalized_beneficiary} error={error}", flush=True)

        return {
            "status": "skipped",
            "reason": "level_check_error",
            "beneficiary_partner_id": normalized_beneficiary,
            "message": str(error),
        }

    current_level = int(progress.get("current_level") or 0)
    subscription_status = progress.get("subscription_status") or ""

    eligible = is_partner_eligible_for_commission_depth(
        current_level=current_level,
        commission_depth=depth_int,
        subscription_status=subscription_status,
    )

    if not eligible:
        return {
            "status": "skipped",
            "reason": "partner_not_eligible_for_commission_depth",
            "beneficiary_partner_id": normalized_beneficiary,
            "current_level": current_level,
            "commission_depth": depth_int,
            "subscription_status": subscription_status,
        }

    depth_rate = float(get_commission_rate_for_depth(depth_int) or 0)

    if depth_rate <= 0:
        return {
            "status": "skipped",
            "reason": "zero_commission_rate_for_depth",
            "beneficiary_partner_id": normalized_beneficiary,
            "commission_depth": depth_int,
        }

    effective_commission_percent = str(depth_rate).rstrip("0").rstrip(".")

    effective_commission_amount = commission_amount or ""

    if not effective_commission_amount and package_amount:
        try:
            amount_number = float(
                re.sub(r"[^0-9.]", "", str(package_amount)) or "0"
            )

            effective_commission_amount = f"{amount_number * depth_rate / 100:.2f}"
        except Exception:
            effective_commission_amount = ""

    eligibility_note = (
        f"level_engine_checked=true; "
        f"beneficiary_current_level={current_level}; "
        f"commission_depth={depth_int}; "
        f"subscription_status={subscription_status}"
    )

    final_notes = notes or ""
    if final_notes:
        final_notes = f"{final_notes}; {eligibility_note}"
    else:
        final_notes = eligibility_note

    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "commission",
        "commission_id": commission_id or generate_commission_id(),
        "invoice_id": invoice_id or "",
        "stripe_subscription_id": stripe_subscription_id or "",
        "payer_client_id": payer_client_id or "",
        "payer_name": payer_name or referral_name or "",
        "client_id": payer_client_id or "",
        "client_name": payer_name or referral_name or "",
        "source_partner_id": normalized_source or "",
        "beneficiary_partner_id": normalized_beneficiary or "",
        "partner_id": normalized_beneficiary or "",
        "partner_name": partner_name or "",
        "referral_name": referral_name or payer_name or "",
        "commission_depth": str(depth_int),
        "depth": str(depth_int),
        "line_owner_partner_id": normalized_line_owner or "",
        "partner_rank": _level_number_to_label(current_level),
        "level": _level_number_to_label(current_level),
        "package": package_name or "",
        "plan_name": package_name or "",
        "package_amount": package_amount or "",
        "commission_percent": effective_commission_percent,
        "commission_amount": effective_commission_amount or "",
        "recurring_type": recurring_type or "monthly",
        "recurring": recurring_type or "monthly",
        "period_start": period_start or "",
        "period_end": period_end or "",
        "status": status or "pending",
        "paid_date": paid_date or "",
        "notes": final_notes,
    }

    return post_to_google_sheet_json(payload, label="commission")


def send_mlm_level_to_google_sheet(
    partner_id,
    current_level="Level 1",
    required_sales="1",
    completed_sales="0",
    required_course_workshop="الاشتراك بأي باقة",
    level_status="active",
    next_level="Level 2",
    partner_rank="",
    current_package="",
    subscription_status="",
    commission_eligible="",
    missing_requirements="",
    last_updated=""
):
    """
    يسجل أو يحدث مستوى الشريك في Google Sheet صفحة MLMLevels.
    يدعم الأعمدة الجديدة:
    Current Package, Subscription Status, Commission Eligible, Missing Requirements, Last Updated
    """
    import json

    normalized_rank = normalize_partner_rank(partner_rank or current_level)

    if isinstance(missing_requirements, (list, dict)):
        missing_requirements_value = json.dumps(missing_requirements, ensure_ascii=False)
    else:
        missing_requirements_value = str(missing_requirements or "")

    if isinstance(commission_eligible, bool):
        commission_eligible_value = "yes" if commission_eligible else "no"
    else:
        commission_eligible_value = str(commission_eligible or "")

    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "mlm_level",
        "partner_id": normalize_partner_id(partner_id) or "",
        "partner_rank": normalized_rank or "Level 1",
        "current_level": normalized_rank or "Level 1",
        "required_sales": required_sales or "1",
        "completed_sales": completed_sales or "0",
        "required_course_workshop": required_course_workshop or "",
        "required_course": required_course_workshop or "",
        "level_status": level_status or "active",
        "next_rank": next_level or "",
        "next_level": next_level or "",
        "current_package": current_package or "",
        "subscription_status": subscription_status or "",
        "commission_eligible": commission_eligible_value,
        "missing_requirements": missing_requirements_value,
        "last_updated": last_updated or current_timestamp(),
    }

    return post_to_google_sheet_json(payload, label="mlm_level")

def _level_db_table_exists(table_name):
    """
    sqlite_master does not exist in PostgreSQL, so this used to raise for
    every table and return False. get_partner_subscription_snapshot() reads
    that answer and gives up immediately, which meant the whole level-progress
    path — the numbers the dashboards display — silently found no
    subscriptions at all after the migration.
    """
    try:
        conn = get_connection()
        c = conn.cursor()

        try:
            c.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ?",
                (table_name,)
            )
            row = c.fetchone()
        except Exception:
            # SQLite fallback, still used for local runs without DATABASE_URL.
            c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            row = c.fetchone()

        conn.close()
        return bool(row)
    except Exception as error:
        print(f"LEVEL DB TABLE EXISTS ERROR {error}", flush=True)
        return False


def _level_db_columns(table_name):
    try:
        if not _level_db_table_exists(table_name):
            return set()

        conn = get_connection()
        c = conn.cursor()
        c.execute(f"PRAGMA table_info({table_name})")
        rows = c.fetchall()
        conn.close()

        return {str(row[1]) for row in rows}

    except Exception as error:
        print(f"LEVEL DB COLUMNS ERROR {error}", flush=True)
        return set()


def _pick_first_existing_column(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return ""


def init_level_qualification_tables():
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS partner_client_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id TEXT UNIQUE,
            client_id TEXT,
            session_id TEXT,
            sponsor_partner_id TEXT,
            partner_name TEXT,
            phone TEXT,
            email TEXT,
            country TEXT,
            plan_name TEXT,
            package_amount TEXT,
            stripe_subscription_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS course_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id TEXT,
            course_code TEXT,
            course_name TEXT,
            amount REAL,
            currency TEXT DEFAULT 'USD',
            status TEXT DEFAULT 'paid',
            stripe_payment_id TEXT,
            notes TEXT,
            paid_at TEXT DEFAULT CURRENT_TIMESTAMP,
            refunded_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(partner_id, course_code, stripe_payment_id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS partner_level_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id TEXT UNIQUE,
            current_level INTEGER DEFAULT 0,
            current_level_name TEXT,
            next_level INTEGER,
            next_level_name TEXT,
            current_package TEXT,
            subscription_status TEXT,
            subscription_active INTEGER DEFAULT 0,
            commission_eligible INTEGER DEFAULT 0,
            active_direct_customers INTEGER DEFAULT 0,
            purchased_courses TEXT,
            missing_requirements TEXT,
            progress_json TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()


def extract_partner_id_from_google_sheet_result(result):
    if not result:
        return ""

    priority_keys = [
        "partner_id",
        "partnerId",
        "Partner ID",
        "generated_partner_id",
        "new_partner_id",
        "id",
    ]

    if isinstance(result, dict):
        for key in priority_keys:
            value = result.get(key)
            if value:
                value = str(value).strip()
                if value.lower() == "alsaab" or value.upper().startswith("ALS-P"):
                    return value if value.lower() == "alsaab" else value.upper()

        for value in result.values():
            partner_id = extract_partner_id_from_google_sheet_result(value)
            if partner_id:
                return partner_id

    if isinstance(result, list):
        for item in result:
            partner_id = extract_partner_id_from_google_sheet_result(item)
            if partner_id:
                return partner_id

    return ""


def save_partner_client_mapping(
    partner_id,
    client_id="",
    session_id="",
    sponsor_partner_id="",
    partner_name="",
    phone="",
    email="",
    country="",
    plan_name="",
    package_amount="",
    stripe_subscription_id="",
):
    init_level_qualification_tables()

    partner_id = normalize_partner_id(partner_id)

    if not partner_id or str(partner_id).lower() == str(COMPANY_OWNER_PARTNER_ID).lower():
        return {
            "status": "skipped",
            "message": "No regular partner_id to map",
            "partner_id": partner_id,
        }

    client_id = str(client_id or session_id or "").strip()
    session_id = str(session_id or client_id or "").strip()
    sponsor_partner_id = normalize_partner_id(sponsor_partner_id or COMPANY_OWNER_PARTNER_ID)

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO partner_client_map (
            partner_id,
            client_id,
            session_id,
            sponsor_partner_id,
            partner_name,
            phone,
            email,
            country,
            plan_name,
            package_amount,
            stripe_subscription_id,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(partner_id) DO UPDATE SET
            client_id=COALESCE(NULLIF(excluded.client_id, ''), partner_client_map.client_id),
            session_id=COALESCE(NULLIF(excluded.session_id, ''), partner_client_map.session_id),
            sponsor_partner_id=COALESCE(NULLIF(excluded.sponsor_partner_id, ''), partner_client_map.sponsor_partner_id),
            partner_name=COALESCE(NULLIF(excluded.partner_name, ''), partner_client_map.partner_name),
            phone=COALESCE(NULLIF(excluded.phone, ''), partner_client_map.phone),
            email=COALESCE(NULLIF(excluded.email, ''), partner_client_map.email),
            country=COALESCE(NULLIF(excluded.country, ''), partner_client_map.country),
            plan_name=COALESCE(NULLIF(excluded.plan_name, ''), partner_client_map.plan_name),
            package_amount=COALESCE(NULLIF(excluded.package_amount, ''), partner_client_map.package_amount),
            stripe_subscription_id=COALESCE(NULLIF(excluded.stripe_subscription_id, ''), partner_client_map.stripe_subscription_id),
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            partner_id,
            client_id,
            session_id,
            sponsor_partner_id,
            str(partner_name or "").strip(),
            str(phone or "").strip(),
            str(email or "").strip(),
            str(country or "").strip(),
            str(plan_name or "").strip(),
            str(package_amount or "").strip(),
            str(stripe_subscription_id or "").strip(),
        )
    )

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "partner_id": partner_id,
        "client_id": client_id,
        "session_id": session_id,
        "sponsor_partner_id": sponsor_partner_id,
    }


def save_auto_partner_mapping_from_result(
    result,
    client_id="",
    session_id="",
    sponsor_partner_id="",
    partner_name="",
    phone="",
    email="",
    country="",
    plan_name="",
    package_amount="",
    stripe_subscription_id="",
):
    partner_id = extract_partner_id_from_google_sheet_result(result)

    if not partner_id:
        print(f"AUTO PARTNER MAPPING SKIPPED no partner_id in result={result}", flush=True)
        return {
            "status": "skipped",
            "message": "partner_id not found in google sheet result",
            "result": result,
        }

    mapped = save_partner_client_mapping(
        partner_id=partner_id,
        client_id=client_id,
        session_id=session_id,
        sponsor_partner_id=sponsor_partner_id,
        partner_name=partner_name,
        phone=phone,
        email=email,
        country=country,
        plan_name=plan_name,
        package_amount=package_amount,
        stripe_subscription_id=stripe_subscription_id,
    )

    print(f"AUTO PARTNER MAPPING SAVED {mapped}", flush=True)

    try:
        sync_partner_level_progress_to_google_sheet(partner_id)
    except Exception as level_sync_error:
        print(f"AUTO PARTNER LEVEL SYNC ERROR ❌ {level_sync_error}", flush=True)

    return mapped


def get_partner_client_mapping(partner_id):
    init_level_qualification_tables()

    partner_id = normalize_partner_id(partner_id)

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            partner_id,
            client_id,
            session_id,
            sponsor_partner_id,
            partner_name,
            phone,
            email,
            country,
            plan_name,
            package_amount,
            stripe_subscription_id,
            created_at,
            updated_at
        FROM partner_client_map
        WHERE partner_id=?
        LIMIT 1
        """,
        (partner_id,)
    )

    row = c.fetchone()
    conn.close()

    if not row:
        return {}

    return {
        "partner_id": row[0],
        "client_id": row[1],
        "session_id": row[2],
        "sponsor_partner_id": row[3],
        "partner_name": row[4],
        "phone": row[5],
        "email": row[6],
        "country": row[7],
        "plan_name": row[8],
        "package_amount": row[9],
        "stripe_subscription_id": row[10],
        "created_at": row[11],
        "updated_at": row[12],
    }


def get_partner_subscription_snapshot(partner_id):
    from level_engine import normalize_package_name

    mapping = get_partner_client_mapping(partner_id)
    client_id = str(mapping.get("client_id") or "").strip()
    session_id = str(mapping.get("session_id") or "").strip()

    default_snapshot = {
        "partner_id": normalize_partner_id(partner_id),
        "client_id": client_id,
        "session_id": session_id,
        "plan_name": normalize_package_name(mapping.get("plan_name") or ""),
        "subscription_status": "",
        "stripe_subscription_id": mapping.get("stripe_subscription_id") or "",
        "package_amount": mapping.get("package_amount") or "",
    }

    table = "subscriptions"

    if not _level_db_table_exists(table):
        return default_snapshot

    columns = _level_db_columns(table)

    plan_col = _pick_first_existing_column(
        columns,
        ["plan_name", "package_name", "plan", "package", "subscription_plan"]
    )

    status_col = _pick_first_existing_column(
        columns,
        ["status", "subscription_status", "state"]
    )

    client_col = _pick_first_existing_column(
        columns,
        ["client_id", "session_id", "user_id"]
    )

    session_col = _pick_first_existing_column(
        columns,
        ["session_id", "client_id", "user_id"]
    )

    stripe_col = _pick_first_existing_column(
        columns,
        ["stripe_subscription_id", "subscription_id"]
    )

    amount_col = _pick_first_existing_column(
        columns,
        ["package_amount", "amount", "price", "subscription_amount"]
    )

    if not client_col and not session_col:
        return default_snapshot

    select_cols = []

    for col in [plan_col, status_col, client_col, session_col, stripe_col, amount_col]:
        if col and col not in select_cols:
            select_cols.append(col)

    if not select_cols:
        return default_snapshot

    where_clauses = []
    params = []

    if client_id and client_col:
        where_clauses.append(f"{client_col}=?")
        params.append(client_id)

    if session_id and session_col:
        where_clauses.append(f"{session_col}=?")
        params.append(session_id)

    if not where_clauses:
        return default_snapshot

    query = (
        f"SELECT {', '.join(select_cols)} FROM {table} "
        f"WHERE {' OR '.join(where_clauses)} "
        "ORDER BY id DESC LIMIT 1"
    )

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(query, tuple(params))
        row = c.fetchone()
        conn.close()

        if not row:
            return default_snapshot

        values = dict(zip(select_cols, row))

        snapshot = dict(default_snapshot)

        if plan_col:
            snapshot["plan_name"] = normalize_package_name(values.get(plan_col) or snapshot["plan_name"])

        if status_col:
            snapshot["subscription_status"] = str(values.get(status_col) or "").strip().lower()

        if client_col:
            snapshot["client_id"] = str(values.get(client_col) or snapshot["client_id"] or "").strip()

        if session_col:
            snapshot["session_id"] = str(values.get(session_col) or snapshot["session_id"] or "").strip()

        if stripe_col:
            snapshot["stripe_subscription_id"] = str(values.get(stripe_col) or snapshot["stripe_subscription_id"] or "").strip()

        if amount_col:
            snapshot["package_amount"] = str(values.get(amount_col) or snapshot["package_amount"] or "").strip()

        return snapshot

    except Exception as error:
        print(f"PARTNER SUBSCRIPTION SNAPSHOT ERROR {error}", flush=True)
        return default_snapshot


def count_active_direct_paid_customers(partner_id):
    from level_engine import ACTIVE_SUBSCRIPTION_STATUSES

    partner_id = normalize_partner_id(partner_id)
    table = "subscriptions"

    if not partner_id or not _level_db_table_exists(table):
        return 0

    columns = _level_db_columns(table)

    source_col = _pick_first_existing_column(
        columns,
        ["source_partner_id", "sponsor_partner_id", "partner_id", "ref_partner_id"]
    )

    status_col = _pick_first_existing_column(
        columns,
        ["status", "subscription_status", "state"]
    )

    distinct_col = _pick_first_existing_column(
        columns,
        ["client_id", "session_id", "stripe_customer_id", "email"]
    )

    if not source_col:
        return 0

    if not distinct_col:
        distinct_col = source_col

    query = f"SELECT COUNT(DISTINCT {distinct_col}) FROM {table} WHERE {source_col}=?"
    params = [partner_id]

    if status_col:
        placeholders = ",".join(["?"] * len(ACTIVE_SUBSCRIPTION_STATUSES))
        query += f" AND LOWER({status_col}) IN ({placeholders})"
        params.extend(sorted(ACTIVE_SUBSCRIPTION_STATUSES))

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(query, tuple(params))
        row = c.fetchone()
        conn.close()

        return int(row[0] or 0) if row else 0

    except Exception as error:
        print(f"COUNT ACTIVE DIRECT CUSTOMERS ERROR {error}", flush=True)
        return 0


def record_partner_course_purchase(
    partner_id,
    course_code,
    course_name="",
    amount=0,
    currency="USD",
    status="paid",
    stripe_payment_id="manual",
    notes="",
    paid_at="",
):
    from level_engine import normalize_course_code

    init_level_qualification_tables()

    partner_id = normalize_partner_id(partner_id)
    course_code = normalize_course_code(course_code)
    status = str(status or "paid").strip().lower()
    stripe_payment_id = str(stripe_payment_id or "manual").strip()

    if not partner_id or not course_code:
        return {
            "status": "error",
            "message": "partner_id and course_code are required"
        }

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        INSERT OR IGNORE INTO course_purchases (
            partner_id,
            course_code,
            course_name,
            amount,
            currency,
            status,
            stripe_payment_id,
            notes,
            paid_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            partner_id,
            course_code,
            str(course_name or "").strip(),
            float(amount or 0),
            str(currency or "USD").strip().upper(),
            status,
            stripe_payment_id,
            str(notes or "").strip(),
            str(paid_at or "").strip(),
        )
    )

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "partner_id": partner_id,
        "course_code": course_code,
        "stripe_payment_id": stripe_payment_id,
    }


def get_partner_purchased_courses(partner_id):
    init_level_qualification_tables()

    partner_id = normalize_partner_id(partner_id)

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT DISTINCT course_code
        FROM course_purchases
        WHERE partner_id=?
          AND LOWER(status) IN ('paid', 'active', 'completed')
          -- refunded_at is a real timestamp column here. SQLite compared it
          -- to '' happily; PostgreSQL rejects the whole query with
          -- "invalid input syntax for type timestamp with time zone".
          -- IS NULL already covers "never refunded".
          AND refunded_at IS NULL
        """,
        (partner_id,)
    )

    rows = c.fetchall()
    conn.close()

    return [row[0] for row in rows if row and row[0]]


def calculate_partner_level_from_database(partner_id):
    from level_engine import calculate_partner_level_progress

    partner_id = normalize_partner_id(partner_id)

    subscription = get_partner_subscription_snapshot(partner_id)
    active_direct_customers = count_active_direct_paid_customers(partner_id)
    purchased_courses = get_partner_purchased_courses(partner_id)

    progress = calculate_partner_level_progress(
        package_name=subscription.get("plan_name") or "",
        active_direct_customers=active_direct_customers,
        purchased_courses=purchased_courses,
        subscription_status=subscription.get("subscription_status") or "",
    )

    progress["partner_id"] = partner_id
    progress["client_id"] = subscription.get("client_id") or ""
    progress["session_id"] = subscription.get("session_id") or ""
    progress["stripe_subscription_id"] = subscription.get("stripe_subscription_id") or ""
    progress["package_amount"] = subscription.get("package_amount") or ""

    return progress


def save_partner_level_progress(partner_id, progress):
    import json

    init_level_qualification_tables()

    partner_id = normalize_partner_id(partner_id)

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO partner_level_progress (
            partner_id,
            current_level,
            current_level_name,
            next_level,
            next_level_name,
            current_package,
            subscription_status,
            subscription_active,
            commission_eligible,
            active_direct_customers,
            purchased_courses,
            missing_requirements,
            progress_json,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(partner_id) DO UPDATE SET
            current_level=excluded.current_level,
            current_level_name=excluded.current_level_name,
            next_level=excluded.next_level,
            next_level_name=excluded.next_level_name,
            current_package=excluded.current_package,
            subscription_status=excluded.subscription_status,
            subscription_active=excluded.subscription_active,
            commission_eligible=excluded.commission_eligible,
            active_direct_customers=excluded.active_direct_customers,
            purchased_courses=excluded.purchased_courses,
            missing_requirements=excluded.missing_requirements,
            progress_json=excluded.progress_json,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            partner_id,
            int(progress.get("current_level") or 0),
            progress.get("current_level_name") or "",
            progress.get("next_level"),
            progress.get("next_level_name") or "",
            progress.get("current_package") or "",
            progress.get("subscription_status") or "",
            1 if progress.get("subscription_active") else 0,
            1 if progress.get("commission_eligible") else 0,
            int(progress.get("active_direct_customers") or 0),
            json.dumps(progress.get("purchased_courses") or [], ensure_ascii=False),
            json.dumps(progress.get("missing_requirements") or [], ensure_ascii=False),
            json.dumps(progress, ensure_ascii=False),
        )
    )

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "partner_id": partner_id,
        "current_level": progress.get("current_level"),
        "commission_eligible": progress.get("commission_eligible"),
    }


def calculate_and_save_partner_level_progress(partner_id):
    progress = calculate_partner_level_from_database(partner_id)
    save_result = save_partner_level_progress(partner_id, progress)
    progress["save_result"] = save_result
    return progress


def get_saved_partner_level_progress(partner_id):
    import json

    init_level_qualification_tables()

    partner_id = normalize_partner_id(partner_id)

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT progress_json
        FROM partner_level_progress
        WHERE partner_id=?
        LIMIT 1
        """,
        (partner_id,)
    )

    row = c.fetchone()
    conn.close()

    if not row or not row[0]:
        return {}

    try:
        return json.loads(row[0])
    except Exception:
        return {}


def is_partner_commission_eligible_from_database(partner_id, commission_depth):
    from level_engine import is_partner_eligible_for_commission_depth

    progress = calculate_and_save_partner_level_progress(partner_id)

    return is_partner_eligible_for_commission_depth(
        current_level=progress.get("current_level") or 0,
        commission_depth=commission_depth,
        subscription_status=progress.get("subscription_status") or "",
    )

def _level_number_to_label(level_value):
    try:
        level_number = int(level_value or 0)
    except (TypeError, ValueError):
        level_number = 0

    if level_number <= 0:
        return "Level 0"

    return f"Level {level_number}"


def _course_code_to_display_name(course_code):
    # The three codes the level rules require are the last three below.
    # The older sales_skills_89 / change_journey_149 entries are kept so that
    # any partner who already bought under the old naming still resolves to a
    # readable name instead of a raw code.
    mapping = {
        "marketing_course_free": "كورس التسويق المجاني",
        "pro_marketer_mindset_69": "كورس عقلية المسوق المحترف 69$",
        "sales_skills_89": "كورس مهارات المبيعات 89$",
        "change_journey_149": "كورس رحلة التغيير 149$",
        "sales_secrets_999": "كورس أسرار المبيعات 999$",
        "change_journey_299": "كورس رحلة التغيير 299$",
    }

    return mapping.get(str(course_code or "").strip(), str(course_code or "").strip())


def _build_required_course_text(required_courses):
    required_courses = required_courses or []

    if not required_courses:
        return "لا يوجد كورس مدفوع مطلوب لهذا المستوى"

    return " + ".join(
        _course_code_to_display_name(course)
        for course in required_courses
        if course
    )


def sync_partner_level_progress_to_google_sheet(partner_id):
    """
    يحسب مستوى الشريك الحقيقي من قاعدة البيانات ثم يرسله إلى Google Sheets / MLMLevels.
    هذا لا يدفع عمولات. فقط يحدّث حالة المستوى والتقدم.
    """
    partner_id = normalize_partner_id(partner_id)

    if not partner_id:
        return {
            "status": "skipped",
            "message": "partner_id is missing"
        }

    if str(partner_id).lower() == str(COMPANY_OWNER_PARTNER_ID).lower():
        return {
            "status": "skipped",
            "message": "company owner does not need MLM level sync",
            "partner_id": partner_id
        }

    try:
        progress = calculate_and_save_partner_level_progress(partner_id)

        current_level_number = int(progress.get("current_level") or 0)
        current_level_label = _level_number_to_label(current_level_number)

        next_level_number = progress.get("next_level")
        next_level_label = _level_number_to_label(next_level_number) if next_level_number else ""

        active_direct_customers = int(progress.get("active_direct_customers") or 0)

        required_sales = "0"
        required_course_workshop = ""

        if next_level_number:
            level_details = progress.get("level_details") or []
            next_detail = level_details[int(next_level_number) - 1] if len(level_details) >= int(next_level_number) else {}

            required_sales = str(next_detail.get("min_active_direct_customers") or "0")
            required_course_workshop = _build_required_course_text(
                next_detail.get("required_courses") or []
            )
        else:
            required_sales = str(active_direct_customers)
            required_course_workshop = "تم الوصول إلى أعلى مستوى"

        level_status = "active" if progress.get("commission_eligible") else "inactive"

        missing_requirements = progress.get("missing_requirements") or []
        current_package = progress.get("current_package") or ""
        subscription_status = progress.get("subscription_status") or ""
        commission_eligible = "yes" if progress.get("commission_eligible") else "no"

        sheet_result = send_mlm_level_to_google_sheet(
            partner_id=partner_id,
            current_level=current_level_label,
            required_sales=required_sales,
            completed_sales=str(active_direct_customers),
            required_course_workshop=required_course_workshop,
            level_status=level_status,
            next_level=next_level_label,
            partner_rank=current_level_label,
            current_package=current_package,
            subscription_status=subscription_status,
            commission_eligible=commission_eligible,
            missing_requirements=missing_requirements,
            last_updated=current_timestamp()
        )

        print(
            f"PARTNER LEVEL SYNC ✅ partner_id={partner_id} level={current_level_label} next={next_level_label} package={current_package} subscription_status={subscription_status} commission_eligible={commission_eligible} result={sheet_result}",
            flush=True
        )

        progress["mlm_level_sheet_result"] = sheet_result

        return {
            "status": "success",
            "partner_id": partner_id,
            "progress": progress,
            "sheet_result": sheet_result,
        }

    except Exception as error:
        print(f"PARTNER LEVEL SYNC ERROR ❌ partner_id={partner_id} error={error}", flush=True)

        return {
            "status": "error",
            "partner_id": partner_id,
            "message": str(error),
        }


# ===== ALSAAB_WORDPRESS_ACCOUNT_LINK_V1 START =====

def send_wordpress_account_link(
    email="",
    partner_id="",
    client_id="",
    plan_name="",
    subscription_status="active",
    name="",
):
    """
    يربط أو ينشئ WordPress user تلقائياً بعد الدفع.
    يستخدم نفس DASHBOARD_SSO_SECRET للتوقيع بين Render و WordPress.
    """
    import os
    import json
    import time
    import hmac
    import hashlib
    import urllib.request
    import urllib.error

    email = str(email or "").strip()
    partner_id = normalize_partner_id(partner_id)
    client_id = str(client_id or partner_id or "").strip()

    if not email:
        return {
            "status": "skipped",
            "message": "email is missing",
            "partner_id": partner_id,
            "client_id": client_id,
        }

    if not partner_id or str(partner_id).lower() == str(COMPANY_OWNER_PARTNER_ID).lower():
        return {
            "status": "skipped",
            "message": "regular partner_id is missing",
            "partner_id": partner_id,
            "client_id": client_id,
        }

    secret = os.getenv("DASHBOARD_SSO_SECRET", "").strip()

    if not secret:
        return {
            "status": "skipped",
            "message": "DASHBOARD_SSO_SECRET is missing",
            "partner_id": partner_id,
            "client_id": client_id,
        }

    wordpress_base_url = os.getenv("WORDPRESS_BASE_URL", "https://alsaab.io").strip().rstrip("/")
    endpoint = f"{wordpress_base_url}/wp-json/alsaab/v1/link-account"

    payload = {
        "email": email,
        "partner_id": partner_id,
        "client_id": client_id,
        "plan_name": str(plan_name or "").strip(),
        "subscription_status": str(subscription_status or "active").strip(),
        "name": str(name or "").strip(),
    }

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature_base = (timestamp + ".").encode("utf-8") + body

    signature = hmac.new(
        secret.encode("utf-8"),
        signature_base,
        hashlib.sha256
    ).hexdigest()

    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-ALSAAB-Timestamp": timestamp,
            "X-ALSAAB-Signature": signature,
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")

        try:
            result = json.loads(raw)
        except Exception:
            result = {
                "status": "unknown",
                "raw": raw,
            }

        return {
            "status": "success",
            "endpoint": endpoint,
            "partner_id": partner_id,
            "client_id": client_id,
            "email": email,
            "wordpress_result": result,
        }

    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")

        return {
            "status": "error",
            "message": f"WordPress HTTP error {error.code}",
            "raw": raw,
            "endpoint": endpoint,
            "partner_id": partner_id,
            "client_id": client_id,
            "email": email,
        }

    except Exception as error:
        return {
            "status": "error",
            "message": str(error),
            "endpoint": endpoint,
            "partner_id": partner_id,
            "client_id": client_id,
            "email": email,
        }

# ===== ALSAAB_WORDPRESS_ACCOUNT_LINK_V1 END =====


# ===== ALSAAB_ENTRY_DATABASE_SAFE_V1 START =====
# Safe Entry package support for database.py.
# This block is additive and does not edit existing functions manually.

ENTRY_PLAN_KEY = "entry"

ENTRY_PLAN_ALIASES = {
    "entry": "entry",
    "دخول": "entry",
    "الدخول": "entry",
    "باقة الدخول": "entry",
    "entry package": "entry",
}

ENTRY_PLAN_LIMITS = {
    "monthly_reply_limit": 500,
    "customer_reply_limit": 500,
    "owner_advisory_reply_limit": 0,
    "max_payment_links": 1,
    "max_product_images": 1,
    "max_product_image_groups": 1,
}

def _alsaab_entry_normalize_plan(value):
    raw = str(value or "").strip()

    if not raw:
        return ""

    raw_lower = raw.lower()

    if raw_lower in ENTRY_PLAN_ALIASES:
        return ENTRY_PLAN_ALIASES[raw_lower]

    if raw in ENTRY_PLAN_ALIASES:
        return ENTRY_PLAN_ALIASES[raw]

    return raw_lower

def _alsaab_entry_patch_known_limit_dicts():
    dict_names = [
        "PLAN_LIMITS",
        "PACKAGE_LIMITS",
        "USAGE_LIMITS",
        "REPLY_LIMITS",
        "MONTHLY_REPLY_LIMITS",
        "PLAN_REPLY_LIMITS",
        "PACKAGE_REPLY_LIMITS",
    ]

    for name in dict_names:
        value = globals().get(name)

        if not isinstance(value, dict):
            continue

        if "entry" in value:
            continue

        starter_value = value.get("starter")

        if isinstance(starter_value, int):
            value["entry"] = 500
        elif isinstance(starter_value, dict):
            entry_value = dict(starter_value)
            entry_value.update(ENTRY_PLAN_LIMITS)
            value["entry"] = entry_value
        else:
            value["entry"] = dict(ENTRY_PLAN_LIMITS)

def _alsaab_entry_patch_known_order_lists():
    list_names = [
        "PLAN_ORDER",
        "PACKAGE_ORDER",
    ]

    for name in list_names:
        value = globals().get(name)

        if isinstance(value, list) and "entry" not in value:
            value.insert(0, "entry")

def _alsaab_entry_wrap_normalizers():
    function_names = [
        "normalize_plan",
        "normalize_plan_name",
        "normalize_package",
        "normalize_package_name",
        "normalize_plan_key",
        "normalize_package_key",
    ]

    for function_name in function_names:
        old_function = globals().get(function_name)

        if not callable(old_function):
            continue

        if getattr(old_function, "_alsaab_entry_wrapped", False):
            continue

        def wrapper(value=None, *args, _old_function=old_function, **kwargs):
            normalized = _alsaab_entry_normalize_plan(value)

            if normalized == "entry":
                return "entry"

            return _old_function(value, *args, **kwargs)

        wrapper._alsaab_entry_wrapped = True
        globals()[function_name] = wrapper

def _alsaab_entry_wrap_limit_functions():
    function_names = [
        "get_plan_limits",
        "get_package_limits",
        "get_usage_limits",
        "get_reply_limits",
        "get_monthly_reply_limit",
        "get_customer_reply_limit",
        "get_owner_advisory_reply_limit",
        "get_max_payment_links",
        "get_max_product_images",
        "get_max_product_image_groups",
    ]

    for function_name in function_names:
        old_function = globals().get(function_name)

        if not callable(old_function):
            continue

        if getattr(old_function, "_alsaab_entry_wrapped", False):
            continue

        def wrapper(plan=None, *args, _old_function=old_function, _function_name=function_name, **kwargs):
            normalized = _alsaab_entry_normalize_plan(plan)

            if normalized == "entry":
                if "limits" in _function_name:
                    return dict(ENTRY_PLAN_LIMITS)

                if "owner_advisory" in _function_name:
                    return 0

                if "payment_links" in _function_name:
                    return 1

                if "product_image_groups" in _function_name:
                    return 1

                if "product_images" in _function_name:
                    return 1

                return 500

            return _old_function(plan, *args, **kwargs)

        wrapper._alsaab_entry_wrapped = True
        globals()[function_name] = wrapper

def get_entry_plan_limits():
    return dict(ENTRY_PLAN_LIMITS)

_al_saab_entry_patch_done = False

try:
    _alsaab_entry_patch_known_limit_dicts()
    _alsaab_entry_patch_known_order_lists()
    _alsaab_entry_wrap_normalizers()
    _alsaab_entry_wrap_limit_functions()
    _al_saab_entry_patch_done = True
except Exception as _entry_database_error:
    print(f"ENTRY DATABASE PATCH WARNING: {_entry_database_error}", flush=True)

# ===== ALSAAB_ENTRY_DATABASE_SAFE_V1 END =====

# ===== ALSAAB_DIAMOND_DATABASE_SAFE_V1 START =====

DIAMOND_PLAN_KEY = "diamond"

DIAMOND_PLAN_ALIASES = {
    "diamond": "diamond",
    "دايموند": "diamond",
    "الماسية": "diamond",
    "باقة الماسية": "diamond",
    "الباقة الماسية": "diamond",
}

DIAMOND_PLAN_LIMITS = {
    "monthly_reply_limit": 40000,
    "customer_reply_limit": 40000,
    "owner_advisory_reply_limit": 5000,
}

def _alsaab_diamond_normalize_plan(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw_lower = raw.lower()
    if raw_lower in DIAMOND_PLAN_ALIASES:
        return DIAMOND_PLAN_ALIASES[raw_lower]
    if raw in DIAMOND_PLAN_ALIASES:
        return DIAMOND_PLAN_ALIASES[raw]
    return raw_lower

def _alsaab_diamond_wrap_normalizers():
    function_names = [
        "normalize_plan_name",
        "normalize_plan",
        "normalize_package_name",
        "normalize_package",
    ]

    for function_name in function_names:
        old_function = globals().get(function_name)

        if not callable(old_function):
            continue

        if getattr(old_function, "_alsaab_diamond_wrapped", False):
            continue

        def wrapper(value=None, *args, _old_function=old_function, **kwargs):
            normalized = _alsaab_diamond_normalize_plan(value)
            if normalized == "diamond":
                return "diamond"
            return _old_function(value, *args, **kwargs)

        wrapper._alsaab_diamond_wrapped = True
        globals()[function_name] = wrapper

def _alsaab_diamond_wrap_limit_functions():
    function_names = [
        "get_plan_reply_limit",
        "get_plan_owner_advisory_reply_limit",
        "get_customer_reply_limit",
        "get_owner_advisory_reply_limit",
        "get_monthly_reply_limit",
    ]

    for function_name in function_names:
        old_function = globals().get(function_name)

        if not callable(old_function):
            continue

        if getattr(old_function, "_alsaab_diamond_wrapped", False):
            continue

        def wrapper(plan=None, *args, _old_function=old_function, _function_name=function_name, **kwargs):
            normalized = _alsaab_diamond_normalize_plan(plan)
            if normalized == "diamond":
                if "owner_advisory" in _function_name:
                    return 5000
                return 40000
            return _old_function(plan, *args, **kwargs)

        wrapper._alsaab_diamond_wrapped = True
        globals()[function_name] = wrapper

try:
    _alsaab_diamond_wrap_normalizers()
    _alsaab_diamond_wrap_limit_functions()
except Exception as _diamond_database_error:
    print(f"DIAMOND DATABASE PATCH WARNING: {_diamond_database_error}", flush=True)

# ===== ALSAAB_DIAMOND_DATABASE_SAFE_V1 END =====

