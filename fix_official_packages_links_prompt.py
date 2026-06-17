from pathlib import Path

# =========================
# 1) CONFIG: official Stripe data
# =========================
config_path = Path("backend/config.py")
config_text = config_path.read_text(encoding="utf-8")
config_path.with_suffix(".py.bak_official_stripe_packages").write_text(config_text, encoding="utf-8")

config_block = '''
# ===== ALSAAB_OFFICIAL_STRIPE_PACKAGES_V2 START =====
# Official approved package prices + Stripe links/ids.
# Do not remove. This block overrides older package/payment values safely.

OFFICIAL_PACKAGE_PRICES_2026 = {
    "entry": "99 AED",
    "starter": "299 AED",
    "growth": "599 AED",
    "elite": "1199 AED",
    "diamond": "2399 AED",
}

PAYMENT_LINKS.update({
    "entry": "https://buy.stripe.com/4gMcN61d2dxI6ku10zaEE07",
    "starter": "https://buy.stripe.com/aFa8wQ9Jy8docISeRpaEE08",
    "growth": "https://buy.stripe.com/7sY14obRG8doaAK5gPaEE09",
    "elite": "https://buy.stripe.com/28E9AUf3SalwbEO4cLaEE0a",
    "diamond": "https://buy.stripe.com/aFaeVe7Bq51c4cmcJhaEE0b",
})

STRIPE_PRICE_IDS = {
    "entry": "price_1Tj84XJbltD9Bsg8rOGTTn3D",
    "starter": "price_1Tj8JmJbltD9Bsg81rMyR7lJ",
    "growth": "price_1Tj8MQJbltD9Bsg8XL7xwOYe",
    "elite": "price_1Tj8OwJbltD9Bsg8h7DCVKbY",
    "diamond": "price_1Tj8T7JbltD9Bsg8bdi7XyiL",
}

STRIPE_PRODUCT_IDS = {
    "entry": "prod_UiZCqDWqXkzVLL",
    "starter": "prod_UiZS4ivHpbRIbE",
    "growth": "prod_UiZVcDRBvn38CN",
    "elite": "prod_UiZY0MsCbzD3dC",
    "diamond": "prod_UiZcnUHa54wiu8",
}

PAYMENT_ROUTE_LINKS.update({
    "entry": f"{APP_BASE_URL}/pay/entry",
    "starter": f"{APP_BASE_URL}/pay/starter",
    "growth": f"{APP_BASE_URL}/pay/growth",
    "elite": f"{APP_BASE_URL}/pay/elite",
    "diamond": f"{APP_BASE_URL}/pay/diamond",
})

STRIPE_PLAN_CONFIG = {
    plan: {
        "plan_name": plan,
        "payment_link": PAYMENT_LINKS[plan],
        "internal_payment_route": PAYMENT_ROUTE_LINKS[plan],
        "monthly_reply_limit": PACKAGES[plan]["monthly_reply_limit"],
        "package_amount": OFFICIAL_PACKAGE_PRICES_2026[plan],
        "subscription_type": "monthly",
    }
    for plan in ["entry", "starter", "growth", "elite", "diamond"]
}

PACKAGE_ORDER = ["entry", "starter", "growth", "elite", "diamond"]
# ===== ALSAAB_OFFICIAL_STRIPE_PACKAGES_V2 END =====
'''

if "ALSAAB_OFFICIAL_STRIPE_PACKAGES_V2" not in config_text:
    config_text = config_text.rstrip() + "\n\n" + config_block + "\n"

config_path.write_text(config_text, encoding="utf-8")


# =========================
# 2) PROMPT: remove wrong prices + force final official list
# =========================
prompt_path = Path("backend/prompt_builder.py")
prompt_text = prompt_path.read_text(encoding="utf-8")
prompt_path.with_suffix(".py.bak_official_prompt_packages").write_text(prompt_text, encoding="utf-8")

