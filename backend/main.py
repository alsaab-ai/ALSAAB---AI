print("ALSAAB AI is running 🔥")

from flask import Flask, request, jsonify, render_template, redirect, session
from brain import think
from database import (
    init_db,
    save_message,
    get_leads,
    get_client_subscription,
    can_client_use_bot,
    record_bot_reply_usage,
    create_or_update_subscription,
    get_usage_summary,
    send_partner_to_google_sheet,
    get_source_partner_id_for_session,
    get_client_subscription_by_stripe_subscription_id,
    ensure_paid_client_is_partner,
)
from config import (
    STRIPE_PLAN_CONFIG,
    STRIPE_WEBHOOK_SECRET,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS,
)
import uuid
import os
import json
import time
import hmac
import hashlib
import re
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

app = Flask(__name__)

# ===== ALSAAB SMART LINK EVENT FILTER REGISTER START =====
try:
    from smart_link_event_filter_routes import register_smart_link_event_filter_routes
except ImportError:
    from backend.smart_link_event_filter_routes import register_smart_link_event_filter_routes

register_smart_link_event_filter_routes(app)
# ===== ALSAAB SMART LINK EVENT FILTER REGISTER END =====


# ===== ALSAAB DASHBOARD FAST MODE REGISTER START =====
try:
    from dashboard_fast_mode_routes import register_dashboard_fast_mode_routes
except ImportError:
    from backend.dashboard_fast_mode_routes import register_dashboard_fast_mode_routes

register_dashboard_fast_mode_routes(app)
# ===== ALSAAB DASHBOARD FAST MODE REGISTER END =====


# ===== ALSAAB_DASHBOARD_SSO_SESSION_SECRET_V1 START =====
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    os.environ.get("DASHBOARD_SSO_SECRET", "alsaab-ai-dev-session-secret-change-me")
)
# ===== ALSAAB_DASHBOARD_SSO_SESSION_SECRET_V1 END =====

init_db()

ADMIN_KEY = "alsaab123"
SAFE_STRIPE_REFERENCE_SEPARATOR = "__"

TRAINING_COMMANDS = [
    "تدريب",
    "تدريب البوت",
    "/train",
    "train",
]

TRAINING_LOCKED_REPLY = (
    "تدريب البوت متاح للمشتركين فقط ✅\n\n"
    "إذا تبغي نجهز البوت لمشروعك، اختر الباقة المناسبة أولاً، "
    "وبعد تفعيل الاشتراك نبدأ تدريب مشروعك خطوة خطوة."
)


def is_training_command(message):
    msg = str(message or "").lower().strip()
    return msg in TRAINING_COMMANDS


def is_active_subscription(subscription):
    if not subscription:
        return False

    status = str(subscription.get("subscription_status", "")).lower().strip()
    return status == "active"


# ===== SAFE ALSAAB OPPORTUNITY PAYMENT GATE V1 START =====
SAFE_ALSAAB_GATE_WORDS = [
    "alsaab",
    "alsaab ai",
    "\u0627\u0644\u0635\u0639\u0628",
    "\u0646\u0638\u0627\u0645 \u0627\u0644\u0635\u0639\u0628",
    "\u0627\u0644\u0646\u0638\u0627\u0645 \u0639\u062c\u0628\u0646\u064a",
    "\u0646\u0641\u0633 \u0627\u0644\u0646\u0638\u0627\u0645",
    "\u0641\u0631\u0635\u0629 \u062f\u062e\u0644",
    "\u062f\u062e\u0644 \u0625\u0636\u0627\u0641\u064a",
    "\u062f\u062e\u0644 \u0627\u0636\u0627\u0641\u064a",
    "\u0623\u0635\u064a\u0631 \u0634\u0631\u064a\u0643",
    "\u0627\u0635\u064a\u0631 \u0634\u0631\u064a\u0643",
    "\u0623\u0628\u063a\u064a \u0623\u0635\u064a\u0631 \u0634\u0631\u064a\u0643",
    "\u0627\u0628\u063a\u064a \u0627\u0635\u064a\u0631 \u0634\u0631\u064a\u0643",
]

SAFE_ALSAAB_PAYMENT_WORDS = [
    "\u062f\u0641\u0639",
    "\u0623\u062f\u0641\u0639",
    "\u0627\u062f\u0641\u0639",
    "\u0631\u0627\u0628\u0637 \u0627\u0644\u062f\u0641\u0639",
    "\u0631\u0627\u0628\u0637 \u062f\u0641\u0639",
    "\u0627\u0634\u062a\u0631\u0643",
    "\u0627\u0634\u062a\u0631\u0627\u0643",
    "subscribe",
    "payment",
    "pay",
    "checkout",
]

SAFE_ALSAAB_PLAN_ALIASES = {
    "entry": ["entry", "\u0627\u0646\u062a\u0631\u064a", "\u0627\u0644\u062f\u062e\u0648\u0644", "\u0628\u0627\u0642\u0629 \u0627\u0644\u062f\u062e\u0648\u0644"],
    "starter": ["starter", "\u0633\u062a\u0627\u0631\u062a\u0631", "\u0627\u0644\u0628\u062f\u0627\u064a\u0629", "\u0628\u0627\u0642\u0629 \u0627\u0644\u0628\u062f\u0627\u064a\u0629"],
    "growth": ["growth", "\u062c\u0631\u0648\u062b", "\u0627\u0644\u0646\u0645\u0648", "\u0628\u0627\u0642\u0629 \u0627\u0644\u0646\u0645\u0648"],
    "elite": ["elite", "\u0627\u064a\u0644\u064a\u062a", "\u0625\u064a\u0644\u064a\u062a", "\u0627\u0644\u0646\u062e\u0628\u0629", "\u0628\u0627\u0642\u0629 \u0627\u0644\u0646\u062e\u0628\u0629"],
    "diamond": ["diamond", "\u062f\u0627\u064a\u0645\u0648\u0646\u062f", "\u0627\u0644\u0645\u0627\u0633\u064a", "\u0627\u0644\u0645\u0627\u0633\u064a\u0629"],
}

SAFE_ALSAAB_PLAN_LABELS = {
    "entry": "Entry",
    "starter": "Starter",
    "growth": "Growth",
    "elite": "Elite",
    "diamond": "Diamond",
}


def detect_safe_alsaab_opportunity_payment_plan(message):
    msg = str(message or "").lower().strip()

    if not msg:
        return ""

    has_alsaab_gate = any(word.lower() in msg for word in SAFE_ALSAAB_GATE_WORDS)
    has_payment = any(word.lower() in msg for word in SAFE_ALSAAB_PAYMENT_WORDS)

    if not has_alsaab_gate or not has_payment:
        return ""

    for plan_name, aliases in SAFE_ALSAAB_PLAN_ALIASES.items():
        if plan_name not in STRIPE_PLAN_CONFIG:
            continue

        for alias in aliases:
            if str(alias).lower() in msg:
                return plan_name

    return ""


# ALSAAB_PAYMENT_REPLY_LANGUAGE_V1
_AL_PAY_TERMS=("pay","payment","payment link","pay now","checkout","subscribe","enlace de pago","quiero pagar","pago","suscribirme","lien de paiement","je veux payer","paiement","payer","abonnement","zahlungslink","ich möchte zahlen","bezahlen","zahlung","link di pagamento","voglio pagare","pagare","abbonarmi","link de pagamento","quero pagar","pagamento","assinar","ödeme bağlantısı","ödeme","ödemek","abone","ссылка на оплату","оплатить","оплата","подписаться","भुगतान लिंक","भुगतान","पेमेंट","सदस्यता","ادائیگی کا لنک","ادائیگی","پیمنٹ","سبسکرائب","لینک پرداخت","پرداخت","اشتراک","付款链接","支付链接","付款","支付","订阅","支払いリンク","決済リンク","支払い","決済","購読","결제 링크","결제","지불","구독")
def _al_pay_lang(message):
    text=str(message or "").strip(); low=text.lower()
    hints=(("es",("enlace de pago","quiero pagar","suscribirme")),("fr",("lien de paiement","je veux payer","abonnement")),("de",("zahlungslink","ich möchte zahlen")),("it",("link di pagamento","voglio pagare","abbonarmi")),("pt",("link de pagamento","quero pagar","assinar")),("tr",("ödeme bağlantısı","abone olmak")),("ru",("ссылка на оплату","оплатить","подписаться")),("hi",("भुगतान","पेमेंट","सदस्यता")),("ur",("ادائیگی","پیمنٹ","سبسکرائب")),("fa",("پرداخت","لینک پرداخت")),("zh",("付款","支付","订阅")),("ja",("支払い","決済","購読")),("ko",("결제","지불","구독")))
    for lang,words in hints:
        if any(w in low for w in words): return lang
    try:
        try: from state import detect_language
        except ImportError: from backend.state import detect_language
        lang=str(detect_language(text) or "en").lower()
    except Exception: lang="en"
    return lang
def _al_pay_reply(message,mode,plan_name="",plan_label="",pay_url=""):
    lang=_al_pay_lang(message); plan=(str(plan_label or plan_name) if lang=="ar" else str(plan_name).title())
    t={
    "ar":("أكيد، أي باقة تريد رابط الدفع الخاص بها؟","درهم شهرياً","تمام ✅\nهذا رابط دفع باقة {p} في ALSAAB AI:","بعد الدفع بيتفعل الاشتراك تلقائياً، وبيتم ربطه بالشريك الصحيح."),
    "en":("Sure. Which package would you like the payment link for?","AED/month","Done ✅\nHere is the payment link for the {p} package in ALSAAB AI:","After payment, the subscription will be activated automatically and linked to the correct partner."),
    "es":("Claro. ¿Para qué plan desea el enlace de pago?","AED al mes","Listo ✅\nEste es el enlace de pago del plan {p} en ALSAAB AI:","Después del pago, la suscripción se activará automáticamente y quedará vinculada al socio correcto."),
    "fr":("Bien sûr. Pour quelle offre souhaitez-vous le lien de paiement ?","AED/mois","C'est prêt ✅\nVoici le lien de paiement de l'offre {p} dans ALSAAB AI :","Après le paiement, l'abonnement sera activé automatiquement et rattaché au bon partenaire."),
    "de":("Für welches Paket möchten Sie den Zahlungslink?","AED/Monat","Erledigt ✅\nHier ist der Zahlungslink für das Paket {p} bei ALSAAB AI:","Nach der Zahlung wird das Abonnement automatisch aktiviert und dem richtigen Partner zugeordnet."),
    "it":("Per quale piano desidera il link di pagamento?","AED/mese","Fatto ✅\nEcco il link di pagamento per il piano {p} in ALSAAB AI:","Dopo il pagamento, l'abbonamento verrà attivato automaticamente e collegato al partner corretto."),
    "pt":("Para qual plano deseja o link de pagamento?","AED/mês","Pronto ✅\nEste é o link de pagamento do plano {p} no ALSAAB AI:","Após o pagamento, a assinatura será ativada automaticamente e vinculada ao parceiro correto."),
    "tr":("Hangi paket için ödeme bağlantısını istiyorsunuz?","AED/ay","Hazır ✅\nALSAAB AI'daki {p} paketi için ödeme bağlantısı:","Ödeme sonrasında abonelik otomatik olarak etkinleştirilecek ve doğru iş ortağına bağlanacaktır."),
    "ru":("Для какого тарифа вам нужна ссылка на оплату?","AED/месяц","Готово ✅\nВот ссылка на оплату тарифа {p} в ALSAAB AI:","После оплаты подписка активируется автоматически и будет привязана к нужному партнёру."),
    "hi":("आपको किस पैकेज का भुगतान लिंक चाहिए?","AED/माह","तैयार है ✅\nALSAAB AI में {p} पैकेज का भुगतान लिंक यह है:","भुगतान के बाद सदस्यता अपने आप सक्रिय हो जाएगी और सही पार्टनर से जुड़ जाएगी।"),
    "ur":("آپ کو کس پیکیج کا ادائیگی لنک چاہیے؟","AED/ماہ","تیار ہے ✅\nALSAAB AI میں {p} پیکیج کا ادائیگی لنک یہ ہے:","ادائیگی کے بعد سبسکرپشن خودکار طور پر فعال ہو جائے گی اور درست پارٹنر سے منسلک ہو گی۔"),
    "fa":("لینک پرداخت کدام بسته را می‌خواهید؟","AED/ماه","آماده است ✅\nاین لینک پرداخت بسته {p} در ALSAAB AI است:","پس از پرداخت، اشتراک به‌صورت خودکار فعال و به شریک صحیح متصل می‌شود."),
    "zh":("您需要哪个套餐的付款链接？","AED/月","已准备好 ✅\n这是 ALSAAB AI 中 {p} 套餐的付款链接：","付款后，订阅将自动激活并关联到正确的合作伙伴。"),
    "ja":("どのプランのお支払いリンクをご希望ですか？","AED/月","準備できました ✅\nALSAAB AIの{p}プランのお支払いリンクです：","お支払い後、サブスクリプションは自動的に有効化され、正しいパートナーに紐付けられます。"),
    "ko":("어떤 요금제의 결제 링크가 필요하신가요?","AED/월","준비되었습니다 ✅\nALSAAB AI의 {p} 요금제 결제 링크입니다:","결제 후 구독이 자동으로 활성화되고 올바른 파트너에게 연결됩니다.")}
    if lang not in t: return ("Entry — 99 AED\nStarter — 299 AED\nGrowth — 599 AED\nElite — 1199 AED\nDiamond — 2399 AED" if mode=="choose" else f"✅ ALSAAB AI — {plan}\n\n{pay_url}")
    intro,suffix,before,after=t[lang]
    if mode=="choose":
        lines="\n".join(f"• {n} — {p} {suffix}" for n,p in (("Entry",99),("Starter",299),("Growth",599),("Elite",1199),("Diamond",2399)))
        return f"{intro}\n\n{lines}"
    return f"{before.format(p=plan)}\n\n{pay_url}\n\n{after}"
# ALSAAB_PAYMENT_REPLY_LANGUAGE_V1_END

def build_safe_alsaab_opportunity_payment_reply(plan_name, session_id, source_partner_id=""):
    # ALSAAB_SAFE_PAYMENT_FUNCTION_HARD_GUARD_V1
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}

    incoming_msg = str((payload.get("original_user_message") or payload.get("message") or "")).lower()

    _payment_words = [
        "pay", "payment", "checkout", "subscribe",
        "\u062f\u0641\u0639",
        "\u0627\u062f\u0641\u0639",
        "\u0623\u062f\u0641\u0639",
        "\u0631\u0627\u0628\u0637 \u0627\u0644\u062f\u0641\u0639",
        "\u0631\u0627\u0628\u0637 \u062f\u0641\u0639",
        "\u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0634\u062a\u0631\u0627\u0643",
    ]

    _payment_words.extend(_AL_PAY_TERMS)

    _plan_aliases = [
        ("diamond", ["diamond", "2399", "\u0627\u0644\u0645\u0627\u0633\u064a\u0629", "\u0645\u0627\u0633\u064a\u0629"]),
        ("elite", ["elite", "1199", "\u0627\u0644\u0646\u062e\u0628\u0629", "\u0646\u062e\u0628\u0629"]),
        ("growth", ["growth", "599", "\u0627\u0644\u0646\u0645\u0648", "\u0646\u0645\u0648"]),
        ("starter", ["starter", "299", "\u0627\u0644\u0628\u062f\u0627\u064a\u0629", "\u0628\u062f\u0627\u064a\u0629"]),
        ("entry", ["entry", "99", "\u0627\u0644\u062f\u062e\u0648\u0644", "\u062f\u062e\u0648\u0644"]),
    ]

    _has_payment = any(w in incoming_msg for w in _payment_words)
    _requested_plan = None

    for _plan, _aliases in _plan_aliases:
        if any(_alias.lower() in incoming_msg for _alias in _aliases):
            _requested_plan = _plan
            break

    if not (_has_payment and _requested_plan):
        return _al_pay_reply(incoming_msg,"choose")

    plan_name = _requested_plan
    # ALSAAB_SAFE_PAYMENT_FUNCTION_HARD_GUARD_V1_END
    plan_name = str(plan_name or "").lower().strip()

    if plan_name not in STRIPE_PLAN_CONFIG:
        return ""

    if not session_id:
        return ""

    source_partner_id = normalize_source_partner_id(source_partner_id)

    params = {"sid": session_id}

    if source_partner_id:
        params["ref"] = source_partner_id
        params["source_partner_id"] = source_partner_id

    pay_url = f"{globals().get('APP_BASE_URL', 'https://alsaab-ai.onrender.com').rstrip('/')}/pay/{plan_name}?{urlencode(params)}"
    plan_label = SAFE_ALSAAB_PLAN_LABELS.get(plan_name, plan_name)

    return _al_pay_reply(incoming_msg,"success",plan_name,plan_label,pay_url)
# ===== SAFE ALSAAB OPPORTUNITY PAYMENT GATE V1 END =====


# ALSAAB_NO_AUTO_PAY_LINK_GUARD_V1
def alsaab_user_explicitly_requested_payment_with_plan(message):
    msg = str(message or "").lower()

    payment_words = [
        "رابط الدفع", "ادفع", "أدفع", "دفع", "الدفع", "اشترك", "اشتراك",
        "باخذ", "بآخذ", "أخذ", "اخذ", "ارسل الرابط", "طرش الرابط",
        "payment", "pay", "checkout", "subscribe"
    ]

    plan_words = [
        "entry", "starter", "growth", "elite", "diamond",
        "الدخول", "البداية", "النمو", "النخبة", "الماسية",
        "99", "299", "599", "1199", "2399"
    ]

    has_payment = any(w.lower() in msg for w in payment_words)
    has_plan = any(w.lower() in msg for w in plan_words)

    return bool(has_payment and has_plan)


def alsaab_guard_auto_payment_links(reply, user_message):
    import re

    reply_text = str(reply or "")

    has_alsaab_pay_link = re.search(
        r"https?://[^\s<>'\"]*/pay/(entry|starter|growth|elite|diamond)[^\s<>'\"]*",
        reply_text,
        flags=re.IGNORECASE
    )

    if not has_alsaab_pay_link:
        return reply_text

    if alsaab_user_explicitly_requested_payment_with_plan(user_message):
        return reply_text

    return (
        "أكيد أقدر أرسل لك رابط الدفع، بس قبلها لازم تختار الباقة المناسبة عشان ما أرسل لك رابط غلط.\n\n"
        "الباقات المتوفرة:\n"
        "• باقة الدخول Entry — 99 درهم شهرياً\n"
        "• باقة البداية Starter — 299 درهم شهرياً\n"
        "• باقة النمو Growth — 599 درهم شهرياً\n"
        "• باقة النخبة Elite — 1199 درهم شهرياً\n"
        "• الباقة الماسية Diamond — 2399 درهم شهرياً\n\n"
        "أي باقة تريد؟"
    )


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


def build_stripe_client_reference_id(session_id, plan_name, source_partner_id=""):
    source_partner_id = normalize_source_partner_id(source_partner_id)

    if source_partner_id:
        return (
            f"{session_id}"
            f"{SAFE_STRIPE_REFERENCE_SEPARATOR}{plan_name}"
            f"{SAFE_STRIPE_REFERENCE_SEPARATOR}{source_partner_id}"
        )

    return f"{session_id}{SAFE_STRIPE_REFERENCE_SEPARATOR}{plan_name}"


def parse_stripe_client_reference_id(reference_id):
    if not reference_id:
        return "", "", ""

    reference_id = str(reference_id).strip()

    if SAFE_STRIPE_REFERENCE_SEPARATOR in reference_id:
        parts = reference_id.rsplit(SAFE_STRIPE_REFERENCE_SEPARATOR, 2)

        if len(parts) == 3:
            return (
                parts[0].strip(),
                parts[1].strip(),
                normalize_source_partner_id(parts[2])
            )

        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip(), ""

    if "::" in reference_id:
        parts = reference_id.rsplit("::", 2)

        if len(parts) == 3:
            return (
                parts[0].strip(),
                parts[1].strip(),
                normalize_source_partner_id(parts[2])
            )

        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip(), ""

    return "", "", ""


def append_query_params(url, params):
    parsed_url = urlparse(url)
    current_params = dict(parse_qsl(parsed_url.query))

    for key, value in params.items():
        if value is not None and value != "":
            current_params[key] = value

    new_query = urlencode(current_params)

    return urlunparse(parsed_url._replace(query=new_query))


def verify_stripe_signature(payload, signature_header, webhook_secret, tolerance_seconds=300):
    if not webhook_secret:
        return False, "STRIPE_WEBHOOK_SECRET is not configured"

    if not signature_header:
        return False, "Stripe-Signature header is missing"

    try:
        parts = signature_header.split(",")
        timestamp = None
        signatures = []

        for part in parts:
            if "=" not in part:
                continue

            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()

            if key == "t":
                timestamp = value

            if key == "v1":
                signatures.append(value)

        if not timestamp:
            return False, "Stripe timestamp is missing"

        if not signatures:
            return False, "Stripe v1 signature is missing"

        timestamp_int = int(timestamp)
        current_time = int(time.time())

        if tolerance_seconds and abs(current_time - timestamp_int) > int(tolerance_seconds):
            return False, "Stripe signature timestamp is outside tolerance"

        signed_payload = timestamp.encode("utf-8") + b"." + payload

        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256
        ).hexdigest()

        for signature in signatures:
            if hmac.compare_digest(expected_signature, signature):
                return True, "verified"

        return False, "No matching Stripe signature"

    except Exception as error:
        return False, str(error)


def get_admin_payload():
    """
    يقرأ بيانات admin routes من JSON أو Form.
    مهم: GET صار للمعاينة فقط، والتنفيذ الحقيقي POST فقط.
    """
    if request.is_json:
        return request.json or {}

    if request.form:
        return request.form.to_dict()

    return {}


def get_payload_value(payload, *keys, default=""):
    for key in keys:
        value = payload.get(key)

        if value is not None and str(value).strip() != "":
            return str(value).strip()

    return default


def get_admin_key(payload):
    return (
        get_payload_value(payload, "key", default="")
        or request.args.get("key", "").strip()
    )


def admin_get_preview(action_name, required_fields=None, example_body=None):
    return jsonify({
        "status": "preview_only",
        "message": (
            f"{action_name} does not execute with GET anymore. "
            "Use POST with JSON body to execute this admin action."
        ),
        "method_required": "POST",
        "reason": "GET links can be triggered by browser preview, prefetch, or copy/link scanners.",
        "required_fields": required_fields or [],
        "example_body": example_body or {}
    })


@app.route("/")
def home():
    return render_template("chat.html")


