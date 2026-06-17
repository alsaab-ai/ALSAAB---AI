from pathlib import Path

# Fix database rank aliases
p = Path("backend/database.py")
text = p.read_text(encoding="utf-8")
text = text.replace('"starter partner": "Level 1"', '"starter partner": "Level 2"')
text = text.replace('"growth partner": "Level 2"', '"growth partner": "Level 3"')
text = text.replace('"elite partner": "Level 5"', '"elite partner": "Level 4"')
if '"diamond partner": "Level 5"' not in text:
    text = text.replace('"diamond": "Level 5",', '"diamond": "Level 5",\n        "diamond partner": "Level 5",')
p.write_text(text, encoding="utf-8")

# Fix main dashboard course display amounts
p = Path("backend/main.py")
text = p.read_text(encoding="utf-8")
text = text.replace('╪º┘ä┘à╪¿┘è╪╣╪º╪¬ 99$"', '╪º┘ä┘à╪¿┘è╪╣╪º╪¬ 89$"')
text = text.replace('╪º┘ä╪¬╪║┘è┘è╪▒ 299$"', '╪º┘ä╪¬╪║┘è┘è╪▒ 149$"')
p.write_text(text, encoding="utf-8")
