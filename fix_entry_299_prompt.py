from pathlib import Path

p = Path("backend/prompt_builder.py")
text = p.read_text(encoding="utf-8")
p.with_suffix(".py.bak_fix_entry_wrong_price_299").write_text(text, encoding="utf-8")

text = text.replace("- السعر: 299 درهم شهرياً", "- السعر: 99 درهم شهرياً")
text = text.replace("باقة الدخول** — 299 درهم", "باقة الدخول** — 99 درهم")
text = text.replace("باقة الدخول — 299 درهم", "باقة الدخول — 99 درهم")
text = text.replace("Entry 299", "Entry old-price")

p.write_text(text, encoding="utf-8")
print("ENTRY_299_PROMPT_FIXED")
