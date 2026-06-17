from pathlib import Path

for file in ["backend/config.py", "backend/prompt_builder.py"]:
    p = Path(file)
    text = p.read_text(encoding="utf-8")

    text = text.replace("1099 Ø¯Ø±Ù‡Ù… Ø¥Ù…Ø§Ø±Ø§ØªÙŠ Ø´Ù‡Ø±ÙŠØ§Ù‹", "599 Ø¯Ø±Ù‡Ù… Ø¥Ù…Ø§Ø±Ø§ØªÙŠ Ø´Ù‡Ø±ÙŠØ§Ù‹")
    text = text.replace("2099 Ø¯Ø±Ù‡Ù… Ø¥Ù…Ø§Ø±Ø§ØªÙŠ Ø´Ù‡Ø±ÙŠØ§Ù‹", "1199 Ø¯Ø±Ù‡Ù… Ø¥Ù…Ø§Ø±Ø§ØªÙŠ Ø´Ù‡Ø±ÙŠØ§Ù‹")
    text = text.replace("1099 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹", "599 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹")
    text = text.replace("2099 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹", "1199 Ø¯Ø±Ù‡Ù… Ø´Ù‡Ø±ÙŠØ§Ù‹")
    text = text.replace("Ø§Ù„Ø¨Ø¯Ø§ÙŠØ©️ Ø¨Ù€ 599", "Ø§Ù„Ø¨Ø¯Ø§ÙŠØ©️ Ø¨Ù€ 299")
    text = text.replace("Ø§Ù„Ù†Ù…Ùˆ Ø¨Ù€ 1099", "Ø§Ù„Ù†Ù…Ùˆ Ø¨Ù€ 599")
    text = text.replace("Ø§Ù„Ù†Ø®️Ø¨Ø©️ Ø¨Ù€ 2099", "Ø§Ù„Ù†Ø®️Ø¨Ø©️ Ø¨Ù€ 1199")

    p.write_text(text, encoding="utf-8")
