# brain.py

import re
from openai import OpenAI

from config import OPENAI_API_KEY, MODEL_NAME, REPLY_MAX_TOKENS
from state import create_state, update_state, detect_language
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

INTERNATIONAL_PHONE_EXAMPLE = "+971523288001"


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


def apply_source_partner_to_state(current_state, source_partner_id):
    normalized_source_partner_id = normalize_source_partner_id(source_partner_id)

    if normalized_source_partner_id:
        current_state["source_partner_id"] = normalized_source_partner_id
        current_state["referrer_partner_id"] = normalized_source_partner_id
        current_state["referral_source_captured"] = True

    else:
        existing_source_partner_id = normalize_source_partner_id(
            current_state.get("source_partner_id")
            or current_state.get("referrer_partner_id")
            or ""
        )

        if existing_source_partner_id:
            current_state["source_partner_id"] = existing_source_partner_id
            current_state["referrer_partner_id"] = existing_source_partner_id

    return current_state


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
        return None

    cleaned = re.sub(r"[\s\-\(\)\.\u200f\u200e]", "", value)

    if cleaned.startswith("+"):
        digits = cleaned[1:]

        if digits.isdigit() and 10 <= len(digits) <= 15:
            return "+" + digits

        return None

    if cleaned.startswith("00"):
        digits = cleaned[2:]

        if digits.isdigit() and 10 <= len(digits) <= 15:
            return "+" + digits

        return None

    if cleaned.isdigit():
        # نرفض المحلي بدون فتح خط
        if cleaned.startswith("0"):
            return None

        # نقبل الرقم إذا واضح أنه يحتوي country code
        if 10 <= len(cleaned) <= 15:
            return "+" + cleaned

    return None


def extract_phone(message):
    message = convert_arabic_digits(message)
    text = str(message or "")

    # نبحث عن أرقام محتملة مع + أو 00 أو أرقام طويلة تحتوي كود الدولة
    candidates = re.findall(
        r"(?:\+|00)?\d[\d\s\-\(\)\.]{7,22}\d",
        text
    )

    for candidate in candidates:
        normalized_phone = normalize_international_phone(candidate)

        if normalized_phone:
            return normalized_phone

    # محاولة أخيرة لو كانت الرسالة كلها رقم
    return normalize_international_phone(text)


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
    normalized_phone = normalize_international_phone(phone)

    if not normalized_phone:
        return

    current_state["lead_phone"] = normalized_phone
    current_state["customer_phone"] = normalized_phone
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
        set_customer_phone(current_state, extracted_phone)

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


def load_client_catalog_into_state(partner_id, current_state):
    """
    Product groups and payment links for the account whose bot is answering.

    client_profiles only holds the trained description; the things the bot has
    to actually quote and send live in their own tables. Without this the
    customer's bot could describe the business but could not name a price or
    hand over a payment link.
    """
    if not partner_id:
        return

    try:
        from dashboard_compat import client_dashboard_data

        data = client_dashboard_data({"partner_id": partner_id}) or {}
    except Exception as error:
        print(f"CLIENT CATALOG LOAD ERROR ⚠️ {partner_id} {error}", flush=True)
        return

    try:
        import client_media
    except ImportError:
        from backend import client_media

    groups = []
    images_by_group = {}

    for group in (data.get("product_image_groups") or []):
        title = str(group.get("group_title") or "").strip()

        if not title:
            continue

        # Image paths are stored relative so the dashboard works on any host.
        # A link the bot sends leaves the app, so it needs a real host in front
        # of it -- this is the one place that conversion belongs.
        shots = [
            client_media.absolute_url(url)
            for url in (group.get("image_urls") or [])
            if url
        ]

        images_by_group[str(group.get("group_id") or "")] = shots

        groups.append({
            "title": title,
            "description": str(group.get("group_description") or "").strip(),
            "sales_instructions": str(group.get("sales_instructions") or "").strip(),
            "images": shots,
        })

    links = []

    for link in (data.get("client_payment_links") or []):
        name = str(link.get("product_name") or "").strip()
        url = str(link.get("payment_link") or "").strip()

        if not name or not url:
            continue

        links.append({
            "product_name": name,
            "payment_link": url,
            "amount": str(link.get("amount") or "").strip(),
            "currency": str(link.get("currency") or "").strip(),
            "description": str(link.get("description") or "").strip(),
            "images": images_by_group.get(
                str(link.get("linked_image_group_id") or ""), []
            ),
        })

    if groups:
        current_state["client_product_groups"] = groups

    if links:
        current_state["client_payment_links"] = links

    print(
        f"CLIENT CATALOG LOADED ✅ partner_id={partner_id} "
        f"groups={len(groups)} links={len(links)}",
        flush=True
    )


