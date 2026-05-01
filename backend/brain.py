# brain.py

import re
from openai import OpenAI

from config import OPENAI_API_KEY, MODEL_NAME, REPLY_MAX_TOKENS
from state import create_state, update_state
from prompt_builder import build_prompt
from database import (
    get_last_messages,
    save_message,
    save_lead,
    get_client_profile,
)
from training_engine import start_training, handle_training
from partner_engine import (
    is_partner_registration_request,
    is_partner_registration_active,
    start_partner_registration,
    handle_partner_registration,
)

client = OpenAI(api_key=OPENAI_API_KEY)

# State منفصل لكل جلسة عشان التدريب ما يضيع بين الرسائل
session_states = {}


def get_session_state(session_id):
    if session_id not in session_states:
        session_states[session_id] = create_state()
    return session_states[session_id]


def set_session_state(session_id, new_state):
    session_states[session_id] = new_state


def format_history(messages):
    history_text = ""
    for role, content in messages:
        if role == "user":
            history_text += f"العميل: {content}\n"
        elif role == "client_data":
            history_text += f"بيانات المشروع: {content}\n"
        else:
            history_text += f"المساعد: {content}\n"
    return history_text


def extract_phone(message):
    cleaned = message.replace(" ", "").replace("-", "").replace("+", "00")

    patterns = [
        r"00971\d{8,9}",
        r"971\d{8,9}",
        r"05\d{8}",
        r"5\d{8}",
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return match.group(0)

    return None


def clean_name_value(name):
    if not name:
        return None

    name = str(name).strip()

    separators = ["\n", ".", ",", "،", "؛", ":", "|", "-", "—"]
    for separator in separators:
        if separator in name:
            name = name.split(separator)[0].strip()

    continuation_patterns = [
        r"\s+وابغي\b",
        r"\s+وأبغي\b",
        r"\s+و أبغي\b",
        r"\s+وابي\b",
        r"\s+وأبي\b",
        r"\s+و أبي\b",
        r"\s+واريد\b",
        r"\s+وأريد\b",
        r"\s+و أريد\b",
        r"\s+واحتاج\b",
        r"\s+وأحتاج\b",
        r"\s+و أحتاج\b",
        r"\s+وعندي\b",
        r"\s+و عندي\b",
        r"\s+and\b",
    ]

    for pattern in continuation_patterns:
        name = re.split(pattern, name, maxsplit=1, flags=re.IGNORECASE)[0].strip()

    name = name.replace(".", "").replace(",", "").replace("،", "").strip()

    if not is_valid_name(name):
        return None

    return name


def is_valid_name(name):
    if not name:
        return False

    name = str(name).strip()

    if len(name) < 2:
        return False

    if len(name) > 40:
        return False

    if re.search(r"\d", name):
        return False

    if "@" in name or "http" in name.lower():
        return False

    words = name.split()

    if not (1 <= len(words) <= 4):
        return False

    blocked_keywords = [
        "ابغي",
        "أبغي",
        "ابي",
        "أبي",
        "اريد",
        "أريد",
        "احتاج",
        "أحتاج",
        "محتاج",
        "عندي",
        "مشروع",
        "مبيعات",
        "دخل",
        "اضافي",
        "إضافي",
        "باقات",
        "باقة",
        "سعر",
        "أسعار",
        "اشتراك",
        "الدفع",
        "بوت",
        "تدريب",
        "واتساب",
        "خدمة",
        "العملاء",
        "كيف",
        "ليش",
        "متى",
        "وين",
        "شو",
        "هل",
        "نظام",
        "شراكة",
        "عمولة",
        "عمولات",
        "affiliate",
        "partner",
        "referral",
        "mlm",
        "package",
        "price",
        "pricing",
    ]

    lowered = name.lower()

    for keyword in blocked_keywords:
        if keyword.lower() in lowered:
            return False

    return True


def extract_name(message):
    msg = message.strip()

    name_patterns = [
        r"اسمي\s+(.+)",
        r"إسمي\s+(.+)",
        r"أنا\s+(.+)",
        r"انا\s+(.+)",
        r"my name is\s+(.+)",
        r"i am\s+(.+)",
        r"i'm\s+(.+)",
    ]

    for pattern in name_patterns:
        match = re.search(pattern, msg, re.IGNORECASE)
        if match:
            name = clean_name_value(match.group(1))
            if name:
                return name

    return None


def extract_direct_name_answer(message):
    """
    يستخدم لما البوت يكون سأل العميل عن اسمه،
    والعميل يرد باسم فقط مثل: أحمد / محمد البلوشي.
    """
    msg = str(message or "").strip()

    msg = msg.replace("اسمي", "").replace("إسمي", "").strip()
    msg = msg.replace("أنا", "").replace("انا", "").strip()

    return clean_name_value(msg)


def is_simple_greeting(message):
    msg = str(message or "").lower().strip()

    greetings = [
        "مرحبا",
        "هلا",
        "السلام عليكم",
        "السلام عليكم ورحمة الله",
        "هاي",
        "hi",
        "hello",
        "hey",
        "هلا والله",
        "مرحبا الساع",
    ]

    return msg in greetings


def set_customer_name(current_state, name):
    if not name:
        return

    current_state["customer_name"] = name
    current_state["lead_name"] = name
    current_state["name_captured"] = True
    current_state["awaiting_customer_name"] = False
    current_state["name_asked"] = True


def set_customer_phone(current_state, phone):
    if not phone:
        return

    current_state["lead_phone"] = phone
    current_state["customer_phone"] = phone
    current_state["phone_captured"] = True
    current_state["awaiting_customer_phone"] = False
    current_state["phone_asked"] = True


def get_customer_name(current_state):
    return (
        current_state.get("customer_name")
        or current_state.get("lead_name")
        or ""
    )


def get_customer_phone(current_state):
    return (
        current_state.get("customer_phone")
        or current_state.get("lead_phone")
        or ""
    )


def save_lead_if_ready(session_id, current_state):
    """
    يحفظ العميل في SQLite + Google Sheets لما يكون عندنا الاسم والرقم.
    """
    lead_name = current_state.get("lead_name") or current_state.get("customer_name")
    lead_phone = current_state.get("lead_phone") or current_state.get("customer_phone")

    if lead_name and lead_phone:
        save_lead(
            session_id=session_id,
            name=lead_name,
            phone=lead_phone,
            state=current_state
        )

        print(
            f"LEAD CAPTURE SAVED ✅ name={lead_name} phone={lead_phone}",
            flush=True
        )

        return True

    return False


def update_lead_data(message, session_id, current_state):
    extracted_name = extract_name(message)
    extracted_phone = extract_phone(message)

    if extracted_name:
        current_state["lead_name"] = extracted_name
        current_state["customer_name"] = extracted_name
        current_state["name_captured"] = True

    if extracted_phone:
        current_state["lead_phone"] = extracted_phone
        current_state["customer_phone"] = extracted_phone
        current_state["phone_captured"] = True

    save_lead_if_ready(session_id, current_state)


def load_client_profile_into_state(session_id, current_state):
    """
    يسترجع بيانات المشروع المدربة من قاعدة البيانات.
    هذا لا يغيّر أسلوب الرد، فقط يضيف معرفة للبوت.
    """
    profile = get_client_profile(session_id)

    if profile:
        clean_profile = {
            key: value
            for key, value in profile.items()
            if value and key != "raw_data"
        }

        if clean_profile:
            current_state["client_data"] = clean_profile

            if clean_profile.get("client_id"):
                current_state["client_id"] = clean_profile.get("client_id")


def build_name_context(current_state):
    customer_name = get_customer_name(current_state)

    if not customer_name:
        return ""

    return (
        f"اسم العميل: {customer_name}\n"
        "استخدم اسم العميل باحتراف وباعتدال داخل الرد، بدون مبالغة أو تكرار زائد.\n"
    )


def think(message, session_id):
    current_state = get_session_state(session_id)
    msg = message.lower().strip()

    # مهم: نخزن session_id داخل state عشان prompt_builder يقدر يبني روابط الدفع الداخلية
    current_state["session_id"] = session_id

    print(f"THINK CALLED ✅ session_id={session_id}")
    print(f"CURRENT MODE ✅ mode={current_state.get('mode')}")

    # =========================
    # TRAINING MODE START
    # =========================

    if msg in ["تدريب", "تدريب البوت", "/train", "train"]:
        print("TRAINING COMMAND DETECTED ✅")
        reply = start_training(current_state)
        set_session_state(session_id, current_state)
        return reply

    # =========================
    # TRAINING MODE LOCKED
    # =========================

    if current_state.get("mode") == "training":
        print("TRAINING MODE ACTIVE ✅")

        reply = handle_training(message, current_state, session_id)

        # لما يخلص التدريب
        if current_state.get("mode") == "sales":
            print("TRAINING MOVED TO SALES ✅")

            client_data = current_state.get("client_data", {})

            if client_data:
                print("SAVING CLIENT DATA INTO MESSAGE HISTORY ✅")

                for key, value in client_data.items():
                    save_message(session_id, "client_data", f"{key}: {value}")

        set_session_state(session_id, current_state)
        return reply

    # =========================
    # PARTNER REGISTRATION MODE
    # =========================

    if is_partner_registration_active(current_state):
        print("PARTNER REGISTRATION MODE ACTIVE ✅", flush=True)

        reply = handle_partner_registration(
            message=message,
            state=current_state,
            session_id=session_id
        )

        set_session_state(session_id, current_state)
        return reply

    # =========================
    # PARTNER REGISTRATION START
    # =========================

    if is_partner_registration_request(message):
        print("PARTNER REGISTRATION REQUEST DETECTED ✅", flush=True)

        reply = start_partner_registration(
            state=current_state,
            session_id=session_id
        )

        set_session_state(session_id, current_state)
        return reply

    # =========================
    # CUSTOMER NAME + PHONE CAPTURE
    # =========================

    message_to_process = message

    extracted_phone_from_message = extract_phone(message)

    if extracted_phone_from_message and not get_customer_phone(current_state):
        set_customer_phone(current_state, extracted_phone_from_message)
        save_lead_if_ready(session_id, current_state)

    if not get_customer_name(current_state):
        extracted_name_from_message = extract_name(message)

        if extracted_name_from_message:
            set_customer_name(current_state, extracted_name_from_message)

        elif current_state.get("awaiting_customer_name"):
            direct_name = extract_direct_name_answer(message)

            current_state["awaiting_customer_name"] = False
            current_state["name_asked"] = True

            if direct_name:
                set_customer_name(current_state, direct_name)

                pending_message = current_state.pop("pending_message_after_name", "")

                if pending_message:
                    current_state["pending_message_after_phone"] = pending_message

                print(f"CUSTOMER NAME CAPTURED ✅ name={direct_name}", flush=True)

            else:
                current_state["name_skipped"] = True
                current_state.pop("pending_message_after_name", None)

        elif not current_state.get("name_asked"):
            current_state["name_asked"] = True
            current_state["awaiting_customer_name"] = True
            current_state["pending_message_after_name"] = message

            reply = "هلا وسهلا 👋 قبل لا أساعدك بشكل أدق، شو اسمك الكريم؟"
            set_session_state(session_id, current_state)
            return reply

    if get_customer_name(current_state) and not get_customer_phone(current_state):
        extracted_phone_from_message = extract_phone(message)

        if extracted_phone_from_message:
            set_customer_phone(current_state, extracted_phone_from_message)
            save_lead_if_ready(session_id, current_state)

            pending_message = current_state.pop("pending_message_after_phone", "")

            if pending_message and not is_simple_greeting(pending_message):
                message_to_process = pending_message
            else:
                customer_name = get_customer_name(current_state)
                reply = (
                    f"تمام يا {customer_name}، تم حفظ بيانات التواصل ✅\n\n"
                    "شو أكثر شي تبغي تطوره حالياً: مبيعات مشروعك ولا دخل إضافي لك؟"
                )
                set_session_state(session_id, current_state)
                return reply

        elif current_state.get("awaiting_customer_phone"):
            reply = (
                "اكتب رقم الواتساب عشان نحفظ بياناتك ونتابع معاك بشكل مرتب ✅\n\n"
                "مثال: 0500000000"
            )
            set_session_state(session_id, current_state)
            return reply

        elif not current_state.get("phone_asked"):
            current_state["phone_asked"] = True
            current_state["awaiting_customer_phone"] = True

            if not current_state.get("pending_message_after_phone"):
                current_state["pending_message_after_phone"] = message_to_process

            customer_name = get_customer_name(current_state)
            reply = (
                f"تمام يا {customer_name}، تشرفت فيك 👋\n\n"
                "عشان نقدر نتابع معاك لو انقطع الشات، اكتب رقم الواتساب؟"
            )
            set_session_state(session_id, current_state)
            return reply

    # =========================
    # SALES MODE
    # =========================

    print("SALES MODE ACTIVE ✅")

    existing_customer_name = get_customer_name(current_state)
    existing_customer_phone = get_customer_phone(current_state)
    existing_partner_id = current_state.get("partner_id", "")
    existing_partner_referral_link = current_state.get("partner_referral_link", "")
    existing_partner_rank = current_state.get("partner_rank", "")

    current_state = update_state(message_to_process, current_state)

    # مهم: نعيد تثبيت session_id بعد update_state عشان ما يضيع إذا رجّع state جديد
    current_state["session_id"] = session_id

    # نحافظ على اسم ورقم العميل إذا update_state رجّع state جديد
    if existing_customer_name:
        current_state["customer_name"] = existing_customer_name
        current_state["lead_name"] = existing_customer_name

    if existing_customer_phone:
        current_state["customer_phone"] = existing_customer_phone
        current_state["lead_phone"] = existing_customer_phone

    # نحافظ على بيانات الشريك إذا update_state رجّع state جديد
    if existing_partner_id:
        current_state["partner_id"] = existing_partner_id

    if existing_partner_referral_link:
        current_state["partner_referral_link"] = existing_partner_referral_link

    if existing_partner_rank:
        current_state["partner_rank"] = existing_partner_rank

    # استرجاع بيانات المشروع المدربة إن وجدت
    load_client_profile_into_state(session_id, current_state)

    # Lead Capture خلف الكواليس
    update_lead_data(message, session_id, current_state)

    history = get_last_messages(session_id, limit=6)
    history_text = format_history(history)

    name_context = build_name_context(current_state)

    if name_context:
        history_text = name_context + "\n" + history_text

    prompt = build_prompt(message_to_process, current_state, history_text)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": message_to_process}
        ],
        temperature=0.7,
        max_tokens=REPLY_MAX_TOKENS
    )

    reply = response.choices[0].message.content.strip()

    set_session_state(session_id, current_state)

    return reply