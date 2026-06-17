from pathlib import Path

files = ["backend/config.py","backend/prompt_builder.py"]

replacements = {
    "1099 درهم إماراتي شهرياً": "599 درهم إماراتي شهرياً",
    "2099 درهم إماراتي شهرياً": "1199 درهم إماراتي شهرياً",
    "النمو بـ 1099 درهم شهرياً": "النمو بـ 599 درهم شهرياً",
    "النخبة بـ 2099 درهم شهرياً": "النخبة بـ 1199 درهم شهرياً",
    "- 1099 درهم شهرياً": "- 599 درهم شهرياً",
    "- 2099 درهم شهرياً": "- 1199 درهم شهرياً",
}

for f in files:
    p = Path(f)
    txt = p.read_text(encoding="utf-8")
    for old,new in replacements.items():
        txt = txt.replace(old,new)
    p.write_text(txt,encoding="utf-8")

print("FINAL_PRICE_FIX_OK")
