from pathlib import Path

path = Path("backend/main.py")
text = path.read_text(encoding="utf-8")
path.with_suffix(".py.bak_main_level_ui").write_text(text, encoding="utf-8")

text = text.replace('1: {"rank": "Starter Partner"', '1: {"rank": "Entry Partner"')
text = text.replace('2: {"rank": "Growth Partner"', '2: {"rank": "Starter Partner"')
text = text.replace('3: {"rank": "Sales Partner"', '3: {"rank": "Growth Partner"')
text = text.replace('4: {"rank": "Leader Partner"', '4: {"rank": "Elite Partner"')
text = text.replace('5: {"rank": "Elite Partner"', '5: {"rank": "Diamond Partner"')

text = text.replace('ÙƒÙˆØ±Ø³ Ù…Ù‡Ø§Ø±Ø§Øª Ø§Ù„Ù…Ø¨ÙŠØ¹Ø§Øª 99$', 'ÙƒÙˆØ±Ø³ Ù…Ù‡Ø§Ø±Ø§Øª Ø§Ù„Ù…Ø¨ÙŠØ¹Ø§Øª 89$')
text = text.replace('"course_token": "99"', '"course_token": "89"')
text = text.replace('Sales Skills Course $99', 'Sales Skills Course $89')

text = text.replace('ÙƒÙˆØ±Ø³ Ø±Ø­Ù„Ø©️ Ø§Ù„ØªØºÙŠÙŠØ± 299$', 'ÙƒÙˆØ±Ø³ Ø±Ø­Ù„Ø©️ Ø§Ù„ØªØºÙŠÙŠØ± 149$')
text = text.replace('"course_token": "299"', '"course_token": "149"')
text = text.replace('Change Journey Course $299', 'Change Journey Course $149')

text = text.replace('("starter", "growth", "elite")', '("starter", "growth", "elite", "diamond")')

path.write_text(text, encoding="utf-8")
