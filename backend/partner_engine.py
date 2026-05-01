# partner_engine.py

import re

from database import (
    send_partner_to_google_sheet,
    save_lead,
    get_effective_client_id,
)


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
    "sponsor",
]


def normalize_text(value):
    return str(value or "").strip()


def normalize_lower(value):
    return normalize_text(value).lower()


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
    cleaned = str(message or "").replace(" ", "").replace("-", "").replace("+", "00")

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

    return ""


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
    msg = str(message or "").strip().upper()

    match = re.search(r"ALS-P\d+", msg)

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
    return (
        state.get("customer_phone")
        or state.get("lead_phone")
        or state.get("partner_phone")
        or ""
    )


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

    if existing_phone and not data.get("phone"):
        data["phone"] = existing_phone

    return data


def get_initial_step(data):
    if not data.get("partner_name"):
        return "partner_name"

    if not data.get("phone"):
        return "phone"

    return "email"


def get_next_step(current_step):
    try:
        current_index = PARTNER_REGISTRATION_STEPS.index(current_step)
    except ValueError:
        return None

    next_index = current_index + 1

    if next_index >= len(PARTNER_REGISTRATION_STEPS):
        return None

    return PARTNER_REGISTRATION_STEPS[next_index]


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
                "اكتب رقم الواتساب عشان نربطه بملف الشراكة."
            )

        return "اكتب رقم الواتساب عشان نربطه بملف الشراكة."

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

    if step == "sponsor":
        return (
            "هل أحد دعاك للنظام؟\n\n"
            "إذا عندك Partner ID اكتبه مثل:\n"
            "ALS-P00001\n\n"
            "وإذا ما حد دعاك، اكتب: لا"
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
                "اكتب رقم واتساب صحيح عشان نحفظه في ملف الشراكة.\n\n"
                "مثال: 0500000000"
            )

        data["phone"] = phone
        state["customer_phone"] = phone
        state["lead_phone"] = phone

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

    elif step == "sponsor":
        if is_skip_answer(raw_message):
            data["invited_by"] = ""
            data["sponsor_partner_id"] = ""
            data["parent_partner_id"] = ""
        else:
            sponsor_partner_id = extract_partner_id(raw_message)

            data["invited_by"] = raw_message
            data["sponsor_partner_id"] = sponsor_partner_id
            data["parent_partner_id"] = sponsor_partner_id

    return True, ""


def build_partner_notes(data, session_id):
    notes_parts = [
        "source=bot_partner_registration",
        f"session_id={session_id}",
        f"has_business={data.get('has_business', '')}",
        f"goal={data.get('goal', '')}",
    ]

    if data.get("invited_by"):
        notes_parts.append(f"invited_by={data.get('invited_by')}")

    return "; ".join(notes_parts)


def finish_partner_registration(state, session_id):
    data = get_or_create_partner_data(state, session_id)

    partner_name = data.get("partner_name", "")
    phone = data.get("phone", "")
    email = data.get("email", "")
    country = data.get("country", "")
    invited_by = data.get("invited_by", "")
    sponsor_partner_id = data.get("sponsor_partner_id", "")
    parent_partner_id = data.get("parent_partner_id", "")
    client_id = data.get("client_id") or get_effective_client_id(session_id, state=state)
    notes = build_partner_notes(data, session_id)

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

    if partner_name and phone:
        try:
            save_lead(
                session_id=session_id,
                name=partner_name,
                phone=phone,
                state=state
            )
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
        sponsor_text = f"\n\nتم ربطك تحت الشريك:\n{sponsor_partner_id}"

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

    next_step = get_next_step(current_step)

    if next_step:
        data["step"] = next_step
        return get_question_for_step(next_step, data)

    return finish_partner_registration(state, session_id)