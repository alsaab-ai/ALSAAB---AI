# database.py

import sqlite3
import json

DB_NAME = "alsaab_ai.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


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
        business_type TEXT,
        pain_point TEXT,
        channel TEXT,
        status TEXT DEFAULT 'new',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS client_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE,
        business_name TEXT,
        business_type TEXT,
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

    conn.commit()
    conn.close()


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


def save_lead(session_id, name, phone, state):
    conn = get_connection()
    c = conn.cursor()

    business_type = state.get("business_type")
    pain_point = state.get("pain_point")
    channel = state.get("channel", "website")

    c.execute(
        "SELECT id FROM leads WHERE session_id=? AND phone=?",
        (session_id, phone)
    )
    existing = c.fetchone()

    if existing:
        c.execute(
            """
            UPDATE leads
            SET name=?, business_type=?, pain_point=?, channel=?
            WHERE id=?
            """,
            (name, business_type, pain_point, channel, existing[0])
        )
    else:
        c.execute(
            """
            INSERT INTO leads (
                session_id, name, phone, business_type, pain_point, channel
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, name, phone, business_type, pain_point, channel)
        )

    conn.commit()
    conn.close()


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
            business_type,
            pain_point,
            channel,
            status,
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
            "business_type": row[4],
            "pain_point": row[5],
            "channel": row[6],
            "status": row[7],
            "created_at": row[8],
        })

    return leads


def save_client_profile(session_id, data):
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
        c.execute(
            """
            UPDATE client_profiles
            SET
                business_name=?,
                business_type=?,
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
        c.execute(
            """
            INSERT INTO client_profiles (
                session_id,
                business_name,
                business_type,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id,) + values
        )

    conn.commit()
    conn.close()


def get_client_profile(session_id):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            business_name,
            business_type,
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
        "products": row[2],
        "prices": row[3],
        "offers": row[4],
        "ordering": row[5],
        "whatsapp": row[6],
        "areas": row[7],
        "faqs": row[8],
        "objections": row[9],
        "tone": row[10],
        "raw_data": row[11],
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
            "products": row[4],
            "prices": row[5],
            "offers": row[6],
            "ordering": row[7],
            "whatsapp": row[8],
            "areas": row[9],
            "faqs": row[10],
            "objections": row[11],
            "tone": row[12],
            "updated_at": row[13],
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
            "Business Type",
            "Pain Point",
            "Channel",
            "Status",
            "Created At",
        ]
    ]

    for lead in leads:
        rows.append([
            lead["id"],
            lead["session_id"],
            lead["name"],
            lead["phone"],
            lead["business_type"],
            lead["pain_point"],
            lead["channel"],
            lead["status"],
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