@app.route("/pay/<plan_name>", methods=["GET"])
def pay(plan_name):
    plan_name = str(plan_name or "").lower().strip()
    session_id = request.args.get("sid") or request.args.get("session_id")
    source_partner_id = normalize_source_partner_id(
        request.args.get("ref")
        or request.args.get("source_partner_id")
        or request.args.get("partner_id")
        or ""
    )

    if plan_name not in STRIPE_PLAN_CONFIG:
        return jsonify({
            "status": "error",
            "message": "Invalid plan name"
        }), 400

    if not session_id:
        return render_template("pay.html"), 400

    if not source_partner_id:
        try:
            source_partner_id = get_source_partner_id_for_session(session_id)
        except Exception as error:
            print(f"PAY SOURCE PARTNER LOOKUP ERROR ❌ {error}", flush=True)
            source_partner_id = ""

    source_partner_id = normalize_source_partner_id(source_partner_id)

    plan_config = STRIPE_PLAN_CONFIG[plan_name]
    payment_link = plan_config.get("payment_link", "")

    if not payment_link:
        return jsonify({
            "status": "error",
            "message": "Payment link is not configured"
        }), 500

    client_reference_id = build_stripe_client_reference_id(
        session_id=session_id,
        plan_name=plan_name,
        source_partner_id=source_partner_id
    )

    payment_url = append_query_params(
        payment_link,
        {
            "client_reference_id": client_reference_id
        }
    )

    print(
        f"PAYMENT REDIRECT ✅ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id} reference={client_reference_id}",
        flush=True
    )

    return redirect(payment_url, code=302)


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    signature_header = request.headers.get("Stripe-Signature", "")

    verified, verification_message = verify_stripe_signature(
        payload=payload,
        signature_header=signature_header,
        webhook_secret=STRIPE_WEBHOOK_SECRET,
        tolerance_seconds=STRIPE_WEBHOOK_TOLERANCE_SECONDS
    )

    if not verified:
        print(f"STRIPE WEBHOOK SIGNATURE FAILED ❌ {verification_message}", flush=True)

        return jsonify({
            "status": "error",
            "message": "Invalid Stripe signature"
        }), 400

    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception as error:
        print(f"STRIPE WEBHOOK JSON ERROR ❌ {error}", flush=True)

        return jsonify({
            "status": "error",
            "message": "Invalid JSON payload"
        }), 400

    event_type = event.get("type", "")
    event_id = event.get("id", "")

    print(f"STRIPE WEBHOOK RECEIVED ✅ event={event_type} id={event_id}", flush=True)

    if event_type == "checkout.session.completed":
        checkout_session = event.get("data", {}).get("object", {})

        client_reference_id = checkout_session.get("client_reference_id", "")
        session_id, plan_name, source_partner_id = parse_stripe_client_reference_id(client_reference_id)

        if not session_id or not plan_name:
            print(
                f"STRIPE CHECKOUT IGNORED ⚠️ missing client_reference_id={client_reference_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_or_invalid_client_reference_id"
            })

        plan_name = str(plan_name).lower().strip()

        if plan_name not in STRIPE_PLAN_CONFIG:
            print(f"STRIPE CHECKOUT IGNORED ⚠️ invalid plan={plan_name}", flush=True)

            return jsonify({
                "status": "ignored",
                "reason": "invalid_plan"
            })

        if not source_partner_id:
            try:
                source_partner_id = get_source_partner_id_for_session(session_id)
            except Exception as error:
                print(f"STRIPE SOURCE PARTNER LOOKUP ERROR ❌ {error}", flush=True)
                source_partner_id = ""

        source_partner_id = normalize_source_partner_id(source_partner_id)

        plan_config = STRIPE_PLAN_CONFIG[plan_name]

        stripe_customer_id = checkout_session.get("customer", "") or ""
        stripe_subscription_id = checkout_session.get("subscription", "") or ""
        package_amount = plan_config.get("package_amount", "")

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=session_id,
            bot_id="",
            status="active",
            custom_reply_limit=plan_config.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Activated automatically by Stripe checkout.session.completed event {event_id}",
            reset_usage=True,
            source_partner_id=source_partner_id
        )

        # ===== ALSAAB CAPTURE CUSTOMER CONTACT V1 START =====
        # Stripe hands us the customer's email and phone at checkout, but they
        # were only forwarded to the partner record and never stored on the
        # subscription. The result: not one email address anywhere in the
        # database, so the system cannot notify a customer about anything —
        # renewal, failed payment or cancellation.
        try:
            from database import get_connection as _contact_connection

            details = checkout_session.get("customer_details", {}) or {}
            captured_email = (
                details.get("email", "")
                or checkout_session.get("customer_email", "")
                or ""
            ).strip()
            captured_phone = (details.get("phone", "") or "").strip()

            if captured_email or captured_phone:
                contact_conn = _contact_connection()
                contact_cursor = contact_conn.cursor()
                contact_cursor.execute(
                    """
                    UPDATE subscriptions
                    SET customer_email = COALESCE(NULLIF(?, ''), customer_email),
                        customer_phone = COALESCE(NULLIF(?, ''), customer_phone)
                    WHERE session_id = ?
                    """,
                    (captured_email, captured_phone, session_id),
                )
                contact_conn.commit()
                contact_conn.close()

                # The partner row is created before Stripe hands the contact
                # over, so mirror it there too. partners.email is the key the
                # WordPress hand-off and the email login both look up, and it
                # was empty for every partner in the table. NULLIF keeps an
                # existing value from being overwritten with a blank.
                partner_conn = _contact_connection()
                partner_cursor = partner_conn.cursor()
                partner_cursor.execute(
                    """
                    UPDATE partners
                    SET email = COALESCE(NULLIF(email, ''), NULLIF(?, '')),
                        phone = COALESCE(NULLIF(phone, ''), NULLIF(?, ''))
                    WHERE client_id = ? OR client_id = ?
                    """,
                    (captured_email, captured_phone, session_id, session_id),
                )
                partner_conn.commit()
                partner_conn.close()

                print(
                    f"CUSTOMER CONTACT CAPTURED ✅ session_id={session_id} "
                    f"email={'yes' if captured_email else 'no'} "
                    f"phone={'yes' if captured_phone else 'no'}",
                    flush=True
                )

        except Exception as contact_error:
            print(f"CUSTOMER CONTACT CAPTURE ERROR ⚠️ {contact_error}", flush=True)
        # ===== ALSAAB CAPTURE CUSTOMER CONTACT V1 END =====

        try:
            customer_details = checkout_session.get("customer_details", {}) or {}

            auto_partner_result = ensure_paid_client_is_partner(
                session_id=session_id,
                client_id=session_id,
                source_partner_id=source_partner_id,
                partner_name=customer_details.get("name", "") or "",
                phone=customer_details.get("phone", "") or "",
                email=(
                    customer_details.get("email", "")
                    or checkout_session.get("customer_email", "")
                    or ""
                ),
                country="",
                notes=f"auto_partner_from_checkout_session_completed; stripe_event_id={event_id}",
                stripe_subscription_id=stripe_subscription_id,
                plan_name=plan_name,
                package_amount=package_amount
            )

            print(f"STRIPE AUTO PARTNER RESULT {auto_partner_result}", flush=True)

        except Exception as error:
            print(f"STRIPE AUTO PARTNER ERROR {error}", flush=True)

        print(
            f"STRIPE SUBSCRIPTION ACTIVATED ✅ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id}",
            flush=True
        )

        return jsonify({
            "status": "success",
            "message": "Subscription activated",
            "subscription": subscription
        })

    if event_type == "invoice.paid":
        invoice = event.get("data", {}).get("object", {})

        invoice_id = invoice.get("id", "") or ""
        billing_reason = invoice.get("billing_reason", "") or ""

        if billing_reason == "subscription_create":
            print(f"STRIPE INVOICE PAID INITIAL SKIPPED checkout already handled invoice_id={invoice_id} event_id={event_id}", flush=True)
            return jsonify({
                "status": "ignored",
                "reason": "initial_invoice_handled_by_checkout",
                "invoice_id": invoice_id,
                "event_id": event_id
            }), 200

        stripe_subscription_id = invoice.get("subscription", "") or ""

        if isinstance(stripe_subscription_id, dict):
            stripe_subscription_id = stripe_subscription_id.get("id", "") or ""

        if not stripe_subscription_id:
            parent = invoice.get("parent", {}) or {}
            subscription_details = parent.get("subscription_details", {}) or {}
            stripe_subscription_id = subscription_details.get("subscription", "") or ""

        if not stripe_subscription_id:
            print(
                f"STRIPE INVOICE PAID IGNORED ⚠️ missing stripe_subscription_id invoice_id={invoice_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_stripe_subscription_id",
                "invoice_id": invoice_id
            })

        existing_subscription = get_client_subscription_by_stripe_subscription_id(
            stripe_subscription_id
        )

        if not existing_subscription:
            print(
                f"STRIPE INVOICE PAID IGNORED ⚠️ subscription not found stripe_subscription_id={stripe_subscription_id} invoice_id={invoice_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "subscription_not_found",
                "stripe_subscription_id": stripe_subscription_id,
                "invoice_id": invoice_id
            })

        session_id = existing_subscription.get("session_id") or ""
        plan_name = existing_subscription.get("plan_name") or "growth"
        source_partner_id = normalize_source_partner_id(
            existing_subscription.get("source_partner_id") or ""
        )

        stripe_customer_id = (
            invoice.get("customer", "")
            or existing_subscription.get("stripe_customer_id")
            or ""
        )

        # ===== ALSAAB INVOICE AMOUNT AS COMMISSION BASE V1 START =====
        # Commission is a percentage of what the customer actually paid, so the
        # base has to come from the invoice, not from the amount stored on the
        # subscription row.
        #
        # Reading the stored value meant a price change, a coupon or a partial
        # payment left the two out of step: after a discount the partner was
        # paid a percentage of the full list price, and after a price rise the
        # partner was underpaid.
        #
        # Stripe reports money in the smallest currency unit, hence /100.
        invoice_amount_paid = invoice.get("amount_paid")

        if invoice_amount_paid in (None, ""):
            invoice_amount_paid = invoice.get("amount_due")

        package_amount = existing_subscription.get("package_amount") or ""

        try:
            if invoice_amount_paid not in (None, "") and float(invoice_amount_paid) > 0:
                package_amount = f"{float(invoice_amount_paid) / 100:.2f}"
                print(
                    f"INVOICE AMOUNT USED AS COMMISSION BASE ✅ invoice_id={invoice_id} "
                    f"amount={package_amount} (stored was {existing_subscription.get('package_amount')})",
                    flush=True
                )
        except (TypeError, ValueError) as amount_error:
            print(
                f"INVOICE AMOUNT PARSE FAILED ⚠️ falling back to the stored amount: {amount_error}",
                flush=True
            )
        # ===== ALSAAB INVOICE AMOUNT AS COMMISSION BASE V1 END =====

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=existing_subscription.get("client_id") or session_id,
            bot_id=existing_subscription.get("bot_id") or "",
            status="active",
            custom_reply_limit=existing_subscription.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Renewed automatically by Stripe invoice.paid event {event_id}; invoice_id={invoice_id}",
            reset_usage=True,
            source_partner_id=source_partner_id
        )

        # The charge went through, so any grace window from an earlier failed
        # attempt is over. Left behind it would keep a genuinely lapsed
        # customer counting later on.
        try:
            from database import get_connection as _grace_connection

            grace_conn = _grace_connection()
            grace_cursor = grace_conn.cursor()
            grace_cursor.execute(
                """
                UPDATE subscriptions
                SET payment_failed_at = NULL, payment_grace_until = NULL,
                    payment_retry_count = 0
                WHERE stripe_subscription_id = ?
                  AND payment_grace_until IS NOT NULL
                """,
                (stripe_subscription_id,),
            )
            grace_conn.commit()
            grace_conn.close()

        except Exception as grace_error:
            print(f"PAYMENT GRACE CLEAR ERROR ⚠️ {grace_error}", flush=True)

        try:
            auto_partner_result = ensure_paid_client_is_partner(
                session_id=session_id,
                client_id=existing_subscription.get("client_id") or session_id,
                source_partner_id=source_partner_id,
                partner_name="",
                phone="",
                email="",
                country="",
                notes=f"auto_partner_from_invoice_paid_fallback; stripe_event_id={event_id}; invoice_id={invoice_id}",
                stripe_subscription_id=stripe_subscription_id,
                plan_name=plan_name,
                package_amount=package_amount
            )

            print(f"INVOICE PAID AUTO PARTNER RESULT {auto_partner_result}", flush=True)

        except Exception as error:
            print(f"INVOICE PAID AUTO PARTNER ERROR {error}", flush=True)

        print(
            f"STRIPE INVOICE PAID HANDLED ✅ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id} invoice_id={invoice_id}",
            flush=True
        )

        telegram_notify(
            f"💵 <b>تجديد مدفوع</b>"
            "\n"
            f"العميل: {session_id}"
            "\n"
            f"الباقة: {plan_name}"
            "\n"
            f"الراعي: {source_partner_id or '-'}"
            "\n"
            f"الفاتورة: <code>{invoice_id}</code>"
        )

        return jsonify({
            "status": "success",
            "message": "invoice.paid handled",
            "invoice_id": invoice_id,
            "stripe_subscription_id": stripe_subscription_id,
            "subscription": subscription
        })

    # ===== ALSAAB UPCOMING RENEWAL NOTICE V1 START =====
    # Stripe fires invoice.upcoming ahead of every renewal. The lead time is
    # set in the Stripe dashboard (Billing -> Subscriptions and emails); set it
    # to 5 days to match the reminder policy.
    #
    # Nothing is sent from here: the project has no email sender and the
    # WhatsApp integration only receives. What this does is record WHEN the
    # renewal lands and how much it will be, so the dashboards can warn the
    # customer and so a reminder job has something to read the day a sending
    # channel exists.
    if event_type == "invoice.upcoming":
        invoice = event.get("data", {}).get("object", {})

        stripe_subscription_id = invoice.get("subscription", "") or ""

        if isinstance(stripe_subscription_id, dict):
            stripe_subscription_id = stripe_subscription_id.get("id", "") or ""

        if not stripe_subscription_id:
            return jsonify({"status": "ignored", "reason": "missing_stripe_subscription_id"})

        renewal_at = invoice.get("next_payment_attempt") or invoice.get("period_end")
        amount_due = invoice.get("amount_due")

        try:
            from database import get_connection as _renewal_connection
            from datetime import datetime as _datetime

            renewal_dt = _datetime.utcfromtimestamp(int(renewal_at)) if renewal_at else None

            renewal_conn = _renewal_connection()
            renewal_cursor = renewal_conn.cursor()
            renewal_cursor.execute(
                """
                UPDATE subscriptions
                SET next_renewal_at   = ?,
                    customer_email    = COALESCE(NULLIF(?, ''), customer_email),
                    last_invoice_url  = COALESCE(NULLIF(?, ''), last_invoice_url)
                WHERE stripe_subscription_id = ?
                """,
                (
                    renewal_dt,
                    (invoice.get("customer_email") or "").strip(),
                    invoice.get("hosted_invoice_url") or "",
                    stripe_subscription_id,
                ),
            )
            renewal_conn.commit()
            renewal_conn.close()

            print(
                f"UPCOMING RENEWAL RECORDED ✅ sub={stripe_subscription_id} "
                f"due={renewal_dt} amount={amount_due}",
                flush=True
            )

        except Exception as renewal_error:
            print(f"UPCOMING RENEWAL ERROR ⚠️ {renewal_error}", flush=True)

        return jsonify({
            "status": "success",
            "message": "invoice.upcoming recorded",
            "stripe_subscription_id": stripe_subscription_id,
        })
    # ===== ALSAAB UPCOMING RENEWAL NOTICE V1 END =====

    if event_type == "invoice.payment_failed":
        invoice = event.get("data", {}).get("object", {})

        invoice_id = invoice.get("id", "") or ""
        stripe_subscription_id = invoice.get("subscription", "") or ""

        if isinstance(stripe_subscription_id, dict):
            stripe_subscription_id = stripe_subscription_id.get("id", "") or ""

        if not stripe_subscription_id:
            parent = invoice.get("parent", {}) or {}
            subscription_details = parent.get("subscription_details", {}) or {}
            stripe_subscription_id = subscription_details.get("subscription", "") or ""

        if not stripe_subscription_id:
            print(
                f"STRIPE INVOICE PAYMENT FAILED IGNORED ⚠️ missing stripe_subscription_id invoice_id={invoice_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_stripe_subscription_id",
                "invoice_id": invoice_id
            })

        existing_subscription = get_client_subscription_by_stripe_subscription_id(
            stripe_subscription_id
        )

        if not existing_subscription:
            print(
                f"STRIPE INVOICE PAYMENT FAILED IGNORED ⚠️ subscription not found stripe_subscription_id={stripe_subscription_id} invoice_id={invoice_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "subscription_not_found",
                "stripe_subscription_id": stripe_subscription_id,
                "invoice_id": invoice_id
            })

        session_id = existing_subscription.get("session_id") or ""
        plan_name = existing_subscription.get("plan_name") or "growth"
        source_partner_id = normalize_source_partner_id(
            existing_subscription.get("source_partner_id") or ""
        )

        stripe_customer_id = (
            invoice.get("customer", "")
            or existing_subscription.get("stripe_customer_id")
            or ""
        )

        package_amount = existing_subscription.get("package_amount") or ""

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=existing_subscription.get("client_id") or session_id,
            bot_id=existing_subscription.get("bot_id") or "",
            status="payment_failed",
            custom_reply_limit=existing_subscription.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Payment failed by Stripe invoice.payment_failed event {event_id}; invoice_id={invoice_id}",
            reset_usage=False,
            source_partner_id=source_partner_id
        )

        # ===== ALSAAB PAYMENT GRACE PERIOD V1 START =====
        # Stripe has not given up yet: Smart Retries makes up to four attempts
        # across about three weeks, and most failures clear on the second one.
        #
        # Treating the first failure as final punished the sponsor immediately —
        # the customer left their active count, which could drop them a whole
        # level and cost them the deeper commissions for that month, all for a
        # card that went through two days later.
        #
        # The customer keeps counting until the grace window closes. When
        # Stripe truly gives up it sends customer.subscription.deleted, which
        # is handled separately and ends it for real.
        try:
            from database import get_connection as _grace_connection

            # Stripe is configured for Smart Retries: up to 8 attempts within
            # 2 weeks, then "cancel the subscription". 15 days keeps the
            # customer counting for the whole retry window plus a day, and the
            # customer.subscription.deleted event ends it sooner if Stripe
            # gives up early.
            grace_days = int(os.getenv("PAYMENT_GRACE_DAYS", "15"))
            attempt = int(invoice.get("attempt_count") or 0)

            # Stripe's own hosted invoice page. Storing it is what makes a
            # "pay now" button possible without this project ever touching a
            # card number: the customer lands on Stripe, updates the card and
            # pays there, and the resulting invoice.paid clears everything.
            hosted_invoice_url = invoice.get("hosted_invoice_url") or ""
            next_attempt = invoice.get("next_payment_attempt")

            grace_conn = _grace_connection()
            grace_cursor = grace_conn.cursor()
            grace_cursor.execute(
                """
                UPDATE subscriptions
                SET payment_failed_at   = COALESCE(payment_failed_at, NOW()),
                    payment_grace_until = COALESCE(payment_failed_at, NOW())
                                          + (? || ' days')::INTERVAL,
                    payment_retry_count = ?,
                    last_invoice_url    = COALESCE(NULLIF(?, ''), last_invoice_url),
                    last_invoice_id     = COALESCE(NULLIF(?, ''), last_invoice_id),
                    customer_email      = COALESCE(NULLIF(?, ''), customer_email)
                WHERE stripe_subscription_id = ?
                """,
                (
                    str(grace_days), attempt, hosted_invoice_url,
                    invoice.get("id") or "",
                    (invoice.get("customer_email") or "").strip(),
                    stripe_subscription_id,
                ),
            )
            grace_conn.commit()
            grace_conn.close()

            print(
                f"PAYMENT GRACE APPLIED ✅ stripe_subscription_id={stripe_subscription_id} "
                f"attempt={attempt} of Stripe's retries; grace_days={grace_days}; "
                f"next_stripe_attempt={next_attempt}; pay_now_link={'yes' if hosted_invoice_url else 'no'}",
                flush=True
            )

        except Exception as grace_error:
            print(f"PAYMENT GRACE ERROR ⚠️ {grace_error}", flush=True)
        # ===== ALSAAB PAYMENT GRACE PERIOD V1 END =====

        print(
            f"STRIPE INVOICE PAYMENT FAILED HANDLED ⚠️ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id} invoice_id={invoice_id}",
            flush=True
        )

        telegram_notify(
            f"🔴 <b>فشل دفع</b>"
            "\n"
            f"العميل: {session_id}"
            "\n"
            f"الباقة: {plan_name}"
            "\n"
            f"الراعي: {source_partner_id or '-'}"
            "\n"
            f"المحاولة: {attempt}"
            "\n"
            f"فترة السماح: {grace_days} يوماً"
            "\n"
            f"محاولة Stripe القادمة: {next_attempt or '-'}"
            "\n"
            f"رابط الدفع الآن: {hosted_invoice_url or 'غير متاح'}"
            "\n"
            f"الفاتورة: <code>{invoice_id}</code>"
        )

        return jsonify({
            "status": "success",
            "message": "invoice.payment_failed handled",
            "invoice_id": invoice_id,
            "stripe_subscription_id": stripe_subscription_id,
            "subscription": subscription
        })

    if event_type == "customer.subscription.deleted":
        stripe_subscription = event.get("data", {}).get("object", {})

        stripe_subscription_id = stripe_subscription.get("id", "") or ""

        if isinstance(stripe_subscription_id, dict):
            stripe_subscription_id = stripe_subscription_id.get("id", "") or ""

        if not stripe_subscription_id:
            print(
                "STRIPE SUBSCRIPTION DELETED IGNORED ⚠️ missing stripe_subscription_id",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_stripe_subscription_id"
            })

        existing_subscription = get_client_subscription_by_stripe_subscription_id(
            stripe_subscription_id
        )

        if not existing_subscription:
            print(
                f"STRIPE SUBSCRIPTION DELETED IGNORED ⚠️ subscription not found stripe_subscription_id={stripe_subscription_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "subscription_not_found",
                "stripe_subscription_id": stripe_subscription_id
            })

        session_id = existing_subscription.get("session_id") or ""
        plan_name = existing_subscription.get("plan_name") or "growth"
        source_partner_id = normalize_source_partner_id(
            existing_subscription.get("source_partner_id") or ""
        )

        stripe_customer_id = (
            stripe_subscription.get("customer", "")
            or existing_subscription.get("stripe_customer_id")
            or ""
        )

        package_amount = existing_subscription.get("package_amount") or ""

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=existing_subscription.get("client_id") or session_id,
            bot_id=existing_subscription.get("bot_id") or "",
            status="cancelled",
            custom_reply_limit=existing_subscription.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Cancelled automatically by Stripe customer.subscription.deleted event {event_id}",
            reset_usage=False,
            source_partner_id=source_partner_id
        )

        print(
            f"STRIPE SUBSCRIPTION DELETED HANDLED ⚠️ session_id={session_id} plan={plan_name} source_partner_id={source_partner_id} stripe_subscription_id={stripe_subscription_id}",
            flush=True
        )

        telegram_notify(
            f"⚫ <b>انتهى اشتراك</b>"
            "\n"
            f"العميل: {session_id}"
            "\n"
            f"الباقة: {plan_name}"
            "\n"
            f"الراعي: {source_partner_id or '-'}"
            "\n"
            f"Stripe: <code>{stripe_subscription_id}</code>"
            "\n"
            f"الخدمة توقفت وسيسقط العميل من عدّاد الراعي."
        )

        return jsonify({
            "status": "success",
            "message": "customer.subscription.deleted handled",
            "stripe_subscription_id": stripe_subscription_id,
            "subscription": subscription
        })

    if event_type == "customer.subscription.updated":
        stripe_subscription = event.get("data", {}).get("object", {})

        stripe_subscription_id = stripe_subscription.get("id", "") or ""

        if isinstance(stripe_subscription_id, dict):
            stripe_subscription_id = stripe_subscription_id.get("id", "") or ""

        if not stripe_subscription_id:
            print(
                "STRIPE SUBSCRIPTION UPDATED IGNORED ⚠️ missing stripe_subscription_id",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "missing_stripe_subscription_id"
            })

        existing_subscription = get_client_subscription_by_stripe_subscription_id(
            stripe_subscription_id
        )

        if not existing_subscription:
            print(
                f"STRIPE SUBSCRIPTION UPDATED IGNORED ⚠️ subscription not found stripe_subscription_id={stripe_subscription_id}",
                flush=True
            )

            return jsonify({
                "status": "ignored",
                "reason": "subscription_not_found",
                "stripe_subscription_id": stripe_subscription_id
            })

        stripe_status = str(stripe_subscription.get("status", "") or "").lower().strip()

        mapped_status = existing_subscription.get("subscription_status") or "active"

        if stripe_status in ["past_due", "unpaid", "incomplete", "incomplete_expired"]:
            mapped_status = "payment_failed"

        elif stripe_status in ["canceled", "cancelled"]:
            mapped_status = "cancelled"

        elif stripe_status in ["paused"]:
            mapped_status = "inactive"

        elif stripe_status in ["active", "trialing"]:
            print(
                f"STRIPE SUBSCRIPTION UPDATED RECEIVED ✅ active update ignored for commission safety stripe_subscription_id={stripe_subscription_id}",
                flush=True
            )

            return jsonify({
                "status": "received",
                "message": "customer.subscription.updated active event received; invoice.paid handles renewal/commission logic",
                "stripe_subscription_id": stripe_subscription_id,
                "stripe_status": stripe_status
            })

        session_id = existing_subscription.get("session_id") or ""
        plan_name = existing_subscription.get("plan_name") or "growth"
        source_partner_id = normalize_source_partner_id(
            existing_subscription.get("source_partner_id") or ""
        )

        stripe_customer_id = (
            stripe_subscription.get("customer", "")
            or existing_subscription.get("stripe_customer_id")
            or ""
        )

        package_amount = existing_subscription.get("package_amount") or ""

        subscription = create_or_update_subscription(
            session_id=session_id,
            plan_name=plan_name,
            client_id=existing_subscription.get("client_id") or session_id,
            bot_id=existing_subscription.get("bot_id") or "",
            status=mapped_status,
            custom_reply_limit=existing_subscription.get("monthly_reply_limit"),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            package_amount=package_amount,
            notes=f"Updated automatically by Stripe customer.subscription.updated event {event_id}; stripe_status={stripe_status}",
            reset_usage=False,
            source_partner_id=source_partner_id
        )

        print(
            f"STRIPE SUBSCRIPTION UPDATED HANDLED ✅ session_id={session_id} mapped_status={mapped_status} stripe_status={stripe_status} stripe_subscription_id={stripe_subscription_id}",
            flush=True
        )

        return jsonify({
            "status": "success",
            "message": "customer.subscription.updated handled",
            "stripe_subscription_id": stripe_subscription_id,
            "stripe_status": stripe_status,
            "mapped_status": mapped_status,
            "subscription": subscription
        })

    return jsonify({
        "status": "ignored",
        "message": f"Unhandled event type: {event_type}"
    })