def build_name_context(current_state):
    customer_name = get_customer_name(current_state)

    if not customer_name:
        return ""

    return (
        f"اسم العميل: {customer_name}\n"
        "استخدم اسم العميل باحتراف وباعتدال داخل الرد، بدون مبالغة أو تكرار زائد.\n"
    )



# ALSAAB_CENTRAL_SESSION_LANGUAGE_V1
_ALSAAB_GATE_TRANSLATIONS = {
    "ar": {
        "name": "هلا وسهلا 👋 قبل لا أساعدك بشكل أدق شو اسمك الكريم",
        "phone": "تمام يا {name} تشرفت فيك 👋\n\nعشان نقدر نتابع معاك لو انقطع الشات اكتب رقم الواتساب مع مفتاح الخط.\n\nمثال: {phone_example}",
        "phone_repeat": "اكتب رقم الواتساب مع مفتاح الخط عشان نحفظ بياناتك ونتابع معاك بشكل صحيح ✅\n\nمثال: {phone_example}",
        "phone_saved": "تمام يا {name} تم حفظ بيانات التواصل ✅\n\nشو أكثر شي تبغي تطوره حاليا: مبيعات مشروعك ولا دخل إضافي لك",
    },
    "en": {
        "name": "Welcome 👋 Before I assist you further, may I know your name?",
        "phone": "Nice to meet you, {name} 👋\n\nTo stay in touch if the chat is interrupted, please enter your WhatsApp number with the country code.\n\nExample: {phone_example}",
        "phone_repeat": "Please enter your WhatsApp number with the country code so we can save your contact details and follow up correctly ✅\n\nExample: {phone_example}",
        "phone_saved": "Thank you, {name}. Your contact details have been saved ✅\n\nWhat would you like to improve most: your business sales or an additional income opportunity?",
    },
    "es": {
        "name": "Bienvenido 👋 Antes de ayudarte mejor, ¿puedo saber tu nombre?",
        "phone": "Encantado de conocerte, {name} 👋\n\nPara mantenernos en contacto si se interrumpe el chat, escribe tu número de WhatsApp con el código del país.\n\nEjemplo: {phone_example}",
        "phone_repeat": "Escribe tu número de WhatsApp con el código del país para guardar tus datos de contacto ✅\n\nEjemplo: {phone_example}",
        "phone_saved": "Gracias, {name}. Tus datos de contacto se han guardado ✅\n\n¿Qué deseas mejorar principalmente: las ventas de tu negocio o una oportunidad de ingresos adicionales?",
    },
    "fr": {
        "name": "Bienvenue 👋 Avant de mieux vous aider, puis-je connaître votre nom ?",
        "phone": "Ravi de vous rencontrer, {name} 👋\n\nPour rester en contact si le chat est interrompu, saisissez votre numéro WhatsApp avec lindicatif du pays.\n\nExemple : {phone_example}",
        "phone_repeat": "Saisissez votre numéro WhatsApp avec lindicatif du pays afin denregistrer vos coordonnées ✅\n\nExemple : {phone_example}",
        "phone_saved": "Merci, {name}. Vos coordonnées ont été enregistrées ✅\n\nQue souhaitez-vous améliorer principalement : les ventes de votre entreprise ou une source de revenus supplémentaire ?",
    },
    "de": {
        "name": "Willkommen 👋 Bevor ich Ihnen genauer helfe: Wie heißen Sie?",
        "phone": "Freut mich, Sie kennenzulernen, {name} 👋\n\nBitte geben Sie Ihre WhatsApp-Nummer mit Landesvorwahl ein, damit wir bei einer Unterbrechung in Kontakt bleiben können.\n\nBeispiel: {phone_example}",
        "phone_repeat": "Bitte geben Sie Ihre WhatsApp-Nummer mit Landesvorwahl ein, damit wir Ihre Kontaktdaten speichern können ✅\n\nBeispiel: {phone_example}",
        "phone_saved": "Vielen Dank, {name}. Ihre Kontaktdaten wurden gespeichert ✅\n\nWas möchten Sie hauptsächlich verbessern: den Umsatz Ihres Unternehmens oder eine zusätzliche Einkommensmöglichkeit?",
    },
    "it": {
        "name": "Benvenuto 👋 Prima di aiutarti meglio, posso sapere il tuo nome?",
        "phone": "Piacere di conoscerti, {name} 👋\n\nInserisci il tuo numero WhatsApp con il prefisso internazionale per restare in contatto se la chat si interrompe.\n\nEsempio: {phone_example}",
        "phone_repeat": "Inserisci il tuo numero WhatsApp con il prefisso internazionale per salvare i dati di contatto ✅\n\nEsempio: {phone_example}",
        "phone_saved": "Grazie, {name}. I tuoi dati di contatto sono stati salvati ✅\n\nCosa vuoi migliorare principalmente: le vendite della tua attività o unopportunità di reddito aggiuntivo?",
    },
    "pt": {
        "name": "Bem-vindo 👋 Antes de ajudá-lo melhor, posso saber o seu nome?",
        "phone": "Prazer em conhecê-lo, {name} 👋\n\nDigite seu número de WhatsApp com o código do país para mantermos contato se o chat for interrompido.\n\nExemplo: {phone_example}",
        "phone_repeat": "Digite seu número de WhatsApp com o código do país para salvarmos seus dados de contato ✅\n\nExemplo: {phone_example}",
        "phone_saved": "Obrigado, {name}. Seus dados de contato foram salvos ✅\n\nO que você deseja melhorar principalmente: as vendas do seu negócio ou uma oportunidade de renda adicional?",
    },
    "tr": {
        "name": "Hoş geldiniz 👋 Size daha iyi yardımcı olmadan önce adınızı öğrenebilir miyim?",
        "phone": "Tanıştığımıza memnun oldum, {name} 👋\n\nSohbet kesilirse iletişimde kalabilmemiz için ülke koduyla birlikte WhatsApp numaranızı yazın.\n\nÖrnek: {phone_example}",
        "phone_repeat": "İletişim bilgilerinizi kaydetmemiz için WhatsApp numaranızı ülke koduyla birlikte yazın ✅\n\nÖrnek: {phone_example}",
        "phone_saved": "Teşekkürler, {name}. İletişim bilgileriniz kaydedildi ✅\n\nEn çok neyi geliştirmek istiyorsunuz: işletmenizin satışlarını mı, ek gelir fırsatını mı?",
    },
}

