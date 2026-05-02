# partner_engine.py

import re

from database import (
    send_partner_to_google_sheet,
    save_lead,
    get_effective_client_id,
)

try:
    from config import (
        COMPANY_OWNER_PARTNER_ID,
        MLM_SPONSOR_RULES,
        MLM_SOURCE_OPTIONS,
        MLM_REGISTRATION_MESSAGES,
    )
except Exception:
    COMPANY_OWNER_PARTNER_ID = "alsaab"

    MLM_SPONSOR_RULES = {
        "require_sponsor_for_partner_registration": True,
        "owner_partner_id": COMPANY_OWNER_PARTNER_ID,
        "owner_id_is_company_income": True,
        "do_not_auto_assign_owner_before_asking_source": True,
        "ask_source_before_owner_assignment": True,
        "prevent_empty_sponsor": True,
        "prevent_invalid_sponsor": True,
    }

    MLM_SOURCE_OPTIONS = {
        "direct_partner": {
            "name_ar": "عن طريق شريك",
            "requires_partner_id": True,
            "example": "ALS-P00025"
        },
        "social_media": {
            "name_ar": "السوشيال ميديا",
            "requires_partner_id": False,
            "default_partner_id": COMPANY_OWNER_PARTNER_ID
        },
        "website": {
            "name_ar": "الموقع",
            "requires_partner_id": False,
            "default_partner_id": COMPANY_OWNER_PARTNER_ID
        },
        "advertisement": {
            "name_ar": "إعلان",
            "requires_partner_id": False,
            "default_partner_id": COMPANY_OWNER_PARTNER_ID
        },
        "company_direct": {
            "name_ar": "تواصل مباشر مع الشركة",
            "requires_partner_id": False,
            "default_partner_id": COMPANY_OWNER_PARTNER_ID
        },
        "event_or_seminar": {
            "name_ar": "ندوة أو فعالية",
            "requires_partner_id": False,
            "default_partner_id": COMPANY_OWNER_PARTNER_ID
        }
    }

    MLM_REGISTRATION_MESSAGES = {
        "ask_source_ar": (
            "قبل ما أكمل تسجيلك كشريك، لازم نربط تسجيلك بالشخص أو المصدر اللي عرّفك على النظام عشان نحفظ الحقوق بدقة.\n\n"
            "من وين عرفت ALSAAB AI؟\n"
            "- عن طريق شخص / شريك\n"
            "- السوشيال ميديا\n"
            "- الموقع\n"
            "- إعلان\n"
            "- ندوة أو فعالية\n"
            "- تواصل مباشر مع الشركة"
        ),
        "ask_sponsor_id_ar": (
            "اكتب Partner ID الخاص بالشخص اللي عرفك على النظام.\n\n"
            "مثال:\n"
            "ALS-P00025\n\n"
            "مهم: بعد التسجيل، تغيير المعرّف يحتاج مراجعة إدارية عشان نحفظ الحقوق."
        ),
        "use_owner_id_ar": (
            "تمام، بما إنك عرفت النظام من مصدر تابع للشركة، بنربط تسجيلك بمعرف الشركة:\n\n"
            f"{COMPANY_OWNER_PARTNER_ID}\n\n"
            "هذا يحفظ التتبع بشكل صحيح داخل النظام."
        ),
        "invalid_sponsor_ar": (
            "لازم يكون عندك Partner ID صحيح للشخص اللي عرفك على النظام.\n\n"
            "إذا عرفتنا من السوشيال ميديا أو الموقع أو إعلان أو من الشركة مباشرة، بنستخدم معرف الشركة."
        )
    }


