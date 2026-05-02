# training_engine.py

import re

from database import save_client_profile


INTERNATIONAL_PHONE_EXAMPLE = "+971523288001"


FIELDS = [
    ("business_name", "شو اسم مشروعك؟"),
    ("business_type", "شو نوع النشاط؟"),

    (
        "general_description",
        "عطني وصف عام ومفصل عن مشروعك. اكتب كل شيء مهم حتى لو بشكل طويل أو ممل: شو تبيع، من جمهورك، شو يميزك، طريقة شغلك، الأسعار العامة، العروض، المشاكل اللي تواجهها، طريقة البيع، وأي معلومة تبغي البوت يعرفها عشان يبيع عنك صح."
    ),

    ("products", "شو المنتجات أو الخدمات اللي تقدمها؟"),
    ("prices", "شو الأسعار أو متوسط الأسعار؟"),
    ("offers", "هل عندك عروض حالياً؟"),
    ("ordering", "كيف يتم الطلب أو الحجز؟"),
    ("whatsapp", f"رقم الواتساب الخاص بالمشروع؟ اكتب الرقم مع فتح الخط.\n\nمثال: {INTERNATIONAL_PHONE_EXAMPLE}"),
    ("areas", "وين تخدم؟ أي مناطق أو مدن؟"),
    ("faqs", "أكثر الأسئلة اللي يسألونك العملاء؟"),
    ("objections", "أكثر اعتراض يجيك من العملاء؟"),
    ("tone", "كيف تبغي أسلوب الرد؟ (رسمي / خفيف / خليجي / قوي)")
]


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


def start_training(state):
    state["mode"] = "training"
    state["training_step"] = 0
    state["training_data"] = {}

    print("TRAINING STARTED ✅", flush=True)

    return "تمام 🔥 خلنا نجهز البوت لمشروعك خطوة خطوة.\n" + FIELDS[0][1]


def handle_training(message, state, session_id=None):
    step = state.get("training_step", 0)

    print(f"TRAINING STEP RECEIVED ✅ step={step}", flush=True)
    print(f"TRAINING SESSION ✅ session_id={session_id}", flush=True)

    if step < len(FIELDS):
        key = FIELDS[step][0]
        value = message.strip()

        if key == "whatsapp":
            normalized_whatsapp = extract_phone(value)

            if not normalized_whatsapp:
                print("TRAINING WHATSAPP INVALID ❌ missing international format", flush=True)

                return (
                    "اكتب رقم واتساب المشروع مع فتح الخط عشان نحفظه بشكل صحيح ✅\n\n"
                    f"مثال: {INTERNATIONAL_PHONE_EXAMPLE}\n\n"
                    "ملاحظة: الرقم المحلي مثل 0500000000 ما يكفي، لازم يكون مع كود الدولة."
                )

            value = normalized_whatsapp
            print(f"TRAINING WHATSAPP NORMALIZED ✅ {value}", flush=True)

        state["training_data"][key] = value
        state["training_step"] = step + 1

        print(f"TRAINING DATA SAVED IN MEMORY ✅ key={key}", flush=True)
        print(f"TRAINING NEXT STEP ✅ next_step={state['training_step']} / total={len(FIELDS)}", flush=True)

    if state.get("training_step", 0) >= len(FIELDS):
        print("TRAINING COMPLETED CONDITION HIT ✅", flush=True)
        return finish_training(state, session_id)

    next_question = FIELDS[state["training_step"]][1]
    return next_question


def finish_training(state, session_id=None):
    data = state.get("training_data", {})

    if data.get("whatsapp"):
        normalized_whatsapp = normalize_international_phone(data.get("whatsapp"))

        if normalized_whatsapp:
            data["whatsapp"] = normalized_whatsapp

    state["mode"] = "sales"
    state["client_data"] = data
    state["training_step"] = len(FIELDS)

    print("TRAINING FINISHED ✅", flush=True)
    print(f"TRAINING DATA READY ✅ fields={list(data.keys())}", flush=True)

    if not session_id:
        print("SAVE CLIENT PROFILE SKIPPED ❌ missing session_id", flush=True)
        return "تم تجهيز معلومات مشروعك، لكن لم يتم الحفظ لأن رقم الجلسة غير موجود. جرّب التدريب مرة ثانية."

    if not data:
        print("SAVE CLIENT PROFILE SKIPPED ❌ missing data", flush=True)
        return "تم إنهاء التدريب، لكن لا توجد بيانات للحفظ. جرّب التدريب مرة ثانية."

    try:
        print(f"SAVING CLIENT PROFILE ✅ session_id={session_id}", flush=True)
        save_client_profile(session_id, data)
        print("SAVE CLIENT PROFILE FUNCTION CALLED ✅", flush=True)

        return "تم حفظ معلومات مشروعك ✅ الحين البوت جاهز يبيع عنك بشكل مخصص"

    except Exception as error:
        print(f"SAVE CLIENT PROFILE ERROR ❌ {error}", flush=True)
        return "تم جمع معلومات مشروعك، لكن صار خطأ أثناء الحفظ. بنراجعه تقنياً."