@app.route("/payment-success", methods=["GET"])
def payment_success():
    return render_template("payment_success.html")


@app.route("/payment-cancel", methods=["GET"])
def payment_cancel():
    return render_template("payment_cancel.html")


# ALSAAB_STRICT_PAYMENT_GUARD_V2
def _alsaab_detect_explicit_plan_from_user_message(message):
    msg = str(message or "").lower()

    plan_aliases = [
        ("diamond", ["diamond", "الماسية", "ماسيه", "2399"]),
        ("elite", ["elite", "النخبة", "نخبة", "1199"]),
        ("growth", ["growth", "النمو", "نمو", "599"]),
        ("starter", ["starter", "البداية", "بداية", "299"]),
        ("entry", ["entry", "الدخول", "دخول", "99"]),
    ]

    for plan, aliases in plan_aliases:
        if any(alias.lower() in msg for alias in aliases):
            return plan

    return None


def detect_safe_alsaab_opportunity_payment_plan(message):
    msg = str(message or "").lower()

    opportunity_words = [
        "alsaab", "الصعب", "نظام الصعب", "نفس النظام", "فرصة دخل", "دخل اضافي", "دخل إضافي",
        "الشراكة", "شراكة", "شريك", "ابي اشترك", "أبي اشترك", "ابغي اشترك", "أبغي اشترك"
    ]

    payment_words = [
        "رابط الدفع", "ادفع", "أدفع", "دفع", "الدفع", "اشترك", "اشتراك",
        "باخذ", "بآخذ", "أخذ", "اخذ", "ارسل الرابط", "طرش الرابط",
        "payment", "pay", "checkout", "subscribe"
    ]

    has_opportunity_intent = any(w.lower() in msg for w in opportunity_words)
    has_payment_intent = any(w.lower() in msg for w in payment_words)
    plan = _alsaab_detect_explicit_plan_from_user_message(msg)

    if has_opportunity_intent and has_payment_intent and plan:
        return plan

    return None


def alsaab_user_explicitly_requested_payment_with_plan(message):
    msg = str(message or "").lower()

    payment_words = [
        "رابط الدفع", "ادفع", "أدفع", "دفع", "الدفع", "اشترك", "اشتراك",
        "باخذ", "بآخذ", "أخذ", "اخذ", "ارسل الرابط", "طرش الرابط",
        "payment", "pay", "checkout", "subscribe"
    ]

    plan = _alsaab_detect_explicit_plan_from_user_message(msg)
    has_payment = any(w.lower() in msg for w in payment_words)

    return bool(has_payment and plan)


def alsaab_guard_auto_payment_links(reply, user_message):
    import re

    reply_text = str(reply or "")

    has_pay_link = bool(re.search(
        r"(https?://[^\s<>'\"]+)?/pay/(entry|starter|growth|elite|diamond)\b|buy\.stripe\.com",
        reply_text,
        flags=re.IGNORECASE
    ))

    if not has_pay_link:
        return reply_text

    if alsaab_user_explicitly_requested_payment_with_plan(user_message):
        return reply_text

    return (
        "أقدر أرسل لك رابط الدفع، لكن لازم تحدد الباقة أولاً عشان ما أرسل لك رابط غلط.\n\n"
        "الباقات المتوفرة:\n"
        "• Entry — 99 درهم شهرياً\n"
        "• Starter — 299 درهم شهرياً\n"
        "• Growth — 599 درهم شهرياً\n"
        "• Elite — 1199 درهم شهرياً\n"
        "• Diamond — 2399 درهم شهرياً\n\n"
        "أي باقة تريد؟"
    )


# ALSAAB_FINAL_HARD_PAYMENT_LOCK_V3
def alsaab_exact_payment_request_plan_v3(message):
    msg = str(message or "").lower()

    payment_words = [
        "pay", "payment", "checkout", "subscribe",
        "\u062f\u0641\u0639",        # دفع
        "\u0627\u062f\u0641\u0639",  # ادفع
        "\u0623\u062f\u0641\u0639",  # أدفع
        "\u0631\u0627\u0628\u0637",  # رابط
        "\u0627\u0634\u062a\u0631\u0643", # اشترك
        "\u0627\u0634\u062a\u0631\u0627\u0643", # اشتراك
    ]

    plans = [
        ("diamond", ["diamond", "2399", "\u0627\u0644\u0645\u0627\u0633\u064a\u0629", "\u0645\u0627\u0633\u064a\u0629"]),
        ("elite", ["elite", "1199", "\u0627\u0644\u0646\u062e\u0628\u0629", "\u0646\u062e\u0628\u0629"]),
        ("growth", ["growth", "599", "\u0627\u0644\u0646\u0645\u0648", "\u0646\u0645\u0648"]),
        ("starter", ["starter", "299", "\u0627\u0644\u0628\u062f\u0627\u064a\u0629", "\u0628\u062f\u0627\u064a\u0629"]),
        ("entry", ["entry", "99", "\u0627\u0644\u062f\u062e\u0648\u0644", "\u062f\u062e\u0648\u0644"]),
    ]

    has_payment = any(w in msg for w in payment_words)

    selected_plan = None
    for plan, aliases in plans:
        if any(alias.lower() in msg for alias in aliases):
            selected_plan = plan
            break

    if has_payment and selected_plan:
        return selected_plan

    return None


def detect_safe_alsaab_opportunity_payment_plan(message):
    return alsaab_exact_payment_request_plan_v3(message)


def alsaab_guard_auto_payment_links(reply, user_message):
    import re

    reply_text = str(reply or "")

    has_pay_link = bool(re.search(
        r"https?://\S*(?:/pay/(?:entry|starter|growth|elite|diamond)|buy\.stripe\.com)\S*|/pay/(?:entry|starter|growth|elite|diamond)\S*",
        reply_text,
        flags=re.IGNORECASE
    ))

    if not has_pay_link:
        return reply_text

    if alsaab_exact_payment_request_plan_v3(user_message):
        return reply_text

    return _al_pay_reply(user_message,"choose")


# ALSAAB_AFTER_RESPONSE_PAYMENT_FIREWALL_V2
@app.after_request
def alsaab_after_response_payment_firewall_v2(response):
    try:
        if request.path != "/chat":
            return response

        raw = response.get_data(as_text=True) or ""
        if "/pay/" not in raw and "buy.stripe.com" not in raw:
            return response

        import json
        import re

        try:
            data = json.loads(raw)
        except Exception:
            return response

        if not isinstance(data, dict):
            return response

        reply = str(data.get("reply") or "")
        if not reply:
            return response

        has_pay_link = bool(re.search(
            r"https?://\S*(?:/pay/(?:entry|starter|growth|elite|diamond)|buy\.stripe\.com)\S*|/pay/(?:entry|starter|growth|elite|diamond)\S*",
            reply,
            flags=re.IGNORECASE
        ))

        if not has_pay_link:
            return response

        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}

        message = str((payload.get("original_user_message") or payload.get("message") or "")).lower()

        payment_words = [
            "pay", "payment", "checkout", "subscribe",
            "\u062f\u0641\u0639",
            "\u0627\u062f\u0641\u0639",
            "\u0623\u062f\u0641\u0639",
            "\u0631\u0627\u0628\u0637 \u0627\u0644\u062f\u0641\u0639",
            "\u0631\u0627\u0628\u0637 \u062f\u0641\u0639",
            "\u0627\u0634\u062a\u0631\u0643",
            "\u0627\u0634\u062a\u0631\u0627\u0643"
        ]

        plan_words = [
            "entry", "starter", "growth", "elite", "diamond",
            "99", "299", "599", "1199", "2399",
            "\u0627\u0644\u062f\u062e\u0648\u0644", "\u062f\u062e\u0648\u0644",
            "\u0627\u0644\u0628\u062f\u0627\u064a\u0629", "\u0628\u062f\u0627\u064a\u0629",
            "\u0627\u0644\u0646\u0645\u0648", "\u0646\u0645\u0648",
            "\u0627\u0644\u0646\u062e\u0628\u0629", "\u0646\u062e\u0628\u0629",
            "\u0627\u0644\u0645\u0627\u0633\u064a\u0629", "\u0645\u0627\u0633\u064a\u0629"
        ]

        try:
            req_payload = request.get_json(silent=True) or {}
        except Exception:
            req_payload = {}
        try:
            decision_message = (
                req_payload.get("original_user_message")
                or req_payload.get("message")
                or message
                or ""
            )
        except Exception:
            decision_message = message
        try:
            # If /chat already generated a safe payment reply, never let the firewall kill it.
            # This keeps random AI-generated payment links blocked, but allows approved payment-gate links.
            allowed = bool(data.get("safe_alsaab_opportunity_payment")) or bool(
                alsaab_payment_plan_v8(decision_message)
                or alsaab_chat_explicit_payment_plan_v5(decision_message)
            )
        except Exception:
            allowed = bool(data.get("safe_alsaab_opportunity_payment")) or (any(w in message for w in payment_words) and any(w in message for w in plan_words))

        if allowed:
            data["reply"] = reply.replace("http://alsaab-ai.onrender.com", "https://alsaab-ai.onrender.com")
        else:
            data["reply"] = (
                "هلا وسهلا.\n"
                "أنا موظف مبيعات ذكي أساعدك تفهم الخدمة وتختار الأنسب.\n\n"
                "ما بطرش لك رابط دفع إلا إذا طلبت الدفع وحددت الباقة بوضوح.\n"
                "شو حاب تعرف بالضبط؟"
            )

        new_raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        response.set_data(new_raw)
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response.headers["Content-Length"] = str(len(new_raw))
        return response

    except Exception as e:
        print("ALSAAB_AFTER_RESPONSE_PAYMENT_FIREWALL_V2_ERROR=" + str(e), flush=True)
        return response