PARTNER_REGISTRATION_TRIGGERS = [
    "أبغي أسجل كشريك",
    "ابي اسجل كشريك",
    "ابغي اسجل كشريك",
    "أريد أسجل كشريك",
    "اريد اسجل كشريك",
    "تسجيل شريك",
    "سجلني كشريك",
    "أبغي أدخل نظام الشراكة",
    "ابي ادخل نظام الشراكة",
    "ابغي ادخل نظام الشراكة",
    "أبغي أكون شريك",
    "ابي اكون شريك",
    "ابغي اكون شريك",
    "أبغي أربح معاكم",
    "ابي اربح معاكم",
    "ابغي اربح معاكم",
    "أبغي أدخل معاكم",
    "ابي ادخل معاكم",
    "ابغي ادخل معاكم",
    "partner registration",
    "register as partner",
    "affiliate registration",
    "become partner",
    "i want to be partner",
    "i want to become partner",
]

PARTNER_REGISTRATION_STEPS = [
    "partner_name",
    "phone",
    "email",
    "country",
    "has_business",
    "goal",
    "source",
    "sponsor",
]

INTERNATIONAL_PHONE_EXAMPLE = "+971523288001"


def normalize_text(value):
    return str(value or "").strip()


def normalize_lower(value):
    return normalize_text(value).lower()


def convert_arabic_digits(value):
    if value is None:
        return ""

    value = str(value)

    arabic_digits_map = {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }

    for arabic_digit, english_digit in arabic_digits_map.items():
        value = value.replace(arabic_digit, english_digit)

    return value


def normalize_international_phone(value):
    """
    يحول الرقم إلى صيغة دولية موحدة:
    +971523288001

    يقبل:
    +971523288001
    00971523288001
    971523288001

    يرفض:
    0500000000
    523288001
    """
    value = convert_arabic_digits(value)
    value = str(value or "").strip()

    if not value:
        return ""

    cleaned = re.sub(r"[\s\-\(\)\.\u200f\u200e]", "", value)

    if cleaned.startswith("+"):
        digits = cleaned[1:]

        if digits.isdigit() and 10 <= len(digits) <= 15:
            return "+" + digits

        return ""

    if cleaned.startswith("00"):
        digits = cleaned[2:]

        if digits.isdigit() and 10 <= len(digits) <= 15:
            return "+" + digits

        return ""

    if cleaned.isdigit():
        # نرفض الرقم المحلي بدون فتح خط
        if cleaned.startswith("0"):
            return ""

        # نقبل الرقم إذا واضح أنه يحتوي country code
        if 10 <= len(cleaned) <= 15:
            return "+" + cleaned

    return ""


def normalize_partner_id(value):
    value = normalize_text(value)

    if not value:
        return ""

    if value.lower() == str(COMPANY_OWNER_PARTNER_ID).lower():
        return COMPANY_OWNER_PARTNER_ID

    value_upper = value.upper()

    match = re.search(r"ALS-P\d+", value_upper)

    if match:
        return match.group(0).strip()

    return ""


def apply_sponsor_referral_to_state(state, sponsor_partner_id, source_type="", source_description=""):
    """
    يثبت مصدر الإحالة داخل state عشان save_lead يحفظه في Referrals.
    مهم جداً لتسجيل الشركاء: Partner جاب Partner.
    """
    normalized_sponsor = normalize_partner_id(sponsor_partner_id)

    if not normalized_sponsor:
        return ""

    state["source_partner_id"] = normalized_sponsor
    state["referrer_partner_id"] = normalized_sponsor
    state["referral_source_captured"] = True
    state["referral_context"] = "partner_registration"

    if source_type:
        state["referral_source_type"] = source_type

    if source_description:
        state["referral_source_description"] = source_description

    return normalized_sponsor


def is_partner_registration_request(message):
    msg = normalize_lower(message)

    if not msg:
        return False

    for trigger in PARTNER_REGISTRATION_TRIGGERS:
        if trigger.lower() in msg:
            return True

    has_partner_word = (
        "شريك" in msg
        or "الشراكة" in msg
        or "partner" in msg
        or "affiliate" in msg
    )

    has_action_word = (
        "اسجل" in msg
        or "أسجل" in msg
        or "سجلني" in msg
        or "ادخل" in msg
        or "أدخل" in msg
        or "اربح" in msg
        or "أربح" in msg
        or "register" in msg
        or "join" in msg
        or "become" in msg
    )

    if has_partner_word and has_action_word:
        return True

    return False


