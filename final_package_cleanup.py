from pathlib import Path

files = [
    Path("backend/config.py"),
    Path("backend/database.py"),
    Path("backend/main.py"),
    Path("backend/upgrade_routes.py"),
]

for path in files:
    text = path.read_text(encoding="utf-8")
    path.with_suffix(path.suffix + ".bak_final_package_cleanup").write_text(text, encoding="utf-8")

# config.py cleanup
p = Path("backend/config.py")
text = p.read_text(encoding="utf-8")

text = text.replace('"package_amount": "599 AED"', '"package_amount": "299 AED"')
text = text.replace('"package_amount": "1099 AED"', '"package_amount": "599 AED"')
text = text.replace('"package_amount": "2099 AED"', '"package_amount": "1199 AED"')
text = text.replace('_package_order = ["entry", "starter", "growth", "elite"]', '_package_order = ["entry", "starter", "growth", "elite", "diamond"]')

text = text.replace('"title_ar": "Ø´Ø±ÙŠÙƒ Ø§Ù„Ù†Ù…Ùˆ"', '"title_ar": "Starter Partner"')
text = text.replace('"title_ar": "Ø´Ø±ÙŠÙƒ Ø§Ù„Ù…Ø¨ÙŠØ¹Ø§Øª"', '"title_ar": "Growth Partner"')
text = text.replace('"title_ar": "Ø´Ø±ÙŠÙƒ Ø§Ù„Ù‚ÙŠØ§Ø¯Ø©️"', '"title_ar": "Elite Partner"')
text = text.replace('"title_ar": "Ø´Ø±ÙŠÙƒ Ø§Ù„Ù†Ø®️Ø¨Ø©️"', '"title_ar": "Diamond Partner"')
text = text.replace('99$ + Ø¨ÙŠØ¹ 5', '69$ + 5')
text = text.replace('299$ + Ø¥Ø¯Ø®️Ø§Ù„ 20', '89$ + 10')
text = text.replace('1099$ + Ø¥Ø¯Ø®️Ø§Ù„ 50', '149$ + 20')

p.write_text(text, encoding="utf-8")

# database.py cleanup
p = Path("backend/database.py")
text = p.read_text(encoding="utf-8")

text = text.replace('"starter": "Level 1",', '"entry": "Level 1",\n        "entry partner": "Level 1",\n        "starter": "Level 2",')
text = text.replace('"growth": "Level 2",', '"growth": "Level 3",')
text = text.replace('"elite": "Level 5",', '"elite": "Level 4",\n        "diamond": "Level 5",')
text = text.replace('"sales_course_99": "كورس المبيعات 99$"', '"pro_marketer_mindset_69": "كورس عقلية المسوق المحترف 69$"')
text = text.replace('"life_philosophy_workshop_299": "ورشة فلسفة الحياة 299$"', '"sales_skills_89": "كورس مهارات المبيعات 89$"')
text = text.replace('"change_journey_course_1099": "كورس رحلة التغيير 1099$"', '"change_journey_149": "كورس رحلة التغيير 149$"')

p.write_text(text, encoding="utf-8")

# main.py cleanup
p = Path("backend/main.py")
text = p.read_text(encoding="utf-8")

text = text.replace('"package_amount": "1099 AED"', '"package_amount": "599 AED"')
text = text.replace('"course_token": "89"', '"course_token": "89"')
text = text.replace('"course_token": "149"', '"course_token": "149"')
text = text.replace('Sales Skills Course $99', 'Sales Skills Course $89')
text = text.replace('Change Journey Course $299', 'Change Journey Course $149')

# Replace only displayed mojibake amounts near requirements
text = text.replace('99$ + 10', '89$ + 10')
text = text.replace('299$ + 20', '149$ + 20')

p.write_text(text, encoding="utf-8")

# upgrade_routes.py cleanup
p = Path("backend/upgrade_routes.py")
text = p.read_text(encoding="utf-8")

text = text.replace('"starter": "price_1TWEwPJbltD9Bsg8SH2xMao1"', '"starter": "price_1Tj8JmJbltD9Bsg81rMyR7lJ"')
text = text.replace('"growth": "price_1TWFRJJbltD9Bsg8vgUXA1WD"', '"growth": "price_1Tj8MQJbltD9Bsg8XL7xwOYe"')
text = text.replace('"elite": "price_1TWFUhJbltD9Bsg848phcf6P"', '"elite": "price_1Tj8OwJbltD9Bsg8h7DCVKbY",\n    "diamond": "price_1Tj8T7JbltD9Bsg8bdi7XyiL"')

text = text.replace('UPGRADE_PLAN_ORDER = ["entry", "starter", "growth", "elite"]', 'UPGRADE_PLAN_ORDER = ["entry", "starter", "growth", "elite", "diamond"]')

text = text.replace('<option value="elite">Ø§Ù„Ù†Ø®️Ø¨Ø©️ / Elite</option>', '<option value="elite">Ø§Ù„Ù†Ø®️Ø¨Ø©️ / Elite</option>\n      <option value="diamond">Ø§Ù„Ù…Ø§Ø³ÙŠØ©️ / Diamond</option>')

text = text.replace('<option value="starter">Ø§Ù„Ø¨Ø¯Ø§ÙŠØ©️ / Starter â€” 599 AED</option>', '<option value="starter">Ø§Ù„Ø¨Ø¯Ø§ÙŠØ©️ / Starter — 299 AED</option>')
text = text.replace('<option value="growth">Ø§Ù„Ù†Ù…Ùˆ / Growth â€” 1099 AED</option>', '<option value="growth">Ø§Ù„Ù†Ù…Ùˆ / Growth — 599 AED</option>')
text = text.replace('<option value="elite">Ø§Ù„Ù†Ø®️Ø¨Ø©️ / Elite â€” 2099 AED</option>', '<option value="elite">Ø§Ù„Ù†Ø®️Ø¨Ø©️ / Elite — 1199 AED</option>\n      <option value="diamond">Ø§Ù„Ù…Ø§Ø³ÙŠØ©️ / Diamond — 2399 AED</option>')

p.write_text(text, encoding="utf-8")
