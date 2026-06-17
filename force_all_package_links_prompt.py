from pathlib import Path
import re

p = Path("backend/prompt_builder.py")
text = p.read_text(encoding="utf-8")
p.with_suffix(".py.bak_force_all_official_package_links").write_text(text, encoding="utf-8")

# نظف أي سعر قديم واضح داخل البرومبت فقط
replace_map = {
    "الدخول بـ 299": "الدخول بـ 99",
    "باقة الدخول — 299": "باقة الدخول — 99",
    "باقة الدخول** — 299": "باقة الدخول** — 99",
    "- السعر: 299 درهم شهرياً": "- السعر: 99 درهم شهرياً",

    "البداية بـ 599": "البداية بـ 299",
    "باقة البداية — 599": "باقة البداية — 299",
    "باقة البداية** — 599": "باقة البداية** — 299",

    "النمو بـ 1099": "النمو بـ 599",
    "باقة النمو — 1099": "باقة النمو — 599",
    "باقة النمو** — 1099": "باقة النمو** — 599",

    "النخبة بـ 2099": "النخبة بـ 1199",
    "باقة النخبة — 2099": "باقة النخبة — 1199",
    "باقة النخبة** — 2099": "باقة النخبة** — 1199",
}
for old, new in replace_map.items():
    text = text.replace(old, new)

# احذف أي override قديم للباقات عشان ما يتضارب
text = re.sub(
    r"# ===== ALSAAB_OFFICIAL_PACKAGE_REPLY_OVERRIDE_V2 START =====.*?# ===== ALSAAB_OFFICIAL_PACKAGE_REPLY_WRAP_V2 END =====",
    "",
    text,
    flags=re.S
)

block = '''
# ===== ALSAAB_FORCE_OFFICIAL_PACKAGES_AND_LINKS_V3 START =====
ALSAAB_FORCE_OFFICIAL_PACKAGES_AND_LINKS_V3 = """
قاعدة نهائية إلزامية عند ذكر الباقات أو الأسعار أو روابط الدفع:

اعرض هذه الباقات فقط، بنفس الأسعار ونفس روابط الدفع الرسمية:

1) Entry / باقة الدخول — 99 AED شهرياً
- 500 رد شهري
- رابط الدفع:
https://buy.stripe.com/4gMcN61d2dxI6ku10zaEE07

2) Starter / باقة البداية — 299 AED شهرياً
- 2000 رد شهري
- رابط الدفع:
https://buy.stripe.com/aFa8wQ9Jy8docISeRpaEE08

3) Growth / باقة النمو — 599 AED شهرياً
- 6000 رد للعملاء + 1000 رد استشاري لصاحب المشروع
- رابط الدفع:
https://buy.stripe.com/7sY14obRG8doaAK5gPaEE09

4) Elite / باقة النخبة — 1199 AED شهرياً
- 15000 رد للعملاء + 2000 رد استشاري لصاحب المشروع
- رابط الدفع:
https://buy.stripe.com/28E9AUf3SalwbEO4cLaEE0a

5) Diamond / الباقة الماسية — 2399 AED شهرياً
- 40000 رد للعملاء + 5000 رد استشاري لصاحب المشروع
- رابط الدفع:
https://buy.stripe.com/aFaeVe7Bq51c4cmcJhaEE0b

ممنوع نهائياً عرض الأسعار القديمة:
Entry 299
Starter 599
Growth 1099
Elite 2099

ممنوع تنقص أي باقة إذا العميل طلب كل الباقات.
ممنوع تخترع روابط دفع.
"""
def _alsaab_force_official_packages_and_links_v3(prompt_text):
    if "ALSAAB_FORCE_OFFICIAL_PACKAGES_AND_LINKS_V3" in str(prompt_text):
        return prompt_text
    return str(prompt_text).rstrip() + "\\n\\n" + ALSAAB_FORCE_OFFICIAL_PACKAGES_AND_LINKS_V3.strip() + "\\n"

for _fn_name in [
    "build_prompt",
    "build_system_prompt",
    "build_sales_prompt",
    "build_alsaab_prompt",
    "build_project_prompt",
]:
    _old_fn = globals().get(_fn_name)
    if callable(_old_fn) and not getattr(_old_fn, "_alsaab_force_packages_v3_wrapped", False):
        def _make_wrapper(fn):
            def _wrapped(*args, **kwargs):
                return _alsaab_force_official_packages_and_links_v3(fn(*args, **kwargs))
            _wrapped._alsaab_force_packages_v3_wrapped = True
            return _wrapped
        globals()[_fn_name] = _make_wrapper(_old_fn)
# ===== ALSAAB_FORCE_OFFICIAL_PACKAGES_AND_LINKS_V3 END =====
'''

text = text.rstrip() + "\n\n" + block + "\n"
p.write_text(text, encoding="utf-8")

print("ALL_PACKAGE_LINKS_PROMPT_FORCED_OK")