def _alsaab_resolve_session_language(message, current_state):
    stored = str(
        current_state.get("conversation_language")
        or current_state.get("language")
        or ""
    ).strip().lower()

    # Never change language because the customer is currently answering
    # the name or phone question.
    if stored and (
        current_state.get("awaiting_customer_name")
        or current_state.get("awaiting_customer_phone")
    ):
        current_state["language"] = stored
        return stored

    detected = detect_language(message)

    # Lock the language from the first real customer request.
    if not stored:
        stored = detected
        current_state["conversation_language"] = stored
    else:
        # Allow a clear language switch after lead capture.
        text = str(message or "")
        if len(text.split()) >= 3:
            stored = detected
            current_state["conversation_language"] = stored

    current_state["language"] = stored
    return stored

def _alsaab_gate_reply(kind, current_state, customer_name=""):
    lang = str(
        current_state.get("conversation_language")
        or current_state.get("language")
        or "en"
    ).lower()

    translations = _ALSAAB_GATE_TRANSLATIONS.get(lang)

    # Other languages continue safely in English for fixed lead-capture
    # messages, while the AI response remains in the customer's language.
    if not translations:
        translations = _ALSAAB_GATE_TRANSLATIONS["en"]

    return translations[kind].format(
        name=customer_name or "",
        phone_example=INTERNATIONAL_PHONE_EXAMPLE,
    )


