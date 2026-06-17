from pathlib import Path
import re

p = Path("backend/prompt_builder.py")
text = p.read_text(encoding="utf-8")
p.with_suffix(".py.bak_prompt_prices_2026").write_text(text, encoding="utf-8")

# Fix old package amounts everywhere in prompt_builder
replacements = {
    "299 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹": "99 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹",
    "599 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹": "299 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹",
    "1099 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹": "599 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹",
    "2099 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹": "1199 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹",
    "12000 Ø±Ø¯ Ø´Ù‡Ø±ÙŠ Ù„Ù„Ø¹Ù…Ù„Ø§Ø¡ + 3000": "15000 Ø±Ø¯ Ø´Ù‡Ø±ÙŠ Ù„Ù„Ø¹Ù…Ù„Ø§Ø¡",
    "12000 Ø±Ø¯ Ù„Ù„Ø¹Ù…Ù„Ø§Ø¡ + 3000": "15000 Ø±Ø¯ Ù„Ù„Ø¹Ù…Ù„Ø§Ø¡",
}

for old, new in replacements.items():
    text = text.replace(old, new)

# Add a final hard rule block so the AI cannot use old prices
hard_rule = r'''
# ===== ALSAAB_PACKAGES_2026_PROMPT_OVERRIDE_V1 START =====
ALSAAB_PACKAGES_2026_PROMPT_OVERRIDE = """
⚠️ قواعد نهائية لأسعار وباقات ALSAAB AI — لا تستخدم أي أسعار قديمة:

الباقات الرسمية الحالية:
1) Entry / باقة الدخول:
- 99 درهم شهرياً
- 500 رد شهري
- بدون صور
- بدون روابط دفع
- WhatsApp فقط

2) Starter / باقة البداية:
- 299 درهم شهرياً
- 2000 رد شهري
- WhatsApp فقط
- مناسبة للبداية

3) Growth / باقة النمو:
- 599 درهم شهرياً
- 6000 رد للعملاء + 1000 رد استشاري لصاحب المشروع
- تدعم الموقع حسب الإعداد
- تدعم صور المنتجات وروابط الدفع الخاصة بالعميل

4) Elite / باقة النخبة:
- 1199 درهم شهرياً
- 15000 رد للعملاء + 2000 رد استشاري لصاحب المشروع
- WhatsApp + Website + Instagram حسب الربط المتقدم

5) Diamond / الباقة الماسية:
- 2399 درهم شهرياً
- 40000 رد للعملاء + 5000 رد استشاري لصاحب المشروع
- أعلى باقة جاهزة قبل Enterprise

ممنوع استخدام هذه الأسعار القديمة:
Entry 299
Starter 599
Growth 1099
Elite 2099

إذا طلب العميل روابط الدفع، استخدم روابط الدفع الداخلية /pay/plan وليس روابط Stripe المباشرة إذا كانت الروابط الداخلية متاحة.
"""
def _alsaab_append_packages_2026_override(prompt_text):
    if "ALSAAB_PACKAGES_2026_PROMPT_OVERRIDE" in str(prompt_text):
        return prompt_text
    return str(prompt_text).rstrip() + "\n\n" + ALSAAB_PACKAGES_2026_PROMPT_OVERRIDE.strip() + "\n"
# ===== ALSAAB_PACKAGES_2026_PROMPT_OVERRIDE_V1 END =====
'''

if "ALSAAB_PACKAGES_2026_PROMPT_OVERRIDE_V1" not in text:
    text = text.rstrip() + "\n\n" + hard_rule + "\n"

# Wrap common prompt builder functions if they exist
wrap = r'''
# ===== ALSAAB_PACKAGES_2026_PROMPT_WRAP_V1 START =====
for _fn_name in [
    "build_prompt",
    "build_system_prompt",
    "build_sales_prompt",
    "build_alsaab_prompt",
    "build_project_prompt",
]:
    _old_fn = globals().get(_fn_name)
    if callable(_old_fn) and not getattr(_old_fn, "_alsaab_packages_2026_wrapped", False):
        def _make_wrapper(fn):
            def _wrapped(*args, **kwargs):
                return _alsaab_append_packages_2026_override(fn(*args, **kwargs))
            _wrapped._alsaab_packages_2026_wrapped = True
            return _wrapped
        globals()[_fn_name] = _make_wrapper(_old_fn)
# ===== ALSAAB_PACKAGES_2026_PROMPT_WRAP_V1 END =====
'''

if "ALSAAB_PACKAGES_2026_PROMPT_WRAP_V1" not in text:
    text = text.rstrip() + "\n\n" + wrap + "\n"

p.write_text(text, encoding="utf-8")
