# database.py

import sqlite3
import json
import urllib.request
import urllib.error

try:
    from config import GOOGLE_SHEET_WEBHOOK_URL, GOOGLE_SHEET_TOKEN
except Exception:
    GOOGLE_SHEET_WEBHOOK_URL = ""
    GOOGLE_SHEET_TOKEN = ""


DB_NAME = "alsaab_ai.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


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

    add_column_if_missing(c, "leads", "user_type", "TEXT")
    add_column_if_missing(c, "leads", "business_name", "TEXT")
    add_column_if_missing(c, "leads", "email", "TEXT")
    add_column_if_missing(c, "leads", "country", "TEXT")

    c.execute("""
    CREATE TABLE IF NOT EXISTS client_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE,
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

    add_column_if_missing(c, "client_profiles", "general_description", "TEXT")

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


def send_lead_to_google_sheet(session_id, name, phone, state, status="new"):
    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "lead",
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


def send_client_profile_to_google_sheet(session_id, data):
    payload = {
        "token": GOOGLE_SHEET_TOKEN,
        "action": "client_profile",
        "session_id": session_id or "",
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


def save_lead(session_id, name, phone, state):
    conn = get_connection()
    c = conn.cursor()

    user_type = normalize_user_type(state)
    business_name = get_state_value(state, "business_name", "")
    business_type = get_state_value(state, "business_type", "")
    pain_point = get_state_value(state, "pain_point", "")
    channel = get_state_value(state, "channel", "website")
    email = get_state_value(state, "email", "") or get_state_value(state, "lead_email", "")
    country = get_state_value(state, "country", "")

    c.execute(
        "SELECT id FROM leads WHERE session_id=? AND phone=?",
        (session_id, phone)
    )
    existing = c.fetchone()

    is_new_lead = False

    if existing:
        c.execute(
            """
            UPDATE leads
            SET
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
                name,
                user_type,
                business_name,
                business_type,
                pain_point,
                channel,
                email,
                country,
                existing[0]
            )
        )
    else:
        c.execute(
            """
            INSERT INTO leads (
                session_id,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
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


def get_leads(limit=100):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            id,
            session_id,
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
            "name": row[2],
            "phone": row[3],
            "user_type": row[4],
            "business_name": row[5],
            "business_type": row[6],
            "pain_point": row[7],
            "channel": row[8],
            "status": row[9],
            "email": row[10],
            "country": row[11],
            "created_at": row[12],
        })

    return leads


def save_client_profile(session_id, data):
    print("SAVE CLIENT PROFILE START ✅", flush=True)
    print(f"SAVE CLIENT PROFILE SESSION ✅ {session_id}", flush=True)
    print(f"SAVE CLIENT PROFILE DATA KEYS ✅ {list(data.keys())}", flush=True)

    conn = get_connection()
    c = conn.cursor()

    raw_data = json.dumps(data, ensure_ascii=False)

    c.execute(
        "SELECT id FROM client_profiles WHERE session_id=?",
        (session_id,)
    )
    existing = c.fetchone()

    values = (
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
            WHERE session_id=?
            """,
            values + (session_id,)
        )
    else:
        print("CLIENT PROFILE NEW ✅ inserting SQLite", flush=True)

        c.execute(
            """
            INSERT INTO client_profiles (
                session_id,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id,) + values
        )

    conn.commit()
    conn.close()

    print("CLIENT PROFILE SAVED TO SQLITE ✅", flush=True)

    sheet_result = send_client_profile_to_google_sheet(session_id, data)

    if sheet_result:
        print("CLIENT PROFILE SENT TO GOOGLE SHEET ✅", flush=True)
    else:
        print("CLIENT PROFILE GOOGLE SHEET SEND FAILED ❌", flush=True)


def get_client_profile(session_id):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
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
        WHERE session_id=?
        """,
        (session_id,)
    )

    row = c.fetchone()
    conn.close()

    if not row:
        return {}

    return {
        "business_name": row[0],
        "business_type": row[1],
        "general_description": row[2],
        "products": row[3],
        "prices": row[4],
        "offers": row[5],
        "ordering": row[6],
        "whatsapp": row[7],
        "areas": row[8],
        "faqs": row[9],
        "objections": row[10],
        "tone": row[11],
        "raw_data": row[12],
    }


def get_client_profiles(limit=100):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            id,
            session_id,
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
            "business_name": row[2],
            "business_type": row[3],
            "general_description": row[4],
            "products": row[5],
            "prices": row[6],
            "offers": row[7],
            "ordering": row[8],
            "whatsapp": row[9],
            "areas": row[10],
            "faqs": row[11],
            "objections": row[12],
            "tone": row[13],
            "updated_at": row[14],
        })

    return profiles


def export_leads_for_google_sheets():
    leads = get_leads(limit=1000)

    rows = [
        [
            "ID",
            "Session ID",
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