# ===== ALSAAB_PAYMENT_PLAN_V8_REQUEST_SAFE START =====
# Dedicated payment phrase detector used by both /chat and the after-response firewall.
# Uses unicode escapes to avoid Windows/PowerShell Arabic encoding corruption.
def alsaab_payment_plan_v8(message):
    text = str(message or "").strip().lower()
    replacements = {
        "\u0623": "\u0627",
        "\u0625": "\u0627",
        "\u0622": "\u0627",
        "\u0649": "\u064a",
        "\u0629": "\u0647",
        "\u0624": "\u0648",
        "\u0626": "\u064a",
        "\u0640": "",
        "\u0669": "9",
        "\u0668": "8",
        "\u0667": "7",
        "\u0666": "6",
        "\u0665": "5",
        "\u0664": "4",
        "\u0663": "3",
        "\u0662": "2",
        "\u0661": "1",
        "\u0660": "0",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    text = " ".join(text.split())
    if not text:
        return None

    plan_aliases = [
        ("diamond", ["diamond", "\u062f\u0627\u064a\u0645\u0648\u0646\u062f", "\u0627\u0644\u0645\u0627\u0633\u064a\u0647", "\u0645\u0627\u0633\u064a\u0647", "2399"]),
        ("elite", ["elite", "\u0627\u064a\u0644\u064a\u062a", "\u0627\u0644\u0646\u062e\u0628\u0647", "\u0646\u062e\u0628\u0647", "1199"]),
        ("growth", ["growth", "\u0627\u0644\u0646\u0645\u0648", "\u0646\u0645\u0648", "599"]),
        ("starter", ["starter", "\u0633\u062a\u0627\u0631\u062a\u0631", "\u0627\u0644\u0628\u062f\u0627\u064a\u0647", "\u0628\u062f\u0627\u064a\u0647", "299"]),
        ("entry", ["entry", "\u0627\u0646\u062a\u0631\u064a", "\u0628\u0627\u0642\u0629 \u0627\u0644\u062f\u062e\u0648\u0644", "\u0628\u0627\u0642\u0647 \u0627\u0644\u062f\u062e\u0648\u0644", "\u0627\u0644\u062f\u062e\u0648\u0644", "\u062f\u062e\u0648\u0644", "99"]),
    ]

    selected_plan = None
    for plan, aliases in plan_aliases:
        if any(alias in text for alias in aliases):
            selected_plan = plan
            break

    payment_intents = [
        "\u0631\u0627\u0628\u0637 \u0627\u0644\u062f\u0641\u0639",
        "\u0631\u0627\u0628\u0637 \u062f\u0641\u0639",
        "\u0631\u0627\u0628\u0637 \u062f\u062e\u0648\u0644",
        "\u0631\u0627\u0628\u0637 \u0628\u0627\u0642\u0629",
        "\u0631\u0627\u0628\u0637 \u0628\u0627\u0642\u0647",
        "\u0631\u0627\u0628\u0637 \u0627\u0644\u0628\u0627\u0642\u0647",
        "\u0631\u0627\u0628\u0637 \u0627\u0634\u062a\u0631\u0627\u0643",
        "\u0637\u0631\u0634 \u0631\u0627\u0628\u0637",
        "\u0637\u0631\u0634\u0644\u064a \u0631\u0627\u0628\u0637",
        "\u0637\u0631\u0634 \u0627\u0644\u0631\u0627\u0628\u0637",
        "\u0627\u0631\u0633\u0644 \u0631\u0627\u0628\u0637",
        "\u0627\u0631\u0633\u0644\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0631\u0633\u0644 \u0627\u0644\u0631\u0627\u0628\u0637",
        "\u0627\u0628\u0627 \u0631\u0627\u0628\u0637",
        "\u0627\u0628\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0628\u063a\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0628\u063a\u0627 \u0631\u0627\u0628\u0637",
        "\u0627\u062d\u062a\u0627\u062c \u0631\u0627\u0628\u0637",
        "\u0645\u062d\u062a\u0627\u062c \u0631\u0627\u0628\u0637",
        "\u0639\u0637\u0646\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0639\u0637\u0646\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u062f\u0641\u0639",
        "\u0627\u0644\u062f\u0641\u0639",
        "\u0627\u0628\u0627 \u0627\u062f\u0641\u0639",
        "\u0627\u0628\u064a \u0627\u062f\u0641\u0639",
        "\u0627\u0628\u063a\u064a \u0627\u062f\u0641\u0639",
        "\u0627\u0628\u063a\u0627 \u0627\u062f\u0641\u0639",
        "\u0627\u0631\u064a\u062f \u0627\u062f\u0641\u0639",
        "\u0627\u062d\u062a\u0627\u062c \u0627\u062f\u0641\u0639",
        "\u0645\u062d\u062a\u0627\u062c \u0627\u062f\u0641\u0639",
        "\u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0634\u062a\u0631\u0627\u0643",
        "\u0627\u0628\u0627 \u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0628\u064a \u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0628\u063a\u064a \u0627\u0634\u062a\u0631\u0643",
    ]

    has_payment_intent = any(x in text for x in payment_intents)

    if selected_plan and ("\u0631\u0627\u0628\u0637" in text or "\u062f\u0641\u0639" in text or "\u0627\u062f\u0641\u0639" in text or "\u0627\u0634\u062a\u0631\u0627\u0643" in text or "\u0627\u0634\u062a\u0631\u0643" in text):
        return selected_plan

    if has_payment_intent:
        return selected_plan or "entry"

    return None
# ===== ALSAAB_PAYMENT_PLAN_V8_REQUEST_SAFE END =====


# ALSAAB_CHAT_PAYMENT_GATE_V5_START
def alsaab_chat_explicit_payment_plan_v5(message):
    text = str(message or "").strip().lower()
    replacements = {
        "\u0623": "\u0627",
        "\u0625": "\u0627",
        "\u0622": "\u0627",
        "\u0649": "\u064a",
        "\u0629": "\u0647",
        "\u0624": "\u0648",
        "\u0626": "\u064a",
        "\u0640": "",
        "\u0669": "9",
        "\u0668": "8",
        "\u0667": "7",
        "\u0666": "6",
        "\u0665": "5",
        "\u0664": "4",
        "\u0663": "3",
        "\u0662": "2",
        "\u0661": "1",
        "\u0660": "0",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    text = " ".join(text.split())
    if not text:
        return None

    plan_aliases = [
        ("diamond", ["diamond", "\u062f\u0627\u064a\u0645\u0648\u0646\u062f", "\u0627\u0644\u0645\u0627\u0633\u064a\u0647", "\u0645\u0627\u0633\u064a\u0647", "2399"]),
        ("elite", ["elite", "\u0627\u064a\u0644\u064a\u062a", "\u0627\u0644\u0646\u062e\u0628\u0647", "\u0646\u062e\u0628\u0647", "1199"]),
        ("growth", ["growth", "\u0627\u0644\u0646\u0645\u0648", "\u0646\u0645\u0648", "599"]),
        ("starter", ["starter", "\u0633\u062a\u0627\u0631\u062a\u0631", "\u0627\u0644\u0628\u062f\u0627\u064a\u0647", "\u0628\u062f\u0627\u064a\u0647", "299"]),
        ("entry", ["entry", "\u0627\u0646\u062a\u0631\u064a", "\u0628\u0627\u0642\u0629 \u0627\u0644\u062f\u062e\u0648\u0644", "\u0628\u0627\u0642\u0647 \u0627\u0644\u062f\u062e\u0648\u0644", "\u0627\u0644\u062f\u062e\u0648\u0644", "\u062f\u062e\u0648\u0644", "99"]),
    ]

    selected_plan = None
    for plan, aliases in plan_aliases:
        if any(alias in text for alias in aliases):
            selected_plan = plan
            break

    payment_intents = [
        "\u0631\u0627\u0628\u0637 \u0627\u0644\u062f\u0641\u0639",
        "\u0631\u0627\u0628\u0637 \u062f\u0641\u0639",
        "\u0631\u0627\u0628\u0637 \u0627\u0644\u0628\u0627\u0642\u0647",
        "\u0631\u0627\u0628\u0637 \u0628\u0627\u0642\u0647",
        "\u0631\u0627\u0628\u0637 \u0627\u0644\u0627\u0634\u062a\u0631\u0627\u0643",
        "\u0631\u0627\u0628\u0637 \u0627\u0634\u062a\u0631\u0627\u0643",
        "\u0631\u0627\u0628\u0637 \u062f\u062e\u0648\u0644",
        "\u0631\u0627\u0628\u0637 \u0628\u0627\u0642\u0629 \u0627\u0644\u062f\u062e\u0648\u0644",
        "\u0631\u0627\u0628\u0637 \u0628\u0627\u0642\u0647 \u0627\u0644\u062f\u062e\u0648\u0644",
        "\u0637\u0631\u0634 \u0631\u0627\u0628\u0637",
        "\u0637\u0631\u0634\u0644\u064a \u0631\u0627\u0628\u0637",
        "\u0637\u0631\u0634 \u0627\u0644\u0631\u0627\u0628\u0637",
        "\u0627\u0631\u0633\u0644 \u0631\u0627\u0628\u0637",
        "\u0627\u0631\u0633\u0644\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0631\u0633\u0644 \u0627\u0644\u0631\u0627\u0628\u0637",
        "\u0627\u0628\u0627 \u0631\u0627\u0628\u0637",
        "\u0627\u0628\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0628\u063a\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0628\u063a\u0627 \u0631\u0627\u0628\u0637",
        "\u0627\u062d\u062a\u0627\u062c \u0631\u0627\u0628\u0637",
        "\u0645\u062d\u062a\u0627\u062c \u0631\u0627\u0628\u0637",
        "\u0639\u0637\u0646\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0639\u0637\u0646\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u062f\u0641\u0639",
        "\u0627\u0644\u062f\u0641\u0639",
        "\u0627\u0628\u0627 \u0627\u062f\u0641\u0639",
        "\u0627\u0628\u064a \u0627\u062f\u0641\u0639",
        "\u0627\u0628\u063a\u064a \u0627\u062f\u0641\u0639",
        "\u0627\u0628\u063a\u0627 \u0627\u062f\u0641\u0639",
        "\u0627\u0631\u064a\u062f \u0627\u062f\u0641\u0639",
        "\u0627\u062d\u062a\u0627\u062c \u0627\u062f\u0641\u0639",
        "\u0645\u062d\u062a\u0627\u062c \u0627\u062f\u0641\u0639",
        "\u0628\u063a\u064a\u062a \u0627\u062f\u0641\u0639",
        "\u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0634\u062a\u0631\u0627\u0643",
        "\u0627\u0628\u0627 \u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0628\u064a \u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0628\u063a\u064a \u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0628\u063a\u0627 \u0627\u0634\u062a\u0631\u0643",
    ]

    has_payment_intent = any(x in text for x in payment_intents)

    if selected_plan and ("\u0631\u0627\u0628\u0637" in text or "\u062f\u0641\u0639" in text or "\u0627\u062f\u0641\u0639" in text or "\u0627\u0634\u062a\u0631\u0627\u0643" in text or "\u0627\u0634\u062a\u0631\u0643" in text):
        return selected_plan

    if has_payment_intent:
        return selected_plan or "entry"

    return None


def alsaab_chat_strip_unwanted_payment_links_v5(reply, payment_decision_message):
    import re

    reply_text = str(reply or "")

    has_pay_link = bool(re.search(
        r"https?://\S*(?:/pay/(?:entry|starter|growth|elite|diamond)|buy\.stripe\.com)\S*|/pay/(?:entry|starter|growth|elite|diamond)\S*",
        reply_text,
        flags=re.IGNORECASE
    ))

    if not has_pay_link:
        return reply_text

    if alsaab_chat_explicit_payment_plan_v5(payment_decision_message):
        return reply_text.replace("http://alsaab-ai.onrender.com", "https://alsaab-ai.onrender.com")

    return _al_pay_reply(payment_decision_message,"choose")
# ALSAAB_CHAT_PAYMENT_GATE_V5_END

@app.route("/chat", methods=["POST"])
def chat():
    print("MAIN CHAT ROUTE HIT ✅", flush=True)

    data = request.json or {}
    print(f"MAIN REQUEST DATA ✅ {data}", flush=True)

    message = data.get("message", "").strip()
    payment_decision_message = (data.get("original_user_message") or message or "").strip()
    print(f"PAYMENT DECISION MESSAGE ✅ {payment_decision_message}", flush=True)
    session_id = data.get("session_id")
    def extract_source_partner_id_from_payload(payload):
        candidates = [
            payload.get("source_partner_id"),
            payload.get("referrer_partner_id"),
            payload.get("ref"),
            payload.get("smart_link_ref"),
            payload.get("context_partner_id"),
            payload.get("client_context_id"),
            payload.get("partner_id"),
        ]

        for value in candidates:
            normalized = normalize_source_partner_id(value)
            if normalized:
                return normalized

        for url_key in ("page_url", "referrer_url"):
            raw_url = payload.get(url_key) or ""
            try:
                from urllib.parse import urlparse, parse_qs

                query = parse_qs(urlparse(str(raw_url)).query)

                for key in ("ref", "source_partner_id", "partner_id", "sponsor_partner_id", "aid"):
                    for value in query.get(key, []):
                        normalized = normalize_source_partner_id(value)
                        if normalized:
                            return normalized
            except Exception:
                pass

        return ""

    source_partner_id = extract_source_partner_id_from_payload(data)

    # ===== ALSAAB_DIRECT_PAYMENT_GATE_BALANCED_V1 START =====
    try:
        _msg = str(payment_decision_message or "").strip().lower()
        for _a, _b in {
            "\u0623": "\u0627", "\u0625": "\u0627", "\u0622": "\u0627",
            "\u0649": "\u064a", "\u0629": "\u0647", "\u0640": "",
            "\u0669": "9", "\u0668": "8", "\u0667": "7", "\u0666": "6", "\u0665": "5",
            "\u0664": "4", "\u0663": "3", "\u0662": "2", "\u0661": "1", "\u0660": "0",
        }.items():
            _msg = _msg.replace(_a, _b)
        _msg = " ".join(_msg.split())

        _plan = None
        if any(x in _msg for x in ["diamond", "\u062f\u0627\u064a\u0645\u0648\u0646\u062f", "\u0645\u0627\u0633\u064a\u0647", "2399"]):
            _plan = "diamond"
        elif any(x in _msg for x in ["elite", "\u0627\u064a\u0644\u064a\u062a", "\u0646\u062e\u0628\u0647", "1199"]):
            _plan = "elite"
        elif any(x in _msg for x in ["growth", "\u0646\u0645\u0648", "599"]):
            _plan = "growth"
        elif any(x in _msg for x in ["starter", "\u0633\u062a\u0627\u0631\u062a\u0631", "\u0628\u062f\u0627\u064a\u0647", "299"]):
            _plan = "starter"
        elif any(x in _msg for x in ["entry", "\u0627\u0646\u062a\u0631\u064a", "\u0627\u0644\u062f\u062e\u0648\u0644", "\u062f\u062e\u0648\u0644", "99"]):
            _plan = "entry"

        _has_payment_intent = any(x in _msg for x in [
            "\u0631\u0627\u0628\u0637", "\u062f\u0641\u0639", "\u0627\u062f\u0641\u0639",
            "\u0627\u0634\u062a\u0631\u0627\u0643", "\u0627\u0634\u062a\u0631\u0643",
            "\u0628\u0627\u062e\u0630", "\u0628\u0627\u062e\u0630", "\u0627\u0628\u0627 \u0627\u062e\u0630",
            "\u0627\u0628\u064a \u0627\u062e\u0630", "\u0627\u0628\u063a\u064a \u0627\u062e\u0630"
        ])

        # Link only when payment intent + package/price are clear.
        if _has_payment_intent and _plan:
            _reply = build_safe_alsaab_opportunity_payment_reply(_plan, session_id, source_partner_id=source_partner_id)
            return jsonify({
                "reply": _reply,
                "session_id": session_id,
                "source_partner_id": source_partner_id,
                "safe_alsaab_opportunity_payment": {
                    "plan": _plan,
                    "source_partner_id": source_partner_id
                }
            })

        # If payment link requested but package is unclear, ask one clean question. No payment link.
        if _has_payment_intent and not _plan:
            return jsonify({
                "reply": _al_pay_reply(payment_decision_message,"choose"),
                "session_id": session_id,
                "source_partner_id": source_partner_id
            })
    except Exception as _e:
        print("DIRECT_PAYMENT_GATE_BALANCED_ERROR=" + str(_e), flush=True)
    # ===== ALSAAB_DIRECT_PAYMENT_GATE_BALANCED_V1 END =====


    print(f"MAIN MESSAGE ✅ {message}", flush=True)
    print(f"MAIN SESSION BEFORE ✅ {session_id}", flush=True)
    print(f"MAIN SOURCE PARTNER ✅ {source_partner_id}", flush=True)

    if not session_id:
        session_id = str(uuid.uuid4())
        print(f"MAIN NEW SESSION CREATED ✅ {session_id}", flush=True)

    if not message:
        print("MAIN EMPTY MESSAGE ❌", flush=True)
        return jsonify({
            "reply": "اكتب رسالتك عشان أقدر أساعدك.",
            "session_id": session_id,
            "source_partner_id": source_partner_id
        })

    usage_session_id = session_id
    brain_message = payment_decision_message

    try:
        save_message(session_id, "user", payment_decision_message)
        print("MAIN USER MESSAGE SAVED ✅", flush=True)

        safe_alsaab_payment_plan = (alsaab_payment_plan_v8(payment_decision_message) or alsaab_chat_explicit_payment_plan_v5(payment_decision_message))
        if safe_alsaab_payment_plan:
            safe_alsaab_payment_reply = build_safe_alsaab_opportunity_payment_reply(
                safe_alsaab_payment_plan,
                session_id,
                source_partner_id
            )

            if safe_alsaab_payment_reply:
                safe_alsaab_payment_reply = alsaab_chat_strip_unwanted_payment_links_v5(safe_alsaab_payment_reply, payment_decision_message)
                save_message(session_id, "bot", safe_alsaab_payment_reply)
                print(
                    f"SAFE ALSAAB OPPORTUNITY PAYMENT LINK REPLY OK session_id={session_id} plan={safe_alsaab_payment_plan} source_partner_id={source_partner_id}",
                    flush=True
                )

                return jsonify({
                    "reply": alsaab_chat_strip_unwanted_payment_links_v5(safe_alsaab_payment_reply, payment_decision_message),
                    "session_id": session_id,
                    "source_partner_id": source_partner_id,
                    "safe_alsaab_opportunity_payment": {
                        "plan": safe_alsaab_payment_plan,
                        "source_partner_id": source_partner_id
                    }
                })


        subscription = get_client_subscription(usage_session_id)

        if is_training_command(payment_decision_message) and not is_active_subscription(subscription):
            print("TRAINING BLOCKED ❌ no active subscription", flush=True)

            save_message(session_id, "bot", TRAINING_LOCKED_REPLY)

            return jsonify({
                "reply": TRAINING_LOCKED_REPLY,
                "session_id": session_id,
                "source_partner_id": source_partner_id,
                "training": {
                    "allowed": False,
                    "reason": "no_active_subscription"
                }
            })

        if subscription:
            print(f"SUBSCRIPTION FOUND ✅ session_id={session_id}", flush=True)

            usage_check = can_client_use_bot(session_id)

            if not usage_check.get("allowed"):
                blocked_reply = usage_check.get("message") or "تم إيقاف الاستخدام مؤقتاً بسبب حالة الاشتراك."

                print(
                    f"USAGE BLOCKED ❌ session_id={session_id} reason={usage_check.get('reason')}",
                    flush=True
                )

                save_message(session_id, "bot", blocked_reply)

                return jsonify({
                    "reply": blocked_reply,
                    "session_id": session_id,
                    "source_partner_id": source_partner_id,
                    "usage": {
                        "allowed": False,
                        "reason": usage_check.get("reason"),
                    }
                })

        else:
            print("NO SUBSCRIPTION FOUND ✅ treating as ALSAAB main sales bot / new visitor", flush=True)

        try:
            reply = think(
                brain_message,
                session_id,
                source_partner_id=source_partner_id
            )
        except TypeError as type_error:
            if "source_partner_id" in str(type_error) or "unexpected keyword argument" in str(type_error):
                print("THINK FALLBACK ⚠️ brain.py does not accept source_partner_id yet", flush=True)
                reply = think(brain_message, session_id)
            else:
                raise

        print(f"MAIN THINK REPLY ✅ {reply}", flush=True)

        reply = alsaab_guard_auto_payment_links(reply, payment_decision_message)
        print(f"MAIN THINK REPLY AFTER PAYMENT GUARD ✅ {reply}", flush=True)

        reply = alsaab_chat_strip_unwanted_payment_links_v5(reply, payment_decision_message)

        save_message(session_id, "bot", reply)
        print("MAIN BOT MESSAGE SAVED ✅", flush=True)

        if subscription:
            record_bot_reply_usage(usage_session_id)
            print("BOT REPLY USAGE RECORDED ✅", flush=True)

        return jsonify({
            "reply": alsaab_chat_strip_unwanted_payment_links_v5(reply, payment_decision_message),
            "session_id": session_id,
            "source_partner_id": source_partner_id
        })

    except Exception as error:
        print(f"MAIN CHAT ERROR ❌ {error}", flush=True)

        return jsonify({
            "reply": "صار خطأ تقني مؤقت. جرب مرة ثانية.",
            "session_id": session_id,
            "source_partner_id": source_partner_id,
            "error": str(error)
        }), 500


@app.route("/admin/activate-subscription", methods=["GET", "POST"])
def activate_subscription():
    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    if request.method == "GET":
        return admin_get_preview(
            action_name="activate-subscription",
            required_fields=[
                "key",
                "session_id",
                "plan",
                "source_partner_id optional",
                "package_amount optional"
            ],
            example_body={
                "key": ADMIN_KEY,
                "session_id": "commission-test-001",
                "plan": "growth",
                "source_partner_id": "ALS-P00001",
                "package_amount": "599 AED",
                "notes": "manual_post_activation"
            }
        )

    session_id = get_payload_value(payload, "session_id")
    plan = get_payload_value(payload, "plan", default="growth")
    client_id = get_payload_value(payload, "client_id")
    bot_id = get_payload_value(payload, "bot_id")
    status = get_payload_value(payload, "status", default="active")
    limit = get_payload_value(payload, "limit")
    package_amount = get_payload_value(payload, "package_amount")
    notes = get_payload_value(payload, "notes")

    source_partner_id = normalize_source_partner_id(
        get_payload_value(payload, "source_partner_id")
        or get_payload_value(payload, "ref")
        or get_payload_value(payload, "partner_id")
    )

    if not session_id:
        return jsonify({
            "status": "error",
            "message": "session_id is required"
        }), 400

    custom_reply_limit = None

    if limit:
        try:
            custom_reply_limit = int(limit)
        except Exception:
            return jsonify({
                "status": "error",
                "message": "limit must be a number"
            }), 400

    if not client_id:
        client_id = session_id

    if not source_partner_id:
        try:
            source_partner_id = get_source_partner_id_for_session(session_id)
        except Exception as error:
            print(f"ADMIN SOURCE PARTNER LOOKUP ERROR ❌ {error}", flush=True)
            source_partner_id = ""

    subscription = create_or_update_subscription(
        session_id=session_id,
        plan_name=plan,
        client_id=client_id,
        bot_id=bot_id,
        status=status,
        custom_reply_limit=custom_reply_limit,
        package_amount=package_amount,
        notes=notes,
        reset_usage=True,
        source_partner_id=source_partner_id
    )

    if str(status or "").lower().strip() in ["active", "paid"]:
        try:
            auto_partner_result = ensure_paid_client_is_partner(
                session_id=session_id,
                client_id=client_id,
                source_partner_id=source_partner_id,
                partner_name="",
                phone="",
                email="",
                country="",
                notes=f"auto_partner_from_admin_activate_subscription; {notes}",
                stripe_subscription_id="",
                plan_name=plan,
                package_amount=package_amount
            )

            print(f"ADMIN AUTO PARTNER RESULT {auto_partner_result}", flush=True)

        except Exception as error:
            print(f"ADMIN AUTO PARTNER ERROR {error}", flush=True)

    return jsonify({
        "status": "success",
        "message": "Subscription activated successfully",
        "subscription": subscription
    })


@app.route("/admin/usage-summary", methods=["GET"])
def usage_summary():
    key = request.args.get("key")

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    session_id = request.args.get("session_id", "").strip()

    if not session_id:
        return jsonify({
            "status": "error",
            "message": "session_id is required"
        }), 400

    summary = get_usage_summary(session_id)

    return jsonify({
        "status": "success",
        "usage": summary
    })


@app.route("/admin/create-partner", methods=["GET", "POST"])
def create_partner():
    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    if request.method == "GET":
        return admin_get_preview(
            action_name="create-partner",
            required_fields=[
                "key",
                "partner_name",
                "phone",
                "invited_by",
                "level"
            ],
            example_body={
                "key": ADMIN_KEY,
                "partner_name": "MLM Level 1 Test",
                "phone": "+971500000001",
                "email": "test@alsaab.ai",
                "country": "UAE",
                "invited_by": "alsaab",
                "level": "Level 1",
                "status": "active",
                "notes": "created_by_post_only"
            }
        )

    partner_name = (
        get_payload_value(payload, "partner_name")
        or get_payload_value(payload, "name")
    )

    phone = (
        get_payload_value(payload, "phone")
        or get_payload_value(payload, "whatsapp")
    )

    email = get_payload_value(payload, "email")
    country = get_payload_value(payload, "country")
    invited_by = (
        get_payload_value(payload, "invited_by")
        or get_payload_value(payload, "invitedBy")
        or get_payload_value(payload, "sponsor_partner_id")
        or get_payload_value(payload, "sponsor_id")
        or get_payload_value(payload, "parent_partner_id")
        or get_payload_value(payload, "ref")
        or get_payload_value(payload, "source_partner_id")
    )
    notes = get_payload_value(payload, "notes")
    level = get_payload_value(payload, "level", default="Level 1")
    status = get_payload_value(payload, "status", default="active")
    client_id = get_payload_value(payload, "client_id")

    if not partner_name:
        return jsonify({
            "status": "error",
            "message": "partner name is required"
        }), 400

    if not phone:
        return jsonify({
            "status": "error",
            "message": "phone is required"
        }), 400

    if not invited_by:
        return jsonify({
            "status": "error",
            "message": "invited_by / sponsor_partner_id is required"
        }), 400

    try:
        result = send_partner_to_google_sheet(
            partner_name=partner_name,
            phone=phone,
            email=email,
            country=country,
            invited_by=invited_by,
            notes=notes,
            level=level,
            status=status,
            client_id=client_id,
            sponsor_partner_id=invited_by,
            parent_partner_id=invited_by,
            partner_rank=level
        )
    except TypeError:
        result = send_partner_to_google_sheet(
            partner_name=partner_name,
            phone=phone,
            email=email,
            country=country,
            invited_by=invited_by,
            notes=notes,
            level=level,
            status=status
        )

    if result.get("status") == "success":
        return jsonify({
            "status": "success",
            "message": result.get("message", "Partner saved"),
            "partner_id": result.get("partner_id", ""),
            "referral_link": result.get("referral_link", ""),
            "sponsor_partner_id": result.get("sponsor_partner_id", invited_by),
            "parent_partner_id": result.get("parent_partner_id", invited_by),
            "invited_by": result.get("invited_by", invited_by),
            "result": result
        })

    return jsonify({
        "status": "error",
        "message": result.get("message", "Partner save failed"),
        "result": result
    }), 500


@app.route("/leads", methods=["GET"])
def leads_json():
    key = request.args.get("key")

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    return jsonify(get_leads())


@app.route("/leads-view", methods=["GET"])
def leads_view():
    key = request.args.get("key")

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    leads = get_leads()
    return render_template("leads.html", leads=leads)


# ===== ALSAAB_PARTNER_DASHBOARD_RENDER_API_V1 START =====

@app.route("/partner-dashboard-data", methods=["GET", "POST"])
def partner_dashboard_data():
    """
    Partner Dashboard Data API MVP.

    Temporary security:
    - Requires ADMIN_KEY for testing.
    - Later this must use logged-in user session and resolve partner_id internally.

    Returns:
    - partner profile
    - level progress
    - direct customers
    - commissions
    - courses
    - tree data
    """
    import os

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.args.get("partner_id", "").strip()
    )

    partner_id = str(partner_id or "").strip()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing in environment"
            }), 500

        sheet_payload = {
            "token": google_sheet_token,
            "action": "partner_dashboard_data",
            "partner_id": partner_id
        }

        result = post_to_google_sheet_json(
            sheet_payload,
            label="partner_dashboard_data"
        )

        if not isinstance(result, dict):
            return jsonify({
                "status": "error",
                "message": "Invalid partner dashboard response",
                "raw_result": str(result)
            }), 500

        return jsonify(result)

    except Exception as error:
        print(
            f"PARTNER DASHBOARD DATA ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        return jsonify({
            "status": "error",
            "message": str(error),
            "partner_id": partner_id
        }), 500

# ===== ALSAAB_PARTNER_DASHBOARD_RENDER_API_V1 END =====


# ===== ALSAAB_PARTNER_DASHBOARD_UI_MVP_V1 START =====

