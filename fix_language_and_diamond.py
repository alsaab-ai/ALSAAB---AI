from pathlib import Path
import re

p = Path("backend/prompt_builder.py")
text = p.read_text(encoding="utf-8")
p.with_suffix(".py.bak_fix_language_and_diamond").write_text(text, encoding="utf-8")

# Fix old package count instructions only
text = text.replace('اشرح الباقات الثلاث فقط', 'اشرح الباقات الخمس كاملة')
text = text.replace('لازم تذكر كل الباقات الأربع', 'لازم تذكر كل الباقات الخمس')
text = text.replace('كل الباقات الأربع', 'كل الباقات الخمس')

# Remove older final language/package hard overrides if repeated
text = re.sub(
    r"# ===== ALSAAB_LANGUAGE_AND_DIAMOND_FINAL_FIX_V1 START =====.*?# ===== ALSAAB_LANGUAGE_AND_DIAMOND_FINAL_FIX_V1 END =====",
    "",
    text,
    flags=re.S
)

block = r'''
# ===== ALSAAB_LANGUAGE_AND_DIAMOND_FINAL_FIX_V1 START =====
def _alsaab_language_and_diamond_final_fix(prompt_text, state=None):
    state = state or {}
    lang = str(state.get("language") or "").lower().strip()

    if lang == "en":
        language_rule = """
FINAL LANGUAGE RULE:
The customer's latest message is English.
You MUST reply in English only.
Do not reply in Arabic.
Do not mix Arabic unless the customer asks for Arabic.
"""
    elif lang == "ar":
        language_rule = """
قاعدة اللغة النهائية:
آخر رسالة من العميل عربية.
رد بالعربي. الأسلوب الأساسي إماراتي/خليجي مرتب، بدون مبالغة.
"""
    else:
        language_rule = """
FINAL LANGUAGE RULE:
Reply in the same language used by the customer's latest message.
If the customer writes French, reply in French.
If the customer writes Italian, reply in Italian.
If the customer writes Spanish, reply in Spanish.
If the customer writes English, reply in English.
Do not force Arabic unless the customer writes Arabic.
"""

    diamond_rule = """
قاعدة نهائية للباقات والعمولات والأرباح:
إذا سأل العميل عن الباقات أو الأسعار أو روابط الدفع أو الأرباح أو الدخل أو العمولات، لازم تذكر كل الباقات الخمس:
1) Entry — 99 AED
2) Starter — 299 AED
3) Growth — 599 AED
4) Elite — 1199 AED
5) Diamond — 2399 AED

ممنوع تنسى Diamond في حساب الأرباح أو العمولات أو روابط الدفع.
ممنوع تقول الباقات الثلاث أو الأربع.
"""

    return str(prompt_text).rstrip() + "\n\n" + language_rule.strip() + "\n\n" + diamond_rule.strip() + "\n"

for _fn_name in [
    "build_prompt",
    "build_system_prompt",
    "build_sales_prompt",
    "build_alsaab_prompt",
    "build_project_prompt",
]:
    _old_fn = globals().get(_fn_name)
    if callable(_old_fn) and not getattr(_old_fn, "_alsaab_language_diamond_final_wrapped", False):
        def _make_wrapper(fn):
            def _wrapped(*args, **kwargs):
                state = None
                if len(args) >= 2 and isinstance(args[1], dict):
                    state = args[1]
                elif isinstance(kwargs.get("state"), dict):
                    state = kwargs.get("state")
                return _alsaab_language_and_diamond_final_fix(fn(*args, **kwargs), state)
            _wrapped._alsaab_language_diamond_final_wrapped = True
            return _wrapped
        globals()[_fn_name] = _make_wrapper(_old_fn)
# ===== ALSAAB_LANGUAGE_AND_DIAMOND_FINAL_FIX_V1 END =====
'''

text = text.rstrip() + "\n\n" + block + "\n"
p.write_text(text, encoding="utf-8")

print("LANGUAGE_AND_DIAMOND_FINAL_FIX_OK")