replacements = {
    "باقة الدخول** — 299 درهم شهرية": "باقة الدخول** — 99 درهم شهرية",
    "باقة الدخول — 299 درهم شهرية": "باقة الدخول — 99 درهم شهرية",
    "الدخول بـ 299": "الدخول بـ 99",
    "Entry 299": "Entry 99",

    "باقة البداية** — 599 درهم شهرية": "باقة البداية** — 299 درهم شهرية",
    "باقة البداية — 599 درهم شهرية": "باقة البداية — 299 درهم شهرية",
    "البداية بـ 599": "البداية بـ 299",
    "Starter 599": "Starter 299",

    "باقة النمو** — 1099 درهم شهرية": "باقة النمو** — 599 درهم شهرية",
    "باقة النمو — 1099 درهم شهرية": "باقة النمو — 599 درهم شهرية",
    "النمو بـ 1099": "النمو بـ 599",
    "Growth 1099": "Growth 599",

    "باقة النخبة** — 2099 درهم شهرية": "باقة النخبة** — 1199 درهم شهرية",
    "باقة النخبة — 2099 درهم شهرية": "باقة النخبة — 1199 درهم شهرية",
    "النخبة بـ 2099": "النخبة بـ 1199",
    "Elite 2099": "Elite 1199",
}

for old, new in replacements.items():
    prompt_text = prompt_text.replace(old, new)

prompt_block = '''
# ===== ALSAAB_OFFICIAL_PACKAGE_REPLY_OVERRIDE_V2 START =====
ALSAAB_OFFICIAL_PACKAGE_REPLY_OVERRIDE_V2 = """
قاعدة نهائية إلزامية عند ذكر الباقات أو الأسعار أو روابط الدفع:

اعرض الباقات الرسمية الحالية فقط بهذا الشكل:

1) Entry / باقة الدخول — 99 درهم شهرياً
- 500 رد شهري
- WhatsApp فقط
- رابط الدفع الداخلي: /pay/entry

2) Starter / باقة البداية — 299 درهم شهرياً
- 2000 رد شهري
- WhatsApp فقط
- رابط الدفع الداخلي: /pay/starter

3) Growth / باقة النمو — 599 درهم شهرياً
- 6000 رد للعملاء + 1000 رد استشاري لصاحب المشروع
- يدعم الموقع حسب الإعداد
- رابط الدفع الداخلي: /pay/growth

4) Elite / باقة النخبة — 1199 درهم شهرياً
- 15000 رد للعملاء + 2000 رد استشاري لصاحب المشروع
- WhatsApp + Website + Instagram حسب الربط المتقدم
- رابط الدفع الداخلي: /pay/elite

5) Diamond / الباقة الماسية — 2399 درهم شهرياً
- 40000 رد للعملاء + 5000 رد استشاري لصاحب المشروع
- أعلى باقة جاهزة قبل Enterprise
- رابط الدفع الداخلي: /pay/diamond

ممنوع نهائياً عرض هذه الأسعار القديمة:
Entry 299
Starter 599
Growth 1099
Elite 2099

إذا طلب العميل كل الباقات، اذكر الخمس باقات كاملة ولا تنقص Diamond.
إذا طلب رابط الدفع، استخدم الرابط الداخلي /pay/package حتى يحافظ النظام على session_id والتتبع.
"""
def _alsaab_append_official_package_reply_override_v2(prompt_text):
    if "ALSAAB_OFFICIAL_PACKAGE_REPLY_OVERRIDE_V2" in str(prompt_text):
        return prompt_text
    return str(prompt_text).rstrip() + "\\n\\n" + ALSAAB_OFFICIAL_PACKAGE_REPLY_OVERRIDE_V2.strip() + "\\n"
# ===== ALSAAB_OFFICIAL_PACKAGE_REPLY_OVERRIDE_V2 END =====

# ===== ALSAAB_OFFICIAL_PACKAGE_REPLY_WRAP_V2 START =====
for _fn_name in [
    "build_prompt",
    "build_system_prompt",
    "build_sales_prompt",
    "build_alsaab_prompt",
    "build_project_prompt",
]:
    _old_fn = globals().get(_fn_name)
    if callable(_old_fn) and not getattr(_old_fn, "_alsaab_official_package_reply_v2_wrapped", False):
        def _make_official_package_reply_wrapper(fn):
            def _wrapped(*args, **kwargs):
                return _alsaab_append_official_package_reply_override_v2(fn(*args, **kwargs))
            _wrapped._alsaab_official_package_reply_v2_wrapped = True
            return _wrapped
        globals()[_fn_name] = _make_official_package_reply_wrapper(_old_fn)
# ===== ALSAAB_OFFICIAL_PACKAGE_REPLY_WRAP_V2 END =====
'''

if "ALSAAB_OFFICIAL_PACKAGE_REPLY_OVERRIDE_V2" not in prompt_text:
    prompt_text = prompt_text.rstrip() + "\n\n" + prompt_block + "\n"

prompt_path.write_text(prompt_text, encoding="utf-8")

print("OFFICIAL_PACKAGE_LINKS_AND_PROMPT_OK")