@app.route("/partner-dashboard", methods=["GET"])
def partner_dashboard_view():
    """
    Partner Dashboard MVP page.

    Temporary security:
    - Requires ADMIN_KEY for testing.
    - Later this will use logged-in WordPress/user session.
    """
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()
    sso_token = request.args.get("sso", "").strip() or request.args.get("token", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("partner", "", request.args.get("lang", "ar"))), 302

    partner_id = (
        request.args.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        print(f"DASHBOARD ACCESS DENIED partner partner_id={partner_id}", flush=True)
        return redirect(build_dashboard_login_redirect(
            "partner", partner_id, request.values.get("lang", "ar")
        )), 302

    if not partner_id:
        return "partner_id is required", 400

    lang = request.args.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    is_ar = lang == "ar"
    direction = "rtl" if is_ar else "ltr"
    text_align = "right" if is_ar else "left"

    try:
        from config import WEBSITE_URL
    except Exception:
        WEBSITE_URL = "https://alsaab.io"

    t = {
        "ar": {
            "page_title": "ALSAAB AI - لوحة الشريك",
            "dashboard_title": "Partner Dashboard",
            "intro": "لوحة الشريك الرسمية في ALSAAB AI. هنا تشوف رابطك، مستواك، عملاءك، عمولاتك، ومتطلبات الترقية.",
            "back_site": "العودة إلى موقع ALSAAB AI",
            "language": "English",
            "partner_id": "Partner ID",
            "current_level": "المستوى الحالي",
            "next": "التالي",
            "active_direct_customers": "العملاء المباشرين النشطين",
            "all_direct": "إجمالي المباشرين",
            "pending_commissions": "العمولات المعلقة",
            "commission_count": "عددها",
            "partner_info": "بيانات الشريك",
            "name": "الاسم",
            "status": "الحالة",
            "sponsor": "Sponsor",
            "referral_link": "Referral Link",
            "level_progress": "المستوى والترقية",
            "completed_sales": "المبيعات المكتملة",
            "required_sales": "المبيعات المطلوبة",
            "current_package": "الباقة الحالية",
            "subscription_status": "حالة الاشتراك",
            "commission_eligible": "مؤهل للعمولة",
            "required_course": "الكورس المطلوب",
            "missing_requirements": "المتطلبات الناقصة",
            "network": "الشبكة",
            "direct": "المباشرين",
            "level_2": "المستوى الثاني",
            "level_3": "المستوى الثالث",
            "total_network": "إجمالي الشبكة",
            "commission_summary": "ملخص العمولات",
            "recent_commissions": "آخر العمولات",
            "date": "التاريخ",
            "depth": "العمق",
            "package": "الباقة",
            "percent": "النسبة",
            "amount": "المبلغ",
            "direct_customers": "العملاء المباشرين",
            "client_id": "Client ID",
            "courses": "الكورسات والمتطلبات",
            "course": "الكورس",
            "code": "الكود",
            "paid_at": "تاريخ الدفع",
            "no_commissions": "لا توجد عمولات حتى الآن.",
            "no_customers": "لا يوجد عملاء مباشرين حتى الآن.",
            "no_courses": "لا توجد كورسات مسجلة حتى الآن.",
            "mvp_note_title": "ملاحظة",
            "mvp_note": "هذه نسخة MVP تجريبية من Partner Dashboard. لاحقاً سيتم ربطها بتسجيل الدخول الرسمي، وإخفاء مفتاح الإدارة، وتحسين التصميم والصلاحيات.",
            "logo_note": "سيتم استبدال هذا المكان بشعار الشركة الرسمي لاحقاً."
        },
        "en": {
            "page_title": "ALSAAB AI - Partner Dashboard",
            "dashboard_title": "Partner Dashboard",
            "intro": "The official ALSAAB AI partner dashboard. View your referral link, level, customers, commissions, and upgrade requirements.",
            "back_site": "Back to ALSAAB AI Website",
            "language": "العربية",
            "partner_id": "Partner ID",
            "current_level": "Current Level",
            "next": "Next",
            "active_direct_customers": "Active Direct Customers",
            "all_direct": "All Direct Customers",
            "pending_commissions": "Pending Commissions",
            "commission_count": "Count",
            "partner_info": "Partner Information",
            "name": "Name",
            "status": "Status",
            "sponsor": "Sponsor",
            "referral_link": "Referral Link",
            "level_progress": "Level & Progress",
            "completed_sales": "Completed Sales",
            "required_sales": "Required Sales",
            "current_package": "Current Package",
            "subscription_status": "Subscription Status",
            "commission_eligible": "Commission Eligible",
            "required_course": "Required Course",
            "missing_requirements": "Missing Requirements",
            "network": "Network",
            "direct": "Direct",
            "level_2": "Level 2",
            "level_3": "Level 3",
            "total_network": "Total Network",
            "commission_summary": "Commission Summary",
            "recent_commissions": "Recent Commissions",
            "date": "Date",
            "depth": "Depth",
            "package": "Package",
            "percent": "Percent",
            "amount": "Amount",
            "direct_customers": "Direct Customers",
            "client_id": "Client ID",
            "courses": "Courses & Requirements",
            "course": "Course",
            "code": "Code",
            "paid_at": "Paid At",
            "no_commissions": "No commissions yet.",
            "no_customers": "No direct customers yet.",
            "no_courses": "No courses recorded yet.",
            "mvp_note_title": "Note",
            "mvp_note": "This is an MVP version of the Partner Dashboard. Later it will be connected to the official login system, admin key will be removed, and permissions/design will be improved.",
            "logo_note": "This area will be replaced with the official company logo later."
        }
    }[lang]

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN is missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "partner_dashboard_data",
                "partner_id": partner_id
            },
            label="partner_dashboard_page"
        )

        if not isinstance(result, dict) or result.get("status") != "success":

            return render_template(
                "partner_dashboard_error_data.html",
                result=result
            ), 500

        profile = result.get("partner_profile") or {}
        level = result.get("level") or {}
        customers = result.get("customers") or {}
        commissions = result.get("commissions") or {}
        courses = result.get("courses") or {}
        tree = result.get("tree") or {}

        totals = commissions.get("totals") or {}
        counts = commissions.get("counts") or {}
        recent_commissions = commissions.get("recent") or []
        recent_customers = customers.get("recent") or []
        purchased_courses = courses.get("purchased_courses") or []
        depth_counts = tree.get("depth_counts") or {}

        ar_url = build_dashboard_nav_url("/partner-dashboard", partner_id, "ar", key)
        en_url = build_dashboard_nav_url("/partner-dashboard", partner_id, "en", key)

        language_url = en_url if is_ar else ar_url
        partner_dashboard_url = build_dashboard_nav_url("/partner-dashboard", partner_id, lang, key)
        client_dashboard_url = build_dashboard_nav_url("/client-dashboard", partner_id, lang, key)
        owner_advisory_url = build_dashboard_nav_url("/owner-advisory", partner_id, lang, key)

        # ALSAAB_FIX_PARTNER_LEVEL_ALIAS_V1
        search_profile = profile
        search_level = level
        search_customers = customers
        search_commissions = commissions
        search_courses = courses

        # ===== ALSAAB_PARTNER_RANK_UI_V2 START =====
        is_ar = True

        def _rank_level_number(value):
            import re
            match = re.search(r"(\d+)", str(value or "Level 1"))
            try:
                return max(1, min(5, int(match.group(1)))) if match else 1
            except Exception:
                return 1

        def _safe_int(value, default=0):
            try:
                return int(float(value or default))
            except Exception:
                return default

        current_level_num = _rank_level_number(search_level.get("current_level") or search_level.get("partner_rank"))
        completed_sales_count = _safe_int(search_level.get("completed_sales") or search_customers.get("active_direct_paid_count") or 0)

        rank_meta = {
            1: {"rank": "Entry Partner", "color": "#B8860B", "glow": "rgba(184,134,11,.28)"},
            2: {"rank": "Starter Partner", "color": "#C0C0C0", "glow": "rgba(192,192,192,.25)"},
            3: {"rank": "Growth Partner", "color": "#D7B85A", "glow": "rgba(215,184,90,.32)"},
            4: {"rank": "Elite Partner", "color": "#F0D98A", "glow": "rgba(240,217,138,.38)"},
            5: {"rank": "Diamond Partner", "color": "#FFFFFF", "glow": "rgba(255,215,0,.42)"},
        }

        next_level_num = current_level_num + 1 if current_level_num < 5 else 5

        next_requirements = {
            2: {
                "sales": 2,
                "course": "-",
                "course_token": "",
                "text_ar": "باقة Starter أو أعلى + 2 عملاء نشطين",
                "text_en": "Starter package or higher + 2 active customers",
            },
            3: {
                "sales": 5,
                "course": "كورس المسوق المحترف 69$",
                "course_token": "69",
                "text_ar": "كورس المسوق المحترف 69$ + 5 عملاء نشطين",
                "text_en": "Professional Marketer Course $69 + 5 active customers",
            },
            4: {
                "sales": 10,
                "course": "كورس مهارات المبيعات 99$",
                "course_token": "89",
                "text_ar": "كورس مهارات المبيعات 89$ + 10 عملاء نشطين",
                "text_en": "Sales Skills Course $89 + 10 active customers",
            },
            5: {
                "sales": 20,
                "course": "كورس رحلة التغيير 299$",
                "course_token": "149",
                "text_ar": "كورس رحلة التغيير 149$ + 20 عميل نشط",
                "text_en": "Change Journey Course $149 + 20 active customers",
            },
        }

        requirement = next_requirements.get(next_level_num, {})
        required_sales_count = _safe_int(requirement.get("sales"), 0)

        purchased_courses_text = str(purchased_courses or "").lower()
        course_token = str(requirement.get("course_token") or "").lower()
        course_done = True if not course_token else course_token in purchased_courses_text

        package_value = str(search_level.get("current_package") or "").lower()
        package_ok = True
        if next_level_num == 2:
            package_ok = package_value in ("starter", "growth", "elite", "diamond")

        missing_items = []

        if next_level_num == 2 and not package_ok:
            missing_items.append("الترقية إلى باقة Starter أو أعلى" if is_ar else "Upgrade to Starter package or higher")

        if required_sales_count and completed_sales_count < required_sales_count:
            missing_items.append(
                f"تحتاج {required_sales_count - completed_sales_count} عملاء نشطين إضافيين"
                if is_ar
                else f"Need {required_sales_count - completed_sales_count} more active customers"
            )

        if not course_done:
            missing_items.append(requirement.get("course") or "-")

        if current_level_num >= 5:
            missing_text = "أنت في أعلى مستوى حالياً" if is_ar else "You are currently at the highest level"
            requirement_text = "لا توجد متطلبات ترقية حالياً" if is_ar else "No upgrade requirements at this level"
            next_label = "أعلى مستوى" if is_ar else "Highest Level"
        else:
            missing_text = "مكتمل" if not missing_items else " / ".join(missing_items)
            requirement_text = requirement.get("text_ar" if is_ar else "text_en") or "-"
            next_label = f"Level {next_level_num}"

        rank_ui = {
            "level_num": current_level_num,
            "level_label": f"Level {current_level_num}",
            "rank_name": rank_meta.get(current_level_num, rank_meta[1]).get("rank"),
            "color": rank_meta.get(current_level_num, rank_meta[1]).get("color"),
            "glow": rank_meta.get(current_level_num, rank_meta[1]).get("glow"),
            "next_label": next_label,
            "completed_sales": completed_sales_count,
            "required_sales": required_sales_count if current_level_num < 5 else "-",
            "current_package": search_level.get("current_package") or "-",
            "subscription_status": search_level.get("subscription_status") or "-",
            "commission_eligible": search_level.get("commission_eligible") or "-",
            "required_course": requirement.get("course") or "-",
            "requirement_text": requirement_text,
            "missing_text": missing_text,
        }
        # ===== ALSAAB_PARTNER_RANK_UI_V2 END =====
        def money(value):
            try:
                return f"{float(value or 0):,.2f} AED"
            except Exception:
                return f"{value or 0} AED"


        return render_template(
            "partner_dashboard.html",
            lang=lang,
            direction=direction,
            text_align=text_align,
            t=t,
            website_url=WEBSITE_URL,
            language_url=language_url,
            partner_dashboard_url=partner_dashboard_url,
            client_dashboard_url=client_dashboard_url,
            owner_advisory_url=owner_advisory_url,
            data=result,
            profile=profile,
            level=level,
            customers=customers,
            commissions=commissions,
            totals=totals,
            counts=counts,
            recent_commissions=recent_commissions,
            recent_customers=recent_customers,
            purchased_courses=purchased_courses,
            tree=tree,
            depth_counts=depth_counts,
            rank_ui=rank_ui,
            money=money
        )

    except Exception as error:
        print(
            f"PARTNER DASHBOARD VIEW ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        return render_template(
            "partner_dashboard_error_render.html",
            error=str(error)
        ), 500

# ===== ALSAAB_PARTNER_DASHBOARD_UI_MVP_V1 END =====


# ===== ALSAAB_CLIENT_DASHBOARD_UI_MVP_V1 START =====

@app.route("/client-dashboard", methods=["GET"])
def client_dashboard_view():
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()
    sso_token = request.args.get("sso", "").strip() or request.args.get("token", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", request.args.get("lang", "ar"))), 302

    partner_id = (
        request.args.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        print(f"DASHBOARD ACCESS DENIED client partner_id={partner_id}", flush=True)
        return redirect(build_dashboard_login_redirect(
            "client", partner_id, request.values.get("lang", "ar")
        )), 302

    if not partner_id:
        return "partner_id is required", 400

    lang = request.args.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    is_ar = lang == "ar"
    direction = "rtl" if is_ar else "ltr"
    text_align = "right" if is_ar else "left"

    try:
        from config import WEBSITE_URL, PACKAGES
    except Exception:
        WEBSITE_URL = "https://alsaab.io"
        PACKAGES = {}

    t = {
        "ar": {
            "page_title": "ALSAAB AI - لوحة العميل",
            "back_site": "العودة إلى موقع ALSAAB AI",
            "language": "English",
            "partner_portal": "Partner Dashboard",
            "client_portal": "Client Dashboard",
            "partner_text": "الشراكة، العمولات، المستويات، العملاء، الكورسات، ومتطلبات الترقية.",
            "client_text": "مشروعك، باقتك، استخدامك، بيانات موظف المبيعات الذكي، الصور، والكتالوجات.",
            "account_id": "معرف الحساب",
            "current_package": "الباقة الحالية",
            "subscription_status": "حالة الاشتراك",
            "customer_replies": "ردود العملاء",
            "advisory_replies": "ردود الاستشارات",
            "channels": "القنوات",
            "owner_advisory": "استشارات صاحب المشروع",
            "owner_advisory_desc": "من هنا تفتح محادثة خاصة مع موظف المبيعات الذكي كمستشار لمشروعك. المحادثة مرتبطة بمعرف حسابك حتى يستمر معك في رحلة تطوير طويلة.",
            "ask_advisor": "فتح الاستشارات الخاصة",
            "project_data": "بيانات المشروع",
            "project_data_desc": "اكتب معلومات مشروعك الأساسية حتى يفهم موظف المبيعات الذكي طبيعة مشروعك.",
            "business_name": "اسم المشروع",
            "business_type": "نوع النشاط",
            "general_description": "وصف مبسط للمشروع",
            "products_notes": "ماذا تبيع أو تقدم؟",
            "save_project": "حفظ بيانات المشروع",
            "image_groups": "صور المنتجات والكتالوجات",
            "image_group_title": "اسم مجموعة المنتجات",
            "image_group_description": "وصف المجموعة وتعليمات البيع",
            "sales_instructions": "تعليمات مهمة لموظف المبيعات الذكي",
            "upload_images": "رفع الصور أو الكتالوجات",
            "save_image_group": "حفظ وإضافة مجموعة منتجات",
            "saved_image_groups": "مجموعات المنتجات المحفوظة",
            "payment_links": "روابط الدفع الخاصة",
            "product_name": "اسم المنتج",
            "payment_link": "رابط الدفع",
            "amount": "السعر",
            "currency": "العملة",
            "payment_description": "وصف المنتج أو العرض",
            "add_more_payment": "إضافة رابط دفع إضافي",
            "save_payment_links": "حفظ روابط الدفع",
            "saved_payment_links": "روابط الدفع المحفوظة",
            "saved_success": "تم الحفظ بنجاح.",
            "empty": "لا توجد بيانات محفوظة حتى الآن."
        },
        "en": {
            "page_title": "ALSAAB AI - Client Dashboard",
            "back_site": "Back to ALSAAB AI Website",
            "language": "العربية",
            "partner_portal": "Partner Dashboard",
            "client_portal": "Client Dashboard",
            "partner_text": "Partnership, commissions, levels, customers, courses, and upgrade requirements.",
            "client_text": "Your project, package, usage, Smart Sales Employee data, product images, and catalogs.",
            "account_id": "Account ID",
            "current_package": "Current Package",
            "subscription_status": "Subscription Status",
            "customer_replies": "Customer Replies",
            "advisory_replies": "Advisory Replies",
            "channels": "Channels",
            "owner_advisory": "Owner Advisory",
            "owner_advisory_desc": "Open a private advisory conversation with your Smart Sales Employee. The conversation is tied to your Account ID and continues with your long-term business journey.",
            "ask_advisor": "Open Advisory Chat",
            "project_data": "Project Data",
            "project_data_desc": "Add your core project information so the Smart Sales Employee understands your business.",
            "business_name": "Business Name",
            "business_type": "Business Type",
            "general_description": "General Description",
            "products_notes": "What do you sell or provide?",
            "save_project": "Save Project Data",
            "image_groups": "Product & Catalog Images",
            "image_group_title": "Product Group Name",
            "image_group_description": "Group Description & Sales Instructions",
            "sales_instructions": "Important instructions for the Smart Sales Employee",
            "upload_images": "Upload Images or Catalogs",
            "save_image_group": "Save & Add Product Group",
            "saved_image_groups": "Saved Product Groups",
            "payment_links": "Client Payment Links",
            "product_name": "Product Name",
            "payment_link": "Payment Link",
            "amount": "Amount",
            "currency": "Currency",
            "payment_description": "Product or Offer Description",
            "add_more_payment": "Add Another Payment Link",
            "save_payment_links": "Save Payment Links",
            "saved_payment_links": "Saved Payment Links",
            "saved_success": "Saved successfully.",
            "empty": "No saved data yet."
        }
    }[lang]

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN is missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "partner_dashboard_data",
                "partner_id": partner_id
            },
            label="client_dashboard_partner_data"
        )

        if not isinstance(result, dict) or result.get("status") != "success":
            return render_template(
                "client_dashboard_error_data.html",
                result=result
            ), 500

        client_dashboard_result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "client_dashboard_data",
                "partner_id": partner_id
            },
            label="client_dashboard_data_page"
        )

        if not isinstance(client_dashboard_result, dict):
            client_dashboard_result = {}

        profile = result.get("partner_profile") or {}
        level = result.get("level") or {}

        product_groups = client_dashboard_result.get("product_image_groups") or []
        client_payment_links = client_dashboard_result.get("client_payment_links") or []

        # ===== ALSAAB_CLIENT_DASHBOARD_HIDE_TEST_DATA_V1 START =====
        def _is_launch_test_item(value):
            text = str(value or "").lower()
            return (
                "test product" in text
                or "test catalog group" in text
                or "test drive upload group" in text
                or "example.com/pay-test" in text
                or "client dashboard mvp" in text
            )

        product_groups = [item for item in product_groups if not _is_launch_test_item(item)]
        client_payment_links = [item for item in client_payment_links if not _is_launch_test_item(item)]
        # ===== ALSAAB_CLIENT_DASHBOARD_HIDE_TEST_DATA_V1 END =====

        account_id = partner_id
        client_id = partner_id

        current_package = (level.get("current_package") or "").lower()
        subscription_status = level.get("subscription_status") or ""

        # ===== ALSAAB CANCELLATION BADGE V1 START =====
        # The status alone cannot express "active, but ending on the 26th", so
        # read the cancellation fields straight off the subscription row.
        cancel_at_period_end = False
        cancel_pending = False
        cancel_ends_on = ""
        payment_failed = False
        pay_now_url = ""
        grace_ends_on = ""
        retry_count = 0
        next_renewal_on = ""

        try:
            from database import get_client_subscription

            client_subscription = get_client_subscription(partner_id) or {}
            cancel_at_period_end = bool(client_subscription.get("cancel_at_period_end"))
            cancel_pending = bool(client_subscription.get("cancel_requested_at")) and not cancel_at_period_end
            cancel_ends_on = str(client_subscription.get("cancel_effective_at") or "")[:10]

            payment_failed = bool(client_subscription.get("payment_grace_until"))
            pay_now_url = str(client_subscription.get("last_invoice_url") or "")
            grace_ends_on = str(client_subscription.get("payment_grace_until") or "")[:10]
            retry_count = int(client_subscription.get("payment_retry_count") or 0)
            next_renewal_on = str(client_subscription.get("next_renewal_at") or "")[:10]

        except Exception as cancel_lookup_error:
            print(f"CLIENT DASHBOARD CANCEL LOOKUP ERROR ⚠️ {cancel_lookup_error}", flush=True)
        # ===== ALSAAB CANCELLATION BADGE V1 END =====

        package = PACKAGES.get(current_package) or {}

        customer_limit = (
            package.get("total_customer_reply_limit")
            or package.get("customer_reply_limit")
            or package.get("monthly_reply_limit")
            or "-"
        )

        advisory_limit = package.get("owner_advisory_reply_limit", 0)
        channels = package.get("channels") or []

        ar_url = build_dashboard_nav_url("/client-dashboard", partner_id, "ar", key)
        en_url = build_dashboard_nav_url("/client-dashboard", partner_id, "en", key)
        language_url = en_url if is_ar else ar_url

        partner_dashboard_url = build_dashboard_nav_url("/partner-dashboard", partner_id, lang, key)
        client_dashboard_url = build_dashboard_nav_url("/client-dashboard", partner_id, lang, key)
        owner_advisory_url = build_dashboard_nav_url("/owner-advisory", partner_id, lang, key)

        saved_message = request.args.get("saved", "").strip()


        return render_template(
            "client_dashboard.html",
            lang=lang,
            direction=direction,
            text_align=text_align,
            t=t,
            website_url=WEBSITE_URL,
            language_url=language_url,
            partner_dashboard_url=partner_dashboard_url,
            client_dashboard_url=client_dashboard_url,
            owner_advisory_url=owner_advisory_url,
            key=key,
            sso_token=sso_token,
            partner_id=partner_id,
            account_id=account_id,
            client_id=client_id,
            current_package=current_package,
            subscription_status=subscription_status,
            cancel_at_period_end=cancel_at_period_end,
            cancel_pending=cancel_pending,
            cancel_ends_on=cancel_ends_on,
            payment_failed=payment_failed,
            pay_now_url=pay_now_url,
            grace_ends_on=grace_ends_on,
            retry_count=retry_count,
            next_renewal_on=next_renewal_on,
            customer_limit=customer_limit,
            advisory_limit=advisory_limit,
            channels=channels,
            product_groups=product_groups,
            client_payment_links=client_payment_links,
            saved_message=saved_message
        )

    except Exception as error:
        print(
            f"CLIENT DASHBOARD VIEW ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )


        return render_template(
            "client_dashboard_error_render.html",
            error=str(error)
        ), 500

# ===== ALSAAB_CLIENT_DASHBOARD_UI_MVP_V1 END =====


# ===== ALSAAB_CLIENT_DASHBOARD_SAVE_ROUTES_V1 START =====

@app.route("/client-dashboard/save-image-group", methods=["POST"])
def client_dashboard_save_image_group():
    import os
    import base64
    from urllib.parse import quote

    key = request.form.get("key", "").strip()
    sso_token = request.form.get("sso", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", request.form.get("lang", "ar"))), 302

    partner_id = (
        request.form.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        print(f"DASHBOARD ACCESS DENIED client form partner_id={partner_id}", flush=True)
        return redirect(build_dashboard_login_redirect(
            "client", partner_id, request.values.get("lang", "ar")
        )), 302
    client_id = request.form.get("client_id", "").strip() or partner_id
    lang = request.form.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    uploaded_files = []

    try:
        for file in request.files.getlist("images"):
            if not file or not file.filename:
                continue

            raw = file.read()

            if not raw:
                continue

            # MVP safety limit per file: 5 MB
            if len(raw) > 5 * 1024 * 1024:
                print(f"CLIENT DASHBOARD UPLOAD SKIPPED large file={file.filename}", flush=True)
                continue

            uploaded_files.append({
                "name": file.filename,
                "mime_type": file.content_type or "application/octet-stream",
                "content_base64": base64.b64encode(raw).decode("ascii")
            })

        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        payload = {
            "token": google_sheet_token,
            "action": "product_image_group",
            "partner_id": partner_id,
            "client_id": client_id,
            "group_title": request.form.get("group_title", "").strip(),
            "group_description": request.form.get("group_description", "").strip(),
            "sales_instructions": request.form.get("sales_instructions", "").strip(),
            "uploaded_files": uploaded_files,
            "notes": "Saved from Client Dashboard with file upload"
        }

        result = post_to_google_sheet_json(payload, label="client_dashboard_save_image_group")
        status = "image_group_saved" if isinstance(result, dict) and result.get("status") == "success" else "image_group_error"

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, status))

    except Exception as error:
        print(f"CLIENT DASHBOARD SAVE IMAGE GROUP ERROR ❌ {error}", flush=True)

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "image_group_error"))


@app.route("/client-dashboard/save-payment-link", methods=["POST"])
def client_dashboard_save_payment_link():
    import os
    from urllib.parse import quote

    key = request.form.get("key", "").strip()
    sso_token = request.form.get("sso", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", request.form.get("lang", "ar"))), 302

    partner_id = (
        request.form.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        print(f"DASHBOARD ACCESS DENIED client form partner_id={partner_id}", flush=True)
        return redirect(build_dashboard_login_redirect(
            "client", partner_id, request.values.get("lang", "ar")
        )), 302
    client_id = request.form.get("client_id", "").strip() or partner_id
    lang = request.form.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        product_names = request.form.getlist("product_name")
        payment_links = request.form.getlist("payment_link")
        amounts = request.form.getlist("amount")
        currencies = request.form.getlist("currency")
        descriptions = request.form.getlist("description")

        max_len = max(len(product_names), len(payment_links), len(amounts), len(currencies), len(descriptions), 1)
        saved_count = 0

        for index in range(max_len):
            product_name = product_names[index].strip() if index < len(product_names) else ""
            payment_link = payment_links[index].strip() if index < len(payment_links) else ""
            amount = amounts[index].strip() if index < len(amounts) else ""
            currency = currencies[index].strip() if index < len(currencies) and currencies[index].strip() else "AED"
            description = descriptions[index].strip() if index < len(descriptions) else ""

            if not product_name and not payment_link:
                continue

            payload = {
                "token": google_sheet_token,
                "action": "client_payment_link",
                "partner_id": partner_id,
                "client_id": client_id,
                "product_name": product_name,
                "payment_link": payment_link,
                "amount": amount,
                "currency": currency,
                "description": description,
                "notes": "Saved from Client Dashboard"
            }

            result = post_to_google_sheet_json(payload, label="client_dashboard_save_payment_link")

            if isinstance(result, dict) and result.get("status") == "success":
                saved_count += 1

        status = "payment_link_saved" if saved_count > 0 else "payment_link_error"

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, status))

    except Exception as error:
        print(f"CLIENT DASHBOARD SAVE PAYMENT LINK ERROR ❌ {error}", flush=True)

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "payment_link_error"))

# ===== ALSAAB_CLIENT_DASHBOARD_SAVE_ROUTES_V1 END =====


