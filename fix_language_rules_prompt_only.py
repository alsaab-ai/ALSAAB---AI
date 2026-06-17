from pathlib import Path

p = Path("backend/prompt_builder.py")
text = p.read_text(encoding="utf-8")
p.with_suffix(".py.bak_language_reply_rules").write_text(text, encoding="utf-8")

block = '''
# ===== ALSAAB_REPLY_LANGUAGE_RULES_V1 START =====
ALSAAB_REPLY_LANGUAGE_RULES = """
🌍 قاعدة نهائية للغة الرد واللهجة:

- أهم قاعدة: رد بنفس لغة آخر رسالة من العميل.
- إذا كتب العميل بالإنجليزي، يجب أن يكون الرد بالإنجليزي فقط.
- لا ترد بالعربي على عميل كتب إنجليزي، إلا إذا طلب العربية صراحة.
- إذا كتب العميل بالعربي، رد بالعربي الواضح.
- في الردود العربية، استخدم أسلوب خليجي واضح:
  80% لهجة إماراتية خفيفة وواضحة
  10% مفردات خليجية قريبة من السعودية عند الحاجة
  10% عربية فصحى بسيطة لتوضيح المعنى
- لا تبالغ في العامية، وخلك محترف ومفهوم.
- افهم كل اللهجات العربية قدر الإمكان: الإماراتية، السعودية، الكويتية، القطرية، البحرينية، العمانية، المصرية، الشامية، المغربية وغيرها.
- افهم اللغات الأخرى قدر الإمكان، لكن الرد يكون بلغة العميل الأقرب.
- إذا كانت رسالة العميل مختلطة عربي وإنجليزي، اختَر اللغة الغالبة في آخر رسالة.
- إذا كانت الرسالة الإنجليزية عبارة عن كلمة تقنية فقط داخل سؤال عربي، اعتبر الرد عربي.
"""
def _alsaab_append_reply_language_rules(prompt_text):
    if "ALSAAB_REPLY_LANGUAGE_RULES" in str(prompt_text):
        return prompt_text
    return str(prompt_text).rstrip() + "\\n\\n" + ALSAAB_REPLY_LANGUAGE_RULES.strip() + "\\n"
# ===== ALSAAB_REPLY_LANGUAGE_RULES_V1 END =====
'''

wrap = '''
# ===== ALSAAB_REPLY_LANGUAGE_RULES_WRAP_V1 START =====
for _fn_name in [
    "build_prompt",
    "build_system_prompt",
    "build_sales_prompt",
    "build_alsaab_prompt",
    "build_project_prompt",
]:
    _old_fn = globals().get(_fn_name)
    if callable(_old_fn) and not getattr(_old_fn, "_alsaab_language_rules_wrapped", False):
        def _make_language_wrapper(fn):
            def _wrapped(*args, **kwargs):
                return _alsaab_append_reply_language_rules(fn(*args, **kwargs))
            _wrapped._alsaab_language_rules_wrapped = True
            return _wrapped
        globals()[_fn_name] = _make_language_wrapper(_old_fn)
# ===== ALSAAB_REPLY_LANGUAGE_RULES_WRAP_V1 END =====
'''

if "ALSAAB_REPLY_LANGUAGE_RULES_V1" not in text:
    text = text.rstrip() + "\n\n" + block + "\n"

if "ALSAAB_REPLY_LANGUAGE_RULES_WRAP_V1" not in text:
    text = text.rstrip() + "\n\n" + wrap + "\n"

p.write_text(text, encoding="utf-8")
print("LANGUAGE_RULES_PROMPT_ONLY_OK")