def is_partner_registration_active(state):
    return state.get("mode") == "partner_registration"


def extract_phone(message):
    message = convert_arabic_digits(message)
    text = str(message or "")

    candidates = re.findall(
        r"(?:\+|00)?\d[\d\s\-\(\)\.]{7,22}\d",
        text
    )

    for candidate in candidates:
        normalized_phone = normalize_international_phone(candidate)

        if normalized_phone:
            return normalized_phone

    return normalize_international_phone(text)


def extract_email(message):
    msg = str(message or "").strip()

    match = re.search(
        r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
        msg
    )

    if match:
        return match.group(0).strip()

    return ""


def extract_partner_id(message):
    msg = str(message or "").strip()

    if str(COMPANY_OWNER_PARTNER_ID).lower() in msg.lower().split():
        return COMPANY_OWNER_PARTNER_ID

    if msg.lower() == str(COMPANY_OWNER_PARTNER_ID).lower():
        return COMPANY_OWNER_PARTNER_ID

    match = re.search(r"ALS-P\d+", msg.upper())

    if match:
        return match.group(0).strip()

    return ""


def is_skip_answer(message):
    msg = normalize_lower(message)

    skip_words = [
        "لا",
        "لا يوجد",
        "ما عندي",
        "ماعرف",
        "ما أعرف",
        "تخطي",
        "skip",
        "no",
        "none",
        "nothing",
        "مش موجود",
        "بدون",
    ]

    return msg in [word.lower() for word in skip_words]


def clean_simple_value(message):
    value = normalize_text(message)

    value = value.replace("\n", " ").strip()

    return value


def get_state_name(state):
    return (
        state.get("customer_name")
        or state.get("lead_name")
        or state.get("partner_name")
        or ""
    )


def get_state_phone(state):
    raw_phone = (
        state.get("customer_phone")
        or state.get("lead_phone")
        or state.get("partner_phone")
        or ""
    )

    return normalize_international_phone(raw_phone)


def get_or_create_partner_data(state, session_id):
    if "partner_registration" not in state:
        state["partner_registration"] = {}

    data = state["partner_registration"]

    if not data.get("client_id"):
        data["client_id"] = get_effective_client_id(
            session_id=session_id,
            state=state
        )

    existing_name = get_state_name(state)
    existing_phone = get_state_phone(state)

    if existing_name and not data.get("partner_name"):
        data["partner_name"] = existing_name

    if existing_phone and not normalize_international_phone(data.get("phone", "")):
        data["phone"] = existing_phone

    if data.get("phone"):
        normalized_existing_data_phone = normalize_international_phone(data.get("phone", ""))

        if normalized_existing_data_phone:
            data["phone"] = normalized_existing_data_phone
        else:
            data["phone"] = ""

    return data


def get_initial_step(data):
    if not data.get("partner_name"):
        return "partner_name"

    if not normalize_international_phone(data.get("phone", "")):
        return "phone"

    return "email"


def get_next_step(current_step, data=None):
    try:
        current_index = PARTNER_REGISTRATION_STEPS.index(current_step)
    except ValueError:
        return None

    if current_step == "source" and data:
        if data.get("skip_sponsor_step"):
            return None

    next_index = current_index + 1

    if next_index >= len(PARTNER_REGISTRATION_STEPS):
        return None

    return PARTNER_REGISTRATION_STEPS[next_index]