# ===== ALSAAB_CLIENT_PROJECT_DATA_AND_ADVISORY_V1 START =====

@app.route("/client-dashboard/save-project-data", methods=["POST"])
@app.route("/client-dashboard/save-project-data", methods=["POST"])
def client_dashboard_save_project_data():
    import os
    from urllib.parse import quote

    key = request.form.get("key", "").strip()
    sso_token = request.form.get("sso", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", request.form.get("lang", "ar"))), 302

    partner_id = (
        request.form.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        print(f"DASHBOARD ACCESS DENIED client form partner_id={partner_id}", flush=True)
        return redirect(build_dashboard_login_redirect(
            "client", partner_id, request.values.get("lang", "ar")
        )), 302
    client_id = request.form.get("client_id", "").strip() or partner_id
    lang = request.form.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        payload = {
            "token": google_sheet_token,
            "action": "client_profile",
            "partner_id": partner_id,
            "client_id": client_id,
            "session_id": client_id,
            "business_name": request.form.get("business_name", "").strip(),
            "business_type": request.form.get("business_type", "").strip(),
            "general_description": request.form.get("general_description", "").strip(),
            "products": request.form.get("products", "").strip(),
            "notes": "Saved from Client Dashboard project data"
        }

        result = post_to_google_sheet_json(payload, label="client_dashboard_save_project_data")
        status = "project_data_saved" if isinstance(result, dict) and result.get("status") == "success" else "project_data_error"

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, status))

    except Exception as error:
        print(f"CLIENT DASHBOARD SAVE PROJECT DATA ERROR ❌ {error}", flush=True)

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "project_data_error"))


@app.route("/owner-advisory", methods=["GET"])
@app.route("/owner-advisory", methods=["GET"])
def owner_advisory_view():
    from urllib.parse import quote

    key = request.args.get("key", "").strip()
    sso_token = request.args.get("sso", "").strip() or request.args.get("token", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("advisory", "", request.args.get("lang", "ar"))), 302

    partner_id = (
        request.args.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        print(f"DASHBOARD ACCESS DENIED advisory partner_id={partner_id}", flush=True)
        return redirect(build_dashboard_login_redirect(
            "advisory", partner_id, request.values.get("lang", "ar")
        )), 302
    lang = request.args.get("lang", "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    if not partner_id:
        return "partner_id is required", 400

    direction = "rtl" if lang == "ar" else "ltr"
    title = "استشارات صاحب المشروع" if lang == "ar" else "Owner Advisory"
    subtitle = (
        "هذه محادثة خاصة مرتبطة بمعرف حسابك. استخدمها للاستشارات في المبيعات، التسويق، تطوير العروض، وتحسين أداء مشروعك."
        if lang == "ar"
        else "This private advisory chat is tied to your Account ID. Use it for sales, marketing, offers, objections, and business improvement."
    )

    back_url = f"/client-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&lang={quote(lang)}"
    session_id = f"owner_advisory_{partner_id}"

    return render_template(
        "owner_advisory_view.html",
        lang=lang,
        direction=direction,
        title=title,
        subtitle=subtitle,
        partner_id=partner_id,
        session_id=session_id,
        back_url=back_url
    )

# ===== ALSAAB_CLIENT_PROJECT_DATA_AND_ADVISORY_V1 END =====


# ===== ALSAAB_DASHBOARD_SSO_BRIDGE_V1 START =====

def normalize_dashboard_partner_id(value):
    value = str(value or "").strip()

    if not value:
        return ""

    if value.lower() == "alsaab":
        return "alsaab"

    value = value.upper()

    if value.startswith("ALS-P"):
        return value

    return ""


def get_dashboard_sso_secret():
    return os.environ.get("DASHBOARD_SSO_SECRET", "").strip()


def dashboard_b64url_encode(raw_bytes):
    import base64
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")


def dashboard_b64url_decode(value):
    import base64

    value = str(value or "")
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def create_dashboard_sso_token(partner_id, target="client", lang="ar", ttl_seconds=900):
    import json
    import time
    import hmac
    import hashlib

    secret = get_dashboard_sso_secret()

    if not secret:
        raise ValueError("DASHBOARD_SSO_SECRET is missing")

    partner_id = normalize_dashboard_partner_id(partner_id)

    if not partner_id:
        raise ValueError("partner_id is required")

    target = str(target or "client").strip().lower()

    if target not in ("client", "partner", "advisory"):
        target = "client"

    lang = str(lang or "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    payload = {
        "partner_id": partner_id,
        "target": target,
        "lang": lang,
        "exp": int(time.time()) + int(ttl_seconds or 900)
    }

    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_part = dashboard_b64url_encode(payload_json)

    signature = hmac.new(
        secret.encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256
    ).digest()

    signature_part = dashboard_b64url_encode(signature)

    return payload_part + "." + signature_part


def verify_dashboard_sso_token(token):
    import json
    import time
    import hmac
    import hashlib

    secret = get_dashboard_sso_secret()

    if not secret:
        return None, "DASHBOARD_SSO_SECRET is missing"

    token = str(token or "").strip()

    if "." not in token:
        return None, "Invalid token format"

    payload_part, signature_part = token.split(".", 1)

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256
    ).digest()

    expected_signature_part = dashboard_b64url_encode(expected_signature)

    if not hmac.compare_digest(expected_signature_part, signature_part):
        return None, "Invalid token signature"

    try:
        payload = json.loads(dashboard_b64url_decode(payload_part).decode("utf-8"))
    except Exception:
        return None, "Invalid token payload"

    if int(payload.get("exp") or 0) < int(time.time()):
        return None, "Token expired"

    partner_id = normalize_dashboard_partner_id(payload.get("partner_id", ""))

    if not partner_id:
        return None, "Invalid partner_id"

    payload["partner_id"] = partner_id

    target = str(payload.get("target") or "client").strip().lower()

    if target not in ("client", "partner", "advisory"):
        target = "client"

    payload["target"] = target

    lang = str(payload.get("lang") or "ar").strip().lower()

    if lang not in ("ar", "en"):
        lang = "ar"

    payload["lang"] = lang

    return payload, ""


def is_dashboard_access_allowed(partner_id, key=""):
    partner_id = normalize_dashboard_partner_id(partner_id)

    # Internal admin bypass only. Do not use key in public/customer links.
    if key and key == ADMIN_KEY:
        return True

    session_partner_id = normalize_dashboard_partner_id(session.get("partner_id", ""))

    if session_partner_id and partner_id and session_partner_id == partner_id:
        return True

    return False


def build_dashboard_nav_url(path, partner_id="", lang="ar", key=""):
    from urllib.parse import urlencode

    params = {
        "lang": lang or "ar"
    }

    current_sso = ""

    try:
        current_sso = (
            request.args.get("sso", "").strip()
            or request.form.get("sso", "").strip()
            or request.args.get("token", "").strip()
        )
    except Exception:
        current_sso = ""

    if current_sso:
        params["sso"] = current_sso
    elif key:
        params["key"] = key

    if partner_id and "partner_id" not in params:
        params["partner_id"] = normalize_dashboard_partner_id(partner_id)

    return path + "?" + urlencode(params)


def build_dashboard_login_redirect(target="client", partner_id="", lang="ar"):
    from urllib.parse import urlencode

    params = {
        "target": target or "client",
        "lang": lang or "ar"
    }

    partner_id = normalize_dashboard_partner_id(partner_id)

    if partner_id:
        params["partner_id"] = partner_id

    # /account-login-placeholder was a stub that only explained that login did
    # not exist yet. /login is the real passwordless page.
    return "/login?" + urlencode(params)


@app.route("/dashboard-sso", methods=["GET"])
def dashboard_sso():
    from urllib.parse import quote

    token = request.args.get("token", "").strip()
    payload, error = verify_dashboard_sso_token(token)

    if error:
        return render_template(
            "dashboard_sso_error.html",
            error=error
        ), 401

    partner_id = payload.get("partner_id")
    target = payload.get("target") or "client"
    lang = payload.get("lang") or "ar"

    session["partner_id"] = partner_id

    encoded_token = quote(token)

    if target == "partner":
        return redirect(f"/partner-dashboard?lang={lang}&sso={encoded_token}")

    if target == "advisory":
        return redirect(f"/owner-advisory?lang={lang}&sso={encoded_token}")

    return redirect(f"/client-dashboard?lang={lang}&sso={encoded_token}")


@app.route("/admin/create-dashboard-sso-link", methods=["GET"])
def admin_create_dashboard_sso_link():
    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = normalize_dashboard_partner_id(request.args.get("partner_id", ""))
    target = request.args.get("target", "client").strip().lower()
    lang = request.args.get("lang", "ar").strip().lower()

    if target not in ("client", "partner", "advisory"):
        target = "client"

    if lang not in ("ar", "en"):
        lang = "ar"

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    try:
        token = create_dashboard_sso_token(
            partner_id=partner_id,
            target=target,
            lang=lang,
            ttl_seconds=900
        )

        # Prefer APP_BASE_URL. Behind Render's proxy request.url_root reports
        # http://, so the link handed to a partner arrived as an insecure URL
        # that only worked because of the 301. auth_routes already prefers the
        # configured base for the same reason.
        try:
            from config import APP_BASE_URL as _configured_base
        except ImportError:
            from backend.config import APP_BASE_URL as _configured_base

        base_url = (_configured_base or "").rstrip("/") or request.url_root.rstrip("/")
        url = f"{base_url}/dashboard-sso?token={token}"

        return jsonify({
            "status": "success",
            "partner_id": partner_id,
            "target": target,
            "lang": lang,
            "url": url
        })

    except Exception as error:
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500


@app.route("/account-login-placeholder", methods=["GET"])
def account_login_placeholder():
    # Superseded by /login. Kept so any link already handed out still lands
    # somewhere useful.
    return redirect("/login"), 302


def _retired_account_login_placeholder():
    return render_template(
        "account_login_placeholder.html"
    )

# ===== ALSAAB_DASHBOARD_SSO_BRIDGE_V1 END =====


# ===== ALSAAB_DASHBOARD_RETURN_URL_V1 START =====

def build_dashboard_return_url(path, key="", partner_id="", lang="ar", saved=""):
    from urllib.parse import urlencode

    params = {
        "lang": lang or "ar"
    }

    current_sso = ""

    try:
        current_sso = (
            request.form.get("sso", "").strip()
            or request.args.get("sso", "").strip()
            or request.args.get("token", "").strip()
        )
    except Exception:
        current_sso = ""

    if current_sso:
        params["sso"] = current_sso
    elif key:
        params["key"] = key

        if partner_id:
            params["partner_id"] = normalize_dashboard_partner_id(partner_id)

    if saved:
        params["saved"] = saved

    return path + "?" + urlencode(params)

# ===== ALSAAB_DASHBOARD_RETURN_URL_V1 END =====


# ===== ALSAAB_ADMIN_DASHBOARD_MVP_V1 START =====

@app.route("/admin-dashboard-data", methods=["GET"])
def admin_dashboard_data():
    """
    Admin Dashboard Data API.

    Internal MVP security:
    - Requires ADMIN_KEY.
    - Later this can be connected to WordPress admin SSO/session.
    """
    import os

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_dashboard_data"
            },
            label="admin_dashboard_data"
        )

        return jsonify(result)

    except Exception as error:
        print(f"ADMIN DASHBOARD DATA ERROR ❌ {error}", flush=True)

        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500


# ===== ALSAAB TELEGRAM BILLING NOTICE V1 START =====
def telegram_notify(text):
    """
    Push a billing event to Telegram.

    sheet_compat.handle() already notifies every data action, but the Stripe
    billing events carry detail that never reaches one -- the grace deadline,
    the retry number, the pay-now link. Those are pushed from here. Never
    raises: a telegram problem must not fail a payment webhook.
    """
    try:
        try:
            from telegram_bot import notify_text
        except ImportError:
            from backend.telegram_bot import notify_text

        notify_text(text)
    except Exception as error:
        print(f"TELEGRAM BILLING NOTICE SKIPPED {error}", flush=True)
# ===== ALSAAB TELEGRAM BILLING NOTICE V1 END =====


# ===== ALSAAB ADMIN MISSING REQUIREMENT TEXT V1 START =====
def humanize_missing_requirements(value):
    """
    partner_levels.missing_requirements stores machine tokens, e.g.
        level_2_requires_package_in_['starter', 'growth', 'elite', 'diamond']
        level_1_requires_1_active_network_customers
        subscription_not_active

    The admin search card printed completed/required sales and nothing else, so
    a partner blocked purely by their own package read as qualified -- ALS-P00003
    shows 5 sales against 2 required and is still Level 1, because Level 2 needs
    a Starter package and they are on Entry. This turns the tokens into a
    sentence the admin can act on.
    """
    if not value:
        return ""

    text = str(value).strip()

    if not text or text in ("[]", "-"):
        return ""

    tokens = re.findall(r"[a-z0-9_]+_requires_[a-z0-9_\[\]', ]+|subscription_not_active", text)

    if not tokens:
        tokens = [text]

    parts = []

    for token in tokens:
        token = token.strip()

        if token.startswith("subscription_not_active"):
            parts.append("لا يوجد اشتراك نشط")
            continue

        package_match = re.search(r"requires_package_in_\[([^\]]*)\]", token)

        if package_match:
            packages = re.findall(r"'([^']+)'", package_match.group(1))
            first = packages[0].title() if packages else ""
            parts.append(f"يحتاج ترقية باقته إلى {first} أو أعلى" if first else "يحتاج ترقية باقته")
            continue

        customers_match = re.search(r"requires_(\d+)_active_(network|direct)_customers", token)

        if customers_match:
            count = customers_match.group(1)
            scope = "في الشبكة" if customers_match.group(2) == "network" else "مباشرين"
            parts.append(f"يحتاج {count} عميل نشط {scope}")
            continue

        course_match = re.search(r"requires_course[s]?_([a-z0-9_]+)", token)

        if course_match:
            parts.append(f"يحتاج شراء الكورس المطلوب ({course_match.group(1)})")
            continue

        parts.append(token)

    return " + ".join(parts)
# ===== ALSAAB ADMIN MISSING REQUIREMENT TEXT V1 END =====


@app.route("/admin-dashboard", methods=["GET"])
def admin_dashboard_view():
    """
    Admin Dashboard MVP page.

    Internal MVP security:
    - Requires ADMIN_KEY.
    - Do not expose this link publicly.
    """
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN is missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_dashboard_data"
            },
            label="admin_dashboard_page"
        )

        if not isinstance(result, dict) or result.get("status") != "success":
            return render_template(
                "admin_dashboard_error_data.html",
                result=result
            ), 500

        partners = result.get("partners") or {}
        subscriptions = result.get("subscriptions") or {}
        commissions = result.get("commissions") or {}
        levels = result.get("levels") or {}
        courses = result.get("courses") or {}

        partner_summary = partners.get("summary") or {}
        subscription_summary = subscriptions.get("summary") or {}
        commission_totals = commissions.get("totals") or {}
        commission_counts = commissions.get("counts") or {}
        course_summary = courses.get("summary") or {}
        level_counts = levels.get("level_counts") or {}
        eligible_counts = levels.get("eligible_counts") or {}

        recent_partners = partners.get("recent") or []
        recent_subscriptions = subscriptions.get("recent") or []
        recent_commissions = commissions.get("recent") or []
        recent_levels = levels.get("recent") or []
        recent_courses = courses.get("recent") or []

        # ===== ALSAAB_ADMIN_DASHBOARD_SEARCH_V1 START =====
        search_query = (
            request.args.get("partner_id", "")
            or request.args.get("search", "")
            or request.args.get("q", "")
        ).strip()

        search_lookup = {}
        search_result = {}

        search_profile = {}
        search_level = {}
        search_missing_text = ""
        search_customers = {}
        search_commissions = {}
        search_courses = {}
        search_tree = {}

        search_recent_commissions = []
        search_recent_customers = []
        search_purchased_courses = []

        # ===== ALSAAB_ADMIN_PAYOUT_HISTORY_DISPLAY_V1 START =====
        search_payout_history = {}
        search_payout_summary = {}
        search_recent_payouts = []
        # ===== ALSAAB_ADMIN_PAYOUT_HISTORY_DISPLAY_V1 END =====

        search_commission_totals = {}
        search_commission_counts = {}

        # ===== ALSAAB_ADMIN_PARTNER_COMMISSION_SUMMARY_V1 START =====
        search_unpaid_total = 0
        search_payable_now = 0
        search_rejected_hold_total = 0
        search_paid_total = 0
        # ===== ALSAAB_ADMIN_PARTNER_COMMISSION_SUMMARY_V1 END =====

        if search_query:
            search_lookup = post_to_google_sheet_json(
                {
                    "token": google_sheet_token,
                    "action": "admin_partner_lookup",
                    "query": search_query
                },
                label="admin_partner_lookup"
            )

            found_partner_id = ""

            if isinstance(search_lookup, dict) and search_lookup.get("status") == "success":
                found_partner_id = str(search_lookup.get("partner_id") or "").strip()

            if found_partner_id:
                search_result = post_to_google_sheet_json(
                    {
                        "token": google_sheet_token,
                        "action": "partner_dashboard_data",
                        "partner_id": found_partner_id
                    },
                    label="admin_partner_detail"
                )

                if isinstance(search_result, dict) and search_result.get("status") == "success":
                    search_profile = search_result.get("partner_profile") or {}
                    search_level = search_result.get("level") or {}
                    search_missing_text = humanize_missing_requirements(
                        search_level.get("missing_requirements")
                    )
                    search_customers = search_result.get("customers") or {}
                    search_commissions = search_result.get("commissions") or {}
                    search_courses = search_result.get("courses") or {}
                    search_tree = search_result.get("tree") or {}

                    search_recent_commissions = search_commissions.get("recent") or []
                    search_recent_customers = search_customers.get("recent") or []
                    search_purchased_courses = search_courses.get("purchased_courses") or []

                    search_payout_history = post_to_google_sheet_json(
                        {
                            "token": google_sheet_token,
                            "action": "admin_partner_payout_history",
                            "partner_id": found_partner_id
                        },
                        label="admin_partner_payout_history"
                    )

                    if isinstance(search_payout_history, dict) and search_payout_history.get("status") == "success":
                        search_payout_summary = search_payout_history.get("summary") or {}
                        search_recent_payouts = search_payout_history.get("recent") or []

                    search_commission_totals = search_commissions.get("totals") or {}
                    search_commission_counts = search_commissions.get("counts") or {}

                    try:
                        search_payout_history = post_to_google_sheet_json(
                            {
                                "token": google_sheet_token,
                                "action": "admin_partner_payout_history",
                                "partner_id": found_partner_id
                            },
                            label="admin_partner_payout_history_v3"
                        )

                        if isinstance(search_payout_history, dict) and search_payout_history.get("status") == "success":
                            search_payout_summary = search_payout_history.get("summary") or {}
                            search_recent_payouts = search_payout_history.get("recent") or []
                    except Exception as payout_history_error:
                        search_payout_history = {
                            "status": "error",
                            "message": str(payout_history_error)
                        }
                        search_payout_summary = {}
                        search_recent_payouts = []

                    def _admin_float(value):
                        try:
                            return float(value or 0)
                        except Exception:
                            return 0

                    pending_amount = _admin_float(search_commission_totals.get("pending"))
                    approved_amount = _admin_float(search_commission_totals.get("approved"))
                    paid_amount = _admin_float(search_commission_totals.get("paid"))
                    rejected_amount = _admin_float(search_commission_totals.get("rejected"))
                    hold_amount = _admin_float(search_commission_totals.get("hold"))

                    # غير مدفوع = pending + approved
                    search_unpaid_total = pending_amount + approved_amount

                    # جاهز للدفع الآن = approved فقط
                    # pending يحتاج موافقة أولاً
                    search_payable_now = approved_amount

                    search_paid_total = paid_amount
                    search_rejected_hold_total = rejected_amount + hold_amount
        # ===== ALSAAB_ADMIN_DASHBOARD_SEARCH_V1 END =====

                rank_ui = {}
        # Admin Dashboard: partner rank UI block removed from admin scope safely.

        def money(value):
            try:
                return f"{float(value or 0):,.2f} AED"
            except Exception:
                return f"{value or 0} AED"

        action_status = request.args.get("admin_action", "").strip()

        admin_action_message = ""

        if action_status == "recalculated":
            admin_action_message = "تمت إعادة حساب مستوى الشريك وتسجيل العملية في AuditLogs."
        elif action_status == "recalculate_error":
            admin_action_message = "حدث خطأ أثناء إعادة حساب مستوى الشريك."

        encoded_key = quote(key)


        return render_template(
            "admin_dashboard.html",
            encoded_key=encoded_key,
            admin_key=key,
            admin_action_message=admin_action_message,
            search_query=search_query,
            search_lookup=search_lookup,
            search_result=search_result,
            search_profile=search_profile,
            search_level=search_level,
            search_missing_text=search_missing_text,
            search_customers=search_customers,
            search_commissions=search_commissions,
            search_courses=search_courses,
            search_tree=search_tree,
            search_recent_commissions=search_recent_commissions,
            search_recent_customers=search_recent_customers,
            search_purchased_courses=search_purchased_courses,
            search_payout_history=search_payout_history,
            search_payout_summary=search_payout_summary,
            search_recent_payouts=search_recent_payouts,
            search_commission_totals=search_commission_totals,
            search_commission_counts=search_commission_counts,
            search_unpaid_total=search_unpaid_total,
            search_payable_now=search_payable_now,
            search_rejected_hold_total=search_rejected_hold_total,
            search_paid_total=search_paid_total,
            partner_summary=partner_summary,
            subscription_summary=subscription_summary,
            commission_totals=commission_totals,
            commission_counts=commission_counts,
            course_summary=course_summary,
            level_counts=level_counts,
            eligible_counts=eligible_counts,
            partners=partners,
            subscriptions=subscriptions,
            recent_partners=recent_partners,
            recent_subscriptions=recent_subscriptions,
            recent_commissions=recent_commissions,
            recent_levels=recent_levels,
            recent_courses=recent_courses,
            money=money
        )

    except Exception as error:
        print(f"ADMIN DASHBOARD VIEW ERROR ❌ {error}", flush=True)

        return render_template(
            "admin_dashboard_error_render.html",
            error=str(error)
        ), 500

# ===== ALSAAB_ADMIN_DASHBOARD_MVP_V1 END =====


# ===== ALSAAB_ADMIN_RECALCULATE_LEVEL_V1 START =====

# ===== ALSAAB TELEGRAM WEBHOOK V1 START =====
@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    """
    Telegram delivers every message the bot receives here.

    Always answers 200. Telegram retries a non-2xx and then backs the webhook
    off entirely, so an error inside one message must not look like a transport
    failure -- the failure is reported into the chat instead.
    """
    try:
        update = request.get_json(force=True, silent=True) or {}
    except Exception:
        update = {}

    try:
        try:
            from telegram_bot import handle_update
        except ImportError:
            from backend.telegram_bot import handle_update

        result = handle_update(update)

    except Exception as error:
        print(f"TELEGRAM WEBHOOK ERROR {type(error).__name__}: {error}", flush=True)
        result = {"status": "error", "message": str(error)[:200]}

    return jsonify(result), 200


