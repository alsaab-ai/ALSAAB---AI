# state.py

def create_state():
    return {
        "messages_count": 0,
        "language": "ar",

        "channel": "website",  # website / whatsapp

        "mode": "sales",
        "training_step": 0,
        "training_data": {},
        "client_data": {},

        "user_type": None,  # business / mlm / unknown

        "business_type": None,
        "pain_point": None,
        "goal": None,

        "customer_type": "unknown",
        "intent": "general",
        "stage": "opening",

        "lead_name": None,
        "lead_phone": None,
    }


def detect_language(message):
    msg = message.lower()
    has_arabic = any("\u0600" <= ch <= "\u06FF" for ch in message)

    if has_arabic:
        return "ar"

    if any(word in msg for word in ["hola", "español", "spanish", "solo español"]):
        return "es"

    return "en"


def detect_user_type(message):
    msg = message.lower()

    business_words = [
        "عندي مشروع", "مشروعي", "شركتي", "عندي بزنس", "عندي محل",
        "عندي مطعم", "عندي كافيه", "عندي متجر", "عندي عقار", "عندي عقارات",
        "أبيع", "ابيع", "منتجاتي", "خدماتي", "عملائي", "زبائني",
        "my business", "my company", "my store", "my restaurant",
        "i sell", "my products", "my service", "clients", "customers"
    ]

    mlm_words = [
        "ابغي اربح", "أبغي أربح", "ابي اربح", "أبي أربح",
        "دخل إضافي", "دخل اضافي", "محتاج دخل إضافي", "محتاج دخل اضافي",
        "مصدر دخل", "دخل ثاني", "دخل شهري", "ارباح", "أرباح", "عمولات",
        "نظام الشراكة", "الشراكة", "mlm", "referral", "commission",
        "i want to earn", "extra income", "passive income", "monthly income"
    ]

    if any(word in msg for word in business_words):
        return "business"

    if any(word in msg for word in mlm_words):
        return "mlm"

    return None


def detect_business_type(message):
    msg = message.lower()

    if any(word in msg for word in ["عقار", "عقارات", "شقة", "فيلا", "real estate", "property"]):
        return "عقار"

    if any(word in msg for word in ["مطعم", "كافيه", "كوفي", "restaurant", "cafe"]):
        return "مطعم / كافيه"

    if any(word in msg for word in ["متجر", "ملابس", "فاشن", "shop", "store", "ecommerce"]):
        return "متجر"

    if any(word in msg for word in ["شركة", "مشروع", "بزنس", "business", "company"]):
        return "مشروع عام"

    return None


def detect_pain_point(message):
    msg = message.lower()

    if any(word in msg for word in ["مبيعات", "sales", "ضعف البيع", "ما ابيع", "ما أبيع"]):
        return "ضعف المبيعات"

    if any(word in msg for word in ["إغلاق", "اغلاق", "closing", "ما يسكر", "مافي إغلاق", "ما في إغلاق"]):
        return "ضعف الإغلاق"

    if any(word in msg for word in ["متابعة", "follow", "follow-up", "ما اتابع", "ما أتابع"]):
        return "ضعف المتابعة"

    if any(word in msg for word in ["عملاء", "leads", "clients", "customers", "استفسارات"]):
        return "إدارة العملاء"

    if any(word in msg for word in ["رد", "رسائل", "reply", "messages", "بطء"]):
        return "بطء الرد"

    return None


def detect_intent(message):
    msg = message.lower()

    if any(word in msg for word in ["مرحبا", "هلا", "السلام", "hello", "hi", "hola"]):
        return "greeting"

    if any(word in msg for word in ["دخل إضافي", "دخل اضافي", "مصدر دخل", "عمولات", "commission", "extra income"]):
        return "mlm_interest"

    if any(word in msg for word in ["الدخل", "كم اربح", "كم أربح", "ارباحي", "أرباحي", "monthly income", "how much can i earn"]):
        return "income_question"

    if any(word in msg for word in ["سعر", "كم", "تكلفة", "price", "cost", "pricing"]):
        return "pricing"

    if any(word in msg for word in ["غالي", "expensive", "too much", "ميزانية"]):
        return "price_objection"

    if any(word in msg for word in ["مو مقتنع", "مش مقتنع", "not convinced", "بفكر", "later"]):
        return "objection"

    if any(word in msg for word in ["ابغي اشترك", "أبغي اشترك", "نبدأ", "جاهز", "ready", "start now", "ابغي اسجل", "أبغي أسجل"]):
        return "buying"

    return "general"


def decide_stage(state):
    if state["mode"] == "training":
        return "training"

    if state["intent"] == "greeting":
        return "opening"

    if state["intent"] in ["mlm_interest", "income_question"] or state["user_type"] == "mlm":
        return "mlm_interest"

    if state["intent"] in ["pricing", "price_objection"]:
        return "offer"

    if state["intent"] == "objection":
        return "objection"

    if state["intent"] == "buying":
        return "closing"

    if not state["business_type"] and state["user_type"] != "mlm":
        return "discovery"

    if not state["pain_point"] and state["user_type"] == "business":
        return "discovery"

    return "diagnosis"


def update_state(message, state):
    if state.get("mode") == "training":
        state["stage"] = "training"
        return state

    state["messages_count"] += 1
    state["language"] = detect_language(message)

    detected_user_type = detect_user_type(message)
    if detected_user_type:
        state["user_type"] = detected_user_type

    business = detect_business_type(message)
    if business:
        state["business_type"] = business
        if not state["user_type"] or state["user_type"] == "unknown":
            state["user_type"] = "business"

    pain = detect_pain_point(message)
    if pain:
        state["pain_point"] = pain

    state["intent"] = detect_intent(message)

    if state["intent"] in ["mlm_interest", "income_question"]:
        state["user_type"] = "mlm"

    state["stage"] = decide_stage(state)

    if not state["user_type"]:
        state["user_type"] = "unknown"

    return state