def detect_source_type(message):
    msg = normalize_lower(message)

    if not msg:
        return ""

    if extract_partner_id(msg):
        return "direct_partner"

    direct_partner_keywords = [
        "شخص",
        "شريك",
        "صديق",
        "رفيقي",
        "واحد",
        "احد",
        "أحد",
        "معرف",
        "partner",
        "affiliate",
        "referral",
        "دعاني",
        "عرفني",
        "عن طريق شخص",
        "عن طريق شريك",
    ]

    social_keywords = [
        "سوشيال",
        "انستغرام",
        "انستا",
        "تيك توك",
        "tiktok",
        "instagram",
        "snap",
        "سناب",
        "facebook",
        "فيسبوك",
        "linkedin",
        "لينكد",
        "يوتيوب",
        "youtube",
        "social",
        "social media",
    ]

    website_keywords = [
        "الموقع",
        "موقع",
        "website",
        "alsaab.io",
        "ويبسايت",
    ]

    advertisement_keywords = [
        "اعلان",
        "إعلان",
        "ads",
        "ad",
        "advertisement",
        "ممولة",
        "إعلان ممول",
        "اعلان ممول",
    ]

    event_keywords = [
        "ندوة",
        "فعالية",
        "محاضرة",
        "ورشة",
        "event",
        "seminar",
        "workshop",
    ]

    company_direct_keywords = [
        "الشركة",
        "الصعب",
        "مصعب",
        "تواصل مباشر",
        "منكم",
        "من عندكم",
        "من الشركة",
        "whatsapp",
        "واتساب الشركة",
    ]

    for keyword in direct_partner_keywords:
        if keyword.lower() in msg:
            return "direct_partner"

    for keyword in social_keywords:
        if keyword.lower() in msg:
            return "social_media"

    for keyword in website_keywords:
        if keyword.lower() in msg:
            return "website"

    for keyword in advertisement_keywords:
        if keyword.lower() in msg:
            return "advertisement"

    for keyword in event_keywords:
        if keyword.lower() in msg:
            return "event_or_seminar"

    for keyword in company_direct_keywords:
        if keyword.lower() in msg:
            return "company_direct"

    return ""


def source_requires_sponsor_id(source_type):
    source_data = MLM_SOURCE_OPTIONS.get(source_type, {})
    return bool(source_data.get("requires_partner_id"))


def get_default_partner_id_for_source(source_type):
    source_data = MLM_SOURCE_OPTIONS.get(source_type, {})
    return source_data.get("default_partner_id", COMPANY_OWNER_PARTNER_ID)


def get_source_name_ar(source_type):
    source_data = MLM_SOURCE_OPTIONS.get(source_type, {})
    return source_data.get("name_ar", source_type)


def get_question_for_step(step, data):
    partner_name = data.get("partner_name", "")

    if step == "partner_name":
        return (
            "تمام، نبدأ تسجيلك كشريك في ALSAAB AI ✅\n\n"
            "اكتب اسمك الكامل مثل ما تحب يظهر في النظام."
        )

    if step == "phone":
        if partner_name:
            return (
                f"تمام يا {partner_name} 👌\n\n"
                "اكتب رقم الواتساب مع فتح الخط عشان نربطه بملف الشراكة.\n\n"
                f"مثال: {INTERNATIONAL_PHONE_EXAMPLE}"
            )

        return (
            "اكتب رقم الواتساب مع فتح الخط عشان نربطه بملف الشراكة.\n\n"
            f"مثال: {INTERNATIONAL_PHONE_EXAMPLE}"
        )

    if step == "email":
        return (
            "اكتب الإيميل الخاص فيك.\n\n"
            "إذا ما عندك أو ما تبي تضيفه حالياً، اكتب: لا"
        )

    if step == "country":
        return "في أي دولة أنت حالياً؟"

    if step == "has_business":
        return (
            "هل عندك مشروع حالياً؟\n\n"
            "اكتب مثلاً: نعم عندي مشروع / لا / أفكر أبدأ"
        )

    if step == "goal":
        return (
            "شو هدفك الأساسي من الشراكة؟\n\n"
            "مثلاً:\n"
            "- دخل إضافي\n"
            "- تسويق ALSAAB AI\n"
            "- عندي علاقات وأبغي أستفيد\n"
            "- عندي مشروع وأبغي أضيف مصدر دخل"
        )

    if step == "source":
        return MLM_REGISTRATION_MESSAGES.get(
            "ask_source_ar",
            (
                "قبل ما أكمل تسجيلك كشريك، لازم نعرف من وين عرفت ALSAAB AI عشان نحفظ الحقوق بدقة.\n\n"
                "- عن طريق شخص / شريك\n"
                "- السوشيال ميديا\n"
                "- الموقع\n"
                "- إعلان\n"
                "- ندوة أو فعالية\n"
                "- تواصل مباشر مع الشركة"
            )
        )

    if step == "sponsor":
        return MLM_REGISTRATION_MESSAGES.get(
            "ask_sponsor_id_ar",
            (
                "اكتب Partner ID الخاص بالشخص اللي عرفك على النظام.\n\n"
                "مثال:\n"
                "ALS-P00025\n\n"
                "مهم: بعد التسجيل، تغيير المعرّف يحتاج مراجعة إدارية عشان نحفظ الحقوق."
            )
        )

    return "كمل بياناتك لو سمحت."


