from pathlib import Path

files = [
    Path("backend/prompt_builder.py"),
    Path("backend/config.py"),
]

repls = {
    "599 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹": "299 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹",
    "1099 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹": "599 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹",
    "2099 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹": "1199 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹",
    "Ø§Ù„Ø¨Ø¯Ø§ÙŠØ©️ Ø¨Ù€ 599": "Ø§Ù„Ø¨Ø¯Ø§ÙŠØ©️ Ø¨Ù€ 299",
    "Ø§Ù„Ù†Ù…Ùˆ Ø¨Ù€ 1099": "Ø§Ù„Ù†Ù…Ùˆ Ø¨Ù€ 599",
    "Ø§Ù„Ù†Ø®️Ø¨Ø©️ Ø¨Ù€ 2099": "Ø§Ù„Ù†Ø®️Ø¨Ø©️ Ø¨Ù€ 1199",
    "Entry 299": "Entry old-price",
    "Starter 599": "Starter old-price",
    "Growth 1099": "Growth old-price",
    "Elite 2099": "Elite old-price",
}

for p in files:
    text = p.read_text(encoding="utf-8")
    p.with_suffix(p.suffix + ".bak_old_price_final").write_text(text, encoding="utf-8")
    for old, new in repls.items():
        text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")