def think(message, session_id, source_partner_id="", bot_partner_id=""):
    current_state = get_session_state(session_id)

    # Which account's project this bot speaks for. A visitor arriving at
    # /c/<partner_id> is talking to that customer's bot, so the project data has
    # to be looked up under the link owner. Keyed on the visitor's own brand new
    # session it came back empty every time, and the bot fell back to selling
    # ALSAAB packages to the customer's own buyers.
    if bot_partner_id:
        current_state["bot_partner_id"] = bot_partner_id
    msg = message.lower().strip()

    # مهم: نخزن session_id داخل state عشان prompt_builder يقدر يبني روابط الدفع الداخلية
    current_state["session_id"] = session_id

    # Detect reply language from the latest customer message.
    current_state["language"] = _alsaab_resolve_session_language(message, current_state)

    # Referral Tracking
    current_state = apply_source_partner_to_state(current_state, source_partner_id)

    print(f"THINK CALLED ✅ session_id={session_id}")
    print(f"CURRENT MODE ✅ mode={current_state.get('mode')}")
    print(f"SOURCE PARTNER STATE ✅ source_partner_id={current_state.get('source_partner_id')}", flush=True)

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

    # ALSAAB_NON_BLOCKING_LEAD_CAPTURE_V1
    # Never block the customer's first request to force name/phone collection.
    # Explicit names and phone numbers are still captured automatically.
    current_state["name_asked"] = True
    current_state["phone_asked"] = True
    current_state["awaiting_customer_name"] = False
    current_state["awaiting_customer_phone"] = False
    current_state.pop("pending_message_after_name", None)
    current_state.pop("pending_message_after_phone", None)

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

            reply = _alsaab_gate_reply("name", current_state)
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
                reply = _alsaab_gate_reply("phone_saved", current_state, customer_name)
                set_session_state(session_id, current_state)
                return reply

        elif current_state.get("awaiting_customer_phone"):
            reply = _alsaab_gate_reply("phone_repeat", current_state)
            set_session_state(session_id, current_state)
            return reply

        elif not current_state.get("phone_asked"):
            current_state["phone_asked"] = True
            current_state["awaiting_customer_phone"] = True

            if not current_state.get("pending_message_after_phone"):
                current_state["pending_message_after_phone"] = message_to_process

            customer_name = get_customer_name(current_state)
            reply = _alsaab_gate_reply("phone", current_state, customer_name)
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
    existing_source_partner_id = current_state.get("source_partner_id", "")
    existing_referrer_partner_id = current_state.get("referrer_partner_id", "")

    current_state = update_state(message_to_process, current_state)

    # مهم: نعيد تثبيت session_id بعد update_state عشان ما يضيع إذا رجّع state جديد
    current_state["session_id"] = session_id

    # Detect reply language from the latest customer message.
    current_state["language"] = _alsaab_resolve_session_language(message, current_state)

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

    # نحافظ على مصدر الإحالة إذا update_state رجّع state جديد
    if existing_source_partner_id:
        current_state["source_partner_id"] = existing_source_partner_id

    if existing_referrer_partner_id:
        current_state["referrer_partner_id"] = existing_referrer_partner_id

    current_state = apply_source_partner_to_state(current_state, source_partner_id)

    # استرجاع بيانات المشروع المدربة إن وجدت
    #
    # On /c/<partner_id> the project belongs to the link owner, not the visitor.
    # The dashboard writes the profile with the partner_id as its session_id, so
    # the partner_id is the key to read it back with. Fall back to the visitor's
    # own session, which is what the owner-advisory chat needs.
    profile_key = current_state.get("bot_partner_id") or session_id

    load_client_profile_into_state(profile_key, current_state)

    if profile_key != session_id and not current_state.get("client_data"):
        print(f"CLIENT BOT PROFILE EMPTY ⚠️ partner_id={profile_key}", flush=True)
        load_client_profile_into_state(session_id, current_state)

    if current_state.get("bot_partner_id"):
        load_client_catalog_into_state(current_state["bot_partner_id"], current_state)

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