def start_partner_registration(state, session_id):
    data = get_or_create_partner_data(state, session_id)

    state["mode"] = "partner_registration"
    state["partner_registration_started"] = True

    first_step = get_initial_step(data)
    data["step"] = first_step

    intro = (
        "حياك الله في نظام الشراكة الخاص بـ ALSAAB AI 🔥\n\n"
        "الفكرة بسيطة: أنت تقدر تدخل ناس للنظام، وإذا اشتركوا واشتراكهم ظل فعّال، "
        "تستفيد من العمولات حسب مستواك وشروط نظام الشراكة.\n\n"
        "تنبيه مهم: الدخل غير مضمون، ويعتمد على شغلك، عدد العملاء، الاستمرارية، وطريقة البيع.\n\n"
    )

    return intro + get_question_for_step(first_step, data)


def process_partner_step(message, state, session_id):
    data = get_or_create_partner_data(state, session_id)
    step = data.get("step") or get_initial_step(data)

    raw_message = normalize_text(message)

    if step == "partner_name":
        partner_name = clean_simple_value(raw_message)

        if len(partner_name) < 2 or len(partner_name) > 80:
            return False, "اكتب اسم واضح عشان أسجلك كشريك بشكل صحيح."

        data["partner_name"] = partner_name
        state["customer_name"] = partner_name
        state["lead_name"] = partner_name

    elif step == "phone":
        phone = extract_phone(raw_message)

        if not phone:
            return False, (
                "اكتب رقم واتساب صحيح مع فتح الخط عشان نحفظه في ملف الشراكة.\n\n"
                f"مثال: {INTERNATIONAL_PHONE_EXAMPLE}"
            )

        data["phone"] = phone
        state["customer_phone"] = phone
        state["lead_phone"] = phone
        state["phone_captured"] = True

    elif step == "email":
        if is_skip_answer(raw_message):
            data["email"] = ""
        else:
            email = extract_email(raw_message)

            if not email:
                return False, (
                    "اكتب إيميل صحيح، أو اكتب: لا\n\n"
                    "مثال: name@email.com"
                )

            data["email"] = email

    elif step == "country":
        country = clean_simple_value(raw_message)

        if is_skip_answer(country):
            country = ""

        data["country"] = country

    elif step == "has_business":
        data["has_business"] = clean_simple_value(raw_message)

    elif step == "goal":
        goal = clean_simple_value(raw_message)

        if len(goal) < 2:
            return False, "اكتب هدفك من الشراكة بشكل مختصر."

        data["goal"] = goal

    elif step == "source":
        source_type = detect_source_type(raw_message)

        if not source_type:
            return False, (
                "لازم نحدد المصدر عشان نحفظ الحقوق بدقة.\n\n"
                "اكتب مثلاً:\n"
                "- عن طريق شخص / شريك\n"
                "- السوشيال ميديا\n"
                "- الموقع\n"
                "- إعلان\n"
                "- ندوة أو فعالية\n"
                "- تواصل مباشر مع الشركة"
            )

        data["source_type"] = source_type
        data["source_description"] = raw_message

        partner_id_in_message = extract_partner_id(raw_message)

        if source_requires_sponsor_id(source_type):
            if partner_id_in_message:
                data["invited_by"] = partner_id_in_message
                data["sponsor_partner_id"] = partner_id_in_message
                data["parent_partner_id"] = partner_id_in_message
                data["skip_sponsor_step"] = True

                apply_sponsor_referral_to_state(
                    state=state,
                    sponsor_partner_id=partner_id_in_message,
                    source_type=source_type,
                    source_description=raw_message
                )
            else:
                data["skip_sponsor_step"] = False

        else:
            owner_partner_id = get_default_partner_id_for_source(source_type)

            data["invited_by"] = get_source_name_ar(source_type)
            data["sponsor_partner_id"] = owner_partner_id
            data["parent_partner_id"] = owner_partner_id
            data["skip_sponsor_step"] = True
            data["owner_partner_id_used"] = True

            apply_sponsor_referral_to_state(
                state=state,
                sponsor_partner_id=owner_partner_id,
                source_type=source_type,
                source_description=raw_message
            )

    elif step == "sponsor":
        sponsor_partner_id = extract_partner_id(raw_message)

        if not sponsor_partner_id:
            return False, MLM_REGISTRATION_MESSAGES.get(
                "invalid_sponsor_ar",
                (
                    "لازم يكون عندك Partner ID صحيح للشخص اللي عرفك على النظام.\n\n"
                    "إذا عرفتنا من السوشيال ميديا أو الموقع أو إعلان أو من الشركة مباشرة، بنستخدم معرف الشركة."
                )
            )

        data["invited_by"] = raw_message
        data["sponsor_partner_id"] = sponsor_partner_id
        data["parent_partner_id"] = sponsor_partner_id

        apply_sponsor_referral_to_state(
            state=state,
            sponsor_partner_id=sponsor_partner_id,
            source_type=data.get("source_type", "direct_partner"),
            source_description=data.get("source_description", raw_message)
        )

    return True, ""