@app.route("/telegram-setup", methods=["POST", "GET"])
def telegram_setup():
    """Register the webhook with Telegram, and report what it thinks is set."""
    key = request.args.get("key", "").strip() or (request.form.get("key", "") or "").strip()

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        try:
            from telegram_bot import get_webhook_info, self_test, set_webhook
        except ImportError:
            from backend.telegram_bot import get_webhook_info, self_test, set_webhook

        base_url = (
            request.args.get("base_url", "").strip()
            or os.getenv("APP_BASE_URL", "").strip()
            or request.url_root.rstrip("/")
        )

        registered = set_webhook(base_url) if request.method == "POST" else None

        return jsonify({
            "status": "success",
            "bot": self_test(),
            "registered": registered,
            "webhook_info": get_webhook_info(),
        })

    except Exception as error:
        return jsonify({"status": "error", "message": str(error)[:300]}), 500
# ===== ALSAAB TELEGRAM WEBHOOK V1 END =====


@app.route("/admin/recalculate-all-levels", methods=["POST"])
def admin_recalculate_all_levels_route():
    """
    Rebuild every partner's level from the live data.

    Levels are otherwise only refreshed when a payment arrives, so anything
    else that changes the inputs — a cancellation, an upgrade, a change to the
    level rules — leaves the stored value stale while the payout engine keeps
    computing the real one. This is the manual resync for that gap.
    """
    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        from database import post_to_google_sheet_json

        result = post_to_google_sheet_json(
            {
                "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                "action": "admin_recalculate_all_levels",
                "actor": "owner_admin",
                "source": "admin_dashboard",
                "reason": get_payload_value(payload, "reason", default="manual resync"),
            },
            label="admin_recalculate_all_levels",
        )

        return jsonify(result)

    except Exception as error:
        print(f"RECALCULATE ALL LEVELS ERROR ❌ {error}", flush=True)
        return jsonify({"status": "error", "message": str(error)}), 500


@app.route("/admin/recalculate-partner-level", methods=["POST"])
def admin_recalculate_partner_level():
    """
    Owner/Admin action:
    Recalculate partner level and sync result to Google Sheets.

    Security:
    - Requires ADMIN_KEY.
    - This is an owner-level admin action.
    - Every action is logged in AuditLogs.
    """
    import os
    import json
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Manual admin recalculate from Admin Dashboard"
    )

    partner_id = str(partner_id or "").strip().upper()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    try:
        from database import (
            normalize_partner_id,
            sync_partner_level_progress_to_google_sheet,
            post_to_google_sheet_json,
        )

        partner_id = normalize_partner_id(partner_id)

        result = sync_partner_level_progress_to_google_sheet(partner_id)

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        audit_result = {}

        if google_sheet_token:
            audit_result = post_to_google_sheet_json(
                {
                    "token": google_sheet_token,
                    "action": "admin_audit_log",
                    "actor": "owner_admin",
                    "action_type": "recalculate_partner_level",
                    "target_type": "partner",
                    "target_id": partner_id,
                    "partner_id": partner_id,
                    "before_json": "",
                    "after_json": json.dumps(result, ensure_ascii=False),
                    "reason": reason,
                    "source": "admin_dashboard",
                    "status": result.get("status", "success") if isinstance(result, dict) else "success",
                    "notes": "Admin manual level recalculation"
                },
                label="admin_audit_log_recalculate_level"
            )

        print(
            f"ADMIN RECALCULATE LEVEL ✅ partner_id={partner_id} result={result} audit={audit_result}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "success",
                "partner_id": partner_id,
                "result": result,
                "audit_result": audit_result
            })

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=recalculated"
        )

    except Exception as error:
        print(
            f"ADMIN RECALCULATE LEVEL ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "partner_id": partner_id,
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=recalculate_error"
        )

# ===== ALSAAB_ADMIN_RECALCULATE_LEVEL_V1 END =====


# ===== ALSAAB_ADMIN_COMMISSION_ACTIONS_RENDER_V1 START =====

@app.route("/admin/update-commission-status", methods=["POST"])
def admin_update_commission_status():
    """
    Owner/Admin action:
    Update commission status: approved / hold / rejected / paid.

    Security:
    - Requires ADMIN_KEY.
    - Every change is logged in Apps Script AuditLogs.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    commission_id = (
        get_payload_value(payload, "commission_id", default="")
        or request.form.get("commission_id", "").strip()
    )

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    new_status = (
        get_payload_value(payload, "new_status", default="")
        or request.form.get("new_status", "").strip()
    ).lower().strip()

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Admin commission status update"
    )

    if new_status not in ("approved", "hold", "rejected", "paid", "pending"):
        return jsonify({
            "status": "error",
            "message": "Invalid new_status"
        }), 400

    if not commission_id:
        return jsonify({
            "status": "error",
            "message": "commission_id is required"
        }), 400

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_update_commission_status",
                "commission_id": commission_id,
                "partner_id": partner_id,
                "new_status": new_status,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard"
            },
            label="admin_update_commission_status"
        )

        print(
            f"ADMIN UPDATE COMMISSION STATUS ✅ commission_id={commission_id} new_status={new_status} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=commission_{quote(new_status)}"
        )

    except Exception as error:
        print(
            f"ADMIN UPDATE COMMISSION STATUS ERROR ❌ commission_id={commission_id} status={new_status} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=commission_error"
        )

# ===== ALSAAB_ADMIN_COMMISSION_ACTIONS_RENDER_V1 END =====


# ===== ALSAAB_ADMIN_BULK_COMMISSION_ACTIONS_RENDER_V1 START =====

@app.route("/admin/bulk-update-commission-status", methods=["POST"])
def admin_bulk_update_commission_status():
    """
    Owner/Admin action:
    Bulk update commission status.

    Safety:
    - Requires ADMIN_KEY.
    - Mark Paid is handled safely by Apps Script and skips non-approved commissions.
    - Every updated commission is logged in AuditLogs.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    new_status = (
        get_payload_value(payload, "new_status", default="")
        or request.form.get("new_status", "").strip()
    ).lower().strip()

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Bulk commission action from Admin Dashboard"
    )

    commission_ids = []

    if request.is_json:
        raw_ids = payload.get("commission_ids") or []
        if isinstance(raw_ids, list):
            commission_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
        else:
            commission_ids = [x.strip() for x in str(raw_ids).replace("\n", ",").split(",") if x.strip()]
    else:
        commission_ids = request.form.getlist("commission_ids")
        commission_ids = [str(x).strip() for x in commission_ids if str(x).strip()]

    if new_status not in ("approved", "hold", "rejected", "paid"):
        return jsonify({
            "status": "error",
            "message": "Invalid new_status"
        }), 400

    if not commission_ids:
        if request.is_json:
            return jsonify({
                "status": "error",
                "message": "No commissions selected"
            }), 400

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=bulk_no_selection"
        )

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_bulk_update_commission_status",
                "commission_ids": commission_ids,
                "partner_id": partner_id,
                "new_status": new_status,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard_bulk"
            },
            label="admin_bulk_update_commission_status"
        )

        print(
            f"ADMIN BULK UPDATE COMMISSION STATUS ✅ partner_id={partner_id} new_status={new_status} count={len(commission_ids)} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        updated_count = 0
        skipped_count = 0

        if isinstance(result, dict):
            updated_count = int(result.get("updated_count") or 0)
            skipped_count = int(result.get("skipped_count") or 0)

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=bulk_commission_{quote(new_status)}&updated={updated_count}&skipped={skipped_count}"
        )

    except Exception as error:
        print(
            f"ADMIN BULK UPDATE COMMISSION STATUS ERROR ❌ partner_id={partner_id} status={new_status} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=bulk_commission_error"
        )

# ===== ALSAAB_ADMIN_BULK_COMMISSION_ACTIONS_RENDER_V1 END =====


# ===== ALSAAB_ADMIN_PARTNER_STATUS_ACTIONS_RENDER_V2 START =====

@app.route("/admin/update-partner-status", methods=["POST"])
def admin_update_partner_status():
    """
    Owner/Admin action:
    Suspend or activate partner.

    Security:
    - Requires ADMIN_KEY.
    - Owner-level admin action.
    - Apps Script logs action in AuditLogs.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    new_status = (
        get_payload_value(payload, "new_status", default="")
        or request.form.get("new_status", "").strip()
    ).lower().strip()

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Admin partner status update"
    )

    partner_id = str(partner_id or "").strip().upper()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    if new_status not in ("active", "suspended"):
        return jsonify({
            "status": "error",
            "message": "Invalid new_status"
        }), 400

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id)

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_update_partner_status",
                "partner_id": partner_id,
                "new_status": new_status,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard"
            },
            label="admin_update_partner_status"
        )

        recalculate_result = {}

        if new_status == "active":
            try:
                from database import sync_partner_level_progress_to_google_sheet
                recalculate_result = sync_partner_level_progress_to_google_sheet(partner_id)
            except Exception as recalc_error:
                recalculate_result = {
                    "status": "error",
                    "message": str(recalc_error)
                }

        print(
            f"ADMIN UPDATE PARTNER STATUS ✅ partner_id={partner_id} new_status={new_status} result={result} recalc={recalculate_result}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "success",
                "partner_id": partner_id,
                "new_status": new_status,
                "result": result,
                "recalculate_result": recalculate_result
            })

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=partner_{quote(new_status)}"
        )

    except Exception as error:
        print(
            f"ADMIN UPDATE PARTNER STATUS ERROR ❌ partner_id={partner_id} status={new_status} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=partner_status_error"
        )

# ===== ALSAAB_ADMIN_PARTNER_STATUS_ACTIONS_RENDER_V2 END =====


# ===== ALSAAB_DOWNLINE_TRANSFER_PREVIEW_RENDER_V1 START =====

@app.route("/admin/downline-transfer-preview", methods=["GET"])
def admin_downline_transfer_preview():
    """
    Owner/Admin preview only:
    Shows what would be affected if partner direct downline is transferred to alsaab.

    No changes are made here.
    """
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    partner_id = request.args.get("partner_id", "").strip().upper()

    if not partner_id:
        return "partner_id is required", 400

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id)
        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN is missing", 500

        preview = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_downline_transfer_preview",
                "partner_id": partner_id
            },
            label="admin_downline_transfer_preview"
        )

        if not isinstance(preview, dict) or preview.get("status") != "success":
            return render_template(
                "downline_transfer_preview_error_data.html",
                preview=preview,
                encoded_key=quote(key),
                partner_id=partner_id
            ), 500

        target_partner = preview.get("target_partner") or {}
        direct_children = preview.get("direct_children") or []
        network_rows = preview.get("network_rows") or []
        depth_counts = preview.get("depth_counts") or {}


        return render_template(
            "downline_transfer_preview.html",
            encoded_key=quote(key),
            raw_admin_key=key,
            partner_id=partner_id,
            preview=preview,
            target_partner=target_partner,
            direct_children=direct_children,
            network_rows=network_rows,
            depth_counts=depth_counts
        )

    except Exception as error:
        print(f"DOWNLINE TRANSFER PREVIEW ERROR ❌ partner_id={partner_id} error={error}", flush=True)

        return render_template(
            "downline_transfer_preview_error_render.html",
            error=str(error)
        ), 500

# ===== ALSAAB_DOWNLINE_TRANSFER_PREVIEW_RENDER_V1 END =====


# ===== ALSAAB_DOWNLINE_TRANSFER_EXECUTE_RENDER_V1 START =====

@app.route("/admin/transfer-downline-to-alsaab", methods=["POST"])
def admin_transfer_downline_to_alsaab():
    """
    Owner/Admin action:
    Transfer direct downline of a partner to alsaab.

    Security:
    - Requires ADMIN_KEY.
    - Requires reason.
    - Requires confirm_text = TRANSFER_TO_ALSAAB.
    - Apps Script logs AuditLogs and rebuilds PartnerTree.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
    )

    confirm_text = (
        get_payload_value(payload, "confirm_text", default="")
        or request.form.get("confirm_text", "").strip()
    )

    partner_id = str(partner_id or "").strip().upper()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    if not reason:
        return jsonify({
            "status": "error",
            "message": "reason is required"
        }), 400

    if confirm_text != "TRANSFER_TO_ALSAAB":
        return jsonify({
            "status": "error",
            "message": "confirm_text must be TRANSFER_TO_ALSAAB"
        }), 400

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id)

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_transfer_downline_to_alsaab",
                "partner_id": partner_id,
                "reason": reason,
                "confirm_text": confirm_text,
                "actor": "owner_admin",
                "source": "admin_dashboard"
            },
            label="admin_transfer_downline_to_alsaab"
        )

        print(
            f"ADMIN TRANSFER DOWNLINE TO ALSAAB ✅ partner_id={partner_id} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        transferred_count = 0

        if isinstance(result, dict):
            transferred_count = int(result.get("transferred_count") or 0)

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=downline_transferred&transferred={transferred_count}"
        )

    except Exception as error:
        print(
            f"ADMIN TRANSFER DOWNLINE ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=downline_transfer_error"
        )

# ===== ALSAAB_DOWNLINE_TRANSFER_EXECUTE_RENDER_V1 END =====


# ===== ALSAAB_AUTO_APPROVE_PENDING_RENDER_V1 START =====

@app.route("/admin/auto-approve-pending-commissions", methods=["POST"])
def admin_auto_approve_pending_commissions():
    """
    Owner/Admin action:
    Convert old pending commissions to approved.

    This is for legacy pending data only.
    New valid commissions are auto-approved by Apps Script.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Convert old pending commissions to approved"
    )

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id) if partner_id else ""

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_auto_approve_pending_commissions",
                "partner_id": partner_id,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard"
            },
            label="admin_auto_approve_pending_commissions"
        )

        print(
            f"ADMIN AUTO APPROVE PENDING COMMISSIONS ✅ partner_id={partner_id} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        action = "auto_approved_pending"

        if isinstance(result, dict) and result.get("status") != "success":
            action = "auto_approve_pending_error"

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action={quote(action)}"
        )

    except Exception as error:
        print(
            f"ADMIN AUTO APPROVE PENDING ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=auto_approve_pending_error"
        )

# ===== ALSAAB_AUTO_APPROVE_PENDING_RENDER_V1 END =====


# ===== ALSAAB_MARK_PARTNER_PAID_BUTTON_RENDER_V1 START =====

@app.route("/admin/mark-partner-paid", methods=["POST"])
def admin_mark_partner_paid():
    """
    Owner/Admin action:
    After owner manually transfers payout to partner,
    mark all approved commissions for this partner as paid.
    """
    import os
    from urllib.parse import quote

    payload = get_admin_payload()
    key = get_admin_key(payload)

    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    partner_id = (
        get_payload_value(payload, "partner_id", default="")
        or request.form.get("partner_id", "").strip()
    )

    reason = (
        get_payload_value(payload, "reason", default="")
        or request.form.get("reason", "").strip()
        or "Owner manually transferred payout to partner"
    )

    partner_id = str(partner_id or "").strip().upper()

    if not partner_id:
        return jsonify({
            "status": "error",
            "message": "partner_id is required"
        }), 400

    try:
        from database import post_to_google_sheet_json, normalize_partner_id

        partner_id = normalize_partner_id(partner_id)

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_mark_partner_approved_commissions_paid",
                "partner_id": partner_id,
                "reason": reason,
                "actor": "owner_admin",
                "source": "admin_dashboard",
                "payment_method": "manual_transfer"
            },
            label="admin_mark_partner_paid"
        )

        print(
            f"ADMIN MARK PARTNER PAID ✅ partner_id={partner_id} result={result}",
            flush=True
        )

        if request.is_json:
            return jsonify(result)

        action = "partner_marked_paid"

        if isinstance(result, dict) and result.get("status") != "success":
            action = "partner_marked_paid_error"

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action={quote(action)}"
        )

    except Exception as error:
        print(
            f"ADMIN MARK PARTNER PAID ERROR ❌ partner_id={partner_id} error={error}",
            flush=True
        )

        if request.is_json:
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

        return redirect(
            f"/admin-dashboard?key={quote(key)}&partner_id={quote(partner_id)}&admin_action=partner_marked_paid_error"
        )

# ===== ALSAAB_MARK_PARTNER_PAID_BUTTON_RENDER_V1 END =====


# ===== ALSAAB_WHATSAPP_WEBHOOK_FOUNDATION_V1 START =====

@app.route("/whatsapp-webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    """
    WhatsApp Cloud API webhook foundation.

    GET:
    - Meta webhook verification.

    POST:
    - Receives WhatsApp messages/status events.
    - Looks up phone_number_id in ClientChannels.
    - Logs incoming messages into WhatsAppMessages.
    - Does not send AI replies yet. Sending replies is the next step.
    """
    import os
    import json
    import hmac
    import hashlib

    # Meta webhook verification.
    if request.method == "GET":
        verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()

        mode = request.args.get("hub.mode", "").strip()
        token = request.args.get("hub.verify_token", "").strip()
        challenge = request.args.get("hub.challenge", "").strip()

        if mode == "subscribe" and verify_token and token == verify_token:
            return challenge, 200

        return "Forbidden", 403

    raw_body = request.get_data() or b""

    # Optional signature verification.
    # If WHATSAPP_APP_SECRET is set, we verify X-Hub-Signature-256.
    app_secret = os.getenv("WHATSAPP_APP_SECRET", "").strip()

    if app_secret:
        received_signature = request.headers.get("X-Hub-Signature-256", "").strip()
        expected_signature = "sha256=" + hmac.new(
            app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        if not received_signature or not hmac.compare_digest(received_signature, expected_signature):
            print("WHATSAPP WEBHOOK SIGNATURE FAILED ❌", flush=True)
            return jsonify({"status": "error", "message": "Invalid signature"}), 403

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        payload = request.get_json(silent=True) or {}

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            print("WHATSAPP WEBHOOK ERROR ❌ GOOGLE_SHEET_TOKEN missing", flush=True)
            return jsonify({
                "status": "error",
                "message": "GOOGLE_SHEET_TOKEN is missing"
            }), 500

        processed = []
        status_events = []

        entries = payload.get("entry", []) if isinstance(payload, dict) else []

        for entry in entries:
            changes = entry.get("changes", []) if isinstance(entry, dict) else []

            for change in changes:
                value = change.get("value", {}) if isinstance(change, dict) else {}

                metadata = value.get("metadata", {}) if isinstance(value, dict) else {}
                phone_number_id = str(metadata.get("phone_number_id", "") or "").strip()
                display_phone_number = str(metadata.get("display_phone_number", "") or "").strip()

                # Lookup channel mapping from ClientChannels.
                lookup = {}

                if phone_number_id:
                    lookup = post_to_google_sheet_json(
                        {
                            "token": google_sheet_token,
                            "action": "whatsapp_channel_lookup",
                            "phone_number_id": phone_number_id
                        },
                        label="whatsapp_channel_lookup"
                    )

                found_channel = isinstance(lookup, dict) and lookup.get("found") is True

                client_id = ""
                partner_id = ""
                business_name = ""

                if found_channel:
                    client_id = str(lookup.get("client_id", "") or "").strip()
                    partner_id = str(lookup.get("partner_id", "") or "").strip()
                    business_name = str(lookup.get("business_name", "") or "").strip()
                else:
                    # Safe fallback for company pilot until ClientChannels is mapped.
                    client_id = os.getenv("WHATSAPP_DEFAULT_CLIENT_ID", "alsaab").strip()
                    partner_id = os.getenv("WHATSAPP_DEFAULT_PARTNER_ID", "alsaab").strip()
                    business_name = "ALSAAB AI"

                contacts = value.get("contacts", []) if isinstance(value, dict) else []
                contact_names = {}

                for contact in contacts:
                    wa_id = str(contact.get("wa_id", "") or "").strip()
                    profile = contact.get("profile", {}) or {}
                    contact_names[wa_id] = str(profile.get("name", "") or "").strip()

                messages = value.get("messages", []) if isinstance(value, dict) else []

                for message in messages:
                    message_id = str(message.get("id", "") or "").strip()
                    from_number = str(message.get("from", "") or "").strip()
                    message_type = str(message.get("type", "") or "unknown").strip()

                    text_value = ""

                    if message_type == "text":
                        text_value = str((message.get("text", {}) or {}).get("body", "") or "").strip()
                    elif message_type == "button":
                        text_value = str((message.get("button", {}) or {}).get("text", "") or "").strip()
                    elif message_type == "interactive":
                        interactive = message.get("interactive", {}) or {}
                        button_reply = interactive.get("button_reply", {}) or {}
                        list_reply = interactive.get("list_reply", {}) or {}
                        text_value = (
                            str(button_reply.get("title", "") or "").strip()
                            or str(button_reply.get("id", "") or "").strip()
                            or str(list_reply.get("title", "") or "").strip()
                            or str(list_reply.get("id", "") or "").strip()
                        )
                    else:
                        text_value = f"[{message_type}]"

                    customer_name = contact_names.get(from_number, "")

                    log_result = post_to_google_sheet_json(
                        {
                            "token": google_sheet_token,
                            "action": "whatsapp_message_log",
                            "message_id": message_id,
                            "direction": "incoming",
                            "client_id": client_id,
                            "partner_id": partner_id,
                            "phone_number_id": phone_number_id,
                            "from": from_number,
                            "to": display_phone_number,
                            "customer_name": customer_name,
                            "text": text_value,
                            "message_type": message_type,
                            "status": "received",
                            "raw_json": json.dumps(message, ensure_ascii=False),
                            "notes": (
                                f"business_name={business_name}; "
                                f"channel_lookup_found={str(found_channel).lower()}"
                            )
                        },
                        label="whatsapp_message_log"
                    )

                    processed.append({
                        "message_id": message_id,
                        "from": from_number,
                        "type": message_type,
                        "client_id": client_id,
                        "partner_id": partner_id,
                        "phone_number_id": phone_number_id,
                        "logged": log_result
                    })

                statuses = value.get("statuses", []) if isinstance(value, dict) else []

                for status in statuses:
                    status_events.append({
                        "phone_number_id": phone_number_id,
                        "status": status
                    })

                    # Keep status logs separate but still stored as WhatsAppMessages for now.
                    post_to_google_sheet_json(
                        {
                            "token": google_sheet_token,
                            "action": "whatsapp_message_log",
                            "message_id": str(status.get("id", "") or "").strip(),
                            "direction": "status",
                            "client_id": client_id,
                            "partner_id": partner_id,
                            "phone_number_id": phone_number_id,
                            "from": "",
                            "to": display_phone_number,
                            "customer_name": "",
                            "text": str(status.get("status", "") or "").strip(),
                            "message_type": "status",
                            "status": str(status.get("status", "") or "").strip(),
                            "raw_json": json.dumps(status, ensure_ascii=False),
                            "notes": "WhatsApp message status event"
                        },
                        label="whatsapp_status_log"
                    )

        print(
            f"WHATSAPP WEBHOOK RECEIVED ✅ processed={len(processed)} statuses={len(status_events)}",
            flush=True
        )

        return jsonify({
            "status": "success",
            "processed_count": len(processed),
            "status_count": len(status_events),
            "processed": processed[:10]
        }), 200

    except Exception as error:
        print(f"WHATSAPP WEBHOOK ERROR ❌ {error}", flush=True)

        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500

# ===== ALSAAB_WHATSAPP_WEBHOOK_FOUNDATION_V1 END =====


# ===== ALSAAB_CLIENT_WHATSAPP_SETUP_ROUTE_V1 START =====

@app.route("/client-dashboard/save-whatsapp-setup", methods=["POST"])
def client_dashboard_save_whatsapp_setup():
    """
    Client Dashboard action:
    Save WhatsApp setup request for current account.

    Default setup_type:
    existing_business_app_coexistence
    """
    import os

    lang = request.form.get("lang", "ar").strip() or "ar"
    key = request.form.get("key", "").strip()
    sso_token = request.form.get("sso", "").strip()
    sso_payload = None

    if sso_token:
        sso_payload, sso_error = verify_dashboard_sso_token(sso_token)

        if sso_error:
            return redirect(build_dashboard_login_redirect("client", "", lang)), 302

    partner_id = (
        request.form.get("partner_id", "").strip()
        or (sso_payload.get("partner_id", "") if sso_payload else "")
        or session.get("partner_id", "")
    )

    partner_id = normalize_dashboard_partner_id(partner_id)

    if sso_payload:
        session["partner_id"] = partner_id
    elif not is_dashboard_access_allowed(partner_id, key):
        print(f"DASHBOARD ACCESS DENIED client lang partner_id={partner_id}", flush=True)
        return redirect(build_dashboard_login_redirect(
            "client", partner_id, request.values.get("lang", "ar")
        )), 302

    business_name = request.form.get("business_name", "").strip()
    whatsapp_number = request.form.get("whatsapp_number", "").strip()
    preferred_language = request.form.get("preferred_language", "ar").strip() or "ar"
    human_handoff = request.form.get("human_handoff", "yes").strip() or "yes"
    customer_notes = request.form.get("customer_notes", "").strip()

    if not whatsapp_number:
        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "whatsapp_setup_error"))

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            print("WHATSAPP SETUP REQUEST ERROR ❌ GOOGLE_SHEET_TOKEN missing", flush=True)
            return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "whatsapp_setup_error"))

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "whatsapp_setup_request",
                "client_id": partner_id,
                "partner_id": partner_id,
                "business_name": business_name,
                "whatsapp_number": whatsapp_number,
                "setup_type": "existing_business_app_coexistence",
                "connection_status": "pending_setup",
                "preferred_language": preferred_language,
                "human_handoff": human_handoff,
                "customer_notes": customer_notes,
            },
            label="whatsapp_setup_request"
        )

        print(f"WHATSAPP SETUP REQUEST SAVED ✅ partner_id={partner_id} result={result}", flush=True)

        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "whatsapp_setup_saved"))

    except Exception as error:
        print(f"WHATSAPP SETUP REQUEST ERROR ❌ partner_id={partner_id} error={error}", flush=True)
        return redirect(build_dashboard_return_url("/client-dashboard", key, partner_id, lang, "whatsapp_setup_error"))

# ===== ALSAAB_CLIENT_WHATSAPP_SETUP_ROUTE_V1 END =====


# ===== ALSAAB_ADMIN_WHATSAPP_SETUP_REQUESTS_PAGE_V1 START =====

@app.route("/admin/whatsapp-setup-requests", methods=["GET"])
def admin_whatsapp_setup_requests_page():
    """
    Owner/Admin page:
    View WhatsApp setup requests from Client Dashboard.
    """
    import os
    from urllib.parse import quote

    key = request.args.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    status_filter = request.args.get("status", "").strip()
    partner_id_filter = request.args.get("partner_id", "").strip()

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_whatsapp_setup_requests",
                "connection_status": status_filter,
                "partner_id": partner_id_filter
            },
            label="admin_whatsapp_setup_requests"
        )

        requests_list = []
        count = 0

        if isinstance(result, dict) and result.get("status") == "success":
            requests_list = result.get("requests") or []
            count = result.get("count") or len(requests_list)


        return render_template(
            "whatsapp_setup_requests.html",
            key=key,
            encoded_key=quote(key),
            status_filter=status_filter,
            partner_id_filter=partner_id_filter,
            result=result,
            requests_list=requests_list,
            count=count
        )

    except Exception as error:
        print(f"ADMIN WHATSAPP SETUP REQUESTS PAGE ERROR ❌ {error}", flush=True)
        return f"Error loading WhatsApp setup requests: {error}", 500


@app.route("/admin/update-whatsapp-setup-request", methods=["POST"])
def admin_update_whatsapp_setup_request_route():
    """
    Owner/Admin action:
    Update WhatsApp setup request status and Meta IDs.
    """
    import os
    from urllib.parse import quote

    key = request.form.get("key", "").strip()

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    request_id = request.form.get("request_id", "").strip()
    connection_status = request.form.get("connection_status", "").strip()
    admin_notes = request.form.get("admin_notes", "").strip()
    phone_number_id = request.form.get("phone_number_id", "").strip()
    waba_id = request.form.get("waba_id", "").strip()
    provider = request.form.get("provider", "").strip()

    try:
        from database import post_to_google_sheet_json

        google_sheet_token = os.getenv("GOOGLE_SHEET_TOKEN", "")

        if not google_sheet_token:
            return "GOOGLE_SHEET_TOKEN missing", 500

        result = post_to_google_sheet_json(
            {
                "token": google_sheet_token,
                "action": "admin_update_whatsapp_setup_request",
                "request_id": request_id,
                "connection_status": connection_status,
                "admin_notes": admin_notes,
                "phone_number_id": phone_number_id,
                "waba_id": waba_id,
                "provider": provider,
                "actor": "owner_admin",
                "source": "admin_whatsapp_setup_requests_page",
                "reason": "Admin updated WhatsApp setup request"
            },
            label="admin_update_whatsapp_setup_request"
        )

        print(f"ADMIN UPDATE WHATSAPP SETUP REQUEST ✅ request_id={request_id} result={result}", flush=True)

        return redirect(f"/admin/whatsapp-setup-requests?key={quote(key)}")

    except Exception as error:
        print(f"ADMIN UPDATE WHATSAPP SETUP REQUEST ERROR ❌ request_id={request_id} error={error}", flush=True)
        return redirect(f"/admin/whatsapp-setup-requests?key={quote(key)}")

# ===== ALSAAB_ADMIN_WHATSAPP_SETUP_REQUESTS_PAGE_V1 END =====


# ===== ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2 START =====

@app.after_request
def inject_admin_whatsapp_requests_button(response):
    """
    Adds a normal non-floating WhatsApp setup requests button inside Admin Dashboard.
    """
    try:
        if request.path != "/admin-dashboard":
            return response

        content_type = response.headers.get("Content-Type", "")

        if "text/html" not in content_type:
            return response

        html = response.get_data(as_text=True)

        if "ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2_HTML" in html:
            return response

        snippet = """
<!-- ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2_HTML START -->
<script>
(function () {
  if (document.getElementById("alsaab-wa-requests-admin-box")) {
    return;
  }

  var params = new URLSearchParams(window.location.search);
  var key = params.get("key") || "";
  var href = "/admin/whatsapp-setup-requests?key=" + encodeURIComponent(key);

  var box = document.createElement("div");
  box.id = "alsaab-wa-requests-admin-box";
  box.style.cssText = [
    "background:#111",
    "border:1px solid rgba(215,184,90,.35)",
    "border-radius:18px",
    "padding:16px 18px",
    "margin:18px 0",
    "display:flex",
    "align-items:center",
    "justify-content:space-between",
    "gap:12px",
    "flex-wrap:wrap",
    "box-shadow:0 8px 25px rgba(0,0,0,.20)"
  ].join(";");

  box.innerHTML =
    '<div>' +
      '<div style="color:#d7b85a;font-size:20px;font-weight:900;margin-bottom:4px;">طلبات ربط WhatsApp</div>' +
      '<div style="color:#cfc7ad;font-size:13px;line-height:1.7;">إدارة طلبات ربط أرقام WhatsApp الحالية للعملاء وتحديث حالة الربط.</div>' +
    '</div>' +
    '<a href="' + href + '" style="' +
      'border:1px solid rgba(215,184,90,.75);' +
      'color:#d7b85a;' +
      'background:#0b0b0b;' +
      'border-radius:999px;' +
      'padding:11px 16px;' +
      'font-family:Arial,Tahoma,sans-serif;' +
      'font-weight:900;' +
      'text-decoration:none;' +
      'display:inline-block;' +
    '">فتح طلبات ربط WhatsApp</a>';

  var header = document.querySelector(".header");
  var page = document.querySelector(".page") || document.body;

  if (header && header.parentNode) {
    header.parentNode.insertBefore(box, header.nextSibling);
  } else if (page && page.firstChild) {
    page.insertBefore(box, page.firstChild);
  } else {
    document.body.insertBefore(box, document.body.firstChild);
  }
})();
</script>
<!-- ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2_HTML END -->
"""

        if "</body>" in html:
            html = html.replace("</body>", snippet + "\n</body>", 1)
        else:
            html = html + snippet

        response.set_data(html)

    except Exception as error:
        print(f"ADMIN WHATSAPP REQUESTS BUTTON INJECTION ERROR ❌ {error}", flush=True)

    return response

# ===== ALSAAB_ADMIN_WHATSAPP_REQUESTS_BUTTON_V2 END =====


# ===== ALSAAB WEBSITE SETUP ROUTES REGISTER START =====

# ===== ALSAAB CUSTOMER AUTH V1 START =====
# Passwordless sign-in (/login), public pricing (/plans) and /logout.
try:
    from auth_routes import register_auth_routes
except ImportError:
    from backend.auth_routes import register_auth_routes

register_auth_routes(app)
# ===== ALSAAB CUSTOMER AUTH V1 END =====

try:
    from website_setup_routes import register_website_setup_routes
except ImportError:
    from backend.website_setup_routes import register_website_setup_routes

register_website_setup_routes(app, ADMIN_KEY)
# ===== ALSAAB WEBSITE SETUP ROUTES REGISTER END =====
# ===== ALSAAB BOT CONTROL ROUTES REGISTER START =====
try:
    from bot_control_routes import register_bot_control_routes
except ImportError:
    from backend.bot_control_routes import register_bot_control_routes

register_bot_control_routes(app)
# ===== ALSAAB BOT CONTROL ROUTES REGISTER END =====
# ===== ALSAAB UPGRADE ROUTES REGISTER START =====
try:
    from upgrade_routes import register_upgrade_routes
except ImportError:
    from backend.upgrade_routes import register_upgrade_routes

register_upgrade_routes(app, ADMIN_KEY)
# ===== ALSAAB UPGRADE ROUTES REGISTER END =====
# ===== ALSAAB SMART LINK ROUTES REGISTER START =====
try:
    from smart_link_routes import register_smart_link_routes
except ImportError:
    from backend.smart_link_routes import register_smart_link_routes

register_smart_link_routes(app)
# ===== ALSAAB SMART LINK ROUTES REGISTER END =====
# ===== ALSAAB SMART LINK DASHBOARD ROUTES REGISTER START =====
try:
    from smart_link_dashboard_routes import register_smart_link_dashboard_routes
except ImportError:
    from backend.smart_link_dashboard_routes import register_smart_link_dashboard_routes

register_smart_link_dashboard_routes(app)
# ===== ALSAAB SMART LINK DASHBOARD ROUTES REGISTER END =====
# ===== ALSAAB CLIENT DASHBOARD CLEANUP ROUTES REGISTER START =====
try:
    from client_dashboard_cleanup_routes import register_client_dashboard_cleanup_routes
except ImportError:
    from backend.client_dashboard_cleanup_routes import register_client_dashboard_cleanup_routes

register_client_dashboard_cleanup_routes(app)
# ===== ALSAAB CLIENT DASHBOARD CLEANUP ROUTES REGISTER END =====
# ===== ALSAAB SMART LINK ANALYTICS ROUTES REGISTER START =====
try:
    from smart_link_analytics_routes import register_smart_link_analytics_routes
except ImportError:
    from backend.smart_link_analytics_routes import register_smart_link_analytics_routes

register_smart_link_analytics_routes(app)
# ===== ALSAAB SMART LINK ANALYTICS ROUTES REGISTER END =====
# ===== ALSAAB SMART LINK PROTECTION ROUTES REGISTER START =====
try:
    from smart_link_protection_routes import register_smart_link_protection_routes
except ImportError:
    from backend.smart_link_protection_routes import register_smart_link_protection_routes

register_smart_link_protection_routes(app)
# ===== ALSAAB SMART LINK PROTECTION ROUTES REGISTER END =====
# ===== ALSAAB CANCELLATION ROUTES REGISTER START =====
try:
    from cancellation_routes import register_cancellation_routes
except ImportError:
    from backend.cancellation_routes import register_cancellation_routes

register_cancellation_routes(app, ADMIN_KEY)
# ===== ALSAAB CANCELLATION ROUTES REGISTER END =====


# ===== ALSAAB_PAYMENT_INTENT_V6 START =====
# Stronger payment intent detector.
# Fixes phrases like:
# - طرش رابط الدفع
# - ارسل رابط الدفع
# - ابا رابط الدفع
# - رابط دخول 99
# - احتاج رابط باقة الدخول 99 درهم
# It keeps the safe behavior: only explicit payment/link requests trigger a payment link.

def _alsaab_payment_norm_v6(value):
    text = str(value or "").strip().lower()
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        "ـ": "",
        "٩": "9",
        "٨": "8",
        "٧": "7",
        "٦": "6",
        "٥": "5",
        "٤": "4",
        "٣": "3",
        "٢": "2",
        "١": "1",
        "٠": "0",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    text = " ".join(text.split())
    return text


def alsaab_chat_explicit_payment_plan_v5(message):
    text = _alsaab_payment_norm_v6(message)
    if not text:
        return None

    direct_payment_intents = [
        "رابط الدفع",
        "رابط دفع",
        "رابط الباقه",
        "رابط الاشتراك",
        "طرش رابط",
        "طرشلي رابط",
        "ارسل رابط",
        "ارسلي رابط",
        "ارسل الرابط",
        "طرش الرابط",
        "ابا رابط",
        "ابي رابط",
        "ابغي رابط",
        "احتاج رابط",
        "عطني رابط",
        "اعطني رابط",
        "ادفع",
        "الدفع",
        "ابا ادفع",
        "ابي ادفع",
        "ابغي ادفع",
        "اريد ادفع",
        "احتاج ادفع",
        "بغيت ادفع",
        "اشترك",
        "اشتراك",
        "ابا اشترك",
        "ابي اشترك",
        "ابغي اشترك",
    ]

    has_payment_intent = any(x in text for x in direct_payment_intents)
    if not has_payment_intent:
        return None

    plan_aliases = [
        ("diamond", ["diamond", "دايموند", "الماسيه", "ماسيه", "2399", "٢٣٩٩"]),
        ("elite", ["elite", "ايليت", "النخبه", "نخبه", "1199", "١١٩٩"]),
        ("growth", ["growth", "النمو", "نمو", "599", "٥٩٩"]),
        ("starter", ["starter", "ستارتر", "البدايه", "بدايه", "299", "٢٩٩"]),
        ("entry", ["entry", "انتري", "باقة الدخول", "باقه الدخول", "الدخول", "دخول", "99", "٩٩"]),
    ]

    for plan, aliases in plan_aliases:
        if any(alias in text for alias in aliases):
            return plan

    # If the client explicitly asks for a payment link but does not repeat the plan,
    # default to Entry instead of blocking the sale.
    # This matches normal chat behavior after the client asks for the 99 AED package.
    if any(x in text for x in [
        "رابط الدفع",
        "رابط دفع",
        "طرش رابط",
        "طرشلي رابط",
        "ارسل رابط",
        "ارسلي رابط",
        "ابا رابط",
        "ابي رابط",
        "ابغي رابط",
        "احتاج رابط",
        "عطني رابط",
        "اعطني رابط",
        "ادفع",
        "ابا ادفع",
        "ابي ادفع",
        "ابغي ادفع",
        "اريد ادفع",
        "احتاج ادفع",
    ]):
        return "entry"

    return None
# ===== ALSAAB_PAYMENT_INTENT_V6 END =====


# ===== ALSAAB_PAYMENT_DETECTOR_FINAL_UTF8_V7 START =====
# Final safe detector using ASCII unicode escapes to avoid Windows/PowerShell encoding corruption.
def alsaab_chat_explicit_payment_plan_v5(message):
    text = str(message or "").strip().lower()
    replacements = {
        "\u0623": "\u0627",
        "\u0625": "\u0627",
        "\u0622": "\u0627",
        "\u0649": "\u064a",
        "\u0629": "\u0647",
        "\u0624": "\u0648",
        "\u0626": "\u064a",
        "\u0640": "",
        "\u0669": "9",
        "\u0668": "8",
        "\u0667": "7",
        "\u0666": "6",
        "\u0665": "5",
        "\u0664": "4",
        "\u0663": "3",
        "\u0662": "2",
        "\u0661": "1",
        "\u0660": "0",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    text = " ".join(text.split())
    if not text:
        return None

    plan_aliases = [
        ("diamond", ["diamond", "\u062f\u0627\u064a\u0645\u0648\u0646\u062f", "\u0627\u0644\u0645\u0627\u0633\u064a\u0647", "\u0645\u0627\u0633\u064a\u0647", "2399"]),
        ("elite", ["elite", "\u0627\u064a\u0644\u064a\u062a", "\u0627\u0644\u0646\u062e\u0628\u0647", "\u0646\u062e\u0628\u0647", "1199"]),
        ("growth", ["growth", "\u0627\u0644\u0646\u0645\u0648", "\u0646\u0645\u0648", "599"]),
        ("starter", ["starter", "\u0633\u062a\u0627\u0631\u062a\u0631", "\u0627\u0644\u0628\u062f\u0627\u064a\u0647", "\u0628\u062f\u0627\u064a\u0647", "299"]),
        ("entry", ["entry", "\u0627\u0646\u062a\u0631\u064a", "\u0628\u0627\u0642\u0629 \u0627\u0644\u062f\u062e\u0648\u0644", "\u0628\u0627\u0642\u0647 \u0627\u0644\u062f\u062e\u0648\u0644", "\u0627\u0644\u062f\u062e\u0648\u0644", "\u062f\u062e\u0648\u0644", "99"]),
    ]

    selected_plan = None
    for plan, aliases in plan_aliases:
        if any(alias in text for alias in aliases):
            selected_plan = plan
            break

    payment_intents = [
        "\u0631\u0627\u0628\u0637 \u0627\u0644\u062f\u0641\u0639",
        "\u0631\u0627\u0628\u0637 \u062f\u0641\u0639",
        "\u0631\u0627\u0628\u0637 \u0627\u0644\u0628\u0627\u0642\u0647",
        "\u0631\u0627\u0628\u0637 \u0628\u0627\u0642\u0647",
        "\u0631\u0627\u0628\u0637 \u0627\u0644\u0627\u0634\u062a\u0631\u0627\u0643",
        "\u0631\u0627\u0628\u0637 \u0627\u0634\u062a\u0631\u0627\u0643",
        "\u0631\u0627\u0628\u0637 \u062f\u062e\u0648\u0644",
        "\u0631\u0627\u0628\u0637 \u0628\u0627\u0642\u0629 \u0627\u0644\u062f\u062e\u0648\u0644",
        "\u0631\u0627\u0628\u0637 \u0628\u0627\u0642\u0647 \u0627\u0644\u062f\u062e\u0648\u0644",
        "\u0637\u0631\u0634 \u0631\u0627\u0628\u0637",
        "\u0637\u0631\u0634\u0644\u064a \u0631\u0627\u0628\u0637",
        "\u0637\u0631\u0634 \u0627\u0644\u0631\u0627\u0628\u0637",
        "\u0627\u0631\u0633\u0644 \u0631\u0627\u0628\u0637",
        "\u0627\u0631\u0633\u0644\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0631\u0633\u0644 \u0627\u0644\u0631\u0627\u0628\u0637",
        "\u0627\u0628\u0627 \u0631\u0627\u0628\u0637",
        "\u0627\u0628\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0628\u063a\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0628\u063a\u0627 \u0631\u0627\u0628\u0637",
        "\u0627\u062d\u062a\u0627\u062c \u0631\u0627\u0628\u0637",
        "\u0645\u062d\u062a\u0627\u062c \u0631\u0627\u0628\u0637",
        "\u0639\u0637\u0646\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u0639\u0637\u0646\u064a \u0631\u0627\u0628\u0637",
        "\u0627\u062f\u0641\u0639",
        "\u0627\u0644\u062f\u0641\u0639",
        "\u0627\u0628\u0627 \u0627\u062f\u0641\u0639",
        "\u0627\u0628\u064a \u0627\u062f\u0641\u0639",
        "\u0627\u0628\u063a\u064a \u0627\u062f\u0641\u0639",
        "\u0627\u0628\u063a\u0627 \u0627\u062f\u0641\u0639",
        "\u0627\u0631\u064a\u062f \u0627\u062f\u0641\u0639",
        "\u0627\u062d\u062a\u0627\u062c \u0627\u062f\u0641\u0639",
        "\u0645\u062d\u062a\u0627\u062c \u0627\u062f\u0641\u0639",
        "\u0628\u063a\u064a\u062a \u0627\u062f\u0641\u0639",
        "\u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0634\u062a\u0631\u0627\u0643",
        "\u0627\u0628\u0627 \u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0628\u064a \u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0628\u063a\u064a \u0627\u0634\u062a\u0631\u0643",
        "\u0627\u0628\u063a\u0627 \u0627\u0634\u062a\u0631\u0643",
    ]

    payment_intents.extend(_AL_PAY_TERMS)

    has_payment_intent = any(x in text for x in payment_intents)

    if selected_plan and ("\u0631\u0627\u0628\u0637" in text or "\u062f\u0641\u0639" in text or "\u0627\u062f\u0641\u0639" in text or "\u0627\u0634\u062a\u0631\u0627\u0643" in text or "\u0627\u0634\u062a\u0631\u0643" in text):
        return selected_plan

    if has_payment_intent:
        return selected_plan or "entry"

    return None
# ===== ALSAAB_PAYMENT_DETECTOR_FINAL_UTF8_V7 END =====


# ===== ALSAAB ENTRY PAYMENT ROUTES REGISTER START =====
try:
    from entry_payment_routes import register_entry_payment_routes
except ImportError:
    from backend.entry_payment_routes import register_entry_payment_routes

register_entry_payment_routes(app)
# ===== ALSAAB ENTRY PAYMENT ROUTES REGISTER END =====
# ===== ALSAAB RANK DASHBOARD ROUTES REGISTER START =====
try:
    from rank_dashboard_routes import register_rank_dashboard_routes
except ImportError:
    from backend.rank_dashboard_routes import register_rank_dashboard_routes

register_rank_dashboard_routes(app)
# ===== ALSAAB RANK DASHBOARD ROUTES REGISTER END =====
# ===== ALSAAB RANK DASHBOARD POLISH ROUTES REGISTER START =====
try:
    from rank_dashboard_polish_routes import register_rank_dashboard_polish_routes
except ImportError:
    from backend.rank_dashboard_polish_routes import register_rank_dashboard_polish_routes

register_rank_dashboard_polish_routes(app)
# ===== ALSAAB RANK DASHBOARD POLISH ROUTES REGISTER END =====
# ===== ALSAAB SMART LINK SUMMARY CACHE REGISTER START =====
try:
    from smart_link_summary_cache_routes import register_smart_link_summary_cache_routes
except ImportError:
    from backend.smart_link_summary_cache_routes import register_smart_link_summary_cache_routes

register_smart_link_summary_cache_routes(app)
# ===== ALSAAB SMART LINK SUMMARY CACHE REGISTER END =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