def build_partner_notes(data, session_id):
    notes_parts = [
        "source=bot_partner_registration",
        f"session_id={session_id}",
        f"has_business={data.get('has_business', '')}",
        f"goal={data.get('goal', '')}",
        f"source_type={data.get('source_type', '')}",
        f"source_description={data.get('source_description', '')}",
    ]

    if data.get("invited_by"):
        notes_parts.append(f"invited_by={data.get('invited_by')}")

    if data.get("sponsor_partner_id"):
        notes_parts.append(f"sponsor_partner_id={data.get('sponsor_partner_id')}")

    if data.get("owner_partner_id_used"):
        notes_parts.append("owner_partner_id_used=true")

    return "; ".join(notes_parts)


def finish_partner_registration(state, session_id):
    data = get_or_create_partner_data(state, session_id)

    partner_name = data.get("partner_name", "")
    phone = normalize_international_phone(data.get("phone", ""))
    email = data.get("email", "")
    country = data.get("country", "")
    invited_by = data.get("invited_by", "")
    sponsor_partner_id = data.get("sponsor_partner_id", "")
    parent_partner_id = data.get("parent_partner_id", "")
    client_id = data.get("client_id") or get_effective_client_id(session_id, state=state)
    notes = build_partner_notes(data, session_id)

    if not phone:
        data["step"] = "phone"
        return (
            "قبل ما أكمل التسجيل، لازم رقم الواتساب يكون مع فتح الخط.\n\n"
            f"مثال: {INTERNATIONAL_PHONE_EXAMPLE}"
        )

    data["phone"] = phone
    state["customer_phone"] = phone
    state["lead_phone"] = phone
    state["phone_captured"] = True

    if MLM_SPONSOR_RULES.get("prevent_empty_sponsor", True) and not sponsor_partner_id:
        data["step"] = "source"
        return (
            "ما أقدر أكمل التسجيل بدون تحديد المصدر أو معرف الشخص اللي عرفك على النظام.\n\n"
            "هذا مهم عشان نحفظ الحقوق وما نلخبط العمولات.\n\n"
            + get_question_for_step("source", data)
        )

    apply_sponsor_referral_to_state(
        state=state,
        sponsor_partner_id=sponsor_partner_id,
        source_type=data.get("source_type", ""),
        source_description=data.get("source_description", "")
    )

    result = send_partner_to_google_sheet(
        partner_name=partner_name,
        phone=phone,
        email=email,
        country=country,
        invited_by=invited_by,
        notes=notes,
        level="Level 1",
        status="active",
        client_id=client_id,
        sponsor_partner_id=sponsor_partner_id,
        parent_partner_id=parent_partner_id,
        partner_rank="Level 1"
    )

    if result.get("status") != "success":
        return (
            "صار خلل مؤقت في تسجيل الشريك.\n\n"
            "بياناتك موجودة عندي داخل المحادثة، جرّب ترسل كلمة: تسجيل شريك مرة ثانية، "
            "أو تواصل مع فريق ALSAAB AI."
        )

    partner_id = result.get("partner_id", "")
    referral_link = result.get("referral_link", "")
    sponsor_partner_id = result.get("sponsor_partner_id", sponsor_partner_id)

    state["partner_id"] = partner_id
    state["partner_referral_link"] = referral_link
    state["partner_rank"] = "Level 1"
    state["client_id"] = client_id
    state["mode"] = "sales"
    state["partner_registration_completed"] = True

    if sponsor_partner_id:
        apply_sponsor_referral_to_state(
            state=state,
            sponsor_partner_id=sponsor_partner_id,
            source_type=data.get("source_type", ""),
            source_description=data.get("source_description", "")
        )

    if partner_name and phone:
        try:
            previous_channel = state.get("channel", "")
            state["channel"] = "partner_registration"

            save_lead(
                session_id=session_id,
                name=partner_name,
                phone=phone,
                state=state
            )

            if previous_channel:
                state["channel"] = previous_channel
        except Exception as error:
            print(f"PARTNER LEAD SAVE ERROR ❌ {error}", flush=True)

    if result.get("message") == "Partner already exists":
        return (
            f"أنت مسجل كشريك من قبل ✅\n\n"
            f"Partner ID:\n{partner_id}\n\n"
            f"Referral Link:\n{referral_link}\n\n"
            "استخدم رابط الإحالة مع أي شخص مهتم بالنظام. أي اشتراك فعّال يدخل عن طريقك نقدر نربطه في نظام الشراكة والعمولات."
        )

    sponsor_text = ""

    if sponsor_partner_id:
        if sponsor_partner_id == COMPANY_OWNER_PARTNER_ID:
            sponsor_text = (
                f"\n\nتم ربط تسجيلك بمصدر الشركة:\n{sponsor_partner_id}"
            )
        else:
            sponsor_text = (
                f"\n\nتم ربطك تحت الشريك:\n{sponsor_partner_id}"
            )

    return (
        f"تم تسجيلك كشريك في ALSAAB AI بنجاح ✅\n\n"
        f"Partner ID:\n{partner_id}\n\n"
        f"Referral Link:\n{referral_link}"
        f"{sponsor_text}\n\n"
        "ابدأ باستخدام رابطك مع أي شخص مهتم بالنظام.\n"
        "وأي اشتراك شهري فعّال يدخل عن طريقك يتم احتساب العمولة حسب رتبتك وشروط نظام الشراكة.\n\n"
        "بدايتك الحالية: Level 1 — Starter Partner 🚀\n"
        "الميزة: 25% عمولة مباشرة + كورس التسويق مجاناً."
    )


def handle_partner_registration(message, state, session_id):
    data = get_or_create_partner_data(state, session_id)

    current_step = data.get("step")

    if not current_step:
        data["step"] = get_initial_step(data)
        return get_question_for_step(data["step"], data)

    is_valid, error_message = process_partner_step(message, state, session_id)

    if not is_valid:
        return error_message

    next_step = get_next_step(current_step, data)

    if next_step:
        data["step"] = next_step
        return get_question_for_step(next_step, data)

    return finish_partner_registration(state